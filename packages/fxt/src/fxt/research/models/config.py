'''
config

HashedConfig: the hash rules + hash. StageConfig: research stage configs (events, labels, ...).
HarnessConfig: model / sizer / backtest / cv configs (no research files).

    @registry.register("CusumEventsConfig", 1)
    class CusumEventsConfig(StageConfig):
        stage = Stage.EVENTS
        h: float = 3.0
        vol_window_days: int = 1
        note: str = Field("", exclude=True)     # not hashed, not stored

    cfg = CusumEventsConfig()
    cfg.config_hash()      # "3f9a1c0d2e4b"

    @registry.register("TripleBarrierConfig", 1)
    class TripleBarrierConfig(StageConfig):
        stage = Stage.LABELS
        events_hash: ConfigHash                  # upstream input -> lineage
        k: float = 1.0
    cfg.input_hashes()     # {"events": "3f9a1c0d2e4b"}

Hash rules (ML pipeline spec §3.2), enforced when the class is defined:
- no `int | float` unions: type numbers explicitly. A `float` field turns 1
  into 1.0 before dumping, so `k=1` and `k=1.0` hash the same; a union keeps
  them apart and would split identical configs into two output sets.
- no sets / frozensets: their dump order isn't stable across runs.
- upstream inputs are fields named `<role>_hash`, typed `ConfigHash`.
- non-semantic fields (notes, labels) use Field(exclude=True): they're left
  out of the dump, so they never change the hash (and aren't stored).
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import types
import typing
from typing import Annotated, Any, ClassVar, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, StringConstraints

from fxt.core.hashing import HASH_PATTERN, content_hash
from fxt.core.versioned import VersionedModel
from fxt.research.paths import Stage

__all__ = ["HARNESS_KINDS", "INPUT_SUFFIX", "ConfigHash", "ConfigRuleError", "HarnessConfig", "HashedConfig",
           "StageConfig", "input_hashes_of"]

ConfigHash = Annotated[str, StringConstraints(pattern=HASH_PATTERN)]
INPUT_SUFFIX = "_hash"


class ConfigRuleError(TypeError):
    """ A config class breaks one of the hashing rules. """


#!================================================================================(80)
#! annotation rules
#!--------------------------------------------------------------------------------(80)
def _check_annotation(owner: str, field: str, ann: Any, seen: set[type]) -> None:
    origin = get_origin(ann)

    if origin is Annotated:
        _check_annotation(owner, field, get_args(ann)[0], seen)
        return

    if ann in (set, frozenset) or origin in (set, frozenset, typing.AbstractSet):
        raise ConfigRuleError(
            f"{owner}.{field}: sets aren't allowed in configs (unstable order); use a tuple"
        )

    if origin in (Union, types.UnionType):
        args = get_args(ann)
        if int in args and float in args:
            raise ConfigRuleError(
                f"{owner}.{field}: `int | float` makes 1 and 1.0 hash differently; "
                f"pick one type (usually float)"
            )
        for a in args:
            _check_annotation(owner, field, a, seen)
        return

    if origin is not None:                       # list[...], tuple[...], dict[...]
        for a in get_args(ann):
            if a is not Ellipsis:
                _check_annotation(owner, field, a, seen)
        return

    #! nested models: their fields are hashed too
    if isinstance(ann, type) and issubclass(ann, BaseModel) and ann not in seen:
        seen.add(ann)
        for name, info in ann.model_fields.items():
            _check_annotation(ann.__qualname__, name, info.annotation, seen)
#

def input_hashes_of(payload: dict[str, Any]) -> dict[str, str]:
    """ {role: hash} from a dumped config: every `<role>_hash` key. """
    return {k.removesuffix(INPUT_SUFFIX): v for k, v in payload.items()
            if k.endswith(INPUT_SUFFIX) and isinstance(v, str)}
#


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class HashedConfig(VersionedModel):
    """ Unregistered base for every hashed config: the hash rules and the hash itself.
        Research stage configs subclass StageConfig; configs that write no research
        files (model, sizer, backtest, cv) subclass HarnessConfig.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        seen: set[type] = set()
        for name, info in cls.model_fields.items():
            _check_annotation(cls.__qualname__, name, info.annotation, seen)
            if name.endswith(INPUT_SUFFIX) and info.exclude:
                raise ConfigRuleError(
                    f"{cls.__qualname__}.{name}: input hashes must be hashed; drop exclude=True"
                )
    #

    @classmethod
    def config_kind(cls) -> str:
        """ What the config is for: a research stage, or model / sizer / backtest / cv. """
        raise NotImplementedError

    def payload(self) -> dict[str, Any]:
        """ What gets hashed and stored: the JSON-mode dump (excluded fields dropped). """
        return self.model_dump(mode="json")

    def config_hash(self) -> str:
        """ 12-char hash of type id + payload. Requires the class to be registered. """
        return content_hash(self.get_id(), self.payload())

    def input_hashes(self) -> dict[str, str]:
        """ {role: hash} for every upstream input, e.g. {"events": "3f9a1c0d2e4b"}. """
        return input_hashes_of(self.payload())
#


class StageConfig(HashedConfig):
    """ Unregistered base for stage configs. Subclasses set `stage` and register. """

    stage: ClassVar[Stage]

    @classmethod
    def get_stage(cls) -> Stage:
        stage = cls.__dict__.get("stage") or getattr(cls, "stage", None)
        if not isinstance(stage, Stage):
            raise ConfigRuleError(f"{cls.__qualname__} doesn't set `stage = Stage.<...>`")
        return stage

    @classmethod
    def config_kind(cls) -> str:
        return str(cls.get_stage())
#


HARNESS_KINDS = ("model", "sizer", "backtest", "cv")


class HarnessConfig(HashedConfig):
    """ Unregistered base for configs used by the evaluation harness (no research files).
        Subclasses set `kind` (one of HARNESS_KINDS) and register.
    """

    kind: ClassVar[str]

    @classmethod
    def config_kind(cls) -> str:
        kind = getattr(cls, "kind", None)
        if kind not in HARNESS_KINDS:
            raise ConfigRuleError(f"{cls.__qualname__}.kind must be one of {HARNESS_KINDS}, got {kind!r}")
        return kind
#-
