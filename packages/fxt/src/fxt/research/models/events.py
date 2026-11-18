'''
events

Config and metadata models for the `events` stage (ML pipeline spec §5).

Events are side-agnostic: a sampler records *when* to look and the raw
direction of whatever fired (`direction`: +1 up, -1 down). Turning that into
a trade side (follow / fade / ...) is the side rule's job, applied in the
labels stage. That way cusum_follow and cusum_fade share one event set and
one touch pass (spec §6.1).

    CusumEventsConfig   two-sided CUSUM on vol-normalized bar returns
    EventsMeta          metadata for every events file (any sampler)
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from fxt.research.paths import Stage

from ._registry import registry
from .config import StageConfig
from .meta import ResearchMeta

__all__ = ["CusumEventsConfig", "EventsMeta"]


@registry.register("CusumEventsConfig", 1)
class CusumEventsConfig(StageConfig):
    """ Two-sided CUSUM of vol-normalized log returns of `price` on `interval` bars.

        z_t   = r_t / vol_{t-1}        r_t = log(price_t / price_{t-1})
        S_up  = max(0, S_up + z_t)     S_dn = min(0, S_dn + z_t)
        fire up if S_up > h, down if S_dn < -h; both accumulators reset on a fire

    Point-in-time: a bar's return is normalized by the vol estimate through the
    PREVIOUS bar, and the estimate is updated only after the bar is used. The
    event's t0 is the close of the triggering bar (open time + bar width).

    Defaults reproduce the first-pass implementation that h=3 was tuned on
    (fxtapps/derived/first_bars/cusum_events.py).
    """
    stage = Stage.EVENTS

    interval: str = "1HOUR"                                   # bar interval in data/lake/derived
    price: Literal["mid_close"] = "mid_close"                 # series the returns are taken from
    vol_estimator: Literal["ewma"] = "ewma"                   # EWMA of the bar returns themselves
    h: float = Field(3.0, gt=0)                               # threshold, cumulative std-devs
    vol_span: int = Field(120, ge=2)                          # EWMA span in bars (~5 trading days of 1HOUR)
    warmup: int = Field(48, ge=1)                             # returns used to seed vol; no events before
    max_gap_hours: float = Field(3.0, gt=0)                   # a return spanning more is a "gap return"
    reset_on_gap: bool = True                                 # zero the accumulators at a gap
    vol_floor: float = Field(1e-6, gt=0)                      # max(vol, floor), log-return units

    @field_validator("interval")
    @classmethod
    def _known_interval(cls, v: str) -> str:
        from fxt.lake.derived.bars import get_interval      # lazy: keeps model import light
        get_interval(v)
        return v

    @property
    def bar_seconds(self) -> int:
        from fxt.lake.derived.bars import get_interval
        return get_interval(self.interval).seconds

    @property
    def label(self) -> str:
        """ Short human-readable id, e.g. "cusum_h3" (not part of the hash). """
        return f"cusum_h{self.h:g}"
#


@registry.register("EventsMeta", 1)
class EventsMeta(ResearchMeta):
    """ Metadata for an events file (one symbol-year, any sampler). """
    sampler: str = Field(min_length=1)                        # e.g. "cusum"; from the config class

    @model_validator(mode="after")
    def _events_stage(self) -> Self:
        if self.stage is not Stage.EVENTS:
            raise ValueError(f"EventsMeta needs stage=events, got {self.stage}")
        return self
#-
