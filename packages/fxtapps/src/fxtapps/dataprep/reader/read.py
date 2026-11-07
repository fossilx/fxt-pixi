'''
Just so I can easily use `fxt` to read the meta information related to a specific
symbol, interval, and day. This is so I can make sure changes to the model definitions 
are being properly applied.

I will probably include reading the corresponding manifest.
'''

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
import datetime as dtime
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal, Annotated
from pathlib import Path
import re

from duckdb import df
from pydantic import BaseModel, Field, ConfigDict, field_validator, BeforeValidator, field_serializer, computed_field
import polars as pl
from rich import print
from rich.panel import Panel
from alive_progress import alive_bar

#fxt
from fxt.data.sources import BaseSource
from fxt.data.markets import BaseMarket
from fxt.data.downloaders import BaseDownloader, DownloaderRegistry
from fxt.data.parquet_store import ParquetStore
from fxt.registry import RegisteredModel

from fxt.data.models import ModelRegistry
from fxt.data.models import DownloadedDataMeta
from fxt.data.models import ConsolidatedDataMeta

from fxt.data.manifest import Manifest, FinancialFileRecord


#apps->shared
from fxtapps.dataprep.storage import StorageManager
#from fxtapps.dataprep.settings import get_settings
from fxtapps.settings import get_settings

#apps->local



#!================================================================================(80)
#! setup (logging, exceptions, types)
#!--------------------------------------------------------------------------------(80)
from . import logger
#import logging
#logger.setLevel(logging.INFO)







#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
UTC = dtime.UTC #not realllly needed, but so I remember where it is defined

def _to_utc(value: datetime) -> datetime:
    """ Naive datetimes are assumed to be UTC; aware ones are converted to UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
#

def _floor_day(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)
#


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class ReadingApp(BaseModel):
    """ Provides access to the downloaded meta/manifest info for a given 
        (symbol, interval, day) combination.

        Aka it's mostly an interface to the `StorageManager`
    """
    #! FIELDS
    root:Path = Field(default=Path(get_settings("DOWNLOADS_DIR"))) #type: ignore


    #~======================================================================(70)
    #~ utils
    #~----------------------------------------------------------------------(70)
    def manager(self, symbol:str, interval:str, root:Path|str|None=None) -> StorageManager:
        """ Returns a storage manager instance for the specified args.

            Defaults to using the parent app's root if one isnt provided.
        """
        if(root is None):
            root = self.root
        root = Path(root)

        return StorageManager(
            root=self.root,
            symbol=symbol,
            interval=interval
        )
    #

    @staticmethod
    def find(
        directory:Path,
        rglob:str, #*.parquet or *.db
        pattern:str
    ) -> tuple[date, str]|None:
        """ Returns the first file matching the required pattern.
        """
        re_pattern = re.compile(pattern) #self.DATA_FILES_PATTERN(symbol))

        if(not directory.is_dir()):
            raise NotADirectoryError(f"not a dir: {directory}")

        for p in directory.rglob(rglob):
            if(m := re_pattern.match(p.name)):
                try:
                    #try to parse group with index 1 as a date
                    day = date.fromisoformat(m[1])

                    return (day, str(p))
                
                except ValueError:
                    logger.warning(f"warning: igoring file with invalid date: {p}")
        #if none were found
        return None
    #
    

    #~======================================================================(70)
    #~ finding files
    #~----------------------------------------------------------------------(70)
    @staticmethod
    def DATA_FILES_PATTERN(symbol:str, day:date|str|None=None, ext:str="parquet") -> str:
        """ Returns the regex pattern as a raw string.
        """
        #make sure they didnt provide a leading .
        ext = ext.strip(".")
        
        if(day is None):
            return rf"^{re.escape(symbol)}-(\d{{4}}-\d{{2}}-\d{{2}})\.{ext}$"
        #else
        day = str(day) #convert to isoformat if a date
        return rf"^{re.escape(symbol)}-({re.escape(day)})\.{ext}$"
    #


    def find_data(self, symbol, interval:str|None=None, day:date|str|None=None, ext:str="parquet", echo=False):
        """ Find's the source data file (if one exists).

            day must be date, or specified in "YYYY-MM-DD" format
        """
        if(echo):
            print(Panel(
                f" - [orchid1]symbol[/]:   {symbol}"
                f"\n - [orchid1]interval[/]: {interval}"
                f"\n - [orchid1]day[/]:      {day}"
                f"\n - [orchid1]ext[/]:      {ext}",
                title="[bold green]find_data(): params..[/]",
                title_align="left"
            ))

        #! need to determine the filename to use
        path:Path|str

        #! case: use storage manager
        if(interval is not None and day is not None): 
            if(isinstance(day, str)):
                day = date.fromisoformat(day)
            manager = self.manager(symbol, interval=interval, root=self.root)
            path = manager.get_database_path(day)
            if(echo):
                print(Panel(
                    f" - [orchid1]result[/]:     {path}",
                    title="[cyan]results->[bold]storagemanager[/][/]",
                    title_align="left"
                ))


        #! case: manual search
        else:
            symbol = StorageManager.sanitize(symbol)

            #~ determine search dir
            target_dir:Path = self.root / symbol
            if(interval is not None):
                target_dir = target_dir / interval

            #~ determine pattern
            if day is None:
                pattern = self.DATA_FILES_PATTERN(symbol, ext=ext)
            else:
                pattern = self.DATA_FILES_PATTERN(symbol, day=day, ext=ext)
                
            #if day is None else self.DATA_FILES_PATTERN(symbol)
            results = self.find(
                target_dir,
                rglob=f"*.{ext}",
                pattern=pattern
            )
            #day:date
            
            if(results is not None):
                day, path = results

            if(echo):
                print(Panel(
                    f" - [orchid1]target dir[/]: {target_dir}"
                    f"\n - [orchid1]pattern[/]:    {pattern}"
                    f"\n - [orchid1]result[/]:     {path}",
                    title="[cyan]results->[bold]search[/][/]",
                    title_align="left"
                ))

        return day, path
    #

    def find_manifest(self, path:Path, day:date|str, mfile:Path|str="manifest.db") -> Path|None:
        """ takes path to data file, reads local manifest
        """
        #path.parent.rglob(mfile)
        mfile = path.parent / mfile
        if(not mfile.exists()):
            raise RuntimeWarning(f"Couldn't find manifest for: {path}")
            return None
        #else:


        return mfile
    #

    


    def read(self, symbol:str, interval:str|None=None, day:date|str|None=None):
        """ Takes a symbol and interval. If a day is provided, it attempts to load it.
        """
        day, target = self.find_data(
            symbol,
            interval,
            day=day,
        )

        target = Path(target)

        #read file
        df, dfmeta = ParquetStore.read(path=target)

        #* get target model
        model:type[RegisteredModel] = ModelRegistry[dfmeta['type']]
        #* parse into meta model
        #meta:DownloadedDataMeta = model.model_validate_json(dfmeta['json'])
        meta:RegisteredModel = model.model_validate_json(dfmeta['json'])
        if(not isinstance(meta, DownloadedDataMeta)):
            raise TypeError(
                f"Meta for: `{target}`, is of the incorrect type; "
                f"got: {type(meta)}, expected: DownloadedDataMeta"
            )

        #! results
        print(Panel(
            f" - [cyan]file found:[/] {target}"
            f"\n - [orchid2 bold]day:[/] {day} (type: {type(day)})"
            f"\n - [cyan]df rows:[/] {len(df)}"
            f"\n - [cyan]df meta:[/] {dfmeta}",
            title=f"[orchid2]{self.__class__.__name__}::read()[/] -> summary",
            title_align="left"
        ))
        print(Panel(
            str(df.head()),
            title=f"[orchid2]{self.__class__.__name__}::read()[/] -> summary -> [green bold]df contents[/]",
            title_align="left"
        ))
        print(Panel(
            meta.model_dump_json(indent=4),
            title=f"[orchid2]{self.__class__.__name__}::read()[/] -> summary -> [green bold]meta contents[/]",
            title_align="left"
        ))


        #! manifest
        if(day is not None):
            mfile:Path|None = self.find_manifest(target, day)
            if(mfile is not None):
                with Manifest(path=mfile, record_type=FinancialFileRecord) as mani:
                    rtn = mani.get(
                        dataset = symbol,
                        id = str(day)
                    )
                    if(rtn):
                        print(Panel(
                            f" - data: {target}"
                            f"\n   at:   {mfile}"
                            f"\n - record:\n{rtn.model_dump_json(indent=4)}",
                            title="manifest", title_align="left"
                        ))
    #


    @classmethod
    def ReadParquet(cls, path:Path|str, metatype:type[RegisteredModel]|None=None):
        """ Takes path to target parquet file.
        """
        target:Path = Path(path)
        
        #* read in the parquet file and meta
        df, dfmeta = ParquetStore.read(path=target)
        
        #* get target model and check it
        model:type[RegisteredModel] = ModelRegistry[dfmeta['type']]
        if(metatype is not None and not issubclass(model, metatype)):
            raise TypeError(
                f"Meta for: `{target}`, is of the incorrect type; "
                f"got: {model}, expected: {metatype}"
            )

        #* parse into meta model
        meta:RegisteredModel = model.model_validate_json(dfmeta['json'])

        return df, meta
    #

#




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from fxt.term import hr, clear, pause
    from rich import print
    from rich.panel import Panel
    from collections.abc import Iterable
    from InquirerPy import inquirer
    from fxt.data.downloaders import FakeDownloader

    def go():
        """
        """
        cases = [
            dict(id="sym", params={"symbol": "EUR/JPY"}),  # noqa: C408
            #dict(id="sym+int", params={"symbol": "EUR/JPY", "interval": "TICK"}),  # noqa: C408
            #dict(id="sym+int+day", params={"symbol": "EUR/JPY", "interval": "TICK", "day": "2024-03-25"}),  # noqa: C408
            
        ]
        #symbol:str = "EUR/JPY"
        #interval:str = "TICK"

        app = ReadingApp()
        first = True
        
        for case in cases:
            if(first):
                first = False
            else:
                pause()
                clear()
            #

            print()
            print(hr(characters="≡"))
            print(hr(title=f"# testing: [green]{case["id"]}[/], params: {case['params']}"))
            print(hr(characters="—"))
            app.read(**case['params']) #type: ignore
           
    #
    #go()

    def summarize_df(df):
        """
        """
        print(Panel(
            f"df rows: {len(df)}"
            f"\n"
            f"\n{df.head(3)}"
            "\n..."
            f"\n{df.tail(3)}",
            title="[green bold]df contents[/]",
            title_align="left"
        ))
    def summarize_meta(meta, metatype:type[RegisteredModel]|None=None):
        """
        """
        if(metatype is not None):
            metatype_s = f" (type: {metatype.__name__})"
        else:
            metatype_s = ""

        print(Panel(
            meta.model_dump_json(indent=4),
            title=f"[green bold]meta contents{metatype_s}[/]",
            title_align="left"
        ))



    from typing import Any
    MetaType = type[RegisteredModel]|None
    TestLabel = str
    TestCase = tuple[TestLabel, Path, MetaType]


    paths:list[TestCase] = [ #tuple[Path, MetaType]
        #downloaded file
        (   
            "testing downloaded file",
            Path("/home/tony/cloud/.rclone-sync/code/python/.jupyter-pixi/datalake/.downloads/EURJPY/TICK/2020/02/EURJPY-2020-02-03.parquet"),
            DownloadedDataMeta
        ),
        #consolidated file
        (
            "testing consolidated file",
            Path("/home/tony/cloud/.rclone-sync/code/python/.jupyter-pixi/datalake/.consolidated/EURJPY/TICK/2022/EURJPY-2022.parquet"),
            ConsolidatedDataMeta
        ),
        (
            "testing consolidated file",
            Path("/home/tony/cloud/.rclone-sync/code/python/.jupyter-pixi/datalake/.consolidated/EURJPY/TICK/2023/EURJPY-2023.parquet"),
            ConsolidatedDataMeta
        )
    ]

    header_border = "pink1"
    header_text = "bold red"
    _first = True
    for p in paths:
        if(_first):
            _first = False
        else:
            pause()
            clear()

        pth:Path = Path(p[1])
        if(not pth.exists()):
            logger.warning(f"file not found: {pth}")
            continue
        metatype:MetaType = p[2]

        print()
        print()
        print(hr(characters="≡", style=f"{header_border}"))
        print(hr(title=f"# [{header_text}]{p[0]}[/] -> [white]ReadParquet()[/], file: {pth.name}"))
        print(hr(characters="—", style=f"{header_border}"))


        df, meta = ReadingApp.ReadParquet(pth, metatype=metatype)



        summarize_df(df)
        summarize_meta(meta, metatype=metatype)

        print(hr(characters="—", style="red"))

        #@pause()