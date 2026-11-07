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
#from datetime import datetime
#from typing import Literal, Self
#from abc import abstractmethod

#from pydantic import BaseModel, Field, ConfigDict, field_validator, field_serializer
#from pydantic import AwareDatetime, model_validator
from pydantic import field_validator, field_serializer
from class_registry import RegistryKeyError

#fxt
#from fxt.registry import RegisteredModel
from fxt.data.markets import BaseMarket, MarketRegistry


#local
#from ._registry import ModelRegistry
from .base import BaseIdentity
from .source_component import SourceComponent



#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
#~ for: market
def _resolve_market(v:BaseMarket|str) -> BaseMarket|str:
    """ Returns a BaseMarket instance if possible
    """
    if isinstance(v, str):
        try:
            return MarketRegistry[v]
        except RegistryKeyError:
            return v #case: unregistered, keep as str
    return v
#
def _market_name(v:BaseMarket|str) -> str:
    """ Returns the market id (the value that is stored)
    """
    return v if(isinstance(v, str)) else v.id
#

#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table
from rich.pretty import Pretty

class DatasetIdentity(BaseIdentity, frozen=True):
    """ Used to ensure that datasets share the same identity.
    """
    #you can create the source by sending a dict or a BaseSource subclass
    source:SourceComponent
    symbol:str
    interval:str
    market:BaseMarket|str

    #~============================================================(60)
    #~ field-validator approach
    #~------------------------------------------------------------(60)
    @field_validator("market", mode="before")
    @classmethod
    def validate_market(cls, v:BaseMarket|str) -> BaseMarket|str:
        """
        """
        return _resolve_market(v)
    #
    @field_serializer("market", when_used="json")
    def _ser(self, v) -> str:
        """
        """
        return _market_name(v)
    #

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        tbl = Table(title=type(self).__name__, show_header=False)
        tbl.add_column(style="cyan", no_wrap=True)
        tbl.add_column(style="magenta")

        for name in type(self).model_fields:
            tbl.add_row(name, Pretty(getattr(self, name)))

        yield tbl
#


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print

    print()
    print("hi2u ~ from [bold cyan]dataset models~[/]")
    print()

