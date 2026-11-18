'''
weights

Config and metadata for sample weights (ML pipeline spec §7).

    SampleWeightsConfig   which labels, which bars serve as the business clock
    WeightsMeta           metadata for a weights file (one per symbol, not split by year)

Both weightings are always written (`weight` = uniqueness x |ret|, `weight_uniq`
= uniqueness only); the model config picks the column, so switching the
return attribution off is a model experiment, not a new weights build.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from fxt.research.paths import Stage

from ._registry import registry
from .config import ConfigHash, StageConfig
from .meta import ResearchMeta

__all__ = ["SampleWeightsConfig", "WeightsMeta"]


@registry.register("SampleWeightsConfig", 1)
class SampleWeightsConfig(StageConfig):
    """ Concurrency-based uniqueness over each label's life, on business time.

        life        [t0, t1) on the business clock; a barrier exit lives through the
                    end of its touching minute (t1 + 1 min), so no life has zero length
        clock       hourly bars of data: time inside a bar counts pro rata, closed
                    stretches (weekends, holidays) count as nothing
        uniqueness  time-weighted mean of 1 / concurrency over the life
        weight      uniqueness * |ret|, rescaled to mean 1 over the symbol's labels
        weight_uniq uniqueness, rescaled to mean 1

    Concurrency counts only this label set's events (one symbol, one strategy):
    two strategies on the same pair are separate experiments.
    """
    stage = Stage.WEIGHTS

    labels_hash: ConfigHash                                   # which labels (one strategy)
    clock_interval: Literal["1HOUR"] = "1HOUR"                # bars that define business time

    @property
    def label(self) -> str:
        return "uniqueness"
#


@registry.register("WeightsMeta", 1)
class WeightsMeta(ResearchMeta):
    """ Metadata for a weights file (one symbol, every year). """

    @model_validator(mode="after")
    def _weights_stage(self) -> Self:
        if self.stage is not Stage.WEIGHTS:
            raise ValueError(f"WeightsMeta needs stage=weights, got {self.stage}")
        return self
#-
