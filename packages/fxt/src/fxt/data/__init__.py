#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
#import registries so they are always available when fxt.data is used
from .downloaders import DownloaderRegistry
from .models import ModelRegistry
from .sources import SourceRegistry


#!================================================================================(80)
#! ENV FILE SUPPORT
#!--------------------------------------------------------------------------------(80)
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class _DATAENV(BaseSettings):
    """ Load settings/secrets from the sibling .env file.

        aka the .env file must be in the same dir as this file
    """
    model_config = SettingsConfigDict(
        #env_file=PATHS.ROOT / ".env",
        extra="ignore",
        env_file_encoding="utf-8",
        env_file=Path(__file__).parent / ".env"
    )

    # #bring in specific keys from .env file
    #DOWNLOADER_MANIFEST:str
    #DOWNLOADER_MAX_RETRIES:int

    PARQUET_STORE_METADATA_NAMESPACE:str

    # TELEGRAM_TOKEN: SecretStr|None = None
    # TELEGRAM_USERID: int|None = None
    # GOD: str|None = None
    
    # #no defaults to ensure that values are specified in the env
    # PARQUET_METADATA_JSON_KEY:str
    # PARQUET_METADATA_TYPE_KEY:str
    
    # DOWNLOADER_MANIFEST:str
    # DOWNLOADER_MAX_RETRIES:int
#
DATAENV = _DATAENV() # type: ignore[call-arg]

from typing import Any

def get_dataenv(key:str, default:Any|None = None) -> Any:
    """ Within the data submodule...
    
        If no key is provided, returns entire env
    """
    #if(key is None):
    #    return DATAENV.model_dump()
    #else:
    return getattr(DATAENV, key, default)
#


#!================================================================================(80)
#! exports
#!--------------------------------------------------------------------------------(80)
# import re
# def _safe(text):
#     """ Returns a version of the provided string 
#     """
#     text = text.replace("/", "")
#     text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")

#     #print(f"text: {text}, safe: {name}")
#     #sys.exit()
#     return text
# #






#!================================================================================(80)
#! exports
#!--------------------------------------------------------------------------------(80)
__all__ = [
    'DownloaderRegistry',
    'ModelRegistry',
    'SourceRegistry'    
]




#!================================================================================(80)
#! kept even though not used, maybe for future use
#!--------------------------------------------------------------------------------(80)
import struct
import lzma

def decode_bi5_file(binary_content):
    """ Decodes a Dukascopy .bi5 file and returns a list of ticks.

        Note: not tested
    """

    # Decompress the raw LZMA payload
    decompressed_data = lzma.decompress(binary_content)
    
    # Each tick is exactly 20 bytes: 
    # - Time offset (4-byte int)
    # - Ask Price (4-byte int)
    # - Bid Price (4-byte int)
    # - Ask Volume (4-byte float)
    # - Bid Volume (4-byte float)
    # The '>' denotes big-endian format, which Dukascopy uses.
    tick_struct = struct.Struct('>IIIff')
    
    ticks = []
    for i in range(0, len(decompressed_data), 20):
        chunk = decompressed_data[i:i+20]
        time_offset, ask, bid, ask_vol, bid_vol = tick_struct.unpack(chunk)
        
        # Real prices are typically multiplied by 100,000 in the binary file
        ticks.append({
            'time_offset_ms': time_offset,
            'ask': ask / 100000.0,
            'bid': bid / 100000.0,
            'ask_volume': ask_vol,
            'bid_volume': bid_vol
        })
    return ticks
#