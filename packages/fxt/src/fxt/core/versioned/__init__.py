'''
fxt.core.versioned

Versioned pydantic models: registry, medium-agnostic envelope, and IO binding.
Nothing in here knows about fxt's domain models.
'''
from .errors import (
    DuplicateModelError,
    InvalidRegistrationError,
    MissingEnvelopeError,
    ModelTypeMismatchError,
    UnknownModelError,
    UnregisteredModelError,
    VersionedModelError,
)
from .model import Registration, VersionedModel
from .registry import VersionedModelRegistry
from .envelope import JSON_KEY, TYPE_KEY, from_kv, has_envelope, to_kv
from .io import KVBackend, VersionedModelIO

__all__ = [  # noqa: RUF022
    "DuplicateModelError", "InvalidRegistrationError", "MissingEnvelopeError",
    "ModelTypeMismatchError", "UnknownModelError", "UnregisteredModelError",
    "VersionedModelError",

    "Registration", "VersionedModel", "VersionedModelRegistry",
    
    "JSON_KEY", "TYPE_KEY", "from_kv", "has_envelope", "to_kv",
    "KVBackend", "VersionedModelIO",
]
