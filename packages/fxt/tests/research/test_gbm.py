"""
LightGBM meta-model, in-fold calibration, the above_prior sizer (spec §8).
"""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from fxt.research.harness import (
    CALIB_EPS, MulticlassCalibrator, apply_sizer, evaluate, fit_calibrator, fit_gbm, fit_gbm_multiclass,
    fold_predict, isotonic_fit,
)
from fxt.research.models import (
    OUTCOME_CLASSES, GBMModelConfig, GBMMulticlassModelConfig, LogisticModelConfig, SizerConfig, registry,
)

from .test_harness import CV, synth_dataset


#!================================================================================(80)
#! calibration
#!--------------------------------------------------------------------------------(80)
def brute_isotonic(x, y, w):
    """ Weighted isotonic regression by repeatedly pooling any decreasing pair (slow, obvious). """
    o = np.argsort(x, kind="stable")
    blocks = [[float(y[i]) * w[i], w[i], float(x[i]) * w[i]] for i in o]
    changed = True
    while changed:
        changed = False
        for i in range(len(blocks) - 1):
            a, b = blocks[i], blocks[i + 1]
            if a[0] / a[1] >= b[0] / b[1]:
                blocks[i:i + 2] = [[a[0] + b[0], a[1] + b[1], a[2] + b[2]]]
                changed = True
                break
    return np.array([b[2] / b[1] for b in blocks]), np.array([b[0] / b[1] for b in blocks])


def test_isotonic_matches_brute_force():
    rng = np.random.default_rng(0)
    x = rng.random(80)
    y = (rng.random(80) < x).astype(float)
    w = rng.random(80) + 0.2
    bx, by = isotonic_fit(x, y, w)
    ex, ey = brute_isotonic(x, y, w)
    assert np.allclose(bx, ex) and np.allclose(by, ey)
    assert (np.diff(by) > 0).all() and (np.diff(bx) > 0).all()


def test_platt_recovers_a_known_distortion():
    rng = np.random.default_rng(1)
    true = rng.uniform(0.05, 0.95, 20_000)
    y = (rng.random(20_000) < true).astype(float)
    raw = 1 / (1 + np.exp(-(0.5 + 2 * np.log(true / (1 - true)))))          # over-confident, shifted
    cal = fit_calibrator("platt", raw, y, np.ones(len(y)))
    assert np.abs(cal(raw) - true).mean() < 0.01
    out = fit_calibrator("isotonic", raw, y, np.ones(len(y)))(np.array([0.0, 1.0]))
    assert out.min() >= CALIB_EPS and out.max() <= 1 - CALIB_EPS


def test_calibration_split_is_purged_and_in_the_past():
    ds = synth_dataset()
    f = ds.frame
    X = f.select("x", "noise").to_numpy()
    y, w = f["meta_label"].to_numpy(), np.ones(f.height)
    t0 = f["t0"].dt.epoch("s").to_numpy()
    ls, le = f["life_start"].to_numpy(), f["life_end"].to_numpy()
    _, info = fold_predict(GBMModelConfig(n_rounds=20), X, y, w, t0, ls, le, X[:5])
    n = f.height
    assert info["n_calib"] == round(n * 0.25)
    assert info["n_fit"] + info["n_calib"] + info["calib_purged"] == n
    #! the fit events are exactly the early ones whose life ends before the calibration window starts
    order = np.argsort(t0, kind="stable")
    calib = order[n - info["n_calib"]:]
    start = ls[calib].min()
    early = order[: n - info["n_calib"]]
    assert info["n_fit"] == int((le[early] <= start).sum()) and info["calib_purged"] > 0
    cw = w[calib]
    assert info["sizing_prior"] == pytest.approx((cw * y[calib]).sum() / cw.sum())


#!================================================================================(80)
#! LightGBM
#!--------------------------------------------------------------------------------(80)
def test_gbm_is_deterministic_and_learns():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(3000, 4))
    X[::9, 1] = np.nan                                               # missing values are fine
    y = ((X[:, 0] > 0.3) ^ (X[:, 2] > 0)).astype(float)               # an interaction a linear model can't fit
    cfg = GBMModelConfig(min_data_in_leaf=20)
    p1 = fit_gbm(cfg, X[:2000], y[:2000], np.ones(2000))(X[2000:])
    p2 = fit_gbm(cfg, X[:2000], y[:2000], np.ones(2000))(X[2000:])
    assert np.array_equal(p1, p2)
    from fxt.research.harness import auc
    assert auc(y[2000:], p1) > 0.9


def test_gbm_config():
    assert GBMModelConfig().label == "gbm" and GBMModelConfig(calibration="isotonic").label == "gbm_isotonic"
    assert GBMModelConfig().config_hash() == "453feb24fb0f"
    assert registry.get_model("GBMModelConfig@1") is GBMModelConfig


#!================================================================================(80)
#! sizing + end to end
#!--------------------------------------------------------------------------------(80)
def test_above_prior_sizer():
    p = np.array([0.3, 0.41, 0.42, 0.6])
    assert apply_sizer(p, SizerConfig(rule="above_prior"), 0.41).tolist() == [0, 0, 1, 1]
    with pytest.raises(ValueError):
        apply_sizer(p, SizerConfig(rule="above_prior"))
    assert SizerConfig(rule="above_prior").label == "above_prior"
    assert SizerConfig().config_hash() == "66cedc144eff"                # adding a rule didn't move the default


@pytest.mark.parametrize("calibration", ["platt", "isotonic", "none"])
def test_evaluate_gbm(calibration):
    ds = synth_dataset()
    res = evaluate(ds, model=GBMModelConfig(calibration=calibration, min_data_in_leaf=20),
                   sizer=SizerConfig(rule="above_prior"), cv=CV, registry=None)
    a = res.aggregate
    assert a["clf_auc"] > 0.75 and a["clf_log_loss_skill"] > 0.05
    assert 0 < a["n_trades"] < res.trades.height
    for row in res.folds.iter_rows(named=True):
        assert row["n_fit"] + row["n_calib"] + row["calib_purged"] == row["n_train"]
        assert (row["n_calib"] > 0) == (calibration != "none")
    assert res.trades["prob"].is_between(0, 1).all()


def test_calibration_only_for_supported_models():
    ds = synth_dataset()
    f = ds.frame
    X = f.select("x").to_numpy()
    cfg = LogisticModelConfig()
    #! logistic has no calibration field: fold_predict fits it directly
    p, info = fold_predict(cfg, X, f["meta_label"].to_numpy(), np.ones(f.height), f["t0"].dt.epoch("s").to_numpy(),
                           f["life_start"].to_numpy(), f["life_end"].to_numpy(), X[:3])
    assert info["n_calib"] == 0 and len(p) == 3
    assert pl.Series(p).is_between(0, 1).all()


#!================================================================================(80)
#! multiclass (pt / sl / timeout)
#!--------------------------------------------------------------------------------(80)
def test_multiclass_gbm_probabilities():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(3000, 3))
    y = np.where(X[:, 0] > 0.5, 2, np.where(X[:, 0] < -0.5, 0, 1))
    cfg = GBMMulticlassModelConfig(min_data_in_leaf=20)
    P = fit_gbm_multiclass(cfg, X[:2000], y[:2000], np.ones(2000))(X[2000:])
    assert P.shape == (1000, 3) and np.allclose(P.sum(axis=1), 1)
    assert np.array_equal(P, fit_gbm_multiclass(cfg, X[:2000], y[:2000], np.ones(2000))(X[2000:]))
    assert (P.argmax(axis=1) == y[2000:]).mean() > 0.9
    cal = MulticlassCalibrator([fit_calibrator("platt", P[:, k], (y[2000:] == k).astype(float), np.ones(1000))
                                for k in range(3)])
    Q = cal(P)
    assert np.allclose(Q.sum(axis=1), 1) and (Q > 0).all()


def test_expected_value_sizer():
    prob, p_sl = np.array([0.40, 0.35, 0.30]), np.array([0.30, 0.34, 0.35])
    hw, cost = np.array([0.008, 0.008, 0.008]), np.array([1e-4, 1e-4, 1e-4])
    #! edge x half_width: 8e-4 > 1e-4 (take); 8e-5 < 1e-4 (skip); negative (skip)
    assert apply_sizer(prob, SizerConfig(rule="expected_value"), p_sl=p_sl, half_width=hw, cost=cost).tolist() == [1, 0, 0]
    with pytest.raises(ValueError, match="multiclass"):
        apply_sizer(prob, SizerConfig(rule="expected_value"))
    assert SizerConfig().config_hash() == "66cedc144eff"


def directional_dataset():
    """ The outcome depends on side x feature: pt when aligned, sl when against, timeout when small. """
    ds = synth_dataset()
    f = ds.frame
    rng = np.random.default_rng(7)
    z = f["side"].to_numpy() * f["x"].to_numpy() + rng.normal(0, 0.4, f.height)
    outcome = np.where(z > 0.5, "pt", np.where(z < -0.5, "sl", "timeout"))
    ret = np.select([outcome == "pt", outcome == "sl"], [0.005, -0.005], 0.0001)
    frame = f.with_columns(pl.Series("outcome", outcome), pl.Series("ret", ret),
                           pl.Series("meta_label", (outcome == "pt").astype(np.int8)))   # touch/t1 kept for costs
    return type(ds)(**{**ds.__dict__, "frame": frame, "signed_names": ("x",)})


def test_evaluate_multiclass_directional():
    ds = directional_dataset()
    res = evaluate(ds, model=GBMMulticlassModelConfig(min_data_in_leaf=20), sizer=SizerConfig(rule="expected_value"),
                   cv=CV, registry=None)
    t, a = res.trades, res.aggregate
    assert t["p_sl"].null_count() == 0 and t["p_timeout"].null_count() == 0
    assert np.allclose((t["prob"] + t["p_sl"] + t["p_timeout"]).to_numpy(), 1)
    assert np.allclose(t["score"].to_numpy(), (t["prob"] - t["p_sl"]).to_numpy())
    assert a["dir_auc"] > 0.9 and a["clf_auc"] > 0.8
    #! it trades the events it expects to profit on: mostly profit-takes
    taken = t.filter(pl.col("size") > 0)
    assert 0 < taken.height < t.height and (taken["outcome"] == "pt").mean() > 0.6
    for row in res.folds.iter_rows(named=True):
        assert row["n_calib"] > 0 and 0 < row["sizing_prior"] < 1


def test_binary_models_report_dir_auc_too():
    res = evaluate(directional_dataset(), model=LogisticModelConfig(), cv=CV, registry=None)
    assert res.trades["p_sl"].null_count() == res.trades.height
    assert np.array_equal(res.trades["score"].to_numpy(), res.trades["prob"].to_numpy())
    assert 0 <= res.aggregate["dir_auc"] <= 1 and "dir_auc" in res.folds.columns


def test_multiclass_config():
    assert GBMMulticlassModelConfig().label == "gbm3" and OUTCOME_CLASSES == ("sl", "timeout", "pt")
