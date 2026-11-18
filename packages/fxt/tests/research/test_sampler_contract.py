"""
The sampler contract: any sampler plugs into build_events by returning the
core event columns (ML pipeline spec §5.3).
"""
from __future__ import annotations

from datetime import timedelta

import polars as pl
import pytest
from pydantic import Field

from fxt.research import Research
from fxt.research.events import (
    CORE_COLUMNS, DETECT_CORE_SCHEMA, EventContractError, build_events, check_detected,
    register_sampler,
)
from fxt.research.models import CusumEventsConfig, SamplerConfig, registry
from fxt.research.store import read_table
from fxt.testing import BASE_KEY, LakeBuilder, build_stamped_bars, make_ticks


#!================================================================================(80)
#! a toy second sampler: fires every `every` bars, alternating direction
#!--------------------------------------------------------------------------------(80)
@registry.register("EveryNthEventsConfig", 1)
class EveryNthConfig(SamplerConfig):
    sampler = "every_nth"
    every: int = Field(10, ge=1)


@register_sampler(EveryNthConfig)
def detect_every_nth(bars: pl.DataFrame, cfg: EveryNthConfig) -> pl.DataFrame:
    picked = bars.sort("time").gather_every(cfg.every)
    return pl.DataFrame({
        "t0": (picked["time"] + timedelta(seconds=cfg.bar_seconds)).dt.replace_time_zone("UTC"),
        "direction": pl.Series([1 if i % 2 == 0 else -1 for i in range(picked.height)], dtype=pl.Int8),
        "price_t0": picked["mid_close"],
        "bar_no": pl.Series(range(0, bars.height, cfg.every), dtype=pl.Int64)[:picked.height],
    }).cast(DETECT_CORE_SCHEMA)  # type: ignore[arg-type]


SER = {"source": BASE_KEY.source, "market": BASE_KEY.market, "symbol": BASE_KEY.symbol}


@pytest.fixture(scope="module")
def bar_lake(tmp_path_factory):
    lb = LakeBuilder(tmp_path_factory.mktemp("lake"))
    build_stamped_bars(lb, make_ticks(n=150_000, start="2014-03-03"))
    return lb


#!================================================================================(80)
#! plugging in
#!--------------------------------------------------------------------------------(80)
def test_a_new_sampler_plugs_into_the_builder(bar_lake, tmp_path):
    rs = Research(root=tmp_path / "research")
    cfg = EveryNthConfig(every=12)
    res = build_events(cfg, **SER, lake=bar_lake.lake, research=rs)

    df, meta = read_table(res.paths[0])
    assert tuple(df.columns) == (*CORE_COLUMNS, "bar_no")          # core first, then extras
    assert meta.sampler == "every_nth"
    assert meta.config_typeid == "EveryNthEventsConfig@1"
    assert df.height == res.events.height > 0
    assert df["direction"].head(2).to_list() == [1, -1]


def test_two_samplers_share_one_core_schema(bar_lake, tmp_path):
    rs = Research(root=tmp_path / "research")
    a = build_events(EveryNthConfig(), **SER, lake=bar_lake.lake, research=rs, write=False).events
    b = build_events(CusumEventsConfig(warmup=24), **SER, lake=bar_lake.lake, research=rs, write=False).events
    assert a.select(CORE_COLUMNS).schema == b.select(CORE_COLUMNS).schema


def test_unregistered_sampler(bar_lake, tmp_path):
    @registry.register("NoDetectEventsConfig", 1)
    class NoDetect(SamplerConfig):
        sampler = "none"

    with pytest.raises(TypeError, match="no sampler registered"):
        build_events(NoDetect(), **SER, lake=bar_lake.lake, research=Research(root=tmp_path))


def test_register_sampler_rejects_non_sampler_configs():
    with pytest.raises(TypeError):
        register_sampler(dict)  # type: ignore[arg-type]


def test_one_sampler_per_config_class():
    with pytest.raises(ValueError, match="already has a sampler"):
        @register_sampler(EveryNthConfig)
        def another(bars, cfg):
            return bars


#!================================================================================(80)
#! contract checks
#!--------------------------------------------------------------------------------(80)
def good(n: int = 3) -> pl.DataFrame:
    return pl.DataFrame({
        "t0": pl.datetime_range(pl.datetime(2020, 1, 6, 1), pl.datetime(2020, 1, 6, n), "1h",
                                time_zone="UTC", eager=True),
        "direction": [1, -1, 1][:n],
        "price_t0": [1.1, 1.2, 1.3][:n],
        "extra": ["a", "b", "c"][:n],
    }).cast(DETECT_CORE_SCHEMA)  # type: ignore[arg-type]


def test_check_detected_accepts_and_orders():
    df = good().select("extra", "price_t0", "direction", "t0")
    assert check_detected(df).columns == ["t0", "direction", "price_t0", "extra"]
    assert check_detected(good().head(0)).height == 0


@pytest.mark.parametrize("bad, match", [
    (lambda d: d.drop("direction"), "missing core column 'direction'"),
    (lambda d: d.with_columns(pl.col("direction").cast(pl.Int64)), "direction must be"),
    (lambda d: d.with_columns(pl.col("t0").dt.replace_time_zone(None)), "t0 must be"),
    (lambda d: d.with_columns(pl.lit(0, dtype=pl.Int8).alias("direction")), r"\+1 or -1"),
    (lambda d: pl.concat([d, d.head(1)]), "unique"),
    (lambda d: d.reverse(), "sorted"),
    (lambda d: d.with_columns(pl.lit(-1.0).alias("price_t0")), "positive"),
    (lambda d: d.with_columns(pl.lit("X").alias("symbol")), "builder adds"),
    (lambda d: d.with_columns(pl.lit(None, dtype=pl.Float64).alias("price_t0")), "nulls"),
])
def test_check_detected_rejects(bad, match):
    with pytest.raises(EventContractError, match=match):
        check_detected(bad(good()))
