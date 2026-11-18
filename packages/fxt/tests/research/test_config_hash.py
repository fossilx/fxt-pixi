"""
Config hashing rules (ML pipeline spec §3.2).
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, Field, ValidationError

from fxt.core.hashing import HASH_LEN, canonical_json, content_hash
from fxt.core.versioned import UnregisteredModelError
from fxt.research import Stage
from fxt.research.models import ConfigHash, ConfigRuleError, StageConfig, registry


#!================================================================================(80)
#! test models
#!--------------------------------------------------------------------------------(80)
@registry.register("TestEventsConfig", 1)
class EventsCfg(StageConfig):
    stage = Stage.EVENTS
    h: float = 3.0
    windows: tuple[int, ...] = (1, 4, 24)
    note: str = Field("", exclude=True)


@registry.register("TestEventsConfig", 2)
class EventsCfgV2(StageConfig):
    stage = Stage.EVENTS
    h: float = 3.0
    windows: tuple[int, ...] = (1, 4, 24)


@registry.register("TestOtherConfig", 1)
class OtherCfg(StageConfig):
    """ Same fields as EventsCfg, different class. """
    stage = Stage.EVENTS
    h: float = 3.0
    windows: tuple[int, ...] = (1, 4, 24)


@registry.register("TestLabelsConfig", 1)
class LabelsCfg(StageConfig):
    stage = Stage.LABELS
    events_hash: ConfigHash
    k: float = 1.0


#!================================================================================(80)
#! canonical json / content_hash
#!--------------------------------------------------------------------------------(80)
def test_canonical_json_is_sorted_and_compact():
    assert canonical_json({"b": 1.0, "a": [1, 2], "c": {"z": 0.1, "y": None}}) == \
        '{"a":[1,2],"b":1.0,"c":{"y":null,"z":0.1}}'


def test_canonical_json_rejects_nan():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_golden_hash():
    """ Pins the canonical form. If this fails, every stored hash just changed:
        that needs a deliberate decision, not a test update.
    """
    assert content_hash("GoldenConfig@1", {"h": 3.0, "name": "cusum", "windows": [1, 4, 24]}) \
        == "d126c3bddb55"


def test_key_order_doesnt_matter():
    assert content_hash("X@1", {"a": 1, "b": 2}) == content_hash("X@1", {"b": 2, "a": 1})


#!================================================================================(80)
#! StageConfig
#!--------------------------------------------------------------------------------(80)
def test_hash_shape():
    h = EventsCfg().config_hash()
    assert len(h) == HASH_LEN and all(c in "0123456789abcdef" for c in h)


def test_int_and_float_hash_the_same():
    assert EventsCfg(h=3).config_hash() == EventsCfg(h=3.0).config_hash()


def test_any_parameter_change_changes_the_hash():
    base = EventsCfg().config_hash()
    assert EventsCfg(h=3.5).config_hash() != base
    assert EventsCfg(windows=(1, 4)).config_hash() != base


def test_excluded_fields_dont_change_the_hash():
    assert EventsCfg(note="first try").config_hash() == EventsCfg().config_hash()
    assert "note" not in EventsCfg(note="x").payload()


def test_version_and_class_are_part_of_the_hash():
    assert EventsCfg().config_hash() != EventsCfgV2().config_hash()
    assert EventsCfg().config_hash() != OtherCfg().config_hash()


def test_input_hashes():
    up = EventsCfg().config_hash()
    cfg = LabelsCfg(events_hash=up)
    assert cfg.input_hashes() == {"events": up}
    assert cfg.config_hash() != LabelsCfg(events_hash=EventsCfg(h=4).config_hash()).config_hash()


def test_input_hash_must_look_like_a_hash():
    with pytest.raises(ValidationError):
        LabelsCfg(events_hash="not-a-hash")


def test_configs_are_frozen_and_strict():
    with pytest.raises(ValidationError):
        EventsCfg(unknown=1)        # type: ignore[call-arg]
    cfg = EventsCfg()
    with pytest.raises(ValidationError):
        cfg.h = 4.0                 # type: ignore[misc]


def test_unregistered_config_cant_be_hashed():
    class Loose(StageConfig):
        stage = Stage.EVENTS
        h: float = 1.0
    with pytest.raises(UnregisteredModelError):
        Loose().config_hash()


def test_stage_must_be_set():
    @registry.register("TestNoStageConfig", 1)
    class NoStage(StageConfig):
        h: float = 1.0
    with pytest.raises(ConfigRuleError):
        NoStage.get_stage()


#!================================================================================(80)
#! rules enforced at class definition
#!--------------------------------------------------------------------------------(80)
@pytest.mark.parametrize("ann", [
    int | float, float | int | None, "list[int | float]", "dict[str, float | int]",
])
def test_int_float_unions_rejected(ann):
    ns = {"__annotations__": {"x": ann}, "stage": Stage.EVENTS}
    with pytest.raises(ConfigRuleError, match="int | float"):
        type("BadCfg", (StageConfig,), ns)


@pytest.mark.parametrize("ann", [set[str], frozenset[int], "tuple[set[str], ...]"])
def test_sets_rejected(ann):
    ns = {"__annotations__": {"x": ann}, "stage": Stage.EVENTS}
    with pytest.raises(ConfigRuleError, match="sets"):
        type("BadCfg", (StageConfig,), ns)


def test_rules_reach_nested_models():
    class Inner(BaseModel):
        v: int | float = 1

    with pytest.raises(ConfigRuleError, match=r"Inner\.v"):
        class Outer(StageConfig):
            stage = Stage.EVENTS
            inner: Inner = Inner()


def test_input_hash_cant_be_excluded():
    with pytest.raises(ConfigRuleError, match="input hashes"):
        class Bad(StageConfig):
            stage = Stage.LABELS
            events_hash: ConfigHash = Field("0" * 12, exclude=True)


def test_optional_and_plain_numbers_are_fine():
    class Ok(StageConfig):
        stage = Stage.EVENTS
        a: float | None = None
        b: int = 1
        c: tuple[float, ...] = ()
        d: dict[str, float] = {}
    assert Ok().payload() == {"a": None, "b": 1, "c": [], "d": {}}
