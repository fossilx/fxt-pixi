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
#from typing import ClassVar
#from functools import cached_property

import polars as pl
from pydantic import BaseModel, ConfigDict
#from rich import print
#from pprint import pformat


#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)
import logging
logger = logging.getLogger(__name__)

class ParquetStoreSettings(BaseModel):
    model_config = ConfigDict(
        # typos in the TOML become errors
        extra="forbid", 

        #allows use of dashs in the toml var name
        populate_by_name=True,
        alias_generator=lambda s: s.replace("_", "-")
    )  
    namespace: str
#


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def _namespace_prefix(ns:str|None) -> str:
    """
    """
    return f"{ns}:" if ns else ""
#
def _prepare_write(
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
        logger.debug(f"ParquetStore ~ file already exists, overwrite={overwrite}; path: {path}")
        if not overwrite:
            raise FileExistsError(f"Failed to write to disk; file already exists: {path}")

    ns = _namespace_prefix(namespace)
    if metadata is not None and len(ns):
        metadata = {f"{ns}{k}": v for k, v in metadata.items()}
    return path, metadata
#


#!================================================================================(80)
#! api: writing
#!--------------------------------------------------------------------------------(80)
def write_lf(
    lf: pl.LazyFrame,
    path:Path|str,
    metadata:dict[str, str]|None = None,
    namespace: str|None = None,
    overwrite:bool = True,
    dry:bool = False
) -> Path:
    """ Specifically for lazy frames.
    """
    path, metadata = _prepare_write(path, metadata, namespace, overwrite)

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

def write_df(
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
    path, metadata = _prepare_write(path, metadata, namespace, overwrite)
    
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

    return path
#

def write(
    data: pl.DataFrame|pl.LazyFrame,
    path:Path|str,
    metadata:dict[str, str]|None = None,
    namespace: str|None = None,
    overwrite:bool = True,
    dry:bool = False
) -> Path:
    """ General write method that writes using either write_parquet or sink_parquet
        accordingly.
    """
    if(isinstance(data, pl.DataFrame)):
        return write_df(data, path, metadata, namespace, overwrite, dry)
    elif(isinstance(data, pl.LazyFrame)):
        return write_lf(data, path, metadata, namespace, overwrite, dry)
    else:
        raise TypeError("Bad type for df - must be pl.DataFrame, or pl.LazyFrame")
    #
#


#!================================================================================(80)
#! api: reading
#!--------------------------------------------------------------------------------(80)
def read_lazyframe(path:Path|str) -> pl.LazyFrame:
    """ Reading a lazy frame.
    """
    path = Path(path)
    return pl.scan_parquet(path)
#
def read_dataframe(path:Path|str) -> pl.DataFrame:
    """ Reading a data frame.
    """
    path = Path(path)
    return pl.read_parquet(path)
#
def read_meta(path:Path|str, namespace:str|None = None) -> dict[str,str]:
    """ This reads in the metadata and (optionally) filters for the corresponding namespace.
        
        To get all meta values, set `namespace=""`
    """
    path = Path(path)
    metadata:dict = dict(pl.read_parquet_metadata(path))

    ns = _namespace_prefix(namespace)
    if(len(ns)):
        #! select meta entries with prefix (and remove prefix)
        metadata = {
            k.removeprefix(ns) : v for k,v in metadata.items()
            if k.startswith(ns)
        }

    return metadata
#

def read(path: Path|str, namespace:str|None = None) -> tuple[pl.DataFrame, dict[str, str]]:
    """ Returns (df, meta). If a namespace is provided, it only returns values with
        that namespace in front.
    """
    path = Path(path)
    df = read_dataframe(path)
    meta = read_meta(path, namespace)
    return (df, meta)
#

#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class ParquetStore(BaseModel):
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
    settings:ParquetStoreSettings


    #~======================================================================(70)
    #~ namespaces
    #~----------------------------------------------------------------------(70)
    # @cached_property
    # def NamespacePrefix(self):
    #     """
    #     """
    #     if(not len(self.settings.namespace)):
    #         return ""
    #     return f"{self.settings.namespace}:"
    # #

    #~======================================================================(70)
    #~ api wrappers
    #~----------------------------------------------------------------------(70)
    def write(
        self,
        data: pl.DataFrame|pl.LazyFrame,
        path:Path|str,
        metadata:dict[str, str]|None = None,
        overwrite:bool = True,
        dry:bool = False
    ):
        """
        """
        return write(
            data=data,
            path=path,
            metadata=metadata,
            namespace=self.settings.namespace,
            overwrite=overwrite,
            dry=dry
        )
    #

    #~======================================================================(70)
    #~ reading
    #~----------------------------------------------------------------------(70)
    def read_lf(self, path:Path|str) -> pl.LazyFrame:
        """
        """
        return read_lazyframe(path)
    #
    def read_df(self, path:Path|str) -> pl.DataFrame:
        """
        """
        return read_dataframe(path)
    #
    def read_meta(self, path:Path|str) -> dict[str,str]:
        """
        """
        return read_meta(path, namespace=self.settings.namespace)
    #
    
    def read(self, path: Path|str) -> tuple[pl.DataFrame, dict[str, str]]:
        """ Returns (df, meta). If a namespace is provided, it only returns values with
            that namespace in front.
        """
        path = Path(path)
        df = self.read_df(path)
        meta = self.read_meta(path)
        return (df, meta)
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
    from rich.pretty import pprint

    import numpy as np
    from datetime import datetime, timedelta
    import random
    
    from fxt.services import get_parquet_store
    store = get_parquet_store()
    # ParquetStore = ParquetStore(
    #     settings = ParquetStoreSettings(
    #         namespace="fxt-data"
    #     )
    # )
    pprint(store)
    sys.exit()



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
    
    # def test_write_nometa(dry=True):
    #     """
    #     """
    #     df = make_sample_df()
        
    #     path = ParquetStore.write(
    #         df, 
    #         TEST_OUTPUT_ROOT / "test-write-(no-meta).parquet",
    #         dry=dry
    #     )

    #     logger.debug(f"test_write_nometa(): created {path}")
    #
    #test_write_nometa(False)

    # def test_write_withmeta(dry=True):
    #     """
    #     """
    #     df = make_sample_df()

    #     meta:dict[str,str] = {
    #         "id": "spiffyid",
    #         "data": "spiffydata",
    #         "created-on": datetime.now().isoformat()
    #     }

    #     path = ParquetStore.write(
    #         df, 
    #         TEST_OUTPUT_ROOT / "test-write-(with-meta).parquet",
    #         metadata=meta,
    #         dry=dry
    #     )

    #     logger.debug(f"test_write_nometa(): created {path}")
    # #
    # #test_write_withmeta(dry=True)
    #test_write_withmeta(dry=False)

    # def test_read():
    #     """
    #     """
    #     dir = Path("/home/tony/cloud/.rclone-sync/code/python/.jupyter-pixi/downloads/EURJPY/TICK/2023/01/")

    #     file = dir / "EURJPY-2023-01-01.parquet"
        
    #     #path:Path = Path(TEST_OUTPUT_ROOT / "test-write-(with-meta).parquet")

    #     #path:Path = Path(TEST_OUTPUT_ROOT / "test-write-(no-meta).parquet")
    #     df, meta = ParquetStore.read(file)

    #     #allmeta = ParquetStore.read_meta(file, namespace="")
    #     print(f"ALL META:\n{pformat(meta)}")


    # def test_polars_metadata_keyword_1():
    #     """ You want this to print True!!
    #         v1.42.1 is fine
    #     """
    #     import inspect, polars as pl
    #     print(pl.__version__)
    #     print("metadata" in inspect.signature(pl.LazyFrame.sink_parquet).parameters)
    # #
    # test_polars_metadata_keyword_1()

    # def test_polars_metadata_keyword_2():
    #     """ Roundtrip test
    #     """
    #     s = ""
    #     good = "[green]True/Passed[/]"
    #     bad = "[red]False/Failed[/]"

    #     lf = make_sample_df().lazy()
    #     p = ParquetStore.write(lf, TEST_OUTPUT_ROOT / "lazy-meta.parquet", metadata={"id": "x"})
    #     s += f"Testing read_meta(p) [bold]with[/] meta: {good if(ParquetStore.read_meta(p) == {"id": "x"}) else bad}"
    #     assert ParquetStore.read_meta(p) == {"id": "x"}
        
    #     p = ParquetStore.write(lf, TEST_OUTPUT_ROOT / "lazy-nometa.parquet")   # metadata=None path
    #     s += f"\nTesting read_meta(p) [bold]WITHOUT[/] meta: {good if(ParquetStore.read_meta(p) == {}) else bad}"
    #     assert ParquetStore.read_meta(p) == {}

    #     print(Panel(s, title="polars meta test", title_align="left"))
        
    # #
    # test_polars_metadata_keyword_2()


