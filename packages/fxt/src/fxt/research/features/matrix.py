'''
matrix

From long-format features to a model's feature matrix (ML pipeline spec §4):
pivot to one column per name, then as-of join onto events at their decision
time t0 (latest bar_time <= t0).

    long  = load_features(research, cfg_hash, source=..., market=..., symbol="EURJPY")
    wide  = to_wide(long)                                 # symbol, bar_time, <name>...
    X     = features_at(labels, wide)                     # labels + feature_time + <name>...

Point-in-time: an event at t0 only ever sees a bar that closed at or before
t0. For events from the same hourly bars, t0 IS a bar_time, so the match is
exact; `tolerance` caps how stale a match may be (beyond it, features are null).
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from datetime import timedelta

import polars as pl

from fxt.research.paths import Research, Stage

__all__ = ["features_at", "load_features", "to_wide"]


def load_features(research: Research, config_hash: str, *, source: str, market: str, symbol: str,
                  years: list[int] | None = None, names: list[str] | None = None) -> pl.DataFrame:
    """ The long table for one features config and symbol (optionally some years / names). """
    found = research.scan(Stage.FEATURES, config=config_hash, source=source, market=market, symbol=symbol)
    if years is not None:
        found = [(k, p) for k, p in found if k.year in set(years)]
    if not found:
        raise FileNotFoundError(f"no features for config={config_hash} {source}/{market}/{symbol}")
    lf = pl.concat([pl.scan_parquet(p, hive_partitioning=False) for _, p in found])
    if names is not None:
        lf = lf.filter(pl.col("name").is_in(names))
    return lf.collect()
#

def to_wide(long: pl.DataFrame, names: list[str] | tuple[str, ...] | None = None) -> pl.DataFrame:
    """ symbol, bar_time, then one Float64 column per name (in `names` order; a name with no
        values at all becomes an all-null column). Sorted by symbol, bar_time.
    """
    if names is None:
        names = long.get_column("name").unique(maintain_order=True).to_list()
    wide = (long.filter(pl.col("name").is_in(list(names)))
                .pivot(on="name", index=["symbol", "bar_time"], values="value"))
    wide = wide.with_columns(*[pl.lit(None, dtype=pl.Float64).alias(n) for n in names if n not in wide.columns])
    return wide.select("symbol", "bar_time", *names).sort("symbol", "bar_time")
#

def features_at(rows: pl.DataFrame, wide: pl.DataFrame, *, tolerance: timedelta | None = timedelta(hours=1),
                time_col: str = "t0") -> pl.DataFrame:
    """ `rows` (needs symbol and `time_col`) + feature_time + every feature column, matched
        backward: the latest bar_time <= time_col, per symbol, no older than `tolerance`.
        Keeps `rows` order.
    """
    features = wide.rename({"bar_time": "feature_time"})
    left = rows.with_row_index("_row").sort("symbol", time_col)
    out = left.join_asof(features.sort("symbol", "feature_time"), left_on=time_col, right_on="feature_time",
                         by="symbol", strategy="backward", tolerance=tolerance, check_sortedness=False)
    return out.sort("_row").drop("_row")
#-
