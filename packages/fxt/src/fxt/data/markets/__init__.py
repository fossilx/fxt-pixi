'''
Provides a means of having market-specific functionality.

I'll add markets as I need them. For now, only really need forex.

'''

#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
#registry first
from ._registry import MarketRegistry

#rest
from .base import BaseMarket

#to trigger registration
from .forex import ForexMarket



