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
import re

#local
from ._registry import MarketRegistry
from .base import BaseMarket


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
import logging
logger = logging.getLogger(__name__)


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
@MarketRegistry.register("forex")
class ForexMarket(BaseMarket):
    """
    """
    id:str = "forex"

    @classmethod
    def sanitize(cls, symbol: str, replacement:str="_") -> str:
        """ For forex, it removes the slash and then replaces the rest.
        """
        symbol = symbol.replace("/", "")
        symbol = re.sub(r"[^A-Za-z0-9._-]+", "_", symbol).strip("_")
        return symbol
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
    print("hi2u ~ from [bold cyan]ForexMarket~[/]")
    print()

    #print(list(MarketRegistry.keys()))
    #print(str(MarketRegistry["forex"]))

    print("[cyan bold]current markets[/]")
    for k,v in MarketRegistry.items():
        print(f" - {k} :: {v}")
    
    print()
    print("[cyan bold]testing symbol sanitization[/]")
    print(f" ~> forex->sanitize('GBP/USD'): {MarketRegistry["forex"].sanitize(symbol="GBP/USD")}")


    
    from class_registry import RegistryKeyError
    try:
        print()
        print("[cyan bold]looking for a non-existant market...[/]")
        print(MarketRegistry["badmarket"])
    except RegistryKeyError as e:
        print(f"Bad market not found! exception: {e}")