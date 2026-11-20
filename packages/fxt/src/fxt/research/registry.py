'''
registry

The experiment registry: data/experiments.db (SQLite, WAL), ML pipeline spec §10.

Two halves:
- configs / config_inputs / artifacts: an index of data/research, filled by
  sync() from the files' own metadata. Rebuildable at any time: the files
  are the source of truth.
- runs / run_configs / metrics: one row per evaluation through the harness.
  These exist nowhere else, which is why the registry lives outside
  data/research and must never be deleted with research outputs. Every trial
  run counts (failed and abandoned ones too) for the deflated Sharpe, except that
  runs making exactly the same trades (runs.trades_hash) count once; baselines are
  recorded with purpose="control" and don't count.

    with Registry("data/experiments.db") as reg:
        reg.sync(research)                                   # index data/research
        run = reg.start_run("cusum_h3_follow", ["EURJPY"], {"labels": "3b896dab2027", ...},
                            cv_scheme="walk_forward_purged", data_start="2012-01-01", data_end="2023-12-31")
        reg.log_metrics(run, {"auc": 0.53}, fold=3)
        reg.finish_run(run, "done")
        reg.trial_count("cusum_h3_follow")

Lockbox rule (spec §9.1): one look per strategy. start_run(is_lockbox=True) raises
LockboxAlreadyUsed if that strategy already has a lockbox run, whatever its status.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

import polars as pl

from .models import HashedConfig
from .paths import Research, Stage

__all__ = ["LockboxAlreadyUsed", "Registry", "RunPurpose", "SCHEMA_VERSION", "SyncReport"]

SCHEMA_VERSION = 3
RunPurpose = Literal["trial", "control"]
RunStatus = Literal["running", "done", "failed", "abandoned"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS configs (
    config_hash   TEXT PRIMARY KEY,
    stage         TEXT NOT NULL,            -- features, events, touches, labels, weights, model, ...
    model_type    TEXT NOT NULL,            -- registered config class name
    model_version TEXT NOT NULL,
    config_json   TEXT NOT NULL,            -- the hashed payload
    first_seen    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_inputs (  -- lineage: which upstream configs a config consumed
    config_hash   TEXT NOT NULL REFERENCES configs,
    role          TEXT NOT NULL,            -- e.g. events, touches, labels
    input_hash    TEXT NOT NULL,
    PRIMARY KEY (config_hash, role)
);
CREATE TABLE IF NOT EXISTS artifacts (      -- where a config's output lives (path relative to data/research)
    config_hash   TEXT NOT NULL REFERENCES configs,
    path          TEXT NOT NULL,
    source        TEXT, market TEXT, symbol TEXT,
    year          INTEGER,
    rows          INTEGER NOT NULL,
    passed        INTEGER NOT NULL,         -- all of the file's checks passed
    code_version  TEXT,
    created_at    TEXT NOT NULL,            -- from the file's metadata
    present       INTEGER NOT NULL DEFAULT 1,  -- 0 once a sync no longer finds the file
    last_seen     TEXT NOT NULL,
    PRIMARY KEY (config_hash, path)
);
CREATE TABLE IF NOT EXISTS runs (           -- one evaluation through the harness = one trial
    run_id        TEXT PRIMARY KEY,
    strategy_id   TEXT NOT NULL,
    symbols       TEXT NOT NULL,            -- JSON list
    cv_scheme     TEXT NOT NULL,            -- e.g. walk_forward_purged
    data_start    TEXT NOT NULL,
    data_end      TEXT NOT NULL,
    is_lockbox    INTEGER NOT NULL DEFAULT 0,
    git_commit    TEXT,
    status        TEXT NOT NULL,            -- running, done, failed, abandoned
    notes         TEXT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    purpose       TEXT NOT NULL DEFAULT 'trial',  -- trial (counts toward multiple testing) or control (a baseline)
    trades_hash   TEXT                            -- hash of the trades the run made: identical trades = one trial
);
CREATE TABLE IF NOT EXISTS run_configs (    -- every config a run used, by role
    run_id        TEXT NOT NULL REFERENCES runs,
    role          TEXT NOT NULL,            -- e.g. features, labels, weights, model, sizer, backtest
    config_hash   TEXT NOT NULL,
    PRIMARY KEY (run_id, role)
);
CREATE TABLE IF NOT EXISTS metrics (
    run_id        TEXT NOT NULL REFERENCES runs,
    fold          INTEGER,                  -- NULL = aggregate across folds
    name          TEXT NOT NULL,
    value         REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS metrics_key ON metrics (run_id, IFNULL(fold, -1), name);
CREATE INDEX IF NOT EXISTS runs_strategy ON runs (strategy_id);
CREATE INDEX IF NOT EXISTS artifacts_symbol ON artifacts (symbol);
"""


class LockboxAlreadyUsed(RuntimeError):
    """ The strategy already had its one look at the lockbox. """


@dataclass
class SyncReport:
    configs_added: int = 0
    artifacts_added: int = 0
    artifacts_seen: int = 0
    artifacts_missing: int = 0                 # in the registry, no longer on disk
    problems: list[str] = field(default_factory=list)
#


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
#


class Registry:
    """ The experiment registry. Opens (and creates/migrates) the database on construction. """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path, timeout=30, isolation_level=None)   # autocommit; explicit txns
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA foreign_keys=ON")
        self._init()

    def _init(self) -> None:
        version = self.con.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"{self.path} has schema v{version}; this code knows v{SCHEMA_VERSION}")
        self.con.executescript(_SCHEMA)
        cols = {r["name"] for r in self.con.execute("PRAGMA table_info(runs)")}
        if 0 < version < 2 and "purpose" not in cols:                # v1 -> v2: runs.purpose
            self.con.execute("ALTER TABLE runs ADD COLUMN purpose TEXT NOT NULL DEFAULT 'trial'")
        if 0 < version < 3 and "trades_hash" not in cols:            # v2 -> v3: runs.trades_hash
            self.con.execute("ALTER TABLE runs ADD COLUMN trades_hash TEXT")
        self.con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    #~======================================================================(70)
    #~ configs
    #~----------------------------------------------------------------------(70)
    def _upsert_config(self, config_hash: str, stage: str, typeid: str, payload: dict,
                       input_hashes: dict[str, str]) -> bool:
        name, _, version = typeid.rpartition("@")
        cur = self.con.execute(
            "INSERT OR IGNORE INTO configs VALUES (?, ?, ?, ?, ?, ?)",
            (config_hash, stage, name, version, json.dumps(payload, sort_keys=True), _now()))
        for role, h in input_hashes.items():
            self.con.execute("INSERT OR IGNORE INTO config_inputs VALUES (?, ?, ?)", (config_hash, role, h))
        return cur.rowcount > 0

    def register_config(self, config: HashedConfig) -> str:
        """ Record a config (e.g. a model or backtest config that writes no research file). """
        h = config.config_hash()
        self._upsert_config(h, config.config_kind(), config.get_id(), config.payload(), config.input_hashes())
        return h

    def config(self, config_hash: str) -> dict[str, Any] | None:
        row = self.con.execute("SELECT * FROM configs WHERE config_hash = ?", (config_hash,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["config"] = json.loads(out.pop("config_json"))
        out["inputs"] = {r["role"]: r["input_hash"] for r in self.con.execute(
            "SELECT role, input_hash FROM config_inputs WHERE config_hash = ?", (config_hash,))}
        return out

    #~======================================================================(70)
    #~ sync from data/research
    #~----------------------------------------------------------------------(70)
    def sync(self, research: Research) -> SyncReport:
        """ Index every research file: configs, lineage, artifacts. Files no longer on disk are
            marked present=0 (their rows stay: runs may refer to them). Idempotent.
        """
        from .store import read_meta
        rep = SyncReport()
        now = _now()
        seen: set[tuple[str, str]] = set()
        self.con.execute("BEGIN")
        try:
            known = {(r[0], r[1]) for r in self.con.execute("SELECT config_hash, path FROM artifacts")}
            for stage in Stage:
                for _, p in research.scan(stage):
                    rel = p.relative_to(research.root).as_posix()
                    try:
                        m = read_meta(p)
                    except Exception as e:
                        msg = str(e).splitlines()[0] if str(e) else ""
                        rep.problems.append(f"{rel}: {e.__class__.__name__}: {msg}")
                        continue
                    if self._upsert_config(m.config_hash, str(m.stage), m.config_typeid, m.config, m.input_hashes):
                        rep.configs_added += 1
                    self.con.execute("""
                        INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                        ON CONFLICT (config_hash, path) DO UPDATE SET
                            rows=excluded.rows, passed=excluded.passed, code_version=excluded.code_version,
                            created_at=excluded.created_at, present=1, last_seen=excluded.last_seen
                        """, (m.config_hash, rel, m.dataset.source, m.dataset.market, m.dataset.symbol, m.year,
                              m.rows, int(m.passed), m.code_version, m.created_at.isoformat(), now))
                    seen.add((m.config_hash, rel))
            rep.artifacts_seen = len(seen)
            rep.artifacts_added = len(seen - known)
            for key in known - seen:
                self.con.execute("UPDATE artifacts SET present = 0 WHERE config_hash = ? AND path = ?", key)
            rep.artifacts_missing = self.con.execute("SELECT COUNT(*) FROM artifacts WHERE present = 0").fetchone()[0]
            self.con.execute("COMMIT")
        except BaseException:
            self.con.execute("ROLLBACK")
            raise
        return rep

    #~======================================================================(70)
    #~ runs
    #~----------------------------------------------------------------------(70)
    def start_run(
        self,
        strategy_id: str,
        symbols: list[str],
        configs: dict[str, str],
        *,
        cv_scheme: str,
        data_start: str,
        data_end: str,
        is_lockbox: bool = False,
        git_commit: str | None = None,
        notes: str | None = None,
        purpose: RunPurpose = "trial",
    ) -> str:
        """ Open a run (status 'running'). `configs` = {role: config_hash} for everything it uses.
            purpose="control" marks a baseline (e.g. random entry): recorded, never counted as a trial.
        """
        if purpose not in ("trial", "control"):
            raise ValueError(f"purpose must be 'trial' or 'control', got {purpose!r}")
        if is_lockbox and purpose != "trial":
            raise ValueError("a lockbox run is always a trial")
        if is_lockbox:
            prev = self.con.execute(
                "SELECT run_id, status, started_at FROM runs WHERE strategy_id = ? AND is_lockbox = 1",
                (strategy_id,)).fetchone()
            if prev is not None:
                raise LockboxAlreadyUsed(
                    f"{strategy_id} already looked at the lockbox: run {prev['run_id']} "
                    f"({prev['status']}, {prev['started_at']}). One look only (spec §9.1).")
        run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"
        self.con.execute("BEGIN")
        try:
            self.con.execute(
                "INSERT INTO runs (run_id, strategy_id, symbols, cv_scheme, data_start, data_end, is_lockbox, "
                "git_commit, status, notes, started_at, purpose) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)",
                (run_id, strategy_id, json.dumps(list(symbols)), cv_scheme, data_start, data_end,
                 int(is_lockbox), git_commit, notes, _now(), purpose))
            for role, h in configs.items():
                self.con.execute("INSERT INTO run_configs VALUES (?, ?, ?)", (run_id, role, h))
            self.con.execute("COMMIT")
        except BaseException:
            self.con.execute("ROLLBACK")
            raise
        return run_id

    def log_metric(self, run_id: str, name: str, value: float, fold: int | None = None) -> None:
        """ Record (or overwrite) one metric; fold None = aggregate across folds. """
        self.con.execute("DELETE FROM metrics WHERE run_id = ? AND IFNULL(fold, -1) = IFNULL(?, -1) AND name = ?",
                         (run_id, fold, name))
        self.con.execute("INSERT INTO metrics VALUES (?, ?, ?, ?)", (run_id, fold, name, float(value)))

    def log_metrics(self, run_id: str, values: dict[str, float], fold: int | None = None) -> None:
        self.con.execute("BEGIN")
        try:
            for name, v in values.items():
                self.log_metric(run_id, name, v, fold)
            self.con.execute("COMMIT")
        except BaseException:
            self.con.execute("ROLLBACK")
            raise

    def finish_run(self, run_id: str, status: RunStatus = "done") -> None:
        if status == "running":
            raise ValueError("finish_run needs a final status")
        n = self.con.execute("UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ?",
                             (status, _now(), run_id)).rowcount
        if n == 0:
            raise KeyError(f"no run {run_id}")

    #~======================================================================(70)
    #~ queries
    #~----------------------------------------------------------------------(70)
    def set_trades_hash(self, run_id: str, trades_hash: str) -> None:
        """ Record what the run traded (see fxt.research.harness.trades_hash). """
        if self.con.execute("UPDATE runs SET trades_hash = ? WHERE run_id = ?", (trades_hash, run_id)).rowcount == 0:
            raise KeyError(f"no run {run_id}")

    def trial_count(self, strategy_id: str | None = None, *, include_lockbox: bool = False,
                    distinct: bool = True) -> int:
        """ Trials for multiple testing (spec §9.6): every trial run counts, failed and abandoned
            included; controls don't. distinct=True (default): runs that made exactly the same
            trades (same trades_hash) count once; runs without a hash (failed, or recorded before
            v3 and not backfilled) count one each. distinct=False: every run.
        """
        what = "COUNT(DISTINCT COALESCE(trades_hash, run_id))" if distinct else "COUNT(*)"
        sql = f"SELECT {what} FROM runs WHERE purpose = 'trial' AND (? IS NULL OR strategy_id = ?)"
        if not include_lockbox:
            sql += " AND is_lockbox = 0"
        return self.con.execute(sql, (strategy_id, strategy_id)).fetchone()[0]

    def trial_metric(self, name: str, *, exclude_run: str | None = None,
                     exclude_trades: str | None = None) -> list[float]:
        """ The aggregate value of metric `name` for every finished trial (not lockbox, not
            control), one value per distinct trade set, e.g. every trial's daily Sharpe for the
            deflated Sharpe ratio. exclude_run / exclude_trades leave out a run and any run that
            made the same trades.
        """
        rows = self.con.execute("""
            SELECT MIN(m.value) FROM metrics m JOIN runs r USING (run_id)
            WHERE m.name = ? AND m.fold IS NULL AND r.purpose = 'trial' AND r.is_lockbox = 0
              AND r.status = 'done' AND r.run_id IS NOT ?
              AND (r.trades_hash IS NULL OR r.trades_hash IS NOT ?)
            GROUP BY COALESCE(r.trades_hash, r.run_id)""", (name, exclude_run, exclude_trades)).fetchall()
        return [r[0] for r in rows]

    def query(self, sql: str, params: tuple | dict = ()) -> pl.DataFrame:
        cur = self.con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return pl.DataFrame([tuple(r) for r in cur.fetchall()], schema=cols, orient="row")

    def runs(self, strategy_id: str | None = None) -> pl.DataFrame:
        return self.query("SELECT * FROM runs WHERE (? IS NULL OR strategy_id = ?) ORDER BY started_at",
                          (strategy_id, strategy_id))

    def run_configs(self, run_id: str) -> dict[str, str]:
        return {r["role"]: r["config_hash"] for r in self.con.execute(
            "SELECT role, config_hash FROM run_configs WHERE run_id = ?", (run_id,))}

    def metrics(self, run_id: str) -> pl.DataFrame:
        return self.query("SELECT fold, name, value FROM metrics WHERE run_id = ? ORDER BY fold NULLS LAST, name",
                          (run_id,))
#-
