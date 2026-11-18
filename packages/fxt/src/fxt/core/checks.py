#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore
"""
Generic verification checks: small named callables run against a context
object, each producing a serializable CheckResult.

Nothing here knows about the lake, bars, or any UI. Each pipeline stage brings
its own context type (e.g. a lake job context with src/dst paths) and its own
checks; this module only defines how a check is declared, run, and reported.

    from fxt.core.checks import Check, CheckResult, Status, run_checks

    def no_nulls(ctx: MyCtx):
        n = ...
        return n == 0, f"{n} rows"

    checks = [Check("no nulls", no_nulls, group="raw"), ...]
    report = run_checks(checks, ctx)
    report.ok            # False if any check FAILed or ERRORed
    report.model_dump()  # JSON-safe, e.g. for parquet meta

A check function may return:
    CheckResult(...)       full control (status, detail, value)
    bool                   True -> PASS, False -> FAIL
    (bool, str)            same, with a detail string
Raising inside a check -> ERROR; run_checks keeps going with the rest.
"""

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar
from collections.abc import Callable, Iterable

from pydantic import BaseModel, ConfigDict, Field

__all__ = [  # noqa: RUF022
    "Status", "BAD_STATUSES", "CheckResult", "CheckFn", "Check",
    "CheckReport", "flatten_checks", "run_checks", "skip_checks",
]




#!================================================================================(80)
#! results
#!--------------------------------------------------------------------------------(80)
class Status(StrEnum):
    PASS  = "pass"
    WARN  = "warn"     # worth seeing, doesn't fail the report
    FAIL  = "fail"     # the check ran and the data is wrong
    ERROR = "error"    # the check itself couldn't run (exception)
    SKIP  = "skip"     # not run, e.g. an earlier stage failed
#

BAD_STATUSES = frozenset({Status.FAIL, Status.ERROR})

Scalar = float | int | str | bool | None


class CheckResult(BaseModel):
    """ Outcome of one check. JSON-safe so it can be stored with the data. """
    model_config = ConfigDict(frozen=True)

    status:   Status
    detail:   str = ""
    value:    Scalar = None          # the measured number etc. (e.g. duplicate fraction)
    duration: float | None = None    # seconds; filled in by Check.run

    @property
    def ok(self) -> bool:
        return self.status not in BAD_STATUSES
#


#!================================================================================(80)
#! checks
#!--------------------------------------------------------------------------------(80)
Ctx = TypeVar("Ctx")
CheckFn = Callable[[Ctx], "CheckResult | bool | tuple[bool, str]"]


@dataclass(frozen=True)
class Check(Generic[Ctx]):
    """ A named check over a context of type Ctx.

        group:     display/grouping label; (group, name) must be unique within a suite
        warn_only: downgrade FAIL to WARN (for things worth flagging but not blocking)
    """
    name:      str
    fn:        CheckFn[Ctx]
    group:     str = ""
    warn_only: bool = False

    @property
    def id(self) -> str:
        return f"{self.group}/{self.name}" if self.group else self.name

    def run(self, ctx: Ctx) -> CheckResult:
        t0 = time.perf_counter()
        try:
            res = _normalize(self.fn(ctx))
        except Exception as exc:
            res = CheckResult(status=Status.ERROR, detail=f"{type(exc).__name__}: {exc}")
        if self.warn_only and res.status is Status.FAIL:
            res = res.model_copy(update={"status": Status.WARN})
        return res.model_copy(update={"duration": time.perf_counter() - t0})
#

def _normalize(r: CheckResult | bool | tuple[bool, str]) -> CheckResult:
    if isinstance(r, CheckResult):
        return r
    if isinstance(r, tuple):
        passed, detail = r
        return CheckResult(status=Status.PASS if passed else Status.FAIL, detail=str(detail))
    if isinstance(r, bool):
        return CheckResult(status=Status.PASS if r else Status.FAIL)
    raise TypeError(f"check returned {type(r).__name__}; expected CheckResult, bool or (bool, str)")
#


def flatten_checks(items: Iterable[Check | Iterable[Check]]) -> list[Check]:
    """ Factories may return a single Check or a list; suites accept both. Also
        enforces unique ids, since results are keyed by them.
    """
    out: list[Check] = []
    for it in items:
        out.extend([it] if isinstance(it, Check) else it)
    ids = [c.id for c in out]
    if dupes := sorted({i for i in ids if ids.count(i) > 1}):
        raise ValueError(f"duplicate check ids (use group= to separate them): {dupes}")
    return out
#


#!================================================================================(80)
#! running
#!--------------------------------------------------------------------------------(80)
class CheckReport(BaseModel):
    """ Results of a suite, in run order, keyed by check id. """
    results: dict[str, CheckResult] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results.values())

    @property
    def failed(self) -> dict[str, CheckResult]:
        return {k: r for k, r in self.results.items() if not r.ok}

    def counts(self) -> dict[Status, int]:
        out: dict[Status, int] = {}
        for r in self.results.values():
            out[r.status] = out.get(r.status, 0) + 1
        return out

    def merge(self, other: "CheckReport") -> "CheckReport":
        return CheckReport(results={**self.results, **other.results})

    def summary(self) -> str:
        """ e.g. 'PASSED  23 pass, 1 warn' """
        parts = ", ".join(f"{n} {s}" for s, n in self.counts().items())
        return f"{'PASSED' if self.ok else 'FAILED'}  {parts}"
#


def run_checks(
    checks:    Iterable[Check[Ctx] | Iterable[Check[Ctx]]],
    ctx:       Ctx,
    *,
    on_start:  Callable[[Check[Ctx]], None] | None = None,
    on_result: Callable[[Check[Ctx], CheckResult], None] | None = None,
) -> CheckReport:
    """ Run every check (failures don't stop the rest, so you see every problem
        at once). The callbacks let a UI show progress; scripts can ignore them.
    """
    report = CheckReport()
    for c in flatten_checks(checks):
        if on_start:
            on_start(c)
        res = c.run(ctx)
        report.results[c.id] = res
        if on_result:
            on_result(c, res)
    return report
#


def skip_checks(
    checks:    Iterable[Check | Iterable[Check]],
    reason:    str,
    *,
    on_result: Callable[[Check, CheckResult], None] | None = None,
) -> CheckReport:
    """ Record checks as SKIP, e.g. post-build checks when the build was blocked. """
    report = CheckReport()
    for c in flatten_checks(checks):
        res = CheckResult(status=Status.SKIP, detail=reason)
        report.results[c.id] = res
        if on_result:
            on_result(c, res)
    return report
#


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print

    data = {"rows": [1, 2, 2, None]}

    def has_rows(d):    return CheckResult(status=Status.PASS if d["rows"] else Status.FAIL,
                                           detail=f"{len(d['rows'])} rows", value=len(d["rows"]))
    def no_nulls(d):    n = sum(r is None for r in d["rows"]); return n == 0, f"{n} nulls"
    def no_dupes(d):    vals = [r for r in d["rows"] if r is not None]; return len(vals) == len(set(vals))
    def explodes(d):    return 1 / 0

    report = run_checks([
        Check("has rows", has_rows),
        Check("no nulls", no_nulls),
        Check("no dupes", no_dupes, warn_only=True),
        Check("explodes", explodes),
    ], data, on_result=lambda c, r: print(f"{r.status:5}  {c.id:10} {r.detail}"))

    print(report.summary())
    print(report.model_dump_json(indent=2))