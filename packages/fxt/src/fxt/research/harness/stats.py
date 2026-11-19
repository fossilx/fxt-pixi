'''
stats

Probabilistic and deflated Sharpe ratios (Bailey & López de Prado, 2012 / 2014),
for ML pipeline spec §9.6. All Sharpe ratios here are per period (daily), not
annualized.

    psr(sr, n, skew, kurt, sr_ref=0)       P(true Sharpe > sr_ref) given n observations
    expected_max_sharpe(n_trials, var_sr)  the best Sharpe expected from n_trials skill-less trials
    deflated_sharpe(sr, n, skew, kurt, n_trials, var_sr)
                                           psr against that expected maximum

`kurt` is the ordinary (non-excess) kurtosis: 3 for a normal distribution.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

__all__ = ["DeflatedSharpe", "EULER_GAMMA", "deflated_sharpe", "expected_max_sharpe", "moments", "psr"]

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def moments(x: np.ndarray) -> tuple[float, float, float, int]:
    """ (sharpe, skew, kurtosis (non-excess), n) of a return series; population moments. """
    n = len(x)
    if n < 2:
        return math.nan, math.nan, math.nan, n
    m = x.mean()
    d = x - m
    m2 = (d ** 2).mean()
    if m2 <= 0:
        return math.nan, math.nan, math.nan, n
    sd = x.std(ddof=1)
    return float(m / sd), float((d ** 3).mean() / m2 ** 1.5), float((d ** 4).mean() / m2 ** 2), n


def psr(sr: float, n: int, skew: float, kurt: float, sr_ref: float = 0.0) -> float:
    """ Probabilistic Sharpe ratio: P(true SR > sr_ref), allowing for skew and fat tails. """
    if n < 2 or not all(math.isfinite(v) for v in (sr, skew, kurt, sr_ref)):
        return math.nan
    var = max(1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr, 1e-12)
    return _N.cdf((sr - sr_ref) * math.sqrt(n - 1) / math.sqrt(var))


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """ Expected maximum of n_trials Sharpe ratios with true value 0 and variance var_sr. """
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    g = EULER_GAMMA
    return math.sqrt(var_sr) * ((1 - g) * _N.inv_cdf(1 - 1 / n_trials) + g * _N.inv_cdf(1 - 1 / (n_trials * math.e)))


@dataclass(frozen=True)
class DeflatedSharpe:
    dsr: float                 # P(true SR > expected max of n_trials skill-less trials)
    psr: float                 # P(true SR > 0)
    sr0: float                 # the expected maximum (per period)
    n_trials: int
    var_sr: float              # variance of the trials' Sharpe ratios (0 if fewer than 2)
#


def deflated_sharpe(sr: float, n: int, skew: float, kurt: float, n_trials: int, trial_srs: list[float]) -> DeflatedSharpe:
    """ `trial_srs`: the per-period Sharpe of every finished trial, this one included. """
    vals = [v for v in trial_srs if math.isfinite(v)]
    var_sr = float(np.var(vals, ddof=1)) if len(vals) >= 2 else 0.0
    sr0 = expected_max_sharpe(n_trials, var_sr)
    return DeflatedSharpe(dsr=psr(sr, n, skew, kurt, sr0), psr=psr(sr, n, skew, kurt), sr0=sr0,
                          n_trials=n_trials, var_sr=var_sr)
#-
