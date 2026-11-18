"""
BarsMeta stamping, end to end on a small synthetic lake:

    raw TICK (with a ConsolidatedDataMeta envelope, like real raw files)
      -> 1MIN bars, checked, stamped
      -> 1HOUR bars from the stamped 1MIN, checked, stamped

Runs the same steps LakePicker runs (pre-checks, build, post-checks, on_report),
without the UI.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from fxt.core.checks import Check, CheckReport, run_checks
from fxt.lake.derived import bar_checks as bc
from fxt.lake.derived.bars import BuildResult, build_bars
from fxt.lake.derived.meta import (
    bars_meta, input_meta_checks, remember_build, stamp_bars, year_period,
)
from fxt.lake.jobs import JobContext
from fxt.lake.models import BarsMeta, CheckRecord, DatasetKey, get_meta_io
from fxt.lake.paths import PartitionKey
from fxt.testing import BASE_KEY, RAW_TYPEID, LakeBuilder, make_ticks, quiet


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
@pytest.fixture
def lb(fresh: LakeBuilder) -> LakeBuilder:
    """ A fresh lake holding one enveloped raw tick file (BASE_KEY). """
    fresh.put(fresh.key("TICK"), make_ticks(n=20_000), envelope=RAW_TYPEID)
    return fresh


def _job(lb: LakeBuilder, src_key: PartitionKey, interval: str, pre, post,
         *, build: bool = True) -> tuple[Path, CheckReport, BarsMeta | None]:
    """ What LakePicker._run_one does, minus the UI. Returns (dst, report, meta). """
    src, dst = lb.path(src_key), lb.path(src_key.replace(interval=interval))
    ctx = JobContext(key=src_key, src=src, dst=dst)
    try:
        report = run_checks(pre, ctx)
        if build:
            remember_build(ctx, build_bars(src, dst, source_interval=src_key.interval,
                                           interval=interval, log=quiet))
        report = report.merge(run_checks(post, ctx))
        meta = stamp_bars(ctx, report, "PASSED", lake_root=lb.lake.root)
    finally:
        ctx.close()
    return dst, report, meta


def _build_1min(lb: LakeBuilder, extra_post: list | None = None):
    pre = [bc.placement("src"), input_meta_checks(), bc.raw_tick_checks()]
    post = [bc.placement("dst"), bc.bar_checks(), *(extra_post or [])]
    return _job(lb, lb.key("TICK"), "1MIN", pre, post)


#!================================================================================(80)
#! tests
#!--------------------------------------------------------------------------------(80)
def test_1min_is_stamped_and_reads_back(lb: LakeBuilder):
    dst, report, meta = _build_1min(lb)
    assert report.ok, report.failed
    assert meta is not None and meta.passed

    stored = get_meta_io().read_meta_as(dst, BarsMeta)
    assert stored == meta
    assert stored.get_id() == "BarsMeta@1"
    assert stored.dataset == DatasetKey(source=BASE_KEY.source, market=BASE_KEY.market,
                                        symbol=BASE_KEY.symbol, interval="1MIN")
    assert (stored.start, stored.end) == year_period(BASE_KEY.year)
    assert stored.rows == pl.read_parquet(dst).height > 0
    assert stored.transform.name == "ticks_to_bars"
    assert stored.transform.params["source_interval"] == "TICK"

    (inp,) = stored.inputs
    assert inp.typeid == RAW_TYPEID
    assert inp.path == lb.path(lb.key("TICK")).relative_to(lb.lake.root).as_posix()

    #! every check in the report is recorded, plus the builder's sort flag
    names = {c.name for c in stored.checks}
    assert set(report.results) <= names
    assert "build: input already in time order" in names


def test_stamping_keeps_the_data(lb: LakeBuilder):
    key = lb.key("TICK")
    src, dst = lb.path(key), lb.path(key.replace(interval="1MIN"))
    ctx = JobContext(key=key, src=src, dst=dst)
    remember_build(ctx, build_bars(src, dst, source_interval="TICK", interval="1MIN", log=quiet))
    before = pl.read_parquet(dst)
    stamp_bars(ctx, CheckReport(), lake_root=lb.lake.root)
    after = pl.read_parquet(dst)
    assert before.equals(after)
    assert before.schema == after.schema


def test_1hour_from_stamped_1min(lb: LakeBuilder):
    _build_1min(lb)
    pre = [bc.placement("src", group="1MIN"), input_meta_checks()]
    post = [bc.placement("dst"), bc.bar_checks()]
    _, report, meta = _job(lb, lb.key("1MIN"), "1HOUR", pre, post)

    assert report.ok, report.failed
    assert meta is not None and meta.passed
    assert meta.dataset.interval == "1HOUR"
    assert meta.transform.name == "resample_bars"
    (inp,) = meta.inputs
    assert inp.typeid == "BarsMeta@1"           # lineage points at the 1MIN file
    assert inp.path.endswith(f"interval=1MIN/year={BASE_KEY.year}/{BASE_KEY.filename}")


def test_failed_checks_are_stamped(lb: LakeBuilder):
    always_fails = Check("always fails", lambda ctx: (False, "on purpose"), group="test")
    _, report, meta = _build_1min(lb, extra_post=[always_fails])
    assert not report.ok
    assert meta is not None and not meta.passed
    assert [c.name for c in meta.failed_checks] == ["test/always fails"]
    assert meta.failed_checks[0].detail == "on purpose"


def test_verify_only_does_not_touch_the_file(lb: LakeBuilder):
    dst, _, _ = _build_1min(lb)
    before = dst.stat().st_mtime_ns
    _, _, meta = _job(lb, lb.key("TICK"), "1MIN", [], [bc.bar_checks()], build=False)
    assert meta is None
    assert dst.stat().st_mtime_ns == before


def test_bare_input_fails_the_input_precheck(lb: LakeBuilder):
    #! an unstamped 1MIN file (like the ones built before stamping existed)
    raw, bare = lb.path(lb.key("TICK")), lb.path(lb.key("1MIN"))
    build_bars(raw, bare, source_interval="TICK", interval="1MIN", log=quiet)
    report = run_checks(input_meta_checks(), JobContext(key=lb.key("1MIN"), src=bare))
    assert report.results["input/carries fxt metadata"].status == "fail"


def test_check_record_status_rules():
    assert CheckRecord(name="a", status="warn").ok
    assert CheckRecord(name="a", status="skip").ok
    assert not CheckRecord(name="a", status="fail").ok
    assert not CheckRecord(name="a", status="error").ok


def test_meta_must_match_its_folder(lb: LakeBuilder):
    dst, report, _ = _build_1min(lb)
    res = BuildResult(src=lb.path(lb.key("TICK")), dst=dst, source_interval="TICK",
                      interval="1HOUR", transform="ticks_to_bars", version=1, rows=1)
    with pytest.raises(ValueError, match="interval"):
        bars_meta(res, report, lb.lake.root)
