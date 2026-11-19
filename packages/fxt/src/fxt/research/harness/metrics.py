'''
metrics

Classifier and trading metrics for the harness (ML pipeline spec §9.3). Pure numpy/polars.

    classifier_metrics(y, prob, prior, w)   log loss (+ vs the training base rate), Brier, AUC, ECE;
                                            weighted like the model's training
    trading_metrics(trades, start, end, cfg)
                                            per-trade bp, hit rate, Sharpe on daily P&L, drawdown,
                                            t-stat with the effective sample size (sum of uniqueness)

All bp figures are per unit of size (sum / total size), so a sizer that halves every
position leaves them unchanged; totals (net_bp_total, max_dd_bp) scale with size.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import numpy as np
import polars as pl

from fxt.research.models import BacktestConfig

from .stats import moments

__all__ = ["auc", "classifier_metrics", "daily_pnl", "trading_metrics"]

EPS = 1e-15


def _log_loss(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    p = np.clip(p, EPS, 1 - EPS)
    return float(-(w * (y * np.log(p) + (1 - y) * np.log(1 - p))).sum() / w.sum())


def auc(y: np.ndarray, p: np.ndarray, w: np.ndarray | None = None) -> float:
    """ (Weighted) ROC AUC: P(score of a random positive > a random negative), ties count
        half, pairs weighted by w_i * w_j. Constant p -> 0.5.
    """
    w = np.ones(len(y)) if w is None else w
    g = (pl.DataFrame({"p": p, "w1": w * (y == 1), "w0": w * (y == 0)})
         .group_by("p").agg(pl.col("w1").sum(), pl.col("w0").sum()).sort("p"))
    w1, w0 = g.get_column("w1").to_numpy(), g.get_column("w0").to_numpy()
    W1, W0 = w1.sum(), w0.sum()
    if W1 == 0 or W0 == 0:
        return math.nan
    below = np.cumsum(w0) - w0
    return float((w1 * (below + 0.5 * w0)).sum() / (W1 * W0))


def classifier_metrics(y: np.ndarray, p: np.ndarray, prior: float, w: np.ndarray | None = None,
                       bins: int = 10) -> dict[str, float]:
    """ Metrics weighted by `w` (the weights the model was trained with, so a weighted model
        is scored on the objective it fitted); `prior` = the training (weighted) base rate.
    """
    y = y.astype(float)
    if len(y) == 0:
        return {"n": 0.0}
    w = np.ones(len(y)) if w is None else w.astype(float)
    W = w.sum()
    ll = _log_loss(y, p, w)
    ll0 = _log_loss(y, np.full(len(y), prior), w)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if w[m].sum() > 0:
            ece += abs(np.average(y[m], weights=w[m]) - np.average(p[m], weights=w[m])) * w[m].sum() / W
    return {
        "n": float(len(y)),
        "base_rate": float((w * y).sum() / W),
        "mean_prob": float((w * p).sum() / W),
        "log_loss": ll,
        "log_loss_prior": ll0,
        "log_loss_skill": 1 - ll / ll0 if ll0 > 0 else math.nan,
        "brier": float((w * (p - y) ** 2).sum() / W),
        "auc": auc(y, p, w),
        "auc_unweighted": auc(y, p),
        "ece": float(ece),
    }


def _trading_day(d: date) -> date:
    """ Weekend exits (Sunday evening open, rare Saturday) count on the next Monday. """
    wd = d.weekday()
    return d + timedelta(days=7 - wd) if wd >= 5 else d


def daily_pnl(trades: pl.DataFrame, start: datetime, end: datetime) -> np.ndarray:
    """ Realized net P&L per weekday in [start, end] (zero days included), booked at t1's date. """
    days = [start.date() + timedelta(days=i) for i in range((end.date() - start.date()).days + 1)]
    days = [d for d in days if d.weekday() < 5]
    index = {d: i for i, d in enumerate(days)}
    pnl = np.zeros(len(days))
    for t1, net in zip(trades.get_column("t1").to_list(), trades.get_column("net").to_list(), strict=True):
        i = index.get(_trading_day(t1.date()))
        if i is None:                           # exit after the period (last days of the test block)
            i = len(days) - 1
        pnl[i] += net
    return pnl


def trading_metrics(trades: pl.DataFrame, start: datetime, end: datetime, cfg: BacktestConfig) -> dict[str, float]:
    """ `trades`: simulate() output; rows with size 0 are ignored. """
    t = trades.filter(pl.col("size") > 0)
    n = t.height
    out: dict[str, float] = {"n_trades": float(n)}
    if n == 0:
        return out
    size = t.get_column("size").to_numpy()
    gross = t.get_column("gross").to_numpy()
    net = t.get_column("net").to_numpy()
    unit_net = net / size
    total = size.sum()
    wins, losses = unit_net[unit_net > 0], unit_net[unit_net <= 0]
    pnl = daily_pnl(t, start, end)
    sd = pnl.std(ddof=1) if len(pnl) > 1 else 0.0
    curve = np.cumsum(pnl)
    n_eff = float(t.get_column("uniqueness").sum())
    sd_trade = unit_net.std(ddof=1) if n > 1 else 0.0
    out.update({
        "turnover": float(total),
        "gross_bp": 1e4 * float(gross.sum() / total),
        "cost_bp": 1e4 * float((t.get_column("cost").to_numpy() * size).sum() / total),
        "net_bp": 1e4 * float(net.sum() / total),
        "net_bp_total": 1e4 * float(net.sum()),
        "hit_rate": float((unit_net > 0).mean()),
        "avg_win_bp": 1e4 * float(wins.mean()) if len(wins) else math.nan,
        "avg_loss_bp": 1e4 * float(losses.mean()) if len(losses) else math.nan,
        "avg_hold_hours": float(t.get_column("hours_to_exit").mean()),      # type: ignore[arg-type]
        "sharpe_ann": float(pnl.mean() / sd * math.sqrt(cfg.annualization_days)) if sd > 0 else math.nan,
        "max_dd_bp": 1e4 * float((np.maximum.accumulate(np.concatenate([[0.0], curve]))[1:] - curve).max()),
        "n_days": float(len(pnl)),
        "sharpe_daily": moments(pnl)[0],
        "skew_daily": moments(pnl)[1],
        "kurt_daily": moments(pnl)[2],
        "n_eff": n_eff,
        "t_eff": float(unit_net.mean() / (sd_trade / math.sqrt(n_eff))) if sd_trade > 0 and n_eff > 0 else math.nan,
    })
    return out
#-
