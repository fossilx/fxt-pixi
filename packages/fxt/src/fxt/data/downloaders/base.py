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
from abc import abstractmethod
from datetime import datetime
from typing import Any, Generic, TypeVar,TYPE_CHECKING

from pydantic import BaseModel, ConfigDict #, Field, field_validator
import polars as pl

#fxt
#from fxt.data.schemas import Ticks, Bars
#from fxt.descriptors import cached_classproperty
from fxt.data.markets import BaseMarket
from fxt.data.models import DownloadedDataMeta

#if TYPE_CHECKING:
#    from fxt.data.sources import BaseSource

from fxt.data.sources.base import BaseSource   # replace the TYPE_CHECKING block



#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
import logging
logger = logging.getLogger(__name__)



#!================================================================================(80)
#! base
#!--------------------------------------------------------------------------------(80)
#bound means it must be a subclass of BaseSource
TSource = TypeVar("TSource", bound=BaseSource)

class BaseDownloader(BaseModel, Generic[TSource]):
    """ Linked to it's parent `source`
    """
    #! pydantic config
    #model_config = ConfigDict(ignored_types=(cached_classproperty,))

    #!fields
    source:TSource

    @property
    def id(self) -> str:
        return self.source.id
    #

    #~======================================================================(70)
    #~ convenience methods that interact with parent source
    #~----------------------------------------------------------------------(70)
    @property
    def SYMBOLS(self) -> tuple[str, ...]:
        """ Provide easy access to the source's symbols.
        """
        return self.source.SYMBOLS
    #
    @property
    def INTERVALS(self) -> tuple[str, ...]:
        """ Provide easy access to the source's intervals.
        """
        return self.source.INTERVALS
    #

    def get_symbol(self, value:str) -> str:
        """ Returns the broker version of the specified symbol.
        """
        return self.source.get_symbol(value)
    #
    def get_interval(self, value:str) -> str:
        """ Returns the broker version of the specified interval.
        """
        return self.source.get_interval(value)
    #

    def get_sourcemeta(self) -> dict[str, Any]:
        """ Returns meta information about the source that should be used
            when storing meta information with downloaded data.
        """
        return self.source.model_dump()
    #
    

    def which_market(self, symbol:str) -> BaseMarket|None:
        """
        """
        return self.source.which_market(symbol=symbol)
    #

    #~======================================================================(70)
    #~ downloader
    #~----------------------------------------------------------------------(70)
    @abstractmethod
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
        ...
    #
#-


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print

    print()
    print("[bold cyan]HI[/]")
