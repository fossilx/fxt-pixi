"""
Side labels: triple-barrier labeling step 2 (ML pipeline spec §6.3).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from fxt.research import Research, Stage
from fxt.research.events import build_events
from fxt.research.labels import (
    LABEL_SCHEMA, InputTouchesError, build_labels, build_touches, check_labels, side_labels,
)
from fxt.research.models import (
    CusumEventsConfig, LabelsMeta, SideLabelsConfig, TripleBarrierTouchConfig,
)
from fxt.research.store import read_table
from fxt.testing import BASE_KEY, LakeBuilder, build_stamped_bars, make_ticks

TOUCH_HASH = TripleBarrierTouchConfig(events_hash=CusumEventsConfig().config_hash()).config_hash()


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def touches(rows: list[dict]) -> pl.DataFrame:
    """ A minimal touches table: each row gives touch, ret (unsided), max_up, max_down. """
    t0 = datetime(2020, 1, 6, 1, tzinfo=UTC)
    out = []
    for i, r in enumerate(rows):
        placed = r["touch"] != "insufficient_data"
        out.append({
            "event_id": f"e{i}", "symbol": "EURJPY", "t0": t0 + timedelta(hours=i),
            "half_width": 0.01 if placed else None, "touch": r["touch"],
            "t1": t0 + timedelta(hours=i + 1) if placed else None,
            "exit_gap": False if placed else None, "hours_to_exit": 1.0 if placed else None,
            "ret": r.get("ret") if placed else None,
            "max_up": r.get("max_up", 0.0) if placed else None,
            "max_down": r.get("max_down", 0.0) if placed else None,
        })
    return pl.DataFrame(out).with_columns(pl.col("t0", "t1").cast(pl.Datetime("us", "UTC")))


def directions(n: int, values: list[int]) -> pl.DataFrame:
    return pl.DataFrame({"event_id": [f"e{i}" for i in range(n)], "direction": values},
                        schema={"event_id": pl.String, "direction": pl.Int8})


def label(rows, dirs, **cfg) -> pl.DataFrame:
    out = side_labels(touches(rows), directions(len(rows), dirs),
                      SideLabelsConfig(touches_hash=TOUCH_HASH, **cfg), strategy_id="x_follow")
    assert dict(out.schema) == LABEL_SCHEMA
    return out


#!================================================================================(80)
#! outcome mapping
#!--------------------------------------------------------------------------------(80)
@pytest.mark.parametrize("touch, ret, direction, rule, side, outcome", [
    ("upper",    0.01,  1, "follow",  1, "pt"),
    ("upper",    0.01, -1, "follow", -1, "sl"),
    ("lower",   -0.01,  1, "follow",  1, "sl"),
    ("lower",   -0.01, -1, "follow", -1, "pt"),
    ("upper",    0.01,  1, "fade",   -1, "sl"),
    ("upper",    0.01, -1, "fade",    1, "pt"),
    ("lower",   -0.01,  1, "fade",   -1, "pt"),
    ("vertical", 0.002, 1, "follow",  1, "timeout"),
    ("vertical", 0.002, 1, "fade",   -1, "timeout"),
])
def test_outcome_mapping(touch, ret, direction, rule, side, outcome):
    r = label([{"touch": touch, "ret": ret}], [direction], side_rule=rule).row(0, named=True)
    assert (r["side"], r["outcome"]) == (side, outcome)
    assert r["ret"] == pytest.approx(side * ret)
    assert r["meta_label"] == (1 if outcome == "pt" else 0)


def test_insufficient_stays_insufficient():
    r = label([{"touch": "insufficient_data"}], [1]).row(0, named=True)
    assert r["outcome"] == "insufficient_data"
    assert r["meta_label"] is None and r["ret"] is None and r["path_type"] is None


def test_timeouts_are_not_wins_by_default():
    rows = [{"touch": "vertical", "ret": 0.003}, {"touch": "vertical", "ret": -0.003},
            {"touch": "vertical", "ret": 0.0}]
    assert label(rows, [1, 1, 1])["meta_label"].to_list() == [0, 0, 0]
    assert label(rows, [1, 1, 1], timeout_positive_is_win=True)["meta_label"].to_list() == [1, 0, 0]
    #! "positive" is the SIDE-adjusted return: a short gains when price falls
    assert label(rows, [-1, -1, -1], timeout_positive_is_win=True)["meta_label"].to_list() == [0, 1, 0]


def test_timeout_rule_changes_the_hash():
    a = SideLabelsConfig(touches_hash=TOUCH_HASH)
    assert a.config_hash() != SideLabelsConfig(touches_hash=TOUCH_HASH, timeout_positive_is_win=True).config_hash()
    assert a.config_hash() != SideLabelsConfig(touches_hash=TOUCH_HASH, side_rule="fade").config_hash()
    assert a.config_hash() == "3b896dab2027"                      # pinned (follow on the default touches)
    assert a.input_hashes() == {"touches": TOUCH_HASH}


def test_follow_and_fade_mirror_each_other():
    rng = np.random.default_rng(1)
    rows = [{"touch": t, "ret": (0.01 if t == "upper" else -0.01 if t == "lower" else float(rng.normal(0, 3e-3))),
             "max_up": float(rng.uniform(0, 0.012)), "max_down": float(rng.uniform(0, 0.012))}
            for t in rng.choice(["upper", "lower", "vertical", "insufficient_data"], 200)]
    dirs = [int(x) for x in rng.choice([1, -1], 200)]
    fo, fa = label(rows, dirs, side_rule="follow"), label(rows, dirs, side_rule="fade")
    swap = {"pt": "sl", "sl": "pt", "timeout": "timeout", "insufficient_data": "insufficient_data"}
    assert fa["outcome"].to_list() == [swap[o] for o in fo["outcome"]]
    assert fa["side"].to_list() == [-s for s in fo["side"]]
    assert fa["ret"].fill_null(0).to_list() == pytest.approx([-r for r in fo["ret"].fill_null(0)])
    assert fa["max_favorable"].to_list() == fo["max_adverse"].to_list()
    assert fa["path_type"].to_list() == fo["path_type"].to_list()   # side-agnostic


def test_excursions_follow_the_side():
    rows = [{"touch": "vertical", "ret": 0.0, "max_up": 0.004, "max_down": 0.001}]
    long, short = label(rows, [1]).row(0, named=True), label(rows, [-1]).row(0, named=True)
    assert (long["max_favorable"], long["max_adverse"]) == (0.004, 0.001)
    assert (short["max_favorable"], short["max_adverse"]) == (0.001, 0.004)


#!================================================================================(80)
#! path features
#!--------------------------------------------------------------------------------(80)
def reference_path_type(exc: float, net: float) -> str:
    """ path_type() from first_bars/d_triple_barrier.py, verbatim (placeholder thresholds). """
    if exc < 0.3 and net > 0.5:
        return "directional"
    if exc >= 0.5:
        return "ranging"
    if exc < 0.3 and net <= 0.3:
        return "quiet"
    return "mixed"


def test_path_features_match_the_first_pass():
    rng = np.random.default_rng(7)
    rows = []
    for _ in range(500):
        up, dn = rng.uniform(0, 0.01, 2)
        rows.append({"touch": "vertical", "ret": float(rng.uniform(-dn, up)), "max_up": float(up), "max_down": float(dn)})
    out = label(rows, [1] * len(rows))
    for r, o in zip(rows, out.iter_rows(named=True), strict=True):
        exc = min(r["max_up"], r["max_down"]) / 0.01
        net = abs(r["ret"]) / 0.01
        assert o["excursion_ratio"] == pytest.approx(exc)
        assert o["net_ratio"] == pytest.approx(net)
        assert o["path_type"] == reference_path_type(exc, net)


def test_path_thresholds_are_config():
    rows = [{"touch": "vertical", "ret": 0.006, "max_up": 0.006, "max_down": 0.0025}]   # exc .25, net .6
    assert label(rows, [1])["path_type"].item() == "directional"
    assert label(rows, [1], path_dir_exc=0.2)["path_type"].item() == "mixed"


#!================================================================================(80)
#! guards
#!--------------------------------------------------------------------------------(80)
def test_every_touch_needs_a_direction():
    rows = [{"touch": "upper", "ret": 0.01}] * 2
    with pytest.raises(ValueError, match="no event direction"):
        side_labels(touches(rows), directions(1, [1]), SideLabelsConfig(touches_hash=TOUCH_HASH), strategy_id="x")
    dup = pl.concat([directions(2, [1, 1]), directions(1, [1])])
    with pytest.raises(ValueError, match="duplicate"):
        side_labels(touches(rows), dup, SideLabelsConfig(touches_hash=TOUCH_HASH), strategy_id="x")


def test_check_labels():
    out = label([{"touch": "upper", "ret": 0.01}, {"touch": "lower", "ret": -0.01}], [1, 1])
    assert all(c.ok for c in check_labels(out))
    bad = out.with_columns(pl.lit(-0.01).alias("ret"))
    assert [c.name for c in check_labels(bad) if not c.ok] == ["labels: profit-takes have ret > 0"]


#!================================================================================(80)
#! builder
#!--------------------------------------------------------------------------------(80)
SER = {"source": BASE_KEY.source, "market": BASE_KEY.market, "symbol": BASE_KEY.symbol}
EVCFG = CusumEventsConfig(warmup=24)


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    root = tmp_path_factory.mktemp("labels_lake")
    lb = LakeBuilder(root / "lake")
    build_stamped_bars(lb, make_ticks(n=400_000, start="2014-12-15"))
    rs = Research(root=root / "research")
    build_events(EVCFG, **SER, lake=lb.lake, research=rs)
    tcfg = TripleBarrierTouchConfig(events_hash=EVCFG.config_hash(), vertical_bars=12, ambiguity="ohlc")
    build_touches(tcfg, **SER, lake=lb.lake, research=rs)
    return rs, tcfg


def test_build_labels(pipeline):
    rs, tcfg = pipeline
    cfg = SideLabelsConfig(touches_hash=tcfg.config_hash())
    res = build_labels(cfg, **SER, research=rs)

    assert res.strategy_id == "cusum_h3_follow"
    touch_years = [k.year for k, _ in rs.scan(Stage.TOUCHES, config=tcfg.config_hash())]
    assert [k.year for k, _ in rs.scan(Stage.LABELS, config=res.config_hash)] == touch_years
    for p in res.paths:
        df, meta = read_table(p)
        assert isinstance(meta, LabelsMeta) and meta.passed
        assert meta.strategy_id == "cusum_h3_follow"
        assert meta.input_hashes == {"touches": tcfg.config_hash()}
        assert {i.typeid for i in meta.inputs} == {"TouchesMeta@1", "EventsMeta@1"}
        assert all(i.root == "research" for i in meta.inputs)
        assert tuple(df.columns) == tuple(LABEL_SCHEMA)
        assert (df["t0"].dt.year() == meta.year).all()
    assert res.labels["outcome"].is_in(["pt", "sl", "timeout", "insufficient_data"]).all()
    assert res.stats["placed"] > 0


def test_follow_and_fade_build_side_by_side(pipeline):
    rs, tcfg = pipeline
    fo = build_labels(SideLabelsConfig(touches_hash=tcfg.config_hash()), **SER, research=rs)
    fa = build_labels(SideLabelsConfig(touches_hash=tcfg.config_hash(), side_rule="fade"), **SER, research=rs)
    assert fo.config_hash != fa.config_hash
    assert fa.strategy_id == "cusum_h3_fade"
    assert fo.stats["share"]["pt"] == pytest.approx(fa.stats["share"]["sl"])
    assert len(rs.configs(Stage.LABELS)) >= 2


def test_missing_touches(pipeline, tmp_path):
    with pytest.raises(InputTouchesError):
        build_labels(SideLabelsConfig(touches_hash="0" * 12), **SER, research=pipeline[0])
