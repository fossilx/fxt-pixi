#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from pathlib import Path
from pydantic import BaseModel, ConfigDict
import re
from enum import StrEnum
#from functools import cache






#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
class LakeType(StrEnum):
    RAW = "raw"            # source of truth (data from broker/source)
    DERIVED = "derived"    # deterministic transforms of raw, one correct answer
    #! anything that depends on a parameter choice (features, events, labels,
    #! weights) lives in data/research instead: see fxt.research
#

PARTITION_KEYS = ("source", "market", "symbol", "interval", "year")
_SAFE = re.compile(r"[A-Za-z0-9_.\-]+")

class LakePathNotFound(FileNotFoundError):
    """
    """


class PartitionKey(BaseModel):
    model_config = ConfigDict(frozen=True)
    source:   str
    market:   str
    symbol:   str
    interval: str
    year:     int

    @classmethod
    def from_path(cls, path: Path) -> "PartitionKey":
        parts = dict(p.split("=", 1) for p in path.parts if "=" in p)
        return cls(**{k: parts[k] for k in PARTITION_KEYS})  # KeyError if a level is missing

    def replace(self, **changes) -> "PartitionKey":
        return PartitionKey(**{**self.model_dump(), **changes})  # re-validates, unlike model_copy

    @property
    def filename(self) -> str:
        return f"{self.symbol}-{self.year}.parquet"


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class Lake(BaseModel):
    """
        lake/raw
            the source of truth (aka data from broker/source)
        lake/derived
            holds deterministic transforms of raw that have one correct answer

        Anything that depends on a parameter choice (features, events, labels,
        weights) is keyed by a config hash and lives in data/research, built
        by fxt.research.Research, never here.
    """
    model_config = ConfigDict(frozen=True)
    root:Path


    #~======================================================================(70)
    #~ path generator
    #~----------------------------------------------------------------------(70)
    def _partition_path(self,
        laketype: LakeType|str,
        *,
        source:     str|None = None,
        market:     str|None = None,
        symbol:     str|None = None,
        interval:   str|None = None,
        year:       int|str|None = None,
        filename:   str|None = None,
        must_exist: bool=True
    ) -> Path:
        """ Build a hive-style lake path, e.g. raw/source=dukascopy/market=forex/...
        """
        values = {"source": source, "market": market, "symbol": symbol,
                  "interval": interval, "year": year}
        rtn = self.root / LakeType(laketype)   # raises ValueError on a bad type

        missing: str | None = None
        for key in PARTITION_KEYS:
            v = values[key]
            if v is None:
                missing = missing or key
                continue
            if missing:
                raise ValueError(f"'{key}' given but '{missing}' is missing")
            s = str(v)
            if not _SAFE.fullmatch(s):
                raise ValueError(f"Unsafe {key} value: {s!r}")
            rtn /= f"{key}={s}"

        if filename is not None:
            if missing:
                raise ValueError(f"filename given but '{missing}' is missing")
            rtn /= filename

        if must_exist and not rtn.exists():
            raise LakePathNotFound(f"Path doesn't exist in lake: {rtn}")
        return rtn
    #
    #! convenience methods
    def raw(self, **kwargs) -> Path:
        return self._partition_path(LakeType.RAW, **kwargs)
    def derived(self, **kwargs) -> Path:
        return self._partition_path(LakeType.DERIVED, **kwargs)


    #~======================================================================(70)
    #~ for scanning
    #~----------------------------------------------------------------------(70)
    def scan(self, laketype: LakeType|str = LakeType.RAW, **filters
             ) -> list[tuple[PartitionKey, Path]]:
        if bad := set(filters) - set(PARTITION_KEYS):
            raise ValueError(f"Unknown partition keys: {bad}")

        # the leading run of filters in key order becomes a real directory prefix
        prefix = {}
        for k in PARTITION_KEYS:
            if k not in filters: break
            prefix[k] = filters[k]
        try:
            base = self._partition_path(laketype, **prefix)
        except LakePathNotFound:
            return []

        rest = "/".join(f"{k}=*" for k in PARTITION_KEYS[len(prefix):])
        out = []
        for p in sorted(base.glob(f"{rest}/*.parquet" if rest else "*.parquet")):
            key = PartitionKey.from_path(p.relative_to(self.root))
            if p.name != key.filename:  # stray/misnamed file: skip (or warn)
                continue
            if all(str(getattr(key, k)) == str(v) for k, v in filters.items()):
                out.append((key, p))
        return out
#    



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    #import sys
    #from fxt.term import hr, clear, pause
    from rich import print
    from rich.panel import Panel

    from fxt.services import get_lake    
    lake = get_lake()


    def _exists_str(p:Path) -> str:
        return "[green]exists[/]" if(p.exists()) else "[red]doesnt exist[/]"
    #

    def summary():
        source = "dukascopy"
        market = "forex"
        symbol = "EURJPY"
        interval = "TICK"
        year = 2015

        examples = [
            {"source": source},
            {"source": source, "market": market},
            {"source": source, "market": market, "symbol": symbol},
            {"source": source, "market": market, "symbol": symbol, "interval": interval},
            {"source": source, "market": market, "symbol": symbol, "interval": interval, "year": year}
        ]
        laketypes = [LakeType.RAW, LakeType.DERIVED]

        path_output = {}
        for ty in laketypes:
            omsg = ""
            for ex in examples:
                if(ty == LakeType.RAW):
                    p = lake.raw(**ex)

                    omsg += f"\n - {p} ~ {_exists_str(p)}"
                else:
                    p = lake.derived(**{**ex, "must_exist": False})

                    omsg += f"\n - {p} ~ {_exists_str(p)}"
                    
            omsg = omsg.replace("\n", "", 1)
            path_output[ty] = omsg
        #

        for k,po in path_output.items():
            print(Panel(
                po,
                title=f"[bold cyan]{k}", title_align="left"
            ))
    
    summary()

    from rich.pretty import pprint
    from fxt.services import get_settings
    pprint(get_settings().paths)
    #pprint(get_paths())


    pprint(lake.scan(LakeType.RAW, interval="TICK"))
    