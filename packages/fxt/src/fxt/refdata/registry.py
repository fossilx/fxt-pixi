"""
Read-only, keyed collections of meta models.
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
from collections.abc import Hashable, Iterator, KeysView, Mapping
from typing import Generic, TypeVar

from pydantic import BaseModel

#local
#from ..settings import get_settings, get_paths
from .models import Symbol


#!================================================================================(80)
#! private
#!--------------------------------------------------------------------------------(80)
K = TypeVar("K", bound=Hashable)
M = TypeVar("M", bound=BaseModel)


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class Registry(Generic[K, M]):
    """An immutable mapping of key -> model with clearer errors than a dict."""

    def __init__(self, kind: str, items: Mapping[K, M]) -> None:
        self._kind = kind
        self._items: dict[K, M] = dict(items)

    def get(self, key: K) -> M:
        try:
            return self._items[key]
        except KeyError:
            raise KeyError(f"unknown {self._kind}: {key!r}") from None

    def __getitem__(self, key: K) -> M:
        return self.get(key)

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __iter__(self) -> Iterator[M]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def keys(self) -> KeysView[K]:
        return self._items.keys()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._kind}, {len(self)} items)"


class SymbolRegistry(Registry[tuple[str, str], Symbol]):
    """Symbols keyed by (market, name), with name/alias resolution."""

    def __init__(self, items: Mapping[tuple[str, str], Symbol]) -> None:
        super().__init__("symbol", items)
        # casefolded name or alias -> {(market, name): Symbol}
        self._lookup: dict[str, dict[tuple[str, str], Symbol]] = {}
        for sym in self:
            for text in (sym.name, *sym.aliases):
                self._lookup.setdefault(text.casefold(), {})[sym.key] = sym

    def resolve(self, text: str, market: str | None = None) -> Symbol:
        """Find a symbol by name or alias (case-insensitive).

        Pass `market` when the same name or alias exists in several markets.
        """
        matches = [
            sym
            for sym in self._lookup.get(text.casefold(), {}).values()
            if market is None or sym.market == market
        ]
        if not matches:
            where = f" in market {market!r}" if market else ""
            raise KeyError(f"unknown symbol or alias {text!r}{where}")
        if len(matches) > 1:
            markets = sorted(sym.market for sym in matches)
            raise LookupError(
                f"{text!r} matches symbols in several markets {markets}; pass market="
            )
        return matches[0]

    def in_market(self, market: str) -> list[Symbol]:
        return [sym for sym in self if sym.market == market]



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print

    print()
    print("# [bold green]gogogogogo[/]")

