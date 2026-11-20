'''
cross

The cross-pair feature set (CrossFeaturesConfig, ML pipeline spec §4.4). Pure: hourly
bars of the target pair and of every basket pair in, long-format features out (same
FEATURE_SCHEMA and missing-means-absent rule as the other sets).

    long = compute_cross(bars["EURJPY"], cfg, symbol="EURJPY", peers=bars)
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

from fxt.research.models.features import CrossFeaturesConfig, split_pair

from .baseline import prepare, to_long

__all__ = ["CROSS_BAR_COLUMNS", "compute_cross", "pair_z"]

CROSS_BAR_COLUMNS = ("time", "mid_close")


def pair_z(bars: pl.DataFrame, cfg: CrossFeaturesConfig) -> pl.DataFrame:
    """ bar_time + z_{h} per horizon: log return over h bars / (vol x sqrt(h)). """
    df = prepare(bars, CROSS_BAR_COLUMNS)
    need = lambda w: max(1, math.ceil(cfg.min_coverage * w))
    c = pl.col("mid_close")
    gap = (pl.col("time") - pl.col("time").shift(1)) > timedelta(hours=cfg.max_gap_hours)
    r1 = (c / c.shift(1)).log()
    vol = pl.when(gap).then(None).otherwise(r1).rolling_std(cfg.vol_window, min_samples=need(cfg.vol_window))
    return df.select(
        (pl.col("time") + timedelta(hours=1)).alias("bar_time"),
        *[((c / c.shift(h)).log() / (vol * math.sqrt(h))).alias(f"z{h}") for h in cfg.horizons],
    )


def compute_cross(bars: pl.DataFrame, cfg: CrossFeaturesConfig, *, symbol: str,
                  peers: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """ Long-format cross features for every bar of `symbol`. `peers` maps basket pairs to
        their hourly bars (the target's own entry, if any, is ignored).
    """
    base, quote = split_pair(symbol)
    others = [p for p in cfg.basket if p != symbol.upper()]
    if missing := [p for p in others if p not in peers]:
        raise ValueError(f"cross features for {symbol} need bars for {missing}")
    out = prepare(bars, CROSS_BAR_COLUMNS).select((pl.col("time") + timedelta(hours=1)).alias("bar_time"))
    for p in others:
        z = pair_z(peers[p], cfg).rename({f"z{h}": f"{p}_z{h}" for h in cfg.horizons})
        out = out.join(z, on="bar_time", how="left")

    def strength(ccy: str, h: int) -> pl.Expr:
        terms = []
        for p in others:
            b, q = split_pair(p)
            if ccy == b:
                terms.append(pl.col(f"{p}_z{h}"))
            elif ccy == q:
                terms.append(-pl.col(f"{p}_z{h}"))
        if not terms:
            return pl.lit(None, pl.Float64)
        return pl.mean_horizontal(terms)                   # nulls skipped; all null -> null

    exprs = []
    for h in cfg.horizons:
        b, q = strength(base, h), strength(quote, h)
        exprs += [b.alias(f"base_str_{h}h"), q.alias(f"quote_str_{h}h"),
                  ((b.abs() - q.abs()) / (b.abs() + q.abs())).alias(f"driver_{h}h")]
    return to_long(out.with_columns(exprs), cfg.names(), symbol)
#-
