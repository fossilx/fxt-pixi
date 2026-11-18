"""
Shared fixtures for fxt's tests. The data/lake helpers themselves live in
fxt.testing so other packages' tests (fxtapps) can use them too.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from fxt.lake.derived.bars import build_bars
from fxt.lake.jobs import JobContext
from fxt.lake.paths import PartitionKey
from fxt.testing import BASE_KEY, LakeBuilder, make_ticks, quiet  # noqa: F401  (re-exported)


@pytest.fixture(scope="session")
def tick_factory():
    """ make_ticks itself, for tests that need custom sizes/seeds. """
    return make_ticks


@pytest.fixture(scope="session")
def ticks() -> pl.DataFrame:
    return make_ticks()


@pytest.fixture(scope="session")
def built(tmp_path_factory, ticks) -> SimpleNamespace:
    """ A lake with raw ticks plus clean 1MIN and 1HOUR bars, built once per session.
        Treat as read-only: copy into `fresh` before mutating anything.
    """
    lb = LakeBuilder(tmp_path_factory.mktemp("lake"))
    raw = lb.put(lb.key("TICK"), ticks)
    m1 = lb.path(lb.key("1MIN"))
    build_bars(raw, m1, source_interval="TICK", interval="1MIN", log=quiet)
    h1 = lb.path(lb.key("1HOUR"))
    build_bars(m1, h1, source_interval="1MIN", interval="1HOUR", log=quiet)
    return SimpleNamespace(lake=lb, raw=raw, m1=m1, h1=h1)


@pytest.fixture
def fresh(tmp_path) -> LakeBuilder:
    """ An empty lake for one test. """
    return LakeBuilder(tmp_path / "lake")


@pytest.fixture
def make_ctx():
    """ JobContext factory; closes cached connections after the test. """
    made: list[JobContext] = []

    def make(src: Path, dst: Path | None = None) -> JobContext:
        ctx = JobContext(key=PartitionKey.from_path(src), src=src, dst=dst)
        made.append(ctx)
        return ctx

    yield make
    for ctx in made:
        ctx.close()