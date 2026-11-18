""" fxt.core.checks: declaring, running and reporting checks. """
import json

import pytest

from fxt.core.checks import (
    Check, CheckReport, CheckResult, Status, flatten_checks, run_checks, skip_checks,
)


#!================================================================================(80)
#! Check.run: return-value normalization
#!--------------------------------------------------------------------------------(80)
@pytest.mark.parametrize("ret, status, detail", [
    (True,                                   Status.PASS, ""),
    (False,                                  Status.FAIL, ""),
    ((True, "fine"),                         Status.PASS, "fine"),
    ((False, "3 bad"),                       Status.FAIL, "3 bad"),
    (CheckResult(status=Status.WARN, detail="hm"), Status.WARN, "hm"),
])
def test_return_values_are_normalized(ret, status, detail):
    r = Check("c", lambda ctx: ret).run(None)
    assert (r.status, r.detail) == (status, detail)

def test_exception_becomes_error_with_message():
    r = Check("c", lambda ctx: 1 / 0).run(None)
    assert r.status is Status.ERROR
    assert "ZeroDivisionError" in r.detail

def test_unexpected_return_type_is_error_not_truthy_pass():
    r = Check("c", lambda ctx: "looks truthy").run(None)
    assert r.status is Status.ERROR
    assert "str" in r.detail

def test_warn_only_downgrades_fail_but_not_error():
    assert Check("c", lambda ctx: False, warn_only=True).run(None).status is Status.WARN
    assert Check("c", lambda ctx: 1 / 0, warn_only=True).run(None).status is Status.ERROR

def test_duration_is_recorded():
    r = Check("c", lambda ctx: True).run(None)
    assert r.duration is not None and r.duration >= 0

def test_context_is_passed_through():
    seen = []
    Check("c", lambda ctx: seen.append(ctx) or True).run({"k": 1})
    assert seen == [{"k": 1}]

def test_id_includes_group():
    assert Check("rows", bool).id == "rows"
    assert Check("rows", bool, group="raw").id == "raw/rows"


#!================================================================================(80)
#! suites
#!--------------------------------------------------------------------------------(80)
def test_flatten_accepts_checks_and_lists():
    a, b, c = Check("a", bool), Check("b", bool), Check("c", bool)
    assert flatten_checks([a, [b, c]]) == [a, b, c]

def test_flatten_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate"):
        flatten_checks([Check("a", bool), [Check("a", bool)]])

def test_same_name_in_different_groups_is_fine():
    assert len(flatten_checks([Check("a", bool, group="raw"), Check("a", bool, group="bars")])) == 2

def test_run_checks_runs_everything_in_order_despite_failures():
    order = []
    def mk(name, ret):
        return Check(name, lambda ctx: order.append(name) or ret)
    report = run_checks([mk("a", False), mk("b", True), mk("c", True)], None)
    assert order == ["a", "b", "c"]
    assert list(report.results) == ["a", "b", "c"]

def test_run_checks_callbacks():
    events = []
    run_checks([Check("a", lambda c: True), Check("b", lambda c: False)], None,
               on_start=lambda c: events.append(("start", c.id)),
               on_result=lambda c, r: events.append(("done", c.id, r.status)))
    assert events == [("start", "a"), ("done", "a", Status.PASS),
                      ("start", "b"), ("done", "b", Status.FAIL)]

def test_skip_checks_marks_everything_skipped_with_reason():
    report = skip_checks([Check("a", bool), Check("b", bool)], "blocked")
    assert {r.status for r in report.results.values()} == {Status.SKIP}
    assert {r.detail for r in report.results.values()} == {"blocked"}


#!================================================================================(80)
#! CheckReport
#!--------------------------------------------------------------------------------(80)
def _report(*statuses: Status) -> CheckReport:
    return CheckReport(results={f"c{i}": CheckResult(status=s) for i, s in enumerate(statuses)})

@pytest.mark.parametrize("statuses, ok", [
    ((Status.PASS, Status.WARN), True),
    ((Status.PASS, Status.FAIL), False),
    ((Status.PASS, Status.ERROR), False),
    ((Status.SKIP, Status.SKIP), True),     # nothing failed: callers that need "something ran" check counts()
    ((), True),
])
def test_report_ok(statuses, ok):
    assert _report(*statuses).ok is ok

def test_report_failed_and_counts():
    r = _report(Status.PASS, Status.FAIL, Status.ERROR, Status.PASS)
    assert set(r.failed) == {"c1", "c2"}
    assert r.counts() == {Status.PASS: 2, Status.FAIL: 1, Status.ERROR: 1}

def test_report_merge_keeps_all_and_later_wins():
    a = CheckReport(results={"x": CheckResult(status=Status.PASS), "y": CheckResult(status=Status.PASS)})
    b = CheckReport(results={"y": CheckResult(status=Status.FAIL), "z": CheckResult(status=Status.PASS)})
    m = a.merge(b)
    assert list(m.results) == ["x", "y", "z"]
    assert m.results["y"].status is Status.FAIL

def test_report_summary():
    assert _report(Status.PASS, Status.PASS, Status.WARN).summary() == "PASSED  2 pass, 1 warn"
    assert _report(Status.FAIL).summary().startswith("FAILED")

def test_report_round_trips_through_json():
    r = run_checks([
        Check("n", lambda c: CheckResult(status=Status.PASS, detail="ok", value=3)),
        Check("x", lambda c: 1 / 0),
    ], None)
    again = CheckReport.model_validate(json.loads(r.model_dump_json()))
    assert again == r
    assert again.results["n"].value == 3