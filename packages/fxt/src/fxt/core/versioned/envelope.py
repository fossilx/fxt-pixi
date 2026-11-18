'''
envelope

Medium-agnostic conversion between a VersionedModel and a flat str -> str
mapping. Any medium that can store string key/value pairs (parquet footer,
arrow IPC, a sidecar json, a sqlite row...) can store the envelope.

Keys are NOT namespaced here; the storage backend applies its namespace.
With ParquetStore's namespace "fxt-data", the footer ends up holding:

    fxt-data:type -> "ConsolidatedDataMeta@1"
    fxt-data:json -> '{"dataset": {...}, ...}'
'''
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import MissingEnvelopeError
from .model import VersionedModel
from .registry import VersionedModelRegistry

TYPE_KEY = "type"
JSON_KEY = "json"
ENVELOPE_KEYS = frozenset({TYPE_KEY, JSON_KEY})


def to_kv(model: VersionedModel) -> dict[str, str]:
    typeid, payload = model.serialize()
    return {TYPE_KEY: typeid, JSON_KEY: payload}


def has_envelope(kv: Mapping[str, str]) -> bool:
    return ENVELOPE_KEYS <= kv.keys()


def from_kv(registry: VersionedModelRegistry[Any], kv: Mapping[str, str]) -> VersionedModel:
    missing = ENVELOPE_KEYS - kv.keys()
    if missing:
        raise MissingEnvelopeError(
            f"Metadata is missing envelope key(s) {sorted(missing)}; "
            f"found keys: {sorted(kv.keys())}"
        )
    return registry.validate_json(kv[TYPE_KEY], kv[JSON_KEY])
