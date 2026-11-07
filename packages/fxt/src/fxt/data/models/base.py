'''
Base classes for the various models types.

This includes:
- BaseMeta
  * these are the semi-flexible meta objects. they have a set of specific 
    values and can store "other" information in meta.other

- BaseMetaComponent
  * for small components that shouldn't be considered standalone models
  * these have very specific values, and don't accept extra values/fields
  * these were created so I could create field subsets for existing meta
    models for the purposes of storage.

- BaseIdentity
  * these are similar to components, but they are also frozen, so their values
    must be hashable

TODO: 
- rename BaseMetaComponent to BaseComponent?
- As of now, components and identities are basically the same thing, just frozen in
  different ways. I want to do something like: 
        
        class BaseIdentity(BaseComponent):
        
  ?


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
#from datetime import datetime
#from typing import Literal, Self
from abc import abstractmethod

from pydantic import BaseModel, Field, ConfigDict #, field_validator, field_serializer
#from pydantic import AwareDatetime, model_validator
#from class_registry import RegistryKeyError

#! local
#from ._registry import ModelRegistry
from fxt.registry import RegisteredModel
#from fxt.data.markets import BaseMarket, MarketRegistry




#!================================================================================(80)
#! setup (logging, types, etc)
#!--------------------------------------------------------------------------------(80)
#import logging
#logger = logging.getLogger(__name__)



#!================================================================================(80)
#! for: identity (useful for comparisons/hashing)
#!--------------------------------------------------------------------------------(80)
class BaseIdentity(BaseModel, frozen=True):
    """ Represents a base frozen model used for identity comparisons.
    """
#


#!================================================================================(80)
#! for: components (meant to store *specific* values...aka no extras)
#!--------------------------------------------------------------------------------(80)
class BaseMetaComponent(BaseModel):
    """ Represents a model component that is setup to ONLY accept certain fields,
        etc.
    """
    model_config = ConfigDict(
        extra="ignore",
        frozen=True,

        #! this is so it will build the component using another model based on
        #! the fields. this allows the component to contain a subset of the 
        #! fields the original model has.
        #! 
        #! So, for example, I have a component for sources, but only want two 
        #! fields from the BaseSource model. with from_attributes set to True,
        #! I can assign the source component field to a BaseSource and it will
        #! create the smaller model from the larger, complete model
        #! 
        #! The purpose of this is so I can control what gets stored in json.
        from_attributes=True
    )
#


#!================================================================================(80)
#! for: meta (meant to be flexible and store whatever is sent)
#!--------------------------------------------------------------------------------(80)
class BaseMeta(RegisteredModel):
    """ Sets up config + fields common to all meta
    """

    @abstractmethod
    def identity(self) -> BaseIdentity:
        """ For identity comparisons. Return a subclass of `BaseIdentity`
        """
    #

    #! represents a general "other" field so non-standard fields can be stored
    other:dict[str,str] = Field(
        default={}
    )

    #~ may not bother keeping these
    def get_other(self, key:str, default:str|None=None) -> str|None:
        """
        """
        return self.other.get(key, default)
    #
    def set_other(self, key:str, value:str) -> None:
        """ 
        """
        return self.other.update({
            key: value
        })
    #
#






#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from datetime import datetime
    from rich import print

    print()
    print("hi2u ~ from [bold cyan]base models~[/]")
    print()

