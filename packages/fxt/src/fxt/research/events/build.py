'''
build

Runs a sampler over every year of one symbol's bars and writes the events,
one file per year of t0:

    data/research/events/config=<hash>/source=…/market=…/symbol=…/year=YYYY/SYMBOL-YYYY.parquet

    result = build_events(CusumEventsConfig(h=3), source="dukascopy", market="forex", symbol="EURJPY")
    result.paths, result.stats

Rules
- All years are read and walked in one pass (vol and accumulators carry
  over year boundaries), so every output file lists every bar file read in
  `meta.inputs`. Rebuilding any bar year changes those sha256s.
- Input bars must carry BarsMeta whose checks passed; anything else is refused
  before anything is written.
- Every year with bars gets a file, even with zero events, so "ran, nothing
  fired" can be told apart from "never ran". A year that only has events
  (a t0 just past midnight on Jan 1) gets one too.
- event_id = first 16 hex of sha256("<config_hash>|<symbol>|<t0 iso>"): stable
  across reruns, distinct across configs.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from fxt.lake.models import BarsMeta, CheckRecord
from fxt.lake.models import get_meta_io as get_lake_meta_io
from fxt.lake.paths import Lake, PartitionKey
from fxt.research.models import EventsMeta, FileRef, SamplerConfig, SymbolKey
from fxt.research.paths import Research
from fxt.research.store import code_version, file_ref, write_table

from .contract import CORE_COLUMNS, check_detected, get_sampler
from .cusum import event_stats  # importing cusum also registers its sampler

__all__ = ["EventsBuild", "InputBarsError", "build_events", "event_ids", "load_bars"]

LogFn = Callable[[str], None]
def _quiet(msg: str) -> None: ...


class InputBarsError(ValueError):
    """ Input bars are missing, unstamped, or failed their checks. """


@dataclass(frozen=True)
class EventsBuild:
    config_hash: str
    events: pl.DataFrame                       # every year: CORE_COLUMNS, then the sampler's extras
    paths: tuple[Path, ...]                    # written files (empty for a dry run)
    inputs: tuple[FileRef, ...]
    stats: dict[str, Any] = field(default_factory=dict)
#


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def _defaults() -> tuple[Lake, Research]:
    from fxt.services import get_lake, get_research    # lazy: needs the project settings
    return get_lake(), get_research()

def load_bars(
    lake: Lake, *, source: str, market: str, symbol: str, interval: str,
    columns: tuple[str, ...] = ("time", "mid_close"),
) -> tuple[pl.DataFrame, list[Path]]:
    """ Every year of one symbol's bars (only `columns`), plus the files read.
        Raises InputBarsError if there are none, or any file isn't a passed BarsMeta.
    """
    found = lake.scan("derived", source=source, market=market, symbol=symbol, interval=interval)
    if not found:
        raise InputBarsError(f"no {interval} bars for {source}/{market}/{symbol} in {lake.root}")

    meta_io = get_lake_meta_io()
    paths: list[Path] = []
    for _, p in found:
        try:
            meta = meta_io.read_meta_as(p, BarsMeta)
        except Exception as e:
            raise InputBarsError(f"{p}: not a stamped bar file ({e})") from e
        if not meta.passed:
            bad = ", ".join(c.name for c in meta.failed_checks)
            raise InputBarsError(f"{p}: bar checks failed ({bad}); fix or rebuild it first")
        paths.append(p)

    bars = pl.concat([pl.read_parquet(p, columns=list(columns), hive_partitioning=False) for p in paths])
    return bars, paths
#

def event_ids(config_hash: str, symbol: str, t0: pl.Series) -> pl.Series:
    """ Deterministic ids: sha256("<hash>|<symbol>|<t0 iso>")[:16]. """
    iso = t0.dt.convert_time_zone("UTC").dt.strftime("%Y-%m-%dT%H:%M:%S%.6fZ").to_list()
    return pl.Series("event_id", [
        hashlib.sha256(f"{config_hash}|{symbol}|{s}".encode()).hexdigest()[:16] for s in iso
    ], dtype=pl.String)
#


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
def build_events(
    config: SamplerConfig,
    *,
    source: str,
    market: str,
    symbol: str,
    lake: Lake | None = None,
    research: Research | None = None,
    write: bool = True,
    log: LogFn = _quiet,
) -> EventsBuild:
    """ Detect events over every year of bars and (unless write=False) write them. """
    detect = get_sampler(config)
    if lake is None or research is None:
        dl, dr = _defaults()
        lake, research = lake or dl, research or dr

    bars, paths = load_bars(lake, source=source, market=market, symbol=symbol,
                            interval=config.interval, columns=config.bar_columns())
    log(f"{symbol}: {bars.height} {config.interval} bars from {len(paths)} file(s)")

    found = check_detected(detect(bars, config), config.sampler)
    h = config.config_hash()
    events = found.select(
        event_ids(h, symbol, found.get_column("t0")),
        pl.lit(symbol, dtype=pl.String).alias("symbol"),
        pl.all(),
    )
    assert events.columns[:len(CORE_COLUMNS)] == list(CORE_COLUMNS)
    stats = event_stats(found, bars)
    log(f"{symbol}: {events.height} events ({stats['per_active_day']:.2f} per active day), config={h}")

    inputs = tuple(file_ref(p, lake_root=lake.root, research_root=research.root) for p in paths)
    if not write:
        return EventsBuild(config_hash=h, events=events, paths=(), inputs=inputs, stats=stats)

    bar_years = {PartitionKey.from_path(p.relative_to(lake.root)).year for p in paths}
    years = sorted(bar_years | set(events.get_column("t0").dt.year().unique().to_list()))
    checks = (
        CheckRecord(name="inputs: bar files stamped and passed", status="pass", value=len(paths)),
        CheckRecord(name="sampler: warmup completed", status="pass" if bars.height > getattr(config, "warmup", 0)
                    else "warn", value=bars.height),
    )
    version = code_version()
    dataset = SymbolKey(source=source, market=market, symbol=symbol)

    written: list[Path] = []
    for year in years:
        part = events.filter(pl.col("t0").dt.year() == year)
        meta = EventsMeta.for_config(config, dataset=dataset, year=year, rows=part.height,
                                     inputs=inputs, checks=checks, code_version=version,
                                     sampler=config.sampler)
        written.append(write_table(part, meta, research=research))
        log(f"  wrote {year}: {part.height} events")

    return EventsBuild(config_hash=h, events=events, paths=tuple(written), inputs=inputs, stats=stats)
#-
