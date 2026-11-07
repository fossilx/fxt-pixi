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
import logging
from contextlib import ExitStack
from typing import TYPE_CHECKING, Protocol


#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)
from app import logger





#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class Reporter(Protocol):
    def start(self, total: int, skipped: int) -> None: ...
    def chunk_done(self, result: ChunkResult) -> None: ...
    def close(self) -> None: ...
#





#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print