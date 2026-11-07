#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
import sys
import os
import logging
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
import tomllib
from typing import Any, Self, Literal
from collections.abc import Sequence
#import warnings

from pydantic import SecretStr, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich import print
from rich.panel import Panel

from fxt.warn import warn


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
class _PATHS:
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
PATHS = _PATHS() #_Paths(_root=Path(..)) if you want to specify the root manually

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
#! base settings
#!--------------------------------------------------------------------------------(80)
class AppSettings(BaseSettings):
    """ Sets up the base/shared settings loader.
    """
    model_config = SettingsConfigDict(
        extra="ignore",
        env_file_encoding="utf-8",
        validate_default=True
    )
#

#!================================================================================(80)
#! base env class without the fields
#!--------------------------------------------------------------------------------(80)
class ENVSettings(AppSettings):
    """ Meant to facilitate loading settings from env files.

        It can:
        - load from the current directory
        - load envs from the current dir, and up a set # of parent dirs
        - load envs from within the current python package

        TODO:
        - add support for multiple env filenames? Right now it assumes one

    """
    model_config = SettingsConfigDict(
        extra="allow",
        case_sensitive=True
    )

    @model_validator(mode="after")
    def warn_about_extra_settings(self) -> Self:
        """ 
        """
        if(self.model_extra):
            extra_keys = list(self.model_extra.keys())
            warn(
                f"Unrecognized setting(s) detected: {extra_keys}. "
                "If this isn't deliberate, check your environment or .env file for typos. "
                "If the unrecognized setting(s) are going to stay, add them to the model "
                "so you can benefit from proper type checking."
                " Note: If you use secretstr's and rely on the print protection, YOU MUST "
                " DEFINE THEM IN THE MODEL OR THEY WILL SHOW AS NORMAL STRINGS"
                ,
                UserWarning
            )

        return self
    #


    #! private
    _FROM_ENV_FILES:Sequence[Path|str] = PrivateAttr(default_factory=list)
    _FROM_METHOD:Literal["pkg", "parent", "files"] = PrivateAttr(default="files")

    #~======================================================================(70)
    #~ static helpers
    #~----------------------------------------------------------------------(70)
    @staticmethod
    def find_pkg_envs(
        path:Path|str,
        name:str = ".env",
    ) -> tuple[Path|str, ...]:
        """ Adds all env files within the python package hierarchy by searching parent
            directories for the presence of `__init__.py`.  This will always add the env path
            for the currect dir, and then adds parent dirs as long as an `__init__.py` exists.
            It stops once `__init__.py` is no longer present.

            TODO: 
            - should i make it so they can specify what file identifies a potential env dir?
              (instead of limiting it to the python package identifier: __init__.py)

            Args
            - path: path to directory or file; if file, it changes it to the corresponding dir
            - name: env-file name

            
        """
        d = Path(path).resolve()
        if(d.is_file()):
            d = d.parent

        #start with current dir
        files = [d / name]
        d = d.parent
        while (d / "__init__.py").exists():
            files.append(d / name)
            if d.parent == d:  # filesystem root guard
                break
            d = d.parent
        return tuple(reversed(files))
    #

    @staticmethod
    def find_parent_envs(
        path:str|Path,
        levels:int = 0,
        name:str = ".env",
    ) -> tuple[Path|str, ...]:
        """ Return env file candidates from `path` up through `levels` parent directories.
            This always searches the directory with `path`

            Notes:
            - the env files don't have to exist. If they don't exist, they are skipped.
            - levels=0 -> only the starting directory.
            - Ordered from farthest ancestor to nearest, so with `pydantic-settings`
              (later files override earlier ones) the closest file wins.
        """
        if levels < 0:
            raise ValueError("levels must be >= 0")

        start = Path(path).resolve()
        if start.is_file():
            start = start.parent

        dirs = [start, *start.parents][: levels + 1]  # stops at the filesystem root
        return tuple(d / name for d in reversed(dirs))
    #

    #~======================================================================(70)
    #~ factory
    #~----------------------------------------------------------------------(70)
    #! main factory method
    @classmethod
    def from_env_files(cls, files:Sequence[Path|str]) -> Self:
        """ Constructs an instance from a tuple/list of env files.

            The order they are specified is the order they are loaded. The values
            in later env files overwrite the values from earlier ones.
        """
        obj = cls(_env_file=files) #type: ignore
        obj._FROM_ENV_FILES = files
        return obj
    #

    #! tree methods: allow you to search parent directorys for envs
    @classmethod
    def from_pkg_tree(cls, path:Path|str, append_envs:Sequence[str|Path]|None=None) -> Self:
        """ You provide a path to a file in a package, and it will create an env using
            all envs in that package hierarchy.

            If `append_envs` is set, it will add those paths to the end of the env file list
            so that their values take precedence.
        """
        files = list(cls.find_pkg_envs(path))
        if(append_envs is not None):
            files.extend(append_envs)
        
        obj = cls.from_env_files(files)
        obj._FROM_METHOD = "pkg"

        return obj

    #
    @classmethod
    def from_path_tree(cls, path:Path|str, levels:int=0, append_envs:Sequence[str|Path]|None=None) -> Self:
        """ Adds the current env file to the path (or closest directoryo in Path), and optionally,
            allows adding env file entries for `levels` parent dirs above it. It assumes that env 
            entries/values in the parent dirs should be overwritten as it goes down the dir tree, 
            with the closest env files taking precedence.
            
            - If `levels=0`, it doesn't add parent directory envs. 
            - `levels` must be `> 0` or it throws an error

            If `append_envs` is set, it will add those paths to the end of the env file list
            so that their values take precedence.
        """
        files = list(cls.find_parent_envs(path, levels=levels))
        if(append_envs is not None):
            files.extend(append_envs)
        
        obj = cls.from_env_files(files)
        obj._FROM_METHOD = "parent"

        return obj
        
    #
    
    #~======================================================================(70)
    #~ 
    #~----------------------------------------------------------------------(70)
    def print_summary(self, label:str|None=""):
        """
        """
        #! misc output settings
        gray = "gray58"
        

        #! label
        if(label is None):
            label = ""
        else: 
            label = f" ~ [bright_yellow]{label}[/]"

        #! creation summary
        from_files:str = ""
        for i, f in enumerate(self._FROM_ENV_FILES):
            f = Path(f)
            filename:str = f.name
            file_color = "bright_green" if f.exists() else "bright_red"
            
            file_s = str(f).replace(filename, f"[{file_color}]{filename}[/]")

            from_files += f"\n     [{gray}][{i}][/]: {file_s}"
        #from_files = from_files.replace("\n", "", 1)

        #! field summary
        fields = self.model_dump()
        summary:str = ""
        for k,v in fields.items():
            if isinstance(v, SecretStr):
                v = v.get_secret_value()
                v_len = len(v)
                if(v_len < 4):
                    v_s = v[:1] + ".."
                else:
                    v_s = v[:2] + ".." + v[-2:]

                #print(f" - {k}: {v_s} (len: {v_len})")
                summary += f"\n - [yellow](secret)[/] [cyan]{k}[/]: {v_s} [{gray}](len: {v_len})[/]"

            else:
                summary += f"\n - [cyan]{k}[/]: {v} [{gray}](type: {type(v)})[/]"


        print(Panel(
            f" - from method: [bright_yellow bold]{self._FROM_METHOD}[/]"
            f"\n - from files: ([bright_green]green[/]=exists, [bright_red]red[/]=doesnt exist) {from_files}"
            f"\n   {'-'*40}"
            f"\n [bold]Field Summary: [{gray}](# fields: {len(fields)})[/]"
            f"{summary}",
            title=f"[green]{type(self).__name__}[/]::[bright_green]summary[/]{label}",
            title_align="left"
        ))
    #
#-


#! testing static methods
def test_find_pkg_envs():
    testpath = Path("/home/tony/cloud/.rclone-sync/code/python/.jupyter-pixi/packages/fxtapps/src/fxtapps/dataprep/reader/settings.py")
    res = ENVSettings.find_pkg_envs(testpath)

    print("test_pkg_envs() -> load order:")
    for i, v in enumerate(res):
        print(f" - [{i}]: {v}")
#
#test_find_pkg_envs()
def test_find_parent_envs(levels:int=0):
    testpath = Path("/home/tony/cloud/.rclone-sync/code/python/.jupyter-pixi/packages/fxtapps/src/fxtapps/dataprep/reader/settings.py")
    res = ENVSettings.find_parent_envs(testpath, levels=levels)

    print(f"test_parent_envs(levels={levels}) -> load order:")
    for i, v in enumerate(res):
        print(f" - [{i}]: {v}")
#
# print()
# test_find_parent_envs(0)
# print()
# test_find_parent_envs(1)
# print()
#test_find_parent_envs(2)

#! testing factory methods
def test_from_path_tree(levels:int=0):
    testpath = Path("/home/tony/cloud/.rclone-sync/code/python/.jupyter-pixi/packages/fxtapps/src/fxtapps/dataprep/reader/settings.py")
    
    settings = ENVSettings.from_path_tree(testpath, levels=levels)
    #print(settings)
    settings.print_summary("test_from_path_tree")
#

#test_from_path_tree(2)



#sys.exit()
#!================================================================================(80)
#! custom app-specific env class with fields
#!--------------------------------------------------------------------------------(80)
#! everything is dependent on this var:
class FXTSettings(ENVSettings):
    """
    """
    GOD: str|None = None
    TELEGRAM_TOKEN: SecretStr|None = None
    TELEGRAM_USERID: int|None = None
    
    #no defaults to ensure that values are specified in the env
    PARQUET_METADATA_JSON_KEY:str
    PARQUET_METADATA_TYPE_KEY:str
    
    #DOWNLOADER_MANIFEST:str
    DOWNLOADER_MAX_RETRIES:int
#

ENV = FXTSettings.from_path_tree(__file__)



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












#!================================================================================(80)
#! ENV FILE SUPPORT
#!--------------------------------------------------------------------------------(80)
# class _ENV(BaseSettings):
#     """ Load settings/secrets from the .env file at the project root.
        
#         - Uses support builtin to `pydantic_settings`
#           https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/
#         - `pydantic_settings` also is fairly flexible when it comes to importing
#           and using env-variables.
#         - For values defined as secrets (via `SecretStr`), those must be accessed 
#           a specific way (you can't just print/access them).
#     """
#     model_config = SettingsConfigDict(
#         #env_file=PATHS.ROOT / ".env",
#         extra="ignore",
#         env_file_encoding="utf-8",
#         env_file=PATHS.ROOT / ".env"
#     )

#     #bring in specific keys from .env file
#     TELEGRAM_TOKEN: SecretStr|None = None
#     TELEGRAM_USERID: int|None = None
#     GOD: str|None = None
    
#     #no defaults to ensure that values are specified in the env
#     PARQUET_METADATA_JSON_KEY:str
#     PARQUET_METADATA_TYPE_KEY:str
    
#     #DOWNLOADER_MANIFEST:str
#     DOWNLOADER_MAX_RETRIES:int
# #

# #! api
# ENV = _ENV() # type: ignore[call-arg]


# def _get_env_dict() -> dict:
#     return ENV.model_dump()
# #

# def get_env(key:str|None = None, default:Any|None = None) -> dict|Any:
#     """ If no key is provided, returns entire env
#     """
#     if(key is None):
#         return _get_env_dict()
#     #else:
#     return getattr(ENV, key, default)
# #



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

    #enumerate()

    print()
    print("# [bold green]env setup[/]")
    print(f" - FROM_METHOD: {ENV._FROM_METHOD}")
    print(" - FROM_ENV_FILES: ")
    for i,f in enumerate(ENV._FROM_ENV_FILES):
        print(f"   [{i}] {f}")


    print()
    print("# [bold green]env file contents/secrets[/]")

    ENV.print_summary()
    #for k,v in get_env().model_dump().items():
    # #for k,v in get_env_dict().items():
    # for k,v in get_env().items():
    #     if isinstance(v, SecretStr):
    #         v = v.get_secret_value()
    #         v_len = len(v)
    #         if(v_len < 4):
    #             v_s = v[:1] + ".."
    #         else:
    #             v_s = v[:2] + ".." + v[-2:]
    #         #v_s = v[:2] + "..." + v[-3:] if v_len > 6 else v
    #         print(f" - {k}: {v_s} (len: {v_len})")
    #         #print(f" - {k}: {v} (len: {v_len})")
    #     else:
    #         #v = str(v)
    #         print(f" - {k}: {v} (type: {type(v)})")

    print()
    print( "Get a specific value:")
    print(f"  - get_path->datalake: { get_path('DATALAKE') }")
    print(f"  - get_env_var->TELEGRAM_USERID: { get_env('TELEGRAM_USERID') }, type: {type(get_env('TELEGRAM_USERID'))}")

    # print()
    # print("Try to get an invalid value:")
    # print(f"  - get_path->INVALID: {get_path('INVALID')}")
    # print(f"  - get_secret->INVALID: {get_secret('INVALID')}")
    # print(f"  - get_secret->INVALID with default: {get_secret('INVALID', default='default_value')}")

