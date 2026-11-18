'''
fxt.lake.models

Metadata models for files in the lake, and the IO that reads/writes them.

Every model module must be imported here: models register on import, and a
file can only be read back if its model is registered.
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
from ._registry import registry
from .base import BAD_CHECK_STATUSES, CheckRecord, CheckStatus, Component, DatasetKey, FileMeta, utcnow
from .derived import BarsMeta, DerivedMeta, InputRef, Transform
from .store import get_meta_io, get_store, input_ref, sha256_file


__all__ = [
    "registry",
    "BAD_CHECK_STATUSES", "CheckRecord", "CheckStatus", "Component", "DatasetKey",
    "FileMeta", "utcnow",
    "DerivedMeta", "InputRef", "Transform",
    "BarsMeta",
    "get_meta_io", "get_store", "input_ref", "sha256_file",
]
