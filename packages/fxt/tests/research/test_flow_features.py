"""
Order-flow features (FlowFeaturesConfig, spec §4.4): hourly features from 1MIN bars.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from fxt.research import Research
from fxt.research.features import build_features, compute_flow, hourly_flow, to_wide
from fxt.research.harness import default_features, load_dataset
from fxt.research.labels import build_labels, build_touches
from fxt.research.events import build_events
from fxt.research.models import (
    BarFeaturesConfig, CusumEventsConfig, FlowFeaturesConfig, SampleWeightsConfig, SideLabelsConfig,
    TrendFeaturesConfig, TripleBarrierTouchConfig,
)
from fxt.research.weights import build_weights
from fxt.testing import BASE_KEY, LakeBuilder, build_stamped_bars, make_ticks

SER = {"source": BASE_KEY.source, "market": BASE_KEY.market, "symbol": BASE_KEY.symbol}
MON = datetime(2020, 1, 6, tzinfo=UTC)


def minutes(n_hours: int = 30, seed: int = 0, start: datetime = MON, drop: slice | None = None) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    n = n_hours * 60
    df = pl.DataFrame({
        "time": [start + timedelta(minutes=i) for i in range(n)],
        "mid_close": 100 + np.cumsum(rng.choice([-0.01, 0.0, 0.01], n)),
        "bid_volume": rng.uniform(50, 150, n), "ask_volume": rng.uniform(50, 150, n),
        "tick_count": rng.integers(1, 50, n).astype(np.uint32), "spread_mean": rng.uniform(0.005, 0.02, n),
    }).with_columns(pl.col("time").cast(pl.Datetime("us", "UTC")))
    return df if drop is None else df.filter(~pl.int_range(pl.len()).is_between(drop.start, drop.stop - 1))


CFG = FlowFeaturesConfig(windows=(1, 4), dev_window=6, activity_window=4, min_coverage=1.0)


def test_names_signed_hash():
    cfg = FlowFeaturesConfig()
    assert cfg.names() == ("depth_imb_1h", "depth_imb_4h", "depth_imb_24h", "tick_imb_1h", "tick_imb_4h",
                           "tick_imb_24h", "flow_imb_1h", "flow_imb_4h", "flow_imb_24h", "depth_imb_1h_dev",
                           "activity_1h_24h", "spread_1h_24h")
    assert set(cfg.signed_names()) == set(cfg.names()) - {"activity_1h_24h", "spread_1h_24h"}
    assert cfg.config_hash() == "dd9bfefcd9db"
    assert default_features() == (BarFeaturesConfig().config_hash(), TrendFeaturesConfig().config_hash(),
                                  cfg.config_hash())


def test_definitions_by_hand():
    m = minutes()
    w = to_wide(compute_flow(m, CFG, symbol="X"), CFG.names()).sort("bar_time")
    c = m["mid_close"].to_numpy()
    d = np.r_[0, np.sign(np.diff(c))]
    bid, ask, ticks = m["bid_volume"].to_numpy(), m["ask_volume"].to_numpy(), m["tick_count"].to_numpy().astype(float)
    spread = m["spread_mean"].to_numpy()
    k = 10                                                       # the hour [10:00, 11:00) -> bar_time 11:00
    row = w.filter(pl.col("bar_time") == MON + timedelta(hours=k + 1)).row(0, named=True)
    h1 = slice(k * 60, (k + 1) * 60)
    h4 = slice((k - 3) * 60, (k + 1) * 60)
    assert row["depth_imb_1h"] == pytest.approx((bid[h1].sum() - ask[h1].sum()) / (bid[h1].sum() + ask[h1].sum()))
    assert row["depth_imb_4h"] == pytest.approx((bid[h4].sum() - ask[h4].sum()) / (bid[h4].sum() + ask[h4].sum()))
    up, dn = (d[h4] > 0).sum(), (d[h4] < 0).sum()
    assert row["tick_imb_4h"] == pytest.approx((up - dn) / (up + dn))
    assert row["flow_imb_1h"] == pytest.approx((d[h1] * ticks[h1]).sum() / ticks[h1].sum())
    hourly_ticks = ticks.reshape(-1, 60).sum(axis=1)
    assert row["activity_1h_4h"] == pytest.approx(hourly_ticks[k] / hourly_ticks[k - 3:k + 1].mean())
    hourly_spread = (spread * ticks).reshape(-1, 60).sum(axis=1) / hourly_ticks
    assert row["spread_1h_4h"] == pytest.approx(hourly_spread[k] / hourly_spread[k - 3:k + 1].mean())
    imb = (bid.reshape(-1, 60).sum(1) - ask.reshape(-1, 60).sum(1)) / (bid.reshape(-1, 60).sum(1) + ask.reshape(-1, 60).sum(1))
    assert row["depth_imb_1h_dev"] == pytest.approx(imb[k] - imb[k - 5:k + 1].mean())


def test_bounds():
    w = to_wide(compute_flow(minutes(60, seed=3), FlowFeaturesConfig(), symbol="X"), FlowFeaturesConfig().names())
    for n in FlowFeaturesConfig().signed_names():
        assert w[n].drop_nulls().is_between(-1, 1).all(), n


def test_gap_minutes_dont_count():
    m = minutes(6, drop=slice(120, 140))                         # a 20-minute hole at the start of hour 2
    h = hourly_flow(m, CFG)
    t = m["time"].to_numpy()
    c = m["mid_close"].to_numpy()
    step = np.diff(t).astype("timedelta64[m]").astype(int)
    d = np.r_[0, np.where(step > 5, 0, np.sign(np.diff(c)))]     # no direction across the hole
    in_h2 = (m["time"].dt.hour() == 2).to_numpy()
    got = h.filter(pl.col("bar_time") == MON + timedelta(hours=3)).row(0, named=True)
    assert got["n_up"] == (d[in_h2] > 0).sum() and got["n_down"] == (d[in_h2] < 0).sum()


def test_point_in_time():
    m = minutes(40, seed=5)
    a = compute_flow(m, FlowFeaturesConfig(windows=(1, 4), activity_window=4, dev_window=6), symbol="X")
    changed = m.with_columns(pl.when(pl.col("time") >= MON + timedelta(hours=20))
                             .then(pl.col("bid_volume") * 9).otherwise(pl.col("bid_volume")).alias("bid_volume"))
    b = compute_flow(changed, FlowFeaturesConfig(windows=(1, 4), activity_window=4, dev_window=6), symbol="X")
    cut = MON + timedelta(hours=20)
    assert a.filter(pl.col("bar_time") <= cut).equals(b.filter(pl.col("bar_time") <= cut))
    assert not a.filter(pl.col("bar_time") > cut).equals(b.filter(pl.col("bar_time") > cut))


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    root = tmp_path_factory.mktemp("flow_lake")
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
    fl = FlowFeaturesConfig(windows=(1, 4), activity_window=4, dev_window=6)
    res = build_features(fl, **SER, lake=lb.lake, research=rs)
    return lb, rs, lc, fl, res


def test_build_from_minute_bars(chain):
    lb, rs, lc, fl, res = chain
    assert res.paths and res.stats["coverage"].min() > 0.8         # per hour, not per minute
    hours = res.features["bar_time"]
    assert (hours.dt.truncate("1h") == hours).all()
    ds = load_dataset(rs, lb.lake, labels_hash=lc.config_hash(), features_hashes=fl.config_hash(), **SER)
    assert ds.hashes["features_flow"] == fl.config_hash()
    assert set(ds.signed_names) == set(fl.signed_names())
    assert ds.frame.select(fl.names()).null_count().sum_horizontal().item() < ds.frame.height * len(fl.names())
