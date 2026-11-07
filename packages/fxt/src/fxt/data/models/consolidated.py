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
from typing import Literal

from pydantic import Field
#from pydantic import BaseModel, Field, ConfigDict, field_validator, field_serializer
#from pydantic import AwareDatetime, model_validator
#from class_registry import RegistryKeyError

#fxt
from fxt.data.markets import BaseMarket, MarketRegistry

#local
from ._registry import ModelRegistry
#from .base import BaseIdentity
#from .base import BaseMeta
from .base import BaseMetaComponent
from .downloaded import DownloadedDataMeta

#from .dataset_identity import DatasetIdentity








#!================================================================================(80)
#! model: for consolidated data
#!--------------------------------------------------------------------------------(80)
from typing import Any
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table
from rich.pretty import Pretty


class ConsolidationTestComponent(BaseMetaComponent):
    """ Represents the results of a consolidation check
    """
    id:str
    status:Literal["passed", "failed"]
    reason:str|None = Field(default=None)
    values:dict[str,Any] = Field(default_factory=dict)
#

@ModelRegistry.register("ConsolidatedDataMeta", 1)
class ConsolidatedDataMeta(DownloadedDataMeta):
    """ For parquet files that are created during consolidation.

        This is basically the same as DownloadedDataMeta, but with small additions.
    """
    #consolidation_checks:dict[str,Literal["passed", "failed"]] = Field(
    consolidation_tests:list[ConsolidationTestComponent] = Field(
        description="Keeps track of the consolidation checks that are performed during consolidation.",
        #default=[]
        default_factory=list
    )

    def add_test_result(
            self, 
            id:str,
            status:Literal["passed", "failed"],
            reason:str|None=None,
            values:dict[str,Any]|None=None
        ):
        """ Adds the results of a consolidation test.
        """
        component = ConsolidationTestComponent(
            id = id,
            status = status,
            reason= reason
        )
        if(values is not None):
            component.values.update(**values)

        self.consolidation_tests.append(component)
    #

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """ https://rich.readthedocs.io/en/stable/protocol.html#console-render
            https://rich.readthedocs.io/en/stable/tables.html
        """
        #yield f"Validation Result: `{self.id}`"
        tbl = Table(title=f"{type(self).__name__}")
        tbl.add_column(style="cyan")
        tbl.add_column(style="magenta", no_wrap=True)

        for name in type(self).model_fields:
            tbl.add_row(name, Pretty(getattr(self, name)))
        #tbl.add_row(Pretty(self.dataset), Pretty(self.start), Pretty(self.end))

        #for k,v in self.model_dump().items():
        #    tbl.add_row(k, str(v))
        
        yield tbl
#



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print

    print()
    print("hi2u ~ from [bold cyan]Consolidated models~[/]")
    print()

