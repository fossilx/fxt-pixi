'''
The registry for every metadata model stored in lake files.

This module must not import any model modules (that avoids circular imports).
Models import `registry` from here; the package __init__ imports the models.
'''
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
from fxt.core.versioned import VersionedModelRegistry

registry: VersionedModelRegistry[int] = VersionedModelRegistry(default_version=1)
