#!/usr/bin/env python3
""" 
"""
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

#import re
#import sqlite3
import sys
from dataclasses import dataclass
#from datetime import date #, timedelta
from pathlib import Path
from collections.abc import Callable #, Sequence, Mapping
from typing import ClassVar, Any, Literal
from typing import Protocol, runtime_checkable
from typing import TypedDict, Unpack

#import click
import polars as pl
from rich import print
#import pprint
#import textwrap
from pydantic import BaseModel, Field, ConfigDict, field_serializer
import sqlite_utils


#fxt
from fxt.data.parquet_store import ParquetStore
from fxt.registry import RegisteredModel
from fxt.data.models import ModelRegistry
from fxt.data.models import DownloadedDataMeta

#apps->shared
#from fxtapps.dataprep.storage import StorageManager
#from fxtapps.dataprep.settings import get_settings

#apps->local


#local 
#from storage import StorageManager
#from settings import get_settings



#!================================================================================(80)
#! setup (logging, exceptions, types)
#!--------------------------------------------------------------------------------(80)
from . import logger
#import logging
#logger.setLevel(logging.INFO)




#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def _load_data_file(path:Path, expected:type[RegisteredModel]|None=None) -> tuple[pl.DataFrame, Any]:
    """ Loads the provided path as a data file, returns the data + meta model.
    """
    df, dfmeta = ParquetStore.read(path=path)

    #* get target model
    model:type[RegisteredModel] = ModelRegistry[dfmeta['type']]

    #* parse into meta model
    #meta:DownloadedDataMeta = model.model_validate_json(dfmeta['json'])
    meta = model.model_validate_json(dfmeta['json'])

    if(expected is not None):
        if(not isinstance(meta, expected)): #DownloadedDataMeta
            raise TypeError(
                f"Meta for: `{path}`, is of the incorrect type; "
                f"got: {type(meta)}, expected: {expected.__name__}"
            )

    return (df, meta)
#

#!basically a list of dicts
from collections.abc import Sequence

PathDicts = Sequence[dict[str,Any]]


#!================================================================================(80)
#! types
#!--------------------------------------------------------------------------------(80)
class ValidationContext(BaseModel):
    """ Used when sending values to the check functions.
    """
    DF_PREVIEW:ClassVar[int] = 3

    model_config = ConfigDict(arbitrary_types_allowed=True)

    year: int
    files: list[str]
    manifests: list[str]
    output:Path
    output_manifest:Path

#     @field_serializer("files", "manifests")
#     def _serialize_df(self, v:pl.DataFrame):
#         """
#         """
#         #return [tuple(row) for row in v.rows()[:self.DF_PREVIEW]]
#         return v.rows()[:self.DF_PREVIEW]
#    #
#
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table

class ValidationCheckResult(BaseModel, frozen=True):
    """ Stores the result of a consolidation validation check.
    """
    id:str
    status:Literal["passed","failed"]
    
    #! optional
    reason:str|None = Field(
        default=None,
        description="If status == 'failed', this should be the reason why."
    )
    values:dict[str, Any]|None = Field(
        default=None,
        description="Contains any values that are worth storing for this validation check."
    )

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """ https://rich.readthedocs.io/en/stable/protocol.html#console-render
            https://rich.readthedocs.io/en/stable/tables.html
        """
        #yield f"Validation Result: `{self.id}`"
        tbl = Table(title=f"Validation Result: `{self.id}`")
        tbl.add_column("property", style="cyan", no_wrap=True)
        tbl.add_column("value", style="magenta")

        for k,v in self.model_dump().items():
            tbl.add_row(k, str(v))
        
        yield tbl
#

#~! callback function
@dataclass(frozen=True, slots=True)
class ValidationCheckCallbackResult:
    result: ValidationCheckResult|None
    context: ValidationContext|None
#


'''
Each callback NEEDS to take in a context and **kw

- The values of **kw are automatically filled in by the registry.
- Right now the only value sent is the ID of the callback function,
  stored as the key: "_registry_id", so you can use: 
        `kw.get('_registry_id')` 
  from within the function.

- When adding new ones, give them an underscore prefix just so it's
  obvious they are from the registry....that or maybe some other 
  prefix 
        USING "_registry_" as a prefix

'''

from typing import Required

#~ represents the callback params that are auto sent via the registry
class ValidationCheckCallbackAutoParams(TypedDict, total=False):
    """ This represents the keyword args dict that is sent to each callback,
        automatically filled in by the registry.

        The `total=False` means that, by default, these are ALL OPTIONAL
        keywords. So you should be checking for the existence of each one
        within the callbacks using:
            
            kw.get('_registry_id')

        etc.

        If you want to mark one as required, use `Required`

        - If you want them all to be required, but select a few to 
          be optional, you can remove `total=False` and use `NotRequired` 
          instead

        -----
          
        - The values for this are SET in CallbackRegistry.run()
        - The values are used in each callback.
    """
    _registry_id: Required[str]
    _registry_god: str  #if total=False, this is optional

    #to make optional ones
#

@runtime_checkable
class ValidationCheckCallback(Protocol):
    def __call__(
        self,
        #add support for **kw
        ctx: ValidationContext, /, **kw: Unpack[ValidationCheckCallbackAutoParams] 
    ) -> ValidationCheckCallbackResult|None:
        ...
#





class ValidationCheck(BaseModel, frozen=True):
    """ Represents a the combination of an id and a validation function.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True) #{"arbitrary_types_allowed": True}

    id:str
    func: ValidationCheckCallback
    desc:str|None = Field(
        default=None,
        description="Description of the validation check, if provided. Most likely from docstring."
    )

    @field_serializer("func")
    def _serialize_function(self, v:ValidationCheckCallback) -> str:
        """
        """
        #return v.__name__
        return getattr(v, "__name__", repr(v))
    #
#

TValidationResultsMap = dict[str, ValidationCheckResult|None]



#!================================================================================(80)
#! registry
#!--------------------------------------------------------------------------------(80)
class CallbackRegistry:
    """
    """
    #~======================================================================(70)
    #~ main
    #~----------------------------------------------------------------------(70)
    def __init__(self):
        """
        """
        self._registry:dict[str, ValidationCheck] = {}
    #
    def __str__(self) -> str:
        """
        """
        s = ""
        _first = True
        for k,v in self._registry.items():
            if(_first): 
                _first = False
                nl = ""
            elif(not _first):
                nl = "\n"
            s += f"{nl}[green bold]{k}:[/]\n{v.model_dump_json(indent=4)}"
        return s
    #
    def __contains__(self, item):
        """
        """
        return item in self._registry
    #
    def __getitem__(self, key):
        """
        """
        if(key not in self):
            raise KeyError(f"Key `{key}` not in this {self.__class__.__name__}")
        return self._registry[key]
    #

    #~======================================================================(70)
    #~ helpers
    #~----------------------------------------------------------------------(70)
    def _clean_docstring(self, doc:str) -> str|None:
        """ Cleans the doc string for the callables.

            We only want the first paragraph, and without the extra new lines.
        """
        #get rid of surrounding whitespace
        doc = "\n".join(line.strip() for line in doc.splitlines())
        #only keep first paragraph
        doc = doc.split("\n\n")[0]
        #remove extra new lines
        doc = doc.replace("\n", " ")
        #strip extra spaces
        doc = doc.strip()

        if(not len(doc)):
            return None

        return doc
    #

    #~======================================================================(70)
    #~ adding models to registry
    #~----------------------------------------------------------------------(70)
    def register[F: ValidationCheckCallback](self, id: str) -> Callable[[F], F]:
        def decorator(fn: F) -> F:
            if id in self._registry:
                raise ValueError(f"Duplicate check id: {id}")

            #! only keep the first sentence (look for a double line break)
            desc:str|None = self._clean_docstring(fn.__doc__) if fn.__doc__ else None

            self._registry[id] = ValidationCheck(
                id=id,
                func=fn,
                desc=desc
            )
            return fn
        return decorator
    #


    #~======================================================================(70)
    #~ run all checks
    #~----------------------------------------------------------------------(70)
    def run(self, ctx:ValidationContext) -> TValidationResultsMap:
        """
        """
        results:TValidationResultsMap = {}

        for id,chk in self._registry.items():
            #! setup extra params for this callback
            params = ValidationCheckCallbackAutoParams(
                _registry_id=id,
                #optional:
                _registry_god="momo"
            )
            # params = {
            #     "_registry_id": id
            # }

            #!trigger callback
            res:ValidationCheckCallbackResult|None = chk.func(ctx, **params)
            
            #! examine result
            if(res is None):
                results[id] = None
                logger.warning(f"Validation check: `{id}` ~ yieled a result of `None`")
            else:
                #~ save the result
                results[id] = res.result
                
                #~update context if needed
                if(res.context is not None):
                    logger.debug(f"Validation check: `{id}` updated the context!")
                    ctx = res.context


        return results
    #
#-

ValidationRegistry:CallbackRegistry = CallbackRegistry()



#!================================================================================(80)
#! validation: 
#!--------------------------------------------------------------------------------(80)

'''

@ValidationRegistry.register("check-example")
def check_example(
    ctx: ValidationContext, 
    **kw:Unpack[ValidationCheckCallbackAutoParams]
) -> ValidationCheckCallbackResult|None:
    """
    """

'''




#!================================================================================(80)
#! validation: ensure-same-dataset
#!--------------------------------------------------------------------------------(80)
#@ValidationRegistry.register("ensure-same-dataset")
def check_dataset(
    ctx: ValidationContext, 
    **kw:Unpack[ValidationCheckCallbackAutoParams]
) -> ValidationCheckCallbackResult|None:
    """ Make sure the data files are all part of the same dataset
        by checking the data file meta info.

        This shouldn't be included in doc notes.


        - If you aren't modifying the context, return None for the context
        - The only reason I'm allowing None for a return type is cuz I don't want to
          be spammed with errors during dev

        #!!! To get the ID associated with a function (aka the value set in the deco)
        #!!! use: kw.get("_id")
        #!!! 
        #!!! see: ValidationCheckCallback protocol/etc above

        
    """
    logger.debug(f"starting (from within) [bold cyan]VALIDATION CHECK[/]: [orchid2]{kw.get('_registry_id')}[/]")

    #create a set of all DataSet's from the meta
    datasets = set()

    for entry in ctx.files: #ctx.files.rows(named=True):
        p = Path(entry)

        _df:pl.DataFrame
        meta:DownloadedDataMeta
        _df, meta = _load_data_file(p, expected=DownloadedDataMeta)
        
        datasets.add(meta.dataset)
    #
    if(len(datasets) > 1):
        return ValidationCheckCallbackResult(
            result=ValidationCheckResult(
                id=kw.get('_registry_id'),
                status="failed",
                reason=f"{len(datasets)} distinct datasets",
                values={
                    "datasets": datasets
                }
            ),
            context=None
        )

    #else:
    return ValidationCheckCallbackResult(
        result=ValidationCheckResult(
            id=kw.get('_registry_id'),
            status="passed",
            values={
                "datasets": datasets
            }
        ),
        context=None
    )
#


#!================================================================================(80)
#! validation: check manifests
#!--------------------------------------------------------------------------------(80)
from .manifest_tools import ManifestTools, BadManifest

@ValidationRegistry.register("check-manifest")
def check_manifests(
    ctx: ValidationContext, 
    **kw:Unpack[ValidationCheckCallbackAutoParams]
) -> ValidationCheckCallbackResult|None:
    """ This makes sure that all of the manifest files exist and all of the data files
        (that are mentioned in the manifests) exist.
    """
    logger.debug(f"starting (from within) [bold cyan]VALIDATION CHECK[/]: [orchid2]{kw.get('_registry_id')}[/]")
    # logger.debug(
    #     "[consolidator->validator] running 'check-manifest'"
    #     f"\n - # manifests: {len(ctx.manifests)}"
    #     f"\n - to file: {ctx.output_manifest}"
    # )
    #print("manifests: ")
    #print(ctx.manifests)

    tools:ManifestTools = ManifestTools()

    #! load all the manfiests into a memory db
    try:
        memdb:sqlite_utils.Database = tools.merge_to_memory(ctx.manifests, on_conflict="error")

    except Exception as e:  # noqa: F841, TRY203
        # return ValidationCheckCallbackResult(
        #     result=ValidationCheckResult(
        #         id="check-manifest",
        #         status="failed",
        #         reason="Exception thrown while merging manifests.",
        #         values={
        #             "exception": e
        #         }
        #     ),
        #     context=None
        # )
        raise

    #! make sure each file record, with "status" == "success" is verified
    invalid:list[Path] = []
    for row in memdb[tools.ResolvedTable].rows_where("status = ?", ["success"]):
        #get the path row from db row
        path:Path = Path(row["path"])
        if(not path.is_file()):
            invalid.append(path)
    if(len(invalid)):
        raise BadManifest(
            f"File records found in manifest that DON'T exist on disk: {invalid}"
        )

    #! if we got here, yey
    return ValidationCheckCallbackResult(
        result=ValidationCheckResult(
            id=kw.get('_registry_id'),
            status="passed"
        ),
        context=None
    )

    return None
#

# @ValidationRegistry.register("check-manifest")
# def check_manifests(ctx: ValidationContext) -> ValidationCheckResult|None:
#     """ 
#     """
#     print("manifests: ")
#     print(ctx.manifests)



#     return None
# #







#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from fxt.term import hr
    from rich import print
    from rich.panel import Panel

    print()
    print("hi2u ~ from [cyan][bold]CONSOLIDATION VALIDATION[/] CHECKS~[/]")
    print()


    print(Panel(
        str(ValidationRegistry),
        title="[green]Registered Validation Checks[/]", title_align="left"
    ))
