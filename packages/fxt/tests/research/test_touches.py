"""
Touch pass: triple-barrier labeling step 1 (ML pipeline spec §6.1).
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError

from fxt.research import Research, Stage
from fxt.research.events import build_events
from fxt.research.labels import (
    TOUCH_SCHEMA, EventsBarsMismatch, InputEventsError, LakeTicks, MinuteBars, barrier_vol,
    build_touches, check_touches, compute_touches,
)
from fxt.research.models import CusumEventsConfig, TouchesMeta, TripleBarrierTouchConfig
from fxt.research.store import read_table
from fxt.testing import BASE_KEY, LakeBuilder, build_stamped_bars, make_ticks

EV_HASH = CusumEventsConfig().config_hash()
START = datetime(2020, 1, 6)                      # a Monday


#!================================================================================(80)
#! hand-built scenario
#!--------------------------------------------------------------------------------(80)
class Scenario:
    """ Hourly bars with alternating ±1e-4 log returns (vol ~1e-4) and flat 1MIN bars at
        each hour's close, so nothing touches unless a test edits a minute bar.
    """

    def __init__(self, n_hours: int = 60, event_hour: int = 30, N: int = 6, k: float = 1.0,
                 skip_hours: tuple[int, ...] = (), **cfg):
        self.cfg = TripleBarrierTouchConfig(events_hash=EV_HASH, vertical_bars=N, k=k, vol_warmup=10,
                                            vol_span=10, **cfg)
        hours = [h for h in range(n_hours + len(skip_hours)) if h not in skip_hours][:n_hours]
        rets = np.array([1e-4 if i % 2 else -1e-4 for i in range(len(hours))])
        rets[0] = 0.0
        close = 100.0 * np.exp(np.cumsum(rets))
        self.htimes = [START + timedelta(hours=h) for h in hours]
        self.hourly = pl.DataFrame({"time": self.htimes, "mid_close": close}).with_columns(
            pl.col("time").cast(pl.Datetime("us")))
        mt = [t + timedelta(minutes=m) for t in self.htimes for m in range(60)]
        mp = np.repeat(close, 60)
        self.minute = pl.DataFrame({"time": mt, "mid_open": mp, "mid_high": mp, "mid_low": mp,
                                    "mid_close": mp}).with_columns(pl.col("time").cast(pl.Datetime("us")))
        self.i = event_hour
        self.t0 = self.htimes[event_hour] + timedelta(hours=1)
        self.px = float(close[event_hour])
        vol = barrier_vol(self.hourly, self.cfg)[event_hour]
        self.half = self.cfg.mult * vol
        self.upper, self.lower = self.px * math.exp(self.half), self.px * math.exp(-self.half)

    def events(self, t0: datetime | None = None, px: float | None = None) -> pl.DataFrame:
        return pl.DataFrame({"event_id": ["e1"], "t0": [(t0 or self.t0).replace(tzinfo=UTC)],
                             "price_t0": [px if px is not None else self.px]}).with_columns(
            pl.col("t0").cast(pl.Datetime("us", "UTC")))

    def edit(self, minutes_after_t0: int, **values: float) -> None:
        t = (self.t0 + timedelta(minutes=minutes_after_t0))
        self.minute = self.minute.with_columns(
            pl.when(pl.col("time") == t).then(pl.lit(v)).otherwise(pl.col(f"mid_{k}")).alias(f"mid_{k}")
            for k, v in values.items())

    def run(self, **kw) -> dict:
        events = kw.pop("events", None)
        out = compute_touches(self.events() if events is None else events, self.hourly,
                              MinuteBars.from_frame(self.minute), kw.pop("cfg", self.cfg), **kw)
        assert dict(out.schema) == TOUCH_SCHEMA and out.height == 1
        return out.row(0, named=True)


def utc(t: datetime) -> datetime:
    return t.replace(tzinfo=UTC)


#!================================================================================(80)
#! outcomes
#!--------------------------------------------------------------------------------(80)
def test_timeout():
    s = Scenario()
    r = s.run()
    vertical = utc(s.htimes[s.i + 6] + timedelta(hours=1))
    assert r["touch"] == "vertical" and r["reason"] is None and r["resolution"] is None
    assert r["vertical_time"] == r["t1"] == vertical
    assert r["exit_price"] == s.minute.filter(pl.col("time") < vertical.replace(tzinfo=None))["mid_close"][-1]
    assert r["hours_to_exit"] == 6.0
    assert r["max_up"] < r["half_width"] and r["max_down"] < r["half_width"]
    assert r["half_width"] == pytest.approx(math.sqrt(6) * r["vol"])


def test_upper_touch():
    s = Scenario()
    s.edit(90, high=s.upper * 1.00001)
    r = s.run()
    assert r["touch"] == "upper" and r["resolution"] == "bar" and not r["exit_gap"]
    assert r["t1"] == utc(s.t0 + timedelta(minutes=90))
    assert r["exit_price"] == s.upper
    assert r["ret"] == pytest.approx(s.half)
    assert r["hours_to_exit"] == pytest.approx(1.5)
    assert r["max_up"] == pytest.approx(math.log(s.upper * 1.00001 / s.px))


def test_lower_gap_exits_at_the_open():
    s = Scenario()
    s.edit(5, open=s.lower * 0.999, low=s.lower * 0.999)
    r = s.run()
    assert r["touch"] == "lower" and r["exit_gap"]
    assert r["exit_price"] == s.lower * 0.999                      # the open, not the barrier
    assert r["exit_price"] < r["lower"]


def test_first_touch_wins():
    s = Scenario()
    s.edit(200, high=s.upper * 1.001)
    s.edit(100, low=s.lower * 0.999)
    assert s.run()["touch"] == "lower"


@pytest.mark.parametrize("o, c, expect", [(100.0, 100.001, "upper"), (100.001, 100.0, "lower")])
def test_ambiguity_ohlc_uses_open_to_close(o, c, expect):
    s = Scenario(ambiguity="ohlc")
    s.edit(10, open=o, close=c, high=s.upper * 1.001, low=s.lower * 0.999)
    r = s.run()
    assert r["touch"] == expect and r["resolution"] == "ohlc_fallback"


def test_ambiguity_flat_bar_picks_the_barrier_nearer_the_open():
    s = Scenario(ambiguity="ohlc")
    near_upper = s.upper - (s.upper - s.lower) * 0.1
    s.edit(10, open=near_upper, close=near_upper, high=s.upper * 1.001, low=s.lower * 0.999)
    assert s.run()["touch"] == "upper"


class FakeTicks:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def first_touch(self, start_s, end_s, upper, lower):
        self.calls.append((start_s, end_s))
        return self.answer


def test_ambiguity_ticks():
    s = Scenario()
    s.edit(10, open=100.0, close=100.001, high=s.upper * 1.001, low=s.lower * 0.999)  # ohlc would say up
    ticks = FakeTicks(-1)
    r = s.run(ticks=ticks)
    assert r["touch"] == "lower" and r["resolution"] == "tick"
    t = int(utc(s.t0 + timedelta(minutes=10)).timestamp())
    assert ticks.calls == [(t, t + 60)]                           # only that one minute

    r = s.run(ticks=FakeTicks(None))                               # no tick crosses: fall back
    assert r["touch"] == "upper" and r["resolution"] == "ohlc_fallback"

    with pytest.raises(ValueError, match="needs ticks"):
        s.run()


#!================================================================================(80)
#! insufficient data
#!--------------------------------------------------------------------------------(80)
def test_insufficient_reasons():
    s = Scenario(n_hours=40, event_hour=36, N=6)
    assert s.run()["reason"] == "end_of_data"

    s = Scenario(event_hour=5)                                     # before vol_warmup returns
    r = s.run()
    assert (r["touch"], r["reason"]) == ("insufficient_data", "warmup")
    assert r["t1"] is None and r["upper"] is None

    s = Scenario()
    r = s.run(minute_years={2019})
    assert (r["touch"], r["reason"]) == ("insufficient_data", "minute_data_missing")
    assert r["upper"] is not None                                  # barriers were placed

    s = Scenario()
    s.minute = s.minute.filter(pl.col("time") < s.t0)
    assert s.run()["reason"] == "no_minute_bars"


def test_horizon_counts_bars_of_data():
    """ Missing hours (a weekend, a holiday) don't count: the vertical barrier is N *bars* on. """
    s = Scenario(event_hour=30, N=6, skip_hours=(33, 34, 35))
    r = s.run()
    assert r["vertical_time"] == utc(s.htimes[36] + timedelta(hours=1))
    assert r["vertical_time"] - r["t0"] == timedelta(hours=9)


#!================================================================================(80)
#! guards
#!--------------------------------------------------------------------------------(80)
def test_events_must_match_the_bars():
    s = Scenario()
    with pytest.raises(EventsBarsMismatch, match="no matching hourly bar"):
        s.run(events=s.events(t0=s.t0 + timedelta(minutes=30)))
    with pytest.raises(EventsBarsMismatch, match="rebuilt"):
        s.run(events=s.events(px=s.px * 1.01))


def test_point_in_time():
    """ Nothing after the vertical barrier changes a touch; nothing in the window changes the barriers. """
    s = Scenario()
    s.edit(90, high=s.upper * 1.00001)
    base = s.run()
    vertical = (s.htimes[s.i + 6] + timedelta(hours=1))

    s.minute = s.minute.with_columns(pl.when(pl.col("time") >= vertical).then(pl.col("mid_high") * 1.1)
                                     .otherwise(pl.col("mid_high")).alias("mid_high"))
    assert s.run() == base
    vol_before = barrier_vol(s.hourly, s.cfg)[s.i]
    later = s.hourly.with_columns(pl.when(pl.col("time") > s.htimes[s.i]).then(pl.col("mid_close") * 1.05)
                                  .otherwise(pl.col("mid_close")))
    assert barrier_vol(later, s.cfg)[s.i] == vol_before


def test_check_touches_catches_bad_rows():
    s = Scenario()
    s.edit(90, high=s.upper * 1.00001)
    out = compute_touches(s.events(), s.hourly, MinuteBars.from_frame(s.minute), s.cfg)
    assert all(c.ok for c in check_touches(out))
    broken = out.with_columns(pl.lit(s.upper * 0.99).alias("exit_price"))
    assert [c.name for c in check_touches(broken) if not c.ok] == ["touches: upper exits at/above barrier"]


#!================================================================================(80)
#! config
#!--------------------------------------------------------------------------------(80)
def test_config():
    cfg = TripleBarrierTouchConfig(events_hash=EV_HASH)
    assert cfg.config_hash() == "5e8aa6660716"                    # pinned: stored touches are keyed by it
    assert cfg.input_hashes() == {"events": EV_HASH}
    assert cfg.mult == pytest.approx(math.sqrt(48))
    assert cfg.label == "tb_k1_n48"
    assert TripleBarrierTouchConfig(events_hash=EV_HASH, k=1).config_hash() == cfg.config_hash()
    with pytest.raises(ValidationError):
        TripleBarrierTouchConfig()                                  # type: ignore[call-arg]


#!================================================================================(80)
#! builder
#!--------------------------------------------------------------------------------(80)
SER = {"source": BASE_KEY.source, "market": BASE_KEY.market, "symbol": BASE_KEY.symbol}
EVCFG = CusumEventsConfig(warmup=24)


@pytest.fixture(scope="module")
def lake_with_events(tmp_path_factory):
    root = tmp_path_factory.mktemp("touch_lake")
    lb = LakeBuilder(root / "lake")
    build_stamped_bars(lb, make_ticks(n=400_000, start="2014-12-15"))
    rs = Research(root=root / "research")
    build_events(EVCFG, **SER, lake=lb.lake, research=rs)
    return lb, rs


def cfg(**kw) -> TripleBarrierTouchConfig:
    return TripleBarrierTouchConfig(events_hash=EVCFG.config_hash(), vertical_bars=12, ambiguity="ohlc", **kw)


def test_build_writes_touches(lake_with_events):
    lb, rs = lake_with_events
    res = build_touches(cfg(), **SER, lake=lb.lake, research=rs)

    ev_years = [k.year for k, _ in rs.scan(Stage.EVENTS, config=EVCFG.config_hash())]
    assert [k.year for k, _ in rs.scan(Stage.TOUCHES, config=res.config_hash)] == ev_years
    n_events = sum(read_table(p)[1].rows for _, p in rs.scan(Stage.EVENTS, config=EVCFG.config_hash()))
    assert res.touches.height == n_events
    for p in res.paths:
        df, meta = read_table(p)
        assert isinstance(meta, TouchesMeta) and meta.passed
        assert meta.input_hashes == {"events": EVCFG.config_hash()}
        assert (df["t0"].dt.year() == meta.year).all()
        roots = {(i.root, i.typeid) for i in meta.inputs}
        assert ("research", "EventsMeta@1") in roots and ("lake", "BarsMeta@1") in roots
        assert {i.path.split("/interval=")[-1].split("/")[0] for i in meta.inputs if i.root == "lake"} \
            == {"1HOUR", "1MIN"}
        assert tuple(df.columns) == ("event_id", "symbol", *[c for c in TOUCH_SCHEMA if c != "event_id"])
    assert res.stats["placed"] > 0
    assert set(res.touches["touch"]) <= {"upper", "lower", "vertical", "insufficient_data"}


def test_build_is_stable(lake_with_events):
    lb, rs = lake_with_events
    a = build_touches(cfg(), **SER, lake=lb.lake, research=rs, write=False).touches
    b = build_touches(cfg(), **SER, lake=lb.lake, research=rs, write=False).touches
    assert a.equals(b)


def test_last_events_run_out_of_data(lake_with_events):
    lb, rs = lake_with_events
    t = build_touches(cfg(), **SER, lake=lb.lake, research=rs, write=False).touches
    assert t.sort("t0").tail(1)["reason"].item() == "end_of_data"


def test_missing_events(lake_with_events, tmp_path):
    lb, _ = lake_with_events
    with pytest.raises(InputEventsError):
        build_touches(cfg(), **SER, lake=lb.lake, research=Research(root=tmp_path / "empty"))


def test_lake_ticks(lake_with_events):
    lb, _ = lake_with_events
    ticks = LakeTicks(lb.lake, **SER)
    raw = pl.read_parquet(lb.lake.raw(source=SER["source"], market=SER["market"], symbol=SER["symbol"],
                                      interval="TICK", year=2014, filename=f"{SER['symbol']}-2014.parquet"))
    w0 = datetime(2014, 12, 16, 10, tzinfo=UTC)
    win = raw.filter(pl.col("dtime").dt.replace_time_zone("UTC").is_between(w0, w0 + timedelta(minutes=10),
                                                                          closed="left"))
    mid = (win["bidPrice"] + win["askPrice"]) / 2
    upper, lower = float(mid.quantile(0.9)), float(mid.quantile(0.1))
    first_up = int((mid >= upper).arg_max())                       # type: ignore[arg-type]
    first_dn = int((mid <= lower).arg_max())                       # type: ignore[arg-type]
    expect = 1 if first_up < first_dn else -1
    s = int(w0.timestamp())
    assert ticks.first_touch(s, s + 600, upper, lower) == expect
    assert ticks.first_touch(s, s + 600, 1e9, -1.0) is None
    assert set(ticks.used) == {2014}
    with pytest.raises(Exception, match="needs raw ticks"):
        ticks.first_touch(int(datetime(2016, 1, 5, tzinfo=UTC).timestamp()),
                          int(datetime(2016, 1, 5, 0, 1, tzinfo=UTC).timestamp()), 2.0, 0.5)
