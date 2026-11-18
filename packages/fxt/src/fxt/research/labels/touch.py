'''
touch

The touch pass (ML pipeline spec §6.1 step 1). Pure: events + bars in,
one touch row per event out, no files. See TripleBarrierTouchConfig for
how the barriers are placed.

    vol    = barrier_vol(hourly, cfg)                       # aligned to hourly rows
    out    = compute_touches(events, hourly, minute, cfg, ticks=..., minute_years=...)

Output columns (TOUCH_SCHEMA), one row per event, in event order:
    event_id, t0, price_t0
    vol, half_width, upper, lower, vertical_time    barrier setup (null if not placed)
    touch           upper | lower | vertical | insufficient_data
    reason          why insufficient: warmup | end_of_data | minute_data_missing | no_minute_bars
    t1              exit time: start of the touching 1MIN bar, or vertical_time on a timeout
    exit_price      the barrier level, the bar's open if it opened past the barrier (a gap),
                    or the last scanned bar's close on a timeout
    exit_gap        True if the exit was a gap open past the barrier
    resolution      bar | tick | ohlc_fallback  (how a touch was decided; null for timeouts)
    ret             log(exit_price / price_t0): unsided, gross, mid
    hours_to_exit   business hours from t0 to t1 (counted on hourly bars of data)
    max_up, max_down  largest log move above / below price_t0 from t0 through the exit bar (>= 0)

Same-minute ambiguity (one 1MIN bar crosses both barriers) is resolved with
ticks when `ticks` is given: the first tick whose mid is at/beyond a barrier
wins. If no tick crosses, or cfg.ambiguity == "ohlc", the bar's open->close
direction decides (equal open and close: the barrier nearer the open).
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import numpy as np
import polars as pl

from fxt.research.models.touches import TripleBarrierTouchConfig

__all__ = ["EventsBarsMismatch", "MinuteBars", "TOUCH_SCHEMA", "TickLookup", "barrier_vol",
           "compute_touches", "epoch_s"]

TOUCH_SCHEMA: dict[str, pl.DataType] = {
    "event_id":      pl.String(),
    "t0":            pl.Datetime("us", "UTC"),
    "price_t0":      pl.Float64(),
    "vol":           pl.Float64(),
    "half_width":    pl.Float64(),
    "upper":         pl.Float64(),
    "lower":         pl.Float64(),
    "vertical_time": pl.Datetime("us", "UTC"),
    "touch":         pl.String(),
    "reason":        pl.String(),
    "t1":            pl.Datetime("us", "UTC"),
    "exit_price":    pl.Float64(),
    "exit_gap":      pl.Boolean(),
    "resolution":    pl.String(),
    "ret":           pl.Float64(),
    "hours_to_exit": pl.Float64(),
    "max_up":        pl.Float64(),
    "max_down":      pl.Float64(),
}
TOUCHES = ("upper", "lower", "vertical", "insufficient_data")


class EventsBarsMismatch(ValueError):
    """ The events weren't built from these bars (missing bar, or the bars were rebuilt). """
REASONS = ("warmup", "end_of_data", "minute_data_missing", "no_minute_bars")


#!================================================================================(80)
#! inputs
#!--------------------------------------------------------------------------------(80)
def epoch_s(times: pl.Series) -> np.ndarray:
    """ UTC epoch seconds of a Datetime series (naive values are taken as UTC). """
    tz = times.dtype.time_zone                                     # type: ignore[union-attr]
    t = times.dt.replace_time_zone("UTC") if tz is None else times.dt.convert_time_zone("UTC")
    return t.dt.epoch("s").to_numpy()
#

@dataclass(frozen=True)
class MinuteBars:
    """ 1MIN mid OHLC as numpy arrays, sorted by open time (epoch seconds, UTC). """
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray

    @classmethod
    def from_frame(cls, bars: pl.DataFrame) -> MinuteBars:
        df = bars.sort("time")
        if df.get_column("time").is_duplicated().any():
            raise ValueError("1MIN bars have duplicate timestamps")
        return cls(t=epoch_s(df.get_column("time")),
                   **{k: df.get_column(f"mid_{name}").to_numpy()
                      for k, name in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))})
#

class TickLookup(Protocol):
    def first_touch(self, start_s: int, end_s: int, upper: float, lower: float) -> int | None:
        """ +1 / -1 for the first tick in [start_s, end_s) whose mid is at/above `upper` /
            at/below `lower`; None if none crosses. Raises if the ticks aren't available.
        """
        ...
#


#!================================================================================(80)
#! barrier vol
#!--------------------------------------------------------------------------------(80)
def barrier_vol(hourly: pl.DataFrame, cfg: TripleBarrierTouchConfig) -> np.ndarray:
    """ EWMA vol of hourly mid_close log returns, aligned to `hourly` rows (sorted by time).
        The value at row i INCLUDES bar i's return. Gap returns (> max_gap_hours) are
        skipped and the previous value carried. NaN until vol_warmup returns are seen.
    """
    t = epoch_s(hourly.get_column("time"))
    price = hourly.get_column("mid_close").to_numpy()
    lam = 1.0 - 2.0 / (cfg.vol_span + 1)
    out = np.full(len(price), np.nan)
    var, n_valid, last = 0.0, 0, float("nan")
    for i in range(1, len(price)):
        if (t[i] - t[i - 1]) / 3600.0 > cfg.max_gap_hours:
            out[i] = last
            continue
        r = math.log(price[i] / price[i - 1])
        if n_valid < cfg.vol_warmup:
            n_valid += 1
            var += (r * r - var) / n_valid
        else:
            var = lam * var + (1.0 - lam) * r * r
        if n_valid >= cfg.vol_warmup:
            last = max(math.sqrt(var), cfg.vol_floor)
        out[i] = last
    return out
#


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
def compute_touches(
    events: pl.DataFrame,
    hourly: pl.DataFrame,
    minute: MinuteBars,
    cfg: TripleBarrierTouchConfig,
    *,
    ticks: TickLookup | None = None,
    minute_years: set[int] | None = None,
) -> pl.DataFrame:
    """ One touch row per event (TOUCH_SCHEMA).

        events        event_id, t0, price_t0 (core event columns)
        hourly        time (bar open), mid_close: every hourly bar the events came from
        minute        1MIN bars covering the scan windows
        ticks         for same-minute ambiguity (required when cfg.ambiguity == "ticks"
                      and an ambiguous bar is found)
        minute_years  years that HAVE 1MIN data; a window touching any other year is
                      "insufficient_data / minute_data_missing" instead of silently
                      scanning a truncated window. None = trust `minute` as complete.

        Raises EventsBarsMismatch if an event's bar isn't in `hourly`, or its price_t0 doesn't
        match that bar's mid_close: the events were built from different bars (stale).
    """
    hourly = hourly.sort("time")
    th = epoch_s(hourly.get_column("time"))
    hclose = hourly.get_column("mid_close").to_numpy()
    vol = barrier_vol(hourly, cfg)
    bar_s = 3600
    N = cfg.vertical_bars
    mt, mo, mh, ml, mc = minute.t, minute.o, minute.h, minute.l, minute.c

    ev_id = events.get_column("event_id").to_list()
    ev_t0 = epoch_s(events.get_column("t0"))
    ev_px = events.get_column("price_t0").to_numpy()
    ev_idx = np.searchsorted(th, ev_t0 - bar_s)

    bad = (ev_idx >= len(th)) | (th[np.minimum(ev_idx, len(th) - 1)] != ev_t0 - bar_s)
    if bad.any():
        k = int(np.argmax(bad))
        raise EventsBarsMismatch(f"event {ev_id[k]} (t0 {_ts(int(ev_t0[k]))}) has no matching hourly bar: "
                         f"the events and bars don't come from the same data")
    stale = hclose[ev_idx] != ev_px
    if stale.any():
        k = int(np.argmax(stale))
        raise EventsBarsMismatch(f"event {ev_id[k]}: price_t0 {ev_px[k]} != bar mid_close {hclose[ev_idx[k]]}; "
                         f"the bars were rebuilt after these events were made (rebuild the events)")

    cols: dict[str, list] = {c: [] for c in TOUCH_SCHEMA}
    for n in range(len(ev_id)):
        i, px, t0 = int(ev_idx[n]), float(ev_px[n]), int(ev_t0[n])
        row = dict.fromkeys(TOUCH_SCHEMA)
        row.update(event_id=ev_id[n], t0=t0, price_t0=px)
        _resolve(row, i, px, t0, vol, th, N, bar_s, cfg, minute_years,
                 mt, mo, mh, ml, mc, ticks)
        for c in TOUCH_SCHEMA:
            cols[c].append(row[c])

    for c in ("t0", "vertical_time", "t1"):
        cols[c] = [None if v is None else datetime.fromtimestamp(v, UTC) for v in cols[c]]
    return pl.DataFrame(cols, schema=TOUCH_SCHEMA)
#

def _ts(s: int) -> str:
    return datetime.fromtimestamp(s, UTC).isoformat()
#

def _resolve(row, i, px, t0, vol, th, N, bar_s, cfg, minute_years, mt, mo, mh, ml, mc, ticks) -> None:
    """ Fill one row in place (the first-pass loop body, kept close to the original). """
    v = float(vol[i])
    if math.isnan(v):                                              # vol not warm yet
        row.update(touch="insufficient_data", reason="warmup")
        return
    j = i + N
    if j >= len(th):
        row.update(touch="insufficient_data", reason="end_of_data")
        return
    vertical_s = int(th[j]) + bar_s
    half = cfg.mult * v
    upper, lower = px * math.exp(half), px * math.exp(-half)
    row.update(vol=v, half_width=half, upper=upper, lower=lower, vertical_time=vertical_s)

    if minute_years is not None:
        y0, y1 = datetime.fromtimestamp(t0, UTC).year, datetime.fromtimestamp(vertical_s - 1, UTC).year
        if any(y not in minute_years for y in range(y0, y1 + 1)):
            row.update(touch="insufficient_data", reason="minute_data_missing")
            return

    s = int(np.searchsorted(mt, t0, "left"))
    e = int(np.searchsorted(mt, vertical_s, "left"))
    if e <= s:
        row.update(touch="insufficient_data", reason="no_minute_bars")
        return

    up = mh[s:e] >= upper
    dn = ml[s:e] <= lower
    hit = up | dn
    resolution = "bar"
    if hit.any():
        k = int(hit.argmax())
        idx = s + k
        if up[k] and dn[k]:                                        # both barriers in one 1MIN bar
            lab = None
            if cfg.ambiguity == "ticks":
                if ticks is None:
                    raise ValueError("an ambiguous 1MIN bar needs ticks (cfg.ambiguity='ticks'), "
                                     "but no tick lookup was given")
                lab = ticks.first_touch(int(mt[idx]), int(mt[idx]) + 60, upper, lower)
            if lab is not None:
                label, resolution = lab, "tick"
            else:                                                  # open -> close direction (v2 §5.3)
                if mc[idx] != mo[idx]:
                    label = 1 if mc[idx] > mo[idx] else -1
                else:
                    label = 1 if abs(mo[idx] - upper) < abs(mo[idx] - lower) else -1
                resolution = "ohlc_fallback"
        else:
            label = 1 if up[k] else -1
        exit_s, last = int(mt[idx]), idx
        if label == 1:
            gap = bool(mo[idx] >= upper)
            exit_px = float(mo[idx]) if gap else upper
        else:
            gap = bool(mo[idx] <= lower)
            exit_px = float(mo[idx]) if gap else lower
        hour0 = exit_s - exit_s % bar_s
        jx = int(np.searchsorted(th, hour0))
        hours = (jx - (i + 1)) + (exit_s - hour0) / 3600.0
        touch = "upper" if label == 1 else "lower"
    else:                                                          # vertical: last scanned bar's close
        touch, exit_s, last, gap, resolution = "vertical", vertical_s, e - 1, False, None
        exit_px, hours = float(mc[e - 1]), float(N)

    row.update(
        touch=touch, t1=exit_s, exit_price=exit_px, exit_gap=gap, resolution=resolution,
        ret=math.log(exit_px / px), hours_to_exit=hours,
        max_up=max(0.0, math.log(float(mh[s:last + 1].max()) / px)),
        max_down=max(0.0, -math.log(float(ml[s:last + 1].min()) / px)),
    )
#-
