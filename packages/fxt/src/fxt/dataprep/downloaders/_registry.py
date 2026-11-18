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
from __future__ import annotations
from class_registry import ClassRegistry
from .base import BaseDownloader


DownloaderRegistry:ClassRegistry[BaseDownloader] = ClassRegistry()

