#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
# stop pylance from being annoying by adding this to end of line:  # type: ignore
# https://rich.readthedocs.io/en/stable/appendix/colors.html

#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
import sys

from .utils import is_notebook
from .settings import get_paths, get_path, get_env
#from .descriptors import classproperty, cached_classproperty

#!================================================================================(80)
#! exports
#!--------------------------------------------------------------------------------(80)
__all__ = [
#    'ParquetDownloader',
#    'ParquetMetadataUtils',
#    'Project',
#    'TicksDownloader',
    'get_path',
    'get_paths',
    'get_env',
    'is_notebook'
]



#!================================================================================(80)
#! local
#!--------------------------------------------------------------------------------(80)
