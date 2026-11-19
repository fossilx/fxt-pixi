"""
Directional features (TrendFeaturesConfig) and side-aligned model inputs (spec §4, §8.1).
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from fxt.research import Research
from fxt.research.features import build_features, compute_trend, to_wide
from fxt.research.harness import auc, evaluate, load_dataset, model_inputs
from fxt.research.labels import build_labels, build_touches
from fxt.research.models import (
    BarFeaturesConfig, CusumEventsConfig, LogisticModelConfig, LogisticModelConfigV1, SampleWeightsConfig,
    SideLabelsConfig, TrendFeaturesConfig, TripleBarrierTouchConfig, registry,
)
from fxt.research.events import build_events
from fxt.research.weights import build_weights
from fxt.testing import BASE_KEY, LakeBuilder, build_stamped_bars, make_ticks

from .test_harness import CV, synth_dataset

SER = {"source": BASE_KEY.source, "market": BASE_KEY.market, "symbol": BASE_KEY.symbol}
MON = datetime(2020, 1, 6, tzinfo=UTC)


def bars_from(close: list[float], start: datetime = MON, spread: float = 0.0) -> pl.DataFrame:
    n = len(close)
    c = np.array(close, dtype=float)
    o = np.r_[c[0], c[:-1]]
    return pl.DataFrame({
        "time": [start + timedelta(hours=i) for i in range(n)],
        "mid_open": o, "mid_high": np.maximum(o, c) + spread, "mid_low": np.minimum(o, c) - spread,
        "mid_close": c,
    }).with_columns(pl.col("time").cast(pl.Datetime("us", "UTC")))


def wide(bars: pl.DataFrame, cfg: TrendFeaturesConfig) -> pl.DataFrame:
    return to_wide(compute_trend(bars, cfg, symbol="X"), cfg.names())


#!================================================================================(80)
#! definitions
#!--------------------------------------------------------------------------------(80)
def test_names_signed_and_hash():
    cfg = TrendFeaturesConfig()
    assert cfg.names() == ("ma_dist_24h", "ma_dist_120h", "ma_cross_24h_120h", "range_pos_24h",
                           "range_pos_120h", "trend_eff_24h", "trend_eff_120h", "ret_day_z")
    assert cfg.signed_names() == cfg.names()
    assert cfg.config_hash() == "8a57e48893ca"
    assert BarFeaturesConfig().config_hash() == "816950fa181b"           # baseline unchanged
    assert set(BarFeaturesConfig().signed_names()) == {f"ret_{h}h{z}" for h in (1, 4, 24, 120) for z in ("", "_z")}
    with pytest.raises(ValueError):
        TrendFeaturesConfig(windows=(120, 24))


def test_definitions_by_hand():
    rng = np.random.default_rng(0)
    close = list(100 * np.exp(np.cumsum(rng.normal(0, 1e-3, 60))))
    cfg = TrendFeaturesConfig(windows=(4, 8), vol_window=10, min_coverage=1.0, day_return=False)
    w = wide(bars_from(close, spread=0.01), cfg).sort("bar_time")
    c = np.array(close)
    i = 40                                                       # a bar well past every warmup
    row = w.filter(pl.col("bar_time") == MON + timedelta(hours=i + 1)).row(0, named=True)
    r1 = np.diff(np.log(c))
    vol = r1[i - 10:i].std(ddof=1)                               # returns ending at bar i (10 of them)
    sma4, sma8 = c[i - 3:i + 1].mean(), c[i - 7:i + 1].mean()
    assert row["ma_dist_4h"] == pytest.approx(math.log(c[i] / sma4) / (vol * 2), rel=1e-9)
    assert row["ma_cross_4h_8h"] == pytest.approx(math.log(sma4 / sma8) / (vol * math.sqrt(8)), rel=1e-9)
    o = np.r_[c[0], c[:-1]]
    hi, lo = np.maximum(o, c) + 0.01, np.minimum(o, c) - 0.01
    assert row["range_pos_8h"] == pytest.approx(
        (c[i] - lo[i - 7:i + 1].min()) / (hi[i - 7:i + 1].max() - lo[i - 7:i + 1].min()) - 0.5, rel=1e-9)
    assert row["trend_eff_4h"] == pytest.approx(math.log(c[i] / c[i - 4]) / np.abs(r1[i - 4:i]).sum(), rel=1e-9)


def test_bounds_and_signs():
    up = bars_from([100 * 1.001 ** k for k in range(200)], spread=0.0)
    w = wide(up, TrendFeaturesConfig()).drop_nulls()
    #! a steady climb: above every average, top of the range, perfectly efficient
    assert (w["ma_dist_24h"] > 0).all() and (w["ma_cross_24h_120h"] > 0).all()
    assert w["range_pos_24h"].max() == pytest.approx(0.5) and w["trend_eff_24h"].min() == pytest.approx(1.0)
    rng = np.random.default_rng(1)
    noisy = bars_from(list(100 * np.exp(np.cumsum(rng.normal(0, 1e-3, 600)))), spread=0.005)
    w = wide(noisy, TrendFeaturesConfig())
    assert w["range_pos_120h"].drop_nulls().is_between(-0.5, 0.5).all()
    assert w["trend_eff_24h"].drop_nulls().is_between(-1, 1).all()


def test_ret_day_z_resets_each_day():
    rng = np.random.default_rng(3)
    close = list(100 * np.exp(np.cumsum(rng.normal(0, 1e-3, 72))))       # three full UTC days
    bars = bars_from(close, start=MON)
    cfg = TrendFeaturesConfig(windows=(2, 3), vol_window=5, min_coverage=1.0)
    w = wide(bars, cfg).sort("bar_time")
    c, o = bars["mid_close"].to_numpy(), bars["mid_open"].to_numpy()
    r1 = np.diff(np.log(c))
    for i in (10, 23, 24, 30, 47, 48, 60):
        day0 = (i // 24) * 24
        vol = r1[i - 5:i].std(ddof=1)
        expect = math.log(c[i] / o[day0]) / (vol * math.sqrt(i - day0 + 1))
        got = w.filter(pl.col("bar_time") == MON + timedelta(hours=i + 1))["ret_day_z"].item()
        assert got == pytest.approx(expect, rel=1e-9), i


def test_point_in_time():
    rng = np.random.default_rng(2)
    close = list(100 * np.exp(np.cumsum(rng.normal(0, 1e-3, 400))))
    cfg = TrendFeaturesConfig()
    a = compute_trend(bars_from(close), cfg, symbol="X")
    changed = close[:300] + [c * 1.05 for c in close[300:]]
    b = compute_trend(bars_from(changed), cfg, symbol="X")
    cut = MON + timedelta(hours=300)                             # bar_time of bar 299
    assert a.filter(pl.col("bar_time") <= cut).equals(b.filter(pl.col("bar_time") <= cut))


#!================================================================================(80)
#! side-aligned inputs
#!--------------------------------------------------------------------------------(80)
def test_model_inputs():
    f = pl.DataFrame({"side": [1, -1], "a": [0.5, 0.5], "b": [2.0, 3.0]}).with_columns(pl.col("side").cast(pl.Int8))
    X, cols = model_inputs(f, ["a", "b"], ("a",), "aligned")
    assert cols == ["a*side", "b", "side"]
    assert X.tolist() == [[0.5, 2.0, 1.0], [-0.5, 3.0, -1.0]]
    X, cols = model_inputs(f, ["a", "b"], ("a",), "none")
    assert cols == ["a", "b"] and X.tolist() == [[0.5, 2.0], [0.5, 3.0]]
    with pytest.raises(ValueError):
        model_inputs(f, ["a"], (), "sideways")


def test_aligned_logistic_learns_direction_v1_cannot():
    """ Outcome = momentum: a long works when x > 0, a short when x < 0. Without side the
        feature is useless; aligned it's nearly everything.
    """
    ds = synth_dataset()
    rng = np.random.default_rng(5)
    x = ds.frame["x"].to_numpy()
    side = ds.frame["side"].to_numpy()
    y = ((side * x + rng.normal(0, 0.5, len(x))) > 0).astype(np.int8)
    frame = ds.frame.with_columns(pl.Series("meta_label", y, dtype=pl.Int8))
    ds = type(ds)(**{**ds.__dict__, "frame": frame, "signed_names": ("x",)})
    v1 = evaluate(ds, model=LogisticModelConfigV1(), cv=CV, registry=None)
    v2 = evaluate(ds, model=LogisticModelConfig(), cv=CV, registry=None)
    noside = evaluate(ds, model=LogisticModelConfig(side_inputs="none"), cv=CV, registry=None)
    assert abs(v1.aggregate["clf_auc"] - 0.5) < 0.05
    assert abs(noside.aggregate["clf_auc"] - 0.5) < 0.05
    assert v2.aggregate["clf_auc"] > 0.85


def test_v1_config_still_readable():
    v1 = registry.get_model("LogisticModelConfig@1").model_validate({"features": [], "l2": 0.01, "max_iter": 50,
                                                                     "tol": 1e-10, "sample_weight": "weight"})
    assert v1.config_hash() == "4d22b654c996" and v1.label == "logistic_v1" and v1.side_inputs == "none"
    assert LogisticModelConfig().label == "logistic"


#!================================================================================(80)
#! several feature sets in one dataset
#!--------------------------------------------------------------------------------(80)
@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    root = tmp_path_factory.mktemp("trend_lake")
    lb = LakeBuilder(root / "lake")
    build_stamped_bars(lb, make_ticks(n=400_000, start="2014-12-15"))
    rs = Research(root=root / "research")
    ev = CusumEventsConfig(warmup=24)
    build_events(ev, **SER, lake=lb.lake, research=rs)
    tc = TripleBarrierTouchConfig(events_hash=ev.config_hash(), vertical_bars=12, ambiguity="ohlc")
    build_touches(tc, **SER, lake=lb.lake, research=rs)
    lc = SideLabelsConfig(touches_hash=tc.config_hash())
    build_labels(lc, **SER, research=rs)
    build_weights(SampleWeightsConfig(labels_hash=lc.config_hash()), **SER, lake=lb.lake, research=rs)
    fb, ft = BarFeaturesConfig(short=6, long=12), TrendFeaturesConfig(windows=(6, 12), vol_window=12)
    for f in (fb, ft):
        build_features(f, **SER, lake=lb.lake, research=rs)
    return lb, rs, lc, fb, ft


def test_dataset_with_two_feature_sets(chain):
    lb, rs, lc, fb, ft = chain
    ds = load_dataset(rs, lb.lake, labels_hash=lc.config_hash(),
                      features_hashes=(fb.config_hash(), ft.config_hash()), **SER)
    assert ds.feature_names == fb.names() + ft.names()
    assert set(ds.signed_names) == set(fb.signed_names()) | set(ft.names())
    assert ds.hashes["features"] == fb.config_hash() and ds.hashes["features_trend"] == ft.config_hash()
    assert set(ft.names()) <= set(ds.frame.columns)
    #! the same set twice is refused (names collide)
    from fxt.research.harness import InputDatasetError
    with pytest.raises(InputDatasetError, match="repeats"):
        load_dataset(rs, lb.lake, labels_hash=lc.config_hash(),
                     features_hashes=(fb.config_hash(), fb.config_hash()), **SER)


def test_auc_helper_sanity():
    assert auc(np.array([0, 1.0]), np.array([0.2, 0.8])) == 1.0
