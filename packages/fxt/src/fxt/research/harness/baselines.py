'''
baselines

The random-entry baseline (ML pipeline spec §9.6): many seeds of RandomEventsConfig,
each run through the same touch pass, side labels, weights and harness as a
candidate strategy, with `take_all`. The spread of their results is what "no
information, same frequency, same barriers, same costs" looks like.

    base = random_baseline(research, lake, registry, like_labels="3b896dab2027",
                           source="dukascopy", market="forex", symbol="EURJPY", seeds=range(20))
    base.runs                         one row per seed: hashes, run_id, aggregate metrics
    compare(base, registry, run_id)   where a candidate run falls in that distribution

Every stage is built only if its config folder has no files yet, and a seed is
evaluated only if no finished control run used exactly the same configs, so
re-running with more seeds only does the new ones. Baseline runs are recorded with
purpose="control": they're in the registry but never counted as trials.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import polars as pl

from fxt.lake.paths import Lake
from fxt.research.events import build_events
from fxt.research.labels import build_labels, build_touches
from fxt.research.models import (
    BacktestConfig, RandomEventsConfig, SampleWeightsConfig, SideLabelsConfig, SizerConfig, StageConfig,
    TakeAllModelConfig, WalkForwardConfig, registry as config_registry,
)
from fxt.research.paths import Research, Stage
from fxt.research.registry import Registry
from fxt.research.store import read_meta
from fxt.research.weights import build_weights

from .dataset import InputDatasetError, load_dataset
from .evaluate import evaluate

__all__ = ["BASELINE_METRICS", "RandomBaseline", "compare", "random_baseline"]

BASELINE_METRICS = ("n_trades", "gross_bp", "cost_bp", "net_bp", "hit_rate", "sharpe_ann", "max_dd_bp")


def _quiet(msg: str) -> None: ...


@dataclass(frozen=True)
class RandomBaseline:
    like_labels: str
    fire_prob: float
    runs: pl.DataFrame                         # seed, events, touches, labels, weights, run_id, reused, *BASELINE_METRICS
#


def _stored_config(research: Research, stage: Stage, config_hash: str, keys: dict) -> StageConfig:
    found = research.scan(stage, config=config_hash, **keys)
    if not found:
        raise InputDatasetError(f"no {stage} files for config={config_hash} {keys}")
    m = read_meta(found[0][1])
    return config_registry.get_model(m.config_typeid).model_validate(m.config)   # type: ignore[return-value]


def _built(research: Research, stage: Stage, config_hash: str, keys: dict) -> bool:
    return bool(research.scan(stage, config=config_hash, **keys))


def _find_control(reg: Registry, configs: dict[str, str]) -> str | None:
    """ A finished control run that used exactly these configs. """
    for (run_id,) in reg.con.execute(
            "SELECT run_id FROM runs WHERE purpose = 'control' AND status = 'done' ORDER BY started_at"):
        if reg.run_configs(run_id) == configs:
            return run_id
    return None


def random_baseline(
    research: Research,
    lake: Lake,
    reg: Registry,
    *,
    like_labels: str,
    source: str,
    market: str,
    symbol: str,
    seeds: Iterable[int],
    fire_prob: float = 0.0935,
    features_hash: str | None = None,
    backtest: BacktestConfig | None = None,
    cv: WalkForwardConfig | None = None,
    log: Callable[[str], None] = _quiet,
) -> RandomBaseline:
    """ Random-entry runs matching the candidate labels' touch and side-label configs. """
    keys = {"source": source, "market": market, "symbol": symbol}
    backtest = backtest or BacktestConfig()
    cv = cv or WalkForwardConfig()
    model = TakeAllModelConfig()

    cand_labels = _stored_config(research, Stage.LABELS, like_labels, keys)
    cand_touches = _stored_config(research, Stage.TOUCHES, cand_labels.input_hashes()["touches"], keys)

    rows = []
    for seed in seeds:
        ev = RandomEventsConfig(seed=seed, fire_prob=fire_prob)
        tc = type(cand_touches).model_validate({**cand_touches.payload(), "events_hash": ev.config_hash()})
        lc = type(cand_labels).model_validate({**cand_labels.payload(), "touches_hash": tc.config_hash()})
        assert isinstance(lc, SideLabelsConfig)
        wc = SampleWeightsConfig(labels_hash=lc.config_hash())
        hashes = {"events": ev.config_hash(), "touches": tc.config_hash(), "labels": lc.config_hash(),
                  "weights": wc.config_hash()}
        log(f"seed {seed}: events {hashes['events']}  touches {hashes['touches']}  labels {hashes['labels']}")
        if not _built(research, Stage.EVENTS, hashes["events"], keys):
            build_events(ev, **keys, lake=lake, research=research)
        if not _built(research, Stage.TOUCHES, hashes["touches"], keys):
            build_touches(tc, **keys, lake=lake, research=research)        # type: ignore[arg-type]
        if not _built(research, Stage.LABELS, hashes["labels"], keys):
            build_labels(lc, **keys, research=research)
        if not _built(research, Stage.WEIGHTS, hashes["weights"], keys):
            build_weights(wc, **keys, lake=lake, research=research)

        ds = load_dataset(research, lake, labels_hash=hashes["labels"], features_hash=features_hash, **keys)
        configs = {**ds.hashes, "model": model.config_hash(), "sizer": SizerConfig().config_hash(),
                   "backtest": backtest.config_hash(), "cv": cv.config_hash()}
        run_id = _find_control(reg, configs)
        reused = run_id is not None
        if run_id is None:
            res = evaluate(ds, model=model, backtest=backtest, cv=cv, registry=reg, research=research,
                           purpose="control", notes=f"random-entry baseline like labels={like_labels}")
            run_id = res.run_id
        got = {r["name"]: r["value"] for r in reg.metrics(run_id).filter(pl.col("fold").is_null()).iter_rows(named=True)}
        rows.append({"seed": seed, **hashes, "run_id": run_id, "reused": reused,
                     **{k: got.get(k) for k in BASELINE_METRICS}})
        log(f"seed {seed}: run {run_id}{' (reused)' if reused else ''}  net {got.get('net_bp', float('nan')):+.2f} bp  "
            f"sharpe {got.get('sharpe_ann', float('nan')):+.2f}")
    return RandomBaseline(like_labels=like_labels, fire_prob=fire_prob, runs=pl.DataFrame(rows))


def compare(base: RandomBaseline, reg: Registry, run_id: str) -> pl.DataFrame:
    """ Per metric: the candidate's value, the baseline's mean / 5% / 50% / 95%, and the
        share of seeds at least as good (an empirical p-value, (1 + k) / (1 + n)).
    """
    cand = {r["name"]: r["value"] for r in reg.metrics(run_id).filter(pl.col("fold").is_null()).iter_rows(named=True)}
    n = base.runs.height
    out = []
    for m in ("gross_bp", "net_bp", "sharpe_ann", "hit_rate"):
        vals = base.runs.get_column(m).drop_nulls()
        c = cand.get(m)
        k = int((vals >= c).sum()) if c is not None else None
        out.append({"metric": m, "candidate": c, "mean": vals.mean(), "p05": vals.quantile(0.05),
                    "p50": vals.quantile(0.5), "p95": vals.quantile(0.95),
                    "p_value": (1 + k) / (1 + n) if k is not None else None})
    return pl.DataFrame(out)
#-
