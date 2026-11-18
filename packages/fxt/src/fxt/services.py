"""
A service is defined as any singletons/etc that need to use SETTINGS when
initialized!
"""
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from functools import lru_cache
from fxt.settings import get_settings, get_secrets


#!================================================================================(80)
#! for: parquet store
#!--------------------------------------------------------------------------------(80)
from fxt.core.io.parquet_store import ParquetStore

@lru_cache
def get_parquet_store() -> ParquetStore:
    """ Returns the ParquetStore singleton.
    """
    return ParquetStore(settings=get_settings().parquet_store)


#!================================================================================(80)
#! for: datalake
#!--------------------------------------------------------------------------------(80)
from fxt.lake import Lake

@lru_cache
def get_lake() -> Lake:
    """ Returns the Lake utility singleton.
    """
    return Lake(root=get_settings().paths.datalake)
#


#!================================================================================(80)
#! for: research tables
#!--------------------------------------------------------------------------------(80)
from fxt.research import Research

@lru_cache
def get_research() -> Research:
    """ Returns the Research path builder singleton (data/research).
    """
    return Research(root=get_settings().paths.research)
#


#!================================================================================(80)
#! for: the experiment registry
#!--------------------------------------------------------------------------------(80)
def get_registry():
    """ The experiment registry (data/experiments.db), created on first use.
        Not cached: each caller gets its own connection.
    """
    from fxt.research.registry import Registry
    return Registry(get_settings().paths.experiments)
#


#!================================================================================(80)
#! for: notifier
#!--------------------------------------------------------------------------------(80)
from fxt.notify import Notifier

@lru_cache
def get_notifier() -> Notifier:
    """ Returns a Notifier that can be used to send messages to telegram.

        Use: send() or try_send()
    """
    s = get_secrets()
    return Notifier(token=s.TELEGRAM_TOKEN, user_id=s.TELEGRAM_USERID)
#





#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print
    from rich.pretty import pprint

    print()
    print()
    print("# [green bold]Settings Objects Summary[/]")
    print()

    pprint(get_settings())
    pprint(get_secrets())
    pprint(get_lake())
    pprint(get_research())
    

