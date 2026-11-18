#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
from pathlib import Path
from typing import Self, Literal
from collections.abc import Sequence
import warnings

from pydantic import SecretStr, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich import print
from rich.panel import Panel







#!================================================================================(80)
#! settings via env files
#!--------------------------------------------------------------------------------(80)
class ENVSettings(BaseSettings):
    """ Meant to facilitate recursively loading settings from env files within 
        a tree.

        It can:
        - load from the current directory
        - load envs from the current dir, and up a set # of parent dirs
        - load envs from within the current python package

        TODO:
        - add support for multiple env filenames? Right now it assumes one

    """
    model_config = SettingsConfigDict(
        extra="allow",
        case_sensitive=True,
        env_file_encoding="utf-8",
        validate_default=True
    )

    @model_validator(mode="after")
    def warn_about_extra_settings(self) -> Self:
        """ 
        """
        if(self.model_extra):
            extra_keys = list(self.model_extra.keys())
            warnings.warn(
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
            - `levels` must be `>= 0` or it throws an error

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
        if(not label or not len(label)):
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
                v_s = v[:2] + ".." + v[-2:] if v_len >= 12 else "****"

                # if(v_len < 4):
                #     v_s = v[:1] + ".."
                # else:
                #     v_s = v[:2] + ".." + v[-2:]

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





#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from rich import print
    #from IPython import get_ipython #type: ignore
    #warnings.
    print("hi2u")

    