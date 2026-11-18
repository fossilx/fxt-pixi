'''
fxt.research.events

Samplers (System 1's "when to look") and the builder that writes their
output to data/research/events. Events are side-agnostic; see
fxt.research.models.events.

    cusum.py   detect_cusum, event_stats (pure)
    build.py   build_events (reads the lake, writes research tables)
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from .build import EVENT_COLUMNS, EventsBuild, InputBarsError, build_events, event_ids, load_bars
from .cusum import EVENT_SCHEMA, detect_cusum, event_stats, prepare_bars

__all__ = [
    "EVENT_COLUMNS", "EventsBuild", "InputBarsError", "build_events", "event_ids", "load_bars",
    "EVENT_SCHEMA", "detect_cusum", "event_stats", "prepare_bars",
]
