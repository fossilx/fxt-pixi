#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#=================================================================================(80)
#   STEP 2 ~ combine daily parquet files into one file per year
#
#   python consolidate.py EURUSD
#
#   reads:   <root>/EURUSD/TICK/2024/01/EURUSD-2024-01-01.parquet  (and so on)
#   writes:  <out>/EURUSD/TICK/EURUSD-2024.parquet
#=================================================================================(80)
from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from loguru import logger
from rich import print

from fxt.download.storage import META_KEY #should now be "fxt"

#old keys to search (uses first it finds)
DOWNLOADED_META_KEYS = ["fxt_meta", META_KEY] 
#use new key:
CONSOLIDATED_META_KEY = META_KEY #"fxt"
DEFAULT_ROOT = Path("downloads")
DEFAULT_OUT = Path("datalake-output")


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def find_daily_files(interval_dir: Path, symbol: str) -> dict[int, list[Path]]:
    """ {year: [daily files, oldest first]}. Only files named
        `<symbol>-YYYY-MM-DD.parquet` are picked up, so manifests and stray
        temp files are ignored.
    """
    pattern = re.compile(rf"^{re.escape(symbol)}-(\d{{4}})-(\d{{2}})-(\d{{2}})\.parquet$")
    found: dict[int, list[tuple[str, Path]]] = defaultdict(list)

    for path in interval_dir.glob("*/*/*.parquet"):
        m = pattern.match(path.name)
        if m:
            found[int(m[1])].append((f"{m[1]}-{m[2]}-{m[3]}", path))
    return {year: [p for _, p in sorted(items)] for year, items in sorted(found.items())}
#
def _row_count(source) -> int:
    """ Cheap: answered from the parquet footers, no data is loaded.
    """
    return pl.scan_parquet(source).select(pl.len()).collect().item()
#


#!================================================================================(80)
#! meta helpers
#!--------------------------------------------------------------------------------(80)
def read_meta(path: Path) -> dict:
    """ The downloader's meta dict embedded in a daily file ({} if there is none).

        It needs to iterate through the possible keys and use the first one. This
        is cuz i changed the key and don't want to redownload everything yet.
    """
    metadict = pl.read_parquet_metadata(path)
    #DOWNLOADED_META_KEYS

    #find the first key in DOWNLOADED_META_KEYS that exists in metadict
    #returns None if not found
    first_key = next((k for k in DOWNLOADED_META_KEYS if k in metadict), None)
    
    #get the corresponding value (provided we found a key)
    raw = metadict.get(first_key) if first_key else None

    #parse it as json (if we found it); else return {}
    return json.loads(raw) if raw else {}

    #raw = pl.read_parquet_metadata(path).get(DOWNLOADED_META_KEY)
    #return json.loads(raw) if raw else {}
#

def filter_meta(meta:dict, keys_to_keep:list) -> dict:
    """ Returns a filtered version of the meta for use in the consolidated ouput.
        Mostly I just want to remove certain values.
    """
    return {k: meta[k] for k in keys_to_keep if k in meta}
#



#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
META_KEYS_TO_KEEP = ["symbol", "interval"]

def consolidated_meta(symbol:str, files: list[Path], nrows:int) -> dict:
    """ Takes in the list of files and returns the meta to use for the combined 
        parquet file.

        It starts with the meta from the first file, and it only keeps the values
        that apply to the combined file.
    """
    meta = read_meta(files[0])
    meta = filter_meta(meta, META_KEYS_TO_KEEP)

    #! ensure that it has a value for symbol
    meta.setdefault("symbol", symbol)

    #! add consolidated info
    consolidated = {
        "nfiles": len(files),
        "nrows": nrows,
        "start": files[0].stem[-10:],
        "end": files[-1].stem[-10:],
        "consolidated-at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    meta.update(consolidated)

    return meta
#


def consolidate_year(
    symbol: str, year: int, files: list[Path], out_dir: Path, force: bool = False
) -> str:
    """ Combine one year's daily files into `<out_dir>/<symbol>-<year>.parquet`.
        Returns "written" or "skipped" (output already newer than every input).
    """
    out = out_dir / f"{symbol}-{year}.parquet"
    if out.exists() and not force:
        if out.stat().st_mtime >= max(f.stat().st_mtime for f in files):
            logger.info("{} is up to date, skipping", out.name)
            return "skipped"

    rows = _row_count(files)

    #------------------------------------------------------------(60)

    #! META DATA
    #meta comes from this year's first daily file; make sure it names the symbol
    #meta = read_meta(files[0])
    meta = consolidated_meta(symbol, files, nrows=rows)
    
    print("# [bold white]{out}[/]")
    print(f"  - [cyan]symbol[/]: {symbol}")
    print(f"  - [cyan]year[/]:   {year}")
    print(f"  - [cyan]nfiles[/]: {len(files)}")
    print(f"  - [cyan]nrows[/]:  {rows}")
    print( "  - consolidated meta:")
    for k,v in meta.items():
        print(f"    * [cyan]{k}[/]: {v}")

    from getch import getch

    print("Pause....pajama time")
    getch()
    import sys
    sys.exit()
    

    #------------------------------------------------------------(60)

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")
    try:
        #lazy + sink: streams to disk instead of loading the whole year into memory.
        #files are in date order, so the rows stay in time order.
        pl.scan_parquet(files).sink_parquet(
            tmp, compression="zstd", metadata={CONSOLIDATED_META_KEY: json.dumps(meta)}
        )
        written = _row_count(tmp)
        if written != rows:
            raise RuntimeError(f"row count mismatch for {out.name}: expected {rows:,}, wrote {written:,}")
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)

    logger.info("{}: {} files, {:,} rows", out.name, len(files), rows)
    return "written"
#


#!================================================================================(80)
#! entry point
#!--------------------------------------------------------------------------------(80)
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="fxt-consolidate",
        description="Combine daily parquet files into one parquet file per year.",
    )
    p.add_argument("symbol", help="symbol directory name, without the slash, e.g. EURUSD")
    p.add_argument("-i", "--interval", help="interval directory name, e.g. TICK (default: every interval found)")
    p.add_argument("-r", "--root", type=Path, default=DEFAULT_ROOT, help=f"download root (default: {DEFAULT_ROOT})")
    p.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT, help=f"output root (default: {DEFAULT_OUT})")
    p.add_argument("--force", action="store_true", help="rebuild even if the yearly file looks up to date")
    args = p.parse_args(argv)

    symbol_dir = args.root / args.symbol
    if not symbol_dir.is_dir():
        p.error(f"no such symbol directory: {symbol_dir}")

    if args.interval:
        interval_dirs = [symbol_dir / args.interval]
        if not interval_dirs[0].is_dir():
            #check to see if the cap variant exists
            upr = str(args.interval).upper()
            caps_dir = symbol_dir / upr
            if(caps_dir.is_dir()):
                p.error(f"no such interval directory: {interval_dirs[0]}, did you mean: {upr} ???")
            else:
                p.error(f"no such interval directory: {interval_dirs[0]}")
    else:
        interval_dirs = sorted(d for d in symbol_dir.iterdir() if d.is_dir())

    failures = 0
    for interval_dir in interval_dirs:
        years = find_daily_files(interval_dir, args.symbol)
        if not years:
            logger.warning("No daily files found in {}", interval_dir)
            continue

        out_dir = args.out / args.symbol / interval_dir.name
        for year, files in years.items():
            try:
                consolidate_year(args.symbol, year, files, out_dir, force=args.force)
            except Exception as e:  # keep going with the other years
                failures += 1
                logger.error("{} {} failed: {}", interval_dir.name, year, e)

    return 1 if failures else 0
#

#!================================================================================(80)
#! gogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from datetime import datetime
    from rich import print

    args = [
        "EURUSD",
        #"-i", "tick" #works
    ]
    
    raise SystemExit(main(args))