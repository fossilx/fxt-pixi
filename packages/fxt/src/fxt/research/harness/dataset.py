'''
dataset

Assembles one strategy's training table for the harness: labels + weights + touches
(prices) + features at t0, plus the hourly bars (business clock and quotes for costs).

    ds = load_dataset(research, lake, labels_hash="3b896dab2027",
                      source="dukascopy", market="forex", symbol="EURJPY")
    ds.frame            one row per labeled event (insufficient rows dropped), sorted by t0
    ds.feature_names    the features config's names, in order
    ds.hashes           {"events", "touches", "labels", "weights", "features"} -> config hash

Weights and features default to the default configs for these labels
(SampleWeightsConfig(labels_hash=...), BarFeaturesConfig()), like the CLIs.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

from fxt.lake.paths import Lake
from fxt.research.events.build import load_bars
from fxt.research.features.matrix import features_at, to_wide
from fxt.research.models import BarFeaturesConfig, SampleWeightsConfig
from fxt.research.paths import Research, Stage
from fxt.research.store import read_meta

__all__ = ["BAR_QUOTE_COLUMNS", "Dataset", "InputDatasetError", "load_dataset"]

BAR_QUOTE_COLUMNS = ("time", "bid_close", "ask_close", "mid_close", "spread_mean")


class InputDatasetError(ValueError):
    """ A table the dataset needs is missing or doesn't match the others. """


@dataclass(frozen=True)
class Dataset:
    source: str
    market: str
    symbol: str
    strategy_id: str
    frame: pl.DataFrame
    feature_names: tuple[str, ...]
    bars: pl.DataFrame                         # BAR_QUOTE_COLUMNS, sorted by time (open times)
    hashes: dict[str, str] = field(default_factory=dict)
#


def _read_stage(research: Research, stage: Stage, config_hash: str, **dataset: str) -> tuple[pl.DataFrame, list]:
    found = research.scan(stage, config=config_hash, **dataset)
    if not found:
        raise InputDatasetError(f"no {stage} files for config={config_hash} {dataset}")
    metas, frames = [], []
    for _, p in found:
        metas.append(read_meta(p))
        frames.append(pl.read_parquet(p, hive_partitioning=False))
    return pl.concat(frames, how="vertical_relaxed"), metas


def load_dataset(
    research: Research,
    lake: Lake,
    *,
    labels_hash: str,
    source: str,
    market: str,
    symbol: str,
    weights_hash: str | None = None,
    features_hash: str | None = None,
) -> Dataset:
    keys = {"source": source, "market": market, "symbol": symbol}
    weights_hash = weights_hash or SampleWeightsConfig(labels_hash=labels_hash).config_hash()
    features_hash = features_hash or BarFeaturesConfig().config_hash()

    labels, lmetas = _read_stage(research, Stage.LABELS, labels_hash, **keys)
    strategy_id = lmetas[0].strategy_id                                   # type: ignore[attr-defined]
    touches_hash = lmetas[0].input_hashes["touches"]

    weights, wmetas = _read_stage(research, Stage.WEIGHTS, weights_hash, **keys)
    if wmetas[0].input_hashes.get("labels") != labels_hash:
        raise InputDatasetError(f"weights config={weights_hash} weights labels "
                                f"{wmetas[0].input_hashes.get('labels')}, not {labels_hash}")

    touches, tmetas = _read_stage(research, Stage.TOUCHES, touches_hash, **keys)
    events_hash = tmetas[0].input_hashes["events"]

    long, fmetas = _read_stage(research, Stage.FEATURES, features_hash, **keys)
    names = tuple(fmetas[0].names)                                        # type: ignore[attr-defined]
    wide = to_wide(long, names)

    frame = (
        labels.filter(pl.col("meta_label").is_not_null())
        .select("event_id", "symbol", "t0", "t1", "side", "touch", "outcome", "meta_label", "ret",
                "hours_to_exit", "exit_gap")
        .join(touches.select("event_id", "price_t0", "exit_price"), on="event_id", how="left")
        .join(weights.select("event_id", "life_start", "life_end", "uniqueness", "weight", "weight_uniq"),
              on="event_id", how="left")
        .sort("t0")
    )
    missing = frame.filter(pl.col("price_t0").is_null() | pl.col("uniqueness").is_null()).height
    if missing:
        raise InputDatasetError(f"{missing} labeled events have no touch or weight row: "
                                "touches/weights don't match these labels (rebuild them)")
    frame = features_at(frame, wide)

    bars, _ = load_bars(lake, source=source, market=market, symbol=symbol, interval="1HOUR",
                        columns=BAR_QUOTE_COLUMNS)
    if bars.schema["time"].time_zone is None:                             # type: ignore[attr-defined]
        bars = bars.with_columns(pl.col("time").dt.replace_time_zone("UTC"))
    bars = bars.with_columns(pl.col("time").dt.cast_time_unit("us"))
    return Dataset(
        source=source, market=market, symbol=symbol, strategy_id=strategy_id,
        frame=frame, feature_names=names, bars=bars.sort("time"),
        hashes={"events": events_hash, "touches": touches_hash, "labels": labels_hash,
                "weights": weights_hash, "features": features_hash},
    )
#-
