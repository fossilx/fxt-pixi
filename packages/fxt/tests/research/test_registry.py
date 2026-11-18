"""
Experiment registry (data/experiments.db): research index, runs, metrics, trials.
"""
from __future__ import annotations

import polars as pl
import pytest

from fxt.research import Research, Stage
from fxt.research.models import ConfigHash, ResearchMeta, StageConfig, SymbolKey, registry
from fxt.research.registry import SCHEMA_VERSION, LockboxAlreadyUsed, Registry
from fxt.research.store import write_table


@registry.register("RegEventsConfig", 1)
class EvCfg(StageConfig):
    stage = Stage.EVENTS
    h: float = 3.0


@registry.register("RegWeightsConfig", 1)
class WtCfg(StageConfig):
    stage = Stage.WEIGHTS
    events_hash: ConfigHash


@registry.register("RegMeta", 1)
class Meta(ResearchMeta):
    pass


def put(rs: Research, cfg: StageConfig, *, year: int | None = 2020, symbol: str = "EURJPY", rows: int = 3):
    ds = SymbolKey(source="dukascopy", market="forex", symbol=symbol)
    df = pl.DataFrame({"x": list(range(rows))})
    return write_table(df, Meta.for_config(cfg, dataset=ds, year=year, rows=rows), research=rs)


@pytest.fixture
def rs(tmp_path) -> Research:
    return Research(root=tmp_path / "research")


@pytest.fixture
def reg(tmp_path):
    with Registry(tmp_path / "experiments.db") as r:
        yield r


def run(reg: Registry, strategy: str = "s1", **kw) -> str:
    return reg.start_run(strategy, ["EURJPY"], {"labels": "a" * 12}, cv_scheme="walk_forward_purged",
                         data_start="2012-01-01", data_end="2023-12-31", **kw)


def test_init_is_idempotent_and_wal(tmp_path):
    p = tmp_path / "sub" / "experiments.db"
    Registry(p).close()
    with Registry(p) as r:
        assert r.con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert r.con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_newer_schema_refused(tmp_path):
    p = tmp_path / "experiments.db"
    with Registry(p) as r:
        r.con.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="schema"):
        Registry(p)


def test_sync_indexes_configs_lineage_artifacts(rs, reg):
    ev = EvCfg()
    put(rs, ev, year=2020)
    put(rs, ev, year=2021, rows=5)
    wt = WtCfg(events_hash=ev.config_hash())
    put(rs, wt, year=None)

    rep = reg.sync(rs)
    assert (rep.configs_added, rep.artifacts_added, rep.artifacts_seen, rep.artifacts_missing) == (2, 3, 3, 0)
    assert not rep.problems

    c = reg.config(wt.config_hash())
    assert c["stage"] == "weights" and c["model_type"] == "RegWeightsConfig" and c["model_version"] == "1"
    assert c["inputs"] == {"events": ev.config_hash()}
    assert c["config"] == wt.payload()

    arts = reg.query("SELECT * FROM artifacts ORDER BY path")
    assert arts.height == 3
    assert set(arts["year"].to_list()) == {2020, 2021, None}
    assert arts.filter(pl.col("year") == 2021)["rows"].item() == 5
    assert arts["present"].to_list() == [1, 1, 1]
    assert all(not p.startswith("/") for p in arts["path"])        # relative to data/research

    #! second sync: nothing new
    rep = reg.sync(rs)
    assert (rep.configs_added, rep.artifacts_added, rep.artifacts_seen) == (0, 0, 3)


def test_sync_marks_missing_and_restores(rs, reg):
    ev = EvCfg()
    p20 = put(rs, ev, year=2020)
    put(rs, ev, year=2021)
    reg.sync(rs)
    p20.unlink()
    rep = reg.sync(rs)
    assert rep.artifacts_missing == 1
    gone = reg.query("SELECT year FROM artifacts WHERE present = 0")
    assert gone["year"].to_list() == [2020]
    #! the config row survives: runs may refer to it
    assert reg.config(ev.config_hash()) is not None
    put(rs, ev, year=2020)
    assert reg.sync(rs).artifacts_missing == 0


def test_sync_reports_unreadable_files(rs, reg):
    put(rs, EvCfg(), year=2020)
    good = put(rs, EvCfg(), year=2021)
    bad = good.parent.parent.parent / "symbol=GBPUSD" / "year=2021" / "GBPUSD-2021.parquet"
    bad.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"x": [1]}).write_parquet(bad)                     # no research metadata
    rep = reg.sync(rs)
    assert rep.artifacts_seen == 2
    assert len(rep.problems) == 1 and "GBPUSD-2021" in rep.problems[0]


def test_register_config_without_files(reg):
    ev = EvCfg(h=2.0)
    h = reg.register_config(ev)
    assert h == ev.config_hash()
    assert reg.register_config(ev) == h                             # idempotent
    assert reg.query("SELECT COUNT(*) AS n FROM configs")["n"].item() == 1


def test_run_lifecycle_and_metrics(reg):
    r = run(reg, notes="first")
    assert reg.runs()["status"].to_list() == ["running"]
    assert reg.run_configs(r) == {"labels": "a" * 12}
    reg.log_metrics(r, {"auc": 0.51, "sharpe": 0.2}, fold=0)
    reg.log_metrics(r, {"auc": 0.53}, fold=1)
    reg.log_metric(r, "auc", 0.52)                                  # aggregate
    reg.log_metric(r, "auc", 0.525)                                 # overwrite aggregate, not a duplicate
    reg.log_metric(r, "auc", 0.515, fold=0)                         # overwrite fold 0
    m = reg.metrics(r)
    assert m.height == 4
    assert m.filter(pl.col("fold").is_null())["value"].item() == 0.525
    assert m.filter((pl.col("fold") == 0) & (pl.col("name") == "auc"))["value"].item() == 0.515
    reg.finish_run(r, "done")
    row = reg.runs().row(0, named=True)
    assert row["status"] == "done" and row["finished_at"] is not None
    with pytest.raises(ValueError):
        reg.finish_run(r, "running")
    with pytest.raises(KeyError):
        reg.finish_run("nope", "done")


def test_metric_uniqueness_enforced_by_index(reg):
    import sqlite3
    r = run(reg)
    reg.log_metric(r, "auc", 0.5)
    with pytest.raises(sqlite3.IntegrityError):
        reg.con.execute("INSERT INTO metrics VALUES (?, NULL, 'auc', 0.6)", (r,))


def test_trial_count_includes_failures(reg):
    a = run(reg, "s1")
    b = run(reg, "s1")
    run(reg, "s1")
    run(reg, "s2")
    reg.finish_run(a, "done")
    reg.finish_run(b, "failed")
    assert reg.trial_count("s1") == 3
    assert reg.trial_count("s2") == 1
    assert reg.trial_count() == 4


def test_lockbox_one_look(reg):
    lb = run(reg, "s1", is_lockbox=True)
    reg.finish_run(lb, "failed")                                     # even a failed look counts
    with pytest.raises(LockboxAlreadyUsed, match=lb):
        run(reg, "s1", is_lockbox=True)
    run(reg, "s2", is_lockbox=True)                                  # other strategy: fine
    assert reg.trial_count("s1") == 0
    assert reg.trial_count("s1", include_lockbox=True) == 1


def test_get_registry_uses_settings_path(tmp_path, monkeypatch):
    from fxt import services
    from fxt.research.registry import Registry as R
    monkeypatch.setattr(services, "get_settings", lambda: type("S", (), {
        "paths": type("P", (), {"experiments": tmp_path / "x.db"})()})())
    with services.get_registry() as r:
        assert isinstance(r, R) and r.path == tmp_path / "x.db"
