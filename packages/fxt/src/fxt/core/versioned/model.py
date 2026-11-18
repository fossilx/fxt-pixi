'''
model

VersionedModel: base class for pydantic models that are stored with a
(name, version) type id, e.g. "ConsolidatedDataMeta@1".

The registry only attaches a `Registration` to the class; every method lives
here, so type checkers see real methods.

Registration is looked up in the class's OWN __dict__, never inherited. An
unregistered subclass of a registered model raises UnregisteredModelError
instead of silently serializing under its parent's type id.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .errors import UnregisteredModelError


#! name of the class attribute the registry sets (dunder => ignored by pydantic)
REGISTRATION_ATTR = "__fxt_registration__"


@dataclass(frozen=True, slots=True)
class Registration:
    """ What the registry attaches to a registered class. """
    name: str
    version: Any

    @property
    def typeid(self) -> str:
        return f"{self.name}@{self.version}"
#


class VersionedModel(BaseModel):
    """ Base model for use with VersionedModelRegistry. """

    #~ registration info (classmethods) ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~(70)
    @classmethod
    def get_registration(cls) -> Registration:
        reg = cls.__dict__.get(REGISTRATION_ATTR)
        if not isinstance(reg, Registration):
            raise UnregisteredModelError(
                f"{cls.__qualname__} is not registered. Subclasses do not "
                f"inherit their parent's registration; decorate it with "
                f"@registry.register(...)."
            )
        return reg

    @classmethod
    def is_registered(cls) -> bool:
        return isinstance(cls.__dict__.get(REGISTRATION_ATTR), Registration)

    @classmethod
    def get_registered_name(cls) -> str:
        return cls.get_registration().name

    @classmethod
    def get_registered_version(cls) -> Any:
        return cls.get_registration().version

    @classmethod
    def get_id(cls) -> str:
        """ "<name>@<version>" """
        return cls.get_registration().typeid

    #~ instance helpers ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~(70)
    def get_json(self) -> str:
        return self.model_dump_json()

    def serialize(self) -> tuple[str, str]:
        """ (typeid, json) """
        return (self.get_id(), self.get_json())
#-
