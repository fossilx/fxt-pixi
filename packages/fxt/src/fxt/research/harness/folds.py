'''
folds

Purged expanding walk-forward folds (ML pipeline spec §9.1).

    folds = make_folds(frame, clock, cfg)                  # development folds
    folds = make_folds(frame, clock, cfg, lockbox=True)    # one fold: test = lockbox year

`frame` needs t0, life_start and life_end (business-clock positions, from weights);
`clock` = sorted hourly bar open times in epoch seconds (the same business clock).
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from fxt.research.models import WalkForwardConfig
from fxt.research.weights.uniqueness import business_coord

__all__ = ["Fold", "data_starts", "make_folds", "usable_mask"]


@dataclass(frozen=True)
class Fold:
    index: int
    test_year: int
    train: np.ndarray                          # bool mask over the frame's rows
    test: np.ndarray
    purged: int                                # training candidates dropped for overlapping the test block
    embargoed: int                             # ... for starting inside the embargo after it

    @property
    def n_train(self) -> int:
        return int(self.train.sum())

    @property
    def n_test(self) -> int:
        return int(self.test.sum())
#


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def data_starts(clock: np.ndarray, cfg: WalkForwardConfig) -> np.ndarray:
    """ Epoch seconds where data (re)starts: the first bar, and every bar after a gap longer
        than restart_gap_days.
    """
    gaps = np.flatnonzero(np.diff(clock) > cfg.restart_gap_days * 86400) + 1
    return np.concatenate([clock[:1], clock[gaps]])


def usable_mask(frame: pl.DataFrame, clock: np.ndarray, cfg: WalkForwardConfig) -> np.ndarray:
    """ False for events within drop_start_days after a data start (start-of-data dependence). """
    t0 = frame.get_column("t0").dt.epoch("s").to_numpy()
    starts = data_starts(clock, cfg)
    last_start = starts[np.searchsorted(starts, t0, side="right") - 1]    # t0 >= clock[0] for real events
    return t0 >= last_start + cfg.drop_start_days * 86400


def make_folds(frame: pl.DataFrame, clock: np.ndarray, cfg: WalkForwardConfig, *,
               lockbox: bool = False) -> list[Fold]:
    t0 = frame.get_column("t0").dt.epoch("s").to_numpy()
    ls = frame.get_column("life_start").to_numpy()
    le = frame.get_column("life_end").to_numpy()
    usable = usable_mask(frame, clock, cfg)
    years = cfg.test_years() if not lockbox else (cfg.lockbox_year,)
    embargo_bars = cfg.embargo_hours                    # business clock unit = one hourly bar

    folds = []
    for i, year in enumerate(years):
        start = _epoch(datetime(year, 1, 1, tzinfo=UTC))
        end = _epoch(datetime(year + 1, 1, 1, tzinfo=UTC))
        b0, b1 = business_coord(np.array([start, end]), clock)
        test = usable & (t0 >= start) & (t0 < end)
        candidates = usable & (t0 < start)              # expanding window: everything before the test year
        overlap = (ls < b1) & (le > b0)
        embargo = (ls >= b1) & (ls < b1 + embargo_bars)
        train = candidates & ~overlap & ~embargo
        folds.append(Fold(index=i, test_year=year, train=train, test=test,
                          purged=int((candidates & overlap).sum()),
                          embargoed=int((candidates & ~overlap & embargo).sum())))
    return folds


def year_span(year: int) -> tuple[datetime, datetime]:
    return datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC) - timedelta(microseconds=1)
#-
