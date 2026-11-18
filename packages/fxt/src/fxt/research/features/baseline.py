'''
baseline

The first feature set (ML pipeline spec §4). Pure: bars in, long-format
features out. See BarFeaturesConfig for the definitions.

    long = compute_features(bars, BarFeaturesConfig(), symbol="EURJPY")

Output (FEATURE_SCHEMA), one row per (bar_time, name) with a value:
    symbol, bar_time (bar close, UTC), name, value, value_str (null: no categoricals yet)

Rows are only written where a feature exists: warmup bars (window not yet
full) and non-finite values (e.g. a 0/0 ratio) are left out, not stored as
null. Missing then means "not computable at this bar" everywhere.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import math
from datetime import timedelta

import polars as pl

from fxt.research.models.features import BarFeaturesConfig

__all__ = ["BAR_COLUMNS", "FEATURE_SCHEMA", "compute_features"]

BAR_COLUMNS = ("time", "mid_close", "spread_mean", "tick_count")

FEATURE_SCHEMA: dict[str, pl.DataType] = {
    "symbol":    pl.String(),
    "bar_time":  pl.Datetime("us", "UTC"),
    "name":      pl.String(),
    "value":     pl.Float64(),
    "value_str": pl.String(),
}


def _utc(col: str, dtype: pl.DataType) -> pl.Expr:
    t = pl.col(col).cast(pl.Datetime("us", dtype.time_zone))          # type: ignore[union-attr]
    return t.dt.replace_time_zone("UTC") if dtype.time_zone is None else t.dt.convert_time_zone("UTC")  # type: ignore[union-attr]


def compute_features(bars: pl.DataFrame, cfg: BarFeaturesConfig, *, symbol: str) -> pl.DataFrame:
    """ Long-format features (FEATURE_SCHEMA) for every bar of one symbol, all years at once
        (windows carry across year boundaries).
    """
    if missing := set(BAR_COLUMNS) - set(bars.columns):
        raise ValueError(f"bars are missing column(s) {sorted(missing)}")
    df = bars.select(BAR_COLUMNS).with_columns(_utc("time", bars.schema["time"])).sort("time")
    if df.get_column("time").is_duplicated().any():
        raise ValueError("bars have duplicate timestamps")

    s, lg = cfg.short, cfg.long
    need = lambda w: max(1, math.ceil(cfg.min_coverage * w))
    c = pl.col("mid_close")
    gap = (pl.col("time") - pl.col("time").shift(1)) > timedelta(hours=cfg.max_gap_hours)
    r1 = (c / c.shift(1)).log()
    r1_vol = pl.when(gap).then(None).otherwise(r1)
    spread = pl.col("spread_mean")
    ticks = pl.col("tick_count").cast(pl.Float64)

    df = df.with_columns(
        (pl.col("time") + timedelta(hours=1)).alias("bar_time"),
        *[(c / c.shift(h)).log().alias(f"ret_{h}h") for h in cfg.ret_horizons],
        r1_vol.rolling_std(s, min_samples=need(s)).alias(f"vol_{s}h"),
        r1_vol.rolling_std(lg, min_samples=need(lg)).alias(f"vol_{lg}h"),
        (spread.rolling_mean(s, min_samples=need(s)) / c * 1e4).alias(f"spread_bp_{s}h"),
        (spread.rolling_mean(s, min_samples=need(s)) / spread.rolling_mean(lg, min_samples=need(lg)))
            .alias(f"spread_ratio_{s}h_{lg}h"),
        (ticks.rolling_mean(s, min_samples=need(s)) / ticks.rolling_mean(lg, min_samples=need(lg)))
            .alias(f"tick_ratio_{s}h_{lg}h"),
    ).with_columns(
        *[(pl.col(f"ret_{h}h") / (pl.col(f"vol_{lg}h") * math.sqrt(h))).alias(f"ret_{h}h_z")
          for h in cfg.ret_horizons],
        (pl.col(f"vol_{s}h") / pl.col(f"vol_{lg}h")).alias(f"vol_ratio_{s}h_{lg}h"),
    )
    if cfg.calendar:
        df = df.with_columns(pl.col("bar_time").dt.hour().cast(pl.Float64).alias("hour_utc"),
                             pl.col("bar_time").dt.weekday().cast(pl.Float64).alias("dow_utc"))

    names = cfg.names()
    order = {n: i for i, n in enumerate(names)}
    long = (df.select("bar_time", *names)
              .unpivot(index="bar_time", on=list(names), variable_name="name", value_name="value")
              .filter(pl.col("value").is_not_null() & pl.col("value").is_finite())
              .with_columns(pl.col("name").replace_strict(order, return_dtype=pl.Int32).alias("_o"))
              .sort("bar_time", "_o").drop("_o"))
    return long.select(
        pl.lit(symbol, dtype=pl.String).alias("symbol"), "bar_time", "name",
        pl.col("value").cast(pl.Float64), pl.lit(None, dtype=pl.String).alias("value_str"),
    )
#-
