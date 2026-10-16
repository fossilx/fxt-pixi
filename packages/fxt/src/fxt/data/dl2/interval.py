from __future__ import annotations

import re
from datetime import timedelta

# unit letter -> seconds, ordered largest to smallest for formatting
_UNITS = {"w": 604_800, "d": 86_400, "h": 3_600, "m": 60, "s": 1}
_PATTERN = re.compile(r"(\d+)\s*([wdhms])")

# Dukascopy time units, and the interval strings its fetch() accepts
# (mirrors the INTERVAL_* constants, minus TICK and 1MONTH which a
# timedelta can't represent).
_DUKA_UNITS = {"w": "WEEK", "d": "DAY", "h": "HOUR", "m": "MIN", "s": "SEC"}
_DUKA_FETCH_INTERVALS = {
    "1SEC", "10SEC", "30SEC",
    "1MIN", "5MIN", "10MIN", "15MIN", "30MIN",
    "1HOUR", "4HOUR", "1DAY", "1WEEK",
}


class Interval:
    """Bar/candle interval, built from a string ("5m", "M5", "1h") or a timedelta."""

    def __init__(self, value: str | timedelta):
        if isinstance(value, timedelta):
            self.td = value
        elif isinstance(value, str):
            self.td = self._parse(value)
        else:
            raise TypeError(f"Expected str or timedelta, got {type(value).__name__}")
        if self.td <= timedelta(0):
            raise ValueError("Interval must be positive")
        if self.td.total_seconds() % 1:
            raise ValueError("Sub-second intervals are not supported")

    @staticmethod
    def _parse(text: str) -> timedelta:
        s = text.strip().lower()
        # Accept "5m", "1h30m", and prefix style "m5" / "h1" (MT5/OANDA)
        m = re.fullmatch(r"([wdhms])\s*(\d+)", s)
        if m:
            s = f"{m[2]}{m[1]}"
        parts = _PATTERN.findall(s)
        if not parts or "".join(f"{n}{u}" for n, u in parts) != s.replace(" ", ""):
            raise ValueError(f"Cannot parse interval: {text!r}")
        return timedelta(seconds=sum(int(n) * _UNITS[u] for n, u in parts))

    def _split(self) -> tuple[int, str]:
        """Largest unit that divides evenly, e.g. (5, 'm'), (1, 'h')."""
        secs = int(self.td.total_seconds())
        for unit, size in _UNITS.items():
            if secs % size == 0:
                return secs // size, unit
        raise AssertionError("unreachable")

    def to_str(self, style: str = "suffix") -> str:
        """style: 'suffix' -> '5m', '1h'; 'prefix' -> 'M5', 'H1' (uppercase)."""
        n, unit = self._split()
        return f"{n}{unit}" if style == "suffix" else f"{unit.upper()}{n}"

    # --- dukascopy-python ---------------------------------------------------
    def to_dukascopy(self) -> str:
        """Value for fetch(interval=...), e.g. '5MIN'. Matches INTERVAL_* constants."""
        n, unit = self._split()
        code = f"{n}{_DUKA_UNITS[unit]}"
        if code not in _DUKA_FETCH_INTERVALS:
            raise ValueError(f"Dukascopy fetch() does not support {self} ({code})")
        return code

    def to_dukascopy_live(self) -> tuple[int, str]:
        """(interval_value, time_unit) for live_fetch(), e.g. (5, 'MIN').
        live_fetch resamples ticks itself, so any value is allowed."""
        n, unit = self._split()
        return n, _DUKA_UNITS[unit]

    def __str__(self) -> str:
        return self.to_str()

    def __repr__(self) -> str:
        return f"Interval({self.to_str()!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Interval) and self.td == other.td

    def __hash__(self) -> int:
        return hash(self.td)


if __name__ == "__main__":
    print(Interval("5m"), Interval(timedelta(hours=1)), Interval("M15"))
    print(Interval(timedelta(minutes=90)))               # 90m
    print(Interval(timedelta(days=1)).to_str("prefix"))  # D1
     