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

import click
from rich import print


#fxt
from fxt.term import pause
from fxt.term.prompts import pick_fuzzy, pick_datetime
from fxt.data.sources import BaseSource 
from fxt.data.downloaders import BaseDownloader, DownloaderRegistry

#apps->shared

#apps->local
from .dl import DailyDownloaderApp



#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)
from . import logger
import logging
logger.setLevel(logging.WARNING)





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


#!================================================================================(80)
#! arg parsing
#!--------------------------------------------------------------------------------(80)
def parse_args(
        source_id:str|None,
        symbol:str|None,
        interval:str|None,
        start:datetime|None,
        end:datetime|None,
        #output:str|None
    ) -> dict[str,Any]:
    """ Get's the required args as needed. Skips those that are already provided.
        
        source_id: the ID of the downloader 
    """
    #~ ---- start with source/downloader cuz symbol/interval depend on it
    if source_id is None:
        #if len(SOURCES) == 1:
        #    source = DEFAULT_SOURCE  # nothing to choose from yet
        #else:
        _require_interactive("source_id")
        source_id = pick_fuzzy(
            "Pick a SOURCE:",
            [k for k in DownloaderRegistry if isinstance(k, str)]
        )
    downloader = _get_downloader(source_id)

    #----------------------------------------(40)

    #~ ---- symbol 
    if symbol is None:
        _require_interactive("symbol")
        symbol = pick_fuzzy("Pick a SYMBOL", downloader.SYMBOLS)
    else:
        try:
            # case-insensitive; error includes "did you mean"
            symbol = downloader.get_symbol(symbol)
        except ValueError as e:
            raise click.ClickException(str(e)) from e

    #~ ---- interval 
    if interval is None:
        _require_interactive("interval")
        interval = pick_fuzzy("Pick an INTERVAL:", list(downloader.INTERVALS))
    else:
        try:
            interval = downloader.get_interval(interval)
        except ValueError as e:
            raise click.ClickException(str(e)) from e

    #----------------------------------------(40)

    #~ ---- start/end
    if(start is None):
        start = pick_datetime("Pick a START dtime:")
    if(end is None):
        end = pick_datetime("Pick an END dtime:")

    #----------------------------------------(40)

    # #~ ---- output
    # if(output is None):
    #     raise ValueError("You must specify a directory for output.")
    # else:
    #     output_dir = Path(output)
    #     if(not output_dir.is_dir()):
    #         raise ValueError("You must specify an existing directory for output.")

    #----------------------------------------(40)

    #! return resulting params
    #click.echo(f"\nsource={downloader.id}  symbol={symbol}  interval={interval}")
    return {
        "downloader": downloader,
        "symbol": symbol,
        "interval": interval,
        "start": start,
        "end": end,
        #"output": output_dir
    }
#

#!================================================================================(80)
#! entry point
#!--------------------------------------------------------------------------------(80)
def go(
        downloader:BaseDownloader,
        symbol:str,
        interval:str,
        start:datetime,
        end:datetime,
        #output:Path
    ):
    """ Runs the downloader assuming all args are good.
    """
    #! prepare params
    #~ if these don't fail, they are valid (they should theoretically be good by now)
    symbol = downloader.get_symbol(symbol)
    interval = downloader.get_interval(interval)

    #~ make sure start < end
    if(start == end):
        raise ValueError("start and end must be different values")
    if(start > end): #swap them
        logger.debug("start > end; swapping them")
        start, end = end, start

    #! print the downloader params
    try:
        print(
            "**** go(): [cyan bold]DOWNLOADER PARAMS[/]"
            f"\n - [green]source ID[/]:  {downloader.id}"
            f"\n - [green]downloader[/]: {downloader}"
            f"\n - [green]symbol[/]:     {symbol}"
            f"\n - [green]interval[/]:   {interval}"
            f"\n - [green]start[/]:      {start}"
            f"\n - [green]end[/]:        {end}"
            #f"\n - [green]output[/]:     {output}"
        )
        pause()

        dd = DailyDownloaderApp(
            downloader=downloader,
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            #root=output
            
            #symbol="EUR/JPY",
            #interval="TICK",
            #January 1st is a Monday
            #start=datetime(2024,1,1),
            #end=datetime(2024,1,20)
        )
        #print(hr(title="# [bold][orchid2]starting up...[/][/]"))
        dd.run(dry=False)
    #

    except KeyboardInterrupt:
        print("[orchid2]KeyboardInterrupt[/]: Operation canceled.")
#




#!================================================================================(80)
#! main entry point
#!--------------------------------------------------------------------------------(80)
@click.command()
@click.option("--source",     "-b", default=None, help="Data broker/source. Prompted if omitted.")
@click.option("--symbol",     "-i", default=None, help="Ticker symbol for the target instrument, e.g. GBP/USD. Prompted if omitted.")
@click.option("--interval",   "-t", default=None, help="Time interval, e.g. TICK, 1MIN. Prompted if omitted.")
@click.option("--start",      "-s", default=None, help="End time, as a valid datetime string")
@click.option("--end",        "-e", default=None, help="Start time, as a valid datetime string")
#@click.option("--output",     "-o", help="Output directory.")
def cli(
        source:str|None=None,
        symbol:str|None=None,
        interval:str|None=None,
        start:datetime|None=None,
        end:datetime|None=None,
        #output:str|None=None
    ):
    """ Downloads daily files using a downloader specific to the specified broker/source.
    """
    #! hardcode for testing
    # downloader = "dukascopy"
    # instrument = "EUR/JPY"
    # interval = "TICK"
    # start = datetime(2024,1,1)
    # end = datetime(2024,2,1)


    #! first parse the args
    args = parse_args(source, symbol, interval, start, end)

    #! send the args to the downloader
    go(**args)
#


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if __name__ == "__main__":
    cli()
    #start = pick_datetime("Start", default=datetime.now().strftime("%Y-%m-%d "))

    #print(f"selected datetime: {start}")