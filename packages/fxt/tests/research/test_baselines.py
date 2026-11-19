"""
Random-entry sampler, probabilistic / deflated Sharpe, control runs, the random baseline.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from fxt.research import Research, Stage
from fxt.research.events import build_events, check_detected, detect_random, uniform_draws
from fxt.research.features import build_features
from fxt.research.harness import (
    compare, deflated_sharpe, evaluate, expected_max_sharpe, load_dataset, moments, psr, random_baseline,
)
from fxt.research.labels import build_labels, build_touches
from fxt.research.models import (
    BarFeaturesConfig, CusumEventsConfig, RandomEventsConfig, SampleWeightsConfig, SideLabelsConfig,
    TakeAllModelConfig,
    TripleBarrierTouchConfig, WalkForwardConfig,
)
from fxt.research.registry import SCHEMA_VERSION, Registry
from fxt.research.store import read_meta
from fxt.research.weights import build_weights
from fxt.testing import BASE_KEY, LakeBuilder, build_stamped_bars, make_ticks

from .test_harness import CV, synth_dataset

SER = {"source": BASE_KEY.source, "market": BASE_KEY.market, "symbol": BASE_KEY.symbol}


#!================================================================================(80)
#! random sampler
#!--------------------------------------------------------------------------------(80)
def hourly_bars(n: int = 20_000) -> pl.DataFrame:
    t0 = datetime(2015, 1, 5, tzinfo=UTC)
    times = [t0 + timedelta(hours=i) for i in range(n)]
    return pl.DataFrame({"time": times, "mid_close": 100 + np.arange(n) * 1e-4}).with_columns(
        pl.col("time").cast(pl.Datetime("us", "UTC")))


def test_random_rate_direction_and_contract():
    bars = hourly_bars()
    cfg = RandomEventsConfig(fire_prob=0.1, seed=3)
    ev = check_detected(detect_random(bars, cfg), "random")
    assert ev.height == pytest.approx(0.1 * (bars.height - cfg.warmup), rel=0.08)
    assert abs(ev["direction"].cast(pl.Float64).mean()) < 0.06
    assert ev["t0"].min() >= bars["time"][cfg.warmup] + timedelta(hours=1)
    #! t0 = bar close, price = that bar's mid
    joined = ev.join(bars.with_columns((pl.col("time") + timedelta(hours=1)).alias("t0")), on="t0")
    assert (joined["price_t0"] == joined["mid_close"]).all()


def test_random_is_deterministic_and_local():
    bars = hourly_bars()
    cfg = RandomEventsConfig(fire_prob=0.2, seed=1)
    a = detect_random(bars, cfg)
    assert a.equals(detect_random(bars, cfg))
    assert not a.equals(detect_random(bars, RandomEventsConfig(fire_prob=0.2, seed=2)))
    #! dropping other bars never moves an event (past the warmup)
    thinned = bars.filter(pl.int_range(pl.len()) % 3 != 0)
    b = detect_random(thinned, cfg)
    cut = thinned["time"][cfg.warmup] + timedelta(hours=1)
    kept = set(thinned["time"].to_list())
    expect = a.filter((pl.col("t0") >= cut) & (pl.col("t0") - timedelta(hours=1)).is_in(list(kept)))
    assert b.filter(pl.col("t0") >= cut).equals(expect)


def test_uniform_draws_look_uniform():
    u, bit = uniform_draws(0, np.arange(1_000_000, 1_200_000) * 3600)
    assert 0 <= u.min() and u.max() < 1
    assert u.mean() == pytest.approx(0.5, abs=0.005)
    assert bit.mean() == pytest.approx(0.5, abs=0.005)
    assert np.corrcoef(u[:-1], u[1:])[0, 1] == pytest.approx(0, abs=0.01)


def test_random_label():
    assert RandomEventsConfig(seed=7).label == "random_p0.0935_s7"


#!================================================================================(80)
#! stats
#!--------------------------------------------------------------------------------(80)
def test_moments_normal():
    x = np.random.default_rng(0).normal(0.1, 1, 200_000)
    sr, sk, ku, n = moments(x)
    assert sr == pytest.approx(0.1, abs=0.01) and sk == pytest.approx(0, abs=0.02)
    assert ku == pytest.approx(3, abs=0.05) and n == 200_000


def test_psr_formula():
    sr, n = 0.05, 1000
    assert psr(sr, n, 0.0, 3.0) == pytest.approx(
        0.5 * (1 + math.erf(sr * math.sqrt(n - 1) / math.sqrt(1 + 0.5 * sr * sr) / math.sqrt(2))))
    assert psr(0.0, 500, 0.0, 3.0) == pytest.approx(0.5)
    #! negative skew and fat tails make a positive Sharpe less convincing
    assert psr(sr, n, -1.0, 8.0) < psr(sr, n, 0.0, 3.0)
    assert math.isnan(psr(sr, 1, 0.0, 3.0))


def test_expected_max_sharpe_matches_simulation():
    rng = np.random.default_rng(1)
    for n_trials in (10, 100, 1000):
        sim = rng.normal(0, 0.02, (4000, n_trials)).max(axis=1).mean()
        assert expected_max_sharpe(n_trials, 0.02 ** 2) == pytest.approx(sim, rel=0.05)
    assert expected_max_sharpe(1, 0.01) == 0 and expected_max_sharpe(50, 0) == 0


def test_deflated_sharpe():
    d1 = deflated_sharpe(0.06, 1500, 0.0, 3.0, 1, [0.06])
    assert d1.sr0 == 0 and d1.dsr == pytest.approx(d1.psr)              # one trial: nothing to deflate
    d = deflated_sharpe(0.06, 1500, 0.0, 3.0, 100, [0.06, -0.02, 0.01, 0.03, -0.01])
    assert d.sr0 > 0 and d.dsr < d.psr and d.n_trials == 100
    assert d.var_sr == pytest.approx(np.var([0.06, -0.02, 0.01, 0.03, -0.01], ddof=1))


#!================================================================================(80)
#! registry v2: controls
#!--------------------------------------------------------------------------------(80)
def start(reg, strategy="s1", **kw):
    return reg.start_run(strategy, ["EURJPY"], {"labels": "a" * 12}, cv_scheme="walk_forward_purged",
                         data_start="2013-01-01", data_end="2023-12-31", **kw)


def test_migrates_v1(tmp_path):
    p = tmp_path / "experiments.db"
    with Registry(p) as r:
        run = start(r)
        r.con.execute("ALTER TABLE runs DROP COLUMN purpose")
        r.con.execute("PRAGMA user_version=1")
    with Registry(p) as r:
        assert r.con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 2
        assert r.runs().row(0, named=True)["purpose"] == "trial"
        assert r.trial_count() == 1 and r.runs()["run_id"].to_list() == [run]
        start(r, purpose="control")                                       # new rows work


def test_controls_dont_count(tmp_path):
    with Registry(tmp_path / "x.db") as r:
        t = start(r)
        c = start(r, "random_p0.0935_s0_follow", purpose="control")
        f = start(r)
        for run, v in ((t, 0.03), (c, 0.5), (f, 0.9)):
            r.log_metric(run, "sharpe_daily", v)
        r.finish_run(t, "done")
        r.finish_run(c, "done")
        r.finish_run(f, "failed")
        assert r.trial_count() == 2                                       # failed trial yes, control no
        assert r.trial_metric("sharpe_daily") == [0.03]                   # only finished trials
        assert r.trial_metric("sharpe_daily", exclude_run=t) == []
        with pytest.raises(ValueError, match="lockbox"):
            start(r, purpose="control", is_lockbox=True)
        with pytest.raises(ValueError, match="purpose"):
            start(r, purpose="nope")


def test_evaluate_records_dsr_and_controls(tmp_path):
    ds = synth_dataset()
    with Registry(tmp_path / "x.db") as r:
        a = evaluate(ds, model=TakeAllModelConfig(), cv=CV, registry=r)
        assert a.aggregate["n_trials"] == 1 and a.aggregate["dsr"] == pytest.approx(a.aggregate["psr"])
        for k in ("sharpe_daily", "skew_daily", "kurt_daily", "n_days"):
            assert k in a.aggregate
        c = evaluate(ds, model=TakeAllModelConfig(), cv=CV, registry=r, purpose="control")
        assert "dsr" not in c.aggregate and "psr" in c.aggregate
        assert r.runs().filter(pl.col("run_id") == c.run_id)["purpose"].item() == "control"
        from fxt.research.models import LogisticModelConfig, SizerConfig
        b = evaluate(ds, model=LogisticModelConfig(), sizer=SizerConfig(rule="threshold"), cv=CV, registry=r)
        assert b.aggregate["n_trials"] == 2                               # the control didn't count
        assert b.aggregate["sr0_daily"] > 0 and b.aggregate["dsr"] < b.aggregate["psr"]
        #! identical trades -> identical Sharpe -> nothing to deflate by
        same = evaluate(ds, model=LogisticModelConfig(), cv=CV, registry=r)
        assert same.aggregate["n_trials"] == 3


#!================================================================================(80)
#! the random baseline, end to end on built stages
#!--------------------------------------------------------------------------------(80)
@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    root = tmp_path_factory.mktemp("baseline_lake")
    lb = LakeBuilder(root / "lake")
    build_stamped_bars(lb, make_ticks(n=500_000, start="2014-12-08"))
    rs = Research(root=root / "research")
    ev = CusumEventsConfig(warmup=24, h=1.5)
    build_events(ev, **SER, lake=lb.lake, research=rs)
    tc = TripleBarrierTouchConfig(events_hash=ev.config_hash(), vertical_bars=6, vol_warmup=12, ambiguity="ohlc")
    build_touches(tc, **SER, lake=lb.lake, research=rs)
    lc = SideLabelsConfig(touches_hash=tc.config_hash())
    build_labels(lc, **SER, research=rs)
    build_weights(SampleWeightsConfig(labels_hash=lc.config_hash()), **SER, lake=lb.lake, research=rs)
    fc = BarFeaturesConfig(short=6, long=12, ret_horizons=(1, 4))
    build_features(fc, **SER, lake=lb.lake, research=rs)
    return lb, rs, lc, tc, fc


def test_random_baseline(chain, tmp_path):
    lb, rs, lc, tc, fc = chain
    cv = WalkForwardConfig(lockbox_year=2016, first_test_year=2015, drop_start_days=2)
    with Registry(tmp_path / "x.db") as reg:
        base = random_baseline(rs, lb.lake, reg, like_labels=lc.config_hash(), **SER, seeds=range(2),
                               fire_prob=0.3, features_hashes=fc.config_hash(), cv=cv)
        assert base.runs.height == 2 and not base.runs["reused"].any()
        assert reg.trial_count() == 0 and reg.runs()["purpose"].unique().to_list() == ["control"]
        #! same barriers as the candidate, just other events
        for h in base.runs["touches"]:
            [(_, p)] = rs.scan(Stage.TOUCHES, config=h, **SER)[:1]
            cfg = read_meta(p).config
            assert {k: v for k, v in cfg.items() if k != "events_hash"} == \
                   {k: v for k, v in tc.payload().items() if k != "events_hash"}
        #! more seeds: the first two are reused, not rebuilt or re-run
        more = random_baseline(rs, lb.lake, reg, like_labels=lc.config_hash(), **SER, seeds=range(3),
                               fire_prob=0.3, features_hashes=fc.config_hash(), cv=cv)
        assert more.runs["reused"].to_list() == [True, True, False]
        assert reg.runs().height == 3
        ds = load_dataset(rs, lb.lake, labels_hash=lc.config_hash(), features_hashes=fc.config_hash(), **SER)
        cand = evaluate(ds, model=TakeAllModelConfig(), cv=cv, registry=reg)
        cmp = compare(more, reg, cand.run_id)
        assert cmp["metric"].to_list() == ["gross_bp", "net_bp", "sharpe_ann", "hit_rate"]
        assert cmp["p_value"].is_between(0, 1).all()


def test_sqlite_has_drop_column():
    assert sqlite3.sqlite_version_info >= (3, 35)
