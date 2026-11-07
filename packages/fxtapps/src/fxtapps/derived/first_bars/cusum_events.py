"""CUSUM event detection on hourly bars (pipeline spec v2, section 4) - first pass.

Reads 1HOUR bars for a symbol across ALL years (state and volatility carry across year
boundaries), walks mid_close sequentially, and returns an events DataFrame. It does not write
to the lake yet: while `h` is being tuned, the output is a scratch artifact.

First-pass simplification: volatility is an EWMA of hourly returns (the spec's `vol_ewma_hourly`
estimator), standing in for the daily Garman-Klass series until the day boundary is decided.
"""
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
import math

import duckdb
import numpy as np
import polars as pl
from rich import print

# adjust this import to wherever build_bars_1m.py lives in your package
from .build_1min import lake_path


#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
@dataclass(frozen=True)
class CusumParams:
    h: float = 3.0                 # threshold, in cumulative std-devs of drift (spec range: 2-4)
    vol_span: int = 120            # EWMA span in bars (~5 trading days of hourly bars)
    warmup: int = 48               # bars used to seed the vol estimate; no events fire during warm-up
    max_gap_hours: float = 3.0     # a return spanning more than this (weekend/holiday) is a "gap return"
    reset_on_gap: bool = True      # zero the accumulators at a gap so events build within a session
    vol_floor: float = 1e-6        # max(vol, floor), in log-return units
    bar_hours: float = 1.0         # bar length; event_time = bar open time + bar length
#


#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
def load_bars(
    lake:Path,
    source:str,
    market:str,
    symbol:str,
    interval:str = "1HOUR"
) -> pl.DataFrame:
    """ All years of bars for one symbol/interval: columns time (UTC), mid_close.
    """
    pattern = lake_path(lake, "derived", source, market, symbol, interval, 2000).parent.parent / "year=*" / "*.parquet"
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    cols = con.execute(f"""SELECT epoch(time)::BIGINT AS t, mid_close
                           FROM read_parquet('{pattern}', hive_partitioning=false) ORDER BY time""").fetchnumpy()
    time = pl.from_epoch(pl.Series("time", cols["t"]), time_unit="s").dt.replace_time_zone("UTC")
    return pl.DataFrame({"time": time, "mid_close": cols["mid_close"]})
#


def detect_events(bars: pl.DataFrame, p:CusumParams = CusumParams()) -> pl.DataFrame:
    """ Two-sided CUSUM of vol-normalized log returns on `bars['mid_close']`.

        Point-in-time: each bar's return is normalized by the vol estimate through the PREVIOUS bar,
        and the estimate is updated only after the bar has been used. Event time is the close of the
        triggering bar. Both accumulators reset to zero whenever either side fires.
    """
    t = bars["time"].dt.epoch("s").to_numpy()
    price = bars["mid_close"].to_numpy()
    lam = 1.0 - 2.0 / (p.vol_span + 1)

    var, n_valid = 0.0, 0
    s_up = s_dn = 0.0
    rows = []  # (index, side, ret, z, vol)

    for i in range(1, len(price)):
        if (t[i] - t[i - 1]) / 3600.0 > p.max_gap_hours:
            # return spans a closed-market gap: leave vol untouched and don't accumulate it
            if p.reset_on_gap:
                s_up = s_dn = 0.0
            continue
        r = math.log(price[i] / price[i - 1])

        if n_valid < p.warmup:                       # seed vol with a running mean of r^2
            n_valid += 1
            var += (r * r - var) / n_valid
            continue

        vol = max(math.sqrt(var), p.vol_floor)      # vol as of the previous bar
        z = r / vol
        s_up = max(0.0, s_up + z)
        s_dn = min(0.0, s_dn + z)
        side = 1 if s_up > p.h else (-1 if s_dn < -p.h else 0)
        if side:
            rows.append((i, side, r, z, vol))
            s_up = s_dn = 0.0
        var = lam * var + (1.0 - lam) * r * r        # update AFTER using it

    idx = np.array([r[0] for r in rows], dtype=int)
    bar_time = bars["time"].gather(idx) if len(idx) else bars["time"].head(0)
    return pl.DataFrame({
        "event_time": bar_time + timedelta(hours=p.bar_hours),
        "bar_time": bar_time,
        "side": pl.Series([r[1] for r in rows], dtype=pl.Int8),
        "price_event": bars["mid_close"].gather(idx) if len(idx) else bars["mid_close"].head(0),
        "ret": pl.Series([r[2] for r in rows], dtype=pl.Float64),
        "z": pl.Series([r[3] for r in rows], dtype=pl.Float64),
        "vol": pl.Series([r[4] for r in rows], dtype=pl.Float64),
    })
#


def summarize(events: pl.DataFrame, bars: pl.DataFrame, p: CusumParams) -> None:
    """Frequency diagnostics: what you tune `h` against."""
    active_days = bars.select(pl.col("time").dt.date().n_unique()).item()
    n = events.height
    gaps_h = events["event_time"].diff().dt.total_seconds().drop_nulls() / 3600.0
    per_year = events.group_by(pl.col("event_time").dt.year().alias("year")).len().sort("year")
    print(f"[bold]h={p.h}[/bold]  events={n}  per active day={n / active_days:.2f}  "
          f"up={int((events['side'] == 1).sum())} down={int((events['side'] == -1).sum())}  "
          f"hours between events p10/median/p90 = "
          f"{gaps_h.quantile(0.1):.1f}/{gaps_h.median():.1f}/{gaps_h.quantile(0.9):.1f}")
    print("   per year: " + ", ".join(f"{y}: {c}" for y, c in per_year.iter_rows()))
#


def describe_clustering(events: pl.DataFrame) -> None:
    """Where in the week/day do events land? (UTC) Useful for spotting artifacts like Sunday-open clustering."""
    by_wd = events.group_by(pl.col("event_time").dt.weekday().alias("wd")).len().sort("wd")
    by_hr = events.group_by(pl.col("event_time").dt.hour().alias("hr")).len().sort("hr")
    names = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
    print("   by weekday: " + ", ".join(f"{names[w]} {c}" for w, c in by_wd.iter_rows()))
    print("   by hour (UTC): " + ", ".join(f"{h:02d}:{c}" for h, c in by_hr.iter_rows()))
#




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    LAKE = Path("datalake/lake")
    bars = load_bars(LAKE, "dukascopy", "forex", "EURJPY")
    print(f"{bars.height} hourly bars, {bars['time'].min()} .. {bars['time'].max()}")

    base = CusumParams()
    for h in (2.0, 3.0, 4.0, 5.0):          # sweep: which h gives the event frequency you want?
        p = replace(base, h=h)
        summarize(detect_events(bars, p), bars, p)

    # detail for one choice
    p = replace(base, h=3.0)
    events = detect_events(bars, p)
    describe_clustering(events)
    print(events.head(10))