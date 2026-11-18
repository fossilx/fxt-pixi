"""
Research path builder (ML pipeline spec §3.1).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from fxt.research import Research, ResearchKey, ResearchPathNotFound, Stage

H1, H2 = "a" * 12, "b" * 12
SER = {"source": "dukascopy", "market": "forex", "symbol": "EURJPY"}


@pytest.fixture
def rs(tmp_path) -> Research:
    return Research(root=tmp_path / "research")


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return p


def test_yearly_path(rs: Research):
    key = ResearchKey(stage=Stage.EVENTS, config=H1, **SER, year=2020)
    p = rs.file(key)
    assert p.relative_to(rs.root).as_posix() == \
        f"events/config={H1}/source=dukascopy/market=forex/symbol=EURJPY/year=2020/EURJPY-2020.parquet"


def test_weights_path_has_no_year(rs: Research):
    key = ResearchKey(stage=Stage.WEIGHTS, config=H1, **SER)
    assert rs.file(key).relative_to(rs.root).as_posix() == \
        f"weights/config={H1}/source=dukascopy/market=forex/symbol=EURJPY/EURJPY.parquet"


def test_year_rules():
    with pytest.raises(ValidationError, match="year is required"):
        ResearchKey(stage=Stage.LABELS, config=H1, **SER)
    with pytest.raises(ValidationError, match="split by year"):
        ResearchKey(stage=Stage.WEIGHTS, config=H1, **SER, year=2020)


def test_path_rejects_year_for_weights(rs: Research):
    with pytest.raises(ValueError, match="split by year"):
        rs.path(Stage.WEIGHTS, config=H1, **SER, year=2020, must_exist=False)


@pytest.mark.parametrize("bad", ["ABCDEF123456", "abc", "g" * 12, "../" + "a" * 9])
def test_config_must_be_a_hash(rs: Research, bad):
    with pytest.raises(ValueError):
        rs.path(Stage.EVENTS, config=bad, must_exist=False)


def test_levels_in_order(rs: Research):
    with pytest.raises(ValueError, match="'source' is missing"):
        rs.path(Stage.EVENTS, config=H1, market="forex", must_exist=False)


def test_unsafe_values(rs: Research):
    with pytest.raises(ValueError, match="Unsafe"):
        rs.path(Stage.EVENTS, config=H1, source="a/b", must_exist=False)


def test_must_exist(rs: Research):
    with pytest.raises(ResearchPathNotFound):
        rs.path(Stage.EVENTS, config=H1)


def test_key_round_trips_through_its_path(rs: Research):
    for key in (ResearchKey(stage=Stage.FEATURES, config=H1, **SER, year=2021),
                ResearchKey(stage=Stage.WEIGHTS, config=H2, **SER)):
        assert ResearchKey.from_path(rs.file(key).relative_to(rs.root)) == key


def test_scan(rs: Research):
    k20 = ResearchKey(stage=Stage.EVENTS, config=H1, **SER, year=2020)
    k21 = k20.model_copy(update={"year": 2021})
    other = ResearchKey(stage=Stage.EVENTS, config=H2, **{**SER, "symbol": "GBPUSD"}, year=2020)
    for k in (k20, k21, other):
        _touch(rs.file(k))
    _touch(rs.config_dir(Stage.EVENTS, H1) / "stray.parquet")              # wrong place
    _touch(rs.file(k20).with_name("EURJPY-1999.parquet"))                  # misnamed

    assert [k for k, _ in rs.scan(Stage.EVENTS)] == [k20, k21, other]
    assert [k for k, _ in rs.scan(Stage.EVENTS, config=H1)] == [k20, k21]
    assert [k for k, _ in rs.scan(Stage.EVENTS, year=2020)] == [k20, other]
    assert [k for k, _ in rs.scan(Stage.EVENTS, symbol="GBPUSD")] == [other]
    assert rs.scan(Stage.LABELS) == []
    assert rs.configs(Stage.EVENTS) == [H1, H2]


def test_scan_weights(rs: Research):
    k = ResearchKey(stage=Stage.WEIGHTS, config=H1, **SER)
    _touch(rs.file(k))
    assert rs.scan(Stage.WEIGHTS, symbol="EURJPY") == [(k, rs.file(k))]
    with pytest.raises(ValueError):
        rs.scan(Stage.WEIGHTS, year=2020)
