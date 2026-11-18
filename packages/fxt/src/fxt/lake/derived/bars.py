#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
# stop pylance from being annoying by adding this to end of line:  # type: ignore

"""
Bar generation: deterministic transforms from raw ticks to bars, and from bars
to coarser bars.

    raw TICK  --ticks_to_bars-->  1MIN  --resample_bars-->  5MIN, 15MIN, 1HOUR, ...

    build_bars(src, dst, source_interval="TICK", interval="1MIN")
    build_bars(src, dst, source_interval="1MIN", interval="1HOUR")

Algorithm (both transforms):
  - windows are left-closed and labelled by their open time: the 10:05 bar holds
    ticks in [10:05:00, 10:06:00). Windows are aligned to the UTC epoch.
  - open/close are the first/last row in *file order*. The raw pre-checks
    guarantee file order is time order, so ties on the same millisecond resolve
    to the order the source recorded them (same rule as the original DuckDB
    builder's (dtime, file_row_number) key).
  - empty windows produce no bar (bars are sparse; weekends/gaps are absent).
  - mid = (bid + ask) / 2 per tick; spread = ask - bid per tick.
  - resampling: spread_mean is tick-weighted, so a 1HOUR spread_mean equals the
    mean over the hour's ticks (a plain mean of minute means would over-weight
    quiet minutes); volumes and tick_count sum; open/close are first/last bar.

Bar schema (BAR_SCHEMA, in this order):
    time                            bar open time (source timezone kept, UTC)
    {bid,ask,mid}_{open,high,low,close}
    bid_volume, ask_volume, tick_count
    spread_mean, spread_min, spread_max

Engine notes: input that is already sorted is streamed (constant memory, ~0.5 GB
for a 25M-tick year in testing). Unsorted input falls back to an in-memory
stable sort and is logged, since it means the raw pre-checks were bypassed.
"""

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Callable

import polars as pl

__all__ = [
    "BarInterval", "INTERVALS", "get_interval", "TIME_COL", "TICK_TIME_COL", "BAR_SCHEMA",
    "TICKS_TO_BARS", "RESAMPLE_BARS", "ticks_to_bars", "resample_bars",
    "BuildResult", "build_bars",
]

logger = logging.getLogger(__name__)
LogFn = Callable[[str], None]


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
TICK_INTERVAL = "TICK"
TICK_TIME_COL = "dtime"          # raw tick schema: dtime, bidPrice, askPrice, bidVolume, askVolume
TIME_COL      = "time"           # bar open time
SIDES         = ("bid", "ask", "mid")
OHLC          = ("open", "high", "low", "close")


@dataclass(frozen=True)
class BarInterval:
    """ A bar width. `name` is the lake's interval folder value (dukascopy_python
        naming), `every` the polars duration, `seconds` the width for checks/SQL.
    """
    name:    str
    every:   str
    seconds: int
#

#! Only widths that divide an hour evenly: their epoch-aligned windows are the
#! conventional ones. Daily (and 4H) FX bars usually close at 17:00 New York,
#! which moves in UTC with DST; add those with an explicit tz + offset when needed.
INTERVALS: dict[str, BarInterval] = {i.name: i for i in (
    BarInterval("1MIN",  "1m",  60),
    BarInterval("5MIN",  "5m",  300),
    BarInterval("15MIN", "15m", 900),
    BarInterval("30MIN", "30m", 1800),
    BarInterval("1HOUR", "1h",  3600),
)}

def get_interval(name: str) -> BarInterval:
    try:
        return INTERVALS[name]
    except KeyError:
        raise ValueError(f"unknown bar interval {name!r}; known: {', '.join(INTERVALS)}") from None
#


BAR_SCHEMA: dict[str, pl.DataType] = {
    TIME_COL: pl.Datetime("us"),          # unit pinned; timezone carried over from the source
    **{f"{s}_{x}": pl.Float64() for s in SIDES for x in OHLC},
    "bid_volume":  pl.Float64(),
    "ask_volume":  pl.Float64(),
    "tick_count":  pl.UInt32(),
    "spread_mean": pl.Float64(),
    "spread_min":  pl.Float64(),
    "spread_max":  pl.Float64(),
}

#! bump the version when a transform's output would change (stored in bar meta)
TICKS_TO_BARS = ("ticks_to_bars", 1)
RESAMPLE_BARS = ("resample_bars", 1)


#!================================================================================(80)
#! transforms (pure: LazyFrame in, LazyFrame out)
#!--------------------------------------------------------------------------------(80)
def ticks_to_bars(ticks: pl.LazyFrame, interval: BarInterval | str) -> pl.LazyFrame:
    """ Raw ticks -> bars. `ticks` must be in time order (see _prepare). """
    iv = interval if isinstance(interval, BarInterval) else get_interval(interval)
    price = {
        "bid": pl.col("bidPrice"),
        "ask": pl.col("askPrice"),
        "mid": (pl.col("bidPrice") + pl.col("askPrice")) / 2,
    }
    spread = pl.col("askPrice") - pl.col("bidPrice")
    return (
        ticks
        .group_by_dynamic(TICK_TIME_COL, every=iv.every, closed="left", label="left")
        .agg(
            *[e for s, p in price.items() for e in (
                p.first().alias(f"{s}_open"),
                p.max().alias(f"{s}_high"),
                p.min().alias(f"{s}_low"),
                p.last().alias(f"{s}_close"),
            )],
            pl.col("bidVolume").sum().alias("bid_volume"),
            pl.col("askVolume").sum().alias("ask_volume"),
            pl.len().alias("tick_count"),
            spread.mean().alias("spread_mean"),
            spread.min().alias("spread_min"),
            spread.max().alias("spread_max"),
        )
        .rename({TICK_TIME_COL: TIME_COL})
    )
#

def resample_bars(bars: pl.LazyFrame, interval: BarInterval | str) -> pl.LazyFrame:
    """ Bars -> coarser bars. `bars` must be in time order (see _prepare). """
    iv = interval if isinstance(interval, BarInterval) else get_interval(interval)
    return (
        bars
        .group_by_dynamic(TIME_COL, every=iv.every, closed="left", label="left")
        .agg(
            *[e for s in SIDES for e in (
                pl.col(f"{s}_open").first(),
                pl.col(f"{s}_high").max(),
                pl.col(f"{s}_low").min(),
                pl.col(f"{s}_close").last(),
            )],
            pl.col("bid_volume").sum(),
            pl.col("ask_volume").sum(),
            pl.col("tick_count").sum(),
            #! tick-weighted: equals the mean over the underlying ticks
            ((pl.col("spread_mean") * pl.col("tick_count")).sum() / pl.col("tick_count").sum())
                .alias("spread_mean"),
            pl.col("spread_min").min(),
            pl.col("spread_max").max(),
        )
    )
#

def _conform(bars: pl.LazyFrame) -> pl.LazyFrame:
    """ Exact output schema: column order, dtypes, time unit (timezone kept). """
    return bars.select(
        pl.col(TIME_COL).dt.cast_time_unit("us"),
        *[pl.col(c).cast(t) for c, t in BAR_SCHEMA.items() if c != TIME_COL],
    )
#


#!================================================================================(80)
#! building (files)
#!--------------------------------------------------------------------------------(80)
@dataclass(frozen=True)
class BuildResult:
    """ What a build did; the meta step turns this into the output's metadata. """
    src:             Path
    dst:             Path
    source_interval: str
    interval:        str
    transform:       str
    version:         int
    params:          dict[str, Any] = field(default_factory=dict)
    rows:            int = 0
    sorted_input:    bool = True       # False -> input needed sorting (pre-checks bypassed?)
#

def _is_sorted(lf: pl.LazyFrame, col: str) -> bool:
    """ One streaming pass; nulls count as unsorted. """
    return bool(lf.select(
        (pl.col(col).diff().drop_nulls() >= pl.duration(microseconds=0)).all()
        & pl.col(col).is_not_null().all()
    ).collect(engine="streaming").item())

def _prepare(lf: pl.LazyFrame, col: str, log: LogFn) -> tuple[pl.LazyFrame, bool]:
    """ Mark sorted input as sorted (keeps file order for ties, allows streaming);
        otherwise stable-sort it in memory so ties still keep file order.
    """
    dtype = lf.collect_schema()[col]
    if isinstance(dtype, pl.Datetime) and dtype.time_zone not in (None, "UTC"):
        lf = lf.with_columns(pl.col(col).dt.convert_time_zone("UTC"))
    if _is_sorted(lf, col):
        return lf.with_columns(pl.col(col).set_sorted()), True
    log(f"! {col} is not in time order: sorting in memory (were the pre-checks bypassed?)")
    return lf.sort(col, maintain_order=True), False
#

def build_bars(
    src: Path,
    dst: Path,
    *,
    source_interval: str,
    interval: str,
    log: LogFn | None = None,
    compression_level: int = 3,
) -> BuildResult:
    """ src (raw TICK file, or a bar file of `source_interval`) -> dst bars.
        Writes to a temp file and renames, so a crash never leaves a partial dst.
    """
    log = log or logger.info
    iv = get_interval(interval)

    if source_interval == TICK_INTERVAL:
        name, version = TICKS_TO_BARS
        time_col, transform = TICK_TIME_COL, ticks_to_bars
    else:
        src_iv = get_interval(source_interval)
        if iv.seconds <= src_iv.seconds or iv.seconds % src_iv.seconds:
            raise ValueError(f"can't build {interval} from {source_interval}: "
                             f"target must be a whole multiple of the source width")
        name, version = RESAMPLE_BARS
        time_col, transform = TIME_COL, resample_bars

    lf, was_sorted = _prepare(pl.scan_parquet(src, hive_partitioning=False), time_col, log)
    out = _conform(transform(lf, iv))

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    out.sink_parquet(tmp, compression="zstd", compression_level=compression_level,
                     engine="streaming")
    tmp.replace(dst)

    rows = pl.scan_parquet(dst, hive_partitioning=False).select(pl.len()).collect().item()
    log(f"wrote {rows:,} {interval} bars")
    return BuildResult(
        src=src, dst=dst, source_interval=source_interval, interval=interval,
        transform=name, version=version, params={"every": iv.every},
        rows=rows, sorted_input=was_sorted,
    )
#


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from pathlib import Path
    from rich import print

    print()
    print(f"hi2u ~ from [bold cyan]{Path(__file__).name}~[/]")
    print()


