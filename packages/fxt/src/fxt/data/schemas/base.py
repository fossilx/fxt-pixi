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
import polars as pl
from typing import TYPE_CHECKING, Any
from datetime import datetime
from abc import ABC, abstractmethod

#fxt
from fxt.data.models import DownloadedDataMeta
if TYPE_CHECKING:
    from fxt.registry import RegisteredModel
    from fxt.data.sources import BaseSource
    from fxt.data.markets import BaseMarket



#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
import logging
logger = logging.getLogger(__name__)




#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def _filter_symbol(symbol:str) -> str:
    """ 
    """
    #return symbol.replace("/", "")
    return symbol
#

def _filter_interval(interval:str) -> str:
    """ Ensures all intervals are stored in a uniform format (aka uppercase).

        They will most likely already be in the correct format, but just in case.
    """
    return interval.upper()
#


#!================================================================================(80)
#! base
#!--------------------------------------------------------------------------------(80)
class BaseIntervalSchema(ABC):
    """
    """
    #~======================================================================(70)
    #~ settings
    #~----------------------------------------------------------------------(70)
    INDEX = "dtime"
    DTIME_TYPE = pl.Datetime(time_unit='ms', time_zone='UTC')



    #~======================================================================(70)
    #~ methods that must be defined in subclasses
    #~----------------------------------------------------------------------(70)
    @classmethod
    @abstractmethod
    def schema(cls) -> pl.Schema:
        """ Should return a polars schema, with the cols defined in the order you want.

            You should define a custom version of this function in all children.
        """
        return pl.Schema({
            cls.INDEX: cls.DTIME_TYPE
        })
    #

    #! this one is optional in subclasses
    @classmethod
    def meta(
        cls, 
        source:BaseSource,
        symbol: str, 
        interval:str,
        start:datetime,
        end:datetime, 
        market:BaseMarket|str,
        **kwargs:Any
    ) -> DownloadedDataMeta:
        """ Generates metadata model, which is used when saving to disk (i.e. in a parquet)
            The details of how they get processed is in `fxt.data.ParquetStore`

            Note, symbol and interval are special
        """
        #params for the model
        meta: dict[str, Any] = {
            "dataset": {
                "source": source,
                "symbol": symbol,
                "interval": interval,
                "market": market,
            },
            "start": start,
            "end": end,

            #save any custom
            "other": kwargs
        }

        #return resulting metadata dict
        return DownloadedDataMeta(**meta)
    #
    


    #~======================================================================(70)
    #~ shared
    #~----------------------------------------------------------------------(70)
    def __init__(self):
        """ Prevent instances from being created~ cuz these are just wrappers.
        """
        raise TypeError(f"{self.__class__.__name__} is a utility class and cannot be instantiated.")
    #
    @classmethod
    def name(cls) -> str:
        """ Returns the class name of this type.
        """
        return cls.__name__
    #
    @classmethod
    def index(cls):
        """ Returns the name of the first field from the schema.
        """
        return cls.cols()[0]
    #
    @classmethod
    def cols(cls):
        """ Returns the name of the first field from the schema.
        """
        return cls.schema().names()
    #

    #~======================================================================(70)
    #~ fake data generation
    #~----------------------------------------------------------------------(70)
    @classmethod
    @abstractmethod
    def fake(
        cls,
        start: datetime,
        end: datetime,
        dt: tuple[float, float] = (0.5, 5),
        values: tuple[float, float] = (1.15, 1.5),
        volatility: float = 0.002,
        spread: float = 0.0001,
        volume: tuple[float, float] = (0.1, 10.0),
        seed: int | None = None,
    ) -> pl.DataFrame:
        """ Generates fake tick data that respects `cls.schema()`, for testing.

            dt:         (min, max) seconds between ticks, uniformly random.
            values:     (low, high) range the mid price stays within.
            volatility: random-walk step size, as a fraction of the (high - low) range.
            spread:     typical bid/ask spread in price units (randomized 0.5x - 1.5x).
            volume:     (min, max) for bid/ask volumes.
            seed:       set for reproducible output.

            Naive datetimes are assumed to be UTC.
        """
        raise NotImplementedError
    #
#-


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80) 
if __name__ == '__main__':

    from rich import print
    
    print()
    print("hi2u ~ from [bold cyan]BaseIntervalSchema~[/]")
    print()


    # data_types = [Ticks, Bars]

    # for d in data_types:
    #     print(f"\n* [bold]schema type: [green]{d.name()}[/]")
    #     print(f"- index: {d.index()}")
    #     print(f"- cols: {d.cols()}")

