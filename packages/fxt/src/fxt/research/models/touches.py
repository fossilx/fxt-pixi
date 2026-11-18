'''
touches

Config and metadata for the touch pass: step 1 of triple-barrier labeling
(ML pipeline spec §6.1). Side-agnostic: it records which barrier price hit
first after each event, never whether that was a win. Side labels (step 2)
apply a side rule on top, so follow / fade / ... share one 1MIN scan.

    TripleBarrierTouchConfig   barrier width, vertical horizon, barrier vol
    TouchesMeta                metadata for every touches file
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import Field, model_validator

from fxt.research.paths import Stage

from ._registry import registry
from .config import ConfigHash, StageConfig
from .meta import ResearchMeta

__all__ = ["TouchesMeta", "TripleBarrierTouchConfig"]


@registry.register("TripleBarrierTouchConfig", 1)
class TripleBarrierTouchConfig(StageConfig):
    """ Symmetric triple barrier around each event's price_t0.

        vol_t      EWMA vol of hourly log returns, INCLUDING the event bar
                   (it has closed by t0, so it's known)
        half_width = k * sqrt(vertical_bars) * vol_t        (log units, "k horizon-sigmas")
        upper      = price_t0 * exp(+half_width)
        lower      = price_t0 * exp(-half_width)
        vertical   = close of the hourly bar `vertical_bars` bars after the event bar
                     (business hours, counted on the data: weekends and holidays skip)

    1MIN bars opening in [t0, vertical) are scanned for the first touch.
    Defaults reproduce first_bars/d_triple_barrier.py with N=48, k=1.0.
    """
    stage = Stage.TOUCHES

    events_hash: ConfigHash                                   # which event set to label
    k: float = Field(1.0, gt=0)                               # half-width in horizon-sigmas
    vertical_bars: int = Field(48, ge=1)                      # horizon, in hourly bars of data
    vol_interval: Literal["1HOUR"] = "1HOUR"                  # bars for barrier vol + the horizon clock
    scan_interval: Literal["1MIN"] = "1MIN"                   # bars scanned for touches
    vol_span: int = Field(24, ge=2)                           # EWMA span (bars): reactive, ~1 day
    vol_warmup: int = Field(24, ge=1)                         # returns used to seed vol
    max_gap_hours: float = Field(3.0, gt=0)                   # longer returns are skipped (weekends)
    vol_floor: float = Field(1e-6, gt=0)
    ambiguity: Literal["ticks", "ohlc"] = "ticks"             # both barriers inside one 1MIN bar:
                                                              #   ticks: first tick past a barrier,
                                                              #   falling back to ohlc if none cross
                                                              #   ohlc: open->close direction only

    @property
    def mult(self) -> float:
        """ Barrier distance in vol units: k * sqrt(N). """
        return self.k * math.sqrt(self.vertical_bars)

    @property
    def label(self) -> str:
        return f"tb_k{self.k:g}_n{self.vertical_bars}"
#


@registry.register("TouchesMeta", 1)
class TouchesMeta(ResearchMeta):
    """ Metadata for a touches file (one symbol-year). """

    @model_validator(mode="after")
    def _touches_stage(self) -> Self:
        if self.stage is not Stage.TOUCHES:
            raise ValueError(f"TouchesMeta needs stage=touches, got {self.stage}")
        return self
#-
