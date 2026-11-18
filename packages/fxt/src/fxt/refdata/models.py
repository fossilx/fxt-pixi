"""
Pydantic models for the meta database (markets, intervals, symbols, sources).

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
from typing import Any

from pydantic import BaseModel, ConfigDict, PrivateAttr

#local
#from ..settings import get_settings, get_paths


#!================================================================================(80)
#! private
#!--------------------------------------------------------------------------------(80)




#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class MetaModel(BaseModel):
    """
    """
    model_config = ConfigDict(frozen=True, extra="forbid")
#-

class Market(MetaModel):
    """
    """
    name: str
#-

class Interval(MetaModel):
    """
    """
    name: str
    seconds: int | None = None  # None for TICK

    @property
    def is_tick(self) -> bool:
        return self.seconds is None
#-

class Symbol(MetaModel):
    """
    """
    market: str
    name: str  # filesystem-safe form, e.g. EURUSD
    aliases: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        return (self.market, self.name)
#-

class SourceSymbol(MetaModel):
    """
    """
    market: str
    name: str  # canonical name, e.g. EURUSD
    source_symbol: str  # source's spelling, e.g. EUR/USD
#-

class SourceInterval(MetaModel):
    """
    """
    interval_name: str  # canonical, e.g. 1HOUR
    source_interval: str  # source's spelling, e.g. 1H
#-

class Source(MetaModel):
    """
    """
    name: str
    website: str | None = None
    symbols: tuple[SourceSymbol, ...] = ()
    intervals: tuple[SourceInterval, ...] = ()

    # Lookup indexes, built once after validation.
    _by_source_symbol: dict[str, SourceSymbol] = PrivateAttr(default_factory=dict)
    _by_name: dict[str, list[SourceSymbol]] = PrivateAttr(default_factory=dict)
    _to_source_interval: dict[str, str] = PrivateAttr(default_factory=dict)
    _from_source_interval: dict[str, str] = PrivateAttr(default_factory=dict)

    def model_post_init(self, context: Any, /) -> None:
        for entry in self.symbols:
            # Matches the NOCASE uniqueness on source_symbols.
            self._by_source_symbol[entry.source_symbol.casefold()] = entry
            self._by_name.setdefault(entry.name, []).append(entry)
        for entry in self.intervals:
            # Case-sensitive on purpose: some APIs use '1m' (minute) vs '1M' (month).
            self._to_source_interval[entry.interval_name] = entry.source_interval
            self._from_source_interval[entry.source_interval] = entry.interval_name

    # --- symbols ---------------------------------------------------------

    def _symbol_entry(self, name: str, market: str | None) -> SourceSymbol:
        entries = [
            e for e in self._by_name.get(name, []) if market is None or e.market == market
        ]
        if not entries:
            where = f" in market {market!r}" if market else ""
            raise KeyError(f"{self.name}: no symbol {name!r}{where}")
        if len(entries) > 1:
            markets = sorted(e.market for e in entries)
            raise LookupError(
                f"{self.name}: symbol {name!r} exists in several markets {markets}; pass market="
            )
        return entries[0]

    def has_symbol(self, name: str, market: str | None = None) -> bool:
        return any(market is None or e.market == market for e in self._by_name.get(name, []))

    def to_source_symbol(self, name: str, market: str | None = None) -> str:
        """Canonical name -> source spelling, e.g. EURUSD -> EUR/USD."""
        return self._symbol_entry(name, market).source_symbol

    def from_source_symbol(self, source_symbol: str) -> SourceSymbol:
        """Source spelling -> canonical entry (case-insensitive)."""
        try:
            return self._by_source_symbol[source_symbol.casefold()]
        except KeyError:
            raise KeyError(f"{self.name}: unknown source symbol {source_symbol!r}") from None

    def market_of(self, symbol: str) -> str:
        """Market for a symbol given in either the source's spelling or the canonical name.

        The source spelling is unique per source, so it is checked first; a canonical
        name raises LookupError if this source lists it in more than one market.
        """
        entry = self._by_source_symbol.get(symbol.casefold())
        if entry is not None:
            return entry.market
        return self._symbol_entry(symbol, None).market

    # --- intervals -------------------------------------------------------

    def has_interval(self, interval_name: str) -> bool:
        return interval_name in self._to_source_interval

    def to_source_interval(self, interval_name: str) -> str:
        """Canonical interval -> source spelling, e.g. 1HOUR -> 1H."""
        try:
            return self._to_source_interval[interval_name]
        except KeyError:
            raise KeyError(f"{self.name}: unsupported interval {interval_name!r}") from None

    def from_source_interval(self, source_interval: str) -> str:
        """Source spelling -> canonical interval."""
        try:
            return self._from_source_interval[source_interval]
        except KeyError:
            raise KeyError(f"{self.name}: unknown source interval {source_interval!r}") from None
#-


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print

    print()
    print("# [bold green]gogogogogo[/]")

