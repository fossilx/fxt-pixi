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
from fxt.registry import VersionedModelRegistry

ModelRegistry:VersionedModelRegistry[int] = VersionedModelRegistry(
    default_version=1
)



