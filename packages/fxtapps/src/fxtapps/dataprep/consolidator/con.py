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

import re
#import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from collections.abc import Callable, Sequence, Mapping, Iterable
from typing import ClassVar, Any, Literal

import click
import polars as pl
from rich import print
import pprint
import textwrap
from pydantic import BaseModel, Field, ConfigDict, field_serializer, field_validator
import sqlite_utils



#fxt
from fxt.data.parquet_store import ParquetStore
from fxt.registry import RegisteredModel
from fxt.data.models import ModelRegistry
from fxt.data.models import DownloadedDataMeta, ConsolidatedDataMeta


#apps->shared
from fxtapps.dataprep.storage import StorageManager
from fxtapps.settings import get_settings
#from apps import create_logger
#apps->local
from .validation import ValidationContext
from .validation import TValidationResultsMap
from .validation import ValidationRegistry
from .validation import PathDicts
from .validation import ValidationCheckCallbackResult
from .validation import ValidationCheckCallbackAutoParams
from .validation import ValidationCheckResult



#!================================================================================(80)
#! setup (logging, exceptions, types)
#!--------------------------------------------------------------------------------(80)
from . import logger

#env vars/constants
_DOWNLOADS_DIR:Path = Path(get_settings("DOWNLOADS_DIR"))
_DOWNLOADS_MANIFEST:str = get_settings("DOWNLOADS_MANIFEST")
_CONSOLIDATED_DIR:Path = Path(get_settings("CONSOLIDATED_DIR"))
_CONSOLIDATED_MANIFEST:str = get_settings("CONSOLIDATED_MANIFEST")

MANIFEST_PATH_COLUMN:str = "path"

# class TooManySymbolsError(Exception):
#     """
#     """



#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
from .manifest_tools import ManifestTools, BadManifest


#!================================================================================(80)
#! app class
#!--------------------------------------------------------------------------------(80)
class ConsolidatorApp(BaseModel):
    """
    """
    #! class-level defaults
    DOWNLOADS_DIR:ClassVar[Path] = _DOWNLOADS_DIR
    DOWNLOADS_MANIFEST:ClassVar[str] = _DOWNLOADS_MANIFEST
    CONSOLIDATED_DIR:ClassVar[Path] = _CONSOLIDATED_DIR
    CONSOLIDATED_MANIFEST:ClassVar[str] = _CONSOLIDATED_MANIFEST


    #~======================================================================(70)
    #~ fields
    #~----------------------------------------------------------------------(70)
    symbol:str
    interval:str
    years:list[int]

    downloads_dir:Path = DOWNLOADS_DIR
    source_manifest_name:str = DOWNLOADS_MANIFEST
    output_dir:Path = CONSOLIDATED_DIR
    output_manifest_filename:str = CONSOLIDATED_MANIFEST



    
    #! properties
    @property #use @cached_property if creating this gets expensive
    def Storage(self) -> StorageManager:
        """ Creates a storage manager instance.
        """
        return StorageManager(
            root=self.downloads_dir,
            symbol=self.symbol,
            interval=self.interval
        )
    #
    #! path stuff
    @property
    def Root(self):
        """ Returns this symbol's root in the downloads folder.
        """
        return self.downloads_dir / self.Storage.sanitize(self.symbol) / self.interval
    #
    @property
    def Output(self) -> Path:
        """
        """
        return self.output_dir / self.Storage.sanitize(self.symbol) / self.interval
    #
    @property
    def OutputManifest(self) -> Path:
        """
        """
        return self.Output / self.output_manifest_filename
    #

    def _output_manifest(self, year:int) -> str:
        """
        """
        return self.Output / str(year) / self.output_manifest_filename
    #
    def _output_filepath(self, year:int) -> Path:
        """
        """
        return self.Output / str(year) / f"{self.Storage.sanitize(self.symbol)}-{year}.parquet"
    #

    @classmethod
    def sanitize(cls, v):
        """
        """
        return StorageManager.sanitize(v)
    #


    #~======================================================================(70)
    #~ finding files
    #~----------------------------------------------------------------------(70)
    DATA_PATTERN:ClassVar[str] = r"^(?P<symbol>{symbol})-(?P<day>\d{{4}}-\d{{2}}-\d{{2}})\.parquet$"
    DATA_RGLOB:ClassVar[str] = "*.parquet"
    MANIFESTS_RGLOB:ClassVar[str] = "*.db"

    #(?P<first>...) -> "first" group
    @classmethod
    def Find(cls, 
        path:Path,
        *,
        rglob:str="*",
        pattern:str|None=None,
        tags:dict[str,Any]|None=None
    ) -> PathDicts:
        """ Searches for files within path that match the provided pattern

            Returns a list of dicts, the keys of which are the named capture groups
            from the filename.

            Args:
                rglob: helps with limiting the # of filenames checked
                pattern: regex pattern with format tags in it 
                    USE NAMED CAPTURE GROUPS
                tags: if provided, these tags are parsed within pattern
                    all tag values are sanitized and escaped.
        """
        #! prepare pattern if needed
        if(pattern is not None):
            #make sure all tag values are properly sanitized for use in a regex
            if(tags is not None):
                for k,v in tags.items():
                    tags[k] = re.escape(cls.sanitize(str(v)))
                #replace said tags
                pattern = pattern.format(
                    **tags
                )
            #compile the pattern
            pattern = re.compile(pattern)
        #
        
        #! search for files
        rows = []
        for p in path.rglob(rglob):
            if(pattern is None):
                rows.append({
                    "path": str(p)
                })
                
            else:
                #maybe use search()? 
                #use prefixmatch if using py 3.15
                #use full match?
                if(m := pattern.match(p.name)): 
                    row:dict = {"path": str(p)}
                    row.update(m.groupdict())
                    rows.append(row)
        #
        return rows
    #
    # @classmethod
    # def find_data(cls, path:Path, symbol:str) -> PathDicts:
    #     """
    #     """
    #     tags = {
    #         "symbol": symbol
    #     }
    #     return cls.Find(
    #         path,
    #         rglob=cls.DATA_RGLOB,
    #         pattern=cls.DATA_PATTERN,
    #         tags=tags
    #     )
    # #
    @classmethod
    def find_manifests(cls, path:Path) -> list[str]:
        """
        """
        values:PathDicts = cls.Find(path, rglob=cls.MANIFESTS_RGLOB)
        return [v['path'] for v in values]
    #


    #~======================================================================(70)
    #~ loading files
    #~----------------------------------------------------------------------(70)
    def _load_datafiles_metadata(
            self,
            paths:Sequence[Path|str],
            expected:type[RegisteredModel]|None=None
        ) -> Sequence[RegisteredModel]:
        """ Specifically gets the meta for all files.
        """
        results:list[RegisteredModel] = []

        for path in paths:
            #load meta object
            dfmeta = ParquetStore.read_meta(path)

            #figure out the model's type
            model:type[RegisteredModel] = ModelRegistry[dfmeta['type']]

            #parse into meta model
            meta = model.model_validate_json(dfmeta['json'])
            
            if(expected is not None):
                if(not isinstance(meta, expected)): #DownloadedDataMeta
                    raise TypeError(
                        f"Meta for: `{path}`, is of the incorrect type; "
                        f"got: {type(meta)}, expected: {expected.__name__}"
                    )
            results.append(meta)

        return results
    #
    def _consolidate_metadata(
            self,
            paths:Sequence[Path|str],
            #meta:Sequence[RegisteredModel],
            tests:Mapping[str, ValidationCheckResult],
            metadb:sqlite_utils.Database|None=None
            #*,
            #expected:type[RegisteredModel]|None=None
        ) -> ConsolidatedDataMeta:
        """ Forms the meta for the consolidated file from the downloaded meta
            of many files.
        """
        models:Sequence[DownloadedDataMeta] = self._load_datafiles_metadata(
            paths=paths,
            expected=DownloadedDataMeta
        )

        #! get values ready
        consolidated:dict[str,Any] = {}

        #set dataset
        consolidated["dataset"] = models[0].dataset
        #set start and end using the min/max from the manifest

        # query = """
        #     SELECT MIN(first_ts) AS earliest_start, 
        #         MAX(last_ts) AS latest_end 
        #     FROM financial_files
        # """
        # metadb

        for m in models:
            if("dataset" not in consolidated):
                consolidated["dataset"] = m.dataset
            if("start" not in consolidated):
                consolidated["start"] = m.start

            consolidated["end"] = m.end
        
        #! create new meta object
        consolidated_meta = ConsolidatedDataMeta(**consolidated)
        #add tests:
        for v in tests.values():
            consolidated_meta.add_test_result(
                id=v.id,
                status=v.status,
                reason=v.reason,
                values=v.values
            )
        #

        return consolidated_meta
    #


    #~======================================================================(70)
    #~ processing a year
    #~----------------------------------------------------------------------(70)
    @classmethod
    def missing_days(
        cls,
        days: Iterable[date],
        start: date,
        end: date,
        skip_weekdays: frozenset[int] = frozenset(),
    ) -> list[date]:
        """ Return the days between [`start`,`end`) not present in `days`.

            An empty list means the range is fully covered.
            skip_weekdays: weekday numbers to ignore (Mon=0 ... Sat=5, Sun=6).

            missing_days(
                days,
                date(2024, 1, 1),
                date(2024, 3, 31),
                skip_weekdays=frozenset({5})
            )
        """
        if start > end:
            raise ValueError(f"start ({start}) must not be after end ({end})")

        present = set(days)
        missing = []
        d = start
        while d < end:
            if d.weekday() not in skip_weekdays and d not in present:
                missing.append(d)
            d += timedelta(days=1)
        return missing
    #
    
    # @classmethod
    # def has_every_day(cls, days: Iterable[date], year: int, skip_weekdays: frozenset[int] = frozenset()) -> bool:
    #     """
    #     """
    #     return not cls.missing_days(days, year, skip_weekdays)
    # #

    def process_year(self, year:int, echo=True, dry=True):
        """ I may make the manifest files dictate what files are used for the merger
            and not use the file-search capability.
        """
        #! find files
        root = self.Root / str(year)
        #files = self.find_data(root, symbol=self.symbol)
        manifests = self.find_manifests(root)

        #~------------------------------------------------------------(60)

        #! load the manifest, and merge it while we're at it
        tools:ManifestTools = ManifestTools()
        memdb:sqlite_utils.Database = tools.merge_to_memory(manifests, on_conflict="error")
        datasets = tools.GetUniqueValues(memdb, table=tools.ResolvedTable, column="dataset")

        #check: dataset
        if(len(datasets) > 1) :
            raise BadManifest(
                "Manifest must only be for a single symbol; "
                f" symbols found: {datasets}"
            )
        elif(len(datasets) < 1):
            raise BadManifest("Manifest has no symbols?")
        else:
            if(datasets[0] != self.symbol):
                raise BadManifest(
                    "Manifest symbol doesn't match the one specified! "
                    f" specified: {self.symbol}, manifest symbol: {datasets[0]}"
                )

        #~------------------------------------------------------------(60)

        #* get the list of days for verification
        days = sorted({
            date.fromisoformat(r["id"]) for r in memdb[tools.ResolvedTable].rows
            #.rows_where(
            #    "status = ?", 
            #    ["success"]
            #)
        })
        days_empty = sorted({
            date.fromisoformat(r["id"]) for r in memdb[tools.ResolvedTable].rows_where(
                "status = ?", 
                ["empty"]
            )
        })

        #~------------------------------------------------------------(60)
        
        #* get the list of paths
        paths = sorted({
            r["path"] for r in memdb[tools.ResolvedTable].rows_where(
                "status = ?", 
                ["success"]
            )
        })

        #~------------------------------------------------------------(60)

        #! run validation/checks
        #check: days
        start = date(year, 1, 1) #inclusive
        end = date(year+1, 1, 1) #non inclusive
        missing = self.missing_days(days, start, end)

        
        context = ValidationContext(
            year=year,
            files=paths,
            manifests=manifests,
            output=self.Output,
            output_manifest=self._output_manifest(year)   #self.OutputManifest
        )

        validation_results:TValidationResultsMap = ValidationRegistry.run(context)
        
        #if(echo):
        #    print(*validation_results.values())

        #~------------------------------------------------------------(60)

        #~ create new meta
        meta:ConsolidatedDataMeta = self._consolidate_metadata(
            paths,
            tests=validation_results,
            metadb=memdb
        )
        #if(echo):
        #    print(meta)

        #~ create lazy frame
        lf = pl.scan_parquet(paths, include_file_paths="source_path")

        #~------------------------------------------------------------(60)

        #~ determine target output path
        output_path_for_manifest = self._output_manifest(year)
        output_path_for_data = self._output_filepath(year)

        # logger.warning(
        #     f"{type(self).__name__}:process_year: writing to file..."
        #     f" - new manifest:  {output_path_for_manifest}"
        #     f" - new dataframe: {output_path_for_data}"
        # )

        #~------------------------------------------------------------(60)

        s_missing = f"[green]{len(missing)}[/]" if(not len(missing)) else f"[red]{len(missing)}[/]"
        if(echo):
            print(Panel(
                f" - total # days covered: {len(days)} ({len(days_empty)} empty)"
                f"\n - # data files:         {len(paths)}"
                f"\n - # manifests:          {len(manifests)}"
                f"\n - # missing days:       {s_missing}"
                f"\n{'-'*40}"
                f"\n - new manifest:  {output_path_for_manifest}"
                f"\n - new dataframe: {output_path_for_data}",

                #f"\n - context:\n{context.model_dump_json(indent=4)}",
                title=f"[cyan]Summary[/] for [green]Year: [bold]{year}[/][/]",
                title_align="left"
            ))

        #~------------------------------------------------------------(60)


        if(not dry):
            output_manifest_path = tools.write_to_file(
                memdb, output_path_for_manifest
            )

            output_df_path = self.Storage.write(
                path=output_path_for_data, #full path to the file
                df=lf,  #lazy frame should automatically be handled by ParquetStore
                dfmeta=meta #RegisteredModel
            )

            return (output_manifest_path, output_df_path)
    #

    #~======================================================================(70)
    #~ main api
    #~----------------------------------------------------------------------(70)
    def run(self, echo=True, dry=True):
        """
        """
        print(Panel(
            f" - symbol:   {self.symbol}"
            f"\n - interval: {self.interval}"
            f"\n - years:    {self.years}"
            f"\n {'-'*30}"
            f"\n - root:     {self.Root}"
            f"\n - output:   {self.Output}"
            f"\n - echo:     {echo}"
            f"\n - dry:      {dry}",
            title=f"[orchid2 bold]{self.__class__.__name__}[/]:[green]params[/]",
            title_align="left"
        ))
        print(Panel(
            str(ValidationRegistry),
            title="[green]Registered Validation Checks[/]", title_align="left"
        ))

        for year in self.years:
            self.process_year(year, echo=echo, dry=dry)
    #
#-







#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from fxt.term import hr
    from rich import print
    from rich.panel import Panel

    #import cli for testing
    from .cli import cli

    #from click.testing import CliRunner
    #runner = CliRunner()
    #symbol = "EURJPY"
    #interval = "1HR"

    symbol = "EUR/JPY"
    test_cases = [
        #[symbol, "--years", "2024"],
        [symbol, "--years", "2020-2024"],
        #[symbol, "--years", "2023-2025", "--interval", interval],
        #[symbol, "--years", "2023..2025"]
    ]

    for args in test_cases:
        print()
        print(hr(title=f"args: [cyan]{' '.join(args)}"))
        #result = runner.invoke(main, args)
        #print(f" * exit code: {result.exit_code}")
        #print(f" * output: {result.output.strip()}")

        #send through click 
        cli.main(args=args, standalone_mode=False)
        #trigger func directly
        #cli.callback(...)
    #
    
    #main()


    
