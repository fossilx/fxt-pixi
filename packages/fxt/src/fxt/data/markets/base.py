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
from abc import abstractmethod #ABC, ABCMeta, 

from pydantic import BaseModel, Field, ConfigDict




#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
import logging
logger = logging.getLogger(__name__)




#!================================================================================(80)
#! base
#!--------------------------------------------------------------------------------(80)
class MarketMeta(type(BaseModel)):
    """ Allows me to control how str(BaseMarket) etc. is printed.
    """
    def __str__(cls):
        """
        """
        return cls.__name__
#


class BaseMarket(BaseModel, metaclass=MarketMeta):
    """ Base representation for financial markets.
    """
    model_config = ConfigDict(frozen=True)
    
    id:str = Field(default="base-market")

    def __str__(self):
        """
        """
        return self.__class__.__name__
    #

    @classmethod
    @abstractmethod
    def sanitize(cls, symbol:str, replacement:str="_") -> str:
        """ Sanitizes the specified symbol for use in a directory structure.
        """
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
    print("hi2u ~ from [bold cyan]BaseMarket~[/]")
    print()

    #print(BaseMarket)

    from ._registry import MarketRegistry
    @MarketRegistry.register("BEEP")
    class BEEPMarket(BaseMarket):
        """
        """
        id:str = "BEEP"

        @classmethod
        def sanitize(cls, symbol: str, replacement:str="_") -> str:
            """ For forex, it removes the slash and then replaces the rest.
            """
            symbol = symbol.replace("/", "")
            #symbol = re.sub(r"[^A-Za-z0-9._-]+", "_", symbol).strip("_")
            return symbol
        #
    #

    print("[bold cyan]printing the class type instances...[/]")
    for k,v in MarketRegistry.items():
        print(f" - {k} :: {v}")

    print("[bold cyan]printing an instance of the class..[/]")
    print(BEEPMarket())


