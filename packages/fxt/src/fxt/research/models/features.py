'''
features

Config and metadata for the feature table (ML pipeline spec §4). Features are
keyed by bar, not by event: computed once per symbol and shared by every
strategy. Stored long (one row per bar x feature name), so adding a feature is
a new name, never a schema change.

    BarFeaturesConfig   the first feature set and its windows
    FeaturesMeta        metadata for every features file (adds the feature names)
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from fxt.research.paths import Stage

from ._registry import registry
from .config import StageConfig
from .meta import ResearchMeta

__all__ = ["BarFeaturesConfig", "FeaturesMeta"]


@registry.register("BarFeaturesConfig", 1)
class BarFeaturesConfig(StageConfig):
    """ Per-bar features on `interval` bars, valid at each bar's CLOSE (bar_time).

    Every window counts bars of data (business hours for 1HOUR), looks only
    backwards, and includes the bar itself: a value at bar_time uses nothing
    that closed later. A window needs `min_coverage` of its values to exist;
    otherwise the feature is missing for that bar (no row is written).

        ret_{h}h                log(close / close h bars earlier)
        ret_{h}h_z              ret_{h}h / (vol_{long}h * sqrt(h))
        vol_{w}h                std of 1-bar log returns over w bars (returns spanning
                                more than max_gap_hours, i.e. weekends, are left out)
        vol_ratio_{s}h_{l}h     vol_{short} / vol_{long}
        spread_bp_{s}h          mean spread over `short` bars, in bp of mid_close
        spread_ratio_{s}h_{l}h  mean spread over `short` / over `long`
        tick_ratio_{s}h_{l}h    mean tick_count over `short` / over `long`
                                (tick density varies by year: use the ratio, not counts)
        hour_utc, dow_utc       hour (0-23) and weekday (1=Mon .. 7=Sun) of bar_time, UTC
    """
    stage = Stage.FEATURES

    feature_set: Literal["baseline"] = "baseline"             # which builder; new sets get new names
    interval: Literal["1HOUR"] = "1HOUR"
    ret_horizons: tuple[int, ...] = (1, 4, 24, 120)
    short: int = Field(24, ge=2)                              # bars
    long: int = Field(120, ge=3)                              # bars
    max_gap_hours: float = Field(3.0, gt=0)
    min_coverage: float = Field(0.9, gt=0, le=1)
    calendar: bool = True

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.short >= self.long:
            raise ValueError(f"short ({self.short}) must be < long ({self.long})")
        if not self.ret_horizons or any(h < 1 for h in self.ret_horizons):
            raise ValueError("ret_horizons must be positive bar counts")
        if len(set(self.ret_horizons)) != len(self.ret_horizons):
            raise ValueError("ret_horizons must be distinct")
        return self

    def names(self) -> tuple[str, ...]:
        """ Every feature name this config produces, in output order. """
        s, lg = self.short, self.long
        out = [f"ret_{h}h" for h in self.ret_horizons] + [f"ret_{h}h_z" for h in self.ret_horizons]
        out += [f"vol_{s}h", f"vol_{lg}h", f"vol_ratio_{s}h_{lg}h",
                f"spread_bp_{s}h", f"spread_ratio_{s}h_{lg}h", f"tick_ratio_{s}h_{lg}h"]
        if self.calendar:
            out += ["hour_utc", "dow_utc"]
        return tuple(out)

    @property
    def label(self) -> str:
        return f"{self.feature_set}_{self.short}h_{self.long}h"
#


@registry.register("FeaturesMeta", 1)
class FeaturesMeta(ResearchMeta):
    """ Metadata for a features file (one symbol-year). """
    names: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _features_stage(self) -> Self:
        if self.stage is not Stage.FEATURES:
            raise ValueError(f"FeaturesMeta needs stage=features, got {self.stage}")
        return self
#-
