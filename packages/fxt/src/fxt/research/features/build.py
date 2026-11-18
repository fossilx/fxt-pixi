'''
build

Computes the feature table for one symbol over every year at once (windows
carry across years) and writes one file per year of bar_time:

    data/research/features/config=<hash>/source=…/market=…/symbol=…/year=YYYY/SYMBOL-YYYY.parquet

    result = build_features(BarFeaturesConfig(), source="dukascopy", market="forex", symbol="EURJPY")

Features don't depend on any strategy: no upstream hash, the only inputs are
bar files (stamped and passed, all listed in meta.inputs).
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

import polars as pl

from fxt.lake.models import CheckRecord
from fxt.lake.paths import Lake
from fxt.research.events.build import load_bars
from fxt.research.models import BarFeaturesConfig, FeaturesMeta, FileRef, SymbolKey
from fxt.research.paths import Research
from fxt.research.store import code_version, file_ref, write_table

from .baseline import BAR_COLUMNS, compute_features

__all__ = ["FeaturesBuild", "build_features", "check_features", "feature_stats"]


def _quiet(msg: str) -> None: ...


@dataclass(frozen=True)
class FeaturesBuild:
    config_hash: str
    features: pl.DataFrame                     # long, every year
    paths: tuple[Path, ...]
    inputs: tuple[FileRef, ...]
    checks: tuple[CheckRecord, ...]
    stats: pl.DataFrame                        # one row per name
    bars: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
#


def check_features(long: pl.DataFrame, cfg: BarFeaturesConfig) -> tuple[CheckRecord, ...]:
    tests = {
        "one value per (bar, name)": not long.select("bar_time", "name").is_duplicated().any(),
        "names are the config's":    set(long.get_column("name").unique()) <= set(cfg.names()),
        "values finite":             long.get_column("value").is_finite().all(),
        "bar_time on the hour":      (long.get_column("bar_time").dt.truncate("1h") == long.get_column("bar_time")).all(),
    }
    return tuple(CheckRecord(name=f"features: {n}", status="pass" if bool(ok) else "fail") for n, ok in tests.items())
#

def feature_stats(long: pl.DataFrame, n_bars: int, names: tuple[str, ...]) -> pl.DataFrame:
    """ Per name: bars with a value, coverage, and the value distribution. """
    st = long.group_by("name").agg(
        pl.len().alias("bars"),
        pl.col("value").mean().alias("mean"), pl.col("value").std().alias("std"),
        pl.col("value").quantile(0.01).alias("p01"), pl.col("value").median().alias("median"),
        pl.col("value").quantile(0.99).alias("p99"),
    ).with_columns((pl.col("bars") / max(n_bars, 1)).alias("coverage"))
    order = pl.DataFrame({"name": list(names), "_o": list(range(len(names)))})
    return order.join(st, on="name", how="left").sort("_o").drop("_o")
#

def _defaults() -> tuple[Lake, Research]:
    from fxt.services import get_lake, get_research
    return get_lake(), get_research()

def build_features(
    config: BarFeaturesConfig,
    *,
    source: str,
    market: str,
    symbol: str,
    lake: Lake | None = None,
    research: Research | None = None,
    write: bool = True,
    log=_quiet,
) -> FeaturesBuild:
    """ The feature table over every year of one symbol's bars. """
    if lake is None or research is None:
        dl, dr = _defaults()
        lake, research = lake or dl, research or dr
    ser = {"source": source, "market": market, "symbol": symbol}

    bars, paths = load_bars(lake, **ser, interval=config.interval, columns=BAR_COLUMNS)
    log(f"{symbol}: {bars.height} {config.interval} bars from {len(paths)} file(s)")
    long = compute_features(bars, config, symbol=symbol)
    checks = check_features(long, config)
    if failed := [c.name for c in checks if not c.ok]:
        raise AssertionError(f"feature invariants failed: {failed}")
    stats = feature_stats(long, bars.height, config.names())
    h = config.config_hash()
    log(f"{symbol}: {long.height} feature values ({len(config.names())} names), config={h}")

    inputs = tuple(file_ref(p, lake_root=lake.root, research_root=research.root) for p in paths)
    if not write:
        return FeaturesBuild(config_hash=h, features=long, paths=(), inputs=inputs, checks=checks,
                             stats=stats, bars=bars.height)

    version = code_version()
    dataset = SymbolKey(**ser)
    written: list[Path] = []
    for year in sorted(long.get_column("bar_time").dt.year().unique().to_list()):
        part = long.filter(pl.col("bar_time").dt.year() == year)
        meta = FeaturesMeta.for_config(config, dataset=dataset, year=year, rows=part.height, inputs=inputs,
                                       checks=checks, code_version=version, names=config.names())
        written.append(write_table(part, meta, research=research))
        log(f"  wrote {year}: {part.height} values")
    return FeaturesBuild(config_hash=h, features=long, paths=tuple(written), inputs=inputs, checks=checks,
                         stats=stats, bars=bars.height)
#-
