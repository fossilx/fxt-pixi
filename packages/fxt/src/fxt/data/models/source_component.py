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
from pydantic import Field


#local
#from ._registry import ModelRegistry
from .base import BaseMetaComponent



#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class SourceComponent(BaseMetaComponent):
    """ Represents what gets stored (in json) about a source (cuz I don't want 
        the entire model).
    """
    id:str = Field(
        description="Source's ID, which links sources, downloaders, etc"
    )
    method:str|None = Field(
        description="The library name, service, etc that identifies how this source is accessed.",
        default=None
    )
#




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print

    print()
    print("hi2u ~ from [bold cyan]SourceComponent~[/]")
    print()

