"""Labeled events with sample weights (pipeline spec v2, section 7) - first pass.

build_labeled_events() runs the locked first-pass pipeline end to end:
    1HOUR bars -> CUSUM events (h=3) -> triple-barrier labels (N=48h, k=1.0 horizon-sigmas) -> weights
and add_weights() adds, for every labeled event:
    uniqueness       time-weighted mean of 1/concurrency over the event's life
    mean_concurrency time-weighted mean concurrency over the event's life
    weight           spec 7.2: uniqueness * |return_at_exit|, rescaled to mean 1
    weight_uniq      uniqueness only, rescaled to mean 1

Concurrency is measured on BUSINESS time (hourly bars as the clock, fractional within a bar), so a
weekend never counts as hours of overlap. An event is alive from its event_time until its exit; a
touch exit lives through the end of the touching minute (so no event has zero length).

Not done here: sequential bootstrap (spec 7.3, deferred) and purged/embargoed cross-validation -
the lives computed here (start/end columns) are exactly what the purging step will need.

"""
'''

- The summary line “effective sample size” is the Kish formula, which only measures how unequal the 
  weights are. It isn’t a count of independent samples. For that, use N × mean uniqueness, which 
  comes to about 950 for your 2,970 events. The summary now prints both and labels them.

Reading your results

- Uniqueness and concurrency: mean uniqueness of 0.32 and mean concurrency of 3.6 (max 7) match 
  what I’d expect from a median hold of about 22 hours against about 8 hours between events.
- Spec weight vs timeouts: timeouts are 41% of events but get only 23% of the spec weight, as flagged earlier.
- Up and down: the two get equal weight shares (38% each), so the weighting doesn’t introduce a directional bias.

Since the data supports about 950 independent samples, I’d keep the first feature set small and the first model simple.

The next step is the event-time feature set. I’d propose a deliberately small first one: multi-horizon 
returns (1h, 4h, 24h, 5d), volatility ratios (the barrier volatility vs the CUSUM volatility, and 24h vs 5d),
average spread, tick activity, hour of day, and day of week. Every feature would use data up to the event 
time only, via the same point-in-time slicing. 

Does that list work as a start?

'''


from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
from rich import print

# adjust these imports to wherever the sibling scripts live in your package
from .build_1min import Check, report
from .cusum_events import CusumParams, detect_events, load_bars
from .d_triple_barrier import LabelParams, TickResolver, label_events, load_minute_bars, summarize_labels


LOCKED = dict(h=3.0, k=1.0, vertical_hours=48)   # first-pass defaults - don't tune before the baseline exists
#


def business_coord(epoch: np.ndarray, th: np.ndarray, bar_s: int = 3600) -> np.ndarray:
    """Epoch seconds -> position on the business clock: index of the bar containing the time (or of the
    next open bar, if the time falls in a closed stretch) plus the fraction of the bar elapsed."""
    hour0 = epoch - epoch % bar_s
    return np.searchsorted(th, hour0, side="left") + (epoch - hour0) / bar_s
#


def _lives(ok: pl.DataFrame, th: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    start = business_coord(ok["event_time"].dt.epoch("s").to_numpy(), th)
    touch = (ok["label"].to_numpy() != 0).astype("int64") * 60       # touch exits live through their minute
    end = business_coord(ok["exit_time"].dt.epoch("s").to_numpy() + touch, th)
    return start, end


def _sweep(start: np.ndarray, end: np.ndarray):
    """Sweep-line over all start/end points: O(n log n), no pairwise overlap checks."""
    pts = np.unique(np.concatenate([start, end]))
    c = np.searchsorted(np.sort(start), pts, "right") - np.searchsorted(np.sort(end), pts, "right")
    seg, c_seg = np.diff(pts), c[:-1]                                # concurrency is constant on [pts[k], pts[k+1])
    inv = np.divide(seg, c_seg, out=np.zeros_like(seg), where=c_seg > 0)
    # prefix sums in extended precision: per-event values are differences of long running totals, and in
    # float64 that loses ~1e-11 absolute, which is visible for events that live only a few minutes
    ld = np.longdouble
    cum_inv = np.concatenate([[0], np.cumsum(inv, dtype=ld)])
    cum_c = np.concatenate([[0], np.cumsum(seg * c_seg, dtype=ld)])
    a, b = np.searchsorted(pts, start), np.searchsorted(pts, end)    # exact: pts contains every start/end
    life = end - start
    uniq = ((cum_inv[b] - cum_inv[a]) / life).astype(float)
    mean_c = ((cum_c[b] - cum_c[a]) / life).astype(float)
    return uniq, mean_c, float(seg[c_seg > 0].sum())


def add_weights(labels: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame:
    ok = labels.filter(pl.col("status") == "ok")
    th = bars["time"].dt.epoch("s").to_numpy()
    start, end = _lives(ok, th)
    if not (end > start).all():
        raise ValueError("every event needs end > start on the business clock")
    uniq, mean_c, _ = _sweep(start, end)
    ret = np.abs(ok["return_at_exit"].to_numpy())
    norm = lambda w: w / w.mean()
    w = pl.DataFrame({
        "event_time": ok["event_time"],
        "life_start": start, "life_end": end,
        "uniqueness": uniq, "mean_concurrency": mean_c,
        "weight": norm(uniq * ret), "weight_uniq": norm(uniq),
    })
    return labels.join(w, on="event_time", how="left")
#


def summarize_weights(lab: pl.DataFrame) -> None:
    ok = lab.filter(pl.col("status") == "ok")
    n = ok.height
    ess = lambda w: float(w.sum() ** 2 / (w ** 2).sum())
    print(f"[bold]{n} labeled events[/bold]  mean uniqueness={ok['uniqueness'].mean():.2f}  "
          f"mean concurrency={ok['mean_concurrency'].mean():.1f} (max {ok['mean_concurrency'].max():.1f})")
    print(f"   independent samples ~ N * mean uniqueness = {n * ok['uniqueness'].mean():.0f};  "   #type: ignore
          f"weight evenness (Kish ESS, only measures how unequal the weights are): "
          f"uniqueness-only {ess(ok['weight_uniq']):.0f}, spec weight {ess(ok['weight']):.0f} (of {n})")
    share = (ok.group_by("label").agg(pl.col("weight").sum().alias("w"), pl.len().alias("n"))
               .with_columns(w_share=pl.col("w") / pl.col("w").sum(), n_share=pl.col("n") / n).sort("label"))
    print("   share of spec weight vs share of events, by label: " +
          ", ".join(f"{int(l):+d}: {ws:.0%} vs {ns:.0%}" for l, ws, ns in share.select("label", "w_share", "n_share").iter_rows()))
#


def verify_weights(lab: pl.DataFrame, bars: pl.DataFrame, sample: int = 100, seed: int = 42) -> list[Check]:
    ok = lab.filter(pl.col("status") == "ok")
    th = bars["time"].dt.epoch("s").to_numpy()
    start, end = _lives(ok, th)
    uniq = ok["uniqueness"].to_numpy()
    mean_c = ok["mean_concurrency"].to_numpy()
    out = [
        Check("weights finite and positive", bool(np.isfinite(ok["weight"].to_numpy()).all()
                                                   and (ok["weight_uniq"].to_numpy() > 0).all())),
        Check("both weights have mean 1", abs(ok["weight"].mean() - 1) < 1e-9 and abs(ok["weight_uniq"].mean() - 1) < 1e-9),   #type: ignore
        Check("uniqueness in (0, 1]", bool(((uniq > 0) & (uniq <= 1 + 1e-12)).all())),
        Check("mean concurrency >= 1", bool((ok["mean_concurrency"].to_numpy() >= 1 - 1e-9).all()),
              f"min {ok['mean_concurrency'].min():.12f}"),
    ]
    # invariant: at any instant the active events' 1/c shares sum to 1, so
    # sum(uniqueness * life) must equal the total business time covered by at least one event.
    union = _sweep(start, end)[2]
    total = float((uniq * (end - start)).sum())
    out.append(Check("sum(uniqueness*life) == time covered", abs(total - union) <= 1e-9 * max(union, 1.0),
                     f"{total:.6f} vs {union:.6f}"))
    # independent recompute for a sample: direct counting at segment midpoints, no sweep-line
    rng = np.random.default_rng(seed)
    worst = worst_c = 0.0
    for i in rng.choice(len(start), size=min(sample, len(start)), replace=False):
        inner = np.concatenate([start[(start > start[i]) & (start < end[i])], end[(end > start[i]) & (end < end[i])]])
        pts = np.unique(np.concatenate([[start[i], end[i]], inner]))
        mids = (pts[:-1] + pts[1:]) / 2
        c = ((start[None, :] <= mids[:, None]) & (mids[:, None] < end[None, :])).sum(axis=1)
        ref = float(((pts[1:] - pts[:-1]) / c).sum() / (end[i] - start[i]))
        ref_c = float(((pts[1:] - pts[:-1]) * c).sum() / (end[i] - start[i]))
        worst = max(worst, abs(ref - uniq[i]))
        worst_c = max(worst_c, abs(ref_c - mean_c[i]))
    out.append(Check(f"{min(sample, len(start))}-event brute-force recompute", worst < 1e-9 and worst_c < 1e-9,   #type: ignore
                     f"max diff uniqueness {worst:.2e}, concurrency {worst_c:.2e}"))
    return out
#


def build_labeled_events(lake: Path, source: str, market: str, symbol: str,
                         h: float = LOCKED["h"], k: float = LOCKED["k"],
                         vertical_hours: int = LOCKED["vertical_hours"], verbose: bool = True) -> pl.DataFrame:   #type: ignore
    bars = load_bars(lake, source, market, symbol, "1HOUR")
    events = detect_events(bars, replace(CusumParams(), h=h))
    minute = load_minute_bars(lake, source, market, symbol)
    resolver = TickResolver(lake, source, market, symbol)
    p = LabelParams.from_horizon(k, vertical_hours)
    labels = label_events(events, bars, minute, resolver, p)
    if verbose:
        summarize_labels(labels, p)
    return add_weights(labels, bars)
#




#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    LAKE = Path("data/lake")
    SRC = ("dukascopy", "forex", "EURJPY")

    lab = build_labeled_events(LAKE, *SRC)
    summarize_weights(lab)
    bars = load_bars(LAKE, *SRC, "1HOUR")
    report(verify_weights(lab, bars))
    print(lab.select("event_time", "label", "hours_to_exit", "return_at_exit", "uniqueness",
                     "mean_concurrency", "weight", "weight_uniq").head(10))