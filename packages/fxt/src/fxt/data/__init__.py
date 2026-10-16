#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
import sys

#from .downloader import DukascopyDownloader  
#from .parquet import ParquetDownloader
#from .parquet import ParquetMetadataUtils

from ._registry import DataRegistry

#from .models import *

#to get them added to registry






#!================================================================================(80)
#! exports
#!--------------------------------------------------------------------------------(80)
__all__ = [
##    'ParquetDownloader',
#    'ParquetMetadataUtils',
    'DataRegistry',
    #'DukascopyDownloader',
    
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