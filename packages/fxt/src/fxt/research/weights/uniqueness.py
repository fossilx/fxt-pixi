'''
uniqueness

Sample weights from label overlap (ML pipeline spec §7). Pure: labels +
the business clock in, one weight row per label out. Ported from
first_bars/e_labeled_events.py.

    out = compute_weights(labels, clock_times)

Output columns (WEIGHT_SCHEMA), one row per label, in label order:
    event_id, t0, t1
    life_start, life_end   position on the business clock (hourly bars + fraction);
                           the purging step will use these
    life_hours             life_end - life_start, in business hours
    uniqueness             time-weighted mean of 1/concurrency over the life, in (0, 1]
    mean_concurrency       time-weighted mean concurrency over the life, >= 1
    weight                 uniqueness * |ret|, rescaled to mean 1
    weight_uniq            uniqueness, rescaled to mean 1
All null for insufficient_data labels (they're not training examples).

Identity used as a check: at any instant the live events' 1/c shares sum to
1, so sum(uniqueness * life) equals the business time covered by >= 1 event.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

import numpy as np
import polars as pl

from fxt.research.labels.touch import epoch_s

__all__ = ["WEIGHT_SCHEMA", "business_coord", "compute_weights", "sweep"]

TOUCH_EXIT_EXTRA_S = 60          # a barrier exit lives through the end of its touching 1MIN bar

WEIGHT_SCHEMA: dict[str, pl.DataType] = {
    "event_id":         pl.String(),
    "t0":               pl.Datetime("us", "UTC"),
    "t1":               pl.Datetime("us", "UTC"),
    "life_start":       pl.Float64(),
    "life_end":         pl.Float64(),
    "life_hours":       pl.Float64(),
    "uniqueness":       pl.Float64(),
    "mean_concurrency": pl.Float64(),
    "weight":           pl.Float64(),
    "weight_uniq":      pl.Float64(),
}


def business_coord(epoch: np.ndarray, clock: np.ndarray, bar_s: int = 3600) -> np.ndarray:
    """ Epoch seconds -> business clock: index of the bar containing the time (or of the
        next open bar, if the time is in a closed stretch) plus the fraction of the bar elapsed.
        `clock` = sorted bar open times (epoch seconds).
    """
    hour0 = epoch - epoch % bar_s
    return np.searchsorted(clock, hour0, side="left") + (epoch - hour0) / bar_s
#

def sweep(start: np.ndarray, end: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """ (uniqueness, mean_concurrency, time covered) by a sweep line over all start/end
        points: O(n log n). Concurrency is constant between consecutive points.
    """
    pts = np.unique(np.concatenate([start, end]))
    c = np.searchsorted(np.sort(start), pts, "right") - np.searchsorted(np.sort(end), pts, "right")
    seg, c_seg = np.diff(pts), c[:-1]
    inv = np.divide(seg, c_seg, out=np.zeros_like(seg), where=c_seg > 0)
    #! prefix sums in extended precision: per-event values are differences of long running
    #! totals, and float64 loses ~1e-11 absolute, visible for events that live a few minutes
    ld = np.longdouble
    cum_inv = np.concatenate([[0], np.cumsum(inv, dtype=ld)])
    cum_c = np.concatenate([[0], np.cumsum(seg * c_seg, dtype=ld)])
    a, b = np.searchsorted(pts, start), np.searchsorted(pts, end)     # exact: pts holds every point
    life = end - start
    uniq = ((cum_inv[b] - cum_inv[a]) / life).astype(float)
    mean_c = ((cum_c[b] - cum_c[a]) / life).astype(float)
    return uniq, mean_c, float(seg[c_seg > 0].sum())
#

def compute_weights(labels: pl.DataFrame, clock_times: pl.Series) -> pl.DataFrame:
    """ One weight row per label (WEIGHT_SCHEMA).

        labels       event_id, t0, t1, touch, outcome, ret (a labels table)
        clock_times  open times of every bar that defines business time (1HOUR)
    """
    clock = np.sort(epoch_s(clock_times))
    placed = labels.filter(pl.col("outcome") != "insufficient_data")
    out = labels.select("event_id", "t0", "t1")
    if placed.height == 0:
        return out.with_columns(*[pl.lit(None, dtype=d).alias(c) for c, d in WEIGHT_SCHEMA.items()
                                  if c not in out.columns]).select(*WEIGHT_SCHEMA).cast(WEIGHT_SCHEMA)  # type: ignore[arg-type]

    extra = np.where(placed.get_column("touch").to_numpy() != "vertical", TOUCH_EXIT_EXTRA_S, 0)
    start = business_coord(epoch_s(placed.get_column("t0")), clock)
    end = business_coord(epoch_s(placed.get_column("t1")) + extra, clock)
    if not (end > start).all():
        bad = placed.get_column("event_id").filter(pl.Series(end <= start)).to_list()[:3]
        raise ValueError(f"every life needs end > start on the business clock; bad: {bad}")

    uniq, mean_c, _ = sweep(start, end)
    absret = np.abs(placed.get_column("ret").to_numpy())
    w = uniq * absret
    if not w.mean() > 0:
        raise ValueError("every placed label has zero return; can't rescale weights")
    calc = pl.DataFrame({
        "event_id": placed.get_column("event_id"),
        "life_start": start, "life_end": end, "life_hours": end - start,
        "uniqueness": uniq, "mean_concurrency": mean_c,
        "weight": w / w.mean(), "weight_uniq": uniq / uniq.mean(),
    })
    return out.join(calc, on="event_id", how="left", maintain_order="left") \
              .select(*WEIGHT_SCHEMA).cast(WEIGHT_SCHEMA)  # type: ignore[arg-type]
#-
