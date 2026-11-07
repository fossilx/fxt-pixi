#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations
from typing import Any

import polars as pl

#fxt
from fxt.data.models import DownloadedDataMeta

#local
from .base import BaseIntervalSchema


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
import logging
logger = logging.getLogger(__name__)


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class Bars(BaseIntervalSchema):
    """ Before I can fully implement the Bars downloader, I need to have it make 
        multiple requests for each time period because it needs to request the bid 
        and ask values separately.

        Then calculate the mid values manually. Have to figure out how I want to 
        handle that.
    """
    @classmethod
    def schema(cls) -> pl.Schema:
        """
        """
        return pl.Schema({
            #! index must be first
            cls.INDEX: cls.DTIME_TYPE,

            #! rest
            'start': cls.DTIME_TYPE,
            'end': cls.DTIME_TYPE,

            #from bid prices
            'bidOpen': pl.Float64,
            'bidHigh': pl.Float64,
            'bidLow': pl.Float64,
            'bidClose': pl.Float64,

            #from ask prices
            'askOpen': pl.Float64,
            'askHigh': pl.Float64,
            'askLow': pl.Float64,
            'askClose': pl.Float64,
            
            #mid-values are from (bid+ask)/2
            'midOpen': pl.Float64,
            'midHigh': pl.Float64,
            'midLow': pl.Float64,
            'midClose': pl.Float64,

            #dukascopy-python only provides a single `volume` field
            'volume': pl.Float64,
            #'bidVolume': pl.Float64,
            #'askVolume'


            #--------------------: pl.Float64,
            'tickCount': pl.UInt64,
            'spread_mean': pl.Float64,
            'spread_max': pl.Float64
        })
    #
    
    @classmethod
    def meta(cls, *args:Any, **kwargs:Any) ->  DownloadedDataMeta:
        """ 
        """
        return super().meta(*args, **kwargs)
    #
#-




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80) 
if __name__ == '__main__':

    from rich import print

    data_types = [Bars]

    for d in data_types:
        print(f"\n* [bold]schema type: [green]{d.name()}[/]")
        print(f"- index: {d.index()}")
        print(f"- cols: {d.cols()}")

