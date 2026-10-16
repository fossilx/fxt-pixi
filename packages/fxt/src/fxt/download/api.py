#=================================================================================(80)
#   fxt.download.api ~ the one function you call from a notebook or script
#=================================================================================(80)
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

#NOTE: adjust this import to wherever DukascopyDownloader lives in your package
from fxt.data.downloader import DukascopyDownloader
from fxt.data.schemas import Ticks

from fxt.download.engine import Summary, plan_chunks, run_download
from fxt.download.progress import Reporter, TqdmReporter
from fxt.download.storage import DayStore

logger = logging.getLogger(__name__)


def download_range(
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    out_dir: str | Path = "downloads",
    workers: int = 1,
    max_retries: int = 5,
    reporter: Reporter | None = None,
) -> Summary:
    """ Download [start, end) as one parquet file per UTC day.

        - The range is expanded to whole UTC days; naive datetimes are treated as UTC.
        - Today's (incomplete) UTC day is never downloaded.
        - Days already on disk are skipped, so reruns resume where they stopped.
        - Failed days are reported in the returned Summary and retried on the next run.
    """
    downloader = DukascopyDownloader(
        symbol=symbol, interval=interval, max_retries=max_retries
    )
    chunks = plan_chunks(start, end)
    if not chunks:
        logger.info("Nothing to download for %s %s in that range.", downloader.symbol, downloader.interval)

    store = DayStore(out_dir, downloader.symbol, downloader.interval)
    reporter = reporter or TqdmReporter(desc=f"{downloader.symbol} {downloader.interval}")

    return run_download(
        downloader, chunks, store, reporter,
        index_col=Ticks.index(), workers=workers,
    )
#



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from datetime import datetime
    from rich import print

    print("[green]HI2U[/]")
    
    #from fxt.download import download_range
    
    # start = datetime(2024, 1, 1)
    # end = datetime(2024, 2, 1)

    # summary = download_range("EUR/USD", "tick", start=start, end=end)
    # print(summary)