#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
import os
import logging
#from functools import lru_cache
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
import tomllib


from typing import Any
from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
#from traitlets import default




#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)



#!================================================================================(80)
#! re: project paths, etc.
#!--------------------------------------------------------------------------------(80)
def pyproject_has_pixi_section(filepath: str | Path) -> bool:
    """ Check's if the provided filepath contains a section that identifies
        it as a pixi config using the `toml` format.
    """
    path = Path(filepath)
    if not path.exists():
        return False

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
        
        tool_table = data.get("tool")
        if not isinstance(tool_table, dict):
            return False

        # Checks if 'pixi' exists as a sub-table under [tool]
        pixi_table = tool_table.get("pixi")
        return isinstance(pixi_table, dict) and bool(pixi_table)

    except Exception:
        return False
#
def get_pixi_root(start_path:Path = Path(__file__)) -> Path|None:
    """ Returns path of nearest pixi env, or None.
        
        Attempts to determine the path for the parent pixi env starting
        from the specified location (`start_path`) using the following
        methods..

        1. check env var: PIXI_PROJECT_ROOT 
           this is set when you run something with pixi
        
        2. looks for the nearest config file, which can be:
           
           a. pixi.toml, or

           b. pyproject.toml with the toml section:
              [tool.pixi.workspace]

        TODO: test this

    """
    if(not start_path.exists()):
        raise ValueError(
            "the provided path doesn't exist; how can it be a pixi project; "
            f"provided path: \n    {start_path}"
        )

    #----------------------------------------(40)

    #~check: PIXI_PROJECT_ROOT env var
    if "PIXI_PROJECT_ROOT" in os.environ:
        res = Path(os.environ["PIXI_PROJECT_ROOT"])
        logger.debug(f"pixi root identified via ENV at: {res}")
        return res

    else:
        for parent in start_path.resolve().parents:
            pixi_toml = parent / "pixi.toml"
            pyproj_toml = parent / "pyproject.toml"

            #~check: config->pixi.toml
            if(pixi_toml.exists()):
                logger.debug(f"pixi root identified via 'pixi.toml' at: {parent}")
                return parent
            #~check: config->pyproject.toml
            elif(pyproj_toml.exists() and pyproject_has_pixi_section(pyproj_toml)):
                logger.debug(f"pixi root identified via 'pyproject.toml' at: {parent}")
                return parent
    #~fallback
    return None
#

@dataclass(frozen=True)
class _Paths:
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
        root = get_pixi_root()
        return root if root is not None else Path(__file__).parent

    #~ derivative/dependent paths
    @cached_property
    def JUPYTER(self) -> Path:
        return self.ROOT / "jupyter"
    @cached_property
    def DOWNLOADS(self) -> Path:
        return self.ROOT / "downloads"
    @cached_property
    def DATALAKE(self) -> Path:
        return self.ROOT / "datalake"

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
#-

#! api
PATHS = _Paths() #_Paths(_root=Path(..)) if you want to specify the root manually

def get_paths() -> dict[str,Path]:
    return PATHS.paths()
#
def get_path(key: str, default:str|Path|None=None) -> Path | None:
    """ Get a specific path from the PATHS dataclass.
        If the key does not exist, return default (usually `None`).
    """
    if(default is not None):
        default = Path(default)
    return get_paths().get(key, default)
#


#!================================================================================(80)
#! ENV FILE SUPPORT
#!--------------------------------------------------------------------------------(80)
class _ENV(BaseSettings):
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
        extra="ignore",
        env_file_encoding="utf-8"
    )

    #bring in specific keys from .env file
    TELEGRAM_TOKEN: SecretStr|None = None
    TELEGRAM_USERID: int|None = None
    GOD: str|None = None
    
    #no defaults to ensure that values are specified in the env
    PARQUET_METADATA_JSON_KEY:str
    PARQUET_METADATA_TYPE_KEY:str
    
    DOWNLOADER_MANIFEST:str
    DOWNLOADER_MAX_RETRIES:int
#

#! api
ENV = _ENV(_env_file=PATHS.ROOT / ".env")

def _get_env_dict() -> dict:
    return ENV.model_dump()
#

def get_env(key:str|None = None, default:Any|None = None) -> dict|Any:
    """ If no key is provided, returns entire env
    """
    if(key is None):
        return _get_env_dict()
    #else:
    return getattr(ENV, key, default)
#



# def get_env_var(key: str, default: Any|None = None) -> Any|None:
#     """ Get a specific env var from the ENV model.
    
#         If the key does not exist, return the default value
#     """
#     secrets = get_env()
#     return getattr(secrets, key, default)
# #




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print
    #print("ROOT:", ROOT)
    print()
    print("# [bold green]project paths[/]")
    for k,v in get_paths().items():
        print(f" - [cyan]{k}[/]: {v}")


    print()
    print("# [bold green]env file contents/secrets[/]")
    #for k,v in get_env().model_dump().items():
    #for k,v in get_env_dict().items():
    for k,v in get_env().items():
        if isinstance(v, SecretStr):
            v = v.get_secret_value()
            v_len = len(v)
            if(v_len < 4):
                v_s = v[:1] + ".."
            else:
                v_s = v[:2] + ".." + v[-2:]
            #v_s = v[:2] + "..." + v[-3:] if v_len > 6 else v
            print(f" - {k}: {v_s} (len: {v_len})")
            #print(f" - {k}: {v} (len: {v_len})")
        else:
            #v = str(v)
            print(f" - {k}: {v} (type: {type(v)})")

    print()
    print( "Get a specific value:")
    print(f"  - get_path->datalake: { get_path('DATALAKE') }")
    print(f"  - get_env_var->TELEGRAM_USERID: { get_env('TELEGRAM_USERID') }, type: {type(get_env('TELEGRAM_USERID'))}")

    # print()
    # print("Try to get an invalid value:")
    # print(f"  - get_path->INVALID: {get_path('INVALID')}")
    # print(f"  - get_secret->INVALID: {get_secret('INVALID')}")
    # print(f"  - get_secret->INVALID with default: {get_secret('INVALID', default='default_value')}")

