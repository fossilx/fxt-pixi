'''
backtest

Cost-aware trade simulation from out-of-fold predictions (ML pipeline spec §9.2).

    costed = trade_costs(frame, bars, cfg, symbol)     # + half_spread_entry/exit, cost (log units)
    trades = simulate(predictions, cfg)                # applies the position cap; gross / net per trade

Returns are log returns per unit of size, mid-to-mid for `gross`, minus `cost` for `net`.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import heapq
from datetime import timedelta

import numpy as np
import polars as pl

from fxt.research.models import BacktestConfig, SizerConfig

__all__ = ["MissingQuoteError", "apply_sizer", "simulate", "trade_costs"]


class MissingQuoteError(ValueError):
    """ No hourly bar to take an entry or exit quote from. """


def trade_costs(frame: pl.DataFrame, bars: pl.DataFrame, cfg: BacktestConfig, symbol: str) -> pl.DataFrame:
    """ frame (t0, t1, touch, price_t0, exit_price) + half_spread_entry, half_spread_exit, cost.

        entry: the event bar (open = t0 - 1h), its closing quote
        exit:  timeout (touch == vertical) -> the bar ending at t1, its closing quote;
               barrier exit -> the bar containing t1, its mean spread
    """
    q = bars.select(
        pl.col("time").alias("bar_open"),
        ((pl.col("ask_close") - pl.col("bid_close")) / 2).alias("half_close"),
        (pl.col("spread_mean") / 2).alias("half_mean"),
    ).sort("bar_open")
    f = frame.with_row_index("_row").with_columns(
        (pl.col("t0") - timedelta(hours=1)).alias("_entry_bar"),
        pl.when(pl.col("touch") == "vertical")
        .then(pl.col("t1") - timedelta(hours=1))
        .otherwise(pl.col("t1").dt.truncate("1h"))
        .alias("_exit_bar"),
    )
    entry = q.select(pl.col("bar_open").alias("_entry_bar"), pl.col("half_close").alias("half_spread_entry"))
    exit_ = q.select(pl.col("bar_open").alias("_exit_bar"), pl.col("half_close").alias("_x_close"),
                     pl.col("half_mean").alias("_x_mean"))
    f = (f.join(entry, on="_entry_bar", how="left")
          .join(exit_, on="_exit_bar", how="left")
          .with_columns(pl.when(pl.col("touch") == "vertical").then(pl.col("_x_close"))
                        .otherwise(pl.col("_x_mean")).alias("half_spread_exit"))
          .drop("_x_close", "_x_mean"))
    bad = f.filter(pl.col("half_spread_entry").is_null() | pl.col("half_spread_exit").is_null())
    if bad.height:
        raise MissingQuoteError(f"{bad.height} trades have no entry/exit bar, e.g. t0={bad['t0'][0]}, "
                                f"t1={bad['t1'][0]}")
    pip = cfg.pip(symbol)
    f = f.with_columns(
        (pl.col("half_spread_entry") / pl.col("price_t0")
         + pl.col("half_spread_exit") / pl.col("exit_price")
         + 2 * cfg.slippage_pips * pip / pl.col("price_t0")
         + cfg.commission_bp / 1e4).alias("cost"),
    )
    return f.sort("_row").drop("_row", "_entry_bar", "_exit_bar")


def apply_sizer(prob: np.ndarray, cfg: SizerConfig, prior: float | None = None) -> np.ndarray:
    """ Sizes in [0, cap]; `prior` (the fold's training base rate) is needed for above_prior. """
    if cfg.rule == "take_all":
        return np.full(len(prob), cfg.cap)
    if cfg.rule == "above_prior":
        if prior is None:
            raise ValueError("above_prior needs the training base rate")
        return np.where(prob > prior, cfg.cap, 0.0)
    if cfg.rule == "threshold":
        return np.where(prob > cfg.threshold, cfg.cap, 0.0)
    return np.clip((prob - cfg.threshold) / (1 - cfg.threshold), 0.0, 1.0) * cfg.cap


def simulate(pred: pl.DataFrame, cfg: BacktestConfig) -> pl.DataFrame:
    """ pred (t0, t1, size, ret, cost, ...) sorted or not -> same rows sorted by t0, with
        `size` cut to the position cap and `gross` = size * ret, `net` = size * (ret - cost).
        Rows with size 0 stay (not trades; gross = net = 0).
    """
    pred = pred.sort("t0")
    size = pred.get_column("size").to_numpy().astype(float).copy()
    if cfg.position_cap is not None:
        t0 = pred.get_column("t0").dt.epoch("us").to_numpy()
        t1 = pred.get_column("t1").dt.epoch("us").to_numpy()
        open_: list[tuple[int, float]] = []
        total = 0.0
        for i in range(len(size)):
            while open_ and open_[0][0] <= t0[i]:
                total -= heapq.heappop(open_)[1]
            s = min(size[i], max(cfg.position_cap - total, 0.0))
            size[i] = s
            if s > 0:
                heapq.heappush(open_, (int(t1[i]), s))
                total += s
    return pred.with_columns(
        pl.Series("size", size),
        (pl.Series(size) * pl.col("ret")).alias("gross"),
        (pl.Series(size) * (pl.col("ret") - pl.col("cost"))).alias("net"),
    )
#-
