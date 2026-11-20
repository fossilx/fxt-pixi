'''
report

Breakdowns of a finished run from its own out-of-fold predictions
(data/research/predictions/run=<run_id>/*.parquet). Reading predictions back fits
nothing, so a report is not a new trial (spec §9.6).

    pred = load_predictions(research, run_id)
    by = breakdown(pred, backtest)            # one row per (symbol, test_year), plus "all" rows
    save_breakdown(registry, run_id, by)      # per-fold metrics "<SYMBOL>.<metric>" in the registry
    trades_hash(pred, labels_hash, backtest_hash)   # what a run traded: identical trades = one trial
    backfill_trades_hashes(registry, research)      # for runs recorded before trades_hash existed
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import hashlib
import math

import polars as pl

from fxt.research.models import BacktestConfig
from fxt.research.paths import Research
from fxt.research.registry import Registry

from .folds import year_span
from .metrics import auc, trading_metrics

__all__ = ["BREAKDOWN_METRICS", "backfill_trades_hashes", "breakdown", "load_predictions", "save_breakdown",
           "trades_hash"]

BREAKDOWN_METRICS = ("n_events", "n_trades", "gross_bp", "cost_bp", "net_bp", "hit_rate", "sharpe_ann", "dir_auc")


def load_predictions(research: Research, run_id: str) -> pl.DataFrame:
    folder = research.root / "predictions" / f"run={run_id}"
    files = sorted(folder.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no predictions for run {run_id} in {folder}")
    return pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed")


def _dir_auc(p: pl.DataFrame) -> float:
    s = p.filter(pl.col("outcome").is_in(["pt", "sl"]))
    score = "score" if "score" in s.columns else "prob"
    return auc((s.get_column("outcome") == "pt").to_numpy().astype(float), s.get_column(score).to_numpy()) \
        if s.height else math.nan


def _row(p: pl.DataFrame, start, end, bt: BacktestConfig) -> dict:
    m = trading_metrics(p, start, end, bt)
    return {"n_events": p.height, **{k: m.get(k, math.nan) for k in BREAKDOWN_METRICS[1:-1]}, "dir_auc": _dir_auc(p)}


def breakdown(pred: pl.DataFrame, backtest: BacktestConfig | None = None) -> pl.DataFrame:
    """ symbol x test_year (fold) rows, plus per-symbol "all" rows (test_year = None) and
        "ALL" symbol rows per year. bp figures are per unit of size; Sharpe on daily P&L;
        the "all" rows' dir_auc is the mean of the yearly values, as in evaluate.
    """
    bt = backtest or BacktestConfig()
    years = sorted(pred.get_column("test_year").unique().to_list())
    first, last = year_span(years[0])[0], year_span(years[-1])[1]
    rows = []
    for sym in [*sorted(pred.get_column("symbol").unique().to_list()), "ALL"]:
        ps = pred if sym == "ALL" else pred.filter(pl.col("symbol") == sym)
        for y in years:
            py = ps.filter(pl.col("test_year") == y)
            fold = int(py.get_column("fold")[0]) if py.height else None
            rows.append({"symbol": sym, "test_year": y, "fold": fold, **_row(py, *year_span(y), bt)})
        total = {"symbol": sym, "test_year": None, "fold": None, **_row(ps, first, last, bt)}
        #! like evaluate: the all-years AUC is the mean of the per-year ones (pooling across folds
        #! mixes fold-to-fold drift into the ranking)
        per_year = [r["dir_auc"] for r in rows[-len(years):] if r["dir_auc"] == r["dir_auc"]]
        total["dir_auc"] = sum(per_year) / len(per_year) if per_year else math.nan
        rows.append(total)
    return pl.DataFrame(rows)


def trades_hash(pred: pl.DataFrame, labels_hash: str, backtest_hash: str) -> str:
    """ 16-hex hash of what a run traded: the labels config (events, barriers, side rule),
        the backtest config (costs, cap) and every (event_id, size) with size > 0. Two runs
        with the same hash made identical trades with identical results, so for multiple
        testing they're one trial (spec §9.6).
    """
    t = (pred.filter(pl.col("size") > 0).select("event_id", pl.col("size").round(9))
             .sort("event_id"))
    h = hashlib.sha256(f"{labels_hash}|{backtest_hash}|".encode())
    for eid, size in t.iter_rows():
        h.update(f"{eid}:{size!r};".encode())
    return h.hexdigest()[:16]


def backfill_trades_hashes(reg: Registry, research: Research) -> dict[str, str]:
    """ trades_hash for finished runs that don't have one, from their predictions on disk.
        Runs without predictions (or without a labels / backtest config) are left alone and
        keep counting as one trial each. Returns {run_id: hash} for the runs filled in.
    """
    out = {}
    for (run_id,) in reg.con.execute(
            "SELECT run_id FROM runs WHERE status = 'done' AND trades_hash IS NULL ORDER BY started_at").fetchall():
        cfg = reg.run_configs(run_id)
        if "labels" not in cfg or "backtest" not in cfg:
            continue
        try:
            pred = load_predictions(research, run_id)
        except FileNotFoundError:
            continue
        h = trades_hash(pred, cfg["labels"], cfg["backtest"])
        reg.set_trades_hash(run_id, h)
        out[run_id] = h
    return out


def save_breakdown(reg: Registry, run_id: str, by: pl.DataFrame) -> int:
    """ Store per-symbol per-fold rows as fold metrics "<SYMBOL>.<metric>" (overwrites). """
    n = 0
    for r in by.filter((pl.col("symbol") != "ALL") & pl.col("fold").is_not_null()).iter_rows(named=True):
        vals = {f"{r['symbol']}.{k}": float(r[k]) for k in BREAKDOWN_METRICS
                if r[k] is not None and math.isfinite(r[k])}
        reg.log_metrics(run_id, vals, fold=r["fold"])
        n += len(vals)
    return n
#-
