'''
fxt.research.weights

Sample weights from label overlap (ML pipeline spec §7).

    uniqueness.py  business_coord, sweep, compute_weights (pure)
    build.py       build_weights (labels + 1HOUR clock -> data/research/weights)
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from .build import InputLabelsError, WeightsBuild, build_weights, check_weights, weight_stats
from .uniqueness import WEIGHT_SCHEMA, business_coord, compute_weights, sweep

__all__ = [
    "InputLabelsError", "WeightsBuild", "build_weights", "check_weights", "weight_stats",
    "WEIGHT_SCHEMA", "business_coord", "compute_weights", "sweep",
]
