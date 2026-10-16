#=================================================================================(80)
#   fxt.download.cli ~ fxt-download EURUSD tick 2024-01-01 2024-02-01
#=================================================================================(80)
from __future__ import annotations

import argparse
import inspect
import logging
import sys
from datetime import datetime
from pathlib import Path

from fxt.download.api import download_range


def _parse_dt(text: str) -> datetime:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid date '{text}' (use ISO format, e.g. 2024-01-31 or 2024-01-31T12:00)"
        )
#

def _setup_logging(verbose: bool) -> None:
    """ Apps use loguru; the library only uses stdlib logging. Route both through
    tqdm.write so log lines never tear the progress bar.
    """
    from loguru import logger
    from tqdm import tqdm

    logger.remove()
    logger.add(
        lambda msg: tqdm.write(msg, end="", file=sys.stderr),
        level="DEBUG" if verbose else "INFO",
        colorize=sys.stderr.isatty(),
    )

    class InterceptHandler(logging.Handler):
        """ Standard loguru recipe: forward stdlib log records to loguru.
        """
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level: str | int = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            frame, depth = inspect.currentframe(), 0
            while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
                frame = frame.f_back
                depth += 1
            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
#

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="fxt-download",
        description="Download historical Dukascopy data as one parquet file per UTC day.",
    )
    p.add_argument("symbol", help="instrument, e.g. EUR/USD")
    p.add_argument("interval", help="interval, e.g. tick")
    p.add_argument("start", type=_parse_dt, help="start (UTC, inclusive), e.g. 2024-01-01")
    p.add_argument("end", type=_parse_dt, help="end (UTC, exclusive), e.g. 2024-02-01")
    p.add_argument("-o", "--out", type=Path, default=Path("data"), help="output root (default: data)")
    p.add_argument("-w", "--workers", type=int, default=1, help="parallel days (default: 1)")
    p.add_argument("--max-retries", type=int, default=5, help="fetch attempts per day (default: 5)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    _setup_logging(args.verbose)
    from loguru import logger

    try:
        summary = download_range(
            args.symbol, args.interval, args.start, args.end,
            out_dir=args.out, workers=args.workers, max_retries=args.max_retries,
        )
    except ValueError as e:  #bad symbol/interval/range
        p.error(str(e))

    logger.info("Done: {}", summary)
    for r in summary.failed:
        logger.error("  failed {}: {}", r.chunk.day, r.error)

    if summary.interrupted:
        return 130
    return 1 if summary.failed else 0
#


if __name__ == "__main__":
    raise SystemExit(main())