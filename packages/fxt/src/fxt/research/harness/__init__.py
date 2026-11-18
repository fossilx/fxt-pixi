'''
fxt.research.harness

The evaluation harness (ML pipeline spec §9): dataset assembly, purged walk-forward
folds, meta-models, sizing, the cost-aware backtest, metrics, and evaluate(), which
records every run in the experiment registry.
'''
from .backtest import MissingQuoteError, apply_sizer, simulate, trade_costs
from .dataset import Dataset, InputDatasetError, load_dataset
from .evaluate import PREDICTION_COLUMNS, EvalResult, evaluate
from .folds import Fold, data_starts, make_folds, usable_mask
from .metrics import auc, classifier_metrics, daily_pnl, trading_metrics
from .models import ConvergenceError, fit_logistic, fit_predict, sigmoid

__all__ = [
    "MissingQuoteError", "apply_sizer", "simulate", "trade_costs",
    "Dataset", "InputDatasetError", "load_dataset",
    "PREDICTION_COLUMNS", "EvalResult", "evaluate",
    "Fold", "data_starts", "make_folds", "usable_mask",
    "auc", "classifier_metrics", "daily_pnl", "trading_metrics",
    "ConvergenceError", "fit_logistic", "fit_predict", "sigmoid",
]
