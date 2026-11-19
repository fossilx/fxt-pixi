'''
trend

The directional feature set (TrendFeaturesConfig, ML pipeline spec §4). Pure: bars
in, long-format features out (same FEATURE_SCHEMA and missing-means-absent rule as
the baseline set). Every feature is signed: positive = price above its average,
high in its range, trending up.

    long = compute_trend(bars, TrendFeaturesConfig(), symbol="EURJPY")
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import itertools
import math
from datetime import timedelta

import polars as pl

from fxt.research.models.features import TrendFeaturesConfig

from .baseline import prepare, to_long

__all__ = ["TREND_BAR_COLUMNS", "compute_trend"]

TREND_BAR_COLUMNS = ("time", "mid_open", "mid_high", "mid_low", "mid_close")


def compute_trend(bars: pl.DataFrame, cfg: TrendFeaturesConfig, *, symbol: str) -> pl.DataFrame:
    """ Long-format trend features for every bar of one symbol, all years at once. """
    df = prepare(bars, TREND_BAR_COLUMNS)
    need = lambda w: max(1, math.ceil(cfg.min_coverage * w))
    c, hi, lo = pl.col("mid_close"), pl.col("mid_high"), pl.col("mid_low")
    gap = (pl.col("time") - pl.col("time").shift(1)) > timedelta(hours=cfg.max_gap_hours)
    r1 = (c / c.shift(1)).log()
    vw = cfg.vol_window
    vol = pl.when(gap).then(None).otherwise(r1).rolling_std(vw, min_samples=need(vw))
    sma = {w: c.rolling_mean(w, min_samples=need(w)) for w in cfg.windows}

    exprs = [(pl.col("time") + timedelta(hours=1)).alias("bar_time"), vol.alias("_vol")]
    exprs += [sma[w].alias(f"_sma{w}") for w in cfg.windows]
    exprs += [((c - lo.rolling_min(w, min_samples=need(w)))
               / (hi.rolling_max(w, min_samples=need(w)) - lo.rolling_min(w, min_samples=need(w))) - 0.5)
              .alias(f"range_pos_{w}h") for w in cfg.windows]
    exprs += [((c / c.shift(w)).log() / r1.abs().rolling_sum(w, min_samples=w)).alias(f"trend_eff_{w}h")
              for w in cfg.windows]
    df = df.with_columns(exprs)

    v = pl.col("_vol")
    w = cfg.windows
    df = df.with_columns(
        *[((c / pl.col(f"_sma{x}")).log() / (v * math.sqrt(x))).alias(f"ma_dist_{x}h") for x in w],
        *[((pl.col(f"_sma{a}") / pl.col(f"_sma{b}")).log() / (v * math.sqrt(b))).alias(f"ma_cross_{a}h_{b}h")
          for a, b in itertools.pairwise(w)],
    )
    if cfg.day_return:
        day = pl.col("time").dt.date()
        df = df.with_columns(
            ((c / pl.col("mid_open").first().over(day)).log()
             / (v * pl.int_range(1, pl.len() + 1).over(day).cast(pl.Float64).sqrt())).alias("ret_day_z"))
    return to_long(df, cfg.names(), symbol)
#-
