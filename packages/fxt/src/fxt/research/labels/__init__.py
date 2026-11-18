'''
fxt.research.labels

Triple-barrier labeling (ML pipeline spec §6), in two steps:

    touch.py   step 1, side-agnostic: which barrier price hit first (compute_touches)
    build.py   reads events + bars, writes data/research/touches (build_touches)

Step 2 (side labels: side rule + outcome + meta_label) builds on the touches table.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from .build import InputEventsError, LakeTicks, TouchesBuild, build_touches, check_touches, touch_stats
from .touch import TOUCH_SCHEMA, EventsBarsMismatch, MinuteBars, TickLookup, barrier_vol, compute_touches

__all__ = [
    "InputEventsError", "LakeTicks", "TouchesBuild", "build_touches", "check_touches", "touch_stats",
    "TOUCH_SCHEMA", "EventsBarsMismatch", "MinuteBars", "TickLookup", "barrier_vol", "compute_touches",
]
