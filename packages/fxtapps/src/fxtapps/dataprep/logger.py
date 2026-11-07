#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from rich.logging import RichHandler
import logging

#from settings import get_settings
#from apps.dataprep.settings import get_settings
#from .settings import get_settings

#LOGGER_ID = get_settings('LOGGER_ID')
LOGGER_ID="[green]dataprep-apps[/]"


logging.basicConfig(
    level=logging.WARNING,
    #format="%(asctime)s [%(levelname)s] **%(name)s**: %(message)s",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)]
)
logger = logging.getLogger(LOGGER_ID)

__all__ = [
    'logger'
]


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    
    logger.warning("Example use of app logger.")
    

    