'''
labels

Config and metadata for side labels: step 2 of triple-barrier labeling
(ML pipeline spec §6.3). Applies a side rule to each event's `direction`
and reads the touch from that side: the side's favorable barrier is a
profit-take, the other one a stop-loss.

    SideLabelsConfig   side rule, timeout rule, path_type thresholds
    LabelsMeta         metadata for every labels file
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
from .config import ConfigHash, StageConfig
from .meta import ResearchMeta

__all__ = ["LabelsMeta", "SIDE_RULES", "SideLabelsConfig"]

#! side rule -> multiplier applied to the event's direction
SIDE_RULES: dict[str, int] = {
    "follow": 1,     # trade the way the sampler fired (momentum / trade the break)
    "fade": -1,      # trade against it (mean reversion / false break)
}


@registry.register("SideLabelsConfig", 1)
class SideLabelsConfig(StageConfig):
    """ Side labels on top of a touch pass.

        side      = SIDE_RULES[side_rule] * direction
        outcome   = pt       touch on the side's favorable barrier (upper for a long)
                    sl       touch on the other barrier
                    timeout  vertical barrier
                    insufficient_data  (from the touch pass; never coerced)
        meta_label = 1 for pt, 0 for sl; timeouts are 0 unless timeout_positive_is_win
                     and the side-adjusted return is > 0; null when insufficient

    path_type thresholds are placeholders (v2 §6.3) until they're derived from
    data (v2 §6.4); they live here, not in the touch pass, so tuning them never
    forces a rescan.
    """
    stage = Stage.LABELS

    touches_hash: ConfigHash                                  # which touch pass to read
    side_rule: Literal["follow", "fade"] = "follow"
    timeout_positive_is_win: bool = False                     # not hitting a barrier isn't a win
    path_dir_exc: float = Field(0.3, ge=0)                    # directional: excursion_ratio <  this
    path_dir_net: float = Field(0.5, ge=0)                    #              and net_ratio    >  this
    path_range_exc: float = Field(0.5, ge=0)                  # ranging:     excursion_ratio >= this
    path_quiet_net: float = Field(0.3, ge=0)                  # quiet:       exc < dir_exc, net <= this

    @property
    def side_mult(self) -> int:
        return SIDE_RULES[self.side_rule]
#


@registry.register("LabelsMeta", 1)
class LabelsMeta(ResearchMeta):
    """ Metadata for a labels file (one symbol-year, one strategy). """
    strategy_id: str = Field(min_length=1)                    # e.g. "cusum_h3_follow"

    @model_validator(mode="after")
    def _labels_stage(self) -> Self:
        if self.stage is not Stage.LABELS:
            raise ValueError(f"LabelsMeta needs stage=labels, got {self.stage}")
        return self
#-
