'''
Provides schemas/settings/constants for the different time intervals.

Each time interval is responsible for:
- providing the dataframe schema
- providing a function that takes in values, and creates the corresponding
  meta model (which is then used when the data is saved to disk)
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
#from ._registry import MarketRegistry

#rest
from .base import BaseIntervalSchema

from .ticks import Ticks
from .bars import Bars


#to trigger registration
#from .forex import ForexMarket



