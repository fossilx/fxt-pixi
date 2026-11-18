"""Baseline: LightGBM on the event features, evaluated with purged walk-forward folds.

Question this answers: do these features carry ANY out-of-sample information about the triple-barrier
label, and does it survive the spread? It is a yardstick for every later piece (RL, ensembles), not a
tuned model: parameters are fixed up front and nothing is chosen using the test folds.

Evaluation design
- Expanding window: each fold trains on everything before the test block and tests on the block.
- Purging: a training event is dropped unless it EXITED more than `embargo_hours` before the test block
  starts, so no training label is built from price moves that overlap the test period.
- Metrics: multiclass log loss against the training-class-frequency prior ("skill" = 1 - ll/ll_prior),
  and spread-aware P&L of the rule "long if p_up - p_down > t, short if < -t, else flat", next to naive
  benchmarks (follow the CUSUM side, fade it, always long, always short) on the same events.
- Cost: one full spread per round trip, spread_24h / price_event (exits are priced on mid).
- Canary: the same pipeline trained on SHUFFLED labels must show no skill. If it does, there is a leak.
"""
'''
The pipeline is working, and the result is an honest “no tradable directional edge yet.” That was the most likely outcome for a first baseline.

What the output says

- Skill: the unweighted model gets +1.2% log-loss skill over the class prior. The shuffled-label canary 
  comes out at −2.9%, since a model fitted to noise does worse than the prior. So the real model sits 
  about 4 points above the no-information level, which is small but probably real. The spec-weighted 
  run is −6%. Those weights concentrate on a few big-return events, and the model overfits them.
- Importance: it’s almost all volatility and activity features (log_vol, the vol ratios, spread, ticks), 
  and side and the calendar features contribute almost nothing. Barriers are volatility-scaled, so these 
  features probably help predict touch versus timeout. I haven’t confirmed that, but it fits.
- Trading: no model variant beats the benchmarks. The best cell (spec weights, edge above 0.1) is +1.15bp 
  with t = +0.4, which is noise out of nine cells. Always-long gets +2.5bp (t = 1.0), which is mostly 
  EURJPY’s upward drift, and follow-the-CUSUM-side is only +0.7bp.

So the features carry a little information about how volatile the next 48 hours will be, and none about
direction. Both findings are plausible for hourly FX.

What I’d do next, in order

- Split the skill into its two parts: touch versus timeout, and up versus down among touched events. 
  This takes about ten minutes and tells us where the +1.2% lives. I expect almost all of it in the first part.

- Try meta-labeling: keep the CUSUM side as the primary signal and train a binary model on whether following 
  it wins. The volatility information is useful here for deciding when to take the trade or skip it. 
  Follow-the-side is the benchmark to beat, at +0.7bp.

- More data before more features: about 950 independent samples is thin for any model. Another 5 to 10 years
  of EURJPY would help more than tuning, and a second pair would enable cross-pair features.

  
One discipline point: 
you’ve now seen every test fold once, so don’t tune on them from here. Judge changes on 2021 to 2023 only and
keep 2024 for a final check. It’s slightly compromised because you’ve seen the aggregate, but better than nothing.



'''


from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
from rich import print

# adjust these imports to wherever the sibling scripts live in your package
from .build_1min import Check, report
from .e_labeled_events import build_labeled_events
from .f_event_features import build_features


UTC = timezone.utc
FOLD_STARTS = [datetime(y, m, 1, tzinfo=UTC) for y in range(2021, 2025) for m in (1, 7)]   # 8 half-year folds
FOLD_END = datetime(2025, 1, 1, tzinfo=UTC)

LGB_PARAMS = dict(objective="multiclass", num_class=3, learning_rate=0.03, num_leaves=7,
                  min_data_in_leaf=40, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                  lambda_l2=5.0, verbose=-1, seed=42, deterministic=True, force_row_wise=True)
N_ROUNDS = 150      # fixed; no early stopping on the test folds
#


@dataclass
class Fold:
    start: float          # test block [start, end) in epoch seconds
    end: float
    train: np.ndarray     # row indices
    test: np.ndarray


def make_folds(df: pl.DataFrame, starts=FOLD_STARTS, end=FOLD_END, embargo_hours: float = 24.0,
               min_train: int = 200, min_test: int = 50) -> list[Fold]:
    t = df["event_time"].dt.epoch("s").to_numpy().astype(float)
    x = df["exit_time"].dt.epoch("s").to_numpy().astype(float)
    bounds = [s.timestamp() for s in starts] + [end.timestamp()]
    folds = []
    for s, e in zip(bounds[:-1], bounds[1:]):
        test = np.where((t >= s) & (t < e))[0]
        train = np.where(x < s - embargo_hours * 3600)[0]          # purge + embargo (exit, not entry)
        if len(test) >= min_test and len(train) >= min_train:
            folds.append(Fold(s, e, train, test))
    return folds
#


def fit_predict(df: pl.DataFrame, cols: list[str], folds: list[Fold], weight_col: str | None = None,
                shuffle_labels: bool = False, seed: int = 0):
    """Out-of-sample class probabilities (columns: -1, 0, +1), training-prior probabilities, fold ids,
    and summed gain importance. Rows outside every test block stay NaN."""
    X = df.select(cols).to_numpy().astype(float)
    y = (df["label"].to_numpy().astype(int) + 1)                    # {-1,0,1} -> {0,1,2}
    w = np.ones(len(y)) if weight_col is None else df[weight_col].to_numpy().astype(float)
    P = np.full((len(y), 3), np.nan)
    prior = np.full((len(y), 3), np.nan)
    fold_id = np.full(len(y), -1)
    imp = np.zeros(len(cols))
    rng = np.random.default_rng(seed)
    for k, f in enumerate(folds):
        ytr = rng.permutation(y[f.train]) if shuffle_labels else y[f.train]
        model = lgb.train(LGB_PARAMS, lgb.Dataset(X[f.train], ytr, weight=w[f.train]), N_ROUNDS)
        P[f.test] = model.predict(X[f.test])
        prior[f.test] = np.bincount(ytr, minlength=3) / len(ytr)
        fold_id[f.test] = k
        imp += model.feature_importance("gain")
    return P, prior, fold_id, imp
#


def log_loss(P: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(P[np.arange(len(y)), y], 1e-12, 1.0)
    return float(-np.log(p).mean())


def skill(P, prior, label) -> tuple[float, float, float]:
    m = ~np.isnan(P[:, 0])
    y = label[m].astype(int) + 1
    ll, ll0 = log_loss(P[m], y), log_loss(prior[m], y)
    return ll, ll0, 1.0 - ll / ll0
#


def trade_stats(pos: np.ndarray, ret: np.ndarray, cost: np.ndarray, uniq: np.ndarray) -> dict:
    """Per-trade stats for position array pos in {-1,0,+1}. net = pos*ret - cost on trades only."""
    m = pos != 0
    n = int(m.sum())
    if n < 5:
        return dict(n=n, gross_bp=np.nan, net_bp=np.nan, hit=np.nan, t=np.nan)
    gross = pos[m] * ret[m]
    net = gross - cost[m]
    n_eff = n * float(uniq[m].mean())                               # overlapping events are not independent
    t = net.mean() / (net.std(ddof=1) / np.sqrt(n_eff)) if net.std() > 0 else np.nan
    return dict(n=n, gross_bp=1e4 * gross.mean(), net_bp=1e4 * net.mean(), hit=float((net > 0).mean()), t=t)


def evaluate(df: pl.DataFrame, P, prior, label: str, thresholds=(0.0, 0.1, 0.2)) -> None:
    m = ~np.isnan(P[:, 0])
    ll, ll0, sk = skill(P, prior, df["label"].to_numpy())
    y = df["label"].to_numpy()[m].astype(int)
    acc = float((P[m].argmax(axis=1) - 1 == y).mean())
    maj = float(max(((y == v).mean() for v in (-1, 0, 1))))
    print(f"[bold]{label}[/bold]  OOS events={int(m.sum())}  log loss {ll:.4f} vs prior {ll0:.4f} "
          f"(skill {sk:+.2%})  accuracy {acc:.1%} vs majority {maj:.1%}")

    ret = df["return_at_exit"].to_numpy()[m]
    cost = df["cost"].to_numpy()[m]
    uniq = df["uniqueness"].to_numpy()[m]
    side = df["side"].to_numpy()[m].astype(float)
    edge = P[m, 2] - P[m, 0]
    rows = {f"model, |edge|>{t:.1f}": np.where(np.abs(edge) > t, np.sign(edge), 0.0) for t in thresholds}
    rows |= {"follow CUSUM side": side, "fade CUSUM side": -side,
             "always long": np.ones(len(ret)), "always short": -np.ones(len(ret))}
    for name, pos in rows.items():
        s = trade_stats(pos, ret, cost, uniq)
        print(f"   {name:<22} trades={s['n']:<5} gross={s['gross_bp']:+6.2f}bp  net={s['net_bp']:+6.2f}bp  "
              f"hit={s['hit']:.1%}  t(eff)={s['t']:+.2f}")
#


def verify_baseline(df: pl.DataFrame, folds: list[Fold], P, fold_id, canary_skill: float) -> list[Check]:
    t = df["event_time"].dt.epoch("s").to_numpy().astype(float)
    x = df["exit_time"].dt.epoch("s").to_numpy().astype(float)
    purged = all(x[f.train].max() < f.start for f in folds)
    in_block = all((t[f.test] >= f.start).all() and (t[f.test] < f.end).all() for f in folds)
    disjoint = len(np.concatenate([f.test for f in folds])) == len(np.unique(np.concatenate([f.test for f in folds])))
    m = fold_id >= 0
    return [
        Check("training labels all exit before their test block", bool(purged)),
        Check("test events inside their block, blocks disjoint", bool(in_block and disjoint)),
        Check("probabilities valid on test rows",
              bool(np.isfinite(P[m]).all() and np.allclose(P[m].sum(axis=1), 1.0, atol=1e-6))),
        Check("canary: shuffled-label model shows no skill", canary_skill < 0.01, f"skill {canary_skill:+.2%}"),
    ]
#


def run(df: pl.DataFrame, cols: list[str], folds: list[Fold]) -> None:
    print(f"{df.height} events, {len(folds)} folds: " +
          ", ".join(f"{datetime.fromtimestamp(f.start, UTC):%Y-%m}({len(f.train)}/{len(f.test)})" for f in folds)
          + "   [train/test sizes]")
    first = None
    for name, wcol in (("no weights", None), ("weight_uniq", "weight_uniq"), ("weight (spec 7.2)", "weight")):
        P, prior, fold_id, imp = fit_predict(df, cols, folds, wcol)
        evaluate(df, P, prior, name)
        if first is None:
            first = (P, fold_id, imp)
    P, fold_id, imp = first
    order = np.argsort(-imp)
    print("   gain importance (no weights): " + ", ".join(f"{cols[i]} {imp[i] / imp.sum():.0%}" for i in order))
    Ps, priors, _, _ = fit_predict(df, cols, folds, None, shuffle_labels=True, seed=1)
    canary = skill(Ps, priors, df["label"].to_numpy())[2]
    report(verify_baseline(df, folds, P, fold_id, canary))
#




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    LAKE = Path("data/lake")
    SRC = ("dukascopy", "forex", "EURJPY")

    labeled = build_labeled_events(LAKE, *SRC, verbose=False)
    df, cols, _ = build_features(LAKE, *SRC, labeled)
    df = (df.join(labeled.select("event_time", "return_at_exit", "price_event"), on="event_time")
            .with_columns(cost=(pl.col("spread_24h") / pl.col("price_event")))
            .with_columns(cost=pl.col("cost").fill_nan(None).fill_null(pl.col("cost").median()))
            .sort("event_time"))
    run(df, cols, make_folds(df))