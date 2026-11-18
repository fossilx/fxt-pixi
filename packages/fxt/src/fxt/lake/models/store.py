'''
store

Wires the lake registry to ParquetStore, plus lineage helpers.
'''
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
from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from fxt.core.versioned import TYPE_KEY, MissingEnvelopeError, VersionedModelIO

from ._registry import registry
from .derived import InputRef



#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
if TYPE_CHECKING:
    from fxt.core.io.parquet_store import ParquetStore

#! Built on first use, not on import: importing the models (e.g. just to read a
#! file's meta, or in tests) shouldn't need the project settings loaded.
#! The store's namespace comes from fxt.toml ([parquet_store] namespace="fxt-data").
def get_store() -> ParquetStore:
    from fxt.services import get_parquet_store   # lazy: services pulls in settings
    return get_parquet_store()

@cache
def get_meta_io() -> VersionedModelIO:
    """ The lake registry bound to the project's ParquetStore. """
    return VersionedModelIO(registry, get_store())



#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
def sha256_file(path: Path | str) -> str:
    """
    """
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
#

def input_ref(path: Path | str, lake_root: Path | str) -> InputRef:
    """ Lineage entry for an input file.

        Copies the input's stored type id WITHOUT parsing the model, so this
        works for files whose model isn't in this registry (e.g. raw tick
        files carrying the legacy dataprep ConsolidatedDataMeta@1).
    """
    path = Path(path)
    kv = get_store().read_meta(path)
    if TYPE_KEY not in kv:
        raise MissingEnvelopeError(f"{path}: input file has no '{TYPE_KEY}' metadata")
    rel = path.resolve().relative_to(Path(lake_root).resolve())
    return InputRef(path=rel.as_posix(), typeid=kv[TYPE_KEY], sha256=sha256_file(path))
#

#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print

    print()
    print(f"hi2u ~ from [bold cyan]{Path(__file__).name}~[/]")
    print()

