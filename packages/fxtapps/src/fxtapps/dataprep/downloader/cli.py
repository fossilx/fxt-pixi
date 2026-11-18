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
#from dataclasses import dataclass

# @dataclass
# class DownloaderParams:
#     downloader:BaseDownloader
#     symbol:str
#     interval:str
#     start:datetime
#     end:datetime
# #


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

    symbol:str|None = None      #depends on: source
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
            v = pick_fuzzy("Pick a SYMBOL", downloader.SYMBOLS)

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
# def check_args(
#         source:str|None,
#         symbol:str|None,
#         interval:str|None,
#         start:datetime|None,
#         end:datetime|None,
#         #output:str|None
#     ) -> DownloaderParams: #-> dict[str,Any]:
#     """ Get's the required args as needed. Skips those that are already provided.
#     """
#     #~ ---- start with source/downloader cuz symbol/interval depend on it
#     if source is None:
#         #if len(SOURCES) == 1:
#         #    source = DEFAULT_SOURCE  # nothing to choose from yet
#         #else:
#         _require_interactive("source")
#         source = pick_fuzzy(
#             "Pick a SOURCE:",
#             [k for k in DownloaderRegistry if isinstance(k, str)]
#         )
#     downloader = _get_downloader(source)

#     #----------------------------------------(40)

#     #~ ---- symbol 
#     if symbol is None:
#         _require_interactive("symbol")
#         symbol = pick_fuzzy("Pick a SYMBOL", downloader.SYMBOLS)
#     else:
#         try:
#             # case-insensitive; error includes "did you mean"
#             symbol = downloader.get_symbol(symbol)
#         except ValueError as e:
#             raise click.ClickException(str(e)) from e

#     #~ ---- interval 
#     if interval is None:
#         _require_interactive("interval")
#         interval = pick_fuzzy("Pick an INTERVAL:", list(downloader.INTERVALS))
#     else:
#         try:
#             interval = downloader.get_interval(interval)
#         except ValueError as e:
#             raise click.ClickException(str(e)) from e

#     #----------------------------------------(40)

#     #~ ---- start/end
#     if(start is None):
#         start = pick_datetime("Pick a START dtime:")
#     if(end is None):
#         end = pick_datetime("Pick an END dtime:")

#     #make sure start < end
#     if(start == end):
#         raise ValueError("start and end must be different values")
#     if(start > end): #swap them
#         logger.debug("start > end; swapping them")
#         start, end = end, start

#     #----------------------------------------(40)

#     # #~ ---- output
#     # if(output is None):
#     #     raise ValueError("You must specify a directory for output.")
#     # else:
#     #     output_dir = Path(output)
#     #     if(not output_dir.is_dir()):
#     #         raise ValueError("You must specify an existing directory for output.")

#     #----------------------------------------(40)

#     #! return resulting params
#     #click.echo(f"\nsource={downloader.id}  symbol={symbol}  interval={interval}")
#     # return {
#     #     "downloader": downloader,
#     #     "symbol": symbol,
#     #     "interval": interval,
#     #     "start": start,
#     #     "end": end,
#     #     #"output": output_dir
#     # }
#     return DownloaderParams(
#         downloader=downloader,
#         symbol=symbol,
#         interval=interval,
#         start=start,
#         end=end
#     )
# #

@click.command()
@click.option("--source",     "-b", default=None, help="Data broker/source. Prompted if omitted.")
@click.option("--market",     "-m", default=None)
@click.option("--symbol",     "-i", default=None, help="Ticker symbol for the target instrument, e.g. GBP/USD. Prompted if omitted.")
@click.option("--interval",   "-t", default=None, help="Time interval, e.g. TICK, 1MIN. Prompted if omitted.")
@click.option("--start",      "-s", default=None, help="End time, as a valid datetime string")
@click.option("--end",        "-e", default=None, help="Start time, as a valid datetime string")

@click.option(
    "--dl",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
    help="Root input/downloads directory"
)
def cli(
        source, 
        market,
        symbol,
        interval,
        start:datetime|None,
        end:datetime|None,
        dl:str|None
    ):
    """ Downloads daily files using a downloader specific to the specified broker/source.
    """
    args = {
        "downloader": source,
        "market": market,
        "symbol": symbol,
        "interval": interval,
        "start": start,
        "end": end
    }
    if(dl is not None):
        args.update(downloads_dir=dl)
    
    print(Panel(
        pformat(args, indent=4),
        title="[cyan bold]params from CLICK[/]", title_align="left"
    ))

    pause()


    params = ParamValidator(**args)

    print(Panel(
        #pformat(ctx.params, indent=4),
        params.model_dump_json(indent=4),
        #pformat(params, indent=4),
        title="Resulting [cyan bold]ParamValidator[/]", title_align="left"
    ))

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

        app = DailyDownloaderApp(
            downloader=params.downloader,   #type: ignore
            market=params.market,           #type: ignore
            symbol=params.symbol,           #type: ignore
            interval=params.interval,       #type: ignore
            start=params.start,             #type: ignore
            end=params.end,                 #type: ignore
            root=params.downloads_dir       #type: ignore
        )
        pause()
        app.run(dry=False)
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
    #start = pick_datetime("Start", default=datetime.now().strftime("%Y-%m-%d "))

    #print(f"selected datetime: {start}")