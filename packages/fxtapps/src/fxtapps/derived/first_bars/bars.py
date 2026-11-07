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
import sys


#fxt

#apps->shared
from fxtapps.settings import get_settings

#apps->local


#!================================================================================(80)
#! setup (logging, exceptions, types)
#!--------------------------------------------------------------------------------(80)
from . import logger
import logging
logger.setLevel(logging.WARNING)











