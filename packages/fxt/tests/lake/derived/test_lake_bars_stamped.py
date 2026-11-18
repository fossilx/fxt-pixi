"""
Slow: walk the real lake and make sure every bar file in lake/derived carries
BarsMeta that agrees with its folders and passed its checks.

Bar files built before BarsMeta stamping existed (e.g. EURGBP 2014 1MIN) fail
here until they're rebuilt with the bars_1min / bars_1hour apps.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fxt.lake.derived.bars import INTERVALS
from fxt.lake.derived.meta import year_period
from fxt.lake.models import BarsMeta, get_meta_io
from fxt.lake.paths import PartitionKey

pytestmark = pytest.mark.slow


def _bar_files() -> list[tuple[PartitionKey, Path]]:
    from fxt.services import get_lake
    lake = get_lake()
    if not (lake.root / "derived").is_dir():
        return []
    return [(k, p) for k, p in lake.scan("derived") if k.interval in INTERVALS]


BAR_FILES = _bar_files()


@pytest.mark.skipif(not BAR_FILES, reason="no bar files in lake/derived")
@pytest.mark.parametrize("key,path", BAR_FILES, ids=[str(p.name) + f"[{k.interval}]"
                                                     for k, p in BAR_FILES])
def test_bar_file_is_stamped(key: PartitionKey, path: Path):
    io = get_meta_io()
    assert io.has_meta(path), f"{path}: no fxt metadata (built before stamping? rebuild it)"

    meta = io.read_meta_as(path, BarsMeta)
    d = meta.dataset
    assert (d.source, d.market, d.symbol, d.interval) == \
           (key.source, key.market, key.symbol, key.interval)
    assert (meta.start, meta.end) == year_period(key.year)
    assert meta.passed, f"failed checks: {[c.name for c in meta.failed_checks]}"
