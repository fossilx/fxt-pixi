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
from typing import TYPE_CHECKING, Any, ClassVar
from datetime import datetime, UTC

from pydantic import BaseModel, ConfigDict, Field, field_validator
import polars as pl
import dukascopy_python as dp

#local 
from fxt.data.schemas import Ticks, Bars
from fxt.data.models import DownloadedDataMeta
from fxt.data.sources.base import BaseSource
from fxt.data.sources.fake import FakeSource

if TYPE_CHECKING:
    from fxt.data.schemas import BaseIntervalSchema
    from fxt.data.markets import BaseMarket


from ._registry import DownloaderRegistry
from .base import BaseDownloader


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
import logging
logger = logging.getLogger(__name__)



#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def _to_utc(value: datetime) -> datetime:
    """ Naive datetimes are assumed to be UTC; aware ones are converted to UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
#

#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class FakeDownloadError(RuntimeError):
    """ Raised when fetching ticks from the data source fails.
    """
#

@DownloaderRegistry.register('fake') #id must match the one in DukascopySource
class FakeDownloader(BaseDownloader[FakeSource]):
    """ Used to emulate a downloader for testing purposes. It just returns a 
        df of random data with the appropriate schema.
    """
    #~======================================================================(70)
    #~ helpers/config
    #~----------------------------------------------------------------------(70)
    #model_config = ConfigDict(ignored_types=(cached_classproperty,))

    #~======================================================================(70)
    #~ downloader settings
    #~----------------------------------------------------------------------(70)
    DEFAULT_MAX_RETRIES: ClassVar[int] = 5


    #~======================================================================(70)
    #~ fields
    #~----------------------------------------------------------------------(70)
    #! not needed with pydantic v2, but kept to be explicit
    source:BaseSource = FakeSource()

    #! new fields specific to this downloader
    max_retries: int = Field(
        default=DEFAULT_MAX_RETRIES, ge=1,
        description="Max fetch attempts before raising.",
    )


    def model_post_init(self, context: Any) -> None:
        """ this works if needed
        """
        #this works, but trying to move it to app
        #self.source.disable_dukascopy_python_logging()
        
        return super().model_post_init(context)
    #

    #~======================================================================(70)
    #~ download
    #~----------------------------------------------------------------------(70)
    def download(
            self, 
            symbol:str,
            interval:str,
            start: datetime,
            end: datetime,
            dry: bool=False
        ) -> tuple[pl.DataFrame, DownloadedDataMeta]:
        """ Download data for [start, end). Returns (dataframe, meta).
        """
        #! check: symbol/interval
        symbol = self.get_symbol(symbol)
        interval = self.get_interval(interval)
        market = self.which_market(symbol=symbol)
        #print(f"symbol: {symbol} || markst: {market}")
        #sys.exit()

        #! check: start/end
        start, end = _to_utc(start), _to_utc(end)
        if start >= end:
            raise ValueError(f"start ({start}) must be before end ({end})")

        #------------------------------------------------------------(60)

        #! determine schema-type (used for meta, schemas, etc)
        interval_schema:type[BaseIntervalSchema] = None
        if interval == self.source.TICK:
            interval_schema = Ticks
        else:
            raise NotImplementedError(
                f"Only tick downloads are supported for now (got interval {interval})."
            )
        #
        
        #! handle meta
        def wrap_meta(df: pl.DataFrame, status: str) -> tuple[pl.DataFrame, DownloadedDataMeta]:
            """ Every return path goes through here so `meta` always has the same shape.
            """
            meta = interval_schema.meta(
                #source is it's own model that results in two json values
                source=self.source,
                symbol=symbol,
                interval=interval,
                start=start,
                end=end,
                market=market,

                #status isnt in the meta model, but it should be saved to "other"
                #testing it here
                status=status
            )
            return (df, meta)
        #


        #------------------------------------------------------------(60)
        
        #! stop here if dry run
        if dry:
            return wrap_meta(pl.DataFrame(schema=interval_schema.schema()), "dry-run")

        #------------------------------------------------------------(60)
        
        #! download the data
        
        try:
            #skip saturdays
            if(start.isoweekday() == 6):
                return wrap_meta(pl.DataFrame(schema=interval_schema.schema()), "empty")
            
            else:
                import time
                time.sleep(1)
                df = interval_schema.fake(
                    start=start,
                    end=end
                )

            # df_pandas = dp.fetch(
            #     instrument=symbol,
            #     interval=interval,
            #     offer_side=dp.OFFER_SIDE_BID, #only matters for Bars (ticks have both)
            #     start=start,
            #     end=end,
            #     max_retries=self.max_retries, #max retries, None = unlimited
            #     #debug=dp_logging
            # )
        except Exception as e:
            raise FakeDownloadError(
                f"Error occurred while fetching data ({interval}) for {symbol}"
            ) from e

        #------------------------------------------------------------(60)

        # #! case: empty
        # if(df_pandas is None or df_pandas.empty):
        #     logger.info("No data returned for %s (%s to %s)", symbol, start, end)
        #     return wrap_meta(pl.DataFrame(schema=interval_schema.schema()), "empty")
        # #

        # #! case: there's data! ~ convert to polars + fix cols
        # df = (
        #     pl.from_pandas(df_pandas, include_index=True)
        #     .rename({"timestamp": interval_schema.index()})
        #     .with_columns(
        #         pl.col(interval_schema.index()).dt.replace_time_zone("UTC"),
        #         #pl.lit(working_symbol).alias("symbol")
        #     )
        #     .select(
        #         interval_schema.cols()
        #     )
        # )

        #------------------------------------------------------------(60)

        # if df.schema != interval_schema.schema():
        #     raise RuntimeError(
        #         f"Generated df has invalid schema for symbol: {symbol}, interval: {interval}, "
        #         f" - start: {start}, end: {end}\n"
        #         f" - expected: {interval_schema.schema()}\n"
        #         f" - got:      {df.schema}"
        #     )

        #------------------------------------------------------------(60)

        return wrap_meta(df, "success")
    # 
#-




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from rich import print

    def test_basic(n=5):
        downloader = FakeDownloader()
        print()
        print("# [bold orchid2]test_basic()[/]")
        print("[bold cyan]  * intervals[/]")
        print(f"    - # intervals: {len(downloader.INTERVALS)}")
        print(f"    - first {n}: {downloader.INTERVALS[:n]}")
        #print(duka.INTERVALS)
        print("[bold cyan]  * symbols[/]")
        print(f"    - # symbols: {len(downloader.SYMBOLS)}")
        print(f"    - first {n}: {downloader.SYMBOLS[:n]}")
    #
    test_basic()


    def test_downloader():
        print()
        print("# [bold orchid2]test_downloader()[/]")
        
        symbol = "GBP/USD"
        interval = "TICK"
        start = datetime(2024,1,1)
        end = datetime(2024,1,2)

        #!create downloader
        duka = FakeDownloader()

        #! dldldldldl
        df, meta = duka.download(symbol, interval, start=start, end=end)

        print("[bold cyan]  * resulting df[/]")
        print(f"     - # records: {len(df)}")
        print("      - df.head():")
        print(df.head())

        
        import textwrap

        print("[bold cyan]  * resulting meta[/]")
        print(f"     - as obj:\n       {meta}")
        print("     - as json:")
        print(textwrap.indent(meta.model_dump_json(indent=4), " "*7))

        # from fxt.term import hr

        # print(hr())

        # #meta_dict = meta.model_dump()
        # newmeta = meta
        # newmeta.market = "spiffymkt"

        # print("[bold cyan]  * meta tests[/]")
        # print("     - with changed market:")
        # print(textwrap.indent(newmeta.model_dump_json(indent=4), " "*7))
        # newmeta_json = newmeta.model_dump_json()
        # print("     - as str:")
        # print(f"       {newmeta_json}")

        # print("     - back into meta obj:")
        # backtomodel = DownloadedDataMeta.model_validate_json(newmeta_json)
        # print(textwrap.indent(backtomodel.model_dump_json(indent=4), " "*7))
        # print("     - as obj:")
        # print(backtomodel)


        # print("     - now change it back to forex:")
        # backtomodel.market = "forex"
        # print(backtomodel)
        



        





        



        #print(f" - df meta json:\n{meta.model_dump_json()}")
    #

    test_downloader()
        

