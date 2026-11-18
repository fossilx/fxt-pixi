"""
Load meta models from the database.

Every loader follows the same shape:
    rows from the db -> dicts (nested lists attached) -> Model.model_validate -> Registry
Each registry is built once per process (cached).
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
from pathlib import Path
from functools import cache
from typing import Any

from pydantic import BaseModel, ConfigDict

#local
from .db import query
from .models import Interval, Market, Source, Symbol
from .registry import Registry, SymbolRegistry



#!================================================================================(80)
#! private
#!--------------------------------------------------------------------------------(80)


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
@cache
def markets() -> Registry[str, Market]:
    """
    """
    rows = query("SELECT name FROM markets ORDER BY name")
    return Registry("market", {r["name"]: Market.model_validate(r) for r in rows})
#

@cache
def intervals() -> Registry[str, Interval]:
    """
    """
    rows = query("SELECT name, seconds FROM intervals ORDER BY seconds IS NOT NULL, seconds")
    return Registry("interval", {r["name"]: Interval.model_validate(r) for r in rows})
#

@cache
def symbols() -> SymbolRegistry:
    """
    """
    data: dict[tuple[str, str], dict[str, Any]] = {
        (r["market"], r["name"]): {**r, "aliases": []}
        for r in query("SELECT market, name FROM symbols ORDER BY market, name")
    }
    for r in query("SELECT market, name, alias FROM symbol_aliases ORDER BY alias"):
        data[(r["market"], r["name"])]["aliases"].append(r["alias"])

    return SymbolRegistry({key: Symbol.model_validate(d) for key, d in data.items()})
#

@cache
def sources() -> Registry[str, Source]:
    """
    """
    data: dict[str, dict[str, Any]] = {
        r["name"]: {**r, "symbols": [], "intervals": []}
        for r in query("SELECT name, website FROM sources ORDER BY name")
    }
    for r in query(
        "SELECT source, market, name, source_symbol FROM source_symbols "
        "ORDER BY source, market, name"
    ):
        source = r.pop("source")
        data[source]["symbols"].append(r)
    for r in query(
        "SELECT source, interval_name, source_interval FROM source_intervals "
        "ORDER BY source, interval_name"
    ):
        source = r.pop("source")
        data[source]["intervals"].append(r)

    return Registry("source", {name: Source.model_validate(d) for name, d in data.items()})


def clear_caches() -> None:
    """ Drop cached registries (and the db), e.g. after editing the SQL files 
        in a session.
    """
    from .db import meta_db

    for fn in (markets, intervals, symbols, sources, meta_db):
        fn.cache_clear()



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print

    print()
    print("# [bold green]gogogogogo[/]")

