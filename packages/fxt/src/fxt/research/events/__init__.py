'''
fxt.research.events

Samplers (System 1's "when to look") and the builder that writes their
output to data/research/events. Events are side-agnostic; see
fxt.research.models.events.

    contract.py  core event columns, @register_sampler, check_detected
    cusum.py     detect_cusum (registered for CusumEventsConfig), event_stats
    build.py     build_events (reads the lake, writes research tables)
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from .build import EventsBuild, InputBarsError, build_events, event_ids, load_bars
from .contract import (
    CORE_COLUMNS, DETECT_CORE_SCHEMA, SAMPLERS, EventContractError, check_detected, get_sampler,
    register_sampler,
)
from .cusum import CUSUM_SCHEMA, detect_cusum, event_stats, prepare_bars

__all__ = [
    "EventsBuild", "InputBarsError", "build_events", "event_ids", "load_bars",
    "CORE_COLUMNS", "DETECT_CORE_SCHEMA", "SAMPLERS", "EventContractError", "check_detected",
    "get_sampler", "register_sampler",
    "CUSUM_SCHEMA", "detect_cusum", "event_stats", "prepare_bars",
]
