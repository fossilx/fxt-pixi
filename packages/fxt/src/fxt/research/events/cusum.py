'''
cusum

Two-sided CUSUM event detection (ML pipeline spec §5.1). Pure: bars in,
events out, no files. See CusumEventsConfig for the algorithm and parameters.

    events = detect_cusum(bars, CusumEventsConfig())   # bars: time (open, UTC) + mid_close
    stats  = event_stats(events, bars)                 # what h gets tuned against

Output columns (one row per fire):
    t0          close of the triggering bar (bar open + bar width), UTC
    direction   +1 if the up accumulator fired, -1 if the down one did
    price_t0    `price` (mid close) of the triggering bar
    ret         the triggering bar's log return
    z           ret / vol
    vol         the vol estimate used (through the previous bar)

Bars are walked in time order across every year given, so vol and the
accumulators carry over year boundaries. Weekend/holiday gaps (a return
spanning more than max_gap_hours) are skipped: the return isn't used, vol
isn't updated, and with reset_on_gap the accumulators restart, so events
build within a session.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

import numpy as np
import polars as pl

from fxt.research.models.events import CusumEventsConfig

__all__ = ["EVENT_SCHEMA", "detect_cusum", "event_stats", "prepare_bars"]

TIME_COL = "time"

EVENT_SCHEMA: dict[str, pl.DataType] = {
    "t0":        pl.Datetime("us", "UTC"),
    "direction": pl.Int8(),
    "price_t0":  pl.Float64(),
    "ret":       pl.Float64(),
    "z":         pl.Float64(),
    "vol":       pl.Float64(),
}


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def prepare_bars(bars: pl.DataFrame, price: str = "mid_close") -> pl.DataFrame:
    """ (time, price) in UTC, sorted, checked: times unique, prices positive and finite. """
    missing = {TIME_COL, price} - set(bars.columns)
    if missing:
        raise ValueError(f"bars are missing column(s) {sorted(missing)}")
    df = bars.select(TIME_COL, price)
    dtype = df.schema[TIME_COL]
    if not isinstance(dtype, pl.Datetime):
        raise TypeError(f"bars.{TIME_COL} must be a Datetime, got {dtype}")
    t = pl.col(TIME_COL).cast(pl.Datetime("us", dtype.time_zone))
    t = t.dt.replace_time_zone("UTC") if dtype.time_zone is None else t.dt.convert_time_zone("UTC")
    df = df.with_columns(t).sort(TIME_COL)

    if df.get_column(TIME_COL).is_duplicated().any():
        raise ValueError("bars have duplicate timestamps")
    p = df.get_column(price)
    if p.null_count() or not p.is_finite().all() or (p <= 0).any():
        raise ValueError(f"bars.{price} must be positive and finite (no nulls)")
    return df
#


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
def detect_cusum(bars: pl.DataFrame, cfg: CusumEventsConfig) -> pl.DataFrame:
    """ Events (EVENT_SCHEMA) from bars with `time` (bar open) and `cfg.price`. """
    df = prepare_bars(bars, cfg.price)
    t = df.get_column(TIME_COL).dt.epoch("us").to_numpy()
    price = df.get_column(cfg.price).to_numpy()
    max_gap_us = cfg.max_gap_hours * 3600e6
    lam = 1.0 - 2.0 / (cfg.vol_span + 1)

    var, n_valid = 0.0, 0
    s_up = s_dn = 0.0
    idx: list[int] = []
    out_dir: list[int] = []
    out_ret: list[float] = []
    out_z: list[float] = []
    out_vol: list[float] = []

    for i in range(1, len(price)):
        if t[i] - t[i - 1] > max_gap_us:
            #! return spans a closed-market gap: don't use it, don't update vol
            if cfg.reset_on_gap:
                s_up = s_dn = 0.0
            continue
        r = math.log(price[i] / price[i - 1])

        if n_valid < cfg.warmup:                     # seed vol with a running mean of r^2
            n_valid += 1
            var += (r * r - var) / n_valid
            continue

        vol = max(math.sqrt(var), cfg.vol_floor)    # vol as of the previous bar
        z = r / vol
        s_up = max(0.0, s_up + z)
        s_dn = min(0.0, s_dn + z)
        fired = 1 if s_up > cfg.h else (-1 if s_dn < -cfg.h else 0)
        if fired:
            idx.append(i)
            out_dir.append(fired)
            out_ret.append(r)
            out_z.append(z)
            out_vol.append(vol)
            s_up = s_dn = 0.0
        var = lam * var + (1.0 - lam) * r * r        # update AFTER using it

    rows = df[idx] if idx else df.head(0)
    return pl.DataFrame({
        "t0":        rows.get_column(TIME_COL) + timedelta(seconds=cfg.bar_seconds),
        "direction": pl.Series(out_dir, dtype=pl.Int8),
        "price_t0":  rows.get_column(cfg.price),
        "ret":       pl.Series(out_ret, dtype=pl.Float64),
        "z":         pl.Series(out_z, dtype=pl.Float64),
        "vol":       pl.Series(out_vol, dtype=pl.Float64),
    }).cast(EVENT_SCHEMA)  # type: ignore[arg-type]
#


#!================================================================================(80)
#! diagnostics
#!--------------------------------------------------------------------------------(80)
def event_stats(events: pl.DataFrame, bars: pl.DataFrame) -> dict[str, Any]:
    """ Frequency diagnostics for tuning `h` (event rate, spacing, balance, per year). """
    active_days = bars.select(pl.col(TIME_COL).dt.date().n_unique()).item()
    n = events.height
    gaps_h = (events.get_column("t0").diff().dt.total_seconds().drop_nulls() / 3600.0)
    q = (lambda x: float(gaps_h.quantile(x))) if gaps_h.len() else (lambda x: float("nan"))
    per_year = events.group_by(pl.col("t0").dt.year().alias("year")).len().sort("year")
    return {
        "events": n,
        "bars": bars.height,
        "active_days": active_days,
        "per_active_day": n / active_days if active_days else float("nan"),
        "up": int((events.get_column("direction") == 1).sum()),
        "down": int((events.get_column("direction") == -1).sum()),
        "gap_hours_p10": q(0.1),
        "gap_hours_median": q(0.5),
        "gap_hours_p90": q(0.9),
        "per_year": dict(per_year.iter_rows()),
    }
#
