'''
errors

Exceptions for the versioned model system.
'''
from __future__ import annotations


class VersionedModelError(Exception):
    """ Base class for everything raised by fxt.core.versioned """


#! registry
class DuplicateModelError(VersionedModelError, RuntimeError):
    """ Raised when a (name, version) is already taken by a different class,
        or a class is registered under two different (name, version) keys.
    """

class InvalidRegistrationError(VersionedModelError, ValueError):
    """ Raised when a name/version can't be registered (bad name, or the
        version doesn't survive the str -> parse_version round trip).
    """

class UnregisteredModelError(VersionedModelError, TypeError):
    """ Raised when serializing a model class that was never registered.
        Note: subclasses do NOT inherit their parent's registration.
    """

class UnknownModelError(VersionedModelError, KeyError):
    """ Raised when a typeid isn't in the registry. """


#! envelope / io
class MissingEnvelopeError(VersionedModelError, KeyError):
    """ Raised when a metadata mapping doesn't contain the envelope keys. """

class ModelTypeMismatchError(VersionedModelError, TypeError):
    """ Raised by read_meta_as() when the stored model isn't the expected class. """
