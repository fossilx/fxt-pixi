'''
io

Binds a registry to a storage backend: writes data + a VersionedModel to a
medium, and reads the model back.

The backend is anything matching `KVBackend` (structural; no inheritance).
fxt.core.io.parquet_store.ParquetStore already matches it, so for parquet:

    meta_io = VersionedModelIO(registry, ParquetStore(settings=...))
    meta_io.write(df, path, meta)
    meta = meta_io.read_meta_as(path, ConsolidatedDataMeta)

Supporting another medium = write a class with the same two methods.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar

from .envelope import ENVELOPE_KEYS, from_kv, has_envelope, to_kv
from .errors import ModelTypeMismatchError, VersionedModelError
from .model import VersionedModel
from .registry import VersionedModelRegistry

TData_contra = TypeVar("TData_contra", contravariant=True)
TData = TypeVar("TData")
_M = TypeVar("_M", bound=VersionedModel)


class KVBackend(Protocol[TData_contra]):
    """ Low-level medium: writes data with str->str metadata, reads metadata.
        The backend owns namespacing of keys.
    """
    def write(
        self,
        data: TData_contra,
        path: Path | str,
        metadata: dict[str, str] | None = None,
        overwrite: bool = True,
        dry: bool = False,
    ) -> Path: ...

    def read_meta(self, path: Path | str) -> dict[str, str]: ...
#


class VersionedModelIO(Generic[TData]):
    """ Write/read VersionedModel metadata through a KVBackend. """

    def __init__(self, registry: VersionedModelRegistry[Any], backend: KVBackend[TData]):
        self.registry = registry
        self.backend = backend

    #~======================================================================(70)
    #~ writing
    #~----------------------------------------------------------------------(70)
    def write(
        self,
        data: TData,
        path: Path | str,
        model: VersionedModel,
        *,
        extra: dict[str, str] | None = None,
        overwrite: bool = True,
        dry: bool = False,
    ) -> Path:
        """ Write `data` to `path` with `model` stored as the envelope.

            `extra`: optional additional (non-envelope) metadata keys.
        """
        #! fail before touching the disk: the model must be registered, AND
        #! registered in *this* registry, or it couldn't be read back
        typeid = model.get_id()
        if self.registry.get_model(typeid) is not type(model):
            raise ModelTypeMismatchError(
                f"{type(model).__qualname__} is registered as {typeid}, but this "
                f"registry maps {typeid} to a different class."
            )

        kv = to_kv(model)
        if extra:
            clash = ENVELOPE_KEYS & extra.keys()
            if clash:
                raise ValueError(f"`extra` can't use reserved envelope keys: {sorted(clash)}")
            kv = {**extra, **kv}

        return self.backend.write(data, path, metadata=kv, overwrite=overwrite, dry=dry)
    #

    #~======================================================================(70)
    #~ reading
    #~----------------------------------------------------------------------(70)
    def has_meta(self, path: Path | str) -> bool:
        """ True if the file carries an envelope (doesn't validate it). """
        return has_envelope(self.backend.read_meta(path))

    def read_meta(self, path: Path | str) -> VersionedModel:
        try:
            return from_kv(self.registry, self.backend.read_meta(path))
        except (VersionedModelError, ValueError) as e:
            e.add_note(f"file: {path}")
            raise

    def read_meta_as(self, path: Path | str, cls: type[_M]) -> _M:
        """ read_meta() + check it's an instance of `cls` (typed result). """
        model = self.read_meta(path)
        if not isinstance(model, cls):
            raise ModelTypeMismatchError(
                f"{path}: expected {cls.__qualname__}, file holds "
                f"{type(model).__qualname__} ({model.get_id()})"
            )
        return model
#-
