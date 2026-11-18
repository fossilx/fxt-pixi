#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
# stop pylance from being annoying by adding this to end of line:  # type: ignore
# https://rich.readthedocs.io/en/stable/appendix/colors.html

#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
from .utils import is_notebook
#from .settings import get_settings # , ENVSettings
#from .paths import get_paths, get_path

#from .descriptors import classproperty, cached_classproperty

# in lib top level __init__.py
import logging
logging.getLogger(__name__).addHandler(logging.NullHandler())

#!================================================================================(80)
#! exports
#!--------------------------------------------------------------------------------(80)
__all__ = [
    #'ENVSettings',
    #'get_path',
    #'get_paths',
    #'get_settings',
    'is_notebook',
]



#!================================================================================(80)
#! local
#!--------------------------------------------------------------------------------(80)
import warnings
from rich.console import Console
_console = Console()

def rich_formatwarning(message, category, filename, lineno, line=None):
    # Print directly to stderr via rich console with markup
    _console.print(
        f"[bold yellow]⚠️  {category.__name__}:[/bold yellow] {message} "
        f"[dim]({filename}:{lineno})[/dim]",
        highlight=False
    )
    # Return an empty string so the standard stream doesn't print a duplicate
    return ""
#
warnings.formatwarning = rich_formatwarning



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from pathlib import Path
    from rich import print

    print()
    print(f"hi2u ~ from [bold cyan]{Path(__file__).name}~[/]")
    print()
    warnings.warn("Example warning")

