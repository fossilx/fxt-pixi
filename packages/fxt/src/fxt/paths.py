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
import tomllib

from pydantic import model_validator, BaseModel, ConfigDict, Field

#from fxt.warn import warn



#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)




#!================================================================================(80)
#! original
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
    """
    if(not start_path.exists()):
        raise ValueError(
            "the provided path doesn't exist; how can it be a pixi project; "
            f"provided path: \n    {start_path}"
        )

    #----------------------------------------(40)

    for parent in start_path.resolve().parents:

        if (parent / "pixi.toml").exists():
            return parent
        
        pyproj = parent / "pyproject.toml"
        if pyproj.exists() and pyproject_has_pixi_section(pyproj):
            return parent
    
    env = os.environ.get("PIXI_PROJECT_ROOT")
    return Path(env) if env else None
#


#!================================================================================(80)
#! new
#!--------------------------------------------------------------------------------(80)
def find_project_root() -> Path:
    if env := os.environ.get("PIXI_PROJECT_ROOT"):   # set by `pixi run` / `pixi shell`
        return Path(env)
    for d in (Path.cwd(), *Path.cwd().parents):
        if (d / "pixi.toml").exists():
            return d
    raise RuntimeError("Couldn't find the project root (no pixi.toml found)")
#



class PathSettings(BaseModel):
    """
    """
    model_config = ConfigDict(extra="forbid")

    root:Path = Field(default_factory=find_project_root)
    jupyter:Path = Path("jupyter")
    dataprep:Path = Path("data/dataprep")
    datalake:Path = Path("data/lake")
    research:Path = Path("data/research")

    @model_validator(mode="after")
    def _resolve(self):
        self.root = self.root.expanduser().resolve()
        for name in ("jupyter", "dataprep", "datalake", "research"):
            p = getattr(self, name).expanduser()
            setattr(self, name, p if p.is_absolute() else self.root / p)
        return self
#



# @dataclass(frozen=True)
# class _PATHS:
#     """ Dataclass holding important project paths.
#     """
#     #! optional hardcoded root
#     _root: Path|None = None

#     #~ core/independent path
#     @cached_property
#     def ROOT(self) -> Path:
#         """ Uses either the specified root, the pixi root (if it can find it),
#             or the dir for this file.
#         """
#         if self._root is not None:
#             return self._root
#         root = get_pixi_root()
#         return root if root is not None else Path(__file__).parent

#     #~ derivative/dependent paths
#     @cached_property
#     def JUPYTER(self) -> Path:
#         return self.ROOT / "jupyter"

#     # @cached_property
#     # def DOWNLOADS(self) -> Path:
#     #     return self.ROOT / "downloads"
#     # @cached_property
#     # def DATA(self) -> Path:
#     #     return self.ROOT / "data"

#     #~ facilitate iteration/looping
#     def paths(self) -> dict[str, Path]:
#         """ Returns a dictionary mapping property names to evaluated Path objects."""
#         result = {}
#         # Look through the class dictionary for cached_property descriptors
#         for name, attr in vars(type(self)).items():
#             if isinstance(attr, cached_property):
#                 result[name] = getattr(self, name)
#         return result
#     #
#     def __iter__(self):
#         """Allows direct iteration over (name, path) pairs or Path values."""
#         return iter(self.paths().items())
#     #
# #-

# #! api
# PATHS = _PATHS() #_Paths(_root=Path(..)) if you want to specify the root manually

# def get_paths() -> dict[str,Path]:
#     return PATHS.paths()
# #
# def get_path(key: str, default:str|Path|None=None) -> Path | None:
#     """ Get a specific path from the PATHS dataclass.
#         If the key does not exist, return default (usually `None`).
#     """
#     if(default is not None):
#         default = Path(default)
#     return get_paths().get(key, default)
# #


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    #from rich import print
    #from rich.panel import Panel
    from rich.pretty import pprint
    
    pprint(PathSettings())

