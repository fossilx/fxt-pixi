#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
import logging
from datetime import datetime
from pathlib import Path
from typing import ClassVar
from abc import abstractmethod
from functools import cache

from pydantic import BaseModel, Field, field_validator
import polars as pl
import dukascopy_python as dp
import dukascopy_python.instruments as dp_instruments


#local 
from fxt.data.schemas import Ticks, Bars



#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)

class DukascopyDownloadError(RuntimeError):
    """ Raised when fetching ticks from the data source fails.
    """
#

#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class cached_classproperty:
    def __init__(self, func):
        self.func = cache(func)
        # Propagate abstract status to abc/Pydantic checking machinery
        self.__isabstractmethod__ = getattr(func, "__isabstractmethod__", False)

    def __get__(self, instance, owner=None):
        if owner is None:
            owner = type(instance)
        return self.func(owner)
#

class BaseDownloader(BaseModel):
    """
    """
    #~======================================================================(70)
    #~ fields
    #~----------------------------------------------------------------------(70)
    symbol: str = Field(description="The instrument symbol.")
    interval: str = Field(description="The interval/timeframe.")


    #~======================================================================(70)
    #~ main retrieval methods that get, or hardcode, the values for the corresponding broker
    #~----------------------------------------------------------------------(70)
    #! main retrieval methods (these should return a tuple or list)
    @cached_classproperty
    @abstractmethod
    def SYMBOLS(cls) -> tuple[str, ...]|list[str]:
        """ All instrument constants, uppercased.
        """
        return ()
    #

    @cached_classproperty
    @abstractmethod
    def INTERVALS(cls) -> tuple[str, ...]|list[str]:
        """ All intervals constants, uppercased.
        """
        return ()
    #

    #~======================================================================(70)
    #~ validation 
    #~----------------------------------------------------------------------(70)
    @field_validator("symbol", mode="before")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        formatted = value.strip().upper()
        if formatted not in cls.SYMBOLS:
            raise ValueError(
                f"Invalid symbol '{value}'. Must be one of {cls.SYMBOLS}"
            )
        return formatted
    #

    @field_validator("interval", mode="before")
    @classmethod
    def validate_interval(cls, value: str) -> str:
        formatted = value.strip().upper()
        if formatted not in cls.INTERVALS:
            raise ValueError(
                f"Invalid interval '{value}'. Must be one of {cls.INTERVALS}"
            )
        return formatted
    #
    
    #~======================================================================(70)
    #~ downloader
    #~----------------------------------------------------------------------(70)    
    @abstractmethod
    def download(self, start:datetime, end:datetime, dry=False) -> tuple[pl.DataFrame, dict]:
        """
        """
        #symbol = self.symbol
        #interval = self.interval

        return (pl.DataFrame(), {})
    #
#-

class DukascopyDownloader(BaseDownloader):
    """
    """
    @cached_classproperty
    def SYMBOLS(cls) -> tuple[str, ...]|list[str]:
        """
        """
        return tuple(
            str(getattr(dp_instruments, attr)).upper()
            for attr in dir(dp_instruments)
            if attr.startswith("INSTRUMENT_")
        )
    #
    @cached_classproperty
    def INTERVALS(cls) -> tuple[str, ...]|list[str]:
        """
        """
        return tuple(
            str(getattr(dp, attr)).upper()
            for attr in dir(dp)
            if attr.startswith("INTERVAL_")
        )
    #

    
    def download(self, start:datetime, end:datetime, dry=False) -> tuple[pl.DataFrame, dict]:
        """
        """
        #must be initialized when class is initialized
        symbol = self.symbol
        interval = self.interval

        if(interval == dp.INTERVAL_TICK):
            SourceType = Ticks
        else:
            SourceType = Bars
            raise RuntimeError(
                """\
                The use of Bars is disabled for now.
                """
            )
                
        #! initialize custom meta
        meta = {
            "symbol": symbol,
            "interval": interval,
            "start": start,
            "end": end,
        }
        
        if dry:
            meta.update(status="dry-run")
            return pl.DataFrame(schema=SourceType.schema()), meta
        #

        #----------------------------------------(40)
        
        #! download the data
        try:
            df_pandas = dp.fetch(
                instrument=symbol,
                interval=interval,
                offer_side=dp.OFFER_SIDE_BID, #i don't think this applies unless using live fetch?
                start=start,
                end=end,
                max_retries=None, #max retries, None = unlimited
                #debug=dp_logging
            )
        except Exception as e:
            raise DukascopyDownloadError(
                f"Error occurred while fetching data ({interval}) for {symbol}"
            ) from e

        if(df_pandas is None or df_pandas.empty):
            logger.info("No data returned for %s (%s to %s)", symbol, start, end)
            return (pl.DataFrame(schema=SourceType.schema()), meta)
        #

        #----------------------------------------(40)

        #! there's data! ~ convert to polars + fix cols
        df = (
            pl.from_pandas(df_pandas, include_index=True)
            .rename({"timestamp": SourceType.index()})
            .with_columns(
                pl.col(SourceType.index()).dt.replace_time_zone("UTC"),
                #pl.lit(working_symbol).alias("symbol")
            )
            .select(
                SourceType.cols()
            )
        )

        if(df.schema != SourceType.schema()):
            import textwrap
            raise RuntimeError(textwrap.dedent(
                """\
                Generated df has invalid schema for  symbol: {symbol}~ 
                    interval: {interval}
                    start: {start}
                    end: {end}"
                """
            ))

        #----------------------------------------(40)

        #! now, get the metadata together
        meta.update(status="success")
        meta = SourceType.meta(**meta)
        
        #! return both
        return (df,meta)
    #
#





#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print


    print("intervals: ")
    print(DukascopyDownloader.INTERVALS())
    print()
    print("symbols: ")
    print(DukascopyDownloader.SYMBOLS())
    sys.exit()



    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    #logger.info("hi")

    print()
    print("* Verify that it is [bold]finding valid symbols[/]:")
    print(DukascopyDownloader.ValidSymbols()[:5])

    print()

    def test_simple(dry=False):
        print("* Check dry run for ticks:")
        start:datetime = datetime(2020, 1, 4)
        end:datetime = datetime(2020,1,7)
        
        downloader = DukascopyDownloader(
            symbol="GBP/USD"
        )
        df,meta = downloader.download(start=start, end=end, dry=dry)

        n_rows = len(df)
        print("[bold cyan]### RESULTS [/]")
        print(f"* [bold white]n rows:[/] {n_rows}")
        print( "* [bold white]meta:[/]")
        for k,v in meta.items():
            print(f" - [bold green]{k}[/]: {v}")

        if(n_rows):
            print(df.head())
        else:
            print("* df: [red]empty[/]")
    #
    test_simple()
    





    
    
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

