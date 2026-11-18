"""
fxt.testing

Test helpers shared by every package's tests (fxt, fxtapps, ...): synthetic
tick data and throwaway lakes. Lives in the package rather than a conftest.py
because pytest doesn't share conftests between sibling test trees; each
package's conftest wraps these in fixtures.

    from fxt.testing import BASE_KEY, LakeBuilder, make_ticks, quiet

    lb = LakeBuilder(tmp_path / "lake")
    raw = lb.put(lb.key("TICK"), make_ticks(n=5_000), envelope=RAW_TYPEID)

No pytest import here, so this module is safe to import anywhere.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import polars as pl

from fxt.lake.paths import Lake, PartitionKey

__all__ = ["BASE_KEY", "RAW_TYPEID", "LakeBuilder", "build_stamped_bars", "make_ticks", "quiet"]

BASE_KEY = PartitionKey(source="dukascopy", market="forex", symbol="EURGBP",
                        interval="TICK", year=2014)

#! what real raw tick files carry (copied from the consolidated tier); the lake
#! registry doesn't know this model, which is exactly the real situation
RAW_TYPEID = "ConsolidatedDataMeta@1"

quiet = lambda msg: None    # noqa: E731  (log sink for builds)


#!================================================================================(80)
#! data
#!--------------------------------------------------------------------------------(80)
def make_ticks(n: int = 250_000, seed: int = 7, start: str = "2014-01-06",
               mean_gap_ms: float = 4500) -> pl.DataFrame:
    """ Weekday ticks in the raw schema (dtime, bidPrice, askPrice, bidVolume, askVolume).

        Built to exercise the awkward cases real data has: irregular spacing,
        ~3% same-millisecond ties, weekend gaps, a random-walk price.
        Defaults give ~2 weeks; the span is roughly n * mean_gap_ms (before
        dropping weekends). `start` sets the year the file belongs to.
    """
    rng = np.random.default_rng(seed)
    gaps = rng.exponential(mean_gap_ms, n).astype("int64")
    gaps[rng.random(n) < 0.03] = 0                                   # same-millisecond ties
    t = np.datetime64(f"{start}T00:00:00", "ms") + np.cumsum(gaps).astype("timedelta64[ms]")
    mid = 0.83 + np.cumsum(rng.normal(0, 2e-5, n))
    spread = np.round(rng.uniform(0.6e-4, 2.5e-4, n), 6)
    bid = np.round(mid - spread / 2, 5)
    return (
        pl.DataFrame({
            "dtime": t,
            "bidPrice": bid,
            "askPrice": np.round(bid + spread, 5),
            "bidVolume": np.round(rng.uniform(0.1, 5, n), 2),
            "askVolume": np.round(rng.uniform(0.1, 5, n), 2),
        })
        .filter(pl.col("dtime").dt.weekday() <= 5)                   # Mon=1 .. Fri=5: real weekend gaps
    )


#!================================================================================(80)
#! lakes
#!--------------------------------------------------------------------------------(80)
class LakeBuilder:
    """ Puts files at their proper hive paths, so placement checks see real lake paths. """

    def __init__(self, root: Path):
        self.lake = Lake(root=root)

    @staticmethod
    def key(interval: str = "TICK", **changes) -> PartitionKey:
        return BASE_KEY.replace(interval=interval, **changes)

    def path(self, key: PartitionKey) -> Path:
        make = self.lake.raw if key.interval == "TICK" else self.lake.derived
        p = make(**key.model_dump(), filename=key.filename, must_exist=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put(self, key: PartitionKey, data: pl.DataFrame | Path,
            envelope: str | None = None) -> Path:
        """ Write (or copy) a file into place.

            envelope: a type id (e.g. RAW_TYPEID) to stamp a minimal fxt metadata
            envelope through the project's ParquetStore, like real raw files have.
            Only valid with a DataFrame.
        """
        p = self.path(key)
        if envelope is not None:
            if isinstance(data, Path):
                raise TypeError("envelope= needs a DataFrame, not a file to copy")
            from fxt.lake.models import get_store    # lazy: needs the project settings
            get_store().write(data, p, metadata={"type": envelope, "json": "{}"})
        elif isinstance(data, Path):
            shutil.copy(data, p)
        else:
            data.write_parquet(p)
        return p
#


def build_stamped_bars(lb: LakeBuilder, ticks: pl.DataFrame,
                       intervals: tuple[str, ...] = ("1MIN", "1HOUR")) -> dict[int, dict[str, Path]]:
    """ Split `ticks` by UTC year, put each year as an enveloped raw file, then
        build and stamp each bar interval from the previous one (TICK -> 1MIN -> 1HOUR),
        the way the bar CLIs do. Returns {year: {interval: path}}.
    """
    from fxt.core.checks import CheckReport                      # lazy: needs the project settings
    from fxt.lake.derived.bars import build_bars
    from fxt.lake.derived.meta import remember_build, stamp_bars
    from fxt.lake.jobs import JobContext

    out: dict[int, dict[str, Path]] = {}
    years = ticks.get_column("dtime").dt.year().unique().sort().to_list()
    for year in years:
        part = ticks.filter(pl.col("dtime").dt.year() == year)
        key = lb.key("TICK", year=year)
        paths = {"TICK": lb.put(key, part, envelope=RAW_TYPEID)}
        prev = key
        for interval in intervals:
            src, dst = lb.path(prev), lb.path(prev.replace(interval=interval))
            ctx = JobContext(key=prev, src=src, dst=dst)
            remember_build(ctx, build_bars(src, dst, source_interval=prev.interval,
                                           interval=interval, log=quiet))
            stamp_bars(ctx, CheckReport(), lake_root=lb.lake.root)
            ctx.close()
            paths[interval] = dst
            prev = prev.replace(interval=interval)
        out[year] = paths
    return out
#
