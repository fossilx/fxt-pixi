'''
model_registry

This module provides a general case registry for versioned pydantic
models.

The registry is responsible for taking in a model (as a class), modifying 
it as needed, and adding it to the registry.

----------

To add something to the registry, you use decorators:
    
    #int is the version type
    registry:ModelRegistry[int] = ModelRegistry(default_version=1)
    
    @registry.register("TickMeta", 1)
    class TickMetaV1(RegisteredModel):
        symbol:str

    @registry.register("TickMeta", 6)
    class TickMetaV2(RegisteredModel):
        symbols:list[str]
    
----------

To create a custom version object, it must support:
- numerical comparison (ie for max())
  - look into functools.total_ordering
- must support a string representation...it has to be able to become
  a string, and then support going from string -> obj
- the version is used as dict keys in the registry, therefore it must
  be hashable!

theoretical example:

    from functools import total_ordering 
    @total_ordering
    class SemVer:
        def __init__(self, major: int, minor: int, patch: int):
            self.major = major
            self.minor = minor
            self.patch = patch

        def __eq__(self, other: Any) -> bool:
            if not isinstance(other, SemVer):
                return NotImplemented
            return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)

        def __lt__(self, other: Any) -> bool:
            if not isinstance(other, SemVer):
                return NotImplemented
            return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

        def __repr__(self) -> str:
            return f"{self.major}.{self.minor}.{self.patch}"
        
        def __hash__(self) -> int:
            return hash((self.major, self.minor, self.patch))



'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
# stop pylance from being annoying by adding this to end of line:  # type: ignore
# https://rich.readthedocs.io/en/stable/appendix/colors.html

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations
import logging
from datetime import datetime
from pydantic import BaseModel

from typing import Generic, TypeVar, Protocol, Any, cast
from collections.abc import Callable, Hashable


#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)

logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)


#! exceptions
class DuplicateModelError(RuntimeError):
    """ Raised when attempting to define a model with name/version that 
        was already used.
    """
#


#!================================================================================(80)
#! define types
#!--------------------------------------------------------------------------------(80)
#TModel = TypeVar("TModel", bound="RegisteredModel")
_T = TypeVar("_T", bound="RegisteredModel") #used for the decorator

#! ensure version can be compared
class SupportsLessThan(Hashable, Protocol):
    """ All that is needed for max()
    """
    def __lt__(self, other: Any, /) -> bool: ...

# Bind the TypeVar to our protocol
TVersion = TypeVar("TVersion", bound=SupportsLessThan)




#!================================================================================(80)
#! base model
#!--------------------------------------------------------------------------------(80)
class RegisteredModel(BaseModel):
    """ Base model for use with the registry
        
        The registry adds methods/private attrs to the model. The model itself
        doesn't need to know anything about them though.
        
        Note:
        - if needed, you can create a model with a generic type like so
          class RegisteredModel(BaseModel, Generic[T]):
              ...
          
          need to verify/test this though
    """
    @classmethod
    def get_id(cls) -> str: raise NotImplementedError
    
    def get_json(self) -> str: raise NotImplementedError
    def serialize(self) -> tuple[str, str]: raise NotImplementedError
#-


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class RegistryEntry(BaseModel):
    model:type[RegisteredModel]
    classname:str
#

#class ModelRegistry(Generic[TModel,TVersion]):
class VersionedModelRegistry(Generic[TVersion]):
    """
    """
    _MODEL_ATTR_PREFIX:str = "_fxt_model_registry_"
    
    @classmethod
    def _attr(cls, name:str) -> str:
        return f"{cls._MODEL_ATTR_PREFIX}{name}"
    #
    
    
    def __init__(
        self, 
        default_version:TVersion,
        parse_version: Callable[[str], TVersion] | None = None,
    ):
        """
        """
        self.default_version = default_version
        #self._registry: dict[str, dict[TVersion, type[RegisteredModel]]] = {}
        self._registry: dict[str, dict[TVersion, RegistryEntry]] = {}

        self._parse_version = parse_version or cast(
            "Callable[[str], TVersion]", type(default_version)
        )
    #
    def __str__(self) -> str:
        """
        """
        s = f"[magenta bold]{self.__class__.__name__} Summary:[/]"
        for k,versions in self._registry.items():
            s += f"\n - [green bold]{k}:[/]"
            #for version,model in versions.items():
            for entry in versions.values():
                model = entry.model
                s += f"\n   - [cyan]{model.get_id()}[/] (class: {model.__name__})"
        return s
    #

    def __contains__(self, item):
        """
        """
        return self.has_model(item)
    #

    def __getitem__(self, key):
        """
        """
        if(key not in self):
            raise KeyError(f"Key `{key}` not in this {self.__class__.__name__}")
        
        return self.get_model(key)
    #


    #~======================================================================(70)
    #~ adding models to registry
    #~----------------------------------------------------------------------(70)
    def register(self, name:str, version:TVersion|None=None, overwrite=False) -> Callable[[type[_T]], type[_T]]:
        """ This adds the wrapped pydantic model class to the registry
            This is a decorator factory. It must return a decorator function

            If you specify overwrite, it will not stop you from overwriting an
            existing model's registration.
        """
        def decorator(cls: type[_T]) -> type[_T]:
            """ This takes in the corresponding class in `cls`, adds it to the
                registry, and returns the class.
                
                If it needs to make changes to the class, that would happen here
                (in this case none are needed).
            """
            #create local versions since it has some weird issues otherwise
            _name = name
            _version = version
            if(_version is None):
                _version = self.default_version
            logger.debug(
                f"{self.__class__.__name__}: Attempting to register [white]("
                f"[magenta]name: [bold]{_name}[/], "
                f"[green]version: [bold]{_version}[/], "
                f"[bright_yellow]classname: [bold]{cls.__name__})[/]"
            )

            if _name not in self._registry:
                self._registry[_name] = {}

            #------------------------------------------------------------(60)

            #! if we are trying to redefine an existing model, make sure we are allowed to
            if(_version in self._registry[_name]):
                #~ this name/version exists, check it's classname
                existing = self._registry[_name][_version]

                #~ case: we already have this exact combo in our registry
                if(cls.__name__ == existing.classname):
                    logger.debug(
                        f"{self.__class__.__name__}: ...skipping registration; combination already registered; ("
                        f"[magenta]name: [bold]{_name}[/][/], "
                        f"[green]version: [bold]{_version}[/][/], "
                        f"[bright_yellow]classname: [bold]{cls.__name__}[/][/])"
                    )
                    return cls

                #~ case: this is a new (name, version, class) combo
                else:
                    #case: not equal, overwrite
                    if(overwrite):
                        logger.warning(
                            f"{self.__class__.__name__}: ...overwriting cls for "
                            f"([magenta]name: [bold]{_name}[/][/], [green]version: [bold]{_version}[/][/]), "
                            f"from: [yellow]{existing.classname}[/] -> to: [bold yellow1]{cls.__name__}[/]"
                        )

                    #case: not equal, don't overwrite, error
                    else:
                        logger.error(
                            f"{self.__class__.__name__}: ...registration failed; name/version exists, overwrite=False; current: ("
                            f"[magenta]name: [bold]{_name}[/][/], "
                            f"[green]version: [bold]{_version}[/][/], "
                            f"[bright_yellow]classname: [bold]{existing.classname}[/][/]);"
                            f" new class: {cls.__name__}"
                        )
                        raise DuplicateModelError(
                            f"{self.__class__.__name__}: Attempting to OVERWRITE EXISTING, overwrite=False; current: ("
                            f"name: {_name}, "
                            f"version: {_version}, "
                            f"classname: {existing.classname});"
                            f" new class: {cls.__name__}"
                        )
            #
                    

            #------------------------------------------------------------(60)

            #! add registry-components to it
            #add class properties (name/version)
            setattr(cls, self._attr("name"), _name)
            setattr(cls, self._attr("version"), _version)
            
            #add classmethods (these depends on cls)
            #@classmethod
            def get_id(cls:type[RegisteredModel]) -> str:
                n = getattr(cls, self._attr("name"), None)
                v = getattr(cls, self._attr("version"), None)
                if(n is None or v is None):
                    raise ValueError(f"Failed to get model id; missing required attrs; n: {n}, v: {v}")
                return f"{n}@{v}"
            
            #add instance methods (depends on self)
            def get_json(self:RegisteredModel) -> str: #
                return self.model_dump_json()
            def serialize(self:RegisteredModel) -> tuple[str,str]:
                return (self.get_id(), self.get_json())
            
            #cls.get_id = get_id
            #cls.get_json = get_json
            #cls.serialize = serialize
            setattr(cls, "get_id", classmethod(get_id))
            setattr(cls, "get_json", get_json)
            setattr(cls, "serialize", serialize)

            #! save it
            self._registry[_name][_version] = RegistryEntry(
                model=cls,
                classname=cls.__name__
            )
            

            return cls

        return decorator
    #

    #~======================================================================(70)
    #~ json -> model
    #~----------------------------------------------------------------------(70)
    def has_model(self, typeid: str) -> bool:
        """
        """
        try:
            _m:type[RegisteredModel] = self.get_model(typeid)
        except Exception:
            return False

        return True
        #
    #
    def get_model(self, typeid: str) -> type[RegisteredModel]:
        """ Find the corresponding model based on a provided string typeid, which
            combines both the name and version.

            for now, assume "@" is always present
        """
        try:
            name, version_str = typeid.split("@", 1)
        except Exception:
            raise ValueError("Invalid typeid! It failed to split on @")
        #
        
        #fix version type
        #version = type(self.default_version)(version)
        version = self._parse_version(version_str)

        #logger.debug(f"get_model() -> {typeid} -> name: {name} ({type(name)}), version: {version} ({type(version)})")

        if(name not in self._registry):
            raise KeyError(f"No models with name='{name}' are registered.")
        if(version not in self._registry[name]):
            raise KeyError(f"No model with (name='{name}', version='{version}') is registered.")

        return self._registry[name][version].model

        # #! case: only name specified (e.g., "TickMeta") -> Pick highest version
        # name = key
        # if(name not in self._registry or not self._registry[name]):
        #     raise KeyError(f"No models registered under name '{name}'.")

        # highest_version = max(self._registry[name].keys())
        # return self._registry[name][highest_version]
    #

    def validate_json(self, key: str, json_data: str | bytes) -> RegisteredModel:
        """
        """
        model_cls = self.get_model(key)
        return model_cls.model_validate_json(json_data)
    #
#-





#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print

    from fxt.term import pause, clear



    def test_registry():
        """
        """
        #! create registry and add some models to it
        #from fxt.data.models import RegisteredModel
        registry:VersionedModelRegistry[int] = VersionedModelRegistry(default_version=1)

        @registry.register("TickMeta", 1)
        class TickMetaV1(RegisteredModel):
            symbol:str

        @registry.register("TickMeta", 6 )
        class TickMetaV2(RegisteredModel):
            symbols:list[str]

        @registry.register("ConsolidatedMeta", 1)
        class ConsolidatedMeta(RegisteredModel):
            symbol:str
            start:datetime
            end:datetime

        print("#### [bold bright_yellow]MODELS IN REGISTRY[/]")
        print(str(registry))
        print()
        #pause()
        #clear()


        #----------------------------------------(40)
    
        #! ENCODE
        objs = [
            TickMetaV1(symbol="GBP"), #wtf, why does it say "No parameter named "symbol"?
            TickMetaV2(symbols=["GBP", "EUR", "JPY"]),
            ConsolidatedMeta(
                symbol="EURUSD",
                start=datetime(2025,1,1),
                end=datetime(2025,12,31)
            )
        ]

        print("\n#### [bold bright_yellow]INSTANCES[/]")
        serialized = []
        for o in objs:
            #model_typeid = o.get_id()
            #model_json = o.get_json()
            model_typeid, model_json = o.serialize()
            print(f" x [bold cyan]{model_typeid}[/]: {model_json}")
            serialized.append((model_typeid, model_json))

        #pause()
        #clear()


        #~ now reverse it
        #add an extra version of the last entry without the version #
        # last = serialized[-1]
        # serialized.append(
        #     (last[0][:-2], last[1])
        # )

        # serialized.append(

        #     {"version":1,"symbols":["GBP","EUR","JPY"]}
        # }

        print("\n#### [yellow]Reversing the process...[/]")
        #deserialized = []
        for o in serialized:
            model_typeid, model_json = o
            model = registry.get_model(model_typeid)
            instance = model.model_validate_json(model_json)
        #     deserialized.append(m.model_validate_json(obj_json))
            print(
                f" - [cyan]{model_typeid}[/cyan]\n"
                f"   json: {model_json}\n"
                f"   {instance}"
            )
    #

    #test_registry()
    #pause()
    #clear()

    def test_overwrite():
        print("\n# [yellow]testing overwrite/add existing/etc[/]")

        #! create registry and add some models to it
        #from fxt.data.models import RegisteredModel
        registry:VersionedModelRegistry[int] = VersionedModelRegistry(default_version=1)

        @registry.register("TickMeta", 1)
        class TickMetaV1(RegisteredModel):
            symbol:str

        @registry.register("TickMeta", 2)
        class TickMetaV2(RegisteredModel):
            symbols:list[str]

        @registry.register("ConsolidatedMeta", 1)
        class ConsolidatedMeta(RegisteredModel):
            symbol:str
            start:datetime
            end:datetime

        #! trying an existing combo:
        print()
        print("### [bold orchid2]trying to register existing combo[/]")
        registry = test_add_existing(registry)
        
        #! to see it fail:
        try:
            print()
            print("### [bold orchid2]trying to overwrite[/] with [cyan]overwrite[/]=[yellow]False[/]")
            registry = test_overwrite_existing(registry, overwrite=False)
        except DuplicateModelError:
            print("    [bold green]SUCCESS[/] ~ successfully triggered DuplicateModelError")
        else:
            print("    [bold red]FAILED![/] ~ failed to trigger DuplicateModelError")

        #! to see it overwrite:
        print()
        print("### [bold orchid2]trying to overwrite[/] with [cyan]overwrite[/]=[yellow]True[/]")
        registry = test_overwrite_existing(registry, overwrite=True)


        #! see final result
        print()
        print("#### [bold orchid2]final models in registry[/]")
        print(str(registry))
        print()


    #
    def test_add_existing(registry):
        """ will try to register again with same id/version/classname
        """
        @registry.register("TickMeta", 1)
        class TickMetaV1(RegisteredModel):
            symbol:str

        return registry
    #


    def test_overwrite_existing(registry, overwrite=False):
        """ used for testing the overwrite functionality (aka with new cls)
        """
        @registry.register("TickMeta", 1, overwrite=overwrite)
        class TickMetaV6(RegisteredModel):
            symbol:str

        return registry
    #

    test_overwrite()