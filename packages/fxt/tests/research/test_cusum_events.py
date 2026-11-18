"""
CUSUM sampler (ML pipeline spec §5.1) and the events builder.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError

from fxt.lake.models import BarsMeta, CheckRecord, get_meta_io as lake_meta_io
from fxt.research import Research, Stage
from fxt.research.events import (
    EVENT_COLUMNS, EVENT_SCHEMA, InputBarsError, build_events, detect_cusum, event_ids, prepare_bars,
)
from fxt.research.models import CusumEventsConfig, EventsMeta
from fxt.research.store import read_table
from fxt.testing import BASE_KEY, LakeBuilder, build_stamped_bars, make_ticks


#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def hourly_bars(n_days: int = 40, seed: int = 3, start: str = "2020-01-06",
                drop: float = 0.02, vol: float = 8e-4) -> pl.DataFrame:
    """ Weekday hourly bars (naive UTC open times, like the lake's), random-walk mid_close,
        with ~`drop` of hours missing (bars are sparse).
    """
    rng = np.random.default_rng(seed)
    t0 = datetime.fromisoformat(start)
    times = [t0 + timedelta(hours=i) for i in range(n_days * 24)]
    times = [t for t in times if t.weekday() < 5]
    keep = rng.random(len(times)) >= drop
    times = [t for t, k in zip(times, keep, strict=True) if k]
    price = 130.0 * np.exp(np.cumsum(rng.normal(0, vol, len(times))))
    return pl.DataFrame({"time": times, "mid_close": price}).with_columns(pl.col("time").cast(pl.Datetime("us")))


def bars_from_returns(returns: list[float], start: str = "2020-01-06 00:00") -> pl.DataFrame:
    t0 = datetime.fromisoformat(start)
    price = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    return pl.DataFrame({"time": [t0 + timedelta(hours=i) for i in range(len(price))],
                         "mid_close": price}).with_columns(pl.col("time").cast(pl.Datetime("us")))


def reference_detect(bars: pl.DataFrame, h=3.0, vol_span=120, warmup=48, max_gap_hours=3.0,
                     reset_on_gap=True, vol_floor=1e-6) -> list[tuple[int, int, float, float, float]]:
    """ The first-pass loop from fxtapps/derived/first_bars/cusum_events.py, verbatim
        (minus the DataFrame assembly). The port must match it exactly.
    """
    t = bars["time"].dt.epoch("s").to_numpy()
    price = bars["mid_close"].to_numpy()
    lam = 1.0 - 2.0 / (vol_span + 1)
    var, n_valid = 0.0, 0
    s_up = s_dn = 0.0
    rows = []
    for i in range(1, len(price)):
        if (t[i] - t[i - 1]) / 3600.0 > max_gap_hours:
            if reset_on_gap:
                s_up = s_dn = 0.0
            continue
        r = math.log(price[i] / price[i - 1])
        if n_valid < warmup:
            n_valid += 1
            var += (r * r - var) / n_valid
            continue
        vol = max(math.sqrt(var), vol_floor)
        z = r / vol
        s_up = max(0.0, s_up + z)
        s_dn = min(0.0, s_dn + z)
        side = 1 if s_up > h else (-1 if s_dn < -h else 0)
        if side:
            rows.append((i, side, r, z, vol))
            s_up = s_dn = 0.0
        var = lam * var + (1.0 - lam) * r * r
    return rows


#!================================================================================(80)
#! config
#!--------------------------------------------------------------------------------(80)
def test_default_config_hash_is_pinned():
    """ Stored event sets are keyed by this hash; changing a default orphans them. """
    assert CusumEventsConfig().config_hash() == "6faf936c570f"


def test_config_validation():
    with pytest.raises(ValidationError, match="unknown bar interval"):
        CusumEventsConfig(interval="2HOUR")
    with pytest.raises(ValidationError):
        CusumEventsConfig(h=0)
    assert CusumEventsConfig(h=3).config_hash() == CusumEventsConfig(h=3.0).config_hash()
    assert CusumEventsConfig(h=3.5).label == "cusum_h3.5"


#!================================================================================(80)
#! detection
#!--------------------------------------------------------------------------------(80)
@pytest.mark.parametrize("params", [
    {}, {"h": 2.0}, {"h": 4.0, "vol_span": 60}, {"warmup": 10, "reset_on_gap": False},
    {"max_gap_hours": 1.5}, {"vol_floor": 9e-4},
])
def test_matches_the_first_pass_implementation(params):
    bars = hourly_bars()
    cfg = CusumEventsConfig(**params)
    ref = reference_detect(bars, **params)
    got = detect_cusum(bars, cfg)

    assert got.height == len(ref) > 0
    idx = [r[0] for r in ref]
    expect_t0 = bars["time"].gather(idx).dt.replace_time_zone("UTC") + timedelta(hours=1)
    assert got["t0"].to_list() == expect_t0.to_list()
    assert got["direction"].to_list() == [r[1] for r in ref]
    assert got["price_t0"].to_list() == bars["mid_close"].gather(idx).to_list()
    assert got["ret"].to_list() == [r[2] for r in ref]
    assert got["z"].to_list() == [r[3] for r in ref]
    assert got["vol"].to_list() == [r[4] for r in ref]


def test_schema():
    got = detect_cusum(hourly_bars(), CusumEventsConfig())
    assert dict(got.schema) == EVENT_SCHEMA
    empty = detect_cusum(hourly_bars(n_days=1), CusumEventsConfig())
    assert empty.height == 0 and dict(empty.schema) == EVENT_SCHEMA


def test_a_jump_fires_at_the_right_bar():
    noise = [1e-4, -1e-4] * 30                    # 60 quiet returns: vol ~1e-4
    bars = bars_from_returns(noise + [5e-4] + noise[:4])
    got = detect_cusum(bars, CusumEventsConfig(warmup=20, h=3.0))
    assert got.height == 1
    ev = got.row(0, named=True)
    #! z ~ 5 on the jump bar (index 61): the up side crosses h there
    assert ev["direction"] == 1
    assert ev["t0"] == bars["time"][61].replace(tzinfo=UTC) + timedelta(hours=1)
    assert ev["price_t0"] == bars["mid_close"][61]


def test_no_events_during_warmup():
    bars = bars_from_returns([5e-3] * 10 + [1e-4, -1e-4] * 20)
    assert detect_cusum(bars, CusumEventsConfig(warmup=10)).height == 0


def test_gap_resets_the_accumulators():
    quiet = [1e-4, -1e-4] * 30
    before = bars_from_returns(quiet + [1.2e-4] * 2)                   # z ~1.1 each: S_up ~2.2 < h
    after = bars_from_returns([1.2e-4] * 2, start="2020-01-10 12:00")  # ~2 day gap, then ~2.2 more
    after = after.with_columns(pl.col("mid_close") * before["mid_close"][-1] / after["mid_close"][0])
    bars = pl.concat([before, after])
    assert detect_cusum(bars, CusumEventsConfig(warmup=20, h=3.0)).height == 0
    assert detect_cusum(bars, CusumEventsConfig(warmup=20, h=3.0, reset_on_gap=False)).height == 1


def test_point_in_time():
    """ Changing the future never changes past events. """
    bars = hourly_bars()
    cut = bars["time"][bars.height // 2]
    base = detect_cusum(bars, CusumEventsConfig())
    shocked = bars.with_columns(
        pl.when(pl.col("time") > cut).then(pl.col("mid_close") * 1.05).otherwise(pl.col("mid_close"))
    )
    other = detect_cusum(shocked, CusumEventsConfig())
    limit = cut.replace(tzinfo=UTC) + timedelta(hours=1)
    assert base.filter(pl.col("t0") <= limit).equals(other.filter(pl.col("t0") <= limit))


def test_input_order_and_timezone_dont_matter():
    bars = hourly_bars()
    base = detect_cusum(bars, CusumEventsConfig())
    shuffled = bars.sample(fraction=1.0, shuffle=True, seed=1)
    aware = bars.with_columns(pl.col("time").dt.replace_time_zone("UTC").dt.convert_time_zone("Asia/Tokyo"))
    assert detect_cusum(shuffled, CusumEventsConfig()).equals(base)
    assert detect_cusum(aware, CusumEventsConfig()).equals(base)


@pytest.mark.parametrize("mutate, match", [
    (lambda b: pl.concat([b, b.head(1)]), "duplicate"),
    (lambda b: b.with_columns(pl.lit(0.0).alias("mid_close")), "positive"),
    (lambda b: b.drop("mid_close"), "missing"),
])
def test_bad_bars(mutate, match):
    with pytest.raises(ValueError, match=match):
        prepare_bars(mutate(hourly_bars(n_days=5)))


#!================================================================================(80)
#! builder
#!--------------------------------------------------------------------------------(80)
SER = {"source": BASE_KEY.source, "market": BASE_KEY.market, "symbol": BASE_KEY.symbol}
CFG = CusumEventsConfig(warmup=24)


@pytest.fixture(scope="module")
def bar_lake(tmp_path_factory):
    """ Stamped 1MIN/1HOUR bars for Dec 2014 -> early Jan 2015 (two year files). """
    lb = LakeBuilder(tmp_path_factory.mktemp("lake"))
    built = build_stamped_bars(lb, make_ticks(n=400_000, start="2014-12-15"))
    return lb, built


@pytest.fixture
def rs(tmp_path) -> Research:
    return Research(root=tmp_path / "research")


def test_build_writes_one_file_per_year(bar_lake, rs):
    lb, built = bar_lake
    res = build_events(CFG, **SER, lake=lb.lake, research=rs)

    assert [k.year for k, _ in rs.scan(Stage.EVENTS, config=res.config_hash)] == [2014, 2015]
    total = 0
    for path in res.paths:
        df, meta = read_table(path)
        assert isinstance(meta, EventsMeta) and meta.sampler == "cusum"
        assert meta.config_hash == CFG.config_hash()
        assert meta.rows == df.height
        assert tuple(df.columns) == EVENT_COLUMNS
        assert (df["t0"].dt.year() == meta.year).all()          # partitioned by t0's year
        assert {i.path for i in meta.inputs} == {
            p["1HOUR"].relative_to(lb.lake.root).as_posix() for p in built.values()}
        assert all(i.root == "lake" and i.typeid == "BarsMeta@1" for i in meta.inputs)
        assert meta.passed
        total += df.height
    assert total == res.events.height == res.stats["events"] > 0


def test_state_carries_across_years(bar_lake, rs):
    """ The builder walks all years in one pass: same as detecting on the concatenation. """
    lb, built = bar_lake
    res = build_events(CFG, **SER, lake=lb.lake, research=rs, write=False)
    bars = pl.concat([pl.read_parquet(built[y]["1HOUR"]) for y in sorted(built)])
    assert res.events.select(*EVENT_SCHEMA).equals(detect_cusum(bars, CFG))
    assert res.paths == ()
    assert not rs.root.exists()                                   # dry run wrote nothing


def test_event_ids(bar_lake, rs):
    lb, _ = bar_lake
    a = build_events(CFG, **SER, lake=lb.lake, research=rs, write=False).events
    b = build_events(CFG, **SER, lake=lb.lake, research=rs, write=False).events
    c = build_events(CFG.model_copy(update={"h": 2.5}), **SER, lake=lb.lake, research=rs, write=False).events
    assert a["event_id"].is_unique().all()
    assert a["event_id"].to_list() == b["event_id"].to_list()
    assert not set(a["event_id"]) & set(c["event_id"])
    assert a["event_id"].str.len_chars().unique().to_list() == [16]
    assert event_ids("a" * 12, "X", a["t0"].head(1)).item() != event_ids("b" * 12, "X", a["t0"].head(1)).item()


def test_rebuild_is_stable(bar_lake, rs):
    lb, _ = bar_lake
    first = build_events(CFG, **SER, lake=lb.lake, research=rs)
    before = [read_table(p)[0] for p in first.paths]
    second = build_events(CFG, **SER, lake=lb.lake, research=rs)
    assert second.paths == first.paths
    assert all(read_table(p)[0].equals(df) for p, df in zip(second.paths, before, strict=True))


def test_quiet_years_still_get_a_file(bar_lake, rs):
    lb, _ = bar_lake
    res = build_events(CusumEventsConfig(warmup=24, h=1e6), **SER, lake=lb.lake, research=rs)
    assert res.events.height == 0
    assert [read_table(p)[1].rows for p in res.paths] == [0, 0]


def test_refuses_missing_bars(rs, tmp_path):
    with pytest.raises(InputBarsError, match="no 1HOUR bars"):
        build_events(CFG, **SER, lake=LakeBuilder(tmp_path / "empty").lake, research=rs)


def test_refuses_failed_or_unstamped_bars(tmp_path, rs):
    lb = LakeBuilder(tmp_path / "lake")
    built = build_stamped_bars(lb, make_ticks(n=120_000, start="2014-01-06"))
    h1 = built[2014]["1HOUR"]
    meta = lake_meta_io().read_meta_as(h1, BarsMeta)

    failed = meta.model_copy(update={"checks": (*meta.checks, CheckRecord(name="x", status="fail"))})
    lake_meta_io().write(pl.read_parquet(h1), h1, failed)
    with pytest.raises(InputBarsError, match="checks failed"):
        build_events(CFG, **SER, lake=lb.lake, research=rs)

    pl.read_parquet(h1).write_parquet(h1)                         # strip the metadata
    with pytest.raises(InputBarsError, match="not a stamped bar file"):
        build_events(CFG, **SER, lake=lb.lake, research=rs)
    assert not rs.root.exists()
