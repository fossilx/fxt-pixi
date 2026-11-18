"""
Contains library reference data: sources, markets, symbols, intervals.

Basically library metadata that was initially stored in registries.
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
from .db import dump_meta_db, meta_db
from .display import format_meta, print_meta
from .loader import clear_caches, intervals, markets, sources, symbols
from .models import Interval, Market, Source, SourceInterval, SourceSymbol, Symbol
from .registry import Registry, SymbolRegistry

__all__ = [
    "Interval",
    "Market",
    "Registry",
    "Source",
    "SourceInterval",
    "SourceSymbol",
    "Symbol",
    "SymbolRegistry",
    "clear_caches",
    "dump_meta_db",
    "format_meta",
    "intervals",
    "markets",
    "meta_db",
    "print_meta",
    "sources",
    "symbols",
]




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from fxt.term import hr, clear, pause

    print()
    print("# [bold green]meta summary[/]")
    print()
    print_meta()
