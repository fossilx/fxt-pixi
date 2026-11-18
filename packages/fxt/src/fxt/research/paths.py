'''
paths

Path builder for data/research: tables whose contents depend on a config.

    data/research/<stage>/config=<hash>/source=…/market=…/symbol=…/year=…/SYMBOL-YYYY.parquet
    (stages: features, events, touches, labels)
    data/research/weights/config=<hash>/source=…/market=…/symbol=…/SYMBOL.parquet

- `config=` comes first, so everything one config produced is one folder.
- Yearly stages are partitioned by the year of each row's key time
  (bar_time for features, t0 for events, touches and labels).
- Weights aren't split by year: concurrency spans year boundaries.

Kept separate from fxt.lake.Lake on purpose: the lake never holds anything
keyed by a config hash. (ML pipeline spec §3.1)
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from fxt.core.hashing import HASH_LEN
from fxt.lake.paths import _SAFE

__all__ = ["RESEARCH_KEYS", "ResearchKey", "ResearchPathNotFound", "Research", "Stage"]


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
class Stage(StrEnum):
    """ Research table types (top-level folders under data/research). """
    FEATURES = "features"
    EVENTS = "events"
    TOUCHES = "touches"      # side-agnostic triple-barrier touch pass (labels step 1)
    LABELS = "labels"
    WEIGHTS = "weights"

    @property
    def yearly(self) -> bool:
        """ True if files are split by year (everything except weights). """
        return self is not Stage.WEIGHTS
#

#! folder order under data/research/<stage>/
RESEARCH_KEYS = ("config", "source", "market", "symbol", "year")


class ResearchPathNotFound(FileNotFoundError):
    """ Raised when a research path is required to exist but doesn't. """


def _check_value(key: str, value: object) -> str:
    s = str(value)
    if not _SAFE.fullmatch(s):
        raise ValueError(f"Unsafe {key} value: {s!r}")
    if key == "config" and (len(s) != HASH_LEN or any(c not in "0123456789abcdef" for c in s)):
        raise ValueError(f"config must be a {HASH_LEN}-char lowercase hex hash: {s!r}")
    return s
#


class ResearchKey(BaseModel):
    """ Where one research file lives. `year` is None exactly when the stage isn't yearly. """
    model_config = ConfigDict(frozen=True)
    stage:  Stage
    config: str
    source: str
    market: str
    symbol: str
    year:   int | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        for k in RESEARCH_KEYS:
            v = getattr(self, k)
            if v is not None:
                _check_value(k, v)
        if self.stage.yearly and self.year is None:
            raise ValueError(f"{self.stage} files are split by year; year is required")
        if not self.stage.yearly and self.year is not None:
            raise ValueError(f"{self.stage} files aren't split by year; got year={self.year}")
        return self

    @classmethod
    def from_path(cls, rel: Path) -> ResearchKey:
        """ From a path relative to the research root: <stage>/config=…/…/file """
        stage = Stage(rel.parts[0])
        parts = dict(p.split("=", 1) for p in rel.parts[1:] if "=" in p)
        return cls(stage=stage, **{k: parts[k] for k in RESEARCH_KEYS if k in parts})

    @property
    def filename(self) -> str:
        return f"{self.symbol}-{self.year}.parquet" if self.stage.yearly else f"{self.symbol}.parquet"

    def parts(self) -> dict[str, str | int]:
        """ The folder keys, in order, without the stage. """
        return {k: getattr(self, k) for k in RESEARCH_KEYS if getattr(self, k) is not None}
#


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class Research(BaseModel):
    """ Builds and scans paths under data/research. """
    model_config = ConfigDict(frozen=True)
    root: Path

    #~======================================================================(70)
    #~ path generator
    #~----------------------------------------------------------------------(70)
    def path(self,
        stage: Stage | str,
        *,
        config:     str | None = None,
        source:     str | None = None,
        market:     str | None = None,
        symbol:     str | None = None,
        year:       int | str | None = None,
        filename:   str | None = None,
        must_exist: bool = True,
    ) -> Path:
        """ Hive-style path, e.g. events/config=3f9a1c0d2e4b/source=dukascopy/…

            Levels must be given in order: a level can't be set while an
            earlier one is missing. `year` is rejected for non-yearly stages.
        """
        stage = Stage(stage)
        if year is not None and not stage.yearly:
            raise ValueError(f"{stage} files aren't split by year; got year={year}")

        values = {"config": config, "source": source, "market": market,
                  "symbol": symbol, "year": year}
        rtn = self.root / stage

        missing: str | None = None
        for key in RESEARCH_KEYS:
            v = values[key]
            if v is None:
                missing = missing or key
                continue
            if missing:
                raise ValueError(f"'{key}' given but '{missing}' is missing")
            rtn /= f"{key}={_check_value(key, v)}"

        if filename is not None:
            needed = "year" if stage.yearly else "symbol"
            if values[needed] is None:
                raise ValueError(f"filename given but '{missing}' is missing")
            rtn /= filename

        if must_exist and not rtn.exists():
            raise ResearchPathNotFound(f"Path doesn't exist in research: {rtn}")
        return rtn
    #

    def file(self, key: ResearchKey, *, must_exist: bool = False) -> Path:
        """ Full file path for a key. """
        return self.path(key.stage, **key.parts(), filename=key.filename, must_exist=must_exist)

    def config_dir(self, stage: Stage | str, config: str) -> Path:
        """ data/research/<stage>/config=<hash> (may not exist yet). """
        return self.path(stage, config=config, must_exist=False)

    #~======================================================================(70)
    #~ scanning
    #~----------------------------------------------------------------------(70)
    def scan(self, stage: Stage | str, **filters) -> list[tuple[ResearchKey, Path]]:
        """ Every well-placed file of `stage` matching the filters, sorted by path.
            Stray or misnamed files are skipped.
        """
        stage = Stage(stage)
        if bad := set(filters) - set(RESEARCH_KEYS):
            raise ValueError(f"Unknown research keys: {bad}")
        if "year" in filters and not stage.yearly:
            raise ValueError(f"{stage} files aren't split by year")

        keys = [k for k in RESEARCH_KEYS if stage.yearly or k != "year"]
        prefix: dict[str, object] = {}
        for k in keys:
            if k not in filters:
                break
            prefix[k] = filters[k]
        try:
            base = self.path(stage, **prefix)  # type: ignore[arg-type]
        except ResearchPathNotFound:
            return []

        rest = "/".join(f"{k}=*" for k in keys[len(prefix):])
        out = []
        for p in sorted(base.glob(f"{rest}/*.parquet" if rest else "*.parquet")):
            try:
                key = ResearchKey.from_path(p.relative_to(self.root))
            except (KeyError, ValueError):
                continue
            if p.name != key.filename:
                continue
            if all(str(getattr(key, k)) == str(v) for k, v in filters.items()):
                out.append((key, p))
        return out
    #

    def configs(self, stage: Stage | str) -> list[str]:
        """ Config hashes that have a folder under `stage`. """
        base = self.root / Stage(stage)
        if not base.is_dir():
            return []
        return sorted(p.name.split("=", 1)[1] for p in base.glob("config=*") if p.is_dir())
#-
