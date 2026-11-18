"""
Sample weights: concurrency-based uniqueness on business time (ML pipeline spec §7).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from fxt.research import Research, Stage
from fxt.research.events import build_events
from fxt.research.labels import build_labels, build_touches
from fxt.research.models import (
    CusumEventsConfig, SampleWeightsConfig, SideLabelsConfig, TripleBarrierTouchConfig, WeightsMeta,
)
from fxt.research.store import read_table
from fxt.research.weights import (
    WEIGHT_SCHEMA, InputLabelsError, build_weights, business_coord, check_weights, compute_weights, sweep,
)
from fxt.testing import BASE_KEY, LakeBuilder, build_stamped_bars, make_ticks

MON = datetime(2020, 1, 6, tzinfo=UTC)


#!================================================================================(80)
#! business clock
#!--------------------------------------------------------------------------------(80)
def weekday_clock(days: int = 14) -> pl.Series:
    """ Hourly bar opens, Mon-Fri only. """
    t = [MON + timedelta(hours=h) for h in range(days * 24)]
    return pl.Series("time", [x for x in t if x.weekday() < 5]).cast(pl.Datetime("us", "UTC"))


def test_business_coord():
    clock = np.array([int((MON + timedelta(hours=h)).timestamp()) for h in range(5)])
    t = lambda **kw: np.array([int((MON + timedelta(**kw)).timestamp())])  # noqa: E731
    assert business_coord(t(hours=0), clock)[0] == 0.0
    assert business_coord(t(hours=2, minutes=30), clock)[0] == 2.5
    #! a closed stretch maps onto the next open bar
    fri = np.array([int((MON + timedelta(days=4, hours=h)).timestamp()) for h in range(22, 24)])
    mon = np.array([int((MON + timedelta(days=7, hours=h)).timestamp()) for h in range(0, 2)])
    clock2 = np.concatenate([fri, mon])
    sat = np.array([int((MON + timedelta(days=5, hours=12)).timestamp())])
    assert business_coord(sat, clock2)[0] == 2.0                   # = start of Monday's first bar


#!================================================================================(80)
#! sweep line
#!--------------------------------------------------------------------------------(80)
@pytest.mark.parametrize("start, end, uniq, mean_c", [
    ([0.0, 0.0], [1.0, 1.0], [0.5, 0.5], [2.0, 2.0]),             # identical lives share everything
    ([0.0, 2.0], [1.0, 3.0], [1.0, 1.0], [1.0, 1.0]),             # disjoint
    ([0.0, 1.0], [4.0, 2.0], [0.875, 0.5], [1.25, 2.0]),          # nested
    ([0.0, 1.0], [2.0, 3.0], [0.75, 0.75], [1.5, 1.5]),           # half overlap
])
def test_sweep_by_hand(start, end, uniq, mean_c):
    u, c, _ = sweep(np.array(start), np.array(end))
    assert u == pytest.approx(uniq) and c == pytest.approx(mean_c)


def brute_force(start: np.ndarray, end: np.ndarray, i: int) -> tuple[float, float]:
    """ Direct count at segment midpoints, no sweep line (verify_weights' recompute). """
    inner = np.concatenate([start[(start > start[i]) & (start < end[i])], end[(end > start[i]) & (end < end[i])]])
    pts = np.unique(np.concatenate([[start[i], end[i]], inner]))
    mids = (pts[:-1] + pts[1:]) / 2
    c = ((start[None, :] <= mids[:, None]) & (mids[:, None] < end[None, :])).sum(axis=1)
    life = end[i] - start[i]
    return float(((pts[1:] - pts[:-1]) / c).sum() / life), float(((pts[1:] - pts[:-1]) * c).sum() / life)


def test_sweep_matches_brute_force():
    rng = np.random.default_rng(3)
    start = np.sort(rng.uniform(0, 500, 400))
    end = start + rng.uniform(1 / 60, 48, 400)
    u, c, covered = sweep(start, end)
    for i in rng.choice(400, 60, replace=False):
        bu, bc = brute_force(start, end, i)
        assert u[i] == pytest.approx(bu, abs=1e-9) and c[i] == pytest.approx(bc, abs=1e-9)
    #! identity: live events' 1/c shares sum to 1 at every instant
    assert float((u * (end - start)).sum()) == pytest.approx(covered, rel=1e-12)
    assert ((u > 0) & (u <= 1 + 1e-12)).all() and (c >= 1 - 1e-12).all()


def test_short_lives_keep_precision():
    """ A one-minute life among long ones: the extended-precision sums keep it exact. """
    start = np.array([0.0, 10_000.0, 10_000.5])
    end = np.array([20_000.0, 10_000.0 + 1 / 60, 10_001.0])
    u, _, _ = sweep(start, end)
    assert u[1] == pytest.approx(0.5, abs=1e-12)


#!================================================================================(80)
#! compute_weights
#!--------------------------------------------------------------------------------(80)
def labels_frame(rows: list[tuple]) -> pl.DataFrame:
    """ rows: (t0, t1, touch, ret); touch None = insufficient. """
    return pl.DataFrame({
        "event_id": [f"e{i}" for i in range(len(rows))],
        "t0": [r[0] for r in rows],
        "t1": [r[1] for r in rows],
        "touch": [r[2] or "insufficient_data" for r in rows],
        "outcome": ["insufficient_data" if r[2] is None else "timeout" if r[2] == "vertical" else "pt"
                    for r in rows],
        "ret": [r[3] for r in rows],
    }, schema_overrides={"t0": pl.Datetime("us", "UTC"), "t1": pl.Datetime("us", "UTC"), "ret": pl.Float64})


def h(n: float) -> datetime:
    return MON + timedelta(hours=n)


def test_compute_weights():
    rows = [(h(1), h(5), "vertical", 0.002),
            (h(3), h(4), "upper", 0.01),           # touch: lives through the end of its minute
            (h(10), None, None, None)]             # insufficient
    w = compute_weights(labels_frame(rows), weekday_clock())
    assert dict(w.schema) == WEIGHT_SCHEMA
    a, b, c = w.iter_rows(named=True)
    assert a["life_hours"] == pytest.approx(4.0)
    assert b["life_hours"] == pytest.approx(1 + 1 / 60)
    assert c["uniqueness"] is None and c["weight"] is None
    #! a: 4h, shares [3, 4+1/60) with b  ->  (4 - (1+1/60)/2) / 4
    assert a["uniqueness"] == pytest.approx((4 - (1 + 1 / 60) / 2) / 4)
    assert b["uniqueness"] == pytest.approx(0.5)
    ok = w.drop_nulls("uniqueness")
    assert ok["weight"].mean() == pytest.approx(1) and ok["weight_uniq"].mean() == pytest.approx(1)
    raw = np.array([a["uniqueness"] * 0.002, b["uniqueness"] * 0.01])
    assert ok["weight"].to_list() == pytest.approx(list(raw / raw.mean()))


def test_weekends_dont_count_as_overlap():
    fri_late, mon_early = MON + timedelta(days=4, hours=22), MON + timedelta(days=7, hours=2)
    w = compute_weights(labels_frame([(fri_late, mon_early, "vertical", 0.001)]), weekday_clock())
    assert w["life_hours"].item() == pytest.approx(4.0)            # Fri 22-24 + Mon 00-02


def test_all_insufficient():
    w = compute_weights(labels_frame([(h(1), None, None, None)]), weekday_clock())
    assert w.height == 1 and w["uniqueness"].is_null().all()
    assert check_weights(w)[0].status == "warn"


def test_check_weights_catches_bad_rows():
    w = compute_weights(labels_frame([(h(1), h(5), "vertical", 0.002), (h(3), h(4), "upper", 0.01)]),
                        weekday_clock())
    assert all(c.ok for c in check_weights(w))
    bad = w.with_columns(pl.col("weight") * 2)
    assert [c.name for c in check_weights(bad) if not c.ok] == ["weights: both weights have mean 1"]


#!================================================================================(80)
#! builder
#!--------------------------------------------------------------------------------(80)
SER = {"source": BASE_KEY.source, "market": BASE_KEY.market, "symbol": BASE_KEY.symbol}


def test_pinned_hash():
    assert SampleWeightsConfig(labels_hash="3b896dab2027").config_hash() == "b50998e8f246"
    assert SampleWeightsConfig(labels_hash="3b896dab2027").input_hashes() == {"labels": "3b896dab2027"}


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    root = tmp_path_factory.mktemp("weights_lake")
    lb = LakeBuilder(root / "lake")
    build_stamped_bars(lb, make_ticks(n=400_000, start="2014-12-15"))
    rs = Research(root=root / "research")
    ev = CusumEventsConfig(warmup=24)
    build_events(ev, **SER, lake=lb.lake, research=rs)
    tc = TripleBarrierTouchConfig(events_hash=ev.config_hash(), vertical_bars=12, ambiguity="ohlc")
    build_touches(tc, **SER, lake=lb.lake, research=rs)
    lc = SideLabelsConfig(touches_hash=tc.config_hash())
    build_labels(lc, **SER, research=rs)
    return lb, rs, lc


def test_build_weights(pipeline):
    lb, rs, lc = pipeline
    res = build_weights(SampleWeightsConfig(labels_hash=lc.config_hash()), **SER, lake=lb.lake, research=rs)
    assert res.strategy_id == "cusum_h3_follow"
    [(key, path)] = rs.scan(Stage.WEIGHTS, config=res.config_hash)
    assert key.year is None and path.name == f"{SER['symbol']}.parquet"   # one file, every year
    df, meta = read_table(path)
    assert isinstance(meta, WeightsMeta) and meta.passed and meta.year is None
    assert meta.input_hashes == {"labels": lc.config_hash()}
    assert {i.typeid for i in meta.inputs} == {"LabelsMeta@1", "BarsMeta@1"}
    n_labels = sum(read_table(p)[1].rows for _, p in rs.scan(Stage.LABELS, config=lc.config_hash()))
    assert df.height == n_labels
    ok = df.drop_nulls("uniqueness")
    assert ok["weight"].mean() == pytest.approx(1)
    assert set(df.columns) == {"symbol", *WEIGHT_SCHEMA}


def test_missing_labels(pipeline):
    lb, rs, _ = pipeline
    with pytest.raises(InputLabelsError):
        build_weights(SampleWeightsConfig(labels_hash="0" * 12), **SER, lake=lb.lake, research=rs)
