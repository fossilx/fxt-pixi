#=================================================================================(80)
#   fxt.download.engine ~ UI-agnostic chunked download loop
#=================================================================================(80)
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal

import polars as pl

if TYPE_CHECKING:
    from fxt.data.downloader import DukascopyDownloader
    from fxt.download.progress import Reporter
    from fxt.download.storage import DayStore

logger = logging.getLogger(__name__)

DAY = timedelta(days=1)


#!================================================================================(80)
#! data types
#!--------------------------------------------------------------------------------(80)
@dataclass(frozen=True)
class Chunk:
    """ One whole UTC day: [start, end).
    """
    start: datetime
    end: datetime

    @property
    def day(self) -> date:
        return self.start.date()
#

@dataclass(frozen=True)
class ChunkResult:
    chunk: Chunk
    status: Literal["success", "empty", "failed"]
    rows: int = 0
    error: str | None = None
#

@dataclass
class Summary:
    total: int = 0          #days in the requested range
    skipped: int = 0        #already on disk before this run
    downloaded: int = 0     #days with data written this run
    empty: int = 0          #days with no data (weekends/holidays)
    rows: int = 0
    failed: list[ChunkResult] = field(default_factory=list)
    interrupted: bool = False

    def add(self, r: ChunkResult) -> None:
        if r.status == "success":
            self.downloaded += 1
            self.rows += r.rows
        elif r.status == "empty":
            self.empty += 1
        else:
            self.failed.append(r)
    #

    def __str__(self) -> str:
        s = (
            f"{self.downloaded} downloaded ({self.rows:,} rows), {self.empty} empty, "
            f"{self.skipped} skipped, {len(self.failed)} failed, of {self.total} days"
        )
        return s + (" [interrupted]" if self.interrupted else "")
    #
#


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def _to_utc(value: datetime) -> datetime:
    """ Naive datetimes are assumed to be UTC; aware ones are converted to UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
#

def _floor_day(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)
#

def plan_chunks(start: datetime, end: datetime, now: datetime | None = None) -> list[Chunk]:
    """ Expand [start, end) to whole UTC days, oldest first.

        The current (still-incomplete) UTC day is never planned, so a day on disk
        is always a finished day.
    """
    start, end = _to_utc(start), _to_utc(end)
    if start >= end:
        raise ValueError(f"start ({start}) must be before end ({end})")

    today = _floor_day(_to_utc(now) if now else datetime.now(timezone.utc))
    first = _floor_day(start)
    last_excl = _floor_day(end)
    if last_excl < end:
        last_excl += DAY          #end falls mid-day -> include that day
    last_excl = min(last_excl, today)

    chunks: list[Chunk] = []
    d = first
    while d < last_excl:
        chunks.append(Chunk(d, d + DAY))
        d += DAY
    return chunks
#


#!================================================================================(80)
#! run loop
#!--------------------------------------------------------------------------------(80)
def _fetch_one(downloader: DukascopyDownloader, store: DayStore, chunk: Chunk, index_col: str) -> ChunkResult:
    """ Runs in a worker thread. Never raises; failures come back as a result.
    """
    try:
        df, meta = downloader.download(chunk.start, chunk.end)
        if not df.is_empty():
            #guard against an inclusive end bound so days never overlap
            df = df.filter(
                pl.col(index_col).is_between(chunk.start, chunk.end, closed="left")
            )
        
        if df.is_empty():
            return ChunkResult(chunk, "empty")

        #! DAYSTORE: write the files
        store.write(chunk.day, df, meta)

        return ChunkResult(chunk, "success", rows=df.height)
    
    except Exception as e:
        cause = f" ({e.__cause__!r})" if e.__cause__ else ""
        logger.warning("Day %s failed: %s%s", chunk.day, e, cause)
        return ChunkResult(chunk, "failed", error=f"{e}{cause}")
    #
#


#!================================================================================(80)
#! engine api
#!--------------------------------------------------------------------------------(80)
def run_download(
    downloader: DukascopyDownloader,
    chunks: list[Chunk],
    store: DayStore,
    reporter: Reporter,
    *,
    index_col: str,
    workers: int = 1,
) -> Summary:
    """ Download every chunk not already on disk. Safe to interrupt and rerun.
    """
    pending = [c for c in chunks if not store.is_done(c.day)]
    
    summary = Summary(total=len(chunks), skipped=len(chunks) - len(pending))
    reporter.start(summary.total, summary.skipped)
    
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    futures = [
        pool.submit(_fetch_one, downloader, store, c, index_col)
        for c in pending
    ]

    try:
        for fut in as_completed(futures):
            result = fut.result()

            #! DAYSTORE: update the manfiest
            if result.status != "failed":
                store.record(result.chunk.day, result.status, result.rows)
            
            summary.add(result)
            reporter.chunk_done(result)

    except KeyboardInterrupt:
        summary.interrupted = True
        logger.warning("Interrupted; waiting for in-flight days to finish...")
    
    finally:
        #cancel anything not started; in-flight days finish and are written atomically
        pool.shutdown(wait=True, cancel_futures=True)
        reporter.close()
    
    return summary
#