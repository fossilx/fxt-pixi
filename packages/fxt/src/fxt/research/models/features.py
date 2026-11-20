'''
features

Config and metadata for the feature table (ML pipeline spec §4). Features are
keyed by bar, not by event: computed once per symbol and shared by every
strategy. Stored long (one row per bar x feature name), so adding a feature is
a new name, never a schema change.

    FeatureSetConfig    base for every feature set (names, which names are signed, bar columns)
    BarFeaturesConfig   the baseline set: returns, vol, spread, ticks, calendar
    TrendFeaturesConfig directional set: distance from moving averages, range position,
                        trend efficiency, return since the UTC day began
    FlowFeaturesConfig  order-flow set from 1MIN bars: quoted-depth imbalance, tick-direction
                        and activity-weighted direction imbalance, activity and spread surges
    CrossFeaturesConfig cross-pair set: how each leg's currency moved in the *other* pairs of a
                        basket (which currency is driving the move)
    FeaturesMeta        metadata for every features file (adds the feature names)

Signed features: a feature is *signed* when its sign says which way price went
(a return, a distance above/below an average). Meta-labels are side-adjusted, so
the harness can feed the model `side x value` for signed features (spec §8.1);
`signed_names()` says which ones.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import itertools
from typing import ClassVar, Literal, Self

from pydantic import Field, model_validator

from fxt.research.paths import Stage

from ._registry import registry
from .config import StageConfig
from .meta import ResearchMeta

__all__ = ["BarFeaturesConfig", "CrossFeaturesConfig", "FeatureSetConfig", "FeaturesMeta", "FlowFeaturesConfig",
           "TrendFeaturesConfig", "split_pair"]


def split_pair(symbol: str) -> tuple[str, str]:
    """ "EURJPY" -> ("EUR", "JPY"). """
    s = symbol.upper()
    if len(s) != 6 or not s.isalpha():
        raise ValueError(f"not a 6-letter currency pair: {symbol!r}")
    return s[:3], s[3:]


class FeatureSetConfig(StageConfig):
    """ Unregistered base for feature-set configs. Every set writes the same long table;
        sets differ in names. Subclasses register, set the `feature_set` field's Literal,
        and implement names(); a builder is registered in fxt.research.features.
    """
    stage = Stage.FEATURES
    bar_interval: ClassVar[str] = "1HOUR"

    def names(self) -> tuple[str, ...]:
        raise NotImplementedError

    def signed_names(self) -> tuple[str, ...]:
        """ Names whose sign carries direction (side-alignable). """
        return ()

    def bar_columns(self) -> tuple[str, ...]:
        return ("time", "mid_close")
#


@registry.register("BarFeaturesConfig", 1)
class BarFeaturesConfig(FeatureSetConfig):
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

    def signed_names(self) -> tuple[str, ...]:
        return tuple(f"ret_{h}h" for h in self.ret_horizons) + tuple(f"ret_{h}h_z" for h in self.ret_horizons)

    def bar_columns(self) -> tuple[str, ...]:
        return ("time", "mid_close", "spread_mean", "tick_count")

    @property
    def label(self) -> str:
        return f"{self.feature_set}_{self.short}h_{self.long}h"
#


@registry.register("TrendFeaturesConfig", 1)
class TrendFeaturesConfig(FeatureSetConfig):
    """ Directional features on 1HOUR bars, valid at each bar's close, every one signed.

    Same conventions as BarFeaturesConfig: windows count bars of data, include the bar
    itself, look only backwards, and need `min_coverage` of their values. `vol` is the
    std of 1-bar log returns over `vol_window` bars (gap returns left out), as vol_120h.

        ma_dist_{w}h            log(close / SMA_w(close)) / (vol * sqrt(w))
        ma_cross_{a}h_{b}h      log(SMA_a / SMA_b) / (vol * sqrt(b)), for consecutive windows a < b
        range_pos_{w}h          (close - lowest low_w) / (highest high_w - lowest low_w) - 0.5,
                                in [-0.5, 0.5]: where price sits in its recent range
        trend_eff_{w}h          log(close / close w bars earlier) / sum of |1-bar log returns|
                                over those w bars, in [-1, 1]: net move per unit of path
                                (Kaufman's efficiency ratio, signed)
        ret_day_z               log(close / open of the UTC day's first bar) / (vol * sqrt(n)),
                                n = bars so far that day
    """
    feature_set: Literal["trend"] = "trend"
    interval: Literal["1HOUR"] = "1HOUR"
    windows: tuple[int, ...] = (24, 120)
    vol_window: int = Field(120, ge=3)
    max_gap_hours: float = Field(3.0, gt=0)
    min_coverage: float = Field(0.9, gt=0, le=1)
    day_return: bool = True

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.windows or any(w < 2 for w in self.windows):
            raise ValueError("windows must be bar counts >= 2")
        if list(self.windows) != sorted(set(self.windows)):
            raise ValueError("windows must be distinct and increasing")
        return self

    def names(self) -> tuple[str, ...]:
        w = self.windows
        out = [f"ma_dist_{x}h" for x in w]
        out += [f"ma_cross_{a}h_{b}h" for a, b in itertools.pairwise(w)]
        out += [f"range_pos_{x}h" for x in w] + [f"trend_eff_{x}h" for x in w]
        if self.day_return:
            out.append("ret_day_z")
        return tuple(out)

    def signed_names(self) -> tuple[str, ...]:
        return self.names()

    def bar_columns(self) -> tuple[str, ...]:
        return ("time", "mid_open", "mid_high", "mid_low", "mid_close")

    @property
    def label(self) -> str:
        return f"trend_{'_'.join(str(x) for x in self.windows)}h"
#


@registry.register("FlowFeaturesConfig", 1)
class FlowFeaturesConfig(FeatureSetConfig):
    """ Order-flow features from 1MIN bars, valid at each hourly bar's close (bar_time).

    Minutes are grouped into their clock hour (the hourly bar they belong to); windows
    count hours of data, include the hour itself and need `min_coverage` of their hours.
    A minute's direction is the sign of its mid_close change from the previous minute;
    changes across a gap longer than `max_gap_minutes` don't count. bid_volume /
    ask_volume are Dukascopy's quoted sizes at the best bid / ask, summed over ticks:
    a measure of resting depth on each side, not traded volume.

        depth_imb_{w}h      (sum bid_volume - sum ask_volume) / (sum of both), in [-1, 1]
        tick_imb_{w}h       (up minutes - down minutes) / (up + down minutes), in [-1, 1]
        flow_imb_{w}h       sum(direction x tick_count) / sum(tick_count): direction weighted
                            by activity, in [-1, 1]
        depth_imb_1h_dev    depth_imb_1h minus its mean over the last `dev_window` hours
                            (quoted depth can lean one way for long stretches)
        activity_1h_{a}h    ticks in the hour / mean ticks per hour over `activity_window` hours
        spread_1h_{a}h      the hour's mean spread / mean over `activity_window` hours

    Signed (side-alignable): the three imbalances and depth_imb_1h_dev.
    """
    feature_set: Literal["flow"] = "flow"
    interval: Literal["1MIN"] = "1MIN"                         # source bars; output is hourly
    windows: tuple[int, ...] = (1, 4, 24)                      # hours
    dev_window: int = Field(120, ge=2)
    activity_window: int = Field(24, ge=2)
    max_gap_minutes: float = Field(5.0, gt=0)
    min_coverage: float = Field(0.9, gt=0, le=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.windows or any(w < 1 for w in self.windows):
            raise ValueError("windows must be hour counts >= 1")
        if list(self.windows) != sorted(set(self.windows)):
            raise ValueError("windows must be distinct and increasing")
        return self

    def _imbalances(self) -> list[str]:
        return [f"{k}_imb_{w}h" for k in ("depth", "tick", "flow") for w in self.windows]

    def names(self) -> tuple[str, ...]:
        a = self.activity_window
        return (*self._imbalances(), "depth_imb_1h_dev", f"activity_1h_{a}h", f"spread_1h_{a}h")

    def signed_names(self) -> tuple[str, ...]:
        return (*self._imbalances(), "depth_imb_1h_dev")

    def bar_columns(self) -> tuple[str, ...]:
        return ("time", "mid_close", "bid_volume", "ask_volume", "tick_count", "spread_mean")

    @property
    def label(self) -> str:
        return f"flow_{'_'.join(str(x) for x in self.windows)}h"
#


@registry.register("CrossFeaturesConfig", 1)
class CrossFeaturesConfig(FeatureSetConfig):
    """ Cross-pair features: what each leg's currency did in the *other* pairs of a basket,
        valid at each hourly bar close of the target pair.

    For every basket pair, z_h = log(close / close h bars earlier) / (vol x sqrt(h)), with vol
    the std of 1-bar log returns over `vol_window` bars (gap returns left out): the same
    vol-normalized return as the baseline set's ret_{h}h_z. A currency's strength over h is
    the mean of +z_h over basket pairs where it's the base and -z_h where it's the quote,
    **leaving out the target pair itself** (its own return is already in the baseline set).
    Pairs are aligned on bar_time; a currency with no other pair at that bar has no value.

        base_str_{h}h     strength of the target's base currency in the other pairs
        quote_str_{h}h    strength of the target's quote currency in the other pairs
        driver_{h}h       (|base_str| - |quote_str|) / (|base_str| + |quote_str|), in [-1, 1]:
                          +1 = the base currency is doing the moving, -1 = the quote

    For EURJPY in the EUR/USD/JPY basket: base_str = EURUSD's z, quote_str = -USDJPY's z.
    Signed (side-alignable): base_str, quote_str. driver is direction-free.
    """
    feature_set: Literal["cross"] = "cross"
    interval: Literal["1HOUR"] = "1HOUR"
    basket: tuple[str, ...] = ("EURJPY", "EURUSD", "USDJPY")
    horizons: tuple[int, ...] = (4, 24, 120)
    vol_window: int = Field(120, ge=3)
    max_gap_hours: float = Field(3.0, gt=0)
    min_coverage: float = Field(0.9, gt=0, le=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(self.basket) < 2 or list(self.basket) != sorted(set(self.basket)):
            raise ValueError("basket: at least two distinct pairs, sorted")
        for s in self.basket:
            split_pair(s)
        if not self.horizons or list(self.horizons) != sorted(set(self.horizons)) or self.horizons[0] < 1:
            raise ValueError("horizons must be distinct, increasing bar counts >= 1")
        return self

    def names(self) -> tuple[str, ...]:
        return tuple(f"{k}_{h}h" for k in ("base_str", "quote_str", "driver") for h in self.horizons)

    def signed_names(self) -> tuple[str, ...]:
        return tuple(f"{k}_{h}h" for k in ("base_str", "quote_str") for h in self.horizons)

    def bar_columns(self) -> tuple[str, ...]:
        return ("time", "mid_close")

    @property
    def label(self) -> str:
        return "cross_" + "_".join(self.basket)
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
