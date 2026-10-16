#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#=================================================================================(80)
#   fxt.download.storage ~ one parquet file per UTC day + a tiny manifest
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

#!================================================================================(80)
#! settings
#!--------------------------------------------------------------------------------(80)
from fxt import get_env





#MANIFEST_NAME = "_manifest.jsonl"
#META_KEY = METADATA_KEY #moved to schemas

MANIFEST_NAME = get_env('DOWNLOADER_MANIFEST')
META_KEY = get_env('PARQUET_METADATA_KEY')

#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def _json_default(obj):
    """ JSON fallback for values like datetimes in the downloader's meta dict.
    """
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)
#

def _safe(name: str) -> str:
    """ Make a symbol/interval safe as a directory name ("EUR/USD" -> "EUR_USD").
    """
    name = name.replace("/", "")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return name
#


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class DayStore:
    """ Layout:  <root>/<SYMBOL>/<INTERVAL>/YYYY-MM-DD.parquet

        The manifest (JSONL, append-only) only exists to remember days that were
        downloaded but had no data (weekends/holidays), so they aren't re-requested.
        Days with data are "done" simply because their parquet file exists.

        Not thread-safe by design: call `record` from one thread (the engine does).
    """
    #~======================================================================(70)
    #~ re: meta/utils
    #~----------------------------------------------------------------------(70)
    @classmethod
    def ReadMeta(cls, file:Path) -> dict|None:
        """ Shows how to read the data for a parquet file created using this 
            downloader.
        """
        raw = pl.read_parquet_metadata(file).get(META_KEY)
        return json.loads(raw) if raw else None
    #

    def read_meta(self, day: date) -> dict | None:
        """ Read back the embedded meta for a day (None if absent). Only reads the
            parquet footer, not the data.
        """
        return self.ReadMeta(self.path(day))
        #raw = pl.read_parquet_metadata(self.path(day)).get(META_KEY)
        #return json.loads(raw) if raw else None
    #

    #~======================================================================(70)
    #~ main
    #~----------------------------------------------------------------------(70)
    def __init__(self, root: str | Path, symbol: str, interval: str):
        self.symbol = symbol
        self.dir = Path(root) / _safe(symbol) / _safe(interval)
        #self.dir.mkdir(parents=True, exist_ok=True)
        
        #self._manifest = self.dir / MANIFEST_NAME
        #self._status: dict[str, str] = {} #self._load_manifest()
    #

    #~======================================================================(70)
    #~ re: parquet file
    #~----------------------------------------------------------------------(70)
    def path(self, day: date) -> Path:
        """ Determines the entire path of the target file.
        """
        symbol = _safe(self.symbol)
        final = self.dir / f"{day:%Y}/{day:%m}/{symbol}-{day:%Y-%m-%d}.parquet"

        return final
    #
    
    def is_done(self, day: date) -> bool:
        """ Used to determine if we should download or not.
        """
        return self.path(day).exists() or self._load_manifest(day).get(day.isoformat()) == "empty"
    #

    def write(self, day: date, df: pl.DataFrame, meta: dict | None = None) -> Path:
        """ Atomic: write to a temp file, then rename over the final name.
            The downloader's meta dict is embedded in the file as JSON under META_KEY.
        """
        final = self.path(day)
        parent = final.parent
        parent.mkdir(parents=True, exist_ok=True)

        tmp = final.with_suffix(".parquet.tmp")
        metadata = {META_KEY: json.dumps(meta, default=_json_default)} if meta else None
        df.write_parquet(tmp, compression="zstd", metadata=metadata)
        os.replace(tmp, final)
        return final
    #


    #~======================================================================(70)
    #~ re: manifest
    #~----------------------------------------------------------------------(70)
    def _load_manifest(self, day:date) -> dict[str, str]:
        """ Called in the very beginning
        """
        status: dict[str, str] = {}

        manifest = self.manifest_path(day)
        #if not self._manifest.exists():
        if not manifest.exists():
            return status
        #with self._manifest.open("r", encoding="utf-8") as f:
        with manifest.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    status[entry["day"]] = entry["status"]
                except (json.JSONDecodeError, KeyError):
                    continue  # e.g. a truncated last line after a crash
        return status
    #

    def manifest_path(self, day:date) -> Path:
        """
        """
        return self.path(day).parent / MANIFEST_NAME
    #
    def record(self, day: date, status: str, rows: int = 0) -> None:
        """ Append a manifest line for a completed day (status: success | empty).
        """
        #self._status[day.isoformat()] = status

        entry = {
            "day": day.isoformat(),
            "status": status,
            "rows": rows,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        #with self._manifest.open("a", encoding="utf-8") as f:
        #manifest = self.manifest_path(day)

        #get location of manifest
        manifest = self.manifest_path(day)
        #make sure the dir exists
        parent = manifest.parent
        parent.mkdir(parents=True, exist_ok=True)

        #write new entry
        with manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    #


    

    
#