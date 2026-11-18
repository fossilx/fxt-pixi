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
from pathlib import Path
from functools import lru_cache

from pydantic import BaseModel, SecretStr, Field
from pydantic_settings import (
    BaseSettings, PydanticBaseSettingsSource,
    SettingsConfigDict, TomlConfigSettingsSource,
)

from fxt.core.env import ENVSettings
from fxt.core.io.parquet_store import ParquetStoreSettings
from fxt.paths import PathSettings



#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)

CONFIG_FILE = 'fxt.toml'
CONFIG_ENV_VAR = "FXT_CONFIG"



#!================================================================================(80)
#! env file
#!--------------------------------------------------------------------------------(80)
class Secrets(ENVSettings):  
    #.env only
    #model_config = SettingsConfigDict(env_prefix="FXT_", env_file=".env")
    TELEGRAM_TOKEN: SecretStr
    TELEGRAM_USERID: int
#

@lru_cache
def get_secrets() -> Secrets:
    """ 
    """
    return Secrets.from_path_tree(__file__)
#

#! to test the env var setting...
#os.environ.setdefault(CONFIG_ENV_VAR, str(Path(__file__).parent / "xfxt.toml"))


#!================================================================================(80)
#! toml setup
#!--------------------------------------------------------------------------------(80)
def _toml_config() -> Path:
    """ toml file should be at the root of this package (not the pixi project)
    """
    config:Path
    src:str

    if(override := os.environ.get(CONFIG_ENV_VAR)): #"FXT_CONFIG"):
        src = f"env-var('{CONFIG_ENV_VAR}')"
        config = Path(override)
    else:
        src = f"config-file('{CONFIG_FILE}')"
        config = Path(__file__).parent / CONFIG_FILE

    if(not config.is_file()):
        raise FileNotFoundError(
            f"Failed to load fxt library settings using method: {src}, file: {config}"
        )
    return config
#

class Settings(BaseSettings):
    """
    """
    model_config = SettingsConfigDict(
        toml_file=_toml_config(),
        env_prefix="FXT_",
        env_nested_delimiter="__"
    )

    #name of field corrersponds to name of key (i think)
    parquet_store: ParquetStoreSettings
    paths: PathSettings = Field(default_factory=PathSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, TomlConfigSettingsSource(settings_cls))
    #
#-

@lru_cache
def get_settings() -> Settings:
    """ Switching to this (rather than get_env)
    """
    #return #FXTSettings.from_path_tree(__file__)
    return Settings() #type: ignore[call-arg]
#



#!================================================================================(80)
#! previewing/output
#!--------------------------------------------------------------------------------(80)
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.tree import Tree

def _fmt_value(value: object) -> str:
    """ Format a single leaf value; secrets are never revealed. 
    """
    if isinstance(value, SecretStr):
        n = len(value.get_secret_value())
        return f"[yellow]{'•' * 8}[/] [dim](secret, len {n})[/]"
    
    if isinstance(value, Path):
        status = "[green]✓[/]" if value.exists() else "[red]✗[/]"
        return f"{status} {escape(str(value))}"
    
    return f"{escape(repr(value))} [dim]({type(value).__name__})[/]"
#
 
def _build_tree(model: BaseModel, tree: Tree, mask_extra: bool) -> Tree:
    """ Recursively add a model's fields (and any extras) to a rich Tree. 
    """
    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            _build_tree(value, tree.add(f"[bold cyan]{name}[/]"), mask_extra)
        else:
            tree.add(f"[cyan]{name}[/]: {_fmt_value(value)}")
 
    # undeclared values (extra="allow") are plain strings, so mask them if asked
    for name, value in (model.model_extra or {}).items():
        shown = SecretStr(str(value)) if mask_extra else value
        tree.add(f"[magenta]{escape(name)}[/] [dim](extra)[/]: {_fmt_value(shown)}")
    return tree
#

_SECRET_COLORS = ['orchid1', 'orchid2', 'pale_violet_red1']
_SETTING_COLORS = ['cyan1', 'steel_blue1', 'aquamarine3']

def show_settings(
    settings: BaseModel | None = None,
    secrets: BaseModel | None = None,
    console: Console | None = None,
) -> None:
    """ Print the Settings and Secrets models as trees.
 
        - SecretStr values are always hidden (only their length is shown)
        - extra (undeclared) keys on Secrets are masked too, since they're plain strings
        - Paths show ✓/✗ for whether they exist
    """
    console = console or Console()
    settings = settings if settings is not None else get_settings()
    secrets = secrets if secrets is not None else get_secrets()
    
    console.print(Panel(
        "Settings are currently loaded in two ways:"
        f"\n- as [bold {_SETTING_COLORS[0]}]settings[/] -- from: [{_SETTING_COLORS[1]}]config.toml[/]"
        f"\n- as [bold {_SECRET_COLORS[0]}]secrets[/] -- from: [{_SECRET_COLORS[1]}].env[/]",
        #title=f"[bold orchid2]{title}[/]"
    ))

    for model, title, mask_extra in (
        (settings, "settings", False),
        (secrets, "secrets", True),
    ):
        if(str(title).lower() == "settings"):
            title_color = _SETTING_COLORS[0]
            tree_top = _SETTING_COLORS[1]
        elif(str(title).lower() == "secrets"):
            title_color = _SECRET_COLORS[0]
            tree_top = _SECRET_COLORS[1]
        
        tree = _build_tree(model, Tree(f"[bold {tree_top}]{type(model).__name__}[/]"), mask_extra)
        console.print(Panel(tree, title=f"[{title_color}]{title}[/]"))
#





#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from rich import print

    #print(Panel(get_settings())

    #print("NEEDS UPDATED")
    show_settings()


    sys.exit()
    


    # print()
    # print("# [bold green]env setup[/]")
    # print(f" - FROM_METHOD: {ENV._FROM_METHOD}")
    # print(" - FROM_ENV_FILES: ")
    # for i,f in enumerate(ENV._FROM_ENV_FILES):
    #     print(f"   [{i}] {f}")


    # print()
    # print("# [bold green]env file contents/secrets[/]")
    # ENV.print_summary()


    # print()
    # print( "Get a specific value:")

    # print(f"  - get_env_var->TELEGRAM_USERID: { get_settings().TELEGRAM_USERID }, type: {type(get_settings().TELEGRAM_USERID)}")



    # print()
    # print("Try to get an invalid value:")
    # print(f"  - get_path->INVALID: {get_path('INVALID')}")
    # print(f"  - get_secret->INVALID: {get_secret('INVALID')}")
    # print(f"  - get_secret->INVALID with default: {get_secret('INVALID', default='default_value')}")


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

