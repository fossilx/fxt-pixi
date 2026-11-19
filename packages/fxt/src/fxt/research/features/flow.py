'''
flow

The order-flow feature set (FlowFeaturesConfig, ML pipeline spec §4.4). Pure: 1MIN bars
in, long-format hourly features out (same FEATURE_SCHEMA and missing-means-absent rule
as the other sets). Every value at bar_time uses only minutes that closed by then.

    long = compute_flow(minute_bars, FlowFeaturesConfig(), symbol="EURJPY")
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

from fxt.research.models.features import FlowFeaturesConfig

from .baseline import prepare, to_long

__all__ = ["FLOW_BAR_COLUMNS", "compute_flow", "hourly_flow"]

FLOW_BAR_COLUMNS = ("time", "mid_close", "bid_volume", "ask_volume", "tick_count", "spread_mean")


def hourly_flow(minutes: pl.DataFrame, cfg: FlowFeaturesConfig) -> pl.DataFrame:
    """ One row per clock hour with data: bar_time (hour open + 1h) and the hour's sums. """
    df = prepare(minutes, FLOW_BAR_COLUMNS)
    c = pl.col("mid_close")
    gap = (pl.col("time") - pl.col("time").shift(1)) > timedelta(minutes=cfg.max_gap_minutes)
    d = pl.when(gap | pl.col("time").shift(1).is_null()).then(0).otherwise((c - c.shift(1)).sign())
    ticks = pl.col("tick_count").cast(pl.Float64)
    return (df.with_columns(d.alias("_dir"), pl.col("time").dt.truncate("1h").alias("_hour"))
              .group_by("_hour", maintain_order=True)
              .agg(pl.col("bid_volume").sum().alias("bid_vol"), pl.col("ask_volume").sum().alias("ask_vol"),
                   (pl.col("_dir") > 0).sum().cast(pl.Float64).alias("n_up"),
                   (pl.col("_dir") < 0).sum().cast(pl.Float64).alias("n_down"),
                   (pl.col("_dir") * ticks).sum().alias("flow_num"), ticks.sum().alias("ticks"),
                   (pl.col("spread_mean") * ticks).sum().alias("_spread_w"))
              .with_columns((pl.col("_spread_w") / pl.col("ticks")).alias("spread"),
                            (pl.col("_hour") + timedelta(hours=1)).alias("bar_time"))
              .drop("_spread_w")
              .sort("_hour"))


def compute_flow(minutes: pl.DataFrame, cfg: FlowFeaturesConfig, *, symbol: str) -> pl.DataFrame:
    """ Long-format flow features for every hour of one symbol, all years at once. """
    h = hourly_flow(minutes, cfg)
    need = lambda w: max(1, math.ceil(cfg.min_coverage * w))
    def roll(col: str, w: int) -> pl.Expr:
        return pl.col(col).rolling_sum(w, min_samples=need(w)) if w > 1 else pl.col(col)
    exprs = []
    for w in cfg.windows:
        bid, ask = roll("bid_vol", w), roll("ask_vol", w)
        up, dn = roll("n_up", w), roll("n_down", w)
        exprs += [((bid - ask) / (bid + ask)).alias(f"depth_imb_{w}h"),
                  ((up - dn) / (up + dn)).alias(f"tick_imb_{w}h"),
                  (roll("flow_num", w) / roll("ticks", w)).alias(f"flow_imb_{w}h")]
    a, dv = cfg.activity_window, cfg.dev_window
    imb1 = (pl.col("bid_vol") - pl.col("ask_vol")) / (pl.col("bid_vol") + pl.col("ask_vol"))
    exprs += [(imb1 - imb1.rolling_mean(dv, min_samples=need(dv))).alias("depth_imb_1h_dev"),
              (pl.col("ticks") / pl.col("ticks").rolling_mean(a, min_samples=need(a))).alias(f"activity_1h_{a}h"),
              (pl.col("spread") / pl.col("spread").rolling_mean(a, min_samples=need(a))).alias(f"spread_1h_{a}h")]
    names = cfg.names()
    out = h.with_columns(exprs)
    missing = set(names) - set(out.columns)
    assert not missing, missing
    return to_long(out, names, symbol)
#-
