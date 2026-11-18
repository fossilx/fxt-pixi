#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
#registry first
from ._registry import ModelRegistry

#import the ones that need to be registered!
#this only includes the main models, not the components
from .downloaded import DownloadedDataMeta
from .consolidated import ConsolidatedDataMeta




#!================================================================================(80)
#! exports
#!--------------------------------------------------------------------------------(80)
__all__ = [
    'ConsolidatedDataMeta',
    'DownloadedDataMeta',
    'ModelRegistry'
]