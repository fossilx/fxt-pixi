#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
"""
Context handed to lake jobs (builders) and to the checks that verify them.

    ctx = JobContext(key=key, src=src_path, dst=out_path)   # log/report default to no-ops
    build_1min(ctx)
    report = run_checks(checks, ctx)
    ctx.close()

UIs (e.g. the lake picker) pass their own `log` / `report` callables to show
progress; scripts and tests can leave them as no-ops.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Callable

from fxt.core.checks import CheckResult
from fxt.lake.paths import PartitionKey

LogFn    = Callable[[str], None]
ReportFn = Callable[[str, CheckResult], None]   # ad-hoc result from inside a job

def _noop_log(msg: str) -> None: ...
def _noop_report(name: str, result: CheckResult) -> None: ...


@dataclass
class JobContext:
    key:    PartitionKey                  # partition of the selected (source) file
    src:    Path                          # input file
    dst:    Path | None = None            # output file, if the job writes one
    log:    LogFn = _noop_log
    report: ReportFn = _noop_report
    cache:  dict[str, Any] = field(default_factory=dict)   # shared by checks, e.g. a duckdb connection

    def close(self) -> None:
        """ Close anything closable that checks left in the cache (connections etc.). """
        for v in self.cache.values():
            if callable(getattr(v, "close", None)):
                try:
                    v.close()
                except Exception:
                    pass
        self.cache.clear()
#