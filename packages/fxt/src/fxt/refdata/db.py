# """
# In-memory meta database, built from the SQL files shipped with the package.

# """
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

import sqlite3
from functools import cache
from importlib.resources import files
from typing import Any


#!================================================================================(80)
#! private
#!--------------------------------------------------------------------------------(80)
SQL_FILES = ("meta-db.sql", "meta-db-seed.sql")



#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
@cache
def meta_db() -> sqlite3.Connection:
    """Build the meta database once per process and return the shared connection.

    Treat it as read-only: the SQL files are the source of truth.
    """
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.execute("PRAGMA foreign_keys = ON")
    for name in SQL_FILES:
        con.executescript(files("fxt.refdata").joinpath("sql", name).read_text())
    return con
#

def query(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Run a query and return each row as a dict keyed by column name."""
    cur = meta_db().execute(sql, params)
    columns = [col[0] for col in cur.description]
    return [dict(zip(columns, row)) for row in cur]
#

def dump_meta_db(path: str) -> None:
    """Write the in-memory database to a file (e.g. to browse in DB Browser)."""
    with sqlite3.connect(path) as target:
        meta_db().backup(target)
#


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print
    from rich.panel import Panel
    from fxt.term import hr, clear, pause

    print(Panel(
        "hi2u",
        title="beep boop",
        title_align="left"
    ))