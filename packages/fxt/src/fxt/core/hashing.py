'''
hashing

Stable content hashes for configs (and anything else that dumps to JSON).

    canonical_json({"b": 1.0, "a": [1, 2]})   -> '{"a":[1,2],"b":1.0}'
    content_hash("EventsConfig@1", {...})      -> "3f9a1c0d2e4b"  (12 hex chars)

The hash covers the type id AND the payload, so two config classes with the
same fields (or two versions of one class) never share a hash.

Canonical form
- keys sorted, no whitespace, ASCII only
- NaN / inf rejected (json can't represent them portably)
- floats use Python's shortest round-trip repr, so 0.1 -> "0.1" on every run

Anything that makes the payload itself unstable (sets, int-vs-float unions)
has to be stopped before this point; see fxt.research.models.config.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ["HASH_LEN", "HASH_PATTERN", "canonical_json", "content_hash"]

HASH_LEN = 12
HASH_PATTERN = rf"^[0-9a-f]{{{HASH_LEN}}}$"


def canonical_json(obj: Any) -> str:
    """ Deterministic JSON text for `obj` (must already be JSON-compatible). """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
#

def content_hash(typeid: str, payload: Any, length: int = HASH_LEN) -> str:
    """ sha256 of the canonical {"type": typeid, "payload": payload}, truncated.

        `payload` is the JSON-mode dump of a model (model_dump(mode="json")),
        or the same dict read back from a file; both hash identically.
    """
    if not 1 <= length <= 64:
        raise ValueError(f"length must be 1..64, got {length}")
    text = canonical_json({"type": typeid, "payload": payload})
    return hashlib.sha256(text.encode("ascii")).hexdigest()[:length]
#
