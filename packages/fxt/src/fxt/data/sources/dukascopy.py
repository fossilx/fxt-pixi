#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
import difflib
import logging
from abc import abstractmethod
from datetime import datetime, timezone
from functools import cache

from pydantic import BaseModel, ConfigDict, Field, field_validator
import polars as pl
import dukascopy_python as dp
import dukascopy_python.instruments as dp_instruments

#local 
from fxt.data.schemas import Ticks, Bars
from fxt.descriptors import cached_classproperty


from fxt.data.sources import BaseSource


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)

from fxt import get_env
DEFAULT_MAX_RETRIES = get_env('DOWNLOADER_MAX_RETRIES')



#!================================================================================(80)
#! source: dukascopy
#!--------------------------------------------------------------------------------(80)
class DukascopySource(BaseSource):
    """ Dukascopy source class.
    """
    #~======================================================================(70)
    #~ utils
    #~----------------------------------------------------------------------(70)
    @classmethod
    def enable_dukascopy_python_logging(cls):
        """ Turns on? the logging that dukascopy-python emits (it emit's a lot).

            TODO: VERIFY THIS WORKS -- disable it, then re-enable it
        """
        logging.getLogger("DUKASCRIPT").disabled = False
    #
    @classmethod
    def disable_dukascopy_python_logging(cls):
        """ Turns off the logging that dukascopy-python emits (it emit's a lot).
        """
        logging.getLogger("DUKASCRIPT").disabled = True
    #
    @classmethod
    def toggle_dukascopy_python_logging(cls):
        """ toggles dukascopy-python logging

            TODO: VERIFY THIS
        """
        dukas_logger = logging.getLogger("DUKASCRIPT")
        dukas_logger.disabled = not dukas_logger.disabled
    #

    @classmethod
    def _build_map(cls, prefix: str, module) -> dict[str, str]:
        """ Map UPPERCASED value -> original value for every `prefix*` constant in `module`.
            The original value is what the library actually expects.
        """
        mapping: dict[str, str] = {}
        for attr in dir(module):
            if attr.startswith(prefix):
                original = str(getattr(module, attr))
                mapping.setdefault(original.upper(), original)
        return mapping
    #

    #~======================================================================(70)
    #~ required class properties
    #~----------------------------------------------------------------------(70)
    id:str = Field(default="dukascopy")
    method:str = Field(default="dukascopy-python")
    TICK:str = Field(default=dp.INTERVAL_TICK)

    @cached_classproperty
    def SYMBOL_MAP(cls) -> dict[str, str]:
        return cls._build_map("INSTRUMENT_", dp_instruments)
    #
 
    @cached_classproperty
    def INTERVAL_MAP(cls) -> dict[str, str]:
        return cls._build_map("INTERVAL_", dp)
    #
#-


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print

    Dukascopy = DukascopySource()

    print()
    print("[bold cyan]* intervals[/]")
    print(Dukascopy.INTERVALS)
    print()
    print("[bold cyan]* symbols[/]")
    print(f" - # symbols: {len(Dukascopy.SYMBOLS)}")
    print(f" - first few: {Dukascopy.SYMBOLS[:5]}")

    #! searching for symbols
    symbols = [
        'eur/usd',
        'GBp/USd',
        'GBPJPY'
    ]
    print()
    print("[bold cyan]* symbol search[/]")
    for sym in symbols:
        try:
            api_value = Dukascopy.get_symbol(sym)
            print(f" - looking for: [bold]{sym}[/], [bold]found: [green]{api_value}[/]")
        except ValueError as e:
            print(f" - looking for: [bold]{sym}[/], [bold red]SYMBOL NOT FOUND[/], error: {e}")

    #! searching for intervals
    intervals = [
        '4hour',
        '30m',
        '1MIN'
    ]
    print()
    print("[bold cyan]* interval search[/]")
    for inter in intervals:
        try:
            api_value = Dukascopy.get_interval(inter)
            print(f" - looking for: [bold]{inter}[/], [bold]found: [green]{api_value}[/]")
        except ValueError as e:
            print(f" - looking for: [bold]{inter}[/], [bold red]INTERVAL NOT FOUND[/], error: {e}")

    print()
    print("[bold cyan]* trying model dump[/]")
    
    print(f" - [cyan]dump[/]: {Dukascopy.model_dump()}")
    print(f" - [cyan]dump_json[/]: {Dukascopy.model_dump_json()}")


    print()
    print("[bold cyan]* trying FULL model dump[/]")
    print(Dukascopy.to_full_json(indent=4))






    # def test_simple(dry=False):
    #     print("* Check dry run for ticks:")
    #     start:datetime = datetime(2020, 1, 4)
    #     end:datetime = datetime(2020,1,7)
        
    #     downloader = DukascopyDownloader(
    #         symbol="GBP/USD",
    #         interval=dp.INTERVAL_TICK
    #     )
    #     df,meta = downloader.download(start=start, end=end, dry=dry)

    #     n_rows = len(df)
    #     print("[bold cyan]### RESULTS [/]")
    #     print(f"* [bold white]n rows:[/] {n_rows}")
    #     print( "* [bold white]meta:[/]")
    #     for k,v in meta.items():
    #         print(f" - [bold green]{k}[/]: {v}")

    #     if(n_rows):
    #         print(df.head())
    #     else:
    #         print("* df: [red]empty[/]")
    # #

    # DukascopyDownloader.disable_dukascopy_python_logging()

    # test_simple()
    





    
    
    #dry example
    #df = TicksDownloader(symbol="GBP/USD", start="2020-01-04", end=datetime(2020,1,7)).download(dry=True)
    #print()
    
    #~ test: end="now"
    #df = TicksDownloader(symbol="GBP/USD", start="2020-01-04", end="now").download(dry=True)
    #print()

    #~ test: bad symbol
    # df = TicksDownloader(symbol="GBPUSD", start="2020-01-04", end="today").download(dry=True)
    # print()

    # df = TicksDownloader(
    #     symbol="GBP/USD", start="2020-01-02", end=datetime(2020,1,3)
    # ).download()
    # print(df)

    #print(DukascopyDownloader.ValidSymbols())

