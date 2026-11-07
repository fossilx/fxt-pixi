#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from typing import Any

#local
from ..settings import _SETTINGS as _PARENT_SETTINGS


#!================================================================================(80)
#! settings for this tier/dir
#!--------------------------------------------------------------------------------(80)
class _SETTINGS(_PARENT_SETTINGS):
    """ App-specific settings
    """
    #from local env
    APP:str|None = None
#-


#! make sure this includes all the env files needed to provide all the
#! required fields (aka make sure levels is correct if using that approach)
#both work!!
#SETTINGS = _SETTINGS.from_path_tree(__file__, levels=2)
SETTINGS = _SETTINGS.from_pkg_tree(__file__)


#!================================================================================(80)
#! api/accessors
#!--------------------------------------------------------------------------------(80)
#def _get_settings_dict() -> dict:
#    return SETTINGS.model_dump()
#
def get_settings(key:str|None = None, default:Any|None = None) -> dict|Any:
    """ If no key is provided, returns entire env
    """
    #if(key is None):
    #   return _get_env_dict()
    if(key is None):
        return SETTINGS
    #else:
    return getattr(SETTINGS, key, default)
#




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print

    print()
    print("# [bold green]env setup[/]")
    print(f" - FROM_METHOD: {SETTINGS._FROM_METHOD}")
    print(" - FROM_ENV_FILES: ")
    for i,f in enumerate(SETTINGS._FROM_ENV_FILES):
        print(f"   [{i}] {f}")

    print()
    print("# [bold green]env file contents/secrets[/]")
    SETTINGS.print_summary()
    