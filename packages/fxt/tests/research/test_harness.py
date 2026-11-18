"""
Evaluation harness (ML pipeline spec §9): folds, costs, sizing, metrics, models, evaluate().
"""
from __future__ import annotations

import itertools
import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from fxt.research import Research
from fxt.research.events import build_events
from fxt.research.features import build_features
from fxt.research.harness import (
    PREDICTION_COLUMNS, Dataset, MissingQuoteError, apply_sizer, auc, classifier_metrics, daily_pnl,
    data_starts, evaluate, fit_logistic, fit_predict, load_dataset, make_folds, sigmoid, simulate,
    trade_costs, trading_metrics, usable_mask,
)
from fxt.research.labels import build_labels, build_touches
from fxt.research.models import (
    BacktestConfig, BarFeaturesConfig, CusumEventsConfig, LogisticModelConfig, SampleWeightsConfig,
    SideLabelsConfig, SizerConfig, TakeAllModelConfig, TripleBarrierTouchConfig, WalkForwardConfig,
)
from fxt.research.registry import LockboxAlreadyUsed, Registry
from fxt.research.weights import build_weights, business_coord
from fxt.testing import BASE_KEY, LakeBuilder, build_stamped_bars, make_ticks

UTC0 = datetime(2014, 1, 6, tzinfo=UTC)          # a Monday


#!================================================================================(80)
#! synthetic dataset
#!--------------------------------------------------------------------------------(80)
def weekday_hours(start: datetime, end: datetime) -> list[datetime]:
    out, t = [], start
    while t < end:
        if t.weekday() < 5:
            out.append(t)
        t += timedelta(hours=1)
    return out


def synth_dataset(seed: int = 3, start: datetime = UTC0, end: datetime = datetime(2018, 1, 1, tzinfo=UTC),
                  every: int = 9, symbol: str = "TESTJPY") -> Dataset:
    """ Events every `every` bars; meta_label driven by feature x (so a model can learn it). """
    rng = np.random.default_rng(seed)
    times = weekday_hours(start, end)
    n = len(times)
    price = 100 * np.exp(np.cumsum(rng.normal(0, 1e-4, n)))
    bars = pl.DataFrame({
        "time": times,
        "bid_close": price - 0.01, "ask_close": price + 0.01, "mid_close": price,
        "spread_mean": np.full(n, 0.01),
    }).with_columns(pl.col("time").cast(pl.Datetime("us", "UTC")))
    clock = bars.get_column("time").dt.epoch("s").to_numpy()

    rows = []
    for k, i in enumerate(range(60, n - 60, every)):
        t0 = times[i] + timedelta(hours=1)
        x = rng.normal()
        y = int(x + rng.normal(0, 0.7) > 0.6)
        hold = int(rng.integers(3, 30))
        vertical = hold >= 24 and not y
        j = i + (24 if vertical else hold)
        t1 = times[j] + timedelta(hours=1) if vertical else times[j] + timedelta(minutes=17)
        side = 1 if k % 2 else -1
        ret = 0.0001 if vertical else (0.005 if y else -0.005)
        rows.append({
            "event_id": f"e{k:05d}", "symbol": symbol, "t0": t0, "t1": t1, "side": side,
            "touch": "vertical" if vertical else ("upper" if (y == 1) == (side == 1) else "lower"),
            "outcome": "timeout" if vertical else ("pt" if y else "sl"), "meta_label": y, "ret": ret,
            "hours_to_exit": float(j - i), "exit_gap": False, "price_t0": price[i],
            "exit_price": price[i] * math.exp(side * ret), "x": x, "noise": rng.normal(),
        })
    frame = pl.DataFrame(rows).with_columns(pl.col("t0", "t1").cast(pl.Datetime("us", "UTC")),
                                            pl.col("side", "meta_label").cast(pl.Int8))
    t0e = frame.get_column("t0").dt.epoch("s").to_numpy()
    t1e = frame.get_column("t1").dt.epoch("s").to_numpy() + np.where(frame["touch"] == "vertical", 0, 60)
    ls, le = business_coord(t0e, clock), business_coord(t1e, clock)
    frame = frame.with_columns(pl.Series("life_start", ls), pl.Series("life_end", le),
                               pl.lit(0.33).alias("uniqueness"), pl.lit(1.0).alias("weight"),
                               pl.lit(1.0).alias("weight_uniq"))
    return Dataset(source="dukascopy", market="forex", symbol=symbol, strategy_id="synth_follow",
                   frame=frame, feature_names=("x", "noise"), bars=bars,
                   hashes={"events": "a" * 12, "touches": "b" * 12, "labels": "c" * 12,
                           "weights": "d" * 12, "features": "e" * 12})


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return synth_dataset()


CV = WalkForwardConfig(lockbox_year=2017, first_test_year=2015)


#!================================================================================(80)
#! folds
#!--------------------------------------------------------------------------------(80)
def test_folds_expanding_purged(ds):
    clock = ds.bars.get_column("time").dt.epoch("s").to_numpy()
    folds = make_folds(ds.frame, clock, CV)
    assert [f.test_year for f in folds] == [2015, 2016]
    t0 = ds.frame.get_column("t0")
    le = ds.frame.get_column("life_end").to_numpy()
    for f in folds:
        start = datetime(f.test_year, 1, 1, tzinfo=UTC)
        b0 = business_coord(np.array([int(start.timestamp())]), clock)[0]
        assert (t0.filter(pl.Series(f.test)).dt.year() == f.test_year).all()
        assert (t0.filter(pl.Series(f.train)) < start).all()
        assert not (le[f.train] > b0).any()                       # no training life reaches the test block
        #! the purged ones are exactly the pre-test events whose life crosses into the test year
        cross = (t0 < start).to_numpy() & (le > b0) & usable_mask(ds.frame, clock, CV)
        assert f.purged == int(cross.sum()) and f.purged > 0
        assert f.embargoed == 0                                  # walk-forward: nothing after the test block
    assert folds[1].n_train > folds[0].n_train                   # expanding
    assert not (folds[0].test & folds[1].test).any()


def test_lockbox_fold(ds):
    clock = ds.bars.get_column("time").dt.epoch("s").to_numpy()
    [f] = make_folds(ds.frame, clock, CV, lockbox=True)
    assert f.test_year == 2017
    assert (ds.frame.get_column("t0").filter(pl.Series(f.train)).dt.year() < 2017).all()


def test_embargo_applies_after_the_test_block():
    clock = np.arange(0, 3600 * 24 * 800, 3600, dtype=np.int64) + int(datetime(2015, 1, 1, tzinfo=UTC).timestamp())
    def at(dt):
        return business_coord(np.array([int(dt.timestamp())]), clock)[0]
    frame = pl.DataFrame({
        "t0": [datetime(2015, 6, 1, tzinfo=UTC), datetime(2017, 1, 1, 10, tzinfo=UTC)],
        "life_start": [at(datetime(2015, 6, 1, tzinfo=UTC)), at(datetime(2017, 1, 1, 10, tzinfo=UTC))],
        "life_end": [at(datetime(2015, 6, 2, tzinfo=UTC)), at(datetime(2017, 1, 2, tzinfo=UTC))],
    })
    cfg = WalkForwardConfig(lockbox_year=2018, first_test_year=2016, drop_start_days=0)
    [f, _] = make_folds(frame, clock, cfg)
    #! the 2017 event isn't a walk-forward training candidate for the 2016 fold at all
    assert f.train.tolist() == [True, False] and f.embargoed == 0


def test_start_of_data_and_restart_drop():
    hours = weekday_hours(UTC0, UTC0 + timedelta(days=20)) + \
        weekday_hours(UTC0 + timedelta(days=60), UTC0 + timedelta(days=90))
    clock = np.array([int(t.timestamp()) for t in hours])
    cfg = WalkForwardConfig(drop_start_days=7, restart_gap_days=7)
    assert len(data_starts(clock, cfg)) == 2
    t0 = [UTC0 + timedelta(days=d, hours=10) for d in (1, 8, 61, 68)]
    mask = usable_mask(pl.DataFrame({"t0": t0}), clock, cfg)
    assert mask.tolist() == [False, True, False, True]


#!================================================================================(80)
#! costs, sizing, simulation
#!--------------------------------------------------------------------------------(80)
def test_trade_costs_quotes(ds):
    bt = BacktestConfig(slippage_pips=0.5, commission_bp=0.3)
    c = trade_costs(ds.frame, ds.bars, bt, "TESTJPY")
    assert c.height == ds.frame.height and c["event_id"].to_list() == ds.frame["event_id"].to_list()
    assert np.allclose(c["half_spread_entry"], 0.01)
    vert = c.filter(pl.col("touch") == "vertical")
    barrier = c.filter(pl.col("touch") != "vertical")
    assert vert.height and barrier.height
    assert np.allclose(vert["half_spread_exit"], 0.01) and np.allclose(barrier["half_spread_exit"], 0.005)
    r = c.row(0, named=True)
    expect = (r["half_spread_entry"] / r["price_t0"] + r["half_spread_exit"] / r["exit_price"]
              + 2 * 0.5 * 0.01 / r["price_t0"] + 0.3e-4)
    assert r["cost"] == pytest.approx(expect, rel=1e-12)


def test_trade_costs_missing_bar(ds):
    bars = ds.bars.filter(pl.col("time") != (ds.frame["t0"][0] - timedelta(hours=1)))
    with pytest.raises(MissingQuoteError):
        trade_costs(ds.frame, bars, BacktestConfig(), "TESTJPY")


def test_pip_size():
    assert BacktestConfig().pip("EURJPY") == 0.01
    assert BacktestConfig().pip("EURUSD") == 0.0001
    assert BacktestConfig(pip_size=0.5).pip("EURUSD") == 0.5


def test_sizers():
    p = np.array([0.2, 0.5, 0.6, 0.9])
    assert apply_sizer(p, SizerConfig()).tolist() == [1, 1, 1, 1]
    assert apply_sizer(p, SizerConfig(rule="threshold", threshold=0.5)).tolist() == [0, 0, 1, 1]
    assert apply_sizer(p, SizerConfig(rule="linear", threshold=0.5, cap=2)) == pytest.approx([0, 0, 0.4, 1.6])


def test_simulate_position_cap():
    h = [datetime(2020, 1, 6, k, tzinfo=UTC) for k in range(24)]
    pred = pl.DataFrame({"t0": [h[0], h[1], h[2], h[5]], "t1": [h[4], h[3], h[6], h[7]],
                         "size": [1.0, 1.0, 1.0, 1.0], "ret": [0.01] * 4, "cost": [0.001] * 4})
    out = simulate(pred, BacktestConfig(position_cap=1.5))
    #! open at h2: trade 0 (1.0) + trade 1 (0.5) -> trade 2 gets 0; at h5 trades 0/1 have exited -> full size
    assert out["size"].to_list() == [1.0, 0.5, 0.0, 1.0]
    assert out["net"].to_list() == pytest.approx([0.009, 0.0045, 0.0, 0.009])
    assert simulate(pred, BacktestConfig())["size"].to_list() == [1.0] * 4


#!================================================================================(80)
#! metrics
#!--------------------------------------------------------------------------------(80)
def brute_auc(y, p, w):
    num = den = 0.0
    for i, j in itertools.product(range(len(y)), repeat=2):
        if y[i] == 1 and y[j] == 0:
            den += w[i] * w[j]
            num += w[i] * w[j] * (1.0 if p[i] > p[j] else 0.5 if p[i] == p[j] else 0.0)
    return num / den


def test_auc_matches_brute_force():
    rng = np.random.default_rng(1)
    y = (rng.random(60) < 0.4).astype(float)
    p = np.round(rng.random(60), 1)                               # plenty of ties
    w = rng.random(60) + 0.1
    assert auc(y, p, w) == pytest.approx(brute_auc(y, p, w))
    assert auc(y, p) == pytest.approx(brute_auc(y, p, np.ones(60)))
    assert auc(y, np.full(60, 0.3)) == 0.5
    assert math.isnan(auc(np.ones(5), np.random.default_rng(0).random(5)))


def test_classifier_metrics():
    y = np.array([1, 0, 0, 1, 0, 0, 0, 1], dtype=float)
    m = classifier_metrics(y, np.full(8, 3 / 8), 3 / 8)
    assert m["log_loss_skill"] == pytest.approx(0) and m["ece"] == pytest.approx(0) and m["auc"] == 0.5
    perfect = classifier_metrics(y, y * 0.98 + 0.01, 3 / 8)
    assert perfect["auc"] == 1 and perfect["log_loss_skill"] > 0.9
    #! weights: doubling every weight changes nothing; weighting one class shifts the base rate
    w = np.where(y == 1, 3.0, 1.0)
    assert classifier_metrics(y, y * 0.5 + 0.2, 0.4, 2 * w) == pytest.approx(classifier_metrics(y, y * 0.5 + 0.2, 0.4, w))
    assert classifier_metrics(y, y * 0.5 + 0.2, 0.4, w)["base_rate"] == pytest.approx(9 / 14)


def test_daily_pnl_books_on_exit_day():
    trades = pl.DataFrame({
        "t1": [datetime(2020, 1, 6, 10, tzinfo=UTC), datetime(2020, 1, 12, 22, 30, tzinfo=UTC),   # Mon, Sun
               datetime(2020, 1, 13, 1, tzinfo=UTC)],
        "net": [1.0, 2.0, 4.0],
    })
    pnl = daily_pnl(trades, datetime(2020, 1, 6, tzinfo=UTC), datetime(2020, 1, 14, tzinfo=UTC))
    assert len(pnl) == 7                                           # Mon 6 .. Tue 14 weekdays
    assert pnl.tolist() == [1, 0, 0, 0, 0, 6, 0]                  # Sunday's exit counts on Monday 13


def test_trading_metrics_by_hand():
    d = [datetime(2020, 1, 6 + k, 12, tzinfo=UTC) for k in range(4)]
    trades = pl.DataFrame({"t1": d, "size": [1.0, 2.0, 1.0, 0.0], "gross": [0.002, -0.002, 0.003, 0.0],
                           "net": [0.001, -0.004, 0.002, 0.0], "cost": [0.001] * 4,
                           "hours_to_exit": [10.0, 20.0, 30.0, 40.0], "uniqueness": [0.5, 0.5, 0.5, 0.5]})
    m = trading_metrics(trades, datetime(2020, 1, 6, tzinfo=UTC), datetime(2020, 1, 9, tzinfo=UTC), BacktestConfig())
    assert m["n_trades"] == 3 and m["turnover"] == 4                        # the size-0 row isn't a trade
    assert m["net_bp"] == pytest.approx(1e4 * -0.001 / 4)
    assert m["gross_bp"] == pytest.approx(1e4 * 0.003 / 4)
    assert m["hit_rate"] == pytest.approx(2 / 3)
    assert m["max_dd_bp"] == pytest.approx(40)                              # +10 bp then -40 bp
    pnl = np.array([0.001, -0.004, 0.002, 0.0])
    assert m["sharpe_ann"] == pytest.approx(pnl.mean() / pnl.std(ddof=1) * math.sqrt(252))
    assert m["n_eff"] == pytest.approx(1.5)


#!================================================================================(80)
#! models
#!--------------------------------------------------------------------------------(80)
def test_logistic_recovers_coefficients():
    rng = np.random.default_rng(0)
    X = np.column_stack([np.ones(20_000), rng.normal(size=(20_000, 2))])
    beta = np.array([-0.5, 1.2, -0.7])
    y = (rng.random(20_000) < sigmoid(X @ beta)).astype(float)
    b = fit_logistic(X, y, np.ones(len(y)), l2=0.0, max_iter=50, tol=1e-12)
    assert b == pytest.approx(beta, abs=0.06)
    #! the penalty shrinks the slopes, not the intercept's role
    b2 = fit_logistic(X, y, np.ones(len(y)), l2=1.0, max_iter=50, tol=1e-12)
    assert np.abs(b2[1:]).sum() < np.abs(b[1:]).sum()


def test_logistic_optimality_with_weights():
    rng = np.random.default_rng(2)
    X = np.column_stack([np.ones(500), rng.normal(size=(500, 3))])
    y = (rng.random(500) < 0.3).astype(float)
    w = rng.random(500) * 3
    b = fit_logistic(X, y, w, l2=0.05, max_iter=50, tol=1e-12)
    p = sigmoid(X @ b)
    grad = X.T @ (w * (p - y)) / w.sum() + 0.05 * np.r_[0, b[1:]]
    assert np.abs(grad).max() < 1e-9


def test_fit_predict_handles_nan_and_constant_columns():
    rng = np.random.default_rng(4)
    X = rng.normal(size=(300, 3))
    X[:, 2] = 5.0                                                  # constant
    X[::7, 0] = np.nan
    y = (X[:, 1] > 0).astype(float)
    p = fit_predict(LogisticModelConfig(), X, y, np.ones(300), X)
    assert np.isfinite(p).all() and auc(y, p) > 0.95
    assert fit_predict(TakeAllModelConfig(), X, y, np.where(y == 1, 3.0, 1.0), X[:5]) == pytest.approx(
        [3 * y.sum() / (3 * y.sum() + (300 - y.sum()))] * 5)


#!================================================================================(80)
#! evaluate
#!--------------------------------------------------------------------------------(80)
@pytest.fixture
def reg(tmp_path):
    with Registry(tmp_path / "experiments.db") as r:
        yield r


def test_evaluate_records_a_run(ds, reg, tmp_path):
    rs = Research(root=tmp_path / "research")
    res = evaluate(ds, model=LogisticModelConfig(), cv=CV, registry=reg, research=rs)
    run = reg.runs().row(0, named=True)
    assert run["status"] == "done" and run["strategy_id"] == "synth_follow" and run["is_lockbox"] == 0
    assert run["data_end"] == "2016-12-31"
    used = reg.run_configs(res.run_id)
    assert set(used) == {"events", "touches", "labels", "weights", "features", "model", "sizer", "backtest", "cv"}
    assert used["model"] == LogisticModelConfig().config_hash()
    assert reg.config(used["model"])["stage"] == "model"
    m = reg.metrics(res.run_id)
    assert set(m["fold"].drop_nulls().to_list()) == {0, 1}
    assert m.filter(pl.col("fold").is_null() & (pl.col("name") == "n_trades"))["value"].item() == res.trades.height
    #! predictions on disk, out-of-fold only, never the lockbox year
    out = rs.root / "predictions" / f"run={res.run_id}" / "TESTJPY.parquet"
    pred = pl.read_parquet(out)
    assert pred.columns == list(PREDICTION_COLUMNS) and pred["event_id"].is_unique().all()
    assert set(pred["t0"].dt.year().unique()) == {2015, 2016}
    #! the feature drives the label, so the model should beat the base rate
    assert res.aggregate["clf_auc"] > 0.75 and res.aggregate["clf_log_loss_skill"] > 0.1
    assert reg.trial_count("synth_follow") == 1


def test_take_all_has_no_skill(ds):
    res = evaluate(ds, model=TakeAllModelConfig(), cv=CV, registry=None)
    assert res.run_id is None
    assert res.aggregate["clf_auc"] == pytest.approx(0.5) and res.aggregate["n_trades"] == res.trades.height
    assert res.aggregate["clf_auc_pooled"] != pytest.approx(0.5)         # why the headline is per fold
    for row in res.folds.iter_rows(named=True):
        assert row["clf_log_loss_skill"] == pytest.approx(0, abs=1e-12)


def test_threshold_sizer_trades_less_and_better(ds):
    base = evaluate(ds, model=LogisticModelConfig(), cv=CV, registry=None)
    picky = evaluate(ds, model=LogisticModelConfig(), sizer=SizerConfig(rule="threshold", threshold=0.5),
                     cv=CV, registry=None)
    assert 0 < picky.aggregate["n_trades"] < base.aggregate["n_trades"]
    assert picky.aggregate["net_bp"] > base.aggregate["net_bp"]


def test_failed_run_is_recorded(ds, reg):
    cv = WalkForwardConfig(lockbox_year=2017, first_test_year=2014)    # first fold has no training data
    with pytest.raises(ValueError, match="fold 0"):
        evaluate(ds, model=TakeAllModelConfig(), cv=cv, registry=reg)
    assert reg.runs()["status"].to_list() == ["failed"]
    assert reg.trial_count() == 1


def test_lockbox_once(ds, reg):
    res = evaluate(ds, model=TakeAllModelConfig(), cv=CV, lockbox=True, registry=reg)
    assert set(res.trades["t0"].dt.year().unique()) == {2017}
    assert reg.runs()["is_lockbox"].to_list() == [1]
    with pytest.raises(LockboxAlreadyUsed):
        evaluate(ds, model=LogisticModelConfig(), cv=CV, lockbox=True, registry=reg)


def test_unknown_model_feature(ds):
    with pytest.raises(ValueError, match="not in the features config"):
        evaluate(ds, model=LogisticModelConfig(features=("nope",)), cv=CV, registry=None)


def test_harness_config_hashes_pinned():
    """ Changing these orphans recorded runs' config rows: bump the class version instead. """
    pinned = {c.get_id(): c.config_hash() for c in (WalkForwardConfig(), BacktestConfig(), TakeAllModelConfig(),
                                                     LogisticModelConfig(), SizerConfig())}
    assert pinned == PINNED


PINNED = {"WalkForwardConfig@1": "a3b1afbed6c2", "BacktestConfig@1": "2359a1a61a9b",
          "TakeAllModelConfig@1": "4796d3accfbb", "LogisticModelConfig@1": "4d22b654c996",
          "SizerConfig@1": "66cedc144eff"}


#!================================================================================(80)
#! dataset from real stage builds
#!--------------------------------------------------------------------------------(80)
SER = {"source": BASE_KEY.source, "market": BASE_KEY.market, "symbol": BASE_KEY.symbol}


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    root = tmp_path_factory.mktemp("harness_lake")
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
    fc = BarFeaturesConfig(short=6, long=12)
    build_features(fc, **SER, lake=lb.lake, research=rs)
    return lb, rs, ev, tc, lc, fc


def test_load_dataset(chain):
    lb, rs, ev, tc, lc, fc = chain
    ds = load_dataset(rs, lb.lake, labels_hash=lc.config_hash(), features_hash=fc.config_hash(), **SER)
    assert ds.strategy_id == "cusum_h3_follow"
    assert ds.hashes == {"events": ev.config_hash(), "touches": tc.config_hash(), "labels": lc.config_hash(),
                         "weights": SampleWeightsConfig(labels_hash=lc.config_hash()).config_hash(),
                         "features": fc.config_hash()}
    assert ds.feature_names == fc.names()
    f = ds.frame
    assert f.height > 0 and f["meta_label"].null_count() == 0 and f["t0"].is_sorted()
    assert f["price_t0"].null_count() == 0 and f["uniqueness"].null_count() == 0
    assert set(fc.names()) <= set(f.columns)
    #! every event bar has a quote: costs can be computed
    c = trade_costs(f, ds.bars, BacktestConfig(), ds.symbol)
    assert c["cost"].null_count() == 0 and (c["cost"] > 0).all()
