#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
import warnings
from rich.console import Console


__all__ = [
    'warn'
]

#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
console = Console()

def rich_formatwarning(message, category, filename, lineno, line=None):
    # Print directly to stderr via rich console with markup
    console.print(
        f"[bold yellow]⚠️  {category.__name__}:[/bold yellow] {message} "
        f"[dim]({filename}:{lineno})[/dim]",
        highlight=False
    )
    # Return an empty string so the standard stream doesn't print a duplicate
    return ""
#
warnings.formatwarning = rich_formatwarning

def warn(*args, **kw):
    """ Wrapper for warnings.warn with rich formatting applied
    """
    warnings.warn(*args, **kw)
#





#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from rich import print
    #from IPython import get_ipython #type: ignore
    #warnings.
    warn("This is a styled rich warning message!", UserWarning)
    