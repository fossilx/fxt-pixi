#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
# stop pylance from being annoying by adding this to end of line:  # type: ignore
# https://rich.readthedocs.io/en/stable/appendix/colors.html

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
import logging
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


#!================================================================================(80)
#! setup (logging, types, etc)
#!--------------------------------------------------------------------------------(80)
from rich.logging import RichHandler
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[RichHandler(rich_tracebacks=True, markup=True)]
)
logger = logging.getLogger(__name__)


#from typing import TypeVar
#TSource = TypeVar("TSource", bound="BaseSource")


#!================================================================================(80)
#! model registry
#!--------------------------------------------------------------------------------(80)
from fxt.model_registry import RegisteredModel
from fxt.data import DataRegistry

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fxt.data.sources import BaseSource


@DataRegistry.register("DownloadedDataMeta", 1)
class DownloadedDataMeta(RegisteredModel):
    """
    """
    model_config = ConfigDict(
        #allows you to add extra fields/keys based on what is sent to the ctor
        extra="allow" 
    )
    # source:str = Field(
    #     description="Source name, like 'dukascopy-python'"
    # )
    source:BaseModel = Field() #source model, currently with two fields (id, method)
    symbol:str = Field(description="Financial/ticker symbol used at the source")
    interval:str = Field() #Field(default="TICK")
    start:datetime = Field()
    end:datetime = Field()
    created_at:datetime = Field()
    
    # @field_validator("interval", mode="before")
    # @classmethod 
    # def validate_interval(cls, value):
    #     """ Make sure it's a valid value. May need to create classes to
    #         represent data sources/libs (that provide access to the 
    #         allowed intervals, symbols, whatever).
    #     """
    # #
#

#!================================================================================(80)
#! other (if any)
#!--------------------------------------------------------------------------------(80)





#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print

    print()
    print("[bold cyan]HI[/]")
