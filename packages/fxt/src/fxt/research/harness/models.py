'''
models

Meta-model fit/predict for the harness: take_all, logistic regression (numpy),
LightGBM, and in-fold probability calibration (Platt, isotonic). Deterministic.

    X, cols = model_inputs(frame, names, signed, side_inputs)   # the model's input matrix
    p_test = fit_predict(cfg, X_train, y_train, w_train, X_test)
    p_test, info = fold_predict(cfg, X_tr, y_tr, w_tr, t0_tr, ls_tr, le_tr, X_te)   # + calibration
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import numpy as np
import polars as pl

from fxt.research.models import (
    GBMModelConfig, LogisticModelConfig, LogisticModelConfigV1, ModelConfig, TakeAllModelConfig,
)

__all__ = ["CALIB_EPS", "ConvergenceError", "Calibrator", "fit_calibrator", "fit_gbm", "fit_logistic",
           "fit_predict", "fold_predict", "isotonic_fit", "model_inputs", "sigmoid"]

CALIB_EPS = 1e-3                                   # calibrated probabilities stay in [eps, 1 - eps]


def model_inputs(frame: pl.DataFrame, names: list[str], signed: tuple[str, ...] | list[str],
                 side_inputs: str) -> tuple[np.ndarray, list[str]]:
    """ The model's input matrix and column names.

        side_inputs="aligned": every signed feature enters as side x value (named
        "<name>*side"), unsigned ones as stored, plus a `side` column. Meta-labels are
        side-adjusted, so aligning makes "ran up before a long" and "ran down before a
        short" the same input. "none": features as stored, no side.
    """
    if side_inputs == "none":
        cols = list(names)
        exprs = [pl.col(n) for n in names]
    elif side_inputs == "aligned":
        sset = set(signed)
        cols = [f"{n}*side" if n in sset else n for n in names] + ["side"]
        exprs = [(pl.col(n) * pl.col("side")).alias(f"{n}*side") if n in sset else pl.col(n) for n in names]
        exprs.append(pl.col("side").cast(pl.Float64))
    else:
        raise ValueError(f"unknown side_inputs {side_inputs!r}")
    if not exprs:
        return np.zeros((frame.height, 0)), []
    return frame.select(exprs).to_numpy().astype(float), cols


class ConvergenceError(RuntimeError):
    """ The model didn't converge within max_iter. """


def sigmoid(z: np.ndarray) -> np.ndarray:
    return np.exp(-np.logaddexp(0.0, -z))


def _loss(X, y, w, beta, l2) -> float:
    z = X @ beta
    ll = np.logaddexp(0.0, z) - y * z                    # -log p(y | x), stable
    return float((w * ll).sum() / w.sum() + 0.5 * l2 * (beta[1:] ** 2).sum())


def fit_logistic(X: np.ndarray, y: np.ndarray, w: np.ndarray, *, l2: float, max_iter: int,
                 tol: float) -> np.ndarray:
    """ Coefficients (intercept first) minimizing weighted mean log loss + l2/2 |beta[1:]|^2.
        X must already include the intercept column. Newton with step halving.
    """
    k = X.shape[1]
    W = w.sum()
    pen = np.full(k, l2)
    pen[0] = 0.0
    beta = np.zeros(k)
    ybar = float((w * y).sum() / W)
    if 0 < ybar < 1:
        beta[0] = np.log(ybar / (1 - ybar))
    loss = _loss(X, y, w, beta, l2)
    for _ in range(max_iter):
        p = sigmoid(X @ beta)
        grad = X.T @ (w * (p - y)) / W + pen * beta
        if np.abs(grad).max() < tol:
            return beta
        H = (X * (w * p * (1 - p))[:, None]).T @ X / W + np.diag(pen)
        step = np.linalg.solve(H + 1e-12 * np.eye(k), grad)
        t = 1.0
        while True:
            cand = beta - t * step
            new = _loss(X, y, w, cand, l2)
            if new <= loss + 1e-15 or t < 1e-8:
                break
            t /= 2
        beta, loss = cand, new
    p = sigmoid(X @ beta)
    grad = X.T @ (w * (p - y)) / W + pen * beta
    if np.abs(grad).max() < max(tol, 1e-7):
        return beta
    raise ConvergenceError(f"logistic regression: |grad| {np.abs(grad).max():.2e} after {max_iter} iterations")


def _standardize(X_train: np.ndarray, w: np.ndarray, X_test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ok = ~np.isnan(X_train)
    ww = w[:, None] * ok
    denom = np.maximum(ww.sum(0), 1e-300)
    mu = np.where(ok, X_train, 0.0).T @ w / denom
    var = (np.where(ok, (X_train - mu) ** 2, 0.0) * w[:, None]).sum(0) / denom
    sd = np.sqrt(var)
    sd[~(sd > 0)] = 1.0
    def tf(X):
        Z = (X - mu) / sd
        Z[np.isnan(Z)] = 0.0                              # missing -> training mean
        return np.column_stack([np.ones(len(Z)), Z])
    return tf(X_train), tf(X_test)


def fit_predict(cfg: ModelConfig, X_train: np.ndarray, y_train: np.ndarray, w_train: np.ndarray,
                X_test: np.ndarray) -> np.ndarray:
    """ Out-of-sample probabilities for X_test. """
    y = y_train.astype(float)
    if isinstance(cfg, TakeAllModelConfig):
        return np.full(len(X_test), float((w_train * y).sum() / w_train.sum()))
    if isinstance(cfg, GBMModelConfig):
        return fit_gbm(cfg, X_train, y, w_train)(X_test)
    if isinstance(cfg, LogisticModelConfig | LogisticModelConfigV1):
        Ztr, Zte = _standardize(X_train, w_train, X_test)
        beta = fit_logistic(Ztr, y, w_train, l2=cfg.l2, max_iter=cfg.max_iter, tol=cfg.tol)
        return sigmoid(Zte @ beta)
    raise TypeError(f"no fit_predict for {type(cfg).__name__}")


#!================================================================================(80)
#! LightGBM
#!--------------------------------------------------------------------------------(80)
def fit_gbm(cfg: GBMModelConfig, X: np.ndarray, y: np.ndarray, w: np.ndarray):
    """ A predict function (X -> probability) from a LightGBM binary model. """
    import lightgbm as lgb                                         # lazy: heavy import
    params = {
        "objective": "binary", "learning_rate": cfg.learning_rate, "num_leaves": cfg.num_leaves,
        "max_depth": cfg.max_depth, "min_data_in_leaf": cfg.min_data_in_leaf,
        "feature_fraction": cfg.feature_fraction, "bagging_fraction": cfg.bagging_fraction,
        "bagging_freq": 1 if cfg.bagging_fraction < 1 else 0, "lambda_l2": cfg.lambda_l2,
        "seed": cfg.seed, "deterministic": True, "force_row_wise": True, "num_threads": 1, "verbose": -1,
    }
    booster = lgb.train(params, lgb.Dataset(X, label=y, weight=w, free_raw_data=True),
                        num_boost_round=cfg.n_rounds)
    return lambda Z: booster.predict(Z)


#!================================================================================(80)
#! calibration
#!--------------------------------------------------------------------------------(80)
def isotonic_fit(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """ Weighted pool-adjacent-violators: (block mean x, block value), both increasing. """
    o = np.argsort(x, kind="stable")
    xs, ys, ws = x[o], y[o].astype(float), w[o].astype(float)
    vals, wts, xsum = [], [], []
    for xi, yi, wi in zip(xs, ys, ws, strict=True):
        vals.append(yi)
        wts.append(wi)
        xsum.append(xi * wi)
        while len(vals) > 1 and vals[-2] >= vals[-1]:
            v2, w2, x2 = vals.pop(), wts.pop(), xsum.pop()
            v1, w1, x1 = vals.pop(), wts.pop(), xsum.pop()
            wt = w1 + w2
            vals.append((v1 * w1 + v2 * w2) / wt if wt > 0 else (v1 + v2) / 2)
            wts.append(wt)
            xsum.append(x1 + x2)
    wts_a = np.maximum(np.array(wts), 1e-300)
    return np.array(xsum) / wts_a, np.array(vals)


class Calibrator:
    """ Raw probability -> calibrated probability, clipped to [CALIB_EPS, 1 - CALIB_EPS]. """

    def __init__(self, method: str, params: tuple):
        self.method, self.params = method, params

    def __call__(self, p: np.ndarray) -> np.ndarray:
        if self.method == "platt":
            a, b = self.params
            out = sigmoid(a + b * _logit(p))
        elif self.method == "isotonic":
            bx, by = self.params
            out = np.interp(p, bx, by) if len(bx) > 1 else np.full(len(p), by[0] if len(by) else 0.5)
        else:
            out = p
        return np.clip(out, CALIB_EPS, 1 - CALIB_EPS)
#


def _logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(q / (1 - q))


def fit_calibrator(method: str, p: np.ndarray, y: np.ndarray, w: np.ndarray) -> Calibrator:
    if method == "platt":
        X = np.column_stack([np.ones(len(p)), _logit(p)])
        a, b = fit_logistic(X, y.astype(float), w, l2=0.0, max_iter=100, tol=1e-10)
        return Calibrator("platt", (float(a), float(b)))
    if method == "isotonic":
        return Calibrator("isotonic", isotonic_fit(p, y, w))
    return Calibrator("none", ())


def fold_predict(cfg: ModelConfig, X: np.ndarray, y: np.ndarray, w: np.ndarray, t0: np.ndarray,
                 life_start: np.ndarray, life_end: np.ndarray, X_test: np.ndarray) -> tuple[np.ndarray, dict]:
    """ Fit on one fold's training rows and predict its test rows, with calibration if the
        model config asks for it (`calibration`, `calib_fraction`).

        Calibration split: the latest calib_fraction of training events by t0 fit the
        calibrator; the model is fitted on the earlier events whose lives end before the
        first calibration event starts (purged on the business clock, like the folds).

        info["sizing_prior"]: the base rate the probabilities are calibrated to (the
        calibration window's, else the whole training set's), for the above_prior sizer.
    """
    method = getattr(cfg, "calibration", "none")
    if method == "none":
        return fit_predict(cfg, X, y, w, X_test), {"n_fit": len(y), "n_calib": 0, "calib_purged": 0,
                                                   "sizing_prior": float((w * y).sum() / w.sum())}
    order = np.argsort(t0, kind="stable")
    n_calib = max(1, round(len(y) * cfg.calib_fraction))              # type: ignore[attr-defined]
    calib = order[len(y) - n_calib:]
    start = life_start[calib].min()
    early = order[: len(y) - n_calib]
    fit = early[life_end[early] <= start]
    if len(fit) == 0 or len(np.unique(y[calib])) < 2:
        raise ValueError(f"calibration split left {len(fit)} fit events / {len(calib)} calibration events "
                         f"with {len(np.unique(y[calib]))} class(es)")
    if isinstance(cfg, GBMModelConfig):
        predict = fit_gbm(cfg, X[fit], y[fit].astype(float), w[fit])
    else:
        raise TypeError(f"calibration isn't supported for {type(cfg).__name__}")
    cal = fit_calibrator(method, predict(X[calib]), y[calib], w[calib])
    wc, yc = w[calib], y[calib].astype(float)
    return cal(predict(X_test)), {"n_fit": len(fit), "n_calib": len(calib),
                                  "calib_purged": len(early) - len(fit),
                                  "sizing_prior": float((wc * yc).sum() / wc.sum())}
#-
