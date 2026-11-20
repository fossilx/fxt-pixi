'''
fxt.research.features

Per-bar features in long format (ML pipeline spec §4), and the helpers that
turn them into a model's feature matrix.

    baseline.py  compute_features (pure): the baseline set; prepare, to_long helpers
    trend.py     compute_trend (pure): the directional set
    flow.py      compute_flow (pure): the order-flow set, from 1MIN bars
    cross.py     compute_cross (pure): the cross-pair set, from the basket's hourly bars
    build.py     build_features (bars -> data/research/features)
    matrix.py    load_features, to_wide, features_at (as-of join onto events at t0)
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from .baseline import BAR_COLUMNS, FEATURE_SCHEMA, compute_features, to_long
from .build import FEATURE_BUILDERS, FeaturesBuild, build_features, check_features, feature_stats
from .cross import CROSS_BAR_COLUMNS, compute_cross, pair_z
from .flow import FLOW_BAR_COLUMNS, compute_flow, hourly_flow
from .trend import TREND_BAR_COLUMNS, compute_trend
from .matrix import features_at, load_features, to_wide

__all__ = [
    "BAR_COLUMNS", "FEATURE_SCHEMA", "compute_features", "to_long",
    "TREND_BAR_COLUMNS", "compute_trend",
    "FLOW_BAR_COLUMNS", "compute_flow", "hourly_flow",
    "CROSS_BAR_COLUMNS", "compute_cross", "pair_z",
    "FEATURE_BUILDERS", "FeaturesBuild", "build_features", "check_features", "feature_stats",
    "features_at", "load_features", "to_wide",
]
