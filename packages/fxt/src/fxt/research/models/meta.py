'''
meta

Metadata carried by every research file (ML pipeline spec §3.3).

    SymbolKey     which series a file belongs to (source/market/symbol)
    FileRef       one input file: which root, where, what metadata type, its hash
    ResearchMeta  unregistered base: config + lineage + checks

Each stage subclasses ResearchMeta and registers it when the stage is built:

    @registry.register("EventsMeta", 1)
    class EventsMeta(ResearchMeta):
        ...

    meta = EventsMeta.for_config(cfg, dataset=..., year=2020, rows=len(df), inputs=(...))

Integrity rules, checked whenever a meta is built OR read back:
- `config_hash` must equal the hash recomputed from `config_typeid` + `config`.
  Reading a file needs no config class for this: the stored dict is exactly
  what was hashed.
- `input_hashes` must equal the `<role>_hash` entries of `config`.
- `year` is set exactly when the stage is split by year.

Two kinds of lineage, on purpose:
- `input_hashes`: which upstream *configs* this used (stable across reruns).
- `inputs`: which upstream *files* this read, with sha256. A config hash
  doesn't change when the bars underneath are rebuilt; these hashes do, so
  stale outputs can be detected later.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from fxt.core.hashing import content_hash
from fxt.core.versioned import VersionedModel
from fxt.lake.models.base import CheckRecord, Component, utcnow
from fxt.research.paths import ResearchKey, Stage

from .config import ConfigHash, StageConfig, input_hashes_of

__all__ = ["FileRef", "ResearchMeta", "SymbolKey"]


#!================================================================================(80)
#! components
#!--------------------------------------------------------------------------------(80)
class SymbolKey(Component):
    """ Which series a research file belongs to. No interval: a research table
        can draw on several intervals (1HOUR for events, 1MIN for labels).
    """
    source: str
    market: str
    symbol: str

    def __str__(self) -> str:
        return f"{self.source}/{self.market}/{self.symbol}"
#

class FileRef(Component):
    """ One input file. `path` is posix and relative to `root`'s directory. """
    root: Literal["lake", "research"]
    path: str
    typeid: str        # the input's stored type id, copied as-is
    sha256: str
#


#!================================================================================(80)
#! base meta
#!--------------------------------------------------------------------------------(80)
class ResearchMeta(VersionedModel):
    """ Unregistered base for research file metadata. """
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Stage
    config_hash: ConfigHash
    config_typeid: str                                  # e.g. "CusumEventsConfig@1"
    config: dict[str, JsonValue]                        # the hashed payload
    input_hashes: dict[str, ConfigHash] = Field(default_factory=dict)
    dataset: SymbolKey
    year: int | None = None
    rows: int = Field(ge=0)
    inputs: tuple[FileRef, ...] = ()
    checks: tuple[CheckRecord, ...] = ()
    code_version: str | None = None                     # git commit, "+dirty" if uncommitted changes
    created_at: AwareDatetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _check_integrity(self) -> Self:
        expected = content_hash(self.config_typeid, self.config)
        if self.config_hash != expected:
            raise ValueError(
                f"config_hash {self.config_hash} doesn't match the stored config "
                f"(recomputed {expected}); the config or its hash was altered"
            )
        derived = input_hashes_of(self.config)
        if self.input_hashes != derived:
            raise ValueError(f"input_hashes {self.input_hashes} don't match the config's {derived}")
        if self.stage.yearly and self.year is None:
            raise ValueError(f"{self.stage} files are split by year; year is required")
        if not self.stage.yearly and self.year is not None:
            raise ValueError(f"{self.stage} files aren't split by year; got year={self.year}")
        return self
    #

    #~ building ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~(70)
    @classmethod
    def for_config(
        cls,
        config: StageConfig,
        *,
        dataset: SymbolKey,
        rows: int,
        year: int | None = None,
        inputs: tuple[FileRef, ...] = (),
        checks: tuple[CheckRecord, ...] = (),
        code_version: str | None = None,
        created_at: datetime | None = None,
    ) -> Self:
        """ Build the meta for one file produced by `config`. """
        payload = config.payload()
        extra: dict[str, Any] = {} if created_at is None else {"created_at": created_at}
        return cls(
            stage=config.get_stage(),
            config_hash=content_hash(config.get_id(), payload),
            config_typeid=config.get_id(),
            config=payload,
            input_hashes=input_hashes_of(payload),
            dataset=dataset,
            year=year,
            rows=rows,
            inputs=tuple(inputs),
            checks=tuple(checks),
            code_version=code_version,
            **extra,
        )
    #

    #~ derived ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~(70)
    @property
    def key(self) -> ResearchKey:
        """ Where this file belongs under data/research. """
        return ResearchKey(stage=self.stage, config=self.config_hash,
                           source=self.dataset.source, market=self.dataset.market,
                           symbol=self.dataset.symbol, year=self.year)

    @property
    def passed(self) -> bool:
        """ True if no check FAILed or ERRORed (same rule as DerivedMeta). """
        return all(c.ok for c in self.checks)

    @property
    def failed_checks(self) -> tuple[CheckRecord, ...]:
        return tuple(c for c in self.checks if not c.ok)

    def same_config(self, other: ResearchMeta) -> bool:
        return (self.config_typeid, self.config) == (other.config_typeid, other.config)
#-
