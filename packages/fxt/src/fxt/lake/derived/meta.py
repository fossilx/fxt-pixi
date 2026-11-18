"""
Metadata step for bar files: turns a finished build + its check report into
BarsMeta, and stamps it into the output file.

Flow inside a lake job (LakePicker or a script):

    pre-checks (src) -> build (writes bare dst) -> post-checks (dst) -> stamp

The stamp has to come last because the post-checks read the output file, and
a parquet footer can't be added without rewriting the file. A year of 1MIN
bars is ~370k rows, so the rewrite is cheap.

    def build(ctx):
        remember_build(ctx, build_bars(ctx.src, ctx.dst, ...))

    LakePicker(..., action=build, on_report=stamp_bars)

Rules
- Only a job that built something gets stamped (the build stores its
  BuildResult in ctx.cache). Verify-only runs never touch the file: the meta
  describes the file as it was built.
- Failed checks are stamped too. The meta records every check's status, and
  `meta.passed` is False when any check FAILed or ERRORed; downstream code
  should refuse those files. A bar file with no meta = incomplete build.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from fxt.core.checks import Check, CheckReport, CheckResult, Status
from fxt.core.versioned import TYPE_KEY
from fxt.lake.derived.bars import BuildResult
from fxt.lake.jobs import JobContext
from fxt.lake.models import (
    BarsMeta, CheckRecord, DatasetKey, DerivedMeta, Transform,
    get_meta_io, get_store, input_ref, registry,
)
from fxt.lake.paths import PartitionKey

__all__ = [
    "BUILD_RESULT_KEY", "remember_build", "build_result", "year_period",
    "input_meta_checks", "bars_meta", "stamp_bars",
]

BUILD_RESULT_KEY = "build_result"


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def remember_build(ctx: JobContext, result: BuildResult) -> BuildResult:
    """ Store the build's result where stamp_bars() looks for it. """
    ctx.cache[BUILD_RESULT_KEY] = result
    return result

def build_result(ctx: JobContext) -> BuildResult | None:
    """ The BuildResult this job produced, or None (verify-only / not built). """
    r = ctx.cache.get(BUILD_RESULT_KEY)
    return r if isinstance(r, BuildResult) else None

def year_period(year: int) -> tuple[datetime, datetime]:
    """ Half-open [Jan 1 year, Jan 1 year+1) in UTC: what a yearly file covers. """
    return datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC)

def _default_lake_root() -> Path:
    from fxt.services import get_lake      # lazy: needs the project settings
    return get_lake().root


#!================================================================================(80)
#! pre-check: the input must carry metadata (lineage needs it)
#!--------------------------------------------------------------------------------(80)
def input_meta_checks(group: str = "input") -> list[Check[JobContext]]:
    """ Pre-checks on ctx.src: it carries an fxt metadata envelope, and if that's
        a lake DerivedMeta (e.g. 1MIN bars feeding 1HOUR), its checks passed.
        Without an envelope, stamping the output would fail at input_ref().
    """
    def has_envelope(ctx: JobContext):
        kv = get_store().read_meta(ctx.src)
        typeid = kv.get(TYPE_KEY)
        return typeid is not None, typeid or "no fxt metadata (rebuild/stamp the input first)"

    def derived_passed(ctx: JobContext):
        kv = get_store().read_meta(ctx.src)
        typeid = kv.get(TYPE_KEY)
        if typeid is None:
            return CheckResult(status=Status.SKIP, detail="no fxt metadata")
        if typeid not in registry:       # e.g. ConsolidatedDataMeta@1 on raw ticks
            return CheckResult(status=Status.SKIP, detail=f"{typeid}: not a lake model")
        meta = get_meta_io().read_meta(ctx.src)
        if not isinstance(meta, DerivedMeta):
            return CheckResult(status=Status.SKIP, detail=f"{typeid}: not derived")
        bad = [c.name for c in meta.failed_checks]
        return not bad, f"{typeid}: " + (", ".join(bad) if bad else "all checks ok")

    return [
        Check("carries fxt metadata", has_envelope, group=group),
        Check("input's own checks passed", derived_passed, group=group),
    ]


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
def bars_meta(
    result: BuildResult,
    report: CheckReport,
    lake_root: Path | str,
) -> BarsMeta:
    """ BarsMeta for `result.dst`. Dataset and period come from the dst folders,
        so the meta can't disagree with where the file lives.
    """
    lake_root = Path(lake_root)
    key = PartitionKey.from_path(result.dst.resolve().relative_to(lake_root.resolve()))
    if key.interval != result.interval:
        raise ValueError(f"dst folder says interval={key.interval}, "
                         f"but the build made {result.interval} bars: {result.dst}")
    if key.filename != result.dst.name:
        raise ValueError(f"dst file name {result.dst.name!r} doesn't match its "
                         f"folders (expected {key.filename!r})")

    checks = [CheckRecord.from_result(name, res) for name, res in report.results.items()]
    #! the builder sorts in memory if the pre-checks were bypassed: keep that visible
    checks.append(CheckRecord(
        name="build: input already in time order",
        status="pass" if result.sorted_input else "warn",
        detail="" if result.sorted_input else "input needed an in-memory sort",
    ))

    start, end = year_period(key.year)
    params: dict[str, Any] = {**result.params, "source_interval": result.source_interval}
    return BarsMeta(
        dataset=DatasetKey(source=key.source, market=key.market,
                           symbol=key.symbol, interval=key.interval),
        start=start,
        end=end,
        inputs=(input_ref(result.src, lake_root),),
        transform=Transform(name=result.transform, version=result.version, params=params),
        checks=tuple(checks),
        rows=result.rows,
    )
#

def stamp_bars(
    ctx: JobContext,
    report: CheckReport,
    outcome: Any = None,
    *,
    lake_root: Path | str | None = None,
) -> BarsMeta | None:
    """ LakePicker `on_report` hook: write BarsMeta into the file this job built.

        Returns the meta that was written, or None if the job didn't build
        anything (verify-only, blocked by pre-checks, or the build raised).
        `outcome` is accepted for the hook's signature; the decision is made
        from the stored BuildResult, so fxt doesn't depend on fxtapps.
    """
    result = build_result(ctx)
    if result is None:
        return None
    if ctx.dst is not None and Path(ctx.dst).resolve() != result.dst.resolve():
        raise ValueError(f"build wrote {result.dst}, but the job's dst is {ctx.dst}")

    root = Path(lake_root) if lake_root is not None else _default_lake_root()
    meta = bars_meta(result, report, root)

    df = pl.read_parquet(result.dst, hive_partitioning=False)
    if df.height != result.rows:
        raise ValueError(f"{result.dst}: {df.height} rows on disk, build reported {result.rows}")
    get_meta_io().write(df, result.dst, meta, overwrite=True)   # atomic (tmp + rename)
    ctx.log(f"stamped {meta.get_id()} ({'passed' if meta.passed else 'FAILED checks'})")
    return meta
#
