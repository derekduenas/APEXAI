"""Purged cross-validation with embargo, walk-forward, and the window guard.

Standard k-fold LEAKS on financial labels: a 20-day forward return at date t
shares 19 days with the label at t+1, so a test fold's neighbours in the
train set carry most of the test answer. Purging removes from the train set
every sample whose LABEL WINDOW overlaps the test fold; the embargo removes
a further buffer after the fold (serial correlation leaks both ways).

FAILS CLOSED: an embargo shorter than the label horizon is refused at
construction -- there is no "warning mode". The window guard refuses any
date on or after the validation period's start, so exploration structurally
cannot touch validation or holdout, and cannot tune against either.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class ExplorationError(ValueError):
    """An exploration-governance invariant was violated."""


def require_exploration_window(dates: pd.DatetimeIndex, config) -> None:
    """IN-SAMPLE ONLY, structurally. Refuses validation and holdout dates."""
    limit = pd.Timestamp(config.period("validation")["start"])
    latest = pd.DatetimeIndex(dates).max()
    if latest >= limit:
        raise ExplorationError(
            f"exploration window reaches {latest.date()}, at or past the "
            f"validation boundary {limit.date()}. Exploration reads in-sample "
            f"only; tuning against validation or holdout is the failure mode "
            f"this guard exists to prevent.")


class PurgedKFold:
    """K folds over ordered samples with label-overlap purging and embargo.

    `label_horizon` is the forward window (in samples) each label spans.
    `embargo` must be >= label_horizon or construction is REFUSED.
    """

    def __init__(self, n_splits: int, label_horizon: int, embargo: int):
        if n_splits < 2:
            raise ExplorationError("need at least 2 folds")
        if embargo < label_horizon:
            raise ExplorationError(
                f"embargo ({embargo}) shorter than the label horizon "
                f"({label_horizon}): overlapping labels would leak across the "
                f"fold boundary. Refused, not warned.")
        self.n_splits = int(n_splits)
        self.label_horizon = int(label_horizon)
        self.embargo = int(embargo)

    def split(self, n_samples: int):
        """Yields (train_idx, test_idx). Train excludes: the fold, every
        sample whose label window overlaps it, and the embargo after it."""
        idx = np.arange(n_samples)
        folds = np.array_split(idx, self.n_splits)
        for fold in folds:
            lo, hi = int(fold[0]), int(fold[-1])
            # a train sample i leaks if its label window [i, i+h] touches
            # [lo, hi]; and the embargo bans (hi, hi+embargo]
            banned_lo = lo - self.label_horizon
            banned_hi = hi + self.embargo
            train = idx[(idx < banned_lo) | (idx > banned_hi)]
            yield train, fold


def walk_forward(n_samples: int, n_folds: int, label_horizon: int):
    """Expanding-window walk-forward: train on everything before the fold
    minus the label horizon (the trailing labels are not yet resolved at the
    fold's start -- using them would be lookahead)."""
    idx = np.arange(n_samples)
    folds = np.array_split(idx[n_samples // (n_folds + 1):], n_folds)
    for fold in folds:
        lo = int(fold[0])
        train = idx[: max(0, lo - label_horizon)]
        if len(train):
            yield train, fold
