"""Triple-barrier labeling (pipeline spec v2, sections 5-6) - first pass.

Inputs : CUSUM events (cusum_events.detect_events), 1HOUR bars (barrier volatility and the
         business-hours clock), 1MIN bars (touch detection), raw ticks (same-minute ambiguity only).
Output : one row per event with the primary label (+1 upper / -1 lower / 0 vertical) and the
         secondary features from section 6.2. Not written to the lake yet; while parameters are
         being tuned this is a scratch artifact.

Conventions
- Price series: canonical mid (mid_open/high/low/close of the bars; (bid+ask)/2 for ticks).
- Event time = close of the triggering hourly bar; scanning starts with the 1MIN bar that opens then.
- Horizontal barriers are log-space: upper = px * exp(+pt_mult * vol), lower = px * exp(-sl_mult * vol),
  where vol is the hourly EWMA vol INCLUDING the event bar (known at event time).
- Vertical barrier = N business hours, counted as N hourly bars of the data (so weekends/holidays
  are skipped automatically). The window scanned is [event_time, vertical_time).
- Barrier width scales with the horizon: a move over N hours is ~ vol * sqrt(N), so pt_mult / sl_mult
  should be on the order of sqrt(N) (see LabelParams.from_horizon), not ~1.
- If a bar OPENS beyond a barrier (a gap), the exit price is that open, not the barrier level.
- Events too close to the end of the data are kept, with label null and status 'insufficient_data'.
"""
'''

# What it tells you

- Timeouts at k=1: for a driftless random walk, the chance of not touching ±1 horizon-sigma within the 
  horizon is about 37%. You got 39-42%, so the volatility scaling is behaving sensibly on real data.

- Timeouts at k=0.5: you see 4-5%, a bit above the random-walk figure. A small error in the volatility
  estimate moves the no-touch probability a lot at tight barriers, so I wouldn’t read much into it.

- Up and down share: the shares are nearly symmetric at k=1. At k=0.5 up leads by a few points (50% 
  vs 45%), which probably reflects EURJPY’s strong uptrend over these years. It’s worth remembering 
  when you evaluate models, since a “predict up” bias would look better than it is.

- Ambiguity and gaps: same-minute ambiguity is essentially nonexistent (one case), and gap exits are 
  only about 1% of events. So skipping pre-weekend events isn’t worth doing now.

Verification: all checks passed, including the tick spot check.

Choosing a working default: 
I’d go with N=48, k=1.0. Its median hold is about a day, which sits inside your “hours to a week” range. 
It keeps timeouts at about 40%, which are informative as quiet or ranging outcomes. The k=0.5 configs are
almost a pure up-or-down call on tight barriers. N=120 holds for 2+ days and stacks more overlap between
events. You can revisit this later, since labels are cheap to recompute, but don’t tune k and N on model
performance over your full history.

path_type: with the placeholder thresholds, “mixed” is the largest bucket (about 44% of timeouts at k=1).
That’s expected from thresholds with a gap between bands, and §6.4’s scatter and clustering step will 
replace them. It doesn’t block anything.

Next: the overlap. With a median of 8 hours between events and about 22 hours of hold, each label overlaps 
roughly three neighbors. A baseline needs the §7 sample weights (concurrency-based uniqueness) and purged 
walk-forward splits, or it will overstate its skill. 

I’d build in this order:
- Lock the defaults (h=3, N=48, k=1.0).
- Write the concurrency and weights step. It’s small and uses only event_time and exit_time.
- Build a minimal feature set at each event, such as multi-horizon returns, volatility ratios, spread, and hour of day.
- Train a LightGBM baseline with purged walk-forward evaluation.


-- 

For now, using the suggested weights:

(h=3, N=48)


'''





from dataclasses import dataclass, replace
from pathlib import Path
import math

import duckdb
import numpy as np
import polars as pl
from rich import print

# adjust these imports to wherever the sibling scripts live in your package
from .build_1min import Check, lake_path, report
from .cusum_events import CusumParams, detect_events, load_bars




@dataclass(frozen=True)
class LabelParams:
    pt_mult: float = 7.0           # profit-take distance, in hourly-vol units
    sl_mult: float = 7.0           # stop-loss distance, in hourly-vol units (independent tunable)
    vertical_hours: int = 48       # business hours until the vertical barrier
    vol_span: int = 24             # EWMA span (bars) of the barrier-width volatility: reactive, ~1 day
    vol_warmup: int = 24
    max_gap_hours: float = 3.0     # returns spanning more than this (weekend/holiday) are skipped
    vol_floor: float = 1e-6
    bar_hours: float = 1.0

    @classmethod
    def from_horizon(cls, k: float, vertical_hours: int, **kw) -> "LabelParams":
        """Barriers at k horizon-sigmas: pt = sl = k * sqrt(N)."""
        m = k * math.sqrt(vertical_hours)
        return cls(pt_mult=m, sl_mult=m, vertical_hours=vertical_hours, **kw)
#

# PLACEHOLDER thresholds from spec section 6.3 - to be derived from data (spec section 6.4)
PATH_DIR_EXC, PATH_DIR_NET, PATH_RANGE_EXC, PATH_QUIET_NET = 0.3, 0.5, 0.5, 0.3

def path_type(excursion_ratio: float, net_ratio: float) -> str:
    """
    """
    if excursion_ratio < PATH_DIR_EXC and net_ratio > PATH_DIR_NET:
        return "directional"
    if excursion_ratio >= PATH_RANGE_EXC:
        return "ranging"
    if excursion_ratio < PATH_DIR_EXC and net_ratio <= PATH_QUIET_NET:
        return "quiet"
    return "mixed"
#


def hourly_vol_series(bars: pl.DataFrame, p: LabelParams) -> np.ndarray:
    """ EWMA vol of hourly log returns, aligned to `bars`; value at i INCLUDES bar i's return.
        Gap returns (> max_gap_hours) are skipped and the previous value carried forward. NaN until warm.
    """
    t = bars["time"].dt.epoch("s").to_numpy()
    price = bars["mid_close"].to_numpy()
    lam = 1.0 - 2.0 / (p.vol_span + 1)
    out = np.full(len(price), np.nan)
    var, n_valid, last = 0.0, 0, float("nan")
    for i in range(1, len(price)):
        if (t[i] - t[i - 1]) / 3600.0 > p.max_gap_hours:
            out[i] = last
            continue
        r = math.log(price[i] / price[i - 1])
        if n_valid < p.vol_warmup:
            n_valid += 1
            var += (r * r - var) / n_valid
        else:
            var = lam * var + (1.0 - lam) * r * r
        if n_valid >= p.vol_warmup:
            last = max(math.sqrt(var), p.vol_floor)
        out[i] = last
    return out
#


def load_minute_bars(lake: Path, source: str, market: str, symbol: str, interval: str = "1MIN") -> dict:
    pattern = lake_path(lake, "derived", source, market, symbol, interval, 2000).parent.parent / "year=*" / "*.parquet"
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    cols = con.execute(f"""SELECT epoch(time)::BIGINT AS t, mid_open AS o, mid_high AS h, mid_low AS l, mid_close AS c
                           FROM read_parquet('{pattern}', hive_partitioning=false) ORDER BY time""").fetchnumpy()
    return {k: np.asarray(v) for k, v in cols.items()}
#


class TickResolver:
    """Looks up raw ticks for a short window (same-minute ambiguity, and the verification spot check)."""

    def __init__(self, lake: Path, source: str, market: str, symbol: str):
        pattern = lake_path(lake, "raw", source, market, symbol, "TICK", 2000).parent.parent / "year=*" / "*.parquet"
        self.con = duckdb.connect()
        self.con.execute("SET TimeZone = 'UTC'")
        self.src = f"read_parquet('{pattern}', hive_partitioning=false, file_row_number=true)"

    def touch(self, t0: int, t1: int, upper: float, lower: float) -> tuple[int, int | None]:
        """Ticks with dtime in [t0, t1) (epoch seconds): (tick count, +1/-1 for the first mid at/beyond
        a barrier, or None if no tick crosses one)."""
        n, lab = self.con.execute(f"""
            WITH w AS (SELECT dtime, file_row_number AS n, (bidPrice + askPrice) / 2 AS m
                       FROM {self.src}
                       WHERE dtime >= to_timestamp({int(t0)}) AND dtime < to_timestamp({int(t1)}))
            SELECT count(*),
                   arg_min(CASE WHEN m >= {upper!r} THEN 1 ELSE -1 END, struct_pack(t := dtime, n := n))
                       FILTER (WHERE m >= {upper!r} OR m <= {lower!r})
            FROM w""").fetchone()  #type: ignore
        return int(n), (None if lab is None else int(lab))
#


_SCHEMA = {
    "event_s": pl.Int64, "side": pl.Int8, "price_event": pl.Float64, "vol": pl.Float64,
    "upper": pl.Float64, "lower": pl.Float64, "upper_dist": pl.Float64, "lower_dist": pl.Float64,
    "vertical_s": pl.Int64, "label": pl.Int8, "status": pl.Utf8, "resolution": pl.Utf8,
    "exit_s": pl.Int64, "exit_price": pl.Float64, "exit_gap": pl.Boolean,
    "return_at_exit": pl.Float64, "hours_to_exit": pl.Float64,
    "max_up_excursion": pl.Float64, "max_down_excursion": pl.Float64,
    "excursion_ratio": pl.Float64, "net_ratio": pl.Float64, "path_type": pl.Utf8,
}


def label_events(events: pl.DataFrame, bars: pl.DataFrame, minute: dict,
                 resolver: TickResolver | None, p: LabelParams = LabelParams(),
                 vol: np.ndarray | None = None) -> pl.DataFrame:
    th = bars["time"].dt.epoch("s").to_numpy()
    if vol is None:
        vol = hourly_vol_series(bars, p)
    mt, mo, mh, ml, mc = (minute[k] for k in ("t", "o", "h", "l", "c"))
    bar_s = int(p.bar_hours * 3600)
    N = p.vertical_hours

    ev_bar = events["bar_time"].dt.epoch("s").to_numpy()
    ev_px = events["price_event"].to_numpy()
    ev_side = events["side"].to_numpy()
    ev_idx = np.searchsorted(th, ev_bar)

    rows = []
    for n in range(events.height):
        i, px = int(ev_idx[n]), float(ev_px[n])
        ev_s = int(ev_bar[n]) + bar_s
        row = {k: None for k in _SCHEMA}
        row.update(event_s=ev_s, side=int(ev_side[n]), price_event=px)   #type: ignore
        rows.append(row)

        v = float(vol[i])
        if not v == v:
            row["status"] = "no_vol"    #type: ignore
            continue
        j = i + N
        if j >= len(th):
            row["status"] = "insufficient_data"    #type: ignore
            continue
        vertical_s = int(th[j]) + bar_s
        up_dist, dn_dist = p.pt_mult * v, p.sl_mult * v
        upper, lower = px * math.exp(up_dist), px * math.exp(-dn_dist)
        row.update(vol=v, upper=upper, lower=lower, upper_dist=up_dist, lower_dist=dn_dist, vertical_s=vertical_s)    #type: ignore

        s = int(np.searchsorted(mt, ev_s, "left"))
        e = int(np.searchsorted(mt, vertical_s, "left"))
        if e <= s:
            row["status"] = "insufficient_data"     #type: ignore
            continue

        up = mh[s:e] >= upper
        dn = ml[s:e] <= lower
        hit = up | dn
        resolution = "bar"
        if hit.any():
            k = int(hit.argmax())
            idx = s + k
            if up[k] and dn[k]:                     # both barriers inside one 1MIN bar
                lab = None
                if resolver is not None:
                    _, lab = resolver.touch(int(mt[idx]), int(mt[idx]) + 60, upper, lower)
                if lab is not None:
                    label, resolution = lab, "tick"
                else:                               # no ticks: open-to-close direction (spec 5.3)
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
        else:                                       # vertical barrier: exit at the last bar's close
            label, exit_s, last, gap = 0, vertical_s, e - 1, False
            exit_px, hours = float(mc[e - 1]), float(N)

        ret = math.log(exit_px / px)
        up_exc = max(0.0, math.log(float(mh[s:last + 1].max()) / px))
        dn_exc = max(0.0, -math.log(float(ml[s:last + 1].min()) / px))
        exc_ratio = min(up_exc / up_dist, dn_exc / dn_dist)          # per-direction normalization (spec 6.5)
        net_ratio = abs(ret) / (up_dist if ret >= 0 else dn_dist)
        row.update(label=label, status="ok", resolution=resolution, exit_s=exit_s, exit_price=exit_px,   #type: ignore
                   exit_gap=gap, return_at_exit=ret, hours_to_exit=hours,   #type: ignore
                   max_up_excursion=up_exc, max_down_excursion=dn_exc,     #type: ignore
                   excursion_ratio=exc_ratio, net_ratio=net_ratio, path_type=path_type(exc_ratio, net_ratio))   #type: ignore

    ts = lambda c: pl.from_epoch(pl.col(c), time_unit="s").dt.replace_time_zone("UTC")
    df = pl.DataFrame(rows, schema=_SCHEMA).with_columns(
        event_time=ts("event_s"), vertical_time=ts("vertical_s"), exit_time=ts("exit_s"))
    first = ["event_time", "side", "label", "status", "resolution", "price_event", "vol", "upper", "lower",
             "upper_dist", "lower_dist", "vertical_time", "exit_time", "exit_price", "exit_gap"]
    return df.drop("event_s", "vertical_s", "exit_s").select(first + [c for c in df.columns
                   if c not in first and c not in ("event_s", "vertical_s", "exit_s")])
#


def summarize_labels(labels: pl.DataFrame, p: LabelParams) -> None:
    ok = labels.filter(pl.col("status") == "ok")
    n, n_ok = labels.height, ok.height
    share = lambda v: f"{(ok['label'] == v).sum() / max(n_ok, 1):.0%}"
    med = lambda v: ok.filter(pl.col("label") == v)["hours_to_exit"].median()
    fmt = lambda x: "-" if x is None else f"{x:.1f}"
    print(f"[bold]pt={p.pt_mult:.1f} sl={p.sl_mult:.1f} N={p.vertical_hours}h[/bold]  events={n} labeled={n_ok}  "
          f"up={share(1)} down={share(-1)} timeout={share(0)}  "
          f"median hours to exit: up={fmt(med(1))} down={fmt(med(-1))}")
    res = ok.group_by("resolution").len()
    extra = ", ".join(f"{r}: {c}" for r, c in res.iter_rows() if r != "bar")
    gaps = int(ok["exit_gap"].sum())
    to = ok.filter(pl.col("label") == 0).group_by("path_type").len().sort("path_type")
    print(f"   same-minute ambiguity: {extra or 'none'};  gap exits: {gaps};  "
          f"timeouts by path_type (placeholder thresholds): "
          + (", ".join(f"{t}: {c}" for t, c in to.iter_rows()) or "none"))
#


def verify_labels(labels: pl.DataFrame, resolver: TickResolver, sample: int = 50, seed: int = 42) -> list[Check]:
    ok = labels.filter(pl.col("status") == "ok")
    up, dn, to = (ok.filter(pl.col("label") == v) for v in (1, -1, 0))
    out = [
        Check("labels in {-1, 0, 1}", bool(ok["label"].is_in([-1, 0, 1]).all())),
        Check("exit not before event", bool((ok["exit_time"] >= ok["event_time"]).all())),
        Check("exit within vertical barrier", bool((ok["exit_time"] <= ok["vertical_time"]).all())),
        Check("upper exits at/above barrier", bool((up["exit_price"] >= up["upper"] - 1e-9).all())),
        Check("lower exits at/below barrier", bool((dn["exit_price"] <= dn["lower"] + 1e-9).all())),
        Check("timeouts exit at vertical barrier", bool((to["exit_time"] == to["vertical_time"]).all())),
        Check("excursions non-negative", bool(((ok["max_up_excursion"] >= 0) & (ok["max_down_excursion"] >= 0)).all())),
        Check("insufficient-data rows have null label",
              bool(labels.filter(pl.col("status") != "ok")["label"].is_null().all())),
    ]
    # independent recompute: first tick whose mid is at/beyond a barrier, scanned straight from raw ticks
    bad = tested = 0
    for r in ok.sample(n=min(sample, ok.height), seed=seed).iter_rows(named=True):
        n_ticks, lab = resolver.touch(int(r["event_time"].timestamp()), int(r["vertical_time"].timestamp()),
                                      r["upper"], r["lower"])
        if n_ticks == 0:
            continue
        tested += 1
        bad += (0 if lab is None else lab) != r["label"]
    out.append(Check(f"{tested}-event tick spot check", bad == 0, f"{bad} mismatches"))
    return out
#




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    LAKE = Path("data/lake")
    SRC = ("dukascopy", "forex", "EURJPY")

    bars = load_bars(LAKE, *SRC, "1HOUR")
    events = detect_events(bars, replace(CusumParams(), h=3.0))     # working default from the CUSUM sweep
    minute = load_minute_bars(LAKE, *SRC)
    resolver = TickResolver(LAKE, *SRC)
    print(f"{events.height} events, {len(minute['t'])} minute bars")

    # sweep: vertical horizon x barrier width (in horizon-sigmas). Pick what gives a sensible
    # label mix and hold time - not just whichever looks most profitable.
    for N in (24, 48, 120):
        for k in (0.5, 1.0):
            p = LabelParams.from_horizon(k, N)
            summarize_labels(label_events(events, bars, minute, resolver, p), p)

    # verify one configuration against raw ticks (slow on real data: lower `sample` if needed)
    p = LabelParams.from_horizon(1.0, 48)
    labels = label_events(events, bars, minute, resolver, p)
    report(verify_labels(labels, resolver, sample=50))
    print(labels.head(10))