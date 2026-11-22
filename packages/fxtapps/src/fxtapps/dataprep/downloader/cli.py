"""
fxtapps: Downloader

Run from anywhere within the pixi project.

    python -m fxtapps.downloader.cli
        -> tested; working

    python -m fxtapps.downloader.cli
    -> TODO: test command line args for downloader cli

    
Try pixi task next time:

    pixi run dl
    -> TODO: test pixi task command for downloader cli
    pixi run dl -s dukascopy --symbol "GBP/USD" --interval 1min
    -> TODO: test pixi task command with custom args for downloader cli

    
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
from pprint import pformat

import click
from rich import print

from rich.panel import Panel
from InquirerPy import inquirer

#fxt
from fxt.term import pause
from fxt.term.prompts import pick_fuzzy, pick_datetime
from fxt.dataprep.sources import BaseSource, SourceRegistry
from fxt.dataprep.downloaders import BaseDownloader, DownloaderRegistry
from fxt.dataprep.markets import BaseMarket, MarketRegistry
 
#apps->shared

#apps->local
from .settings import get_settings
from .dl import DailyDownloaderApp

#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)
from . import logger
import logging
logger.setLevel(logging.WARNING)


#env constants
_DOWNLOADS_DIR:Path = Path(str(get_settings("DOWNLOADS_DIR")))



#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def _require_interactive(param: str) -> None:
    """ Fail with a clear message instead of hanging when there's no 
        terminal (cron, CI, pipes).

        from an LLM to ensure we have an interactive prompt

        Not sure if I'm going to keep it implemented in quite this fashion
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise click.UsageError(f"Missing --{param} (and not running in an interactive terminal).")
#

def _get_downloader(id:str) -> BaseDownloader:
    """
    """
    key = id.strip()
    if key not in DownloaderRegistry:
        valid:str = ", ".join(
            [str(k) for k in DownloaderRegistry if isinstance(k, str)]
        )
        raise click.ClickException(f"Unknown downloader '{id}'. Valid downloaders: {valid}")
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




#!================================================================================(80)
#! check args
#!--------------------------------------------------------------------------------(80)
from pydantic import BaseModel, field_validator, ConfigDict, model_validator, Field, ValidationInfo
from typing import Self, cast
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
    downloader:str|BaseDownloader|None = None 
    market:str|BaseMarket|None = None
    start:datetime|None = None
    end:datetime|None = None

    symbol:str|None = None      #depends on: source (aka downloader)
    interval:str|None = None    #depends on: source, symbol
    

    
    #~======================================================================(70)
    #~ independent validators
    #~----------------------------------------------------------------------(70)
    @field_validator("downloader", mode="before")
    @classmethod
    def _validate_downloader(cls, v:str|BaseDownloader|None) -> BaseDownloader:
        """
        """
        if(isinstance(v, BaseDownloader)):
            return v
        
        key:str|None = v
        if(key is None):
            key = pick_fuzzy(
                "Pick a DOWNLOADER:",
                [k for k in DownloaderRegistry if isinstance(k, str)]
            )

        #! if it gets here, key must be set
        try:
            return DownloaderRegistry[key]
        
        except RegistryKeyError: 
            valid = [k for k in DownloaderRegistry if isinstance(k, str)]
            raise click.ClickException(f"Invalid DOWNLOADER provided: {v} ({type(v)}); valid: {valid}")
        #
    #

    @field_validator("market", mode="before") #! should depend on source..maybe?
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

    @field_validator("start", "end", mode="before")
    @classmethod
    def _validate_dtime(cls, v:str|datetime|None, info:ValidationInfo) -> datetime:
        """
        """
        if(v is None):
            v = pick_datetime(f"Pick a dtime for: {info.field_name}")
        elif(isinstance(v, str)):
            logger.debug(f"string sent to _validate_dtime() -- this prob shouldnt happen: {v}")
            v = datetime.fromisoformat(v)
        
        return v
    #

    #~======================================================================(70)
    #~ dependent validators
    #~----------------------------------------------------------------------(70)
    @field_validator("symbol", mode="before")
    @classmethod
    def _validate_symbol(cls, v:str|None, info:ValidationInfo) -> str:
        """
        """
        downloader:BaseDownloader = info.data.get("downloader") #type: ignore
        
        if(v is None): #prompt if needed
            choices = downloader.SYMBOLS
            v = pick_fuzzy("Pick a SYMBOL", choices)

        try:
            symbol = downloader.get_symbol(v)
        except Exception as e:
            raise click.ClickException(str(e)) from e

        return symbol
    #

    @field_validator("interval", mode="before")
    @classmethod
    def _validate_interval(cls, v:str|None, info:ValidationInfo) -> str:
        """
        """
        downloader:BaseDownloader = info.data.get("downloader") #type: ignore

        if(v is None): #prompt if needed
            v = pick_fuzzy("Pick an INTERVAL:", list(downloader.INTERVALS))
        
        try:
            interval = downloader.get_interval(v)
        except Exception as e:
            #raise click.ClickException(f"Invalid interval -- '{v}' -- for source: {downloader.id}; valid: {valid}")
            raise click.ClickException(str(e)) from e

        return interval
    #



    #~======================================================================(70)
    #~ model validators
    #~----------------------------------------------------------------------(70)
    @model_validator(mode="after")
    def _validate_dates(self) -> Self:
        """
        """
        if(self.start is not None and self.end is not None):
            #make sure start < end
            if(self.start == self.end):
                raise click.ClickException("start and end must be different values")
            if(self.start > self.end): #swap them
                logger.debug("start > end; swapping them")
                self.start, self.end = self.end, self.start

        return self
    #
#





#!================================================================================(80)
#! cli
#!--------------------------------------------------------------------------------(80)
@click.command()
@click.option("--source",     "-b", default=None, help="Data broker/source. Prompted if omitted.")
@click.option("--market",     "-m", default=None)
@click.option("--symbol",     "-i", default=None,
    multiple=True,
    help="Ticker symbol for the target instrument, e.g. GBP/USD. Prompted if omitted.")
@click.option("--interval",   "-t", default=None, help="Time interval, e.g. TICK, 1MIN. Prompted if omitted.")
@click.option("--start",      "-s", default=None, help="End time, as a valid datetime string")
@click.option("--end",        "-e", default=None, help="Start time, as a valid datetime string")
@click.option(
    "--dl",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
    help="Root input/downloads directory"
)
@click.option("--auto/--no-auto", default=False)
@click.option("--dry/--no-dry", default=False)
def cli(
        source,
        market,
        symbol, #is either a tuple/list
        interval,
        start:datetime|None,
        end:datetime|None,
        dl:str|None,
        auto:bool,
        dry:bool
    ):
    """ Downloads daily files using a downloader specific to the specified broker/source.
    """
    
    args = {
        "downloader": source,
        "market": market,
        #"symbol": symbol,
        "interval": interval,
        "start": start,
        "end": end,
        "auto": auto
    }
    if(dl is not None):
        args.update(downloads_dir=dl)
    #! make sure symbol is the correct type
    if(not len(symbol)):
        symbol = [None]

    print(Panel(
        f"symbols: {symbol}"
        "\n"
        f"{pformat(args, indent=4)}",
        title="[cyan bold]params from CLICK[/]", title_align="left"
    ))
    
    from fxt.core.geo import home_geo
    from rich.pretty import Pretty
    print(Panel(
            Pretty(home_geo()),
            title="[cyan bold]networking[/]", title_align="left"
        ))

    if(not auto): pause()

    #------------------------------------------------------------(60)

    try:
        # print(
        #     "**** cli(): [cyan bold]FINAL PARAMS[/]"
        #     f"\n - [green]source ID[/]:  {params.downloader.id}"
        #     f"\n - [green]downloader[/]: {params.downloader}"
        #     f"\n - [green]symbol[/]:     {params.symbol}"
        #     f"\n - [green]interval[/]:   {params.interval}"
        #     f"\n - [green]start[/]:      {params.start}"
        #     f"\n - [green]end[/]:        {params.end}"
        # )
        # pause()
        for sym in symbol:
            #create params
            sym_args = dict(**args)
            sym_args.update(symbol=sym)

            params = ParamValidator(**sym_args)
            print(Panel(
                #pformat(ctx.params, indent=4),
                params.model_dump_json(indent=4),
                #pformat(params, indent=4),
                title="Resulting [cyan bold]ParamValidator[/]", title_align="left"
            ))
            app = DailyDownloaderApp(
                downloader=params.downloader,   #type: ignore
                market=params.market,           #type: ignore
                symbol=params.symbol,           #type: ignore
                interval=params.interval,       #type: ignore
                start=params.start,             #type: ignore
                end=params.end,                 #type: ignore
                root=params.downloads_dir       #type: ignore
            )
            if(not auto): pause()

            app.run(auto=auto, dry=dry)
    #

    except KeyboardInterrupt:
        print("[orchid2]KeyboardInterrupt[/]: Operation canceled.")


    #go(**args)
#


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if __name__ == "__main__":
    cli()

    #TODO: add something to support multiple symbols?

    #! to disable the pauses, use --auto
    #pixi run dl -b dukascopy -m forex -t TICK -s 2013-01-01 -e 2025-01-01 -i AUD/JPY --auto

    #! you can now set multiple symbols with repeated uses of --symbol, like so:
    #pixi run dl -b dukascopy -m forex -t TICK -s 2025-01-01 -e 2025-01-02 --symbol GBP/JPY --symbol EUR/USD

    #! yey
