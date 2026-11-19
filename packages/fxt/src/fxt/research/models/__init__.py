'''
fxt.research.models

Stage config models and research file metadata, plus their registry.

Every model module must be imported here: models register on import, and a
file can only be read back if its model is registered. Stage-specific models
(EventsMeta, CusumEventsConfig, ...) are added as each stage is built.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from ._registry import registry
from .config import (
    HARNESS_KINDS, INPUT_SUFFIX, ConfigHash, ConfigRuleError, HarnessConfig, HashedConfig, StageConfig,
    input_hashes_of,
)
from .meta import FileRef, ResearchMeta, SymbolKey
from .events import CusumEventsConfig, EventsMeta, RandomEventsConfig, SamplerConfig
from .touches import TouchesMeta, TripleBarrierTouchConfig
from .labels import SIDE_RULES, LabelsMeta, SideLabelsConfig
from .weights import SampleWeightsConfig, WeightsMeta
from .features import (
    BarFeaturesConfig, FeatureSetConfig, FeaturesMeta, FlowFeaturesConfig, TrendFeaturesConfig,
)
from .harness import (
    OUTCOME_CLASSES, BacktestConfig, GBMModelConfig, GBMMulticlassModelConfig, LogisticModelConfig, LogisticModelConfigV1, ModelConfig, SizerConfig, TakeAllModelConfig, WalkForwardConfig,
)

__all__ = [
    "registry",
    "HARNESS_KINDS", "INPUT_SUFFIX", "ConfigHash", "ConfigRuleError", "HarnessConfig", "HashedConfig",
    "StageConfig", "input_hashes_of",
    "FileRef", "ResearchMeta", "SymbolKey",
    "CusumEventsConfig", "EventsMeta", "RandomEventsConfig", "SamplerConfig",
    "TouchesMeta", "TripleBarrierTouchConfig",
    "SIDE_RULES", "LabelsMeta", "SideLabelsConfig",
    "SampleWeightsConfig", "WeightsMeta",
    "BarFeaturesConfig", "FeatureSetConfig", "FeaturesMeta", "FlowFeaturesConfig", "TrendFeaturesConfig",
    "OUTCOME_CLASSES", "BacktestConfig", "GBMModelConfig", "GBMMulticlassModelConfig", "LogisticModelConfig", "LogisticModelConfigV1", "ModelConfig", "SizerConfig", "TakeAllModelConfig",
    "WalkForwardConfig",
]
