"""
Config inventory: what each config hash under data/research means.
"""
from __future__ import annotations

import polars as pl
import pytest

from fxt.research import Research, Stage
from fxt.research.inventory import changed_from_defaults, config_inventory
from fxt.research.models import ConfigHash, ResearchMeta, StageConfig, SymbolKey, registry
from fxt.research.store import get_store, write_table


@registry.register("InvEventsConfig", 1)
class EvCfg(StageConfig):
    stage = Stage.EVENTS
    h: float = 3.0
    windows: tuple[int, ...] = (1, 4)


@registry.register("InvWeightsConfig", 1)
class WtCfg(StageConfig):
    stage = Stage.WEIGHTS
    events_hash: ConfigHash
    use_ret: bool = True


@registry.register("InvMeta", 1)
class Meta(ResearchMeta):
    pass


def ds(symbol: str = "EURJPY") -> SymbolKey:
    return SymbolKey(source="dukascopy", market="forex", symbol=symbol)


def put(rs: Research, cfg: StageConfig, *, year: int | None = 2020, symbol: str = "EURJPY", rows: int = 3):
    df = pl.DataFrame({"x": list(range(rows))})
    return write_table(df, Meta.for_config(cfg, dataset=ds(symbol), year=year, rows=rows), research=rs)


@pytest.fixture
def rs(tmp_path) -> Research:
    return Research(root=tmp_path / "research")


def test_changed_from_defaults():
    assert changed_from_defaults("InvEventsConfig@1", EvCfg().payload()) == ({}, True)
    assert changed_from_defaults("InvEventsConfig@1", EvCfg(h=2.5).payload()) == ({"h": 2.5}, True)
    #! tuples are stored as lists: a default tuple must still compare equal
    assert changed_from_defaults("InvEventsConfig@1", EvCfg(windows=(1, 4)).payload())[0] == {}
    assert changed_from_defaults("InvEventsConfig@1", EvCfg(windows=(1,)).payload())[0] == {"windows": [1]}
    #! no default -> always shown
    up = EvCfg().config_hash()
    assert changed_from_defaults("InvWeightsConfig@1", WtCfg(events_hash=up).payload())[0] == {"events_hash": up}
    #! unknown class -> everything shown, flagged
    assert changed_from_defaults("GoneConfig@1", {"a": 1}) == ({"a": 1}, False)


def test_inventory(rs):
    base, other = EvCfg(), EvCfg(h=2.5)
    for y in (2020, 2021, 2023):
        put(rs, base, year=y)
    put(rs, base, year=2020, symbol="GBPJPY", rows=5)
    put(rs, other, year=2020)
    put(rs, WtCfg(events_hash=base.config_hash()), year=None, rows=4)

    entries = config_inventory(rs)
    assert [(e.stage, e.config_hash) for e in entries] == [
        (Stage.EVENTS, base.config_hash()), (Stage.EVENTS, other.config_hash()),
        (Stage.WEIGHTS, WtCfg(events_hash=base.config_hash()).config_hash()),
    ]
    b, o, w = entries
    assert b.config_typeid == "InvEventsConfig@1" and b.changed == {} and b.known_class
    assert b.series == {"dukascopy/forex/EURJPY": (2020, 2021, 2023), "dukascopy/forex/GBPJPY": (2020,)}
    assert (b.files, b.rows) == (4, 14)
    assert b.label == "InvEventsConfig@1 defaults"
    assert o.changed == {"h": 2.5} and o.label == "InvEventsConfig@1 h=2.5"
    assert w.input_hashes == {"events": base.config_hash()}
    assert w.series == {"dukascopy/forex/EURJPY": (None,)}
    assert not any(e.problems for e in entries)

    assert [e.config_hash for e in config_inventory(rs, stage="weights")] == [w.config_hash]
    assert [e.config_hash for e in config_inventory(rs, config_hash=o.config_hash)] == [o.config_hash]
    assert config_inventory(rs, config_hash="0" * 12) == []


def test_inventory_reports_problems(rs):
    cfg = EvCfg()
    p20 = put(rs, cfg, year=2020)
    put(rs, cfg, year=2021)

    #! a tampered file is reported, not fatal
    kv = get_store().read_meta(p20)
    get_store().write(pl.read_parquet(p20), p20, metadata={**kv, "json": kv["json"].replace('"h":3.0', '"h":9.0')})
    [e] = config_inventory(rs)
    assert e.files == 1 and len(e.problems) == 1 and "ValidationError" in e.problems[0]


def test_empty(rs):
    assert config_inventory(rs) == []
