'''
evaluate

One harness run = one trial (ML pipeline spec §9): purged walk-forward folds, a model
fitted per fold, a sizer, the cost-aware backtest, metrics per fold and in aggregate,
all logged to the registry, with out-of-fold predictions written to

    data/research/predictions/run=<run_id>/<SYMBOL>.parquet

    ds = load_dataset(research, lake, labels_hash=..., source=..., market=..., symbol="EURJPY")
    res = evaluate(ds, model=LogisticModelConfig(), registry=reg, research=research)
    res.run_id, res.folds (one row per fold), res.aggregate (dict), res.trades

The run is opened before anything is fitted and closed as "failed" if anything raises,
so every attempt counts as a trial. registry=None runs without recording anything:
for tests only, since an unrecorded evaluation still spends a trial.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl

from fxt.research.models import BacktestConfig, ModelConfig, SizerConfig, WalkForwardConfig
from fxt.research.paths import Research
from fxt.research.registry import Registry, RunPurpose
from fxt.research.store import code_version

from .backtest import apply_sizer, simulate, trade_costs
from .dataset import Dataset
from .folds import make_folds, usable_mask, year_span
from .metrics import classifier_metrics, trading_metrics
from .models import fit_predict
from .stats import deflated_sharpe, psr

__all__ = ["EvalResult", "PREDICTION_COLUMNS", "evaluate"]

PREDICTION_COLUMNS = ("event_id", "symbol", "t0", "t1", "fold", "test_year", "side", "outcome", "meta_label",
                      "sample_weight", "prob", "size", "ret", "cost", "gross", "net", "uniqueness",
                      "hours_to_exit")


def _quiet(msg: str) -> None: ...


@dataclass
class EvalResult:
    run_id: str | None
    strategy_id: str
    folds: pl.DataFrame                        # one row per fold: sizes + every metric
    aggregate: dict[str, float]
    trades: pl.DataFrame                       # PREDICTION_COLUMNS, every test event (size 0 = not taken)
    configs: dict[str, str] = field(default_factory=dict)
#


def _metrics(pred: pl.DataFrame, prior: float, start: datetime, end: datetime, bt: BacktestConfig) -> dict[str, float]:
    y = pred.get_column("meta_label").to_numpy()
    p = pred.get_column("prob").to_numpy()
    w = pred.get_column("sample_weight").to_numpy()
    out = {f"clf_{k}": v for k, v in classifier_metrics(y, p, prior, w).items()}
    out.update(trading_metrics(pred, start, end, bt))
    return out


def evaluate(
    ds: Dataset,
    *,
    model: ModelConfig,
    sizer: SizerConfig | None = None,
    backtest: BacktestConfig | None = None,
    cv: WalkForwardConfig | None = None,
    lockbox: bool = False,
    registry: Registry | None,
    research: Research | None = None,
    notes: str | None = None,
    purpose: RunPurpose = "trial",
    log: Callable[[str], None] = _quiet,
) -> EvalResult:
    sizer = sizer or SizerConfig()
    backtest = backtest or BacktestConfig()
    cv = cv or WalkForwardConfig()
    names = list(model.features) if getattr(model, "features", ()) else list(ds.feature_names)
    unknown = set(names) - set(ds.feature_names)
    if unknown:
        raise ValueError(f"model features not in the features config: {sorted(unknown)}")

    clock = ds.bars.get_column("time").dt.epoch("s").to_numpy()
    lock_start = datetime(cv.lockbox_year, 1, 1, tzinfo=UTC)
    frame = ds.frame if lockbox else ds.frame.filter(pl.col("t0") < lock_start)     # dev runs never see the lockbox
    folds = make_folds(frame, clock, cv, lockbox=lockbox)
    first_used = frame.filter(pl.Series(usable_mask(frame, clock, cv))).get_column("t0").min()
    test_end = year_span(folds[-1].test_year)[1]

    configs = {**ds.hashes, "model": model.config_hash(), "sizer": sizer.config_hash(),
               "backtest": backtest.config_hash(), "cv": cv.config_hash()}
    run_id = None
    if registry is not None:
        for c in (model, sizer, backtest, cv):
            registry.register_config(c)
        run_id = registry.start_run(
            ds.strategy_id, [ds.symbol], configs, cv_scheme=cv.scheme,
            data_start=first_used.date().isoformat() if first_used else "", data_end=test_end.date().isoformat(),
            is_lockbox=lockbox, git_commit=code_version(), notes=notes, purpose=purpose)
        log(f"run {run_id}: {ds.strategy_id} / {model.label} / {sizer.label}")

    try:
        costed = trade_costs(frame, ds.bars, backtest, ds.symbol)
        X_all = costed.select(names).to_numpy().astype(float) if names else np.zeros((costed.height, 0))
        y_all = costed.get_column("meta_label").to_numpy()
        w_all = (np.ones(costed.height) if model.sample_weight == "none"
                 else costed.get_column(model.sample_weight).to_numpy().astype(float))

        parts, priors, fold_rows = [], {}, []
        for f in folds:
            if f.n_train == 0 or f.n_test == 0:
                raise ValueError(f"fold {f.index} ({f.test_year}): {f.n_train} train / {f.n_test} test events")
            prob = fit_predict(model, X_all[f.train], y_all[f.train], w_all[f.train], X_all[f.test])
            priors[f.index] = float((w_all[f.train] * y_all[f.train]).sum() / w_all[f.train].sum())
            parts.append(costed.filter(pl.Series(f.test)).with_columns(
                pl.lit(f.index, pl.Int32).alias("fold"), pl.lit(f.test_year, pl.Int32).alias("test_year"),
                pl.Series("prob", prob), pl.Series("size", apply_sizer(prob, sizer)),
                pl.Series("sample_weight", w_all[f.test])))
            fold_rows.append({"fold": f.index, "test_year": f.test_year, "n_train": f.n_train,
                              "n_test": f.n_test, "purged": f.purged, "embargoed": f.embargoed})
            log(f"  fold {f.index} ({f.test_year}): train {f.n_train:,} (purged {f.purged}), test {f.n_test:,}")

        trades = simulate(pl.concat(parts), backtest).select(PREDICTION_COLUMNS)

        for row in fold_rows:
            pred = trades.filter(pl.col("fold") == row["fold"])
            start, end = year_span(row["test_year"])
            row.update(_metrics(pred, priors[row["fold"]], start, end, backtest))
        #! aggregate: classifier vs each event's own fold prior; trading over the whole test span
        prior_all = np.array([priors[i] for i in trades.get_column("fold").to_list()])
        y, p = trades.get_column("meta_label").to_numpy(), trades.get_column("prob").to_numpy()
        w = trades.get_column("sample_weight").to_numpy()
        agg = {f"clf_{k}": v for k, v in classifier_metrics(y, p, 0.5, w).items()}
        agg["clf_log_loss_prior"] = float(-(w * (y * np.log(prior_all) + (1 - y) * np.log(1 - prior_all))).sum()
                                          / w.sum())
        agg["clf_log_loss_skill"] = 1 - agg["clf_log_loss"] / agg["clf_log_loss_prior"]
        #! pooled AUC ranks events across folds, so drift in the base rate between folds leaks in
        #! (take_all scores != 0.5); the headline is the mean of the per-fold AUCs
        agg["clf_auc_pooled"], agg["clf_auc_unweighted_pooled"] = agg["clf_auc"], agg.pop("clf_auc_unweighted")
        agg["clf_auc"] = float(np.mean([r["clf_auc"] for r in fold_rows]))
        agg["clf_auc_unweighted"] = float(np.mean([r["clf_auc_unweighted"] for r in fold_rows]))
        agg.update(trading_metrics(trades, year_span(folds[0].test_year)[0], test_end, backtest))
        #! deflated Sharpe: against the best daily Sharpe expected from this many skill-less trials
        sr, sk, ku, nd = (agg.get(k, math.nan) for k in ("sharpe_daily", "skew_daily", "kurt_daily", "n_days"))
        agg["psr"] = psr(sr, int(nd) if _finite(nd) else 0, sk, ku)
        if registry is not None and purpose == "trial":
            d = deflated_sharpe(sr, int(nd), sk, ku, registry.trial_count(include_lockbox=True),
                                [*registry.trial_metric("sharpe_daily", exclude_run=run_id), sr])
            agg.update({"dsr": d.dsr, "sr0_daily": d.sr0, "n_trials": float(d.n_trials),
                        "var_sr_trials": d.var_sr})
        agg["n_folds"] = float(len(folds))
        agg["folds_net_positive"] = float(sum(r.get("net_bp", 0) > 0 for r in fold_rows))

        if registry is not None and run_id is not None:
            for row in fold_rows:
                registry.log_metrics(run_id, {k: float(v) for k, v in row.items()
                                              if k not in ("fold", "test_year") and _finite(v)}, fold=row["fold"])
            registry.log_metrics(run_id, {k: v for k, v in agg.items() if _finite(v)})
            if research is not None:
                out = research.root / "predictions" / f"run={run_id}" / f"{ds.symbol}.parquet"
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp = out.with_suffix(f".tmp{os.getpid()}")
                trades.write_parquet(tmp)
                tmp.replace(out)
            registry.finish_run(run_id, "done")
    except BaseException:
        if registry is not None and run_id is not None:
            registry.finish_run(run_id, "failed")
        raise

    return EvalResult(run_id=run_id, strategy_id=ds.strategy_id, folds=pl.DataFrame(fold_rows),
                      aggregate=agg, trades=trades, configs=configs)


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)
#-
