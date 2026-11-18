'''
harness

Configs for the evaluation harness (ML pipeline spec §8–§9). They write no research
files; the harness records them in the registry (`configs` table) and each run lists
the hashes it used (`run_configs`).

    WalkForwardConfig     cv: lockbox, test years, purge/embargo, start-of-data drop
    BacktestConfig        backtest: costs (bid/ask, slippage, commission), position cap
    TakeAllModelConfig    model: no model; predicts the training base rate
    LogisticModelConfig   model: L2 logistic regression on standardized features
    SizerConfig           sizer: take_all / threshold / linear
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

__all__ = ["BacktestConfig", "LogisticModelConfig", "ModelConfig", "SizerConfig", "TakeAllModelConfig",
           "WalkForwardConfig"]


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
class LogisticModelConfig(ModelConfig):
    """ L2-penalized logistic regression, fitted by Newton's method on features standardized
        with the training fold's (weighted) mean and std. Missing values -> the training mean.

        features  feature names to use; () = every feature of the features config
        l2        penalty on the coefficients (not the intercept), in units of the
                  total sample weight: loss = mean weighted log loss + l2/2 * |beta|^2
    """
    features: tuple[str, ...] = ()
    l2: float = Field(1e-2, ge=0)
    max_iter: int = Field(50, ge=1)
    tol: float = Field(1e-10, gt=0)

    @property
    def label(self) -> str:
        return "logistic"
#


@registry.register("SizerConfig", 1)
class SizerConfig(HarnessConfig):
    """ Probability -> position size in [0, cap] (spec §8.2).

        take_all   size = cap for every event
        threshold  size = cap if prob > threshold, else 0
        linear     size = clip((prob - threshold) / (1 - threshold), 0, 1) * cap
    """
    kind = "sizer"

    rule: Literal["take_all", "threshold", "linear"] = "take_all"
    threshold: float = Field(0.5, ge=0, lt=1)
    cap: float = Field(1.0, gt=0)

    @property
    def label(self) -> str:
        return self.rule if self.rule == "take_all" else f"{self.rule}{self.threshold:g}"
#-
