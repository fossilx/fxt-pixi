#!/usr/bin/env python3
"""Merge daily tick parquet files found under a directory into a single parquet file.

Works with partial data: whatever files exist are merged. Metadata from the first
file is carried over and updated with info about the merge (file count, rows, range).

Usage:
    python merge_ticks.py downloads/EURUSD/TICK -o EURUSD-merged.parquet
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import click
import polars as pl

log = logging.getLogger(__name__)

# Written by Arrow/Polars automatically; must not be copied into new metadata.
_SKIP_META_KEYS = {"ARROW:schema"}


def find_parquet_files(root: Path, pattern: str = "*.parquet", exclude: Path | None = None) -> list[Path]:
    """Recursively find parquet files, ordered chronologically by filename (SYMBOL-YYYY-MM-DD)."""
    files = [
        p for p in root.rglob(pattern)
        if p.is_file() and (exclude is None or p.resolve() != exclude)
    ]
    return sorted(files, key=lambda p: (p.name, str(p)))


def merge_parquet_files(
    root: Path,
    output: Path,
    sort_by: str | None = "timestamp",
    pattern: str = "*.parquet",
) -> pl.DataFrame:
    root = root.resolve()
    output = output.resolve()

    files = find_parquet_files(root, pattern, exclude=output)
    if not files:
        raise FileNotFoundError(f"No parquet files found under {root}")
    log.info("Found %d parquet files", len(files))

    # Carry over the first file's metadata (e.g. `symbol`).
    meta = {
        k: v for k, v in pl.read_parquet_metadata(files[0]).items()
        if k not in _SKIP_META_KEYS
    }

    df = pl.scan_parquet(files).collect()

    meta.update(
        {
            "files_merged": str(len(files)),
            "first_file": files[0].name,
            "last_file": files[-1].name,
            "merged_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    if sort_by and sort_by in df.columns:
        df = df.sort(sort_by, maintain_order=True)
        meta["first_ts"] = str(df[sort_by][0])
        meta["last_ts"] = str(df[sort_by][-1])
    elif sort_by:
        log.warning("Column %r not found; skipping sort and first/last ts", sort_by)

    meta["rows"] = str(df.height)

    # Write to a temp file first so a failure never leaves a half-written output.
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    df.write_parquet(tmp, compression="zstd", metadata=meta)
    tmp.replace(output)

    log.info("Wrote %s (%d rows from %d files)", output, df.height, len(files))
    return df


@click.command(help="Merge daily tick parquet files under ROOT (recursively) into a single parquet file.")
@click.argument("root", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "-o", "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output parquet path. Default: <ROOT>/../<ROOT name>-merged.parquet",
)
@click.option("--sort-by", default="timestamp", show_default=True, help="Column to sort by.")
@click.option("--pattern", default="*.parquet", show_default=True, help="Glob pattern for input files.")
def main(root: Path, output: Path | None, sort_by: str, pattern: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    root = root.resolve()
    output = output or root.parent / f"{root.name}-merged.parquet"

    try:
        merge_parquet_files(root, output, sort_by=sort_by, pattern=pattern)
    except FileNotFoundError as e:
        raise click.ClickException(str(e)) from e


if __name__ == "__main__":
    main()
