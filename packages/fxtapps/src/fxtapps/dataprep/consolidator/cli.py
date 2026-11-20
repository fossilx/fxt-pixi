"""
fxtapps: Consolidator

Run from anywhere within the pixi project.

Run this via: `pixi run con --help` 

Or...

    python -m fxtapps.consolidator.cli
    -> TODO: test this: fxtapps.consolidator.cli

    python -m fxtapps.consolidator.cli
    -> TODO: test fxtapps.consolidator.cli with args

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
from dataclasses import dataclass
import re
import warnings

import click
from rich import print
from rich.panel import Panel
from InquirerPy import inquirer

#fxt
import fxt
from fxt.term import pause
from fxt.term.prompts import pick_fuzzy, pick_datetime
from fxt.dataprep.sources import BaseSource, SourceRegistry
from fxt.dataprep.downloaders import BaseDownloader, DownloaderRegistry
from fxt.dataprep.markets import BaseMarket, MarketRegistry

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
#! helpers
#!--------------------------------------------------------------------------------(80)
def _require_interactive(missing: Sequence[str]) -> None:
    """ Fail with a clear message instead of hanging when there's no terminal (cron, CI, pipes).
    """
    if(len(missing)):
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise click.UsageError(f"Missing params and not running in an interactive terminal: {missing}")
    #

def _get_downloader(id:str) -> BaseDownloader:
    """
    """
    key = id.strip()
    if key not in DownloaderRegistry:
        valid:str = ", ".join(
            [str(k) for k in DownloaderRegistry if isinstance(k, str)]
        )
        raise click.ClickException(f"Unknown downloader: '{id}'. Valid: {valid}")
    return DownloaderRegistry[key]
#

def _get_source(source:str|BaseSource) -> BaseSource:
    """
    """
    if(isinstance(source, BaseSource)):
        return source

    key = source.strip()
    if key not in SourceRegistry:
        valid:str = ", ".join(
            [str(k) for k in SourceRegistry if isinstance(k, str)]
        )
        raise click.ClickException(f"Unknown source: '{source}'. Valid: {valid}")
    return SourceRegistry[key]
#

def _get_market(market:str|BaseMarket) -> BaseMarket:
    """ Returns the corresponding market instance
    """
    if(isinstance(market, BaseMarket)):
        return market
    else:
        key = market.strip()
        if key not in MarketRegistry:
            valid:str = ", ".join(
                [str(k) for k in MarketRegistry if isinstance(k, str)]
            )
            raise click.ClickException(f"Unknown market: '{market}'. Valid: {valid}")
        return MarketRegistry[key]
#

def _find_downloaded_symbols(downloaded_root:Path=_DOWNLOADS_DIR):
    """
    """
    return [x for x in downloaded_root.iterdir() if x.is_dir()]


def _find_downloaded_intervals(symbol_dir:Path):
    """
    """
    return [x for x in symbol_dir.iterdir() if x.is_dir()]
#

def _find_subdirs(path:Path):
    """
    """
    return [x.name for x in path.iterdir() if x.is_dir()]
#


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
        - special cases that pass through:
            ALL|all
    """
    name = "year_range"
    PASS_THROUGH_VALUES:list = ["all"]  # noqa: RUF012

    def convert(self, value, param, ctx):
        #! case: already a list; e.g., passed via python code directly
        if(isinstance(value, list)):
            return value
        #! case: special case "ALL"
        if(str(value).lower() in self.PASS_THROUGH_VALUES):
            #make sure to return it as a list as the validation class will handle it's value
            return [value]

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



#!================================================================================(80)
#! check args
#!--------------------------------------------------------------------------------(80)


@dataclass
class ConsolidatorParams:
    #downloader:BaseDownloader
    source:BaseSource|None=None
    market:BaseMarket|None=None
    symbol:str|None=None
    interval:str|None=None
    years:list[int]|None=None
    #optional
    downloads_dir:Path|None=None
    output_dir:Path|None=None
    #output_manifest
#

from pydantic import BaseModel, field_validator, ConfigDict, model_validator, Field, ValidationInfo
from typing import Any, Self, cast
from class_registry import RegistryKeyError

class ParamValidator(BaseModel):
    """
    """
    model_config = ConfigDict(
        validate_assignment=True,
        validate_default=True
    )

    #! THE ORDER FIELDS ARE DEFINED MATTERS HERE
    #put values that don't need any others first:
    downloads_dir:Path|str|None = Field(default=_DOWNLOADS_DIR)
    consolidated_dir:Path|str|None = Field(default=_CONSOLIDATED_DIR)
    source:str|BaseSource|None = None
    market:str|BaseMarket|None = None

    symbol:str|None = None      #depends on: source
    interval:str|None = None    #depends on: source, symbol
    years:list[int]|None = None #depends on: source, symbol, interval
    
    #paths
    


    @field_validator("source", mode="before")
    @classmethod
    def _validate_source(cls, v:str|BaseSource|None) -> BaseSource:
        """
        """
        if(isinstance(v, BaseSource)):
            return v
        
        key:str|None = v
        if(key is None):
            key = pick_fuzzy(
                "Pick a SOURCE:",
                [k for k in SourceRegistry if isinstance(k, str) and k != "fake"]
            )

        #! if it gets here, key must be set
        try:
            return SourceRegistry[key]
        
        except RegistryKeyError: 
            valid = [k for k in SourceRegistry if isinstance(k, str)]
            raise click.ClickException(f"Invalid SOURCE provided: {v} ({type(v)}); valid: {valid}")
        #
    #
    
    @field_validator("market", mode="before")
    @classmethod
    def _validate_market(cls, v:str|BaseMarket|None) -> BaseMarket:
        """
        """
        if(isinstance(v, BaseMarket)):
            return v
        
        key:str|None = v
        if(key is None):
            key = pick_fuzzy(
                "Pick a MARKET:",
                [k for k in MarketRegistry if isinstance(k, str)]
            )

        #! if it gets here, key must be set
        try:
            return MarketRegistry[key]
        
        except RegistryKeyError: 
            valid = [k for k in MarketRegistry if isinstance(k, str)]
            raise click.ClickException(f"Invalid MARKET provided: {v} ({type(v)}); valid: {valid}")
        #
    #

    #! these depend on the ones before it!
    @field_validator("symbol", mode="before")
    @classmethod
    def _validate_symbol(cls, v:str|None, info:ValidationInfo) -> str:
        """
        """
        downloads_dir:Path = Path(info.data.get("downloads_dir")) #type: ignore
        source:BaseSource = info.data.get("source") #type: ignore
        market:BaseMarket = info.data.get("market") #type: ignore

        if(v is None): #prompt if needed
            search_dir:Path = downloads_dir / source.id / market.id
            opts = _find_subdirs(search_dir)
            if(not opts):
                raise click.ClickException("No valid symbols found in the download dir.")
            v = pick_fuzzy("Pick a SYMBOL dir:", opts)

        #issue warning if symbol is invalid
        # TODO: add a check to see if it's a valid symbol using BaseSource
        # TODO: need to add an aliases feature to the symbol lookup
        #source.get_symbol()

        #ensure the value we have for v corresponds to a real dir
        # target = Path(downloads_dir / v)
        # if(not target.exists()):
        #     raise click.ClickException(f"The specified symbol dir, {target}, doesn't exist.")

        #all good
        return v
    #

    @field_validator("interval", mode="before")
    @classmethod
    def _validate_interval(cls, v:str|None, info:ValidationInfo) -> str:
        """
        """
        downloads_dir:Path = Path(info.data.get("downloads_dir")) #type: ignore
        source:BaseSource = info.data.get("source") #type: ignore
        market:BaseMarket = info.data.get("market") #type: ignore -- will need in future
        symbol:str = ConsolidatorApp.sanitize(info.data.get("symbol")) #type: ignore

        
        # opts = _find_subdirs(search_dir)

        search_dir:Path = downloads_dir / source.id / market.id / symbol
        valid = sorted(_find_subdirs(search_dir))
        if(v is None): #prompt if needed
            
            if(not valid):
                raise click.ClickException("No valid intervals found in the specified symbol dir.")
            v = pick_fuzzy("Pick an INTERVAL dir:", valid)

        #issue warning if invalid
        v = source.get_interval(v)
        if(not v):
            raise click.ClickException(f"Invalid interval -- '{v}' -- for source: {source.id}; valid: {valid}")
           
        #ensure the value we have for v corresponds to a real dir
        # target = Path(downloads_dir / symbol / v)
        # if(not target.exists()):
        #     raise click.ClickException(f"The specified interval dir, {target}, doesn't exist.")

        #all good
        return v
    #


    @field_validator("years", mode="before")
    @classmethod
    def _validate_years(cls, v:list[int]|None, info:ValidationInfo) -> list[int]|None:
        """
        """
        ALL = "ALL"

        #! needed path elements
        downloads_dir:Path = Path(info.data.get("downloads_dir")) #type: ignore
        source:BaseSource = info.data.get("source") #type: ignore
        market:BaseMarket = info.data.get("market") #type: ignore -- will need in future
        symbol:str = ConsolidatorApp.sanitize(info.data.get("symbol")) #type: ignore
        interval:str = info.data.get("interval") #type: ignore

        search_dir:Path = downloads_dir / source.id / market.id / symbol / interval
        valid = sorted(_find_subdirs(search_dir))
        
        choices = [{"name": str(year), "value": year} for year in valid]
        choices.insert(0, {"name": ALL, "value": ALL})
        selected:list[str] = []
        if(v is None):
            selected = inquirer.checkbox( #type: ignore
                message="Select at least 1 year:",
                choices=choices,
                validate=lambda sel: len(sel) >= 1,
                invalid_message="You must select at least one year",
                long_instruction="If you select ALL, ALL will be used."
            ).execute()
        else:
            #they provided a list
            selected = [str(yr) for yr in v]
        #

        if(ALL in selected):
            selected = valid
        
        years:list[str] = sorted(selected)

        #! make sure all values in v exist
        existing_years = []
        missing_years = []
        for yr in years:
            d = search_dir / str(yr)
            if(d.is_dir()):
                existing_years.append(yr)
            else:
                missing_years.append(yr)
        if(not len(existing_years)):
            raise click.ClickException("No valid years provided.")
        elif(len(missing_years)):
            warnings.warn(f"Some of the specified years don't exist: {missing_years}")
        
        return existing_years
    #
#-

#

def check_args(
        ctx:click.Context,
        symbol:str,
        years:list[int]|None,

        source:str|None, #|BaseSource,
        market:str|None,#|BaseMarket,
        interval:str|None,
        downloads_dir:Path,
        output_dir:Path
    ):
    """ Checks provided args and prompts for the missing ones.
    """
    rtn = ConsolidatorParams()

    if(downloads_dir is None):
        downloads_dir = _DOWNLOADS_DIR
    if(output_dir is None):
        output_dir = _CONSOLIDATED_DIR
        #




    #! will eventually be needed to determine the dir to search
    if(source is None):
        source = pick_fuzzy(
            "Pick a SOURCE:",
            [k for k in SourceRegistry if isinstance(k, str)]
        )
    rtn.source = _get_source(source)

    #----------------------------------------(40)

    #! will eventually be needed to determine the dir to search
    # _market:BaseMarket
    # if(market is None):
    #     #try to get it from the source+symbol
    #     mkt = _source.which_market(symbol=symbol)
    #     if(mkt is None):
    #         raise ValueError("The provided symbol failed to return a valid market!")
    #     #else:
    #     _market = _get_market(mkt)
    # else:
    #     _market = _get_market(market)
    # #

    #----------------------------------------(40)

    #~ check: symbol
    
    if(symbol is None):
        #! look for existing symbol dirs
        symbol = pick_fuzzy("Pick a SYMBOL dir:", _find_subdirs(downloads_dir))
        if(not len(symbol)):
            raise RuntimeError("No valid symbol directories found.")
    else:
        _symbol = ConsolidatorApp.sanitize(symbol)
        target = Path(downloads_dir / symbol)
        if(not target.exists()):
            raise RuntimeError(f"The specified symbol dir, {target}, doesn't exist.")
    rtn.symbol = symbol
    #

    #~ check: interval
    if(interval is None):
        #! look for existing interval dirs
        interval = pick_fuzzy("Pick an INTERVAL:", _find_subdirs(downloads_dir / symbol))
        if(not len(interval)):
            raise RuntimeError("No valid interval directories found.")
    else:
        #check to see if the target dir exists
        target = Path(downloads_dir / symbol / interval)
        if(not target.exists()):
            raise RuntimeError(f"The specified interval dir, {target}, doesn't exist.")
    rtn.interval = interval

    #----------------------------------------(40)
    
    if(years is None):
        years_pattern = re.compile(r"^\d{4}(?:\s*-\s*\d{4}|\s*\.\.\s*\d{4}|(?:\s*,\s*\d{4})*)?$")
        years_prompt = inquirer.text(  #type: ignore
            message="Enter the target years:",
            validate=lambda val: bool(re.match(years_pattern, val)),
            invalid_message="Invalid format! Please enter a valid email address.",
        ).execute()

        years = YEAR_RANGE.convert(years_prompt, None, None)
    #
    rtn.years = years

    #----------------------------------------(40)

    rtn.downloads_dir = downloads_dir
    rtn.output_dir = output_dir

    return rtn




    # class ConsolidatorParams:
    # #downloader:BaseDownloader
    # source:BaseDownloader|None #not sure wtf i want yet
    # market:BaseMarket|None
    # symbol:str
    # interval:str
    # years:list[int]
    # #optional
    # downloads_dir:Path
    # output_dir:Path
    #output_manifest
#



#!================================================================================(80)
#! cli
#!--------------------------------------------------------------------------------(80)
from pprint import pprint, pformat
from rich.panel import Panel



#~ click handler
@click.command()
@click.option("--source",   "-b", default=None, help="Data broker/source")
@click.option("--market",   "-m", default=None)
@click.option("--symbol",   "-i", default=None, help="Ticker symbol for the target instrument, e.g. GBP/USD.")
@click.option("--interval", "-t", default=None, help="Time interval, e.g. TICK, 1MIN.")
@click.option("--years",    "-y", default=None, type=YEAR_RANGE, help="Accepts a single year: 2024, a range: 2020-2024 or 2020..2024 (i think), or a list: 2020,2023,2024, or: ALL")
#@click.option("--symbol",   "-i", default=None, help="Ticker symbol for the target instrument, e.g. GBP/USD. Prompted if omitted.")

#@click.option("--market",   "-m", default=None, show_default=True)

@click.option(
    "--dl",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
    help="Root input/downloads directory"
)
@click.option(
    "--con", # "-o", #required=True, 
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Root dir for the consolidated output. Generated files are then put in a symbol subdir."
)
@click.pass_context
def cli(ctx:click.Context, source, market, symbol, interval, years, dl, con):
    """
    """
    args = {
        "source": source,
        "market": market,
        "symbol": symbol,
        "interval": interval,
        "years": years,
    }
    if(dl is not None):
        args.update(downloads_dir=dl)
    if(con is not None):
        args.update(consolidated_dir=con)

    print(Panel(
        pformat(args, indent=4),
        title="[cyan bold]params from CLICK[/]", title_align="left"
    ))

    params = ParamValidator(**args)
    print(Panel(
        #pformat(ctx.params, indent=4),
        params.model_dump_json(indent=4),
        #pformat(params, indent=4),
        title="Resulting [cyan bold]ParamValidator[/]", title_align="left"
    ))

    #pause()
    #sys.exit()

    
    #symbol = "EUR/JPY"
    #years = list(range(2013,2020))
    try:
        app = ConsolidatorApp(
            source=params.source,     #type: ignore
            market=params.market,   #type: ignore
            symbol=params.symbol,   #type: ignore
            interval=params.interval, #type: ignore
            years=params.years, #type: ignore
            downloads_dir=params.downloads_dir, #type: ignore
            consolidated_dir=params.consolidated_dir   #type: ignore
        )
        pause()
        app.run(dry=False)

    except KeyboardInterrupt:
        print("[orchid2]KeyboardInterrupt[/]: Operation canceled.")

#




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if __name__ == "__main__":
    cli()

