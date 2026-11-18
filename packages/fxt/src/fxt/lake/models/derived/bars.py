'''
bars

Metadata for bar files (1MIN, 1HOUR, ...) in lake/derived.
The interval lives in `dataset.interval`, so one model covers every bar size.
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
from __future__ import annotations
from typing import Literal

from pydantic import Field

from .._registry import registry
from .base import DerivedMeta


@registry.register("BarsMeta", 1)
class BarsMeta(DerivedMeta):
    rows: int = Field(ge=0)
    #! conventions stored with the data, so later code doesn't have to guess
    timestamp: Literal["open"] = "open"            # a bar's dtime is its open time
    empty_bars: Literal["omitted"] = "omitted"     # intervals with no ticks have no row
#-



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from pathlib import Path
    from rich import print

    print()
    print(f"hi2u ~ from [bold cyan]{Path(__file__).name}~[/]")
    print()

