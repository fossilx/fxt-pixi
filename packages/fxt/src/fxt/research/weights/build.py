'''
build

Computes sample weights for one labels config (one strategy) and one symbol,
over every year at once, and writes ONE file (weights aren't split by year:
overlap crosses year boundaries):

    data/research/weights/config=<hash>/source=…/market=…/symbol=…/SYMBOL.parquet

    cfg = SampleWeightsConfig(labels_hash=...)
    result = build_weights(cfg, source="dukascopy", market="forex", symbol="EURJPY")

Reads the labels (every year) and every year of 1HOUR bars (the business
clock). Bar files must be stamped and passed. Invariant checks are recorded
in the metadata; a failed check stops the build before anything is written.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from fxt.lake.models import CheckRecord
from fxt.lake.paths import Lake
from fxt.research.events.build import load_bars
from fxt.research.models import FileRef, SampleWeightsConfig, SymbolKey, WeightsMeta
from fxt.research.paths import Research, Stage
from fxt.research.store import code_version, file_ref, read_meta, write_table

from .uniqueness import WEIGHT_SCHEMA, compute_weights, sweep

__all__ = ["InputLabelsError", "WeightsBuild", "build_weights", "check_weights", "weight_stats"]


def _quiet(msg: str) -> None: ...


class InputLabelsError(ValueError):
    """ The labels to weight are missing. """


@dataclass(frozen=True)
class WeightsBuild:
    config_hash: str
    strategy_id: str
    weights: pl.DataFrame                      # event_id, symbol, then WEIGHT_SCHEMA (minus event_id)
    paths: tuple[Path, ...]
    inputs: tuple[FileRef, ...]
    checks: tuple[CheckRecord, ...]
    stats: dict[str, Any] = field(default_factory=dict)
#


def check_weights(w: pl.DataFrame) -> tuple[CheckRecord, ...]:
    """ Invariants every weights table must satisfy (ported from verify_weights). """
    ok = w.filter(pl.col("uniqueness").is_not_null())
    if ok.height == 0:
        return (CheckRecord(name="weights: no placed labels", status="warn"),)
    start, end = ok["life_start"].to_numpy(), ok["life_end"].to_numpy()
    uniq = ok["uniqueness"].to_numpy()
    covered = sweep(start, end)[2]
    total = float((uniq * (end - start)).sum())
    tests = {
        "one row per event":            w.get_column("event_id").is_unique().all(),
        "weights finite and positive":  bool(np.isfinite(ok["weight"].to_numpy()).all()
                                             and (ok["weight"] >= 0).all() and (ok["weight_uniq"] > 0).all()),
        "both weights have mean 1":     abs(ok["weight"].mean() - 1) < 1e-9 and abs(ok["weight_uniq"].mean() - 1) < 1e-9,  # type: ignore[operator]
        "uniqueness in (0, 1]":         bool(((uniq > 0) & (uniq <= 1 + 1e-12)).all()),
        "mean concurrency >= 1":        bool((ok["mean_concurrency"] >= 1 - 1e-9).all()),
        "sum(uniqueness*life) == time covered": abs(total - covered) <= 1e-9 * max(covered, 1.0),
    }
    return tuple(CheckRecord(name=f"weights: {name}", status="pass" if bool(passed) else "fail")
                 for name, passed in tests.items())
#

def weight_stats(w: pl.DataFrame, labels: pl.DataFrame) -> dict[str, Any]:
    ok = w.filter(pl.col("uniqueness").is_not_null())
    n = ok.height
    if n == 0:
        return {"labels": w.height, "weighted": 0}
    ess = lambda s: float(s.sum() ** 2 / (s ** 2).sum())
    by = (ok.join(labels.select("event_id", "outcome"), on="event_id")
            .group_by("outcome").agg(pl.col("weight").sum().alias("w"), pl.len().alias("n"))
            .with_columns(w_share=pl.col("w") / pl.col("w").sum(), n_share=pl.col("n") / n))
    return {
        "labels": w.height,
        "weighted": n,
        "mean_uniqueness": float(ok["uniqueness"].mean()),               # type: ignore[arg-type]
        "mean_concurrency": float(ok["mean_concurrency"].mean()),         # type: ignore[arg-type]
        "max_concurrency": float(ok["mean_concurrency"].max()),           # type: ignore[arg-type]
        "independent_samples": n * float(ok["uniqueness"].mean()),        # type: ignore[arg-type]
        "kish_ess_weight": ess(ok["weight"]),
        "kish_ess_uniq": ess(ok["weight_uniq"]),
        "weight_share_by_outcome": {o: (ws, ns) for o, ws, ns in by.select("outcome", "w_share", "n_share").iter_rows()},
    }
#

def _defaults() -> tuple[Lake, Research]:
    from fxt.services import get_lake, get_research
    return get_lake(), get_research()

def build_weights(
    config: SampleWeightsConfig,
    *,
    source: str,
    market: str,
    symbol: str,
    lake: Lake | None = None,
    research: Research | None = None,
    write: bool = True,
    log=_quiet,
) -> WeightsBuild:
    """ Sample weights for every label of `config.labels_hash` for one symbol. """
    if lake is None or research is None:
        dl, dr = _defaults()
        lake, research = lake or dl, research or dr
    ser = {"source": source, "market": market, "symbol": symbol}

    label_files = research.scan(Stage.LABELS, config=config.labels_hash, **ser)
    if not label_files:
        raise InputLabelsError(f"no labels for config={config.labels_hash} {source}/{market}/{symbol} "
                               f"in {research.root}")
    strategy_id = str(getattr(read_meta(label_files[0][1]), "strategy_id", ""))
    labels = pl.concat([pl.read_parquet(p, hive_partitioning=False) for _, p in label_files]).sort("t0")
    clock, clock_paths = load_bars(lake, **ser, interval=config.clock_interval, columns=("time",))
    log(f"{symbol}: {strategy_id}: {labels.height} labels, {clock.height} {config.clock_interval} bars as clock")

    weights = compute_weights(labels, clock.get_column("time"))
    weights = weights.select("event_id", pl.lit(symbol, dtype=pl.String).alias("symbol"),
                             *[c for c in WEIGHT_SCHEMA if c != "event_id"])
    checks = check_weights(weights)
    if failed := [c.name for c in checks if c.status == "fail"]:
        raise AssertionError(f"weight invariants failed: {failed}")
    stats = weight_stats(weights, labels)
    h = config.config_hash()
    log(f"{symbol}: {stats['weighted']}/{stats['labels']} weighted, config={h}")

    inputs = tuple([file_ref(p, lake_root=lake.root, research_root=research.root) for _, p in label_files]
                   + [file_ref(p, lake_root=lake.root, research_root=research.root) for p in clock_paths])
    if not write:
        return WeightsBuild(config_hash=h, strategy_id=strategy_id, weights=weights, paths=(),
                            inputs=inputs, checks=checks, stats=stats)

    meta = WeightsMeta.for_config(config, dataset=SymbolKey(**ser), rows=weights.height,
                                  inputs=inputs, checks=checks, code_version=code_version())
    path = write_table(weights, meta, research=research)
    log(f"  wrote {path.name}: {weights.height} rows")
    return WeightsBuild(config_hash=h, strategy_id=strategy_id, weights=weights, paths=(path,),
                        inputs=inputs, checks=checks, stats=stats)
#-
