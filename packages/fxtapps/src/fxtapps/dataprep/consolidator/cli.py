"""
fxtapps: Consolidator

Run from anywhere within the pixi project.

    python -m fxtapps.consolidator.cli
    -> TODO: test this: fxtapps.consolidator.cli

    python -m fxtapps.consolidator.cli
    -> TODO: test fxtapps.consolidator.cli with args

    
Try pixi task next time:

    -> TODO: create consolidator pixi task and test it
    
"""
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations
import sys
from datetime import datetime
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import click
from rich import print


#fxt
from fxt.term import pause
from fxt.term.prompts import pick_fuzzy, pick_datetime
from fxt.data.sources import BaseSource 
from fxt.data.downloaders import BaseDownloader, DownloaderRegistry

#apps->shared
#from fxtapps.settings import get_settings


#apps->local
from .settings import get_settings
from .con import ConsolidatorApp




#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)
from . import logger
import logging
logger.setLevel(logging.WARNING)

#env constants
_DOWNLOADS_DIR:Path = Path(str(get_settings("DOWNLOADS_DIR")))
_DOWNLOADS_MANIFEST:str = str(get_settings("DOWNLOADS_MANIFEST"))
_CONSOLIDATED_DIR:Path = Path(str(get_settings("CONSOLIDATED_DIR")))
_CONSOLIDATED_MANIFEST:str = str(get_settings("CONSOLIDATED_MANIFEST"))


#!================================================================================(80)
#! cli
#!--------------------------------------------------------------------------------(80)
#~ custom year range type
class YearRangeType(click.ParamType):
    """ Represents a range of years as a click param. 
        Supports
        - single years:
            2024
        - range of years:
            2020-2024 
            2020..2024
        - list of years:
            2020,2021,2022,2023
        
    """
    name = "year_range"

    def convert(self, value, param, ctx):
        # If it's already a list (e.g., passed via python code directly)
        if isinstance(value, list):
            return value

        years = set()
        # Support splitting by comma to allow multiple ranges or single years (e.g., "2018,2020-2022")
        parts = [p.strip() for p in str(value).split(",") if p.strip()]

        for part in parts:
            # Handle range syntax (supports both '-' and '..')
            if "-" in part or ".." in part:
                sep = ".." if ".." in part else "-"
                try:
                    start_str, end_str = part.split(sep, 1)
                    start, end = int(start_str.strip()), int(end_str.strip())
                    if start > end:
                        self.fail(
                            f"Invalid range '{part}': start year ({start}) cannot be after end year ({end}).",
                            param,
                            ctx,
                        )
                    years.update(range(start, end + 1))
                except ValueError:
                    self.fail(
                        f"Invalid range format '{part}'. Expected format YYYY-YYYY or YYYY..YYYY.",
                        param,
                        ctx,
                    )
            else:
                # Handle single year
                try:
                    year = int(part)
                    years.add(year)
                except ValueError:
                    self.fail(
                        f"'{part}' is not a valid 4-digit year.", param, ctx
                    )

        if not years:
            self.fail("No valid years provided.", param, ctx)

        #return sorted(list(years))
        return sorted(years)
#-
YEAR_RANGE = YearRangeType()


#~ click handler
@click.command()
@click.argument("symbol")
#@click.option("--source",     "-b", default=None, help="Data broker/source. Prompted if omitted.")
@click.option(
    "--years", "-y",
    type=YEAR_RANGE,
    help="Accepts a single year: 2024, a range: 2020-2024 or 2020..2024 (i think), or a list: 2020,2023,2024"
)
@click.option("--interval", default="TICK", show_default=True)
@click.option(
    "--dl-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=_DOWNLOADS_DIR, show_default=True,
    help="Root downloads directory."
)
@click.option(
    "--con-dir", # "-o", #required=True, 
    type=click.Path(path_type=Path, file_okay=False),
    default=_CONSOLIDATED_DIR, show_default=True,
    help="Root dir for the consolidated output. Generated files are then put in a symbol subdir."
)
def cli(
    symbol: str,
    years: list[int],
    interval: str,
    source: Path, #has default
    output: Path, #has default
):
    """ Consolidates/merges daily parquet files for a given SYMBOL (filename-safe, e.g. EURJPY) 
        into yearly files (with matching manifests).

        - For each `(symbol, interval, year)`, this tool combines the parquet files into yearly
          parquet files.
        - It assumes the data has been stored in daily files. 
        - These yearly parquet files are the starting point for the datalake.
        - All parquet files are written using `fxt.data.ParquetStore` and a custom meta system
          where each type of parquet has a pydantic model defined for its contents.

        ---

        As of now, it searches for manifests files and uses those to determine which files should
        be combined into the yearly file. There should be 1 manifest in each monthly directory.
        
        Using those manifests, it combines all manifests in a given year's dir into one big manifest,
        and uses that to merge the parquets into one big one. This also creates an updated, yearly
        manifest file detailing the origins of the data.

        Notes:
        - I may make the download dir setup more flexible, but for now, that info is stored 
          in the .env file. Unless I see a need to add more flexibility as to where downloaded
          and consolidated files go, I'm leaving it as is.
        - 
    """
    #symbol = "EURUSD"
    #years = [2023,2024]

    app = ConsolidatorApp(
        symbol=symbol,
        interval=interval,
        years=years,
        downloads_dir=source,
        output_dir=output
    )

    app.run(dry=False)
#




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if __name__ == "__main__":
    cli()

