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
from math import ceil
from datetime import datetime, timezone, UTC
    
import numpy as np
import polars as pl

#fxt
from fxt.data.models import DownloadedDataMeta

#local
from .base import BaseIntervalSchema


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
import logging
logger = logging.getLogger(__name__)




#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class Ticks(BaseIntervalSchema):
    """
    """
    @classmethod
    def schema(cls) -> pl.Schema:
        """
        """
        return pl.Schema({
            #! index must be first
            cls.INDEX: cls.DTIME_TYPE,

            #! rest
            #'symbol': pl.String,
            'bidPrice': pl.Float64,
            'askPrice': pl.Float64,
            'bidVolume': pl.Float64,
            'askVolume': pl.Float64
        })
    #

    @classmethod
    def meta(cls, *args:Any, **kwargs:Any) ->  DownloadedDataMeta:
        """ 
            #this is how this method is called, need a pydantic model that works with these inputs
            meta = interval_schema.meta(
                source=self.source(), #BaseSource 
                symbol=symbol,
                interval=interval,
                start=start,
                end=end,
                status=status
            )

        """
        #if('interval' in kwargs):
        #    logger.warning("A value of ")
        #remove interval if it exists
        #kwargs.pop('interval', None)
        

        #redirect to the parent
        return super().meta(*args, **kwargs)
    #

    @classmethod
    def fake(
        cls,
        start: datetime,
        end: datetime,
        dt: tuple[float, float] = (0.5, 5),
        values: tuple[float, float] = (1.15, 1.5),
        volatility: float = 0.002,
        spread: float = 0.0001,
        volume: tuple[float, float] = (0.1, 10.0),
        seed: int | None = None,
    ) -> pl.DataFrame:
        """ Generates fake tick data that respects `cls.schema()`, for testing.

            dt:         (min, max) seconds between ticks, uniformly random.
            values:     (low, high) range the mid price stays within.
            volatility: random-walk step size, as a fraction of the (high - low) range.
            spread:     typical bid/ask spread in price units (randomized 0.5x - 1.5x).
            volume:     (min, max) for bid/ask volumes.
            seed:       set for reproducible output.

            Naive datetimes are assumed to be UTC.
        """
        rng = np.random.default_rng(seed)

        #~~ time ~~
        def to_ms(d: datetime) -> int:
            if d.tzinfo is None:
                d = d.replace(tzinfo=UTC)
            return int(d.timestamp() * 1000)

        start_ms, end_ms = to_ms(start), to_ms(end)
        if end_ms <= start_ms:
            return pl.DataFrame(schema=cls.schema())

        # generate gaps in chunks until we pass `end` (n isn't known ahead of time)
        mean_ms = (dt[0] + dt[1]) / 2 * 1000
        chunk = max(16, ceil((end_ms - start_ms) / mean_ms * 1.1))
        times: list[np.ndarray] = []
        last = start_ms
        while last < end_ms:
            gaps = np.maximum(1, np.round(rng.uniform(dt[0], dt[1], chunk) * 1000)).astype(np.int64)
            ts = last + np.cumsum(gaps)
            times.append(ts)
            last = int(ts[-1])
        ts = np.concatenate(times)
        ts = ts[ts < end_ms]
        n = len(ts)

        #~~ prices: random walk, reflected so it stays inside `values` ~~
        lo, hi = values
        width = hi - lo
        steps = rng.normal(0, volatility * width, n)
        walk = rng.uniform(lo, hi) + np.cumsum(steps)
        # fold back into [lo, hi] (bounces off the edges instead of clipping)
        folded = np.mod(walk - lo, 2 * width)
        mid = lo + np.where(folded > width, 2 * width - folded, folded)

        half = spread * rng.uniform(0.5, 1.5, n) / 2
        bid = mid - half
        ask = mid + half

        #~~ volumes ~~
        bid_vol = np.round(rng.uniform(*volume, n), 2)
        ask_vol = np.round(rng.uniform(*volume, n), 2)

        #~~ build, matching the schema (order + dtypes) ~~
        df = pl.DataFrame({
            cls.INDEX: ts,
            "bidPrice": bid,
            "askPrice": ask,
            "bidVolume": bid_vol,
            "askVolume": ask_vol,
        })
        return df.select(cls.cols()).cast(cls.schema())
    #
#-



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80) 
if __name__ == '__main__':

    from rich import print
    from rich.panel import Panel

    data_types = [Ticks]

    for d in data_types:
        print(f"\n* [bold]schema type: [green]{d.name()}[/]")
        print(f"- index: {d.index()}")
        print(f"- cols: {d.cols()}")

    #test fake data
    def test_fakdata():
        start = datetime(1990,1,1)
        end = datetime(1990, 1, 2)

        df = Ticks.fake(start, end)

        print(
            Panel(
                f" - start: {start}"
                f"\n - end: {end}"
                f"\n - # rows: {len(df)}",
            title="[cyan bold]df stats:[/]",
            title_align="left"
        ))
        print(df.head())
    #
    test_fakdata()
