"""
For creating the core bars.

#~ paths





#~ basic todo....
- create 1min bars from tick data
- create 1hour and 1day bars from 1min data


#~ Each "bar" should contain:

```py
#* values based on bid prices
- bid_open
- bid_high
- bid_low
- bid_close
#* values based on ask prices
- ask_open
- ask_high
- ask_low
- ask_close
#* values based on mid prices (maybe)
- mid_open
- mid_high
- mid_low
- mid_close

#* and then...
bid_volume
ask_volume
tick_count
spread_mean
spread_max
```

Metadata fields for derived files:
- `derived_from:Path`
  the source file used to generate these 




"""
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
logger = create_logger("derived-bars")



