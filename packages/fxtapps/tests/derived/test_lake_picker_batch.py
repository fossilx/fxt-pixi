"""
LakePicker multi-select + batch runs, driven headless with Textual's Pilot on a
small synthetic lake (no pytest-asyncio needed: each test runs its own loop).

Lake: raw TICK for 2019-2021 with an fxt envelope, plus 2022 without one
(its input pre-check fails -> BLOCKED).
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from fxt.lake.derived import bar_checks as bc
from fxt.lake.derived.bars import build_bars
from fxt.lake.derived.meta import input_meta_checks, remember_build, stamp_bars
from fxt.lake.jobs import JobContext
from fxt.lake.models import BarsMeta, get_meta_io
from fxt.lake.paths import PartitionKey
from fxt.testing import RAW_TYPEID, LakeBuilder, make_ticks, quiet
from fxtapps.derived.lake_picker import LakePicker, Outcome

YEARS_OK = (2019, 2020, 2021)
YEAR_BARE = 2022


@pytest.fixture
def lb(tmp_path: Path) -> LakeBuilder:
    lb = LakeBuilder(tmp_path / "lake")
    for year in (*YEARS_OK, YEAR_BARE):
        ticks = make_ticks(n=3_000, seed=year, start=f"{year}-03-04")   # a weekday in each year
        lb.put(lb.key("TICK", year=year), ticks,
               envelope=None if year == YEAR_BARE else RAW_TYPEID)
    return lb


def _picker(lb: LakeBuilder, gate: threading.Event | None = None) -> LakePicker:
    lake = lb.lake

    def out_path(key: PartitionKey) -> Path:
        return lb.path(key.replace(interval="1MIN"))

    def build(ctx: JobContext) -> None:
        if gate is not None:
            gate.wait(5)                          # lets a test hold a job "in progress"
        assert ctx.dst is not None
        remember_build(ctx, build_bars(ctx.src, ctx.dst, source_interval="TICK",
                                       interval="1MIN", log=quiet))

    return LakePicker(
        root=lake.raw(), filters={"interval": "TICK"}, action_label="Generate 1MIN bars",
        action=build, out_path=out_path,
        pre_checks=[bc.placement("src"), input_meta_checks(), bc.raw_tick_checks()],
        checks=[bc.placement("dst"), bc.bar_checks()],
        on_report=lambda ctx, r, o: stamp_bars(ctx, r, o, lake_root=lake.root),
        lake=lake,
    )


def _years(app: LakePicker, outcome: Outcome) -> set[int]:
    return {app.entries[[e.path for e in app.entries].index(p)].key.year
            for p, (_, _, o) in app.reports.items() if o is outcome}


async def _until_idle(app: LakePicker, pilot) -> None:
    await app.workers.wait_for_complete()
    await pilot.pause()


def run(coro):
    return asyncio.run(coro)


#!================================================================================(80)
#! tests
#!--------------------------------------------------------------------------------(80)
def test_mark_all_and_run(lb: LakeBuilder):
    async def go():
        app = _picker(lb)
        async with app.run_test(size=(180, 50)) as pilot:
            app.query_one("#results").focus()
            await pilot.press("ctrl+a")
            assert len(app.marked) == 4
            assert "4 files selected" in str(app.query_one("#details").render())
            await pilot.press("ctrl+r")
            await _until_idle(app, pilot)

            assert _years(app, Outcome.PASSED) == set(YEARS_OK)
            assert _years(app, Outcome.BLOCKED) == {YEAR_BARE}
            b = app.batch
            assert b is not None and not b.paused and len(b.done) == 4
            status = str(app.query_one("#batch").render())
            assert "3 passed" in status and "1 blocked" in status and "finished" in status
            for year in YEARS_OK:              # every passing file got stamped
                p = next(e for e in app.entries if e.key.year == year)
                assert app.out_path is not None
                meta = get_meta_io().read_meta_as(app.out_path(p.key), BarsMeta)
                assert meta.passed
    run(go())


def test_space_toggles_and_runs_only_marked(lb: LakeBuilder):
    async def go():
        app = _picker(lb)
        async with app.run_test(size=(180, 50)) as pilot:
            app.query_one("#results").focus()
            await pilot.press("space")            # row 0
            await pilot.press("down", "space")    # row 1
            await pilot.press("down", "space", "space")   # row 2 marked then unmarked
            assert len(app.marked) == 2
            await pilot.press("ctrl+r")
            await _until_idle(app, pilot)
            assert len(app.reports) == 2
    run(go())


def test_marks_survive_search(lb: LakeBuilder):
    async def go():
        app = _picker(lb)
        async with app.run_test(size=(180, 50)) as pilot:
            await pilot.press(*"2019")
            await pilot.press("enter")            # top result, focus moves to the table
            await pilot.press("space")
            await pilot.press("ctrl+f", *["backspace"] * 4, *"2021", "enter")
            assert app.results[0].key.year == 2021
            await pilot.press("space")
            app.query_one("#search").value = ""
            await pilot.pause()
            assert sorted(e.key.year for e in app.marked_in_order()) == [2019, 2021]
    run(go())


def test_typing_space_in_search_does_not_mark(lb: LakeBuilder):
    async def go():
        app = _picker(lb)
        async with app.run_test(size=(180, 50)) as pilot:
            await pilot.press("e", "u", "r", "space", "2")
            assert app.query_one("#search").value == "eur 2"
            assert not app.marked
    run(go())


def test_pause_and_resume(lb: LakeBuilder):
    async def go():
        gate = threading.Event()
        app = _picker(lb, gate)
        async with app.run_test(size=(180, 50)) as pilot:
            app.query_one("#results").focus()
            await pilot.press("ctrl+a")
            await pilot.press("ctrl+r")
            await pilot.pause()
            assert app.busy
            await pilot.press("p")                # pause while the first file is held
            assert "pausing" in str(app.query_one("#batch").render())
            gate.set()
            await _until_idle(app, pilot)

            b = app.batch
            assert b is not None and b.paused and len(b.done) == 1
            assert "Resume (3 left)" in str(app.query_one("#run").label)
            assert "paused" in str(app.query_one("#batch").render())

            await pilot.press("ctrl+r")           # resume
            await _until_idle(app, pilot)
            assert not app.batch.paused and len(app.batch.done) == 4
            assert app.batch is b                 # same batch: counts carry over
    run(go())


def test_verify_skips_files_without_output(lb: LakeBuilder):
    async def go():
        app = _picker(lb)
        async with app.run_test(size=(180, 50)) as pilot:
            app.query_one("#results").focus()
            await pilot.press("space", "ctrl+r")  # build only the first file
            await _until_idle(app, pilot)
            await pilot.press("ctrl+a")           # now all 4 marked
            await pilot.press("ctrl+v")
            await _until_idle(app, pilot)
            b = app.batch
            assert not b.build
            assert b.count(Outcome.SKIPPED) == 3 and b.count(Outcome.PASSED) == 1
    run(go())
