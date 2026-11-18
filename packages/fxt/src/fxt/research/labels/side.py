'''
side

Side labels (ML pipeline spec §6.3). Pure: touches + event directions in,
one label row per event out. See SideLabelsConfig for the rules.

    labels = side_labels(touches, directions, cfg, strategy_id="cusum_h3_follow")

Output columns (LABEL_SCHEMA):
    event_id, symbol, t0
    side            +1 long / -1 short
    strategy_id     sampler label + side rule, e.g. "cusum_h3_follow"
    touch           the side-agnostic touch it came from
    outcome         pt | sl | timeout | insufficient_data
    meta_label      1 / 0; null when insufficient
    t1, hours_to_exit, exit_gap     from the touch
    ret             side-adjusted log return at exit: side * touch ret
    max_favorable   largest log move in the side's favor (max_up for a long)
    max_adverse     largest log move against it
    excursion_ratio min(max_up, max_down) / half_width: how far price went BOTH ways
    net_ratio       |ret| / half_width: how far it ended up, in barrier units
    path_type       directional | ranging | quiet | mixed (placeholder thresholds)

The ratios and path_type don't depend on side (symmetric barriers); they live
here rather than in touches so their thresholds can change without a rescan.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import polars as pl

from fxt.research.models.labels import SideLabelsConfig

__all__ = ["LABEL_SCHEMA", "OUTCOMES", "side_labels"]

OUTCOMES = ("pt", "sl", "timeout", "insufficient_data")

LABEL_SCHEMA: dict[str, pl.DataType] = {
    "event_id":        pl.String(),
    "symbol":          pl.String(),
    "t0":              pl.Datetime("us", "UTC"),
    "side":            pl.Int8(),
    "strategy_id":     pl.String(),
    "touch":           pl.String(),
    "outcome":         pl.String(),
    "meta_label":      pl.Int8(),
    "t1":              pl.Datetime("us", "UTC"),
    "hours_to_exit":   pl.Float64(),
    "exit_gap":        pl.Boolean(),
    "ret":             pl.Float64(),
    "max_favorable":   pl.Float64(),
    "max_adverse":     pl.Float64(),
    "excursion_ratio": pl.Float64(),
    "net_ratio":       pl.Float64(),
    "path_type":       pl.String(),
}


def side_labels(touches: pl.DataFrame, directions: pl.DataFrame, cfg: SideLabelsConfig,
                *, strategy_id: str) -> pl.DataFrame:
    """ One label row per touch row (LABEL_SCHEMA), in touch order.

        touches     the touches table (event_id, symbol, t0, touch, t1, ret, ...)
        directions  event_id, direction for every event in `touches`
    """
    missing = touches.join(directions, on="event_id", how="anti")
    if missing.height:
        raise ValueError(f"{missing.height} touch rows have no event direction "
                         f"(first: {missing.item(0, 'event_id')}); wrong events for this touch pass?")
    if not directions.get_column("event_id").is_unique().all():
        raise ValueError("directions has duplicate event_ids")

    floats = [c for c in ("ret", "half_width", "max_up", "max_down", "hours_to_exit") if c in touches.columns]
    touches = touches.with_columns(pl.col(floats).cast(pl.Float64))   # all-null columns have no type
    d = touches.join(directions.select("event_id", "direction"), on="event_id", how="left",
                     maintain_order="left")
    side = (pl.col("direction") * cfg.side_mult).cast(pl.Int8)
    placed = pl.col("touch") != "insufficient_data"
    favorable = pl.when(pl.col("side") == 1).then(pl.lit("upper")).otherwise(pl.lit("lower"))
    ret = pl.col("side").cast(pl.Float64) * pl.col("ret")
    exc = pl.min_horizontal("max_up", "max_down") / pl.col("half_width")
    net = pl.col("ret").abs() / pl.col("half_width")

    out = d.with_columns(side.alias("side")).with_columns(
        pl.lit(strategy_id, dtype=pl.String).alias("strategy_id"),
        pl.when(~placed).then(pl.lit("insufficient_data"))
          .when(pl.col("touch") == "vertical").then(pl.lit("timeout"))
          .when(pl.col("touch") == favorable).then(pl.lit("pt"))
          .otherwise(pl.lit("sl")).alias("outcome"),
        pl.when(placed).then(ret).alias("ret"),
        pl.when(placed).then(pl.when(pl.col("side") == 1).then("max_up").otherwise("max_down"))
          .alias("max_favorable"),
        pl.when(placed).then(pl.when(pl.col("side") == 1).then("max_down").otherwise("max_up"))
          .alias("max_adverse"),
        pl.when(placed).then(exc).alias("excursion_ratio"),
        pl.when(placed).then(net).alias("net_ratio"),
    )
    win_timeout = (pl.col("ret") > 0) if cfg.timeout_positive_is_win else pl.lit(False)
    path = (pl.when(~placed).then(None)
              .when((pl.col("excursion_ratio") < cfg.path_dir_exc) & (pl.col("net_ratio") > cfg.path_dir_net))
              .then(pl.lit("directional"))
              .when(pl.col("excursion_ratio") >= cfg.path_range_exc).then(pl.lit("ranging"))
              .when((pl.col("excursion_ratio") < cfg.path_dir_exc) & (pl.col("net_ratio") <= cfg.path_quiet_net))
              .then(pl.lit("quiet"))
              .otherwise(pl.lit("mixed")))
    out = out.with_columns(
        pl.when(pl.col("outcome") == "pt").then(1)
          .when(pl.col("outcome") == "sl").then(0)
          .when(pl.col("outcome") == "timeout").then(pl.when(win_timeout).then(1).otherwise(0))
          .otherwise(None).cast(pl.Int8).alias("meta_label"),
        path.alias("path_type"),
    )
    return out.select(*LABEL_SCHEMA).cast(LABEL_SCHEMA)  # type: ignore[arg-type]
#-
