#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

from pathlib import Path
from typing import Any
from dataclasses import dataclass
from functools import cached_property

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


#from logger import logger
from .logger import logger



#!================================================================================(80)
#! PATHS
#!--------------------------------------------------------------------------------(80)
def get_app_root():
    """
    """
    return Path(__file__).parent
#

@dataclass
class _APP_PATHS:
    """ Dataclass holding important project paths.
    """
    #! optional hardcoded root
    _root: Path|None = None

    #~ core/independent path
    @cached_property
    def ROOT(self) -> Path:
        """ Uses either the specified root, the pixi root (if it can find it),
            or the dir for this file.
        """
        if self._root is not None:
            return self._root
        return get_app_root()
    #

    @cached_property
    def SETTINGS(self) -> Path:
        """ Path to the settings file
        """
        return PATHS.ROOT / ".env"
    #

    #~ facilitate iteration/looping
    def paths(self) -> dict[str, Path]:
        """ Returns a dictionary mapping property names to evaluated Path objects."""
        result = {}
        # Look through the class dictionary for cached_property descriptors
        for name, attr in vars(type(self)).items():
            if isinstance(attr, cached_property):
                result[name] = getattr(self, name)
        return result
    #
    def __iter__(self):
        """Allows direct iteration over (name, path) pairs or Path values."""
        return iter(self.paths().items())
    #
    
#
#! api
PATHS = _APP_PATHS() 


#!================================================================================(80)
#! ENV FILE SUPPORT
#!--------------------------------------------------------------------------------(80)
class _SETTINGS(BaseSettings):
    """ Load settings/secrets from the .env file at the project root.
        
        - Uses support builtin to `pydantic_settings`
          https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/
        - `pydantic_settings` also is fairly flexible when it comes to importing
          and using env-variables.
        - For values defined as secrets (via `SecretStr`), those must be accessed 
          a specific way (you can't just print/access them).
    """
    model_config = SettingsConfigDict(
        #env_file=PATHS.ROOT / ".env",
        extra="allow",
        env_file_encoding="utf-8",
        env_file=PATHS.ROOT / ".env"
    )

    GOD: str|None = None

    TIME_COL:str

    DOWNLOADS_DIR:str
    DOWNLOADS_MANIFEST:str

    CONSOLIDATED_DIR:str
    CONSOLIDATED_MANIFEST:str

    #! for extra vars not included here, their names are automatically
    #! converted to lowercase! 

    #bring in specific keys from .env file
    #TELEGRAM_TOKEN: SecretStr|None = None
    #TELEGRAM_USERID: int|None = None
    #
    
    #no defaults to ensure that values are specified in the env
    # PARQUET_METADATA_JSON_KEY:str
    # PARQUET_METADATA_TYPE_KEY:str
    
    # DOWNLOADER_MANIFEST:str
    # DOWNLOADER_MAX_RETRIES:int
#


#! api
ENV = _SETTINGS() # type: ignore[call-arg]


def _get_settings_dict() -> dict:
    return ENV.model_dump()
#
def get_settings(key:str|None = None, default:Any|None = None) -> dict|Any:
    """ If no key is provided, returns entire env
    """
    if(key is None):
        return _get_settings_dict()
    #else:
    return getattr(ENV, key, default)
#


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print
    #print("ROOT:", ROOT)
    print()

    #print(PATHS)
    #print(PATHS.ROOT)
    #print(PATHS.SETTINGS)
    #print(PATHS.paths())

    print("# [bold green]paths:[/]")
    # #print(f" - [cyan]ROOT[/]: {PATHS.ROOT}")
    for k,v in PATHS:
        print(f" - [cyan]{k}[/]: {v}")

    print()
    print("# [bold green]env file contents/secrets[/]")
    #for k,v in get_env().model_dump().items():
    #for k,v in get_env_dict().items():
    for k,v in get_settings().items():
        if isinstance(v, SecretStr):
            v = v.get_secret_value()
            v_len = len(v)
            if(v_len < 4):
                v_s = v[:1] + ".."
            else:
                v_s = v[:2] + ".." + v[-2:]
            print(f" - [orchid1]{k}[/]: {v_s} (len: {v_len})")
        else:
            print(f" - [orchid2]{k}[/]: {v} (type: {type(v)})")
