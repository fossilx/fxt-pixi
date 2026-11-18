"""Event-time features - first small set.

One row per labeled event, using only information available at event_time. event_time is the CLOSE of
the triggering hourly bar, so every feature may use that bar and everything before it, never anything
after. Windows are counted in hourly BARS (business hours), so weekends don't count as elapsed time;
a lookback that spans a weekend simply includes the gap move.

Features (all unitless or scale-free where possible, so they compare across vol regimes):
    side                     CUSUM direction that fired the event (+1 up / -1 down)
    ret_{1,4,24,120}h_z      log return over the last k business hours, divided by barrier_vol * sqrt(k)
    log_vol                  log of the reactive hourly vol (span 24) - the volatility level itself
    vol_ratio_barrier_cusum  reactive hourly vol / the slow vol the CUSUM normalized by
    vol_ratio_24_120         realized vol of the last 24 bars / of the last 120 bars
    spread_24h               tick-weighted mean spread over the last 24 bars (price units)
    spread_ratio_24_120      spread_24h / the same over 120 bars
    ticks_ratio_24_120       mean ticks per bar over 24 bars / over 120 bars
    hour_utc, dow            hour of event_time (UTC), weekday (Mon=0)

Output also carries label, weights, exit_time and life_start/life_end, which purged cross-validation needs.
"""
from dataclasses import replace
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from rich import print

# adjust these imports to wherever the sibling scripts live in your package
from .build_1min import Check, lake_path, report
from .cusum_events import CusumParams, detect_events
from .d_triple_barrier import LabelParams, hourly_vol_series
from .e_labeled_events import LOCKED, build_labeled_events


HORIZONS = (1, 4, 24, 120)
#


def load_feature_bars(lake: Path, source: str, market: str, symbol: str, interval: str = "1HOUR") -> pl.DataFrame:
    pattern = lake_path(lake, "derived", source, market, symbol, interval, 2000).parent.parent / "year=*" / "*.parquet"
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    c = con.execute(f"""SELECT epoch(time)::BIGINT AS t, mid_close, tick_count::DOUBLE AS tick_count, spread_mean
                        FROM read_parquet('{pattern}', hive_partitioning=false) ORDER BY time""").fetchnumpy()
    time = pl.from_epoch(pl.Series("time", c["t"]), time_unit="s").dt.replace_time_zone("UTC")
    return pl.DataFrame({"time": time, "mid_close": c["mid_close"], "tick_count": c["tick_count"],
                         "spread_mean": c["spread_mean"]})
#


def _trail_sum(x: np.ndarray, m: int) -> np.ndarray:
    """Sum of the last m values including the current one; NaN until m values exist."""
    c = np.concatenate([[0.0], np.cumsum(x)])
    out = np.full(len(x), np.nan)
    if len(x) >= m:
        out[m - 1:] = c[m:] - c[:-m]
    return out


def compute_features(bars: pl.DataFrame, idx: np.ndarray, cusum_vol: np.ndarray,
                     p: LabelParams = LabelParams()) -> dict[str, np.ndarray]:  # noqa: B008
    """Feature arrays for the bars at positions `idx`. Row i only ever reads bars[:i+1]."""
    th = bars["time"].dt.epoch("s").to_numpy()
    px = bars["mid_close"].to_numpy()
    tc = bars["tick_count"].to_numpy()
    sp = bars["spread_mean"].to_numpy()
    n = len(px)
    vol = hourly_vol_series(bars, p)                       # span 24, includes bar i

    r = np.full(n, np.nan)                                 # hourly log returns; closed-market gaps -> NaN
    gap = np.diff(th) / 3600.0 > p.max_gap_hours
    r[1:] = np.where(gap, np.nan, np.diff(np.log(px)))
    sq = np.where(np.isnan(r), 0.0, r * r)
    ok = (~np.isnan(r)).astype(float)

    def rv(m):
        s, c = _trail_sum(sq, m), _trail_sum(ok, m)
        return np.where(c >= m / 2, np.sqrt(s / np.maximum(c, 1.0)), np.nan)

    def spread(m):
        return _trail_sum(sp * tc, m) / _trail_sum(tc, m)

    f = {}
    for k in HORIZONS:
        ret = np.full(n, np.nan)
        ret[k:] = np.log(px[k:] / px[:-k])
        f[f"ret_{k}h_z"] = (ret / (vol * np.sqrt(k)))[idx]
    f["log_vol"] = np.log(vol)[idx]
    f["vol_ratio_barrier_cusum"] = vol[idx] / cusum_vol
    f["vol_ratio_24_120"] = (rv(24) / rv(120))[idx]
    f["spread_24h"] = spread(24)[idx]
    f["spread_ratio_24_120"] = (spread(24) / spread(120))[idx]
    f["ticks_ratio_24_120"] = ((_trail_sum(tc, 24) / 24) / (_trail_sum(tc, 120) / 120))[idx]
    ev_epoch = th[idx] + 3600                              # event_time = bar open + 1 bar
    f["hour_utc"] = ((ev_epoch // 3600) % 24).astype("int64")
    f["dow"] = (((ev_epoch // 86400) + 3) % 7).astype("int64")   # 1970-01-01 was a Thursday; Mon=0
    return f
#


def build_features(lake: Path, source: str, market: str, symbol: str, labeled: pl.DataFrame,
                   h: float = LOCKED["h"]) -> tuple[pl.DataFrame, list[str], pl.DataFrame]:
    """Returns (rows with features + labels + weights, feature column names, the hourly bars used)."""
    bars = load_feature_bars(lake, source, market, symbol)
    events = detect_events(bars, replace(CusumParams(), h=h))
    ok = (labeled.filter(pl.col("status") == "ok")
                 .join(events.select("event_time", pl.col("vol").alias("cusum_vol")), on="event_time", how="left"))
    th = bars["time"].dt.epoch("s").to_numpy()
    idx = np.searchsorted(th, ok["event_time"].dt.epoch("s").to_numpy() - 3600)
    if not (th[idx] + 3600 == ok["event_time"].dt.epoch("s").to_numpy()).all():
        raise ValueError("event_time does not line up with an hourly bar close")
    f = compute_features(bars, idx, ok["cusum_vol"].to_numpy())
    cols = ["side"] + list(f)
    keep = ["event_time", "label", "weight", "weight_uniq", "uniqueness", "exit_time", "life_start", "life_end"]
    df = ok.select(keep + ["side"]).with_columns([pl.Series(k, v) for k, v in f.items()])
    return df, cols, bars
#


def verify_features(df: pl.DataFrame, cols: list[str], bars: pl.DataFrame, h: float = LOCKED["h"],
                    sample: int = 30, seed: int = 42) -> list[Check]:
    X = df.select(cols).to_numpy().astype(float)
    out = [Check("no infinite values", bool(np.isfinite(X[~np.isnan(X)]).all())),
           Check("calendar features match event_time",
                 bool((df["hour_utc"] == df["event_time"].dt.hour()).all()
                      and (df["dow"] == df["event_time"].dt.weekday() - 1).all()))]
    # no-lookahead test: recompute each sampled event's features from ONLY the bars up to its own bar
    th = bars["time"].dt.epoch("s").to_numpy()
    rng = np.random.default_rng(seed)
    bad, tested = [], 0
    for r in rng.choice(df.height, size=min(sample, df.height), replace=False):
        row = df.row(int(r), named=True)
        i = int(np.searchsorted(th, row["event_time"].timestamp() - 3600))
        prefix = bars.head(i + 1)
        ev = detect_events(prefix, replace(CusumParams(), h=h)).filter(pl.col("event_time") == row["event_time"])
        if ev.height != 1:
            bad.append(("event missing from prefix run", row["event_time"]))
            continue
        f = compute_features(prefix, np.array([i]), ev["vol"].to_numpy())
        tested += 1
        for k, v in f.items():
            if not np.allclose(v[0], row[k], rtol=1e-9, atol=1e-12, equal_nan=True):
                bad.append((k, row["event_time"]))
    out.append(Check(f"{tested}-event no-lookahead recompute from truncated bars", not bad, f"{len(bad)} mismatches {bad[:3]}"))
    return out
#


def summarize_features(df: pl.DataFrame, cols: list[str]) -> None:
    n = df.height
    nulls = {c: int(df[c].is_null().sum() + df[c].is_nan().sum()) if df[c].dtype.is_float() else 0 for c in cols} #type: ignore
    complete = df.drop_nulls(cols).filter(~pl.any_horizontal([pl.col(c).is_nan() for c in cols if df[c].dtype.is_float()])).height
    print(f"[bold]{n} events x {len(cols)} features[/bold]; rows with every feature present: {complete}")
    print("   missing (warm-up) by feature: " + (", ".join(f"{c}: {v}" for c, v in nulls.items() if v) or "none"))
    print(df.select(cols).with_columns(pl.col(pl.Float64).fill_nan(None)).describe())
#




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    LAKE = Path("data/lake")
    SRC = ("dukascopy", "forex", "EURJPY")

    labeled = build_labeled_events(LAKE, *SRC, verbose=False)
    df, cols, bars = build_features(LAKE, *SRC, labeled)
    summarize_features(df, cols)
    report(verify_features(df, cols, bars))
    print(df.head(5))