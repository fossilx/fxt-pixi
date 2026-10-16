#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
import logging
from pathlib import Path
from pydantic import BaseModel, Field, field_validator, FilePath


from fxt import get_env
from fxt.data.schemas import METADATA_KEY



#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)

_METADATA_KEY = get_env('PARQUET_METADATA_KEY')

"""

ParauetUtils:
- write(file, df, meta={}, key=METADATA_KEY)
  for writing a df to a parquet
  optionally with meta
  may have it automatically include a "created" timestamp
  need to look into best way to encode/decode this meta (was using json)

- read(file, key=METADATA_KEY) -> df, meta
  - needs to be able to return a df, and the meta as a dict

- update(file, newmeta:dict)
  for updating the meta dict and rewriting it back to thr file

  
alright, so...the read/write methkds need to support sending 
a pydantic model as a variable. 
- for writing, it can support writing either an actual model
  instance, a dict[str, str], or plain str
- for reading, it would apply the provided model to decode/validate
  the meta (handles type conversions automatically)

- i need to figure ou if there is a way to save the model name in the
  meta, and then have it auto use it upon restoring

  use a registry
  see claude discussion on it
  it shows how to use a decorator to define the meta name/version, 
    which is then stored as name@version in a separate field

"""

#!================================================================================(80)
#! metadata utils
#!--------------------------------------------------------------------------------(80)
class FXTParquet(BaseModel):
    """ Wrapper for parquet files. It is assumed this file exists.
    """
    #NewPath if it's a path that doesn't exist
    #FilePath if it's a path that must exist
    #DirectoryPath if it needs to be a dir
    src:Path = Field(
        description="Path to the parquet file in question."
    )
    meta:str = Field(
        default=_METADATA_KEY
    )

    #~======================================================================(70)
    #~ validators
    #~----------------------------------------------------------------------(70)
    #keeping this one for ref for now
    @field_validator("src", mode="before")
    @classmethod
    def validate_src(cls, value: str) -> str:
        """
        """
        #return _lookup("symbol", value, cls.SYMBOL_MAP)
    #

    #~======================================================================(70)
    #~ misc
    #~----------------------------------------------------------------------(70)
    def exists(self):
        """ Returns True only if self.src is set, self.src exists, and self.src
            is a file.
        """
        return (self.src.exists() and self.src.is_file)
#



class MetadataUtils:
    """ A utility class for handling Parquet file metadata operations.
    """



