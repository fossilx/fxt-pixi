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
from .utils import is_notebook
from .settings import get_paths, get_path, get_env, ENVSettings


#from .descriptors import classproperty, cached_classproperty

# in lib top level __init__.py
import logging
logging.getLogger(__name__).addHandler(logging.NullHandler())

#!================================================================================(80)
#! exports
#!--------------------------------------------------------------------------------(80)
__all__ = [
    'ENVSettings',
    'get_env',
    'get_path',
    'get_paths',
    'is_notebook',
]



#!================================================================================(80)
#! local
#!--------------------------------------------------------------------------------(80)

#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from rich import print
    #from IPython import get_ipython #type: ignore
    #warnings.
    print("hi2u")