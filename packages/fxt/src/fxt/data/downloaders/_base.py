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

#import difflib
import logging
from abc import abstractmethod
from datetime import datetime

from pydantic import BaseModel, ConfigDict #, Field, field_validator
import polars as pl

#local 
#from fxt.data.schemas import Ticks, Bars
from fxt.descriptors import cached_classproperty


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)

#from fxt import get_env
#DEFAULT_MAX_RETRIES = get_env('DOWNLOADER_MAX_RETRIES')


#!================================================================================(80)
#! base
#!--------------------------------------------------------------------------------(80)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from fxt.data.sources import BaseSource



from typing import Generic, TypeVar
TSource = TypeVar("TSource", bound="BaseSource")

class BaseDownloader(BaseModel, Generic[TSource]):
    """ Linked to it's parent `source`
    """
    #! pydantic config
    model_config = ConfigDict(ignored_types=(cached_classproperty,))

    #!fields    
    source:TSource

    #~======================================================================(70)
    #~ convenience methods that interact with parent source
    #~----------------------------------------------------------------------(70)
    #! may change these as i go
    @cached_classproperty
    def SYMBOLS(self):
        """ Provide easy access to the source's symbols.
        """
        return self.source.SYMBOLS
    #
    @cached_classproperty
    def INTERVALS(self):
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

    def get_sourcemeta(self) -> dict[str:str]:
        """ Returns meta information about the source that should be used
            when storing meta information with downloaded data.
        """
        # return {
        #     "id": self.source.id,
        #     "method": self.source.method
        # }
        return self.source.model_dump()
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
    ) -> tuple[pl.DataFrame, dict]:
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
