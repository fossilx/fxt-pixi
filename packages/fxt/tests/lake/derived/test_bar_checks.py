""" fxt.lake.derived.bar_checks: clean data passes; each injected fault is caught by the
    checks meant for it.

Faults are applied with polars to copies placed at proper lake paths (placement checks
read the hive folders). Assertions are "these checks fail" (a subset), plus the clean-data
tests, which guard against checks failing when they shouldn't.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

import polars as pl
import pytest

from fxt.core.checks import BAD_STATUSES, Status, run_checks
from fxt.lake.derived import bar_checks as bc
from fxt.lake.derived.bars import TIME_COL, build_bars

quiet = lambda msg: None    # noqa: E731

PRE_1MIN  = [bc.placement("src"), bc.raw_tick_checks()]
POST      = [bc.placement("dst"), bc.bar_checks()]
PRE_1HOUR = [bc.placement("src", group="1MIN")]

Fault = Callable[[pl.DataFrame], pl.DataFrame]


def failing(report) -> set[str]:
    return set(report.failed)

def statuses(report) -> set[Status]:
    return {r.status for r in report.results.values()}

def at(df: pl.DataFrame, i: int, **values) -> pl.DataFrame:
    """ Set columns on row i (values may be expressions). """
    row = pl.int_range(pl.len()) == i
    return df.with_columns(**{c: pl.when(row).then(v).otherwise(pl.col(c)) for c, v in values.items()})

def first_row_where(df: pl.DataFrame, cond: pl.Expr, start: int = 100) -> int:
    """ Index of the first row >= start meeting cond (so a fault really changes something). """
    idx = df.with_row_index("_i").filter((pl.col("_i") >= start) & cond)["_i"]
    assert len(idx), "test data has no row meeting the condition"
    return int(idx[0])


#!================================================================================(80)
#! clean data
#!--------------------------------------------------------------------------------(80)
def test_clean_1min_passes_everything(built, make_ctx):
    ctx = make_ctx(built.raw, built.m1)
    report = run_checks(PRE_1MIN, ctx).merge(run_checks(POST, ctx))
    assert report.ok, report.failed
    assert statuses(report) == {Status.PASS}

def test_clean_1hour_passes_everything(built, make_ctx):
    ctx = make_ctx(built.m1, built.h1)
    report = run_checks(PRE_1HOUR, ctx).merge(run_checks(POST, ctx))
    assert statuses(report) == {Status.PASS}, report.failed

def test_timezone_aware_data_passes(fresh, ticks, make_ctx):
    raw = fresh.put(fresh.key("TICK"), ticks.with_columns(pl.col("dtime").dt.replace_time_zone("UTC")))
    m1 = fresh.path(fresh.key("1MIN"))
    build_bars(raw, m1, source_interval="TICK", interval="1MIN", log=quiet)
    ctx = make_ctx(raw, m1)
    report = run_checks(PRE_1MIN, ctx).merge(run_checks(POST, ctx))
    assert statuses(report) == {Status.PASS}, report.failed


#!================================================================================(80)
#! raw tick faults -> pre-checks
#!--------------------------------------------------------------------------------(80)
def _swap_adjacent_distinct(df: pl.DataFrame) -> pl.DataFrame:
    i = first_row_where(df, pl.col("dtime") < pl.col("dtime").shift(-1), start=1000)
    order = list(range(df.height)); order[i], order[i + 1] = order[i + 1], order[i]
    return df[order]

RAW_FAULTS: dict[str, tuple[Fault, set[str]]] = {
    "crossed quote": (
        lambda df: at(df, 500, bidPrice=pl.col("askPrice") + 0.01),
        {"raw/no crossed quotes"}),
    "out-of-order tick": (
        _swap_adjacent_distinct,
        {"raw/dtime sorted in file order"}),
    "duplicated ticks": (
        lambda df: pl.concat([df, df.head(50)]).sort("dtime", maintain_order=True),
        {"raw/duplicate ticks < 1e-06"}),
    "null price": (
        lambda df: at(df, 7, bidPrice=pl.lit(None, pl.Float64)),
        {"raw/no null prices/times"}),
    "non-positive price": (
        lambda df: at(df, 7, bidPrice=pl.lit(0.0)),
        {"raw/prices positive"}),
    "tick in the wrong year": (
        lambda df: pl.concat([df, df.tail(1).with_columns(dtime=pl.lit(datetime(2015, 1, 2, 10)).cast(df["dtime"].dtype))]),
        {"raw/timestamps within folder year"}),
}

@pytest.mark.parametrize("fault", RAW_FAULTS)
def test_raw_fault_is_caught(fault, fresh, ticks, make_ctx):
    fn, expected = RAW_FAULTS[fault]
    raw = fresh.put(fresh.key("TICK"), fn(ticks))
    report = run_checks(PRE_1MIN, make_ctx(raw))
    assert expected <= failing(report), f"expected {expected}, failed {failing(report)}"
    assert Status.ERROR not in statuses(report)

def test_empty_raw_file_fails_cleanly(fresh, ticks, make_ctx):
    """ An empty file should FAIL the relevant checks, not ERROR (crash) them. """
    raw = fresh.put(fresh.key("TICK"), ticks.head(0))
    report = run_checks(PRE_1MIN, make_ctx(raw))
    assert {"raw/has rows", "raw/timestamps within folder year"} <= failing(report)
    assert Status.ERROR not in statuses(report), report.failed


#!================================================================================(80)
#! bar faults -> post-checks
#!--------------------------------------------------------------------------------(80)
def _changed_close(df: pl.DataFrame, sides: tuple[str, ...]) -> pl.DataFrame:
    i = first_row_where(df, pl.col("bid_open") != pl.col("bid_close"))
    return at(df, i, **{f"{s}_close": pl.col(f"{s}_open") for s in sides})

def _bar_without_source(df: pl.DataFrame) -> pl.DataFrame:
    """ Move a bar to a Saturday (no ticks exist then), keeping it aligned and in order. """
    sat = df[TIME_COL].dt.truncate("1w").min() + timedelta(days=5, hours=12)   # weeks start Monday #type: ignore
    return at(df, 100, **{TIME_COL: pl.lit(sat).cast(df[TIME_COL].dtype)}).sort(TIME_COL)

BAR_FAULTS: dict[str, tuple[Fault, set[str]]] = {
    "dropped bar": (
        lambda df: df.filter(pl.int_range(pl.len()) != 100),
        {"bars/tick_count reconciles with source", "bars/volume totals match source",
         "bars/full recompute (every bar)"}),
    "high below low": (
        lambda df: at(df, 100, bid_high=pl.col("bid_low") - 1e-5),
        {"bars/bid OHLC consistent", "bars/full recompute (every bar)"}),
    "wrong bid close": (
        lambda df: _changed_close(df, ("bid",)),
        {"bars/mid open/close = (bid+ask)/2", "bars/full recompute (every bar)"}),
    "consistently wrong closes": (     # only a full recompute can see this one
        lambda df: _changed_close(df, ("bid", "ask", "mid")),
        {"bars/full recompute (every bar)"}),
    "unaligned time": (
        lambda df: at(df, 50, **{TIME_COL: pl.col(TIME_COL) + timedelta(seconds=30)}),
        {"bars/time aligned to interval", "bars/full recompute (every bar)"}),
    "rows out of order": (
        lambda df: df[[*range(10), 11, 10, *range(12, df.height)]],
        {"bars/time sorted"}),
    "duplicate bar": (
        lambda df: pl.concat([df.head(20), df.slice(19)]),
        {"bars/time unique"}),
    "volume off": (
        lambda df: at(df, 3, bid_volume=pl.col("bid_volume") + 1),
        {"bars/volume totals match source", "bars/full recompute (every bar)"}),
    "spread_mean outside [min, max]": (
        lambda df: at(df, 9, spread_mean=pl.col("spread_max") * 2),
        {"bars/spread non-negative, mean in [min,max]"}),
    "zero tick_count": (
        lambda df: at(df, 9, tick_count=pl.lit(0, pl.UInt32)),
        {"bars/tick_count > 0", "bars/tick_count reconciles with source"}),
    "bar with no source ticks": (
        _bar_without_source,
        {"bars/full recompute (every bar)"}),
}

@pytest.mark.parametrize("fault", BAR_FAULTS)
def test_1min_bar_fault_is_caught(fault, fresh, built, make_ctx):
    fn, expected = BAR_FAULTS[fault]
    raw = fresh.put(fresh.key("TICK"), built.raw)
    m1 = fresh.put(fresh.key("1MIN"), fn(pl.read_parquet(built.m1, hive_partitioning=False)))
    report = run_checks(POST, make_ctx(raw, m1))
    assert expected <= failing(report), f"expected {expected}, failed {failing(report)}"
    assert Status.ERROR not in statuses(report), report.failed

@pytest.mark.parametrize("fault", ["dropped bar", "wrong bid close", "unaligned time", "volume off"])
def test_1hour_bar_fault_is_caught(fault, fresh, built, make_ctx):
    fn, expected = BAR_FAULTS[fault]
    m1 = fresh.put(fresh.key("1MIN"), built.m1)
    h1 = fresh.put(fresh.key("1HOUR"), fn(pl.read_parquet(built.h1, hive_partitioning=False)))
    report = run_checks(POST, make_ctx(m1, h1))
    assert expected <= failing(report), f"expected {expected}, failed {failing(report)}"

def test_fault_report_on_timezone_aware_bars_does_not_error(fresh, ticks, make_ctx):
    """ Failure details include timestamps; tz-aware values must not need pytz. """
    raw = fresh.put(fresh.key("TICK"), ticks.with_columns(pl.col("dtime").dt.replace_time_zone("UTC")))
    m1 = fresh.path(fresh.key("1MIN"))
    build_bars(raw, m1, source_interval="TICK", interval="1MIN", log=quiet)
    fresh.put(fresh.key("1MIN"), BAR_FAULTS["dropped bar"][0](pl.read_parquet(m1)))
    report = run_checks(POST, make_ctx(raw, m1))
    assert "bars/full recompute (every bar)" in failing(report)
    assert not {k for k, r in report.results.items() if r.status in BAD_STATUSES - {Status.FAIL}}

def test_missing_output_errors_instead_of_passing(fresh, built, make_ctx):
    raw = fresh.put(fresh.key("TICK"), built.raw)
    report = run_checks(POST, make_ctx(raw, fresh.path(fresh.key("1MIN"))))   # path exists, file doesn't
    assert not report.ok
    assert all(r.status is Status.ERROR for r in report.results.values())