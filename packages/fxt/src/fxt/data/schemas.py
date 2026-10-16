'''
Provides schemas/settings/constants for the data used in the fxt package.
'''

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
import polars as pl
from typing import TYPE_CHECKING
from datetime import datetime
from abc import ABC, abstractmethod

#! local
from fxt.data.models import DownloadedDataMeta
if TYPE_CHECKING:
    from fxt.model_registry import RegisteredModel
    from fxt.data.sources import BaseSource


#! default exports
__all__ = [
    "Bars",
    "Ticks"
]


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
from rich.logging import RichHandler
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[RichHandler(rich_tracebacks=True, markup=True)]
)
logger = logging.getLogger(__name__)


#!================================================================================(80)
#! constants
#!--------------------------------------------------------------------------------(80)
#! moved to .env
#METADATA_KEY = "fxt" #? for cases where a key is needed for storing metadata





#!================================================================================(80)
#! metadata filtering
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
    def meta(cls, source:BaseSource, symbol: str, interval:str, **kwargs:dict) -> RegisteredModel: #dict[str, Any]:
        """ Generates metadata! Note, symbol and interval are special
        """
        #start with empty dict
        meta = {}

        #apply metadata sent as keyword args
        meta.update(kwargs)

        #overwrite (if needed) with filtered versions of important args
        meta.update({
            'source': source,
            'symbol': _filter_symbol(symbol),
            'interval': _filter_interval(interval),
            'created_at': str(datetime.now()),
        })

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


#-

#!================================================================================(80)
#! ticks
#!--------------------------------------------------------------------------------(80)
class Ticks(BaseIntervalSchema):
    """
    """
    @classmethod
    def schema(cls) -> pl.Schema:
        """
        """
        return pl.Schema({
            #! index must be first
            cls.INDEX: cls.DTIME_TYPE,

            #! rest
            #'symbol': pl.String,
            'bidPrice': pl.Float64,
            'askPrice': pl.Float64,
            'bidVolume': pl.Float64,
            'askVolume': pl.Float64
        })
    #

    @classmethod
    def meta(cls, *args, **kwargs) ->  RegisteredModel:#dict[str, Any]:
        """ 
            #this is how this method is called, need a pydantic model that works with these inputs
            meta = interval_schema.meta(
                source=self.source(), #BaseSource 
                symbol=symbol,
                interval=interval,
                start=start,
                end=end,
                status=status
            )

        """
        #if('interval' in kwargs):
        #    logger.warning("A value of ")
        #remove interval if it exists
        #kwargs.pop('interval', None)
        

        #redirect to the parent
        return super().meta(*args, **kwargs)
    #
#-


#!================================================================================(80)
#! bars
#!--------------------------------------------------------------------------------(80)
class Bars(BaseIntervalSchema):
    """ Before I can fully implement the Bars downloader, I need to have it make 
        multiple requests for each time period because it needs to request the bid 
        and ask values separately.

        Then calculate the mid values manually. Have to figure out how I want to 
        handle that.
    """
    @classmethod
    def schema(cls) -> pl.Schema:
        """
        """
        return pl.Schema({
            #! index must be first
            cls.INDEX: cls.DTIME_TYPE,

            #! rest
            'start': cls.DTIME_TYPE,
            'end': cls.DTIME_TYPE,

            #from bid prices
            'bidOpen': pl.Float64,
            'bidHigh': pl.Float64,
            'bidLow': pl.Float64,
            'bidClose': pl.Float64,

            #from ask prices
            'askOpen': pl.Float64,
            'askHigh': pl.Float64,
            'askLow': pl.Float64,
            'askClose': pl.Float64,
            
            #mid-values are from (bid+ask)/2
            'midOpen': pl.Float64,
            'midHigh': pl.Float64,
            'midLow': pl.Float64,
            'midClose': pl.Float64,

            #dukascopy-python only provides a single `volume` field
            'volume': pl.Float64,
            #'bidVolume': pl.Float64,
            #'askVolume'


            #--------------------: pl.Float64,
            'tickCount': pl.UInt64,
            'spread_mean': pl.Float64,
            'spread_max': pl.Float64
        })
    #
    
    @classmethod
    def meta(cls, *args, **kwargs) -> RegisteredModel: #dict[str, Any]:
        """ 
        """
        return super().meta(*args, **kwargs)
    #
#-


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80) 
if __name__ == '__main__':

    from rich import print

    data_types = [Ticks, Bars]

    for d in data_types:
        print(f"\n* [bold]schema type: [green]{d.name()}[/]")
        print(f"- index: {d.index()}")
        print(f"- cols: {d.cols()}")

    #-----

    def print_meta(interval_schema, custom_meta:dict|None=None, symbol:str|None=None, interval:str|None=None):
        """ symbol/duration are just example values for testing
        """
        if(custom_meta is None): custom_meta = {}
        if(symbol is None): symbol = "EURUSD"
        from fxt.data.sources import DukascopySource

        source = DukascopySource()
        start:datetime = datetime(2025,1,1)
        end:datetime = datetime(2025,1,1)

        
        if(interval_schema.name() == "Ticks"):
            meta = interval_schema.meta(
                source=source,
                symbol=symbol,
                interval='TICKS', #should be ignored
                start=start,
                end=end,
                **custom_meta
            )
        else:
            #1MIN is dp.INTERVAL_MIN_1
            _int = "1MIN" if(interval is None) else interval
            meta = interval_schema.meta(
                source=source,
                symbol=symbol,
                interval=_int,
                start=start,
                end=end,
                **custom_meta
            )

        print(f"\n* [green]Example [bold]{interval_schema.name()}[/bold] meta data[/]:")
        print(f" - [cyan]as obj:[/]\n{meta}")
        print(f" - [cyan]as json:[/]\n{meta.model_dump_json()}")
        
        #for k,v in meta.items():
        #    print(f" - [bold yellow]{k}[/]: {v}")
    #


    print_meta(Ticks)
    print_meta(Bars, interval="4HOUR")
    

