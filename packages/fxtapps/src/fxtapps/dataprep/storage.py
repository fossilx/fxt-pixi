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
import json

import os
import re
import sys

from typing import ClassVar, Literal, Any
from pathlib import Path
from datetime import datetime, date, UTC

import polars as pl
from pydantic import BaseModel, Field, field_validator
from rich import print
from rich.panel import Panel
from pprint import pformat

#fxt
from fxt import get_env
from fxt.term import hr, panel_with_title
from fxt.registry import RegisteredModel
from fxt.data import ModelRegistry
from fxt.data.parquet_store import ParquetStore
from fxt.data.manifest import Manifest, FinancialFileRecord


#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)
import logging
logger = logging.getLogger(__name__)


class ManifestEntryExistsError(RuntimeError):
    """
    """


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class StorageManager(BaseModel):
    """ This needs to handle all app-specific storage, including reading/writing
        and managing the manifest.

    
        You basically create a manager that targets a specific storage location.
        This handles the rest.

        The download dir is where all downloads will be stored. They may be further
        split into dirs based on their date/etc.
    """
    MANIFEST_FILE:ClassVar[str] = "manifest.db" #MANIFEST_NAME
    MANFIEST_KEY:ClassVar[str]  = "day"
    METADATA_TYPE_KEY:ClassVar[str] = "type" #METADATA_TYPE_KEY
    METADATA_JSON_KEY:ClassVar[str] = "json" #METADATA_JSON_KEY
    DATABASE_FILE_TMPSUFFIX:ClassVar[str] = ".tmp"

    #specify the root for all storage
    root:Path = Field()
    symbol:str = Field()
    interval:str = Field()


    @field_validator('root', mode='before')
    @classmethod
    def validate_root(cls, value:str|Path) -> Path:
        """ This is the provided root for all storage
        """
        if(isinstance(value, str)):
            value = value.strip()
        value = Path(value)
        if(not value.exists() or not value.is_dir()):
            raise ValueError("You must specify an existing directory for the storage ROOT")
        return value
    #

    #~======================================================================(70)
    #~ re: paths
    #~----------------------------------------------------------------------(70)
    _safe_warning_warned:ClassVar[bool] = False
    @classmethod
    def sanitize(cls, text):
        """ Returns a version of the symbol that is safe for use in dir paths/etc.
        """
        if(not cls._safe_warning_warned):
            logger.warning(
                f"{cls.__name__}::sanitize() should probably be changed so that it has"
                " a way to use the parent source. That means that I'll need to provide" 
                " the source/downloader...so I can get the market instance, so i can"
                " use the sanitize() method. Note: Only showing this warning once."
            )
            cls._safe_warning_warned = True
        text = text.replace("/", "")
        text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")

        #print(f"text: {text}, safe: {name}")
        #sys.exit()
        return text
    #

    #!
    @classmethod
    def GetSymbols(cls, root:Path|str):
        """ Get's the available symbols.
        """
        raise NotImplementedError("Not sure if im gonna implement this yet")
    @classmethod
    def GetIntervals(self):
        """ Get's the available intervals for a given symbol
        """
        raise NotImplementedError("Not sure if im gonna implement this yet")
    
    #! dirs
    def get_symbol_root(self, symbol:str|None=None, interval:str|None=None) -> Path:
        """ The root dir for this symbol/interval combo
        
            This is the combination of: root / symbol / interval
        """
        symbol = self.symbol if symbol is None else symbol
        interval = self.interval if interval is None else interval

        #print(f"symbol: {symbol}, interval: {interval}")
        
        return self.root / self.sanitize(symbol) / self.sanitize(interval)
    #
    def get_download_dir(self, day:date, symbol:str|None=None, interval:str|None=None) -> Path:
        """
        """
        sr = self.get_symbol_root(symbol, interval)
        return sr / f"{day:%Y}/{day:%m}/"
    #
    def get_database_path(self, day:date, symbol:str|None=None, interval:str|None=None) -> Path:
        """ Path to a target database file for the provided day.
        """
        symbol = self.symbol if symbol is None else symbol

        d = self.get_download_dir(day, symbol, interval)
        return d / f"{self.sanitize(symbol)}-{day:%Y-%m-%d}.parquet"
    #
    def get_manifest_path(self, day:date, symbol:str|None=None, interval:str|None=None) -> Path:
        """
        """
        d = self.get_download_dir(day, symbol, interval)
        return d / self.MANIFEST_FILE
    #

    def print_path_summary(self, day:date) -> None:
        """ Print's the path's for a given date.
        """
        from rich.console import Group
        from rich.text import Text

        print(
            panel_with_title(
                title=f"[yellow bold]PATH SUMMARY[/] using [green]{day:%Y-%m-%d}[/]",
                message=(
                    f"- [cyan]root[/]:          {self.root}"
                    f"\n- [cyan]symbol-root[/]:   {self.get_symbol_root()}"
                    f"\n- [cyan]download-dir[/]:  {self.get_download_dir(day)}"
                    f"\n- [cyan]database-path[/]: {self.get_database_path(day)}"
                    f"\n- [cyan]manfiest-path[/]: {self.get_manifest_path(day)}"
                )
            )
        )
    #

    
    #~======================================================================(70)
    #~ re: working with manifests
    #~----------------------------------------------------------------------(70)
    ''' manifest notes:

        I built a general purpose manifest system that basically stores rows for 
        files in a given directory using primary keys comprised of

            (dataset, id)

        Those two values, when used in this context, are basically:

            (symbol, date)
    '''
    #! dataset: is going to be fixed to self.symbol
    #! id: date
    def is_done(
            self,
            id:date|str,
            dataset:str|None=None
            #symbol:str|None=None,
            #interval:str|None=None
        ) -> bool:
        """ Returns True if this day has been processed and has successfully finished,
            which means the database file exists, OR it has a manifest record with
            a status of empty.
        """
        if(dataset is None):
            dataset = self.symbol

        #! case 1: file exists (this part works)
        if(self.get_database_path(id).exists()):
           return True

        # #! case 2: check manifest
        mpath = self.get_manifest_path(id)
        with Manifest(path=mpath, record_type=FinancialFileRecord) as mani:
            record:FinancialFileRecord = mani.get(
                id=id,
                dataset=dataset
            )
            if(record is None): #means no record exists
                return False
            else: #check status
                if(record.status == "empty" or record.status == "success"):
                    return True
                else:
                    raise RuntimeError(f"Bad status found for: ('{self.symbol}', '{id}')")
            #elif(record.get("status") == "empty"):
            #    return True
        
        #! else:
        return False
    #
    def load_manifest_entry(
            self,
            id:date|str,
            dataset:str|None = None
        ):
        """ Loads and returns the manifest entry for a specific combination of
            (dataset, id) -- dataset defaults to self.symbol
        """
        if(dataset is None):
            dataset = self.symbol

        #get the manifest corresponding for this day (is a monthly one)
        manifest = self.get_manifest_path(id)
        if(not manifest.exists()):
            return {}

        #! get the row
        #rtn = {}
        with Manifest(path=manifest, record_type=FinancialFileRecord) as mani:
            rtn = mani.get(
                dataset = dataset,
                id = id
            )
            #for row in mani.rows():
            #for pk, row in mani.all():
            #    rtn[pk] = row
        #
        return rtn
    #
    def record(
            self,
            *,
            id:Any, #for fx data, this is the date
            fpath:Path|None = None, #the data file to add
            #dataset:str, #for fx data, this is the symbol (most likely)
            
            status:Literal["success", "empty", "error"],

            error:str|None = None,
            rows:int|None = None, #defaults to 0 if not specified
            #algo:str|None = None #defaults to sha256 if not specified
            #digest:str|None
            #...
            echo:bool=False, #used for debug
            **kw
        ): 
        """ fields:
                dataset, id 
                path
                status
                rows
                error:str|None
            ignore: algo, digest, size, 
        """
        #the manifest system uses a dataset var, setting that to self.symbol
        dataset = self.symbol
        
        #! paths
        mpath = self.get_manifest_path(id)
        #root is the dir with the manifest
        root = mpath.parent
        #get relative path to the data file (WRT root)
        rel_path = fpath.relative_to(root) if fpath is not None else None

        #----------------------------------------(40)

        #! record entry
        entry = {
            "dataset": dataset, 
            "id": id,
            "root": root,
            "rel_path": rel_path,
            "status": status
        }

        if(error is not None):
            entry.update(error=error)
        if(rows is not None):
            entry.update(rows=rows)

        entry.update(**kw)


        logger.debug(f"manifest entry values (before going to record): \n{pformat(entry, indent=4)}")
        if(echo):
            print(Panel(
                pformat(entry, indent=4), 
                expand=False, 
                title="manifest entry values (before going to record)",
                title_align="left"
            ))
        
        #----------------------------------------(40)

        #! create record
        record = FinancialFileRecord.FromFile(**entry)

        logger.debug(f"manifest entry -> FinancialFileRecord(): {record.model_dump_json(indent=4)}")
        if(echo):
            print(Panel(
                #pformat(entry, indent=4), 
                record.model_dump_json(indent=4),
                expand=False, 
                title="FinancialFileRecord()",
                title_align="left"
            ))

        #----------------------------------------(40)
        
        #! add it to manifest
        with Manifest(path=mpath, record_type=FinancialFileRecord) as manifest:
            manifest.add(record)

        return mpath, record
    #



    #~======================================================================(70)
    #~ re: database file
    #~----------------------------------------------------------------------(70)
    def write_day(
            self,
            day:date,
            symbol:str|None=None,
            interval:str|None=None,
            *args,
            **kwargs
            # df: pl.DataFrame,
            # dfmeta: type[RegisteredModel]|None=None,
            # symbol:str|None=None,
            # interval:str|None=None,
            # dry:bool = False
        ) -> Path:
        """ Writes the df/dfmeta for a given day to the day-appropriate path.
            Returns `Path` to created file.

            If not provided, the symbol/interval are taken from the class.
        """
        #! determine where it needs to put the file based on the day
        path = self.get_database_path(day, symbol, interval)

        #! forward to the write method
        return self.write(path, *args, **kwargs)
    #
    
    #! re: main read/write
    @classmethod
    def write(
            cls,
            path:Path,
            df: pl.DataFrame,
            dfmeta: type[RegisteredModel]|None=None,
            dry:bool = False
        ) -> Path:
        """ Writes the df/dfmeta to a specific path.

            Returns `Path` to created file.
        """
        #* path stuff
        path_tmp = path.with_suffix(path.suffix + cls.DATABASE_FILE_TMPSUFFIX)
        path.parent.mkdir(parents=True, exist_ok=True)

        #* setup metadata
        metadata = {}
        meta_id = None
        meta_json = None
        if(dfmeta is not None):
            #this lets the model determine how it is serialized
            meta_id, meta_json = dfmeta.serialize()
            metadata = {
                cls.METADATA_TYPE_KEY: meta_id,
                cls.METADATA_JSON_KEY: meta_json
            }
        
        #logger.debug(
        # logger.info(
        #     f"write() ~ about to write, and then rename: (dry: {dry})"
        #     f"\n  - temp file:             {path_tmp}"
        #     f"\n    which gets renamed to: {path}"
        #     f"\n  - df: #rows = {len(df)}"
        #     f"\n  - metadata:\n{json.dumps(metadata, indent=4)}"
        # )

        if(dry):
            logger.info(
                f"{cls.__name__}::write(dry=True): "
                f"writing df (#rows: {len(df)}) to `{path}`; "
                f"with meta: {json.dumps(metadata, indent=4)}"
            )
        else:
            written = ParquetStore.write(
                df=df,
                path=path_tmp,
                metadata=metadata
            )
            #import time
            #time.sleep(3)
            os.replace(written, path)
        
        return path
    #

    @classmethod
    def read(cls, path:Path):
        """ Reads the specified df and it's meta
        """
        df:pl.DataFrame = ParquetStore.read_df(path)

        #read meta
        meta:dict[str,str] = ParquetStore.read_meta(path)

        #convert meta back to metadata obj
        #it needs "type" and "json" keys
        if(cls.METADATA_TYPE_KEY not in meta or cls.METADATA_JSON_KEY not in meta):
            raise ValueError(
                "Provided parquet file has invalid meta (missing required keys)!" 
                f" It is missing either: `{cls.METADATA_TYPE_KEY}` or `{cls.METADATA_JSON_KEY}`"
            )

        #! search for type
        meta_type = meta["type"]
        meta_json = meta["json"]
        if(meta_type not in ModelRegistry):
            raise RuntimeError(f"Invalid/unregistered model found in parquet: {meta_type}")

        #! get the model instance
        meta_model:RegisteredModel = ModelRegistry[meta_type]

        #! convert it back into model using json values
        final_meta = meta_model.model_validate_json(meta_json)

        return df, final_meta

#-






#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from rich import print
    from rich.panel import Panel
    
    #~------------------------------------------------------------(60)
    
    symbol = "GBP/USD"
    interval = "TICK"
    testdate = date(2015, 1, 6) #2015-01-06 = Tuesday
    nonexisting = date(2014,1,1)

    man = StorageManager(
        root="downloads",
        symbol=symbol,
        interval=interval
    )
    man.print_path_summary(testdate)

    #~------------------------------------------------------------(60)

    ''' example lines from a manifest:
        {"day": "2015-01-01", "status": "success", "rows": 5949, "at": "2026-10-05T19:29:40+00:00"}
        {"day": "2015-01-02", "status": "success", "rows": 84996, "at": "2026-10-05T19:29:48+00:00"}
        {"day": "2015-01-03", "status": "empty", "rows": 0, "at": "2026-10-05T19:29:52+00:00"}
    '''
    # def test_record():
    #     """
    #     """
    #     manager = StorageManager(
    #         root="downloads",
    #         symbol="EUR/JPY",
    #         interval="TICK"
    #     )

    #     day:date = date(2024,1,5)
    #     status:str = "empty"
    #     rows:int = 2000

    #     manifest:Path
    #     entry:ManifestEntry
    #     manifest, entry = manager.record_to_manifest(day, status, rows) #dry=True)

    #     print(
    #         panel_with_title(
    #             title=f"[yellow bold]example manifest entry SUMMARY[/] using [green]{day:%Y-%m-%d}[/]",
    #             message=(
    #                 f"- [cyan]manifest[/]: {manifest}"
    #                 f"\n- [cyan]manifest entry[/]:\n{entry.model_dump_json()}"
    #             )
    #         )
    #     )
    # #
    #test_record()

    #~------------------------------------------------------------(60)
    def test_load_manifest():
        """
        """
        manager = StorageManager(
            root="downloads",
            symbol="EUR/JPY",
            interval="TICK"
        )
        
        day:date = date(2024,1,2)
        manifest = manager.load_manifest(day)

        print(manifest)
    #
    #test_load_manifest()




    #~------------------------------------------------------------(60)

    def test_isdone(manager:StorageManager, existing_day:date, nonexistant_day:date):
        """
        """
        print(
            panel_with_title(
                title="[yellow]test [bold]is_done()[/bold][/]", # using [green]{day:%Y-%m-%d}[/]
                message=(
                    f"- [green](existing)[/][cyan]is_done('[green]{existing_day:%Y-%m-%d}[/]')[/]:     [orchid2]{manager.is_done(existing_day)}[/]"
                    f"\n- [green](non-existing)[/][cyan]is_done('[green]{nonexistant_day:%Y-%m-%d}[/]')[/]: [orchid2]{manager.is_done(nonexistant_day)}[/]"
                )
            )
        )
    #
    #test_isdone(man, existing_day=testdate, nonexistant_day=nonexisting)

    #~------------------------------------------------------------(60)
    
    def test_read(manager:StorageManager):
        """
        """
        dir = Path("/home/tony/cloud/.rclone-sync/code/python/.jupyter-pixi/downloads/EURJPY/TICK/2023/01/")
        file = dir / "EURJPY-2023-01-01.parquet"

        df, meta = manager.read(file)

        print("[cyan bold]test file[/]")
        print(file)
        
        print()
        print("[cyan bold]example df[/]")
        print(df.head())

        print()
        print("[cyan bold]and meta[/]")
        print(meta)
    #
    #test_read(manager=man)

    print(list(StorageManager.model_fields.keys()))





    #def test_readmeta(manager:StorageManager, day:date):
        # """
        # """
        # #print("WTFTWFES")
        # testfile = Path("/home/tony/cloud/.rclone-sync/code/python/.jupyter-pixi/downloads/EURJPY/TICK/2024/01/")
        # testfile /= "EURJPY-2024-01-02.parquet"
        # res = ParquetUtils.read_metadata(testfile)
        # print(res)

        #dbfile = man.get_database_path(day)
        #example_db = dbfile.parent.parent / "example.parquet"

        #print(f"example: {example_db}")

        #ParquetUtils.read_metadata(example_db)

        #man.ReadMeta(dbfile)
        #StorageManager.ReadMeta(dbfile)

    #
    #test_readmeta(man, testdate)


