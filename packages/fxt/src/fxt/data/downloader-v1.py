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


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)

from fxt import get_env

DEFAULT_MAX_RETRIES = get_env('DOWNLOADER_MAX_RETRIES')




#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
#moved to fxt.descriptors
# class cached_classproperty:
#     """ A read-only, cached property that lives on the class (not the instance).
#     """
#     def __init__(self, func):
#         self.func = cache(func)
#         # Propagate abstract status to abc/Pydantic checking machinery
#         self.__isabstractmethod__ = getattr(func, "__isabstractmethod__", False)
 
#     def __get__(self, instance, owner=None):
#         if owner is None:
#             owner = type(instance)
#         return self.func(owner)
# #

def _build_map(prefix: str, module) -> dict[str, str]:
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
 
def _to_utc(value: datetime) -> datetime:
    """ Naive datetimes are assumed to be UTC; aware ones are converted to UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
#
 
def _lookup(kind: str, value: str, valid: dict[str, str]) -> str:
    """ Case-insensitive membership check; returns the uppercased key.
    """
    key = value.strip().upper()
    if key not in valid:
        close = difflib.get_close_matches(key, valid.keys(), n=5)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise ValueError(f"Invalid {kind} '{value}'.{hint}")
    return key
#


#!================================================================================(80)
#! base
#!--------------------------------------------------------------------------------(80)
class BaseDownloader(BaseModel):
    """ You create an instance using a combination of (symbol, interval)

        Then you call `download()` with `start` and `end`
    """
    model_config = ConfigDict(ignored_types=(cached_classproperty,))


    #~======================================================================(70)
    #~ fields
    #~----------------------------------------------------------------------(70)
    symbol: str = Field(description="The instrument symbol.")
    interval: str = Field(description="The interval/timeframe.")


    #~======================================================================(70)
    #~ retrieval: subclasses need to implement these two maps
    #~----------------------------------------------------------------------(70)
    #! subclasses need to implement these two maps (those with @abstractmethod)
    @cached_classproperty
    @abstractmethod
    def SYMBOL_MAP(cls) -> dict[str, str]:
        """ UPPERCASED symbol -> the broker's real symbol string.
        """
        ...
    #
    @cached_classproperty
    @abstractmethod
    def INTERVAL_MAP(cls) -> dict[str, str]:
        """ UPPERCASED interval -> the broker's real interval string.
        """
        ...
    #

    @cached_classproperty
    def SYMBOLS(cls) -> tuple[str, ...]:
        """ All valid (uppercased) symbols.
        """
        return tuple(cls.SYMBOL_MAP)
    #
    @cached_classproperty
    def INTERVALS(cls) -> tuple[str, ...]:
        """ All valid (uppercased) intervals.
        """
        return tuple(cls.INTERVAL_MAP)
    #

    #~======================================================================(70)
    #~ validation
    #~----------------------------------------------------------------------(70)
    @field_validator("symbol", mode="before")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        """
        """
        return _lookup("symbol", value, cls.SYMBOL_MAP)
    #
 
    @field_validator("interval", mode="before")
    @classmethod
    def validate_interval(cls, value: str) -> str:
        """
        """
        return _lookup("interval", value, cls.INTERVAL_MAP)
    #
 
    #~======================================================================(70)
    #~ values to send to the broker API (original casing)
    #~----------------------------------------------------------------------(70)
    @property
    def api_symbol(self) -> str:
        """ Returns the ticker symbol expected by the data source's API.
        """
        return type(self).SYMBOL_MAP[self.symbol]
    #
    @property
    def api_interval(self) -> str:
        """ Returns the interval string expected by the data source's API.
        """
        return type(self).INTERVAL_MAP[self.interval]
    #




    #~======================================================================(70)
    #~ downloader
    #~----------------------------------------------------------------------(70)
    @abstractmethod
    def download(self, start: datetime, end: datetime, dry: bool = False) -> tuple[pl.DataFrame, dict]:
        """ Download data for [start, end). Returns (dataframe, meta).
        """
        ...
    #
#-


#!================================================================================(80)
#! source: dukascopy
#!--------------------------------------------------------------------------------(80)
class DukascopyDownloadError(RuntimeError):
    """ Raised when fetching ticks from the data source fails.
    """
#

class DukascopyDownloader(BaseDownloader):
    """ Downloads data from Dukascopy via `dukascopy_python`.
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

    #~======================================================================(70)
    #~ required class properties
    #~----------------------------------------------------------------------(70)
    DEFAULT_MAX_RETRIES:int = 5

    max_retries: int = Field(
        default=DEFAULT_MAX_RETRIES, ge=1,
        description="Max fetch attempts before raising.",
    )



    #~======================================================================(70)
    #~ required class properties
    #~----------------------------------------------------------------------(70)
    @cached_classproperty
    def SYMBOL_MAP(cls) -> dict[str, str]:
        return _build_map("INSTRUMENT_", dp_instruments)
    #
 
    @cached_classproperty
    def INTERVAL_MAP(cls) -> dict[str, str]:
        return _build_map("INTERVAL_", dp)
    #

    #~======================================================================(70)
    #~ download
    #~----------------------------------------------------------------------(70)
    def download(self, start:datetime, end:datetime, dry=False) -> tuple[pl.DataFrame, dict]:
        """ Download ticks for [start, end). Naive datetimes are treated as UTC.
        """
        symbol = self.symbol
        interval = self.interval
        

        #! validate inputs
        start, end = _to_utc(start), _to_utc(end)
        if start >= end:
            raise ValueError(f"start ({start}) must be before end ({end})")

        if self.api_interval == dp.INTERVAL_TICK:
            SourceType = Ticks
        else:
            raise NotImplementedError(
                f"Only tick downloads are supported for now (got interval {interval})."
            )
        #
        
        #------------------------------------------------------------(60)

        #! handle meta
        def finish(df: pl.DataFrame, status: str) -> tuple[pl.DataFrame, dict]:
            """ Every return path goes through here so `meta` always has the same shape.
            """
            meta = SourceType.meta(
                symbol=symbol, interval=interval, start=start, end=end, status=status,
            )
            return (df, meta)
        #
    
        #! stop here if dry run
        if dry:
            return finish(pl.DataFrame(schema=SourceType.schema()), "dry-run")
        #

        #------------------------------------------------------------(60)
        
        #! download the data
        try:
            df_pandas = dp.fetch(
                instrument=self.api_symbol,
                interval=self.api_interval,
                offer_side=dp.OFFER_SIDE_BID, #only matters for Bars (ticks have both)
                start=start,
                end=end,
                max_retries=self.max_retries, #max retries, None = unlimited
                #debug=dp_logging
            )
        except Exception as e:
            raise DukascopyDownloadError(
                f"Error occurred while fetching data ({interval}) for {symbol}"
            ) from e

        #------------------------------------------------------------(60)
        
        #! case: empty
        if(df_pandas is None or df_pandas.empty):
            logger.info("No data returned for %s (%s to %s)", symbol, start, end)
            return finish(pl.DataFrame(schema=SourceType.schema()), "empty")
        #

        #! case: there's data! ~ convert to polars + fix cols
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
        
        if df.schema != SourceType.schema():
            raise RuntimeError(
                f"Generated df has invalid schema for symbol: {symbol}, interval: {interval}, "
                f" - start: {start}, end: {end}\n"
                f" - expected: {SourceType.schema()}\n"
                f" - got:      {df.schema}"
            )

        #------------------------------------------------------------(60)

        return finish(df, "success")
    #
#





#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print

    print()
    print("[bold cyan]* intervals[/]")
    print(DukascopyDownloader.INTERVALS)
    print()
    print("[bold cyan]* symbols[/]")
    print(f" - # symbols: {len(DukascopyDownloader.SYMBOLS)}")
    print(f" - first few: {DukascopyDownloader.SYMBOLS[:5]}")
    
    

    def test_simple(dry=False):
        print("* Check dry run for ticks:")
        start:datetime = datetime(2020, 1, 4)
        end:datetime = datetime(2020,1,7)
        
        downloader = DukascopyDownloader(
            symbol="GBP/USD",
            interval=dp.INTERVAL_TICK
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

    DukascopyDownloader.disable_dukascopy_python_logging()

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

