#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from fxtapps import create_logger
logger = create_logger("dataprep-downloader")

#THEY WOULDN"T SHUT UP
import logging
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


