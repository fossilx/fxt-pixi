#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
import difflib
import logging
from abc import abstractmethod
from pydantic import BaseModel, ConfigDict, Field

#fxt
from fxt.descriptors import cached_classproperty
from fxt.data.markets import BaseMarket



#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)




#!================================================================================(80)
#! base
#!--------------------------------------------------------------------------------(80)
class BaseSource(BaseModel):
    """ Provides a common interface for a specific data source. 
        
        It should provide a common interface for working with symbols and intervals
        that match that given source's API.
    
        notes:
        - for symbols/intervals, always work with the uppercased version
          - let the downloader get the version needed by the source.
    """
    #! pydantic config
    model_config = ConfigDict(ignored_types=(cached_classproperty,))

    #~======================================================================(70)
    #~ helpers
    #~----------------------------------------------------------------------(70)
    @classmethod
    def _lookup(cls, kind: str, value: str, valid: dict[str, str]) -> str:
        """ Case-insensitive membership check; returns the uppercased key.
        """
        key = value.strip().upper()
        if key not in valid:
            close = difflib.get_close_matches(key, valid.keys(), n=5)
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            raise ValueError(f"Invalid **{kind}**: '{value}'.{hint}")
        return key
    #


    #~======================================================================(70)
    #~ set these in subclasses
    #~----------------------------------------------------------------------(70)
    #! change these for your source
    id:str = Field(description="string id (slug-syntax) of the source; i.e. dukascopy")
    method:str = Field(description="Storing the method used to get the data; i.e. the library name")

    #! change these accordingly 
    TICK:str = Field(
        default="TICK",
        description=(
            "Whatever special value is used to indicate an interval of TICK;"
            " This is used by the downloader to determine metadata."
        ),
        exclude=True #stop this from being included in model dumps
    )



    @cached_classproperty
    @abstractmethod
    def SYMBOL_MAP(cls) -> dict[str, str]:
        """ Should return a dictionary of:
                { str(symbol).upper() : symbol }
            
            The values are the values used by the data source's API/lib.
        """
        ...
    #
    @cached_classproperty
    @abstractmethod
    def INTERVAL_MAP(cls) -> dict[str, str]:
        """ Same as SYMBOL_MAP, but for intervals.

            It is suggested that you ensure that the list of intervals is in
            order based on the duration. This might impact the order of terminal
            apps that use the intervals.
            
            Since each broker/source might use custom ways to representing time 
            intervals, it's not worth creating a general purpose way to parse these.
        """
        ...
    #

    #~======================================================================(70)
    #~ retrieval
    #~----------------------------------------------------------------------(70)
    def to_full_json(self, indent:int|None=None) -> str:
        """ Returns a complete representation of the source, with symbols
            and intervals

            This is because I don't want all this info included when I just
            want the basic meta info for storing in a parquet file.

            May change this system:
            - i can pass groups to model_dump() and model_dump_json()..so..

                class MyBaseModel(BaseModel):
                    #class property
                    ALL = None
                    SUBGRP = ['id', 'name']
                    
                
                    
                class MyModel(BaseModel):
                    SUBGRP = ['id', 'name']

                    def to_json(self, groups:list[str]|None=None):
                        #self.ALL is same as None
                        if(groups is None):
                            self.model_dump_json() #return all
                        elif(isinstance(groups, list)):
                            self.model_dump_json(include=groups)

                m = MyModel()
                m.to_json(MyModel.SUBGRP)
                
                -- just an possible way to handle it
                -- probably would want to create a base class that is
                   used across all bases that provide the function and
                   groups

                            
        """
        import json

        #take the base json
        data = json.loads(self.model_dump_json())

        #add desired fields
        data.update({
            "TICK": self.TICK,
            "symbols": list(self.SYMBOL_MAP.values()),
            "intervals": list(self.INTERVAL_MAP.values())
        })

        return json.dumps(data, indent=indent)
    #

    #~======================================================================(70)
    #~ retrieval
    #~----------------------------------------------------------------------(70)
    @cached_classproperty
    def SYMBOLS(cls) -> tuple[str, ...]:
        """ All valid (uppercased) symbols.
        """
        #tuple(dict) will automatically return a tuple from the keys
        #so... MAP.keys isn't technically needed, but i'd rather be explicit
        return tuple(cls.SYMBOL_MAP.keys()) 
    #
    @cached_classproperty
    def INTERVALS(cls) -> tuple[str, ...]:
        """ All valid (uppercased) intervals.
        """
        return tuple(cls.INTERVAL_MAP.keys())
    #

    def get_symbol(self, value):
        """ Provides a common way to get the broker/api version of a symbol
            that is case-insensitive
        """
        return self._lookup("symbol", value, self.SYMBOL_MAP)
    #
    def get_interval(self, value):
        """ Provides a common way to get the broker/api version of an interval
            that is case-insensitive
        """
        return self._lookup("interval", value, self.INTERVAL_MAP)


    #~======================================================================(70)
    #~ retrieval
    #~----------------------------------------------------------------------(70)
    @classmethod
    @abstractmethod
    def which_market(cls, symbol:str) -> type[BaseMarket]|None:
        """ Determines the market from the provided symbol
        """
    #

#-



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print

    print()
    print("hi2u ~ from [bold cyan]BaseSource~[/]")
    print()


    from typing import Literal

    class ExampleSource(BaseSource):
        """
        """
        id:str = "example-source"
        method:str = "example-lib"
        TICK:Literal["-tick-"] = "-tick-"


        @cached_classproperty
        def SYMBOL_MAP(cls) -> dict[str, str]:
            values = [
                "EURUSD", "EURJPY", "GBPUSD", "GBPJPY"
            ]
            return {v.upper() : v for v in values}
        #

        @cached_classproperty
        def INTERVAL_MAP(cls) -> dict[str, str]:
            values = [
                "1min", "1h", "4hour", "tick"
            ]
            return {v.upper() : v for v in values}
        #

    src = ExampleSource()
    print()
    print("[bold cyan]* intervals[/]")
    print(src.INTERVALS)
    print()
    print("[bold cyan]* symbols[/]")
    print(f" - # symbols: {len(src.SYMBOLS)}")
    print(f" - first few: {src.SYMBOLS[:5]}")
    print()
    print("[bold cyan]* model json[/]")
    print(src.model_dump_json())
    print()
    print("[bold cyan]* full json[/]")
    print(src.to_full_json(2))
