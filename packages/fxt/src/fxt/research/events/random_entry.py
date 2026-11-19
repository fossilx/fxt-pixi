'''
random_entry

The random-entry sampler (RandomEventsConfig): the null strategy the real ones are
compared with (ML pipeline spec §9.6).

Each bar's draw is a hash of (seed, bar open time) through splitmix64, so an event
never depends on which other bars are in the data; only the warmup count does.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from datetime import timedelta

import numpy as np
import polars as pl

from fxt.research.models import RandomEventsConfig

from .contract import DETECT_CORE_SCHEMA, register_sampler

__all__ = ["RANDOM_SCHEMA", "detect_random", "splitmix64", "uniform_draws"]

RANDOM_SCHEMA = DETECT_CORE_SCHEMA

_M = np.uint64(0xFFFFFFFFFFFFFFFF)


def splitmix64(x: np.ndarray) -> np.ndarray:
    """ The splitmix64 finalizer, element-wise on uint64 (wrapping arithmetic). """
    with np.errstate(over="ignore"):
        z = (x + np.uint64(0x9E3779B97F4A7C15)) & _M
        z = ((z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)) & _M
        z = ((z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)) & _M
        return z ^ (z >> np.uint64(31))


def uniform_draws(seed: int, epoch_s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """ (u in [0, 1), direction bit) per timestamp, from (seed, timestamp) only. """
    key = splitmix64(np.array([seed], dtype=np.uint64))[0]
    z = splitmix64(epoch_s.astype(np.int64).view(np.uint64) ^ key)
    u = (z >> np.uint64(11)).astype(np.float64) / float(1 << 53)
    bit = splitmix64(z) & np.uint64(1)
    return u, bit.astype(np.int8)


@register_sampler(RandomEventsConfig)
def detect_random(bars: pl.DataFrame, cfg: RandomEventsConfig) -> pl.DataFrame:
    """ Events (t0, direction, price_t0) from bars with `time` (bar open) and `mid_close`. """
    df = bars.sort("time").drop_nulls("mid_close")
    t = df.get_column("time").dt.epoch("s").to_numpy()
    u, bit = uniform_draws(cfg.seed, t)
    fire = u < cfg.fire_prob
    fire[: cfg.warmup] = False
    rows = df.filter(pl.Series(fire))
    direction = np.where(bit[fire] == 1, 1, -1).astype(np.int8)
    return pl.DataFrame({
        "t0":        rows.get_column("time") + timedelta(seconds=cfg.bar_seconds),
        "direction": pl.Series(direction, dtype=pl.Int8),
        "price_t0":  rows.get_column("mid_close"),
    }).cast(RANDOM_SCHEMA)  # type: ignore[arg-type]
#-
