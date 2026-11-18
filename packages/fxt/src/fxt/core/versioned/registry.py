'''
registry

General case registry for versioned pydantic models.

    registry: VersionedModelRegistry[int] = VersionedModelRegistry(default_version=1)

    @registry.register("TickMeta", 1)
    class TickMetaV1(VersionedModel):
        symbol: str

    @registry.register("TickMeta", 2)
    class TickMetaV2(VersionedModel):
        symbols: list[str]

    registry.get_model("TickMeta@2")   # -> TickMetaV2

----------

Custom version types must be:
- orderable (__lt__, for max(); see functools.total_ordering)
- hashable (used as dict keys)
- round-trippable through str: parse_version(str(v)) == v
  (checked at registration time, so a bad version type fails immediately
  instead of when a file is read back)
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import logging
from collections.abc import Callable, Hashable, Iterator
from typing import Any, Generic, Protocol, TypeVar, cast

from .errors import (
    DuplicateModelError,
    InvalidRegistrationError,
    UnknownModelError,
)
from .model import REGISTRATION_ATTR, Registration, VersionedModel

logger = logging.getLogger(__name__)


#!================================================================================(80)
#! types
#!--------------------------------------------------------------------------------(80)
class SupportsLessThan(Hashable, Protocol):
    def __lt__(self, other: Any, /) -> bool: ...

TVersion = TypeVar("TVersion", bound=SupportsLessThan)
_T = TypeVar("_T", bound=VersionedModel)


#!================================================================================(80)
#! registry
#!--------------------------------------------------------------------------------(80)
class VersionedModelRegistry(Generic[TVersion]):
    """ Maps (name, version) -> VersionedModel subclass. """

    def __init__(
        self,
        default_version: TVersion,
        parse_version: Callable[[str], TVersion] | None = None,
    ):
        self.default_version = default_version
        self._parse_version: Callable[[str], TVersion] = parse_version or cast(
            "Callable[[str], TVersion]", type(default_version)
        )
        self._registry: dict[str, dict[TVersion, type[VersionedModel]]] = {}
    #

    #~======================================================================(70)
    #~ dunder
    #~----------------------------------------------------------------------(70)
    def __str__(self) -> str:
        s = f"[magenta bold]{self.__class__.__name__} Summary:[/]"
        for name, versions in self._registry.items():
            s += f"\n - [green bold]{name}:[/]"
            for model in versions.values():
                s += f"\n   - [cyan]{model.get_id()}[/] (class: {model.__name__})"
        return s

    def __contains__(self, typeid: object) -> bool:
        return isinstance(typeid, str) and self.has_model(typeid)

    def __getitem__(self, typeid: str) -> type[VersionedModel]:
        return self.get_model(typeid)

    def __iter__(self) -> Iterator[type[VersionedModel]]:
        for versions in self._registry.values():
            yield from versions.values()

    def __len__(self) -> int:
        return sum(len(v) for v in self._registry.values())

    #~======================================================================(70)
    #~ registering
    #~----------------------------------------------------------------------(70)
    def _check_key(self, name: str, version: TVersion) -> None:
        if not name or "@" in name:
            raise InvalidRegistrationError(
                f"Model name must be non-empty and must not contain '@': {name!r}"
            )
        try:
            roundtrip = self._parse_version(str(version))
        except Exception as e:
            raise InvalidRegistrationError(
                f"parse_version failed on str(version)={str(version)!r}: {e}"
            ) from e
        if roundtrip != version:
            raise InvalidRegistrationError(
                f"Version doesn't round-trip through str: {version!r} -> "
                f"{str(version)!r} -> {roundtrip!r}"
            )
    #

    def register(
        self,
        name: str,
        version: TVersion | None = None,
        *,
        overwrite: bool = False,
    ) -> Callable[[type[_T]], type[_T]]:
        """ Decorator factory that registers a VersionedModel subclass.

            Re-registering a class with the same module + class name (a module
            reload, or re-running a notebook cell) replaces the old class, so
            field changes take effect. A *different* class on a taken
            (name, version) raises DuplicateModelError unless overwrite=True.
        """
        def decorator(cls: type[_T]) -> type[_T]:
            v: TVersion = self.default_version if version is None else version
            self._check_key(name, v)
            reg = Registration(name=name, version=v)
            logger.debug(
                f"{self.__class__.__name__}: registering {reg.typeid} -> {cls.__qualname__}"
            )

            #! one class == one type id
            own = cls.__dict__.get(REGISTRATION_ATTR)
            if isinstance(own, Registration) and own != reg:
                raise DuplicateModelError(
                    f"{cls.__qualname__} is already registered as {own.typeid}; "
                    f"can't also register it as {reg.typeid}"
                )

            versions = self._registry.setdefault(name, {})
            existing = versions.get(v)
            if existing is not None and existing is not cls:
                same_def = (
                    existing.__module__ == cls.__module__
                    and existing.__name__ == cls.__name__
                )
                if same_def:
                    logger.debug(
                        f"{self.__class__.__name__}: replacing redefined class for {reg.typeid}"
                    )
                elif overwrite:
                    logger.warning(
                        f"{self.__class__.__name__}: overwriting {reg.typeid}: "
                        f"{existing.__qualname__} -> {cls.__qualname__}"
                    )
                else:
                    raise DuplicateModelError(
                        f"{reg.typeid} is already registered to "
                        f"{existing.__module__}.{existing.__qualname__}; new class: "
                        f"{cls.__module__}.{cls.__qualname__} (pass overwrite=True to replace)"
                    )

            setattr(cls, REGISTRATION_ATTR, reg)
            versions[v] = cls
            return cls

        return decorator
    #

    #~======================================================================(70)
    #~ lookup
    #~----------------------------------------------------------------------(70)
    def split_typeid(self, typeid: str) -> tuple[str, TVersion]:
        name, sep, version_str = typeid.partition("@")
        if not sep or not name:
            raise ValueError(f"Invalid typeid {typeid!r}; expected '<name>@<version>'")
        return name, self._parse_version(version_str)

    def get_model(self, typeid: str) -> type[VersionedModel]:
        name, version = self.split_typeid(typeid)
        versions = self._registry.get(name)
        if not versions:
            raise UnknownModelError(f"No models with name={name!r} are registered.")
        if version not in versions:
            known = ", ".join(str(k) for k in versions)
            raise UnknownModelError(
                f"No model {name}@{version} is registered (known versions: {known})."
            )
        return versions[version]

    def has_model(self, typeid: str) -> bool:
        try:
            self.get_model(typeid)
        except (ValueError, KeyError):
            return False
        return True

    def latest(self, name: str) -> type[VersionedModel]:
        """ Highest registered version for `name`. """
        versions = self._registry.get(name)
        if not versions:
            raise UnknownModelError(f"No models with name={name!r} are registered.")
        return versions[max(versions)]

    def validate_json(self, typeid: str, json_data: str | bytes) -> VersionedModel:
        return self.get_model(typeid).model_validate_json(json_data)
#-
