"""
Research tables: writing, reading back, lineage, and the guards in write_table.
"""
from __future__ import annotations

import polars as pl
import pytest
from pydantic import ValidationError

from fxt.core.versioned import TYPE_KEY
from fxt.lake.models import CheckRecord
from fxt.research import Research, ResearchKey, Stage
from fxt.research.models import ConfigHash, ResearchMeta, StageConfig, SymbolKey, registry
from fxt.research.store import (
    ConfigCollisionError, code_version, existing_config, file_ref, get_store,
    read_meta, read_table, write_table,
)
from fxt.testing import BASE_KEY, RAW_TYPEID, LakeBuilder, make_ticks


#!================================================================================(80)
#! test models
#!--------------------------------------------------------------------------------(80)
@registry.register("StoreTestEventsConfig", 1)
class EvCfg(StageConfig):
    stage = Stage.EVENTS
    h: float = 3.0


@registry.register("StoreTestWeightsConfig", 1)
class WtCfg(StageConfig):
    stage = Stage.WEIGHTS
    events_hash: ConfigHash
    use_ret: bool = True


@registry.register("StoreTestEventsMeta", 1)
class EvMeta(ResearchMeta):
    pass


@registry.register("StoreTestWeightsMeta", 1)
class WtMeta(ResearchMeta):
    pass


DS = SymbolKey(source=BASE_KEY.source, market=BASE_KEY.market, symbol=BASE_KEY.symbol)


def _events(n: int = 5) -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": [DS.symbol] * n,
        "t0": pl.datetime_range(pl.datetime(2014, 1, 6, 1), pl.datetime(2014, 1, 6, n), "1h",
                                time_zone="UTC", eager=True),
        "side": [1, -1] * (n // 2) + [1] * (n % 2),
    })


@pytest.fixture
def rs(tmp_path) -> Research:
    return Research(root=tmp_path / "research")


#!================================================================================(80)
#! meta
#!--------------------------------------------------------------------------------(80)
def test_meta_from_config():
    cfg = EvCfg()
    meta = EvMeta.for_config(cfg, dataset=DS, year=2014, rows=5)
    assert meta.config_hash == cfg.config_hash()
    assert meta.config_typeid == "StoreTestEventsConfig@1"
    assert meta.config == {"h": 3.0}
    assert meta.stage is Stage.EVENTS
    assert meta.key == ResearchKey(stage=Stage.EVENTS, config=cfg.config_hash(),
                                   source=DS.source, market=DS.market, symbol=DS.symbol, year=2014)


def test_meta_input_hashes_follow_the_config():
    up = EvCfg().config_hash()
    meta = WtMeta.for_config(WtCfg(events_hash=up), dataset=DS, rows=0)
    assert meta.input_hashes == {"events": up}
    assert meta.year is None


def test_meta_rejects_a_wrong_hash():
    meta = EvMeta.for_config(EvCfg(), dataset=DS, year=2014, rows=5)
    with pytest.raises(ValidationError, match="doesn't match the stored config"):
        EvMeta(**{**meta.model_dump(), "config": {"h": 4.0}})


def test_meta_year_rules():
    with pytest.raises(ValidationError, match="year is required"):
        EvMeta.for_config(EvCfg(), dataset=DS, rows=5)
    with pytest.raises(ValidationError, match="split by year"):
        WtMeta.for_config(WtCfg(events_hash=EvCfg().config_hash()), dataset=DS, year=2014, rows=0)


def test_meta_checks():
    meta = EvMeta.for_config(EvCfg(), dataset=DS, year=2014, rows=5,
                             checks=(CheckRecord(name="a", status="pass"),
                                     CheckRecord(name="b", status="fail", detail="nope")))
    assert not meta.passed
    assert [c.name for c in meta.failed_checks] == ["b"]


#!================================================================================(80)
#! write / read
#!--------------------------------------------------------------------------------(80)
def test_round_trip(rs: Research):
    df = _events()
    meta = EvMeta.for_config(EvCfg(), dataset=DS, year=2014, rows=df.height)
    path = write_table(df, meta, research=rs)

    assert path == rs.file(meta.key)
    back, stored = read_table(path)
    assert back.equals(df)
    assert stored == meta
    assert stored.get_id() == "StoreTestEventsMeta@1"
    assert [p for _, p in rs.scan(Stage.EVENTS, config=meta.config_hash)] == [path]


def test_weights_round_trip(rs: Research):
    meta = WtMeta.for_config(WtCfg(events_hash=EvCfg().config_hash()), dataset=DS, rows=2)
    df = pl.DataFrame({"event_id": ["a", "b"], "uniqueness": [1.0, 0.5], "weight": [1.2, 0.8]})
    path = write_table(df, meta, research=rs)
    assert path.name == f"{DS.symbol}.parquet"
    assert read_meta(path).input_hashes == {"events": EvCfg().config_hash()}


def test_same_config_can_be_rewritten_and_extended(rs: Research):
    cfg = EvCfg()
    write_table(_events(), EvMeta.for_config(cfg, dataset=DS, year=2014, rows=5), research=rs)
    write_table(_events(3), EvMeta.for_config(cfg, dataset=DS, year=2014, rows=3), research=rs)
    write_table(_events(2), EvMeta.for_config(cfg, dataset=DS, year=2015, rows=2), research=rs)
    assert len(rs.scan(Stage.EVENTS, config=cfg.config_hash())) == 2


def test_no_overwrite(rs: Research):
    meta = EvMeta.for_config(EvCfg(), dataset=DS, year=2014, rows=5)
    write_table(_events(), meta, research=rs)
    with pytest.raises(FileExistsError):
        write_table(_events(), meta, research=rs, overwrite=False)


def test_rows_must_match(rs: Research):
    meta = EvMeta.for_config(EvCfg(), dataset=DS, year=2014, rows=4)
    with pytest.raises(ValueError, match="rows"):
        write_table(_events(5), meta, research=rs)


def test_partition_columns_must_match_the_folder(rs: Research):
    df = _events().with_columns(pl.lit("GBPUSD").alias("symbol"))
    meta = EvMeta.for_config(EvCfg(), dataset=DS, year=2014, rows=df.height)
    with pytest.raises(ValueError, match="symbol"):
        write_table(df, meta, research=rs)


def test_hash_collision_is_caught(rs: Research):
    """ Fake a collision: a second config forced onto the first one's hash. """
    real = EvMeta.for_config(EvCfg(), dataset=DS, year=2014, rows=5)
    write_table(_events(), real, research=rs)

    forged = EvMeta.model_construct(**{**dict(real), "config": {"h": 99.0}, "year": 2015})
    with pytest.raises(ConfigCollisionError, match="different config"):
        write_table(_events(), forged, research=rs)
    assert existing_config(rs, Stage.EVENTS, real.config_hash) == real


def test_tampered_meta_fails_on_read(rs: Research):
    meta = EvMeta.for_config(EvCfg(), dataset=DS, year=2014, rows=5)
    path = write_table(_events(), meta, research=rs)

    kv = get_store().read_meta(path)
    bad_json = kv["json"].replace('"h":3.0', '"h":4.0')
    assert bad_json != kv["json"]
    get_store().write(pl.read_parquet(path), path, metadata={**kv, "json": bad_json})
    with pytest.raises(ValidationError, match="doesn't match the stored config"):
        read_meta(path)


#!================================================================================(80)
#! lineage helpers
#!--------------------------------------------------------------------------------(80)
def test_file_ref_to_a_lake_file(tmp_path, rs: Research):
    lb = LakeBuilder(tmp_path / "lake")
    raw = lb.put(lb.key("TICK"), make_ticks(n=2_000), envelope=RAW_TYPEID)
    ref = file_ref(raw, lake_root=lb.lake.root, research_root=rs.root)
    assert ref.root == "lake"
    assert ref.typeid == RAW_TYPEID
    assert ref.path == raw.relative_to(lb.lake.root).as_posix()
    assert len(ref.sha256) == 64


def test_file_ref_to_a_research_file(tmp_path, rs: Research):
    meta = EvMeta.for_config(EvCfg(), dataset=DS, year=2014, rows=5)
    path = write_table(_events(), meta, research=rs)
    ref = file_ref(path, lake_root=tmp_path / "lake", research_root=rs.root)
    assert ref.root == "research"
    assert ref.typeid == get_store().read_meta(path)[TYPE_KEY] == "StoreTestEventsMeta@1"


def test_file_ref_outside_both_roots(tmp_path, rs: Research):
    p = tmp_path / "elsewhere.parquet"
    pl.DataFrame({"a": [1]}).write_parquet(p)
    with pytest.raises(ValueError, match="neither"):
        file_ref(p, lake_root=tmp_path / "lake", research_root=rs.root)


def test_code_version_never_raises(tmp_path):
    assert code_version(tmp_path) is None        # not a repo
    v = code_version()                           # this checkout (or None if no git)
    assert v is None or len(v.removesuffix("+dirty")) == 12
