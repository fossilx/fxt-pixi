'''
ParquetStore

Creates a common interface for writing/reading parquet files to disk with
(optional) metadata.

To verify the parquet file metadata, you can use the following query within
an app like Beekeeper Studio:

```sql
    -- note: this is using the duckdb library from Beekeeper Studio

    -- this automatically gets prepended to every path
    SET file_search_path = '/home/tony/path/to/outputdir/';

    SELECT 
        CAST(key as varchar) as key,
        CAST(value as varchar) as value
    FROM parquet_kv_metadata(
        'ParquetStore/test-write-(with-meta).parquet'
    );
```

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
from pathlib import Path
from typing import ClassVar

import polars as pl


#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)
import logging
from rich import print
from pprint import pformat
logger = logging.getLogger(__name__)


from . import get_dataenv
_DEFAULT_METADATA_NAMESPACE:str = get_dataenv('PARQUET_STORE_METADATA_NAMESPACE')



#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class ParquetStore:#(BaseModel):
    """ Write/read polars DataFrames to/from parquet with (optionally) namespaced 
        entries.

        This should not care what values you are writing. It should just 
        - if provided, add a namespace string to the front of each key
        - if provided, use the namespace when reading
        
        ------- 
 
        Metadata is stored in the parquet key-value footer as:
            "<namespace>:key"  -> value
    
        Requires a polars version that supports:
            `pl.read_parquet_metadata`
            `write_parquet(metadata=...)`
            `sink_parquet(metadata=...)`

        (polars >= 1.0 era; no pyarrow needed).
    """
    DEFAULT_NAMESPACE:ClassVar[str] = _DEFAULT_METADATA_NAMESPACE


    #~======================================================================(70)
    #~ namespaces
    #~----------------------------------------------------------------------(70)
    @classmethod
    def _namespace_prefix(cls, namespace:str|None):
        """ Handles how the namespace is handled.
        
            Returns the default prefix if the provided namespace is None.
        """
        if(namespace == ""):
            return ""
        elif(namespace is None):
            namespace = cls.DEFAULT_NAMESPACE

        return f"{namespace}:"
    #

    #~======================================================================(70)
    #~ writing
    #~----------------------------------------------------------------------(70)
    @classmethod
    def _prepare_write(
        cls,
        path: Path | str,
        metadata: dict[str, str] | None,
        namespace: str | None,
        overwrite: bool,
    ) -> tuple[Path, dict[str, str] | None]:
        """ Shared by the write methods (write_df() and write_lf()):
            checks the path, applies the namespace.
        """
        #check target output path
        path = Path(path)
        if path.exists():
            logger.debug(f"{cls.__name__} - file already exists, overwrite={overwrite}; path: {path}")
            if not overwrite:
                raise FileExistsError(f"Failed to write to disk; file already exists: {path}")

        ns = cls._namespace_prefix(namespace)
        if metadata is not None and len(ns):
            metadata = {f"{ns}{k}": v for k, v in metadata.items()}
        return path, metadata
    #

    @classmethod
    def write_lf(
        cls,
        lf: pl.LazyFrame,
        path:Path|str,
        metadata:dict[str, str]|None = None,
        namespace: str|None = None,
        overwrite:bool = True,
        dry:bool = False
    ) -> Path:
        """ Specifically for lazy frames.
        """
        path, metadata = cls._prepare_write(path, metadata, namespace, overwrite)

        if(not dry):
            path.parent.mkdir(parents=True, exist_ok=True)

            #! make writing atomic
            tmp = path.with_name(path.name + ".tmp")
            try:
                lf.sink_parquet(tmp, metadata=metadata)
                tmp.replace(path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise

        #return path
        return path
    #

    @classmethod
    def write_df(
        cls,
        df: pl.DataFrame,
        path:Path|str,
        metadata:dict[str, str]|None = None,
        namespace: str|None = None,
        overwrite:bool = True,
        dry:bool = False
    ) -> Path:
        """ Writes a polars dataframe to a parquet file with the given path and
            optional metadata.

            Args:
                df: dataframe to write
                path: path to output file
                metdata: (optional) dict of string keys/values 
                namespace: (optional) string to use as a prefix before the keys 
                    to prevent collisions with other libraries.

                    If you don't want a namespace, provide an empty string.

                    If you specify a namespace when writing, you should specify
                    the namespace when reading, or you'll (most likely) end up 
                    with all of the metadata.

                    for example, if namespace = "spiffy", then the metadata:
                    {
                        "id": "test 1",
                        "market": "forex"
                    }

                    is saved in the parquet file as...
                    {
                        "spiffy:id": "test 1",
                        "spiffy:market": "forex"
                    }
                overwrite: (optional), determines if it should overwrite the 
                    target file if it already exists
                dry: (optional) if `True`, it wont actually write to a file
        """
        path, metadata = cls._prepare_write(path, metadata, namespace, overwrite)
        
        if(not dry):
            path.parent.mkdir(parents=True, exist_ok=True)
            
            #! make writing atomic
            tmp = path.with_name(path.name + ".tmp")
            try:
                df.write_parquet(tmp, metadata=metadata)
                tmp.replace(path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise

            #df.write_parquet(path, metadata=metadata)

        #return path
        return path
    #

    @classmethod
    def write(
        cls,
        df: pl.DataFrame|pl.LazyFrame,
        path:Path|str,
        metadata:dict[str, str]|None = None,
        namespace: str|None = None,
        overwrite:bool = True,
        dry:bool = False
    ) -> Path:
        """ General write method that writes using either write_parquet or sink_parquet
            accordingly.
        """
        if(isinstance(df, pl.DataFrame)):
            return cls.write_df(df, path, metadata, namespace, overwrite, dry)
        elif(isinstance(df, pl.LazyFrame)):
            return cls.write_lf(df, path, metadata, namespace, overwrite, dry)
        else:
            raise TypeError("Bad type for df - must be pl.DataFrame, or pl.LazyFrame")
        #
    #



 
    #~======================================================================(70)
    #~ reading
    #~----------------------------------------------------------------------(70)
    @classmethod
    def read_lf(cls, path:Path|str) -> pl.LazyFrame:
        """ 
        """
        path = Path(path)
        return pl.scan_parquet(path)
    #

    @classmethod
    def read_df(cls, path:Path|str) -> pl.DataFrame:
        """
        """
        path = Path(path)
        return pl.read_parquet(path)
    #
    @classmethod
    def read_meta(cls, path:Path|str, namespace:str|None = None) -> dict[str,str]:
        """ This reads in the metadata and (optionally) filters for the corresponding namespace.
            
            To get all meta values, set `namespace=""`
            If no namespace is provided, it uses the default.
        """
        path = Path(path)
        metadata:dict = dict(pl.read_parquet_metadata(path))

        ns = cls._namespace_prefix(namespace)
        if(len(ns)):
            #! select meta entries with prefix (and remove prefix)
            metadata = {
                k.removeprefix(ns) : v for k,v in metadata.items()
                if k.startswith(ns)
            }

        return metadata
    #


    @classmethod
    def read(
        cls,
        path: Path|str,
        namespace:str|None = None,
    ) -> tuple[pl.DataFrame, dict[str, str]]:
        """ Returns (df, meta). If a namespace is provided, it only returns values with
            that namespace in front.
        """
        
        # prefix = cls._namespace_prefix(namespace)

        # #attempt to read the target parquet
        # df = pl.read_parquet(path)
        # metadata = pl.read_parquet_metadata(path)

        # if(prefix is not None):
        #     #! select meta entries with prefix (and remove prefix)
        #     metadata = {
        #         k.removeprefix(prefix) : v for k,v in metadata.items()
        #         if k.startswith(prefix)
        #     }
        path = Path(path)
        df = cls.read_df(path)
        meta = cls.read_meta(path, namespace)

        
        # logger.info(
        #     f"{cls.__name__}.read(namespace={None if namespace is None else f'"{namespace}"'}):..."
        #     f"\n - [cyan]df[/] with..."
        #     f"\n   * [green]cols[/]: {df.columns}"
        #     f"\n   * [green]{len(df)}[/] rows"
        #     f"\n - [cyan]to path[/]:"
        #     f"\n   * [green]provided[/]: {path}"
        #     f"\n   * [green]resolved[/]: {path.resolve()}"
        #     f"\n - [cyan]metadata[/]: {meta if meta is None else f"\n{textwrap.indent(pformat(meta), " "*3)}"}"
        # )

        return (df, meta)
    #
    
 
 
 #


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from fxt.term import hr
    from rich import print
    from rich.panel import Panel

    import numpy as np
    from datetime import datetime, timedelta
    import random

    def make_sample_df(n: int|None = None, seed: int = 0) -> pl.DataFrame:
        """ Generates a df with `n` rows using `numpy`'s random values
        """
        if(n is None):
            n = random.randint(1000,2000)
        #

        rng = np.random.default_rng(seed)
        start = datetime(2024, 1, 2)
        mid = 1.10 + np.cumsum(rng.normal(0, 1e-5, n))
        spread = 2e-5
        return pl.DataFrame(
            {
                "dtime": [start + timedelta(milliseconds=int(i * 250)) for i in range(n)],
                "bid": mid - spread / 2,
                "ask": mid + spread / 2,
                "bidVolume": rng.uniform(0.5, 5.0, n),
                "askVolume": rng.uniform(0.5, 5.0, n),
            }
        ).with_columns(pl.col("dtime").cast(pl.Datetime("ms")))
    #

    #setup inputs
    TEST_OUTPUT_ROOT = Path(".tmp/ParquetStore")
    
    #print(df)
    
    def test_write_nometa(dry=True):
        """
        """
        df = make_sample_df()
        
        path = ParquetStore.write(
            df, 
            TEST_OUTPUT_ROOT / "test-write-(no-meta).parquet",
            dry=dry
        )

        logger.debug(f"test_write_nometa(): created {path}")
    #
    #test_write_nometa(False)

    def test_write_withmeta(dry=True):
        """
        """
        df = make_sample_df()

        meta:dict[str,str] = {
            "id": "spiffyid",
            "data": "spiffydata",
            "created-on": datetime.now().isoformat()
        }

        path = ParquetStore.write(
            df, 
            TEST_OUTPUT_ROOT / "test-write-(with-meta).parquet",
            metadata=meta,
            dry=dry
        )

        logger.debug(f"test_write_nometa(): created {path}")
    #
    #test_write_withmeta(dry=True)
    #test_write_withmeta(dry=False)

    def test_read():
        """
        """
        dir = Path("/home/tony/cloud/.rclone-sync/code/python/.jupyter-pixi/downloads/EURJPY/TICK/2023/01/")

        file = dir / "EURJPY-2023-01-01.parquet"
        
        #path:Path = Path(TEST_OUTPUT_ROOT / "test-write-(with-meta).parquet")

        #path:Path = Path(TEST_OUTPUT_ROOT / "test-write-(no-meta).parquet")
        df, meta = ParquetStore.read(file)

        #allmeta = ParquetStore.read_meta(file, namespace="")
        print(f"ALL META:\n{pformat(meta)}")


    def test_polars_metadata_keyword_1():
        """ You want this to print True!!
            v1.42.1 is fine
        """
        import inspect, polars as pl
        print(pl.__version__)
        print("metadata" in inspect.signature(pl.LazyFrame.sink_parquet).parameters)
    #
    test_polars_metadata_keyword_1()

    def test_polars_metadata_keyword_2():
        """ Roundtrip test
        """
        s = ""
        good = "[green]True/Passed[/]"
        bad = "[red]False/Failed[/]"

        lf = make_sample_df().lazy()
        p = ParquetStore.write(lf, TEST_OUTPUT_ROOT / "lazy-meta.parquet", metadata={"id": "x"})
        s += f"Testing read_meta(p) [bold]with[/] meta: {good if(ParquetStore.read_meta(p) == {"id": "x"}) else bad}"
        assert ParquetStore.read_meta(p) == {"id": "x"}
        
        p = ParquetStore.write(lf, TEST_OUTPUT_ROOT / "lazy-nometa.parquet")   # metadata=None path
        s += f"\nTesting read_meta(p) [bold]WITHOUT[/] meta: {good if(ParquetStore.read_meta(p) == {}) else bad}"
        assert ParquetStore.read_meta(p) == {}

        print(Panel(s, title="polars meta test", title_align="left"))
        
    #
    test_polars_metadata_keyword_2()