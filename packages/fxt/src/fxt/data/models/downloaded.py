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
from datetime import datetime
from typing import Self

from pydantic import Field, ConfigDict
#from pydantic import BaseModel, Field, ConfigDict, field_validator, field_serializer
from pydantic import AwareDatetime, model_validator
from class_registry import RegistryKeyError

#fxt
#from fxt.registry import RegisteredModel
from fxt.data.markets import BaseMarket, MarketRegistry


#local
from ._registry import ModelRegistry
from .base import BaseIdentity
from .base import BaseMeta
from .base import BaseMetaComponent

from .dataset_identity import DatasetIdentity
from .source_component import SourceComponent



#!================================================================================(80)
#! helpers
# #!--------------------------------------------------------------------------------(80)
# #~ for: market
# def _resolve_market(v:BaseMarket|str) -> BaseMarket|str:
#     """ Returns a BaseMarket instance if possible
#     """
#     if isinstance(v, str):
#         try:
#             return MarketRegistry[v]
#         except RegistryKeyError:
#             return v #case: unregistered, keep as str
#     return v
# #
# def _market_name(v:BaseMarket|str) -> str:
#     """ Returns the market id (the value that is stored)
#     """
#     return v if(isinstance(v, str)) else v.id
# #

#~ for: created_at
def _now_local() -> datetime:
    """
    """
    return datetime.now().astimezone() #tz aware, using local tz
#


#!================================================================================(80)
#! components
#!--------------------------------------------------------------------------------(80)
#~ for: DownloadedDataMeta.source
# class SourceComponent(BaseMetaComponent):
#     """ Represents what gets stored (in json) about a source (cuz I don't want 
#         the entire model).
#     """
#     id:str = Field(
#         description="Source's ID, which links sources, downloaders, etc"
#     )
#     method:str|None = Field(
#         description="The library name, service, etc that identifies how this source is accessed.",
#         default=None
#     )
# #




#!================================================================================(80)
#! identity (small SUBSET of DownloadedDataMeta)
#!--------------------------------------------------------------------------------(80)
class DownloadedDataIdentity(BaseIdentity, frozen=True):
    """ Represents the identity for a downloaded section of a dataset,
        which is the combination of `dataset` and a `start` and `end`
    """
    dataset:DatasetIdentity
    start:AwareDatetime
    end:AwareDatetime

    #~============================================================(60)
    #~ validators
    #~------------------------------------------------------------(60)
    @model_validator(mode="after")
    def _check_start_before_end(self) -> Self:
        if self.start >= self.end:
            raise ValueError(
                f"start must be before end (start={self.start}, end={self.end})"
            )
        return self
    #

 
#


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
@ModelRegistry.register("DownloadedDataMeta", 1)
class DownloadedDataMeta(BaseMeta):
    """ For downloaded data stored in parquet files.
    """
    model_config = ConfigDict(validate_assignment=True)


    dataset:DatasetIdentity
    start:AwareDatetime
    end:AwareDatetime
    created_at:AwareDatetime = Field(
        description="Time this meta, and approx time the data, was saved.",
        default_factory=_now_local
    )

    #~============================================================(60)
    #~ validators
    #~------------------------------------------------------------(60)
    @model_validator(mode="after")
    def _check_start_before_end(self) -> Self:
        if self.start >= self.end:
            raise ValueError(
                f"start must be before end (start={self.start}, end={self.end})"
            )
        return self
    #


    #~============================================================(60)
    #~ identity
    #~------------------------------------------------------------(60)
    def identity(self) -> DownloadedDataIdentity:
        """
        """
        return DownloadedDataIdentity(
            dataset=self.dataset,
            start=self.start,
            end=self.end
        )
    #
#



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print

    print()
    print("hi2u ~ from [bold cyan]downloaded models~[/]")
    print()
