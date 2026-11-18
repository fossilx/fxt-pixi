'''
build

Builders for both labeling steps. Step 1, the touch pass (build_touches),
writes one file per year of t0 (the same years as the events):

    data/research/touches/config=<hash>/source=…/market=…/symbol=…/year=YYYY/SYMBOL-YYYY.parquet

    cfg = TripleBarrierTouchConfig(events_hash=CusumEventsConfig().config_hash())
    result = build_touches(cfg, source="dukascopy", market="forex", symbol="EURJPY")

Reads
- the events (data/research/events/config=<events_hash>/…): core columns only
- every year of 1HOUR bars (barrier vol and the horizon clock)
- every year of 1MIN bars (the scan)
- raw ticks, only for same-minute ambiguity, only the years where it happens

Every file read is listed in each output file's `meta.inputs` (tick files
only if one was actually consulted). Bar files must be stamped and passed.
Invariant checks (check_touches) run on the result and are recorded in the
metadata; a failed check stops the build before anything is written.

Step 2, side labels (build_labels), reads a touch pass plus its events'
directions and writes data/research/labels/config=<hash>/… for one side rule;
same years, same rules for lineage and checks.

    cfg = SideLabelsConfig(touches_hash=..., side_rule="fade")
    result = build_labels(cfg, source="dukascopy", market="forex", symbol="EURJPY")
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from fxt.lake.models import CheckRecord
from fxt.lake.paths import Lake, PartitionKey
from fxt.research.events.build import InputBarsError, load_bars
from fxt.research.events.contract import CORE_COLUMNS
from fxt.research.models import (
    FileRef, LabelsMeta, ResearchMeta, SideLabelsConfig, SymbolKey, TouchesMeta, TripleBarrierTouchConfig,
    registry,
)
from fxt.research.paths import Research, Stage
from fxt.research.store import code_version, file_ref, read_meta, write_table

from .side import OUTCOMES, side_labels
from .touch import TOUCH_SCHEMA, MinuteBars, compute_touches

__all__ = [
    "InputEventsError", "LakeTicks", "TouchesBuild", "build_touches", "check_touches", "touch_stats",
    "InputTouchesError", "LabelsBuild", "build_labels", "check_labels", "label_stats", "strategy_label",
]


def _quiet(msg: str) -> None: ...


class InputEventsError(ValueError):
    """ The events to label are missing or unreadable. """


@dataclass(frozen=True)
class TouchesBuild:
    config_hash: str
    touches: pl.DataFrame                      # every year: event_id, symbol, then TOUCH_SCHEMA
    paths: tuple[Path, ...]
    inputs: tuple[FileRef, ...]
    checks: tuple[CheckRecord, ...]
    stats: dict[str, Any] = field(default_factory=dict)
#


#!================================================================================(80)
#! ticks
#!--------------------------------------------------------------------------------(80)
class LakeTicks:
    """ TickLookup over the lake's raw tick files; remembers which files it read. """

    def __init__(self, lake: Lake, *, source: str, market: str, symbol: str):
        self.lake, self.ser = lake, {"source": source, "market": market, "symbol": symbol}
        self.used: dict[int, Path] = {}

    def _file(self, year: int) -> Path:
        key = PartitionKey(**self.ser, interval="TICK", year=year)
        p = self.lake.raw(**key.model_dump(), filename=key.filename, must_exist=False)
        if not p.exists():
            raise InputBarsError(f"same-minute ambiguity at {year} needs raw ticks, but {p} is missing "
                                 f"(or rebuild with ambiguity='ohlc')")
        self.used[year] = p
        return p

    def _frame(self, year: int) -> pl.LazyFrame:
        lf = pl.scan_parquet(self._file(year), hive_partitioning=False).select("dtime", "bidPrice", "askPrice")
        tz = lf.collect_schema()["dtime"].time_zone                 # type: ignore[union-attr]
        t = pl.col("dtime").dt.replace_time_zone("UTC") if tz is None else pl.col("dtime").dt.convert_time_zone("UTC")
        return lf.with_row_index("n").with_columns(t)

    def first_touch(self, start_s: int, end_s: int, upper: float, lower: float) -> int | None:
        start, end = datetime.fromtimestamp(start_s, UTC), datetime.fromtimestamp(end_s, UTC)
        df = (self._frame(start.year)
              .filter(pl.col("dtime") >= start, pl.col("dtime") < end)
              .with_columns(((pl.col("bidPrice") + pl.col("askPrice")) / 2).alias("m"))
              .filter((pl.col("m") >= upper) | (pl.col("m") <= lower))
              .sort("dtime", "n")                                     # file order breaks ties
              .head(1)
              .collect())
        if df.height == 0:
            return None
        return 1 if df.item(0, "m") >= upper else -1
#


#!================================================================================(80)
#! checks
#!--------------------------------------------------------------------------------(80)
def check_touches(df: pl.DataFrame) -> tuple[CheckRecord, ...]:
    """ Invariants every touch table must satisfy (ported from verify_labels). """
    ok = df.filter(pl.col("touch") != "insufficient_data")
    up, dn, vt = (ok.filter(pl.col("touch") == t) for t in ("upper", "lower", "vertical"))
    insuf = df.filter(pl.col("touch") == "insufficient_data")
    tests = {
        "one row per event":            df.get_column("event_id").is_unique().all(),
        "touch values known":           df.get_column("touch").is_in(["upper", "lower", "vertical",
                                                                       "insufficient_data"]).all(),
        "exit not before t0":           (ok["t1"] >= ok["t0"]).all(),
        "exit within vertical barrier": (ok["t1"] <= ok["vertical_time"]).all(),
        "upper exits at/above barrier": (up["exit_price"] >= up["upper"] - 1e-12).all(),
        "lower exits at/below barrier": (dn["exit_price"] <= dn["lower"] + 1e-12).all(),
        "timeouts exit at vertical":    (vt["t1"] == vt["vertical_time"]).all(),
        "timeouts stay inside barriers": ((vt["max_up"] < vt["half_width"]) & (vt["max_down"] < vt["half_width"])).all(),
        "excursions non-negative":      ((ok["max_up"] >= 0) & (ok["max_down"] >= 0)).all(),
        "insufficient rows: no exit":   insuf["t1"].is_null().all() and insuf["reason"].is_not_null().all(),
    }
    return tuple(CheckRecord(name=f"touches: {name}", status="pass" if bool(passed) else "fail")
                 for name, passed in tests.items())
#


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
def _defaults() -> tuple[Lake, Research]:
    from fxt.services import get_lake, get_research
    return get_lake(), get_research()

def touch_stats(df: pl.DataFrame) -> dict[str, Any]:
    ok = df.filter(pl.col("touch") != "insufficient_data")
    n_ok = max(ok.height, 1)
    share = {t: ok.filter(pl.col("touch") == t).height / n_ok for t in ("upper", "lower", "vertical")}
    med = {t: ok.filter(pl.col("touch") == t)["hours_to_exit"].median() for t in ("upper", "lower")}
    return {
        "events": df.height,
        "placed": ok.height,
        "insufficient": dict(df.filter(pl.col("touch") == "insufficient_data")
                             .group_by("reason").len().sort("reason").iter_rows()),
        "share": share,
        "median_hours": med,
        "median_hours_all": ok["hours_to_exit"].median(),
        "resolution": dict(ok.filter(pl.col("resolution").is_not_null())
                           .group_by("resolution").len().sort("resolution").iter_rows()),
        "gap_exits": int(ok["exit_gap"].sum()),
    }
#

def build_touches(
    config: TripleBarrierTouchConfig,
    *,
    source: str,
    market: str,
    symbol: str,
    lake: Lake | None = None,
    research: Research | None = None,
    write: bool = True,
    log=_quiet,
) -> TouchesBuild:
    """ Touch pass over every event of `config.events_hash` for one symbol. """
    if lake is None or research is None:
        dl, dr = _defaults()
        lake, research = lake or dl, research or dr
    ser = {"source": source, "market": market, "symbol": symbol}

    #~ events ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~(70)
    found = research.scan(Stage.EVENTS, config=config.events_hash, **ser)
    if not found:
        raise InputEventsError(f"no events for config={config.events_hash} {source}/{market}/{symbol} "
                               f"in {research.root}")
    for _, p in found:
        read_meta(p)                                        # validates (hash integrity)
    event_years = [int(k.year) for k, _ in found]           # type: ignore[arg-type]
    events = pl.concat([pl.read_parquet(p, columns=list(CORE_COLUMNS), hive_partitioning=False)
                        for _, p in found]).sort("t0")
    log(f"{symbol}: {events.height} events from {len(found)} file(s)")

    #~ bars ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~(70)
    hourly, hourly_paths = load_bars(lake, **ser, interval=config.vol_interval, columns=("time", "mid_close"))
    minute_df, minute_paths = load_bars(lake, **ser, interval=config.scan_interval,
                                        columns=("time", "mid_open", "mid_high", "mid_low", "mid_close"))
    minute_years = {PartitionKey.from_path(p.relative_to(lake.root)).year for p in minute_paths}
    log(f"{symbol}: {hourly.height} {config.vol_interval} bars, {minute_df.height} {config.scan_interval} bars "
        f"({min(minute_years)}–{max(minute_years)})")

    #~ touch pass ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~(70)
    ticks = LakeTicks(lake, **ser) if config.ambiguity == "ticks" else None
    out = compute_touches(events, hourly, MinuteBars.from_frame(minute_df), config,
                          ticks=ticks, minute_years=minute_years)
    touches = out.select("event_id", pl.lit(symbol, dtype=pl.String).alias("symbol"),
                         *[c for c in TOUCH_SCHEMA if c != "event_id"])
    checks = check_touches(touches)
    if failed := [c.name for c in checks if not c.ok]:
        raise AssertionError(f"touch invariants failed: {failed}")
    stats = touch_stats(touches)
    h = config.config_hash()
    log(f"{symbol}: {stats['placed']}/{stats['events']} placed, config={h}")

    tick_paths = sorted(ticks.used.values()) if ticks else []
    inputs = tuple(
        [file_ref(p, lake_root=lake.root, research_root=research.root) for _, p in found]
        + [file_ref(p, lake_root=lake.root, research_root=research.root)
           for p in (*hourly_paths, *minute_paths, *tick_paths)]
    )
    if not write:
        return TouchesBuild(config_hash=h, touches=touches, paths=(), inputs=inputs, checks=checks, stats=stats)

    version = code_version()
    dataset = SymbolKey(**ser)
    written: list[Path] = []
    for year in sorted(set(event_years)):
        part = touches.filter(pl.col("t0").dt.year() == year)
        meta = TouchesMeta.for_config(config, dataset=dataset, year=year, rows=part.height,
                                      inputs=inputs, checks=checks, code_version=version)
        written.append(write_table(part, meta, research=research))
        log(f"  wrote {year}: {part.height} rows")
    return TouchesBuild(config_hash=h, touches=touches, paths=tuple(written), inputs=inputs,
                        checks=checks, stats=stats)
#-


#!================================================================================(80)
#! side labels (step 2)
#!--------------------------------------------------------------------------------(80)
class InputTouchesError(ValueError):
    """ The touch pass to label is missing or unreadable. """


@dataclass(frozen=True)
class LabelsBuild:
    config_hash: str
    strategy_id: str
    labels: pl.DataFrame                       # every year, LABEL_SCHEMA
    paths: tuple[Path, ...]
    inputs: tuple[FileRef, ...]
    checks: tuple[CheckRecord, ...]
    stats: dict[str, Any] = field(default_factory=dict)
#

def check_labels(df: pl.DataFrame) -> tuple[CheckRecord, ...]:
    """ Invariants every labels table must satisfy. """
    placed = df.filter(pl.col("outcome") != "insufficient_data")
    pt, sl = (df.filter(pl.col("outcome") == o) for o in ("pt", "sl"))
    tests = {
        "one row per event":             df.get_column("event_id").is_unique().all(),
        "outcome values known":          df.get_column("outcome").is_in(list(OUTCOMES)).all(),
        "side is +1 or -1":              df.get_column("side").is_in([1, -1]).all(),
        "meta_label null iff insufficient": (df["meta_label"].is_null() == (df["outcome"] == "insufficient_data")).all(),
        "profit-takes have ret > 0":     (pt["ret"] > 0).all(),
        "stop-losses have ret < 0":      (sl["ret"] < 0).all(),
        "excursions non-negative":       ((placed["max_favorable"] >= 0) & (placed["max_adverse"] >= 0)).all(),
    }
    return tuple(CheckRecord(name=f"labels: {name}", status="pass" if bool(passed) else "fail")
                 for name, passed in tests.items())
#

def label_stats(df: pl.DataFrame) -> dict[str, Any]:
    placed = df.filter(pl.col("outcome") != "insufficient_data")
    n = max(placed.height, 1)
    by = placed.group_by("outcome").agg(pl.len(), pl.col("ret").mean().alias("mean_ret"))
    return {
        "events": df.height,
        "placed": placed.height,
        "share": {o: placed.filter(pl.col("outcome") == o).height / n for o in ("pt", "sl", "timeout")},
        "win_rate": placed["meta_label"].mean() if placed.height else None,
        "mean_ret": placed["ret"].mean() if placed.height else None,
        "mean_ret_by_outcome": {o: r for o, _, r in by.iter_rows()},
        "timeout_paths": dict(placed.filter(pl.col("outcome") == "timeout")
                              .group_by("path_type").len().sort("path_type").iter_rows()),
    }
#

def strategy_label(events_meta: ResearchMeta) -> str:
    """ The sampler's short label (e.g. "cusum_h3") from an events file's stored config. """
    if registry.has_model(events_meta.config_typeid):
        cfg = registry.get_model(events_meta.config_typeid).model_validate(events_meta.config)
        if hasattr(cfg, "label"):
            return str(cfg.label)
    return str(getattr(events_meta, "sampler", "events"))
#

def build_labels(
    config: SideLabelsConfig,
    *,
    source: str,
    market: str,
    symbol: str,
    research: Research | None = None,
    write: bool = True,
    log=_quiet,
) -> LabelsBuild:
    """ Side labels for every touch of `config.touches_hash` for one symbol. """
    if research is None:
        _, research = _defaults()
    ser = {"source": source, "market": market, "symbol": symbol}

    touch_files = research.scan(Stage.TOUCHES, config=config.touches_hash, **ser)
    if not touch_files:
        raise InputTouchesError(f"no touches for config={config.touches_hash} {source}/{market}/{symbol} "
                                f"in {research.root}")
    touch_meta = read_meta(touch_files[0][1])
    events_hash = touch_meta.input_hashes["events"]
    event_files = research.scan(Stage.EVENTS, config=events_hash, **ser)
    if not event_files:
        raise InputEventsError(f"the touch pass {config.touches_hash} was built from events {events_hash}, "
                               f"which aren't in {research.root}")
    strategy_id = f"{strategy_label(read_meta(event_files[0][1]))}_{config.side_rule}"

    touches = pl.concat([pl.read_parquet(p, hive_partitioning=False) for _, p in touch_files]).sort("t0")
    directions = pl.concat([pl.read_parquet(p, columns=["event_id", "direction"], hive_partitioning=False)
                            for _, p in event_files])
    labels = side_labels(touches, directions, config, strategy_id=strategy_id)
    checks = check_labels(labels)
    if failed := [c.name for c in checks if not c.ok]:
        raise AssertionError(f"label invariants failed: {failed}")
    stats = label_stats(labels)
    h = config.config_hash()
    log(f"{symbol}: {strategy_id}: {stats['placed']}/{stats['events']} labeled, config={h}")

    inputs = tuple(file_ref(p, lake_root=research.root, research_root=research.root)   # all research files
                   for _, p in (*touch_files, *event_files))
    if not write:
        return LabelsBuild(config_hash=h, strategy_id=strategy_id, labels=labels, paths=(),
                           inputs=inputs, checks=checks, stats=stats)

    version = code_version()
    dataset = SymbolKey(**ser)
    written: list[Path] = []
    for key, _ in touch_files:
        part = labels.filter(pl.col("t0").dt.year() == key.year)
        meta = LabelsMeta.for_config(config, dataset=dataset, year=key.year, rows=part.height,
                                     inputs=inputs, checks=checks, code_version=version,
                                     strategy_id=strategy_id)
        written.append(write_table(part, meta, research=research))
        log(f"  wrote {key.year}: {part.height} rows")
    return LabelsBuild(config_hash=h, strategy_id=strategy_id, labels=labels, paths=tuple(written),
                       inputs=inputs, checks=checks, stats=stats)
#-
