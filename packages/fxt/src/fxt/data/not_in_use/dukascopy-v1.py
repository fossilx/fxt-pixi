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

from functools import cache
from datetime import datetime
from pathlib import Path
from pprint import pformat

from typing import Literal, ClassVar
from pydantic import BaseModel, Field, field_validator, model_validator

import polars as pl
import dukascopy_python as dp
import dukascopy_python.instruments as dp_instruments
from rapidfuzz import process, fuzz

#local 
from fxt.data.schemas import Ticks, Bars

#default exports
__all__ = [
    "DukascopyDownloadError",
    "DukascopyDownloader"
]


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)

class DukascopyDownloadError(RuntimeError):
    """ Raised when fetching ticks from the data source fails.
    """
#


@cache
def _instrument_symbols() -> tuple[str, ...]:
    """All Dukascopy instrument constants, uppercased (computed once)."""
    return tuple(
        str(getattr(dp_instruments, attr)).upper()
        for attr in dir(dp_instruments)
        if attr.startswith("INSTRUMENT_")
    )
#



def get_allowed_intervals() -> list[str]:
    """ Returns a list of the allowed interval time units

        This is for historical data, therefore this does not involve dp.TIME_UNIT_*

        Instead, you need to use dp.INTERVAL_*
    """
    return [
        dp.INTERVAL_TICK,
        dp.INTERVAL_SEC_1,
        dp.INTERVAL_SEC_10,
        dp.INTERVAL_SEC_30,
        dp.INTERVAL_MIN_1,
        dp.INTERVAL_MIN_5,
        dp.INTERVAL_MIN_10,
        dp.INTERVAL_MIN_15,
        dp.INTERVAL_MIN_30,
        dp.INTERVAL_HOUR_1,
        dp.INTERVAL_HOUR_4,
        dp.INTERVAL_DAY_1,
        dp.INTERVAL_WEEK_1,
        dp.INTERVAL_MONTH_1
    ]
#

#!utils
def disable_dukascopy_python_logging():
    """
    """
    import logging
    logging.getLogger("DUKASCRIPT").disabled = True
#


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class DukascopyDownloader(BaseModel):
    """ You initialize this with a symbol. The rest is sent to the download function.
    """
    symbol:str = Field(
        description="Must be a valid ticker symbol for your broker"
    )




    #DEFAULT_OUTPUT_DIR: ClassVar[str] = "downloads"
    #INDEX_NAME: ClassVar[str] = "dtime"

    #----------------------------------------(40)
    
    symbol:str = Field(
        description="Must be a valid ticker symbol for your broker"
    )
    # start:datetime = Field(
    #     gt=datetime(2000,1,1),
    #     description="Can be a datetime, datetime string"
    # )
    # end: datetime | Literal["now", "today"] = Field(
    #     description="Can be a datetime, datetime string, 'now', or 'today'"
    # )
    # interval: Literal[*get_allowed_intervals()] = Field(
    #     description="Must be one of the dp.INTERVAL_ values provided by dukascopy-python",
    #     default=dp.INTERVAL_TICK
    # )



    # output_dir: Path = Field(
    #     description="Directory to save output files.",
    #     default=Path(DEFAULT_OUTPUT_DIR), 
    #     validate_default=True
    # )


    #~======================================================================(70)
    #~ validators
    #~----------------------------------------------------------------------(70)
    @field_validator('symbol', mode="before")
    @classmethod
    def check_symbol(cls, value):
        """ Check if it's a valid symbol.
        """
        match cls.ValidateSymbol(value):
            case (":valid", valid_symbol):
                return valid_symbol
            
            #fail for known reason
            case (":invalid", suggestions):
                logger.debug("Symbol validation failed for %r", value)
                raise ValueError(
                    f"invalid symbol {value!r}; did you mean one of: {suggestions}?"
                )
                
            #catchall: fail for unk reason
            case unexpected:
                logger.error("ValidateSymbol returned unexpected result: %r", unexpected)
                raise RuntimeError("Symbol validation failed unexpectedly")
    #

    # @field_validator('start', mode="before")
    # @classmethod
    # def check_start(cls, value):
    #     """ Make sure start time is valid/reasonable.
            
    #         Just a placeholder for now. I may edit it later based on the data 
    #         source. ie using dukascopy's earliest possible start date. for example,
    #         if they provide one that is before that, maybe stop it and tell them.
    #         this would ensure they are being intentional with their start date AND 
    #         that it isn't something crazy (which would probably be a typo).
    #     """
    #     return value
    # #

    # @field_validator('end', mode="after")
    # @classmethod
    # def check_end(cls, value) -> datetime:
    #     """ Takes in a value for end, which must be a datetime, or "now" or "today".
        
    #         This is run after pydantic checks it to make sure it is one of the required
    #         values.

    #         Returns a datetime object.

    #         TODO: maybe add support for date-parsable strings (I would need another
    #             function that runs BEFORE pydantic, to try to parse unrecognized
    #             strings into datetimes
            
    #     """
    #     if(isinstance(value, str)):
    #         normalized = value.strip().lower()
    #         if(normalized == "today"):
    #             return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    #         elif(normalized == "now"):
    #             return datetime.now()
    #         #else:
    #         # no other values are allowed; must be a datetime object, or "now" or "today"
    #         # pydantic stops everything else
    #     return value
    # #

    # @field_validator('output_dir', mode="before")
    # @classmethod
    # def check_output_dir(cls, value) -> Path:
    #     """ Makes sure the output dir exists
    #     """
    #     path = Path(value)
    #     if path.exists() and not path.is_dir():
    #         raise ValueError(f"output_dir exists but is not a directory: {path}")
    #     if not path.exists():
    #         raise ValueError(f"output_dir does not exist, please explicitly create it at:\n{path}")
    #     #path.mkdir(parents=True, exist_ok=True)
    #     return path
    # #

    # @model_validator(mode="after")
    # def check_dates(self):
    #     """ This checks values the entire model after validation is run.
            
    #         I think it needs to run this way (as a model validator) cuz it needs
    #         to access multiple values.
    #     """
    #     if(self.start > self.end):
    #         raise ValueError("start must be before end~!")
    #     return self
    # #


    #~======================================================================(70)
    #~ validation
    #~----------------------------------------------------------------------(70)
    @classmethod
    def ValidSymbols(self) -> list[str]:
        """ Returns a list of valid symbols for the dukascopy downloader.
        """
        return list(_instrument_symbols())
    #

    @classmethod
    #def ValidateSymbol(cls, symbol: str, n: int = 3) -> tuple[str, Union[str, list[str]]]: #threshold: float = 70.0, 
    def ValidateSymbol(cls, symbol: str, n: int = 3) -> tuple[str, str | list[str]]:
        """ Checks user input against valid Dukascopy instrument constants.

            Only exact matches (after strip/upper) are accepted. Fuzzy matching is
            used solely to suggest alternatives; auto-accepting a "close" match
            risks silently downloading the wrong instrument.

            Returns:
                (":valid", symbol) on an exact match
                (":invalid", top_n_suggestions) otherwise
        """
        #!normalize
        query = symbol.strip().upper()
        valid = cls.ValidSymbols()
        
        #! if valid, skip the rest
        if(query in valid):
            return ":valid", query

        #! check for close match
        # match = process.extractOne(
        #     search_query, 
        #     cls.ValidSymbols(), 
        #     scorer=fuzz.token_sort_ratio
        # )
        # if match:
        #     best_string, score, _ = match
        #     if score >= threshold:
        #         return ":valid", best_string
                
        #find top n closest matches
        close_calls = process.extract(
            query, 
            valid,
            limit=n, 
            scorer=fuzz.token_sort_ratio
        )
        closest_suggestions = [item[0] for item in close_calls]
        
        return ":invalid", closest_suggestions
    #

    @classmethod
    def resolve_symbol(cls, value) -> str:
        """Return the normalized symbol or raise ``ValueError`` with suggestions."""
        if not isinstance(value, str):
            raise TypeError(f"symbol must be a string, got {type(value).__name__}")
 
        match cls.ValidateSymbol(value):
            case (":valid", valid_symbol):
                return valid_symbol
            
            case (":invalid", suggestions):
                logger.debug("Symbol validation failed for %r", value)
                raise ValueError(
                    f"invalid symbol {value!r}; did you mean one of: {suggestions}?"
                )
            
            case unexpected:
                logger.error("ValidateSymbol returned unexpected result: %r", unexpected)
                raise RuntimeError("Symbol validation failed unexpectedly")
    #

    #~======================================================================(70)
    #~ downloading
    #~----------------------------------------------------------------------(70)
    # @property
    # def Schema(self):
    #     """ Returns the expected schema for the returned df
    #     """
    #     return pl.Schema({
    #         self.INDEX_NAME: pl.Datetime(time_unit='ms', time_zone='UTC'),
    #         'symbol': pl.String,
    #         'bidPrice': pl.Float64,
    #         'askPrice': pl.Float64,
    #         'bidVolume': pl.Float64,
    #         'askVolume': pl.Float64
    #     })
    # #

    def download(
        self, 
        #symbol:str|None=None,
        start:datetime,
        end:datetime,
        interval:Literal[*get_allowed_intervals()]=dp.INTERVAL_TICK,
        dry=False
         #, dp_logging=False
    ) -> tuple(pl.DataFrame, dict):
        """ Download ticks/bars, optionally overriding the instance's symbol/start/end.
 
            Args:
                dry: Validate parameters and return an empty, correctly-typed frame.
    
            Raises:
                DukascopyDownloadError: if the fetch fails.
                ValueError: if the symbol is invalid or the result has the wrong schema.
        """
        #working_symbol = self.symbol if symbol is None else self.resolve_symbol(symbol)
        #working_start = self.start if start is None else start
        #working_end = self.end if end is None else end
        working_symbol = self.symbol
        working_start = start
        working_end = end

        #! check interval
        if(interval not in get_allowed_intervals()):
            raise ValueError(f"the provided interval ({interval}) must be one of: {get_allowed_intervals()}")
        
        #ticks or bars
        SourceType = Ticks if(interval == dp.INTERVAL_TICK) else Bars
        if(SourceType == Bars):
            raise RuntimeError(
                """\
                Disabling the use of Bars for now. Reason: the downloaded bars data doesn't 
                have the amount of info I want it to have. It only has one value for
                OHLCV.
                """
            )

        #! initialize custom meta
        custom_meta = {
            "symbol": working_symbol,
            "start": working_start,
            "end": working_end,
            "interval": interval
        }


        if(dry):
            logger.debug(
                "dry run, not downloading: symbol=%s start=%s end=%s, interval=%s",
                working_symbol,
                working_start,
                working_end,
                interval
            )
            return (pl.DataFrame(schema=SourceType.schema()), custom_meta)
        #

        #if(not dp_logging):
        #    import logging
        #    logging.getLogger("DUKASCRIPT").disabled = True
        
        #----------------------------------------(40)
        
        #! download the data
        try:
            df_pandas = dp.fetch(
                instrument=working_symbol,
                interval=interval,
                offer_side=dp.OFFER_SIDE_BID, #i don't think this applies unless using live fetch?
                start=working_start,
                end=working_end,
                max_retries=None, #max retries, None = unlimited
                #debug=dp_logging
            )
        except Exception as e:
            raise DukascopyDownloadError(
                f"Error occurred while fetching data ({interval}) for {working_symbol}"
            ) from e

        if(df_pandas is None or df_pandas.empty):
            logger.info(
                "No data returned for %s (%s to %s)",
                working_symbol,
                working_start,
                working_end
            )
            return (pl.DataFrame(schema=SourceType.schema()), custom_meta)
        #

        #----------------------------------------(40)

        #! there's data! ~ convert to polars
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

        #----------------------------------------(40)

        #! modify the df to match our expected schema
        #* fix timestamp column name
        #df = df.rename({"timestamp": self.INDEX_NAME})

        #* make sure timezone is properly applied
        #df = df.with_columns(pl.col(self.INDEX_NAME).dt.replace_time_zone("UTC"))

        #* add symbol
        #df = df.with_columns(pl.lit(working_symbol).alias("symbol"))

        # #* fix order
        # df = df.select([
        #     self.INDEX_NAME,
        #     "symbol",
        #     "bidPrice",
        #     "askPrice",
        #     "bidVolume",
        #     "askVolume"
        # ])

        #----------------------------------------(40)

        #! verify final schema
        if(df.schema != SourceType.schema()):
            from pprint import pformat
            import textwrap
            raise ValueError(textwrap.dedent(
                f"""\
                DOWNLOADED/FORMATTED DF HAS INVALID SCHEMA
                ENFORCED SCHEMA ~ SourceType->schema():
                {pformat(SourceType.schema())}

                DF schema:
                {pformat(df.schema)}

                DF data:
                {df.head()}
                """
            ))
        else:
            logger.info(f"df for {working_symbol} between {working_start} and {working_end} had the correct schema.")

        #----------------------------------------(40)

        #! now, get the metadata together
        meta = SourceType.meta(
            **custom_meta
        )
        
        #! return both
        return (df,meta)
#-





#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from datetime import datetime
    from rich import print

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
