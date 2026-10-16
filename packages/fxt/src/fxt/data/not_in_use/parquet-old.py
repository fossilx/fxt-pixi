#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
import logging
from pathlib import Path
from datetime import datetime
from calendar import monthrange
from dateutil.relativedelta import relativedelta

import pyarrow.parquet as pq
import polars as pl

from fxt import is_notebook
from fxt.data.downloader import DukascopyDownloader

if is_notebook():
    from tqdm.notebook import tqdm
else:
    from tqdm import tqdm


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)




#!================================================================================(80)
#! metadata utils
#!--------------------------------------------------------------------------------(80)
class ParquetMetadataUtils:
    """ A utility class for handling Parquet file metadata operations.
    """
    @classmethod
    def _read_column_compression(cls, path, default="zstd"):
        """ Reads the compression type of each column in a Parquet file.
            Returns a dictionary mapping column names to their compression types.

            It's not possible to get the compression level from the parquet file. You
            need to manually save it as metadata if you want it.

            Keeping this as a reference for now (not tested/verified)
        """
        parquet_file = pq.ParquetFile(path)

        column_compressions = {
            parquet_file.metadata.row_group(r).column(c).compression
            for r in range(parquet_file.metadata.num_row_groups)
            for c in range(parquet_file.metadata.num_columns)
        }
    
        # Standard practice: use the primary compression algorithm found in the file
        # If uncompressed or uniform, fallback to the single compression type
        primary_compression = list(column_compressions)[0] if column_compressions else default
        print(f"Detected compression: {primary_compression}")

        return primary_compression
    #

    @classmethod
    def read_metadata(cls, path: str) -> dict:
        """ Returns metadata from specified parquet file without reading raw tables.
        """
        schema = pq.read_schema(path)
        raw_metadata = schema.metadata

        if not raw_metadata:
            return {}

        return {
            k.decode("utf-8"): v.decode("utf-8") for k, v in raw_metadata.items()
        }
    #

    @classmethod
    def add_metadata(cls, fpath: str|Path, new_metadata: dict, suffix:str = "-with-metadata", 
                     inplace:bool = False, compression:str = "zstd") -> str:
        """ Creates a copy or updates a parquet file with additional structural metadata keys.
        """
        path = Path(fpath)
        
        #output_path = path if inplace else path.with_name(f"{path.stem}{suffix}{path.suffix}")
        # Temporary file path used to handle execution stability during in-place replacements
        #temp_path = output_path.with_suffix(".tmp") if inplace else output_path

        #default case: not inplace, use new file with suffix
        output_path = path.with_name(f"{path.stem}{suffix}{path.suffix}")
        temp_path = output_path

        #if inplace: use a temp file 
        if inplace:
            output_path = path
            temp_path = path.with_suffix(".tmp")

        #----------------------------------------(40)

        with pq.ParquetFile(fpath) as reader:
            schema = reader.schema.to_arrow_schema()
            existing_metadata = schema.metadata or {}

            # Map inputs to standard byte payloads safely
            encoded_metadata = {
                (k.encode("utf-8") if isinstance(k, str) else k): (v.encode("utf-8") if isinstance(v, str) else str(v).encode("utf-8"))
                for k, v in new_metadata.items()
            }

            #update existing metadata
            combined_metadata = {**existing_metadata, **encoded_metadata}
            new_schema = schema.with_metadata(combined_metadata)

            with pq.ParquetWriter(str(temp_path), schema=new_schema, compression=compression) as writer:
                for i in range(reader.num_row_groups):
                    row_group = reader.read_row_group(i)
                    writer.write_table(row_group)

        if inplace:
            #this will overwrite the existing file with the new one with the new metadata
            temp_path.replace(output_path)

        return str(output_path)
#-


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80) 
if __name__ == '__main__':
    #import os
    from pprint import pprint
    from rich import print
    import pyarrow as pa

    class UNITS:
        KB = ("KB", 1024)
        MB = ("MB", 1024 * 1024)
    #
    def filesize(f, units=UNITS.MB):
        """
        """
        return (
            Path(f).stat().st_size / units[1],
            units[0]
        )
    #

    #------------------------------------------------------------(60)
    #------------------------------------------------------------(60)

    class ParquetTests:
        """ All paths in the functions below should be relative to `cls.TMPDIR`, which is 
            relative to the root of the project (most likely the pixi root).
        """
        #~======================================================================(70)
        #~ settings
        #~----------------------------------------------------------------------(70)
        #the root dir used for test files; this is RELATIVE TO THE PIXI ROOT
        TMPDIR:str = "tmp"


        #~======================================================================(70)
        #~ utils
        #~----------------------------------------------------------------------(70)
        @classmethod
        def divider(cls, txt:str|None=None, chars:str|None=None): #, width:int = 80
            from rich.console import Console
            console = Console()

            if(txt is None): txt = ""
            console.rule(txt, align="left", style="bold cyan")
        #

        @classmethod
        def panel(cls, txt:str|None=None, style:str|None="green", expand:bool=False):
            from rich.console import Console
            from rich.panel import Panel
            console = Console()

            if(txt is None): txt = ""

            txt = f"[bold white]{txt}[/bold white]"
            console.print(Panel(txt, expand=expand, style=style))
        #

        @classmethod
        def create_test_pq(cls, fpath:str = "tmp.parquet", rows:int = 1000, meta:dict|None = None, overwrite:bool = False) -> str:
            """ Creates a test parquet file with dummy data for testing purposes. You should
                only provide the filename, not the path/dirs. The fpath should be relative 
                to the project's tmp dir (which in turn in relative to pixi's root dir).

                Args:
                    fpath (str): The relative path where the test Parquet file will be created. 
            """
            print("* create_test_pq()")
            fpath = Path(cls.TMPDIR) / fpath
            if(Path(fpath).exists()):
                if(overwrite == True):
                    print(f" > [yellow]File already exists, overwriting:[/] {fpath}")
                else: 
                    print(f" > [yellow]File already exists:[/] {fpath}")
                    return fpath
            else:
                print(f" > [yellow]Creating test parquet file:[/] {fpath}")

            #----------------------------------------(40)

            table = pa.table({
                'column1': range(rows),
                'column2': [f"row_{i}" for i in range(rows)]
            })

            #handle metadata
            newmeta = {
                "source": "test",
                "yesterday": str(datetime.now() - relativedelta(hours=24)),
            }
            if(meta is not None):
                newmeta.update(meta)
            #add it to table
            schema = table.schema.with_metadata({k.encode("utf-8"): v.encode("utf-8") for k, v in newmeta.items()})
            table_with_meta = table.cast(schema)

            #----------------------------------------(40)

            #create file
            pq.write_table(table_with_meta, fpath, compression='zstd', compression_level=3)

            #----------------------------------------(40)

            return fpath
        #
        @classmethod
        def print_parquet_details(cls, abs_fpath:str|Path, title:str|None = None):
            """ use the absolute path for this method!
            """
            title = "" if title is None else f": [bold]{title}[/]"
            print(f"* print_parquet_details(){title}")

            fpath = Path(abs_fpath)
            if(not fpath.exists()):
                print(f" > [red]File does not exist:[/] {fpath.resolve()}")
                return
            
            #-----

            fs = filesize(fpath)
            print(f" > [cyan]path[/]: {Path(fpath).resolve()}")
            print(f" > [cyan]size[/]: {fs[0]:.2f} {fs[1]}") #Path('file_path').stat().st_size
            print(" > [cyan]metadata[/]:")
            meta = ParquetMetadataUtils.read_metadata(fpath)
            for k,v in meta.items():
                print(f"   - [cyan]{k}[/]: {v}")
        #
        @classmethod
        def delete_test_files(cls, prefix:str):
            """ Deletes all test files in the tmp dir based on the specified prefix.
            """
            if not prefix:
                #print("[red]Error: prefix is required to delete test files.[/]")
                raise ValueError("prefix is required to delete test files.")
                return
            #
            print(f"* delete_test_files(): deleting all files with prefix: {prefix}")

            #print(f"#{'-'*60}")
            #print("# [bold orange]* deleting test files if needed...[/]")
            #print(f"#{'-'*60}")

            tmp_dir = Path(cls.TMPDIR)
            if not tmp_dir.exists():
                print(f" > [bold red]No tmp dir found at {tmp_dir.resolve()}. Nothing to delete.[/]")
                return

            for f in tmp_dir.iterdir():
                if f.is_file() and f.suffix == ".parquet" and f.name.startswith(prefix):
                    f.unlink()
                    print(f" > [red]* Deleted test file[/]: {f.resolve()}")
        #

        #~======================================================================(70)
        #~ tests
        #~----------------------------------------------------------------------(70)
        @classmethod
        def test_reading_metadata(cls):
            #! settings
            TESTFILES = {
                "base": "test1.parquet",
            }
            CUSTOM_META = {
                "test": "test_reading_metadata"
            }

            #! setup
            cls.panel("test: test_reading_metadata")
            cls.delete_test_files(prefix="test1")
            
            #! GOGOGO
            parquetFile = cls.create_test_pq(fpath=TESTFILES["base"], meta=CUSTOM_META)
            cls.print_parquet_details(parquetFile)
        #

        #------------------------------------------------------------(60)


        @classmethod
        def test_adding_metadata(cls):
            #! settings
            TESTFILES = {
                "base": "test2.parquet",
                "with-metadata": "test2-with-metadata.parquet"
            }
            CUSTOM_META = {
                "test": "test_adding_metadata"
            }

            #----------------------------------------(40)

            #! setup
            cls.panel("test: test_adding_metadata")
            cls.delete_test_files(prefix="test2")
            
            #cls.delete_test_files(prefix="test2")

            # #delete test files if they exist
            # for f in TESTFILES.values(): #["tmp/test2.parquet", "tmp/test2-with-metadata.parquet"]:
            #     filepath = Path(cls.TMPDIR) / f
            #     if(Path(filepath).exists()):
            #         Path(filepath).unlink()
            #         print(f" - [red]* Deleted existing test file[/]: {filepath}")

            #----------------------------------------(40)

            #! GOGOGO
            parquetFile = cls.create_test_pq(fpath=TESTFILES["base"], meta=CUSTOM_META)
            #print("* starting parquet file...")
            cls.print_parquet_details(parquetFile, title="starting parquet file")

            #----------------------------------------(40)

            print("* applying new metadata...")
            newMetadata = {
                "ticker": "TestTicker",
                "market_hours": "24/5",
                "data_source": "Dukascopy",
                "updated-datetime": str(datetime.now() - relativedelta(hours=1))
            }
            resulting_file = ParquetMetadataUtils.add_metadata(parquetFile, newMetadata)

            cls.print_parquet_details(resulting_file, title="and now the modified file...")
        #
    #

    #print()
    #print()
    #ParquetTests.panel("Parquet Metadata Tests")
    #ParquetTests.header()

    #console.print(Panel("[bold white]Section Header[/bold white]", expand=False, style="green"))

    print()

    ParquetTests.test_reading_metadata()
    print("\n\n")
    ParquetTests.test_adding_metadata()
    
    

    #print(f"#{'-'*60}")

