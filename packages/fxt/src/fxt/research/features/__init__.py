'''
fxt.research.features

Per-bar features in long format (ML pipeline spec §4), and the helpers that
turn them into a model's feature matrix.

    baseline.py  compute_features (pure): the first feature set
    build.py     build_features (bars -> data/research/features)
    matrix.py    load_features, to_wide, features_at (as-of join onto events at t0)
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from .baseline import BAR_COLUMNS, FEATURE_SCHEMA, compute_features
from .build import FeaturesBuild, build_features, check_features, feature_stats
from .matrix import features_at, load_features, to_wide

__all__ = [
    "BAR_COLUMNS", "FEATURE_SCHEMA", "compute_features",
    "FeaturesBuild", "build_features", "check_features", "feature_stats",
    "features_at", "load_features", "to_wide",
]
