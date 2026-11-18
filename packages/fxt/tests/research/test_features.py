"""
Feature table (ML pipeline spec §4): per-bar features in long format, and the
as-of join onto events.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError

from fxt.research import Research, Stage
from fxt.research.features import (
    FEATURE_SCHEMA, build_features, check_features, compute_features, features_at, load_features, to_wide,
)
from fxt.research.models import BarFeaturesConfig, FeaturesMeta
from fxt.research.store import read_table
from fxt.testing import BASE_KEY, LakeBuilder, build_stamped_bars, make_ticks

MON = datetime(2020, 1, 6)
CFG = BarFeaturesConfig(ret_horizons=(1, 4), short=4, long=8, min_coverage=1.0)


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def bars(n: int = 40, *, seed: int = 0, skip: tuple[int, ...] = (), spread=None, ticks=None) -> pl.DataFrame:
    """ Hourly bars (naive UTC open times like the lake's); `skip` drops those hours (a gap). """
    rng = np.random.default_rng(seed)
    hours = [h for h in range(n + len(skip)) if h not in skip][:n]
    close = 100 * np.exp(np.cumsum(rng.normal(0, 1e-3, len(hours))))
    return pl.DataFrame({
        "time": [MON + timedelta(hours=h) for h in hours],
        "mid_close": close,
        "spread_mean": spread if spread is not None else rng.uniform(0.01, 0.02, len(hours)),
        "tick_count": ticks if ticks is not None else rng.integers(1000, 2000, len(hours)).astype(np.uint32),
    }).with_columns(pl.col("time").cast(pl.Datetime("us")))


def wide(df: pl.DataFrame, cfg: BarFeaturesConfig = CFG) -> pl.DataFrame:
    return to_wide(compute_features(df, cfg, symbol="EURJPY"), cfg.names())


def at(w: pl.DataFrame, i: int) -> dict:
    """ Features at the close of bar i (bar_time = open + 1h). """
    t = (MON + timedelta(hours=i + 1)).replace(tzinfo=UTC)
    return w.filter(pl.col("bar_time") == t).row(0, named=True)


#!================================================================================(80)
#! values
#!--------------------------------------------------------------------------------(80)
def test_schema_and_names():
    long = compute_features(bars(), CFG, symbol="EURJPY")
    assert dict(long.schema) == FEATURE_SCHEMA
    assert set(long["name"].unique()) == set(CFG.names())
    assert long["value_str"].is_null().all()
    assert all(c.ok for c in check_features(long, CFG))


def test_values_by_hand():
    df = bars()
    c = df["mid_close"].to_numpy()
    sp, tk = df["spread_mean"].to_numpy(), df["tick_count"].to_numpy().astype(float)
    r = np.diff(np.log(c))                              # r[i-1] = return INTO bar i
    w = wide(df)
    i = 20
    f = at(w, i)
    assert f["ret_1h"] == pytest.approx(math.log(c[i] / c[i - 1]))
    assert f["ret_4h"] == pytest.approx(math.log(c[i] / c[i - 4]))
    vol4, vol8 = np.std(r[i - 4:i], ddof=1), np.std(r[i - 8:i], ddof=1)
    assert f["vol_4h"] == pytest.approx(vol4)
    assert f["vol_8h"] == pytest.approx(vol8)
    assert f["vol_ratio_4h_8h"] == pytest.approx(vol4 / vol8)
    assert f["ret_4h_z"] == pytest.approx(math.log(c[i] / c[i - 4]) / (vol8 * 2))
    assert f["spread_bp_4h"] == pytest.approx(sp[i - 3:i + 1].mean() / c[i] * 1e4)
    assert f["spread_ratio_4h_8h"] == pytest.approx(sp[i - 3:i + 1].mean() / sp[i - 7:i + 1].mean())
    assert f["tick_ratio_4h_8h"] == pytest.approx(tk[i - 3:i + 1].mean() / tk[i - 7:i + 1].mean())
    assert (f["hour_utc"], f["dow_utc"]) == (21.0, 1.0)  # bar 20 opens Mon 20:00, closes 21:00


def test_bar_time_is_the_close():
    long = compute_features(bars(), CFG, symbol="EURJPY")
    first = long.filter(pl.col("name") == "ret_1h")["bar_time"].min()
    assert first == (MON + timedelta(hours=2)).replace(tzinfo=UTC)    # bar 1 closes at 02:00


def test_warmup_rows_are_absent():
    long = compute_features(bars(), CFG, symbol="EURJPY")
    n = lambda name: long.filter(pl.col("name") == name).height       # noqa: E731
    assert n("ret_1h") == 39 and n("ret_4h") == 36
    assert n("vol_8h") == 40 - 8                                      # needs 8 returns
    assert n("hour_utc") == 40


def test_gap_returns_stay_out_of_vol():
    """ A return across a closed stretch counts as a 1-bar return, but never in vol. """
    df = bars(skip=(10, 11, 12, 13))                                  # 5-hour gap before bar 10
    w = wide(df, CFG)
    c = df["mid_close"].to_numpy()
    i = 10                                                            # first bar after the gap
    t = (MON + timedelta(hours=14 + 1)).replace(tzinfo=UTC)
    f = w.filter(pl.col("bar_time") == t).row(0, named=True)
    assert f["ret_1h"] == pytest.approx(math.log(c[i] / c[i - 1]))
    assert f["vol_4h"] is None                                        # min_coverage 1.0 and one return missing
    loose = wide(df, CFG.model_copy(update={"min_coverage": 0.75}))
    g = loose.filter(pl.col("bar_time") == t).row(0, named=True)
    r = np.diff(np.log(c))
    assert g["vol_4h"] == pytest.approx(np.std(r[i - 4:i - 1], ddof=1))  # the 3 non-gap returns


def test_non_finite_values_are_dropped():
    df = bars(spread=np.zeros(40))                                    # 0 / 0 spread ratio
    long = compute_features(df, CFG, symbol="EURJPY")
    assert long.filter(pl.col("name") == "spread_ratio_4h_8h").height == 0
    assert long["value"].is_finite().all()


def test_point_in_time():
    """ Changing the future never changes a past feature. """
    df = bars()
    cut = df["time"][25]
    base = compute_features(df, CFG, symbol="X")
    shocked = df.with_columns(
        pl.when(pl.col("time") > cut).then(pl.col("mid_close") * 1.05).otherwise(pl.col("mid_close")),
        pl.when(pl.col("time") > cut).then(pl.col("spread_mean") * 3).otherwise(pl.col("spread_mean")),
    )
    other = compute_features(shocked, CFG, symbol="X")
    limit = (cut + timedelta(hours=1)).replace(tzinfo=UTC)
    assert base.filter(pl.col("bar_time") <= limit).equals(other.filter(pl.col("bar_time") <= limit))


def test_config():
    assert BarFeaturesConfig().config_hash() == "816950fa181b"        # pinned
    assert len(BarFeaturesConfig().names()) == 16
    assert "hour_utc" not in BarFeaturesConfig(calendar=False).names()
    with pytest.raises(ValidationError, match="short"):
        BarFeaturesConfig(short=120, long=24)
    with pytest.raises(ValidationError, match="distinct"):
        BarFeaturesConfig(ret_horizons=(1, 1))
    with pytest.raises(Exception):
        compute_features(pl.concat([bars(5), bars(5)]), CFG, symbol="X")


#!================================================================================(80)
#! wide + as-of join
#!--------------------------------------------------------------------------------(80)
def test_to_wide_keeps_name_order_and_fills_missing():
    long = compute_features(bars(), CFG, symbol="EURJPY")
    w = to_wide(long, ["vol_8h", "ret_1h", "not_a_feature"])
    assert w.columns == ["symbol", "bar_time", "vol_8h", "ret_1h", "not_a_feature"]
    assert w["not_a_feature"].is_null().all()


def test_features_at():
    w = wide(bars())
    t = lambda h, m=0: (MON + timedelta(hours=h, minutes=m)).replace(tzinfo=UTC)   # noqa: E731
    ev = pl.DataFrame({"event_id": ["late", "exact", "between", "stale", "early"],
                       "symbol": ["EURJPY"] * 5,
                       "t0": [t(30), t(21), t(21, 30), t(60), t(0, 30)]})
    X = features_at(ev, w)
    assert X["event_id"].to_list() == ev["event_id"].to_list()        # row order kept
    ft = dict(zip(X["event_id"], X["feature_time"], strict=True))
    assert ft["exact"] == t(21)
    assert ft["between"] == t(21)                                     # backward only: never the future
    assert ft["late"] == t(30)
    assert ft["stale"] is None                                        # last bar closes at 40:00; > 1h old
    assert ft["early"] is None                                        # before the first bar closed
    assert features_at(ev, w, tolerance=None).filter(pl.col("event_id") == "stale")["feature_time"].item() == t(40)


#!================================================================================(80)
#! builder
#!--------------------------------------------------------------------------------(80)
SER = {"source": BASE_KEY.source, "market": BASE_KEY.market, "symbol": BASE_KEY.symbol}


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    lb = LakeBuilder(tmp_path_factory.mktemp("feat_lake") / "lake")
    build_stamped_bars(lb, make_ticks(n=400_000, start="2014-12-15"))
    return lb


def test_build_features(lake, tmp_path):
    rs = Research(root=tmp_path / "research")
    cfg = BarFeaturesConfig(short=12, long=48)
    res = build_features(cfg, **SER, lake=lake.lake, research=rs)
    years = [k.year for k, _ in rs.scan(Stage.FEATURES, config=res.config_hash)]
    assert years == [2014, 2015]
    for p in res.paths:
        df, meta = read_table(p)
        assert isinstance(meta, FeaturesMeta) and meta.passed
        assert meta.names == cfg.names() and meta.input_hashes == {}
        assert {i.typeid for i in meta.inputs} == {"BarsMeta@1"}
        assert (df["bar_time"].dt.year() == meta.year).all()
    long = load_features(rs, res.config_hash, **SER)
    assert long.height == res.features.height
    assert load_features(rs, res.config_hash, **SER, years=[2015], names=["ret_1h"])["name"].unique().to_list() \
        == ["ret_1h"]
    assert res.stats["name"].to_list() == list(cfg.names())
    with pytest.raises(FileNotFoundError):
        load_features(rs, "0" * 12, **SER)
