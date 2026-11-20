'''
evaluate

One harness run = one trial (ML pipeline spec §9): purged walk-forward folds, a model
fitted per fold, a sizer, the cost-aware backtest, metrics per fold and in aggregate,
all logged to the registry, with out-of-fold predictions written to

    data/research/predictions/run=<run_id>/<SYMBOL>.parquet       (one file per symbol)

    ds = load_dataset(research, lake, labels_hash=..., source=..., market=..., symbol="EURJPY")
    res = evaluate(ds, model=LogisticModelConfig(), registry=reg, research=research)
    res.run_id, res.folds (one row per fold), res.aggregate (dict), res.trades

Pooled (spec §9.7): pass one Dataset per symbol, all built from the same configs.
One model is fitted per fold on every symbol's training events; folds, purging and
the start-of-data drop are applied per symbol on its own business clock, so the test
years are the same for every pair. With more than one symbol the model also gets one
0/1 column per symbol after the first (alphabetical), named "symbol=<SYMBOL>". Costs
use each pair's own quotes and pip size. Aggregate metrics are also logged per
symbol as "<SYMBOL>.<metric>", both overall and per fold.

    res = evaluate([ds_eurjpy, ds_eurusd, ds_usdjpy], model=GBMMulticlassModelConfig(), ...)

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

from fxt.research.models import OUTCOME_CLASSES, BacktestConfig, ModelConfig, SizerConfig, WalkForwardConfig
from fxt.research.paths import Research
from fxt.research.registry import Registry, RunPurpose
from fxt.research.store import code_version

from .backtest import apply_sizer, simulate, trade_costs
from .dataset import Dataset
from .folds import Fold, make_folds, usable_mask, year_span
from .metrics import classifier_metrics, trading_metrics
from .metrics import auc
from .models import fold_predict, is_multiclass, model_inputs
from .report import trades_hash
from .stats import deflated_sharpe, psr

__all__ = ["EvalResult", "PER_SYMBOL_METRICS", "PREDICTION_COLUMNS", "evaluate"]

#! aggregate metrics also logged per symbol ("<SYMBOL>.<name>") in pooled runs
PER_SYMBOL_METRICS = ("n_trades", "gross_bp", "cost_bp", "net_bp", "hit_rate", "sharpe_ann", "clf_auc", "dir_auc")

PREDICTION_COLUMNS = ("event_id", "symbol", "t0", "t1", "fold", "test_year", "side", "outcome", "meta_label",
                      "sample_weight", "prob", "p_sl", "p_timeout", "score", "size", "ret", "cost", "gross",
                      "net", "uniqueness", "hours_to_exit")
#! prob = P(meta_label = 1) (= P(pt) for multiclass models); p_sl / p_timeout: multiclass only (else null);
#! score = the model's directional score: P(pt) - P(sl) for multiclass, prob otherwise (dir_auc uses it)


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
    out["dir_auc"] = _dir_auc(pred)
    out.update(trading_metrics(pred, start, end, bt))
    return out


def _pool(datasets: list[Dataset]) -> None:
    """ Pooled datasets must come from the same configs, one per symbol. """
    syms = [d.symbol for d in datasets]
    if len(set(syms)) != len(syms):
        raise ValueError(f"one dataset per symbol, got {syms}")
    first = datasets[0]
    for d in datasets[1:]:
        for what in ("hashes", "strategy_id", "feature_names", "signed_names"):
            if getattr(d, what) != getattr(first, what):
                raise ValueError(f"pooled datasets differ in {what}: {first.symbol} vs {d.symbol}")


def evaluate(
    ds: Dataset | list[Dataset] | tuple[Dataset, ...],
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
    datasets = sorted([ds] if isinstance(ds, Dataset) else list(ds), key=lambda d: d.symbol)
    if not datasets:
        raise ValueError("no datasets")
    _pool(datasets)
    ds0 = datasets[0]
    symbols = [d.symbol for d in datasets]
    names = list(model.features) if getattr(model, "features", ()) else list(ds0.feature_names)
    unknown = set(names) - set(ds0.feature_names)
    if unknown:
        raise ValueError(f"model features not in the features config: {sorted(unknown)}")

    #! per symbol: lockbox cut, folds on its own clock, costs on its own quotes
    lock_start = datetime(cv.lockbox_year, 1, 1, tzinfo=UTC)
    frames, sym_folds, firsts = [], [], []
    for d in datasets:
        clock = d.bars.get_column("time").dt.epoch("s").to_numpy()
        fr = d.frame if lockbox else d.frame.filter(pl.col("t0") < lock_start)    # dev runs never see the lockbox
        sym_folds.append(make_folds(fr, clock, cv, lockbox=lockbox))
        first = fr.filter(pl.Series(usable_mask(fr, clock, cv))).get_column("t0").min()
        if first is not None:
            firsts.append(first)
        frames.append((d, fr))
    folds = [Fold(index=parts[0].index, test_year=parts[0].test_year,
                  train=np.concatenate([p.train for p in parts]), test=np.concatenate([p.test for p in parts]),
                  purged=sum(p.purged for p in parts), embargoed=sum(p.embargoed for p in parts))
             for parts in zip(*sym_folds, strict=True)]
    first_used = min(firsts) if firsts else None
    test_end = year_span(folds[-1].test_year)[1]

    configs = {**ds0.hashes, "model": model.config_hash(), "sizer": sizer.config_hash(),
               "backtest": backtest.config_hash(), "cv": cv.config_hash()}
    run_id = None
    if registry is not None:
        for c in (model, sizer, backtest, cv):
            registry.register_config(c)
        run_id = registry.start_run(
            ds0.strategy_id, symbols, configs, cv_scheme=cv.scheme,
            data_start=first_used.date().isoformat() if first_used else "", data_end=test_end.date().isoformat(),
            is_lockbox=lockbox, git_commit=code_version(), notes=notes, purpose=purpose)
        log(f"run {run_id}: {ds0.strategy_id} {'+'.join(symbols)} / {model.label} / {sizer.label}")

    try:
        costed = pl.concat([trade_costs(fr, d.bars, backtest, d.symbol) for d, fr in frames], how="vertical_relaxed")
        X_all, _ = model_inputs(costed, names, ds0.signed_names, getattr(model, "side_inputs", "none"))
        if len(symbols) > 1:                                  # symbol dummies (first symbol = baseline)
            sym = costed.get_column("symbol").to_numpy()
            X_all = np.column_stack([X_all, *[(sym == s).astype(float) for s in symbols[1:]]])
        y_all = costed.get_column("meta_label").to_numpy()
        multi = is_multiclass(model)
        y_fit = (costed.get_column("outcome").replace_strict({c: i for i, c in enumerate(OUTCOME_CLASSES)},
                                                             return_dtype=pl.Int8).to_numpy()
                 if multi else y_all)
        hw_all = costed.get_column("half_width").to_numpy()
        cost_all = costed.get_column("cost").to_numpy()
        w_all = (np.ones(costed.height) if model.sample_weight == "none"
                 else costed.get_column(model.sample_weight).to_numpy().astype(float))
        t0_all = costed.get_column("t0").dt.epoch("s").to_numpy()
        ls_all = costed.get_column("life_start").to_numpy()
        le_all = costed.get_column("life_end").to_numpy()

        parts, priors, fold_rows = [], {}, []
        for f in folds:
            if f.n_train == 0 or f.n_test == 0:
                raise ValueError(f"fold {f.index} ({f.test_year}): {f.n_train} train / {f.n_test} test events")
            probs, info = fold_predict(model, X_all[f.train], y_fit[f.train], w_all[f.train], t0_all[f.train],
                                       ls_all[f.train], le_all[f.train], X_all[f.test])
            if probs.ndim == 2:
                prob, p_sl, p_to = probs[:, 2], probs[:, 0], probs[:, 1]
                score = prob - p_sl
            else:
                prob, p_sl, p_to, score = probs, None, None, probs
            priors[f.index] = float((w_all[f.train] * y_all[f.train]).sum() / w_all[f.train].sum())
            parts.append(costed.filter(pl.Series(f.test)).with_columns(
                pl.lit(f.index, pl.Int32).alias("fold"), pl.lit(f.test_year, pl.Int32).alias("test_year"),
                pl.Series("prob", prob),
                pl.Series("p_sl", p_sl, dtype=pl.Float64) if p_sl is not None else pl.lit(None, pl.Float64).alias("p_sl"),
                pl.Series("p_timeout", p_to, dtype=pl.Float64) if p_to is not None
                else pl.lit(None, pl.Float64).alias("p_timeout"),
                pl.Series("score", score),
                pl.Series("size", apply_sizer(prob, sizer, info["sizing_prior"], p_sl=p_sl,
                                              half_width=hw_all[f.test], cost=cost_all[f.test])),
                pl.Series("sample_weight", w_all[f.test])))
            fold_rows.append({"fold": f.index, "test_year": f.test_year, "n_train": f.n_train,
                              "n_test": f.n_test, "purged": f.purged, "embargoed": f.embargoed, **info})
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
        agg["dir_auc_pooled"] = _dir_auc(trades)
        fold_dir = [r["dir_auc"] for r in fold_rows if _finite(r["dir_auc"])]
        agg["dir_auc"] = float(np.mean(fold_dir)) if fold_dir else math.nan
        agg.update(trading_metrics(trades, year_span(folds[0].test_year)[0], test_end, backtest))
        #! deflated Sharpe: against the best daily Sharpe expected from this many skill-less trials;
        #! a run that trades exactly like an earlier one adds no trial (same trades_hash)
        sr, sk, ku, nd = (agg.get(k, math.nan) for k in ("sharpe_daily", "skew_daily", "kurt_daily", "n_days"))
        agg["psr"] = psr(sr, int(nd) if _finite(nd) else 0, sk, ku)
        th = trades_hash(trades, configs["labels"], configs["backtest"])
        if registry is not None and run_id is not None:
            registry.set_trades_hash(run_id, th)
        if registry is not None and purpose == "trial":
            d = deflated_sharpe(sr, int(nd), sk, ku, registry.trial_count(include_lockbox=True),
                                [*registry.trial_metric("sharpe_daily", exclude_run=run_id, exclude_trades=th), sr])
            agg.update({"dsr": d.dsr, "sr0_daily": d.sr0, "n_trials": float(d.n_trials),
                        "var_sr_trials": d.var_sr})
        agg["n_folds"] = float(len(folds))
        agg["folds_net_positive"] = float(sum(r.get("net_bp", 0) > 0 for r in fold_rows))
        if len(symbols) > 1:
            agg["n_symbols"] = float(len(symbols))
            for s in symbols:
                st = trades.filter(pl.col("symbol") == s)
                sm = trading_metrics(st, year_span(folds[0].test_year)[0], test_end, backtest)
                by_fold = [_metrics(st.filter(pl.col("fold") == r["fold"]), priors[r["fold"]],
                                    *year_span(r["test_year"]), backtest) for r in fold_rows]
                for r, b in zip(fold_rows, by_fold, strict=True):        # per symbol per fold, too
                    r.update({f"{s}.{k}": b[k] for k in PER_SYMBOL_METRICS if k in b})
                sm["clf_auc"] = _mean_finite([b.get("clf_auc") for b in by_fold])
                sm["dir_auc"] = _mean_finite([b.get("dir_auc") for b in by_fold])
                agg.update({f"{s}.{k}": sm[k] for k in PER_SYMBOL_METRICS if k in sm})

        if registry is not None and run_id is not None:
            for row in fold_rows:
                registry.log_metrics(run_id, {k: float(v) for k, v in row.items()
                                              if k not in ("fold", "test_year") and _finite(v)}, fold=row["fold"])
            registry.log_metrics(run_id, {k: v for k, v in agg.items() if _finite(v)})
            if research is not None:
                for s in symbols:
                    out = research.root / "predictions" / f"run={run_id}" / f"{s}.parquet"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    tmp = out.with_suffix(f".tmp{os.getpid()}")
                    trades.filter(pl.col("symbol") == s).write_parquet(tmp)
                    tmp.replace(out)
            registry.finish_run(run_id, "done")
    except BaseException:
        if registry is not None and run_id is not None:
            registry.finish_run(run_id, "failed")
        raise

    return EvalResult(run_id=run_id, strategy_id=ds0.strategy_id, folds=pl.DataFrame(fold_rows),
                      aggregate=agg, trades=trades, configs=configs)


def _dir_auc(pred: pl.DataFrame) -> float:
    """ Directional AUC: the model's score on profit-takes vs stop-losses (timeouts left out).
        0.5 = it can't tell which barrier gets hit, however well it predicts that one does.
    """
    s = pred.filter(pl.col("outcome").is_in(["pt", "sl"]))
    if s.height == 0:
        return math.nan
    return auc((s.get_column("outcome") == "pt").to_numpy().astype(float), s.get_column("score").to_numpy())


def _mean_finite(vals: list) -> float:
    v = [x for x in vals if _finite(x)]
    return float(np.mean(v)) if v else math.nan


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)
#-
