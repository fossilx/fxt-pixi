#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
#registry first
from ._registry import DownloaderRegistry

#rest
from .base import BaseDownloader

#to trigger registration
from .fake import FakeDownloader
from .dukascopy import DukascopyDownloader
from .dukascopy import DukascopyDownloadError



#!================================================================================(80)
#! exports
#!--------------------------------------------------------------------------------(80)
__all__ = [
    'BaseDownloader',
    'DownloaderRegistry',
    'DukascopyDownloadError',
    'DukascopyDownloader',
    'FakeDownloader'
]