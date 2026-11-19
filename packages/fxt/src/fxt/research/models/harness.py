'''
harness

Configs for the evaluation harness (ML pipeline spec §8–§9). They write no research
files; the harness records them in the registry (`configs` table) and each run lists
the hashes it used (`run_configs`).

    WalkForwardConfig     cv: lockbox, test years, purge/embargo, start-of-data drop
    BacktestConfig        backtest: costs (bid/ask, slippage, commission), position cap
    TakeAllModelConfig    model: no model; predicts the training base rate
    LogisticModelConfig   model: L2 logistic regression on standardized features (v2: side inputs)
    GBMModelConfig        model: LightGBM, fixed small trees, calibrated inside each fold
    GBMMulticlassModelConfig  model: LightGBM on pt / sl / timeout (open question 9)
    SizerConfig           sizer: take_all / threshold / linear / above_prior
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from ._registry import registry
from .config import HarnessConfig

__all__ = ["OUTCOME_CLASSES", "BacktestConfig", "GBMModelConfig", "GBMMulticlassModelConfig", "LogisticModelConfig", "LogisticModelConfigV1", "ModelConfig", "SizerConfig",
           "TakeAllModelConfig", "WalkForwardConfig"]


@registry.register("WalkForwardConfig", 1)
class WalkForwardConfig(HarnessConfig):
    """ Expanding-window walk-forward with yearly test blocks (spec §9.1).

        development  every year before `lockbox_year`
        folds        one per test year, first_test_year .. lockbox_year - 1; fold i trains
                     on events with t0 before the test year, minus purged ones
        purge        a training event is dropped if its life [life_start, life_end) on the
                     business clock overlaps the test block
        embargo      training events starting less than `embargo_hours` of business time
                     after the test block ends are dropped (no-op for pure walk-forward,
                     kept so a k-fold layout gets it for free)
        start drop   events within `drop_start_days` of the start of data are never used (they
                     depend on where the data starts, §5.1). "Start" = the first hourly bar, and
                     the first bar after any gap longer than `restart_gap_days` (data that
                     resumes after a long hole has the same warm-up problem)
        lockbox      a lockbox run is one fold: train on all development data, test on the
                     lockbox year (one look per strategy, enforced by the registry)
    """
    kind = "cv"

    scheme: Literal["walk_forward_purged"] = "walk_forward_purged"
    lockbox_year: int = 2024
    first_test_year: int = 2016
    embargo_hours: float = 48.0
    drop_start_days: float = 7.0
    restart_gap_days: float = 7.0

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.first_test_year >= self.lockbox_year:
            raise ValueError("first_test_year must be before lockbox_year")
        if self.embargo_hours < 0 or self.drop_start_days < 0:
            raise ValueError("embargo_hours and drop_start_days must be >= 0")
        if self.restart_gap_days <= 0:
            raise ValueError("restart_gap_days must be > 0")
        return self

    def test_years(self) -> tuple[int, ...]:
        return tuple(range(self.first_test_year, self.lockbox_year))
#


@registry.register("BacktestConfig", 1)
class BacktestConfig(HarnessConfig):
    """ Cost model (spec §9.2). Entry at t0, exit at t1, both on the traded side of the quote:
        a long buys the ask and sells the bid, a short the reverse.

        entry spread  the event bar's closing quote (ask_close - bid_close): the quote at t0
        exit spread   timeout exits (t1 on the hour) use the closing quote of the bar ending
                      at t1; barrier exits use the mean spread of the hourly bar containing t1
        slippage      `slippage_pips` per side, on top of the spread
        commission    `commission_bp` per round trip, in bp of notional

        net_ret = size * (side * ret_mid - cost), cost in log units:
            cost = half_spread_entry / price_t0 + half_spread_exit / price_exit
                   + 2 * slippage_pips * pip / price_t0 + commission_bp / 1e4

        position_cap  max total open size; a trade that would exceed it is cut to fit
                      (None = no cap, open question 4)
    """
    kind = "backtest"

    slippage_pips: float = 0.2
    commission_bp: float = 0.0
    pip_size: float | None = None              # None: 0.01 if the quote currency is JPY, else 0.0001
    position_cap: float | None = None
    annualization_days: float = 252.0          # Sharpe: daily P&L x sqrt(days)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.slippage_pips < 0 or self.commission_bp < 0:
            raise ValueError("costs must be >= 0")
        if self.position_cap is not None and self.position_cap <= 0:
            raise ValueError("position_cap must be > 0")
        return self

    def pip(self, symbol: str) -> float:
        if self.pip_size is not None:
            return self.pip_size
        return 0.01 if symbol.upper().endswith("JPY") else 0.0001
#


class ModelConfig(HarnessConfig):
    """ Unregistered base for meta-model configs. """
    kind = "model"
    sample_weight: Literal["weight", "weight_uniq", "none"] = "weight"   # weights column (§7)

    @property
    def label(self) -> str:
        raise NotImplementedError
#


@registry.register("TakeAllModelConfig", 1)
class TakeAllModelConfig(ModelConfig):
    """ No model: every event gets the (weighted) training base rate. The baseline. """

    @property
    def label(self) -> str:
        return "take_all"
#


@registry.register("LogisticModelConfig", 1)
class LogisticModelConfigV1(ModelConfig):
    """ v1, kept so recorded runs can be read back: no side inputs (signed features are fed
        as-is and `side` isn't an input, so the model can't learn direction). Use v2.
    """
    features: tuple[str, ...] = ()
    l2: float = Field(1e-2, ge=0)
    max_iter: int = Field(50, ge=1)
    tol: float = Field(1e-10, gt=0)

    @property
    def side_inputs(self) -> str:
        return "none"

    @property
    def label(self) -> str:
        return "logistic_v1"
#


@registry.register("LogisticModelConfig", 2)
class LogisticModelConfig(ModelConfig):
    """ L2-penalized logistic regression, fitted by Newton's method on features standardized
        with the training fold's (weighted) mean and std. Missing values -> the training mean.

        features     feature names to use; () = every feature of the dataset
        side_inputs  "aligned" (default): signed features enter as side x value, plus `side`
                     itself, so "price ran up before a long" and "price ran down before a
                     short" look the same to the model (meta-labels are side-adjusted).
                     "none": features as stored, no side (v1 behaviour)
        l2           penalty on the coefficients (not the intercept), in units of the
                     total sample weight: loss = mean weighted log loss + l2/2 * |beta|^2
    """
    features: tuple[str, ...] = ()
    side_inputs: Literal["aligned", "none"] = "aligned"
    l2: float = Field(1e-2, ge=0)
    max_iter: int = Field(50, ge=1)
    tol: float = Field(1e-10, gt=0)

    @property
    def label(self) -> str:
        return "logistic" if self.side_inputs == "aligned" else "logistic_noside"
#


@registry.register("GBMModelConfig", 1)
class GBMModelConfig(ModelConfig):
    """ Gradient-boosted trees (LightGBM, binary log loss), meta-model default (spec §8.1).

    Parameters are fixed, small and strongly regularized rather than tuned: with ~190
    independent samples per year, every tuning pass would be another trial (§9.6).
    Missing feature values are left to LightGBM (no imputation); no scaling needed.
    Training is deterministic (one thread, fixed seed).

        calibration     "platt" (default): logistic regression of the label on the raw
                        score's logit; "isotonic": weighted pool-adjacent-violators;
                        "none": raw probabilities
        calib_fraction  the latest share of each fold's training events (by t0) held out
                        to fit the calibrator. The trees are fitted on the rest, purged so
                        no fitted event's life reaches into the calibration window. The test
                        year is never used for either.
    """
    features: tuple[str, ...] = ()
    side_inputs: Literal["aligned", "none"] = "aligned"
    n_rounds: int = Field(200, ge=1)
    learning_rate: float = Field(0.03, gt=0, le=1)
    num_leaves: int = Field(7, ge=2)
    max_depth: int = Field(3, ge=1)
    min_data_in_leaf: int = Field(50, ge=1)
    feature_fraction: float = Field(0.8, gt=0, le=1)
    bagging_fraction: float = Field(0.8, gt=0, le=1)
    lambda_l2: float = Field(5.0, ge=0)
    seed: int = 42
    calibration: Literal["platt", "isotonic", "none"] = "platt"
    calib_fraction: float = Field(0.25, gt=0, lt=1)

    @property
    def label(self) -> str:
        return "gbm" if self.calibration == "platt" else f"gbm_{self.calibration}"
#


OUTCOME_CLASSES = ("sl", "timeout", "pt")                   # multiclass label order: 0, 1, 2


@registry.register("GBMMulticlassModelConfig", 1)
class GBMMulticlassModelConfig(ModelConfig):
    """ LightGBM on the three outcomes (stop-loss / timeout / profit-take), spec §8.1 and
        open question 9.

    The binary meta-label lumps stop-losses with timeouts, so a binary model can raise
    P(profit-take) just by predicting that *some* barrier gets hit. With the outcomes
    kept apart, P(pt) - P(sl) is a directional score: with symmetric barriers the
    expected gross return is about half_width x (P(pt) - P(sl)) plus the small timeout
    term, which is what the `expected_value` sizer uses.

    Same fixed tree parameters as GBMModelConfig (not tuned). The harness's classifier
    metrics use P(pt) as the probability of meta_label = 1, so they compare directly with
    the binary models; `dir_auc` scores P(pt) - P(sl) on profit-takes vs stop-losses.

        calibration     "platt" (default): one-vs-rest Platt per class on the calibration
                        window, then renormalized to sum to 1; "none": raw probabilities
        calib_fraction  as GBMModelConfig
    """
    features: tuple[str, ...] = ()
    side_inputs: Literal["aligned", "none"] = "aligned"
    n_rounds: int = Field(200, ge=1)
    learning_rate: float = Field(0.03, gt=0, le=1)
    num_leaves: int = Field(7, ge=2)
    max_depth: int = Field(3, ge=1)
    min_data_in_leaf: int = Field(50, ge=1)
    feature_fraction: float = Field(0.8, gt=0, le=1)
    bagging_fraction: float = Field(0.8, gt=0, le=1)
    lambda_l2: float = Field(5.0, ge=0)
    seed: int = 42
    calibration: Literal["platt", "none"] = "platt"
    calib_fraction: float = Field(0.25, gt=0, lt=1)

    @property
    def label(self) -> str:
        return "gbm3" if self.calibration == "platt" else f"gbm3_{self.calibration}"
#


@registry.register("SizerConfig", 1)
class SizerConfig(HarnessConfig):
    """ Probability -> position size in [0, cap] (spec §8.2).

        take_all     size = cap for every event
        threshold    size = cap if prob > threshold, else 0
        linear       size = clip((prob - threshold) / (1 - threshold), 0, 1) * cap
        expected_value  size = cap if half_width x (P(pt) - P(sl)) > cost: the trade's
                     expected gross return (symmetric barriers, timeout term ignored) beats
                     its cost. Needs a multiclass model; no free parameter
        above_prior  size = cap if prob > the base rate the probabilities are calibrated to
                     (the calibration window's for a calibrated model, else the training
                     set's), else 0: "better than an average event", no free parameter
                     (threshold ignored)
    """
    kind = "sizer"

    rule: Literal["take_all", "threshold", "linear", "above_prior", "expected_value"] = "take_all"
    threshold: float = Field(0.5, ge=0, lt=1)
    cap: float = Field(1.0, gt=0)

    @property
    def label(self) -> str:
        return self.rule if self.rule in ("take_all", "above_prior", "expected_value") \
            else f"{self.rule}{self.threshold:g}"
#-
