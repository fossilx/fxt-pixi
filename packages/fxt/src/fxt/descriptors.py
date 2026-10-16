#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from functools import cache

__all__ = [
    'cached_classproperty',
    'classproperty'
]

#!================================================================================(80)
#! decorators
#!--------------------------------------------------------------------------------(80)
class cached_classproperty:
    """ Creates a cached class property.

        Descriptor that evaluates a class method once, attaches the result
        directly to the class namespace, and replaces itself.
    """
    def __init__(self, func):
        self.func = cache(func)
        # Propagate abstract status to abc/Pydantic checking machinery
        self.__isabstractmethod__ = getattr(func, "__isabstractmethod__", False)
 
    # def __get__(self, instance, owner=None):
    #     if owner is None:
    #         owner = type(instance)
    #     return self.func(owner)
    def __get__(self, instance, owner=None):
        if owner is None:
            owner = type(instance)
        
        # Compute value once
        value = self.func(owner)
        
        # Overwrite the descriptor on the owner class so subsequent reads 
        # bypass descriptor lookup entirely and return the cached value directly
        setattr(owner, self.func.__name__, value)
        return value
#

class classproperty:
    """ Create properties from classmethods (without caching)
    """
    def __init__(self, fget=None, fset=None):
        self.fget = fget
        self.fset = fset

    def __get__(self, instance, owner):
        if self.fget is None:
            raise AttributeError("unreadable attribute")
        return self.fget(owner)

    def __set__(self, instance, value):
        if self.fset is None:
            raise AttributeError("can't set attribute")
        # Determine the owner class whether accessed via the class or an instance
        owner = instance if isinstance(instance, type) else type(instance)
        self.fset(owner, value)

    def setter(self, fset):
        return type(self)(self.fget, fset)
    
#     def __init__(self, func):
#         self.func = func

#     def __get__(self, instance, owner=None):
#         if owner is None:
#             owner = type(instance)
#         return self.func(owner) 

#     def __set__(self, instance, value):
#         if self.fset is None:
#             raise AttributeError("can't set attribute")
#         # Determine the owner class whether accessed via the class or an instance
#         owner = instance if isinstance(instance, type) else type(instance)
#         self.fset(owner, value)
# #




