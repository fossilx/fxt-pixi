'''
base

Building blocks shared by every lake metadata model.

    Component   small immutable value object embedded in metadata
    DatasetKey  which dataset a file belongs to (mirrors the lake's partition folders)
    Check       result of one verification check run before the file was written
    FileMeta    unregistered base for every file's metadata: dataset + period

Design rules
- Metadata is built once, right before the file is written, then never changed:
  every model is frozen, and collections are tuples.
- extra="forbid": a file holding fields the model doesn't know fails loudly.
  Adding or changing fields means registering a new version.
- Catalog values (source, market, symbol, interval) are plain strings. Check them
  against fxt.refdata when *building* metadata, never in a validator, so reading a
  file never needs the catalog DB.
- `start`/`end` is the period the file covers, half-open: [start, end).
  For a yearly file: start=2020-01-01T00:00Z, end=2021-01-01T00:00Z.
  This isn't the first/last timestamp in the data, so files for neighbouring
  periods line up exactly (end of one == start of the next).
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
# stop pylance from being annoying by adding this to end of line:  # type: ignore
# https://rich.readthedocs.io/en/stable/appendix/colors.html


#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations

from datetime import datetime, timezone, UTC
from typing import Self, Literal, Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from fxt.core.versioned import VersionedModel


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def utcnow() -> datetime:
    return datetime.now(UTC) #timezone.utc)


#!================================================================================(80)
#! components
#!--------------------------------------------------------------------------------(80)
class Component(BaseModel):
    """ Small immutable value object embedded in metadata.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")
#


class DatasetKey(Component):
    """ Which dataset a file belongs to. Mirrors the lake's partition folders
        (source=/market=/symbol=/interval=). Hashable, so it can be used as
        a dict key or compared directly.
    """
    source: str      # "dukascopy"
    market: str      # "forex"
    symbol: str      # filesystem-safe form: "EURJPY"
    interval: str    # "TICK", "1MIN", "1HOUR"

    def with_interval(self, interval: str) -> DatasetKey:
        return self.model_copy(update={"interval": interval})

    def __str__(self) -> str:
        return f"{self.source}/{self.market}/{self.symbol}/{self.interval}"
#


CheckStatus = Literal["pass", "warn", "fail", "error", "skip"]
BAD_CHECK_STATUSES: frozenset[str] = frozenset({"fail", "error"})


class CheckRecord(Component):
    """ Stored result of one verification check (replaces ConsolidationTestComponent).

        Mirrors fxt.core.checks.CheckResult (status/detail/value) but keeps the
        status as a plain string, so reading a file never imports the check
        runner. Build one with `CheckRecord.from_result(check_id, result)`.
    """
    name: str                                    # check id, e.g. "bars 1MIN: time unique"
    status: CheckStatus
    detail: str = ""
    value: float | int | str | bool | None = None

    @property
    def ok(self) -> bool:
        """ Same rule as CheckResult.ok: only FAIL and ERROR are bad. """
        return self.status not in BAD_CHECK_STATUSES

    @classmethod
    def from_result(cls, name: str, result: Any) -> CheckRecord:
        """ From an fxt.core.checks.CheckResult (duck-typed: status/detail/value). """
        return cls(name=name, status=str(result.status), detail=result.detail or "", #type: ignore
                   value=result.value)
#



#!================================================================================(80)
#! base meta
#!--------------------------------------------------------------------------------(80)
class FileMeta(VersionedModel):
    """ Unregistered base for every lake file's metadata.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: DatasetKey
    start: AwareDatetime
    end: AwareDatetime
    created_at: AwareDatetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _check_period(self) -> Self:
        if self.start >= self.end:
            raise ValueError(f"start must be before end (start={self.start}, end={self.end})")
        return self
#-



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from pathlib import Path
    from rich import print

    print()
    print(f"hi2u ~ from [bold cyan]{Path(__file__).name}~[/]")
    print()


