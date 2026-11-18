'''
derived

Base for anything computed from other lake files (bars, features, labels).

    InputRef     one input file: where it was, what metadata type it carried, its hash
    Transform    what produced the file: name + algorithm version + parameters
    DerivedMeta  unregistered base: FileMeta + inputs + transform + checks

Bump `Transform.version` when the algorithm's output would change (a bug fix
or a different aggregation rule). Bump the *model* version only when the
metadata fields change.
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

from pydantic import Field

from ..base import CheckRecord, Component, FileMeta


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class InputRef(Component):
    path: str          # posix path relative to the lake root
    typeid: str        # the input's stored type id, copied as-is (e.g. "ConsolidatedDataMeta@1")
    sha256: str
#

class Transform(Component):
    name: str                                            # "ticks_to_bars", "resample_bars"
    version: int                                         # algorithm version
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)
#

class DerivedMeta(FileMeta):
    """ Unregistered base for derived lake files. """
    inputs: tuple[InputRef, ...] = Field(min_length=1)
    transform: Transform
    checks: tuple[CheckRecord, ...] = ()

    @property
    def passed(self) -> bool:
        """ True if no check FAILed or ERRORed (WARN and SKIP don't fail a file).
            Downstream code should refuse files where this is False.
        """
        return all(c.ok for c in self.checks)

    @property
    def failed_checks(self) -> tuple[CheckRecord, ...]:
        return tuple(c for c in self.checks if not c.ok)
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
