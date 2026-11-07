""" Utilities for validating, merging and persisting downloader manifest databases.

    written mostly by claude
"""
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

import os
import sqlite3
from pathlib import Path
from typing import Literal
from collections.abc import Sequence
from sqlite_utils import Database
from typing import Any
from collections.abc import Mapping


#apps->shared
#from fxtapps.dataprep.storage import StorageManager
#from fxtapps.dataprep.settings import get_settings

#!================================================================================(80)
#! setup (logging, exceptions, types)
#!--------------------------------------------------------------------------------(80)
from . import logger
#import logging
#logger.setLevel(logging.INFO)



#!================================================================================(80)
#! types
#!--------------------------------------------------------------------------------(80)
Conflict = Literal["latest", "error", "ignore", "replace"]

class SchemaMismatchError(Exception):
    """ Raised when a manifest's table is missing or differs from the reference.
    """
#

class BadManifest(Exception):
    """ Generic bad manifest 
    """


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def _q(name: str) -> str:
    """ Quote an SQL identifier.
    """
    return '"' + name.replace('"', '""') + '"'
#

PathLike = str | Path | Mapping[str, Any]


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class ManifestTools:
    """ Helpers for manifest files that all share one table (e.g. financial_files).

        Every manifest must contain that table with identical fields. The merged
        database gets that table (same DDL, so same PK/defaults/NOT NULLs) plus its indices.

        If `table_name` is None, it is taken from the first manifest, which must
        then contain exactly one table.
    """
    def __init__(
        self,
        table_name: str | None = None,
        recency_column: str = "ingested_at",
    ) -> None:
        self.table_name = table_name          # what the user asked for
        self.resolved_table: str | None = None  # what was actually used

        self.recency_column = recency_column
    #

    # ------------------------------------------------------------------ helpers

    @property
    def ResolvedTable(self) -> str:
        """ The table name actually used by the last validate/merge call.
            Raises ValueError if no manifest has been processed yet.
        """
        if(self.resolved_table is None):
            raise ValueError(
                "ResolvedTable is not set yet: call validate_schemas() or "
                "merge_to_memory() first"
            )
        return self.resolved_table
    #

    #~======================================================================(70)
    #~ helpers
    #~----------------------------------------------------------------------(70)
    @staticmethod
    def _to_path(p: PathLike) -> Path:
        """ Normalize a str / Path / {"path": ...} mapping to a Path.
        """
        if isinstance(p, Mapping):
            p = p["path"]
        return Path(p) #type: ignore
    #

    @classmethod
    def _fix_paths(cls, paths: Sequence[PathLike]) -> list[Path]:
        """ Normalize every entry to a Path (cheap, and a no-op for Paths).
        """
        # rows = []
        # for p in paths:
        #     if(isinstance(p, PathDict)):
        #         rows.append(p)
        #     elif(isinstance(p, dict)):
        #         rows.append(PathDict(**p))
        #     else:
        #         rows.append(PathDict(path=Path(p)))

        # return rows
        return [cls._to_path(p) for p in paths]
    #

    @staticmethod
    def _restore_path(manifest: Path, value: str) -> str:
        """ Turn a manifest-relative file path into one relative to the cwd.

            manifest: path of the manifest db the row came from
            value:    the row's stored path (usually just a filename)
        """
        # join + lexically simplify ("a/b/../c" -> "a/c"); absolute values pass through
        p = Path(os.path.normpath(manifest.parent / value))
        if p.is_absolute():
            try:
                p = p.relative_to(Path.cwd())
            except ValueError:
                pass  # outside the cwd, keep absolute
        return p.as_posix()
    #

    @classmethod
    def _rewrite_row(cls, row: tuple, idx: int, manifest: Path) -> tuple:
        out = list(row)
        if out[idx] is not None:
            out[idx] = cls._restore_path(manifest, str(out[idx]))
        return tuple(out)
    #

    @staticmethod
    def _open_readonly(path:Path) -> Database:
        """ Open a manifest read-only. Expects an already-normalized Path.
        """
        if not path.is_file():
            raise FileNotFoundError(path)
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        return Database(conn)
    #

    # def resolve_table_from_path(self, db: Database) -> str:
    #     """
    #     """

    def resolve_table(self, paths: Sequence[Path]) -> str:
        """ Return the configured table name, or infer it from the first manifest.
        """
        if self.table_name is not None:
            self.resolved_table = self.table_name
            return self.table_name

        
        db = self._open_readonly(paths[0])
        try:
            names = [n for n in db.table_names() if not n.startswith("sqlite_")]
        finally:
            db.close()
        if len(names) != 1:
            raise ValueError(
                f"Cannot infer table name from {paths[0]} (tables: {names or 'none'}); "
                "pass table_name explicitly"
            )

        self.resolved_table = names[0]
        return self.resolved_table
    #

    @staticmethod
    def get_schema(db: Database, table: str) -> dict[str, tuple]:
        """ Return {column: (type, notnull, default, pk_position)} for `table`.
        """
        if table not in db.table_names():
            raise SchemaMismatchError(f"table '{table}' not found")
        return {
            c.name: (c.type.upper(), c.notnull, c.default_value, c.is_pk)
            for c in db[table].columns
        }
    #

    @staticmethod
    def _diff(ref: dict, other: dict) -> list[str]:
        problems = [f"missing column '{c}'" for c in sorted(ref.keys() - other.keys())]
        problems += [f"unexpected column '{c}'" for c in sorted(other.keys() - ref.keys())]
        for c in sorted(ref.keys() & other.keys()):
            if ref[c] != other[c]:
                problems.append(f"column '{c}': {other[c]} != {ref[c]}")
        return problems
    #
    
    #~======================================================================(70)
    #~ helpers
    #~----------------------------------------------------------------------(70)
    @staticmethod
    def GetUniqueValues(memdb:Database, table:str, column:str) -> list[Any]:
        """ Get's the unique values 
        """
        #rows = []
        rows = memdb.execute(f"SELECT DISTINCT {column} FROM {table}").fetchall()
        return [r[0] for r in rows]
    #

    #~======================================================================(70)
    #~ public API
    #~----------------------------------------------------------------------(70)
    def validate_schemas(self, paths: Sequence[PathLike]) -> dict[str, tuple]:
        """ Check every manifest has the table, with the same fields as the first.

            Returns the reference schema; raises SchemaMismatchError listing all problems.
        """
        if not paths:
            raise ValueError("No database paths given")
        paths = self._fix_paths(paths)

        table = self.resolve_table(paths)
        errors: list[str] = []
        reference: dict[str, tuple] | None = None

        for p in paths:
            db = self._open_readonly(p)
            try:
                try:
                    schema = self.get_schema(db, table)
                except SchemaMismatchError as e:
                    errors.append(f"{p}: {e}")
                    continue
            finally:
                db.close()
            if reference is None:
                reference = schema
            else:
                errors += [f"{p}: {m}" for m in self._diff(reference, schema)]

        if errors:
            raise SchemaMismatchError(
                f"Manifest schema problems (reference: {paths[0]}):\n  "
                + "\n  ".join(errors)
            )
        assert reference is not None
        return reference
    #
    def merge_to_memory(
        self,
        paths: Sequence[PathLike],
        on_conflict: Conflict = "latest",
        batch_size: int = 5000,
        path_column: str | None = "path",
    ) -> Database:
        """ Merge all manifests into a new in-memory database.

            Args:
                on_conflict: applies when two rows share the same primary key:
                    "latest"  - keep the row with the greater `recency_column` (ingested_at);
                                ISO-8601 timestamps compare correctly as text
                    "error"   - raise sqlite3.IntegrityError
                    "ignore"  - keep the first row seen
                    "replace" - keep the last row seen

                path_column: column holding file paths stored relative to each manifest.
                         They are rewritten as manifest dir + value, simplified and
                         made relative to the cwd. None disables rewriting.
        """
        if not paths:
            raise ValueError("No database paths given")
        paths = self._fix_paths(paths)


        self.validate_schemas(paths)
        t = self.resolve_table(paths)

        # Build the target table + indices from the first manifest's own DDL.
        first = self._open_readonly(paths[0])
        try:
            table_ddl = first[t].schema
            index_ddl = [
                r[0]
                for r in first.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
                    [t],
                ).fetchall()
            ]
            columns = [c.name for c in first[t].columns]
            pks = first[t].pks #type: ignore
        finally:
            first.close()

        mem = Database(memory=True)
        mem.execute(table_ddl)

        col_sql = ", ".join(_q(c) for c in columns)
        marks = ", ".join("?" for _ in columns)

        #!=====

        path_idx: int | None = None
        if path_column is not None:
            if path_column not in columns:
                raise ValueError(
                    f"no '{path_column}' column to rewrite; pass path_column=None to skip"
                )
            path_idx = columns.index(path_column)

        #!=====

        if on_conflict == "latest":
            if pks == ["rowid"]:
                raise ValueError("'latest' needs a primary key on the manifest table")
            if self.recency_column not in columns:
                raise ValueError(f"no '{self.recency_column}' column for 'latest'")
            sets = ", ".join(
                f"{_q(c)} = excluded.{_q(c)}" for c in columns if c not in pks
            )
            insert = (
                f"INSERT INTO {_q(t)} ({col_sql}) VALUES ({marks}) "
                f"ON CONFLICT ({', '.join(_q(p) for p in pks)}) DO UPDATE SET {sets} "
                f"WHERE excluded.{_q(self.recency_column)} > {_q(t)}.{_q(self.recency_column)}"
            )
        else:
            verb = {
                "error": "INSERT INTO",
                "ignore": "INSERT OR IGNORE INTO",
                "replace": "INSERT OR REPLACE INTO",
            }[on_conflict]
            insert = f"{verb} {_q(t)} ({col_sql}) VALUES ({marks})"

        #!=====

        for p in paths:
            src = self._open_readonly(p)
            try:
                cur = src.execute(f"SELECT {col_sql} FROM {_q(t)}")
                with mem.conn:  # one transaction per source file
                    while batch := cur.fetchmany(batch_size):
                        if path_idx is not None:
                            batch = [self._rewrite_row(r, path_idx, p) for r in batch]
                        mem.conn.executemany(insert, batch)
            finally:
                src.close()
        
        #!=====

        # Indices last, so inserts aren't slowed down.
        for sql in index_ddl:
            mem.execute(sql)
        mem.conn.commit()
        return mem
    #

    @staticmethod
    def write_to_file(db:Database, output_path: str|Path, overwrite:bool = False) -> Path:
        """ Write a (typically in-memory) database to a file on disk.
        """
        output_path = Path(output_path)
        if output_path.exists():
            if not overwrite:
                raise FileExistsError(output_path)
            output_path.unlink()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        db.conn.commit()
        dest = sqlite3.connect(output_path)
        try:
            db.conn.backup(dest)
        finally:
            dest.close()
        return output_path
    #




    #~======================================================================(70)
    #~ ddebugging
    #~----------------------------------------------------------------------(70)
    @staticmethod
    def preview(
        db: Database,
        table: str | None = None,
        head: int | None = 5,
        tail: int | None = None,
        cols: Sequence[str] | None = None,
        order_by: str | None = None,
    ) -> None:
        """ Pretty-print row counts and a sample of rows for a database.

            table    - preview only this table (default: all user tables)
            head     - number of rows from the start (None or 0 to skip)
            tail     - number of rows from the end (None or 0 to skip); shown after
                       the head rows, separated by a rule
            cols     - limit the output to these columns (default: all)
            order_by - optional ordering applied before head/tail, e.g. "ingested_at desc"

            If head + tail covers the whole table, every row is shown once.
        """
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text

        console = Console()

        if table is not None:
            if table not in db.table_names():
                raise SchemaMismatchError(f"table '{table}' not found")
            names = [table]
        else:
            names = [n for n in db.table_names() if not n.startswith("sqlite_")]

        head_n = head or 0
        tail_n = tail or 0

        for name in names:
            tbl = db[name]
            all_cols = [c.name for c in tbl.columns]

            if cols is not None:
                unknown = [c for c in cols if c not in all_cols]
                if unknown:
                    raise SchemaMismatchError(
                        f"table '{name}' has no column(s): {', '.join(unknown)}"
                    )
                show_cols = list(cols)
            else:
                show_cols = all_cols
            select = ", ".join(_q(c) for c in show_cols)

            total = tbl.count
            console.print(
                f"\n[bold]{name}[/bold]: {total:,} rows, {len(all_cols)} columns"
                + (f" (showing {len(show_cols)})" if cols is not None else "")
            )

            if total == 0:
                console.print("  [dim](table is empty)[/dim]")
                continue

            def fetch(limit: int | None = None, offset: int | None = None) -> list[dict]:
                return list(
                    tbl.rows_where(  # noqa: B023
                        select=select, order_by=order_by, limit=limit, offset=offset  # noqa: B023
                    )
                )

            head_rows: list[dict] = []
            tail_rows: list[dict] = []
            if head_n + tail_n >= total:
                #fetch everything, once
                head_rows = fetch()
            else:
                if head_n:
                    head_rows = fetch(limit=head_n)
                if tail_n:
                    tail_rows = fetch(limit=tail_n, offset=total - tail_n)

            grid = Table(show_lines=False, header_style="bold cyan")
            for c in show_cols:
                grid.add_column(c, overflow="fold")

            def add(rows: list[dict]) -> None:
                for row in rows:
                    # Text() so brackets in values aren't parsed as rich markup
                    grid.add_row(*(Text(str(row[c])) for c in show_cols))  # noqa: B023

            add(head_rows)
            #…
            #! to show stuff in between...
            if head_rows and tail_rows:
                # rule between head and tail
                #grid.add_section()

                #add rows: empty - ellipses - empty
                # grid.add_row(*(Text(" ", justify="center") for _ in show_cols))
                # grid.add_row(*(Text("…", justify="center") for _ in show_cols))
                # grid.add_row(*(Text(" ", justify="center") for _ in show_cols))
                for marker in (" ", "…", " "):
                    grid.add_row(*(Text(marker, justify="center") for _ in show_cols))
            #
            add(tail_rows)
            console.print(grid)
    #
#



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from fxt.term import hr, clear, pause
    from rich import print
    from rich.panel import Panel

    from .con import ConsolidatorApp

    manifests = ConsolidatorApp.Find(
        path=Path("datalake/downloads/EURJPY/TICK"),
        #pattern=
        rglob=ConsolidatorApp.MANIFESTS_RGLOB
    )
    print(manifests)

    #------------------------------------------------------------(60)

    tools = ManifestTools()

    #------------------------------------------------------------(60)
    
    print(hr(title="Validating schemas..."))
    valid_schema = tools.validate_schemas(manifests)
    print(valid_schema)

    # pause()
    # clear() 
    
    #------------------------------------------------------------(60)

    memdb = tools.merge_to_memory(manifests, on_conflict="error")

    print(hr("preview: <defaults>"))
    tools.preview(
        memdb
    )
    # pause()
    # clear() 

    print(hr("preview: head=3, tail=3"))
    tools.preview(memdb, head=3, tail=3)


    # pause()
    # clear()

    print(hr("preview: cols=('dataset', 'id', 'path', 'status', 'rows')"))
    tools.preview(memdb, cols=('dataset', 'id', 'path', 'status', 'rows'))

    #------------------------------------------------------------(60)

    target_file = ConsolidatorApp.CONSOLIDATED_DIR / ".tmp" / ConsolidatorApp.CONSOLIDATED_MANIFEST

    print(target_file)
    tools.write_to_file(memdb, target_file)


    # print(hr("preview: head=3, tail=3"))
    # tools.write_to_file(
    #     db=memdb,

    # )


    
    




