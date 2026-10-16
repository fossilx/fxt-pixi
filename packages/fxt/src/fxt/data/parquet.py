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
import logging
from datetime import datetime
from pydantic import BaseModel, field_validator, Field
from typing import TypeAlias
from pathlib import Path


import polars as pl
import pyarrow.parquet as pq


#!================================================================================(80)
#! setup (logging, types, etc)
#!--------------------------------------------------------------------------------(80)
from rich.logging import RichHandler
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[RichHandler(rich_tracebacks=True, markup=True)]
)
logger = logging.getLogger(__name__)

#! constants
from fxt import get_env
_METADATA_TYPE_KEY = get_env("PARQUET_METADATA_TYPE_KEY")
_METADATA_JSON_KEY = get_env("PARQUET_METADATA_JSON_KEY")

#!================================================================================(80)
#! main: models
#!--------------------------------------------------------------------------------(80)
#from fxt.data.model_registry import RegisteredModel
from fxt.data.models import ParquetMeta





#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
from typing import Any

class ParquetUtils:
    """ This needs utils that write and load parquet files, and automatically
        handle my meta-data conventions.
    """
    @staticmethod 
    def get_meta(path, key=None) -> dict|None:
        meta = pl.read_parquet_metadata(path)
        return meta.get(key, None)
    #
    
    #TODO: CREATE FUNCTION TO MAKE PARQUET USING df, metatype ("Blah@v1"), metastring (json string)
    #TODO: CREATE A SAMPLE PARQUET WITH THE CORRECT KEYS...using above 
    #~======================================================================(70)
    #~ writing
    #~----------------------------------------------------------------------(70)
    @classmethod
    def write(cls, 
        df:pl.DataFrame,
        path:Path,
        meta:RegisteredModel|None=None,
        #metaType:
        #meta_key, 
        meta_type_key:str=_METADATA_TYPE_KEY,
        meta_json_key:str=_METADATA_JSON_KEY
    ):
        table = df.to_arrow()
        existing_meta = table.schema.metadata or {}

        #need to prepare the values (as a json string) and the type string
        metavalue:str|None = None
        metatype:str|None = None
        metadata = {}
        if(isinstance(meta, RegisteredModel)):
            metatype, metavalue = meta.serialize()

            metadata = {
                meta_type_key: metatype, #should be string like: SpiffyModel@2
                meta_json_key: metavalue #should be a json string
            }

        logger.debug(f"write() using metadata: \n{metadata}")

        #! merge
        merged = {
            **existing_meta,
            **{k.encode(): v.encode() for k,v in metadata.items()}
        }

        #! apply
        table = table.replace_schema_metadata(merged)

        #! write
        #path.parent.mkdir(parents=True, exist_ok=True)
        #pq.write_table(table, path)
        #return path
    #



    #~======================================================================(70)
    #~ reading
    #~----------------------------------------------------------------------(70)
    @classmethod
    def read_meta(cls,
        path:Path,
        meta_type_key:str=_METADATA_TYPE_KEY,
        meta_json_key:str=_METADATA_JSON_KEY
    ):
        """ Reads just the meta without loading all of the data.
        """
        if(not path.is_file()):
            raise ValueError("Specified path is not a valid parquet file.")

        pq_meta = pl.read_parquet_metadata(path)

        #need both keys
        try:
            #metatype = pq_meta.get(meta_type_key, None)
            #metadata = pq_meta.get(meta_json_key, None)
            metatype = pq_meta[meta_type_key]
            metadata = pq_meta[meta_json_key]
        except KeyError:
            raise KeyError(
                "Failed to read parquet metadata; missing required keys. "
                f"\n - has type key ({meta_type_key}): {meta_type_key in pq_meta}; "
                f"\n - has json key ({meta_json_key}): {meta_json_key in pq_meta}"
            )

        #! convert it back to the model using the registry?~!
        #for now return tuple
        return (metatype, metadata)
    #

    @classmethod
    def read_data(cls, path:Path) -> tuple[pl.DataFrame, Any]:
        """
        """
        if(not path.is_file()):
            raise ValueError("Specified path is not a valid parquet file.")

        #! read in data
        df = pl.read_parquet(path)
        

        return (df)

    #
#

#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print
    from fxt.term import pause, clear

    def test_df():
        """
        """
        return pl.DataFrame(
            {
                "dtime": [1, 2, 3],
                "bid": [1.1000, 1.1001, 1.1002],
                "ask": [1.1002, 1.1003, 1.1004],
            }
        )
    #
    def test_meta():
        """ Example meta
        """
        return ParquetMeta(
            interval="TICK",
            source="dukascopy",
            symbol="GBPUSD",
            start=datetime(2025,1,1),
            end=datetime(2026,1,1)
        )
    #
    from fxt.data.model_registry import ModelRegistry

    registry = ModelRegistry()
    df = test_df()
    meta = test_meta

    print(meta.serialize())
    
