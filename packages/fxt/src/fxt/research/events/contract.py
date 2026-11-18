'''
contract

What every sampler must produce, and the registry that maps a sampler's
config class to its detect function.

    @register_sampler(BreakoutEventsConfig)
    def detect_breakout(bars: pl.DataFrame, cfg: BreakoutEventsConfig) -> pl.DataFrame:
        ...   # core columns + any extras

Core columns (every sampler, checked by check_detected):
    t0          close of the triggering bar, UTC, unique, sorted
    direction   +1 / -1: which way the sampler fired. Not a trade side
                (side rules map it; see ML pipeline spec §5.2)
    price_t0    mid price at t0

The builder adds `event_id` and `symbol` in front. Anything else a detect
function returns is a sampler-specific *extra* (CUSUM: ret, z, vol): kept in
the file for diagnostics, never read by downstream stages. Downstream code
selects CORE_COLUMNS only, so adding a sampler never touches labels/weights.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

import polars as pl

from fxt.research.models.events import SamplerConfig

__all__ = [
    "CORE_COLUMNS", "DETECT_CORE_SCHEMA", "EventContractError", "SAMPLERS",
    "DetectFn", "check_detected", "get_sampler", "register_sampler",
]

#! what a detect function returns (before the builder adds event_id/symbol)
DETECT_CORE_SCHEMA: dict[str, pl.DataType] = {
    "t0":        pl.Datetime("us", "UTC"),
    "direction": pl.Int8(),
    "price_t0":  pl.Float64(),
}
#! what every events file starts with; downstream stages read only these
CORE_COLUMNS: tuple[str, ...] = ("event_id", "symbol", *DETECT_CORE_SCHEMA)
_RESERVED = {"event_id", "symbol"}

DetectFn = Callable[[pl.DataFrame, Any], pl.DataFrame]
_F = TypeVar("_F", bound=DetectFn)

SAMPLERS: dict[type[SamplerConfig], DetectFn] = {}


class EventContractError(ValueError):
    """ A detect function returned something that isn't a valid events frame. """


def register_sampler(config_cls: type[SamplerConfig]) -> Callable[[_F], _F]:
    """ Decorator: `detect` is the sampler for `config_cls`. """
    if not (isinstance(config_cls, type) and issubclass(config_cls, SamplerConfig)):
        raise TypeError(f"{config_cls!r} isn't a SamplerConfig subclass")

    def decorator(fn: _F) -> _F:
        other = SAMPLERS.get(config_cls)
        if other is not None and (other.__module__, other.__qualname__) != (fn.__module__, fn.__qualname__):
            raise ValueError(f"{config_cls.__qualname__} already has a sampler: {other.__qualname__}")
        SAMPLERS[config_cls] = fn
        return fn
    return decorator
#

def get_sampler(config: SamplerConfig) -> DetectFn:
    try:
        return SAMPLERS[type(config)]
    except KeyError:
        raise TypeError(f"no sampler registered for {type(config).__qualname__}") from None
#

def check_detected(df: pl.DataFrame, sampler: str = "sampler") -> pl.DataFrame:
    """ Validate a detect function's output; returns it with core columns first. """
    if not isinstance(df, pl.DataFrame):
        raise EventContractError(f"{sampler} returned {type(df).__name__}, not a polars DataFrame")
    if clash := _RESERVED & set(df.columns):
        raise EventContractError(f"{sampler} returned {sorted(clash)}; the builder adds those")
    for col, dtype in DETECT_CORE_SCHEMA.items():
        if col not in df.columns:
            raise EventContractError(f"{sampler} output is missing core column {col!r}")
        if df.schema[col] != dtype:
            raise EventContractError(f"{sampler}: {col} must be {dtype}, got {df.schema[col]}")
        if df.get_column(col).null_count():
            raise EventContractError(f"{sampler}: {col} has nulls")
    if df.height:
        t0 = df.get_column("t0")
        if not t0.is_unique().all():
            raise EventContractError(f"{sampler}: t0 must be unique (one event per bar)")
        if not t0.is_sorted():
            raise EventContractError(f"{sampler}: events must be sorted by t0")
        if not df.get_column("direction").is_in([1, -1]).all():
            raise EventContractError(f"{sampler}: direction must be +1 or -1")
        p = df.get_column("price_t0")
        if not (p.is_finite().all() and (p > 0).all()):
            raise EventContractError(f"{sampler}: price_t0 must be positive and finite")
    extras = [c for c in df.columns if c not in DETECT_CORE_SCHEMA]
    return df.select(*DETECT_CORE_SCHEMA, *extras)
#-
