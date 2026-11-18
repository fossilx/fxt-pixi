'''
store

Writes and reads research tables: one parquet file per ResearchKey, with its
ResearchMeta stamped in the footer through the project's ParquetStore.

    meta = EventsMeta.for_config(cfg, dataset=ds, year=2020, rows=df.height,
                                 inputs=(file_ref(bars_1h, lake_root=..., research_root=...),),
                                 code_version=code_version())
    path = write_table(df, meta, research=get_research())
    df, meta = read_table(path)

write_table() derives the path from the meta, so a file can't end up in a
folder that disagrees with its metadata. Before writing it checks:
- hash collision: other files already under config=<hash> must hold the
  same config (a 12-char hash makes this astronomically unlikely, but a
  silent mix of two configs in one folder would be very hard to spot)
- row count matches `meta.rows`
- any column named like a folder key (symbol, year, ...) holds only the
  folder's value, so hive reads (DuckDB, polars) can't see two answers
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import subprocess
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from fxt.core.versioned import TYPE_KEY, MissingEnvelopeError, VersionedModelIO
from fxt.lake.models.store import sha256_file

from .models import FileRef, ResearchMeta, registry
from .paths import RESEARCH_KEYS, Research, ResearchKey, Stage

if TYPE_CHECKING:
    from fxt.core.io.parquet_store import ParquetStore

__all__ = [
    "ConfigCollisionError", "code_version", "existing_config", "file_ref",
    "get_meta_io", "get_store", "read_meta", "read_table", "write_table",
]


class ConfigCollisionError(RuntimeError):
    """ Two different configs produced the same hash. """


#!================================================================================(80)
#! wiring
#!--------------------------------------------------------------------------------(80)
#! built on first use, not on import (same reason as fxt.lake.models.store)
def get_store() -> ParquetStore:
    from fxt.services import get_parquet_store
    return get_parquet_store()

@cache
def get_meta_io() -> VersionedModelIO:
    """ The research registry bound to the project's ParquetStore. """
    return VersionedModelIO(registry, get_store())

def _default_research() -> Research:
    from fxt.services import get_research
    return get_research()


#!================================================================================(80)
#! lineage helpers
#!--------------------------------------------------------------------------------(80)
def code_version(repo: Path | str | None = None) -> str | None:
    """ Short git commit of the code, "+dirty" if tracked files have uncommitted
        changes. None if git or the repo isn't available (never raises).
    """
    try:
        if repo is None:
            from fxt.services import get_settings
            repo = get_settings().paths.root
        def run(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10, check=True
            ).stdout.strip()
        sha = run("rev-parse", "--short=12", "HEAD")
        dirty = bool(run("status", "--porcelain", "--untracked-files=no"))
    except Exception:
        return None
    return f"{sha}+dirty" if dirty else sha
#

def file_ref(path: Path | str, *, lake_root: Path | str, research_root: Path | str) -> FileRef:
    """ Lineage entry for an input file in the lake or in research.

        Copies the input's stored type id without parsing it, so any fxt file
        works (bars, raw ticks, other research tables).
    """
    path = Path(path).resolve()
    for root_name, root in (("research", research_root), ("lake", lake_root)):
        try:
            rel = path.relative_to(Path(root).resolve())
        except ValueError:
            continue
        kv = get_store().read_meta(path)
        if TYPE_KEY not in kv:
            raise MissingEnvelopeError(f"{path}: input file has no '{TYPE_KEY}' metadata")
        return FileRef(root=root_name, path=rel.as_posix(), typeid=kv[TYPE_KEY],  # type: ignore[arg-type]
                       sha256=sha256_file(path))
    raise ValueError(f"{path} is in neither the lake ({lake_root}) nor research ({research_root})")
#


#!================================================================================(80)
#! checks
#!--------------------------------------------------------------------------------(80)
def existing_config(research: Research, stage: Stage | str, config_hash: str) -> ResearchMeta | None:
    """ Meta of any file already under <stage>/config=<hash>, or None. """
    base = research.config_dir(stage, config_hash)
    if not base.is_dir():
        return None
    for p in sorted(base.rglob("*.parquet")):
        return read_meta(p)
    return None
#

def _check_partition_columns(df: pl.DataFrame, key: ResearchKey) -> None:
    for k, want in key.parts().items():
        if k not in df.columns or df.height == 0:
            continue
        got = df.get_column(k).cast(pl.String).unique().to_list()
        if got != [str(want)]:
            raise ValueError(f"column {k!r} holds {got[:5]}, but the file goes in {k}={want}")
#


#!================================================================================(80)
#! api
#!--------------------------------------------------------------------------------(80)
def write_table(
    df: pl.DataFrame,
    meta: ResearchMeta,
    *,
    research: Research | None = None,
    overwrite: bool = True,
) -> Path:
    """ Write `df` with `meta` to the path the meta implies. Returns the path. """
    if not isinstance(df, pl.DataFrame):
        raise TypeError(f"write_table needs a polars DataFrame, got {type(df).__name__}")
    research = research or _default_research()
    key = meta.key

    if df.height != meta.rows:
        raise ValueError(f"meta.rows={meta.rows}, but the frame has {df.height} rows")
    _check_partition_columns(df, key)

    other = existing_config(research, key.stage, key.config)
    if other is not None and not other.same_config(meta):
        raise ConfigCollisionError(
            f"{key.stage}/config={key.config} already holds a different config:\n"
            f"  existing: {other.config_typeid} {other.config}\n"
            f"  new:      {meta.config_typeid} {meta.config}"
        )

    path = research.file(key)
    return get_meta_io().write(df, path, meta, overwrite=overwrite)   # atomic (tmp + rename)
#

def read_meta(path: Path | str) -> ResearchMeta:
    """ The file's ResearchMeta (validated: hash integrity is re-checked). """
    return get_meta_io().read_meta_as(path, ResearchMeta)

def read_table(path: Path | str) -> tuple[pl.DataFrame, ResearchMeta]:
    """ (df, meta). Reads the file alone (no hive columns added). """
    meta = read_meta(path)
    return pl.read_parquet(path, hive_partitioning=False), meta
#-
