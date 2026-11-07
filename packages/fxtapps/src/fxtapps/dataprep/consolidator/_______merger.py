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
from datetime import date #, timedelta
from pathlib import Path
from collections.abc import Callable, Sequence, Mapping
from typing import ClassVar, Any, Literal

import click
import polars as pl
from rich import print
import pprint
import textwrap
from pydantic import BaseModel, Field, ConfigDict, field_serializer, field_validator

#fxt
from fxt.data.parquet_store import ParquetStore
from fxt.registry import RegisteredModel
from fxt.data.models import ModelRegistry
from fxt.data.models import DownloadedDataMeta

#apps->shared
from apps.dataprep.storage import StorageManager
from apps.dataprep.settings import get_settings
from apps.dataprep.logger import logger
#apps->local
from .validation import ValidationContext
from .validation import TValidationResultsMap
from .validation import ValidationRegistry


import os
import sqlite3
import sqlite_utils
from functools import cached_property



#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)
TIME_COL:str = get_settings("TIME_COL") #"dtime"
DOWNLOADS_DIR:str = get_settings("DOWNLOADS_DIR")  #"downloads" #type:ignore
DOWNLOADS_MANIFEST:str = get_settings("DOWNLOADS_MANIFEST")
CONSOLIDATED_DIR:str = get_settings("CONSOLIDATED_DIR")
CONSOLIDATED_MANIFEST:str = get_settings("CONSOLIDATED_MANIFEST")




#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
MANIFEST_PATH_COLUMN:str = "path"

class ManifestMerger(BaseModel):
    """
    """
    manifests:list[str]  #pl.DataFrame
    path_column:str = Field(default=MANIFEST_PATH_COLUMN)
    output_path:Path|str

    @cached_property
    def BaseSchema(self):
        """ Uses the first entry to establish the target schema
        """
        self._get_schema_signature(sqlite_utils.Database(self.manifests[0]))
    #

    @field_validator("manifests", mode="before")
    @classmethod
    def _validate_manifests(cls, v) -> list[str]:
        """
        """
        if(isinstance(v, pl.DataFrame)):
            v = v[cls.path_column].drop_nulls().to_list()
        if(not len(v)):
            raise ValueError("No manifests provided")
        return sorted(v)
    #
    


    
    def _get_schema_signature(self, db: sqlite_utils.Database) -> dict[str, str]:
        """ Extracts a dictionary of {table_name: create_sql} for all user tables.
        """
        rows = db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE"
            " 'sqlite_%' ORDER BY name;"
        ).fetchall()
        return {row[0]: row[1].strip() if row[1] else "" for row in rows}
        #return {row[0]: row[1].strip() if row[1] else "" for row in cursor.fetchall()}
    #

    def check(self, stuff):
        """ This function needs to actually verify the contents.

            I'm not sure what all this will entail.
        """



    def write(self, path:Path|str|None=None):
        """ Saves the db to disk.
        """
        if(path is None):
            path = self.output_path

        #! WRITE TO DISK HERE  
#-




# def _combine_sqlite_databases(df: pl.DataFrame, path_column: str, output_db_path: str|Path, echo:bool=True):
#     """ Validates schemas, combines all databases in memory first,

#         and writes the final result to disk atomically.
#     """
#     paths = sorted(df[path_column].drop_nulls().to_list())
#     if not paths:
#         raise ValueError("No database paths found in the DataFrame.")

#     if(echo):
#         print(f"Found {len(paths)} databases to validate and combine.")



#     # 1. Establish and validate baseline schema from the first database
#     with sqlite3.connect(paths[0]) as baseline_conn:
#         baseline_schema = _get_schema_signature(baseline_conn)

#     if not baseline_schema:
#         raise ValueError(f"Baseline database {paths[0]} contains no user tables.")




#     # Validate all other databases against the baseline schema upfront
#     for db_path in paths[1:]:
#         with sqlite3.connect(db_path) as conn:
#             current_schema = _get_schema_signature(conn)

#         if current_schema != baseline_schema:
#             raise ValueError(
#                 f"Schema mismatch detected in database: {db_path}\n"
#                 f"Tables or structures do not match the baseline database {paths[0]}."
#             )
#     if(echo):
#         print("All schemas verified successfully. Initializing in-memory database...")

#     # 2. Create an in-memory SQLite database
#     mem_conn = sqlite3.connect(":memory:")
#     mem_cursor = mem_conn.cursor()

#     try:
#         # Create the tables in memory using the baseline schema SQL statements
#         for table_name, create_sql in baseline_schema.items():
#             mem_cursor.execute(create_sql)

#         # 3. Attach and ingest records from ALL databases (including the first one)
#         for i, db_path in enumerate(paths, start=1):
#             if(echo):
#                 print(f"Ingesting records ({i}/{len(paths)}): {db_path}")

#             mem_cursor.execute("ATTACH DATABASE ? AS src;", (db_path,))

#             for table_name in baseline_schema:
#                 mem_cursor.execute(f"INSERT INTO main.{table_name} SELECT * FROM src.{table_name};")

#             mem_cursor.execute("DETACH DATABASE src;")

#         mem_conn.commit()

#         # 4. Write the completed in-memory database to disk using the backup API
#         if(echo):
#             print(f"Writing in-memory database to disk: {output_db_path}")
        
#         output_db_path = Path(output_db_path)
#         if os.path.exists(output_db_path):
#             os.remove(output_db_path)

#         with sqlite3.connect(output_db_path) as disk_conn:
#             mem_conn.backup(disk_conn)

#         if(echo):
#             print(f"Successfully created combined database at: {output_db_path}")

#     finally:
#         mem_conn.close()
# #


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from fxt.term import hr
    from rich import print
    from rich.panel import Panel


