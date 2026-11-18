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
from .config import INPUT_SUFFIX, ConfigHash, ConfigRuleError, StageConfig, input_hashes_of
from .meta import FileRef, ResearchMeta, SymbolKey
from .events import CusumEventsConfig, EventsMeta, SamplerConfig

__all__ = [
    "registry",
    "INPUT_SUFFIX", "ConfigHash", "ConfigRuleError", "StageConfig", "input_hashes_of",
    "FileRef", "ResearchMeta", "SymbolKey",
    "CusumEventsConfig", "EventsMeta", "SamplerConfig",
]
