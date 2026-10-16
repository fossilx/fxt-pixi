from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, ClassVar

from interval import Interval  # the broker-agnostic value type from before


class UnsupportedInterval(ValueError):
    pass


class IntervalMap:
    """Data-driven translation between Interval and one broker's strings."""

    def __init__(self, mapping: dict[str, str]):
        self._enc = {Interval(k): v for k, v in mapping.items()}
        self._dec = {v: k for k, v in self._enc.items()}

    def encode(self, interval: Interval) -> str:
        try:
            return self._enc[interval]
        except KeyError:
            raise UnsupportedInterval(
                f"{interval} not supported; choose from {sorted(map(str, self._enc))}"
            ) from None

    def decode(self, native: str) -> Interval:
        return self._dec[native]

    @property
    def supported(self) -> list[Interval]:
        return sorted(self._enc, key=lambda i: i.td)


class DataSource(ABC):
    name: ClassVar[str]
    intervals: ClassVar[IntervalMap]
    registry: ClassVar[dict[str, type[DataSource]]] = {}

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if hasattr(cls, "name"):
            DataSource.registry[cls.name] = cls

    def download(
        self,
        symbol: str,
        interval: Interval | str | timedelta,
        start: datetime,
        end: datetime,
    ) -> Any:
        """ Template method: normalize + translate once, so subclasses only
            ever see broker-native values.
            
            https://refactoring.guru/design-patterns/template-method/python/example 
        """
        if not isinstance(interval, Interval):
            interval = Interval(interval)
        return self._download(symbol, self.intervals.encode(interval), start, end)

    @abstractmethod
    def _download(self, symbol: str, interval: str, start: datetime, end: datetime) -> Any:
        """symbol/interval are already in the broker's own vocabulary."""


class Dukascopy(DataSource):
    name = "dukascopy"
    intervals = IntervalMap({
        "1s": "1SEC", "10s": "10SEC", "30s": "30SEC",
        "1m": "1MIN", "5m": "5MIN", "10m": "10MIN", "15m": "15MIN", "30m": "30MIN",
        "1h": "1HOUR", "4h": "4HOUR", "1d": "1DAY", "1w": "1WEEK",
    })

    def _download(self, symbol, interval, start, end):
        import dukascopy_python as dc
        # symbol -> INSTRUMENT_* lookup would go here
        return dc.fetch(symbol, interval, dc.OFFER_SIDE_BID, start, end)


# Usage:
#   src = DataSource.registry["dukascopy"]()
#   src.download(instrument, "5m", start, end)
#   src.download(instrument, timedelta(hours=1), start, end)
