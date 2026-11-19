'''
models

Meta-model fit/predict for the harness. Pure numpy; deterministic.

    X, cols = model_inputs(frame, names, signed, side_inputs)   # the model's input matrix
    p_test = fit_predict(cfg, X_train, y_train, w_train, X_test)
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import numpy as np
import polars as pl

from fxt.research.models import LogisticModelConfig, LogisticModelConfigV1, ModelConfig, TakeAllModelConfig

__all__ = ["ConvergenceError", "fit_logistic", "fit_predict", "model_inputs", "sigmoid"]


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
    if isinstance(cfg, LogisticModelConfig | LogisticModelConfigV1):
        Ztr, Zte = _standardize(X_train, w_train, X_test)
        beta = fit_logistic(Ztr, y, w_train, l2=cfg.l2, max_iter=cfg.max_iter, tol=cfg.tol)
        return sigmoid(Zte @ beta)
    raise TypeError(f"no fit_predict for {type(cfg).__name__}")
#-
