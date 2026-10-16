#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from datetime import datetime, timezone
import difflib
from typing import Type

from pydantic import BaseModel, ConfigDict, Field, field_validator

import dukascopy_python as dp
import dukascopy_python.instruments as dp_instruments
from fxt.descriptors import cached_classproperty


from abc import abstractmethod
from datetime import datetime, 

#!================================================================================(80)
#! sources - not sure if im goign to keep this
#!--------------------------------------------------------------------------------(80)
#! helpers

def _lookup(kind: str, value: str, valid: dict[str, str]) -> str:
    """ Case-insensitive membership check; returns the uppercased key.
    """
    key = value.strip().upper()
    if key not in valid:
        close = difflib.get_close_matches(key, valid.keys(), n=5)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise ValueError(f"Invalid {kind} '{value}'.{hint}")
    return key
#
def _to_utc(value: datetime) -> datetime:
    """ Naive datetimes are assumed to be UTC; aware ones are converted to UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
#

#! base
class BaseDataSource(BaseModel):
    """
    """
    model_config = ConfigDict(ignored_types=(cached_classproperty,))
    
    #~======================================================================(70)
    #~ helpers
    #~----------------------------------------------------------------------(70)
    @classmethod
    def _lookup(cls, kind: str, value: str, valid: dict[str, str]) -> str:
        """ Case-insensitive membership check.
        """
        key = value.strip().upper()
        if key not in valid:
            close = difflib.get_close_matches(key, valid.keys(), n=5)
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            raise ValueError(f"Invalid {kind} '{value}'.{hint}")
        return key
    #

    #~======================================================================(70)
    #~ fields
    #~----------------------------------------------------------------------(70)
    symbols: str = Field(description="The instrument symbol.")
    intervals: str = Field(description="The interval/timeframe.")

    @field_validator("symbol", mode="before")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        """
        """
        if(value not in cls.SYMBOL_MAP):
            raise ValueError(f"Failed to validate SYMBOL; invalid value: `{value}`")
        return value
    #
    @field_validator("interval", mode="before")
    @classmethod
    def validate_interval(cls, value: str) -> str:
        """
        """
        if(value not in cls.INTERVAL_MAP):
            raise ValueError(f"Failed to validate INTERVAL; invalid value: `{value}`")
        return value
    #


    #~======================================================================(70)
    #~ subclasses need...
    #~----------------------------------------------------------------------(70)
    @cached_classproperty
    @abstractmethod
    def SYMBOL_MAP(cls) -> dict[str, str]:
        """ the broker's real symbol string.
        """
        ...
    #
    @cached_classproperty
    @abstractmethod
    def INTERVAL_MAP(cls) -> dict[str, str]:
        """ UPPERCASED interval -> the broker's real interval string.
        """
        ...
    #


    #~======================================================================(70)
    #~ inherited
    #~----------------------------------------------------------------------(70)
    @cached_classproperty
    def SYMBOLS(cls) -> tuple[str, ...]:
        """ All valid (uppercased) symbols.
        """
        return tuple(cls.SYMBOL_MAP)
    #
    @cached_classproperty
    def INTERVALS(cls) -> tuple[str, ...]:
        """ All valid (uppercased) intervals.
        """
        return tuple(cls.INTERVAL_MAP)
    #


    
    def is_symbol(self, value:str) -> bool:
        """ checks if this is a valid symbol
        """
        return value in self.symbols
        
    def is_interval(self, value:str) -> bool:
        """ either returns the proper interval str or False
        """
        return v in self.intervals
    def as_interval(self, v) -> str|None:
        """ returns proper interval 
        """
        if(self.is_interval(v)): return v
        if(self.is_interval(v.upper())): return v.upper()
        return None
    #
#-

#dukascopy




class Dukascopy(DataSource):
    """
    """
    def _build_map(prefix: str, module) -> dict[str, str]:
        """ This ensures that the map keys are always in uppercase, and it stores
            the original value as the map value (as this is what the API's expect).

            - This doesn't really matter much for dukascopy since those values are 
              all in uppercase anyway, but just in case.
            - All verifications later on are done vs the upper case version
            
            Map UPPERCASED value -> original value for every `prefix*` constant in 
            `module`.
        """
        mapping: dict[str, str] = {}
        for attr in dir(module):
            if attr.startswith(prefix):
                original = str(getattr(module, attr))
                mapping.setdefault(original.upper(), original)
        return mapping
    #

    @field_validator("intervals", "after")
    @classmethod
    def validate_intervals(cls, value):
        """ You may have to do this in sub classes cuz you have no idea 
            what values the broker/source needs.
            
            For example, dukascopy-python requires the use of strings witb
            capital letters, so "1h" should be "1H". So for dukascopy, you 
            can use this to ensure that all values are capital...granted fhat
            isn't needed cuz im gettj g them directly from the lib
        """
        return v
    #

    @cached_classproperty
    def SYMBOL_MAP(cls) -> dict[str, str]:
        return cls._build_map("INSTRUMENT_", dp_instruments)
    #
 
    @cached_classproperty
    def INTERVAL_MAP(cls) -> dict[str, str]:
        return cls._build_map("INTERVAL_", dp)
    #
#
    







#!================================================================================(80)
#! versioned models
#!--------------------------------------------------------------------------------(80)
# for model_registry.py
# so I can have a generic way to save/load/use versioned pydantic models
class VersionedModel(BaseModel):
    """
    """
    version: str = Field(default="1.0", frozen=True)
#

class ModelRegistry:
    """
        good ref for function decorators
        https://dev.to/digitalocean/python-decorators-from-basics-to-real-world-use-cases-n5f 
    """

    def __init__(self):
        self._registry: dict[str, Type[VersionedModel]] = {}

    def register(self, name: str, version: str):
        """ This is a decorator factory. It must return a decorator function
        """

        def decorator(cls: Type[VersionedModel]):
            """ This takes in the corresponding class in `cls`, adds it to the
                registry, and returns the class.
                
                If it needs to make changes to the class, that would happen here
                (in this case none are needed).
            """
            key = f"{name}@{version}"
            self._registry[key] = cls
            
            #return original class
            return cls

        return decorator

    def validate_json(self, key: str, json_data: str | bytes) -> VersionedModel:

        if key not in self._registry:
            raise KeyError(f"Model '{key}' is not registered.")
        
        model_cls = self._registry[key]
        return model_cls.model_validate_json(json_data)
#



class ParquetMeta(BaseModel):
    """
    """
    interval:str = Field() #Field(default="TICK")
    source:str = Field()
    symbol:str = Field()
    start:datetime = Field()
    end:datetime = Field()
    
    @field_validator("interval", mode="before")
    @classmethod 
    def validate_interval(cls, value):
        """ Make sure it's a valid value. May need to create classes to
            represent data sources/libs (that provide access to the 
            allowed intervals, symbols, whatever).
        """
        ...
    #
#


    





if __name__ == "__main__":
    from rich import print
    
    # Instantiate global registry
    registry = ModelRegistry()

    @registry.register("ParquetMeta", "1.0")
    class ParquetMetaV1(BaseModel):
        """
        """
        interval:str = Field() #Field(default="TICK")
        source:str = Field()
        symbol:str = Field()
        start:datetime = Field()
        end:datetime = Field()
    
        @field_validator("interval", mode="before")
        @classmethod 
        def validate_interval(cls, value):
            """ Make sure it's a valid value. May need to create classes to
                represent data sources/libs (that provide access to the 
                allowed intervals, symbols, whatever).
            """
            #...
            return value
        #
    #-
    
    json_payload = """
        {
            "interval": "TICK",
            "source": "DUKASCOPY",
            "symbol": "GBP/JPY",
            "start": "2026-10-07T09:30:00Z",
            "end": "2026-10-07T16:00:00Z"
        }
    """

    tick_v1 = registry.validate_json("ParquetMeta@1.0", json_payload)
    #print(f"Validated v1: {tick_v1.source} starting at {tick_v1.start}")
    print("[bold green]json validation test:[/]")
    for k,v in tick_v1.model_dump().items():
        print(f" - [cyan]{k}[/]: {v}")


'''
# 2. Register different model versions
@registry.register("TickMeta", "1.0")
class TickMetaV1(VersionedModel):

    source: str
    start: datetime
    end: datetime


@registry.register("TickMeta", "2.0")
class TickMetaV2(VersionedModel):

    source: str
    start: datetime
    end: datetime
    symbols: list[str]  # Added in v2.0


# --- Usage Example ---

# Raw JSON strings payload coming from an API/Event bus
json_v1_payload = """
{
    "source": "NYSE",
    "start": "2026-10-07T09:30:00Z",
    "end": "2026-10-07T16:00:00Z"
}
"""

# Validating against version 1.0
tick_v1 = registry.validate_json("TickMeta@1.0", json_v1_payload)
print(f"Validated v1: {tick_v1.source} starting at {tick_v1.start}")

'''
