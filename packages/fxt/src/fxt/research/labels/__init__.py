'''
fxt.research.labels

Triple-barrier labeling (ML pipeline spec §6), in two steps:

    touch.py   step 1, side-agnostic: which barrier price hit first (compute_touches)
    side.py    step 2: side rule -> outcome, meta_label, path features (side_labels)
    build.py   build_touches (events + bars -> data/research/touches)
               build_labels  (touches + event directions -> data/research/labels)
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from .build import (
    InputEventsError, InputTouchesError, LabelsBuild, LakeTicks, TouchesBuild, build_labels, build_touches,
    check_labels, check_touches, label_stats, strategy_label, touch_stats,
)
from .side import LABEL_SCHEMA, OUTCOMES, side_labels
from .touch import TOUCH_SCHEMA, EventsBarsMismatch, MinuteBars, TickLookup, barrier_vol, compute_touches

__all__ = [
    "InputEventsError", "InputTouchesError", "LabelsBuild", "LakeTicks", "TouchesBuild", "build_labels",
    "build_touches", "check_labels", "check_touches", "label_stats", "strategy_label", "touch_stats",
    "LABEL_SCHEMA", "OUTCOMES", "side_labels",
    "TOUCH_SCHEMA", "EventsBarsMismatch", "MinuteBars", "TickLookup", "barrier_vol", "compute_touches",
]
