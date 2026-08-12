"""APEX-002 -- Net Share Issuance. Execution of a FROZEN specification.

Governed by APEX-002-Protocol-Net-Share-Issuance.md,
SHA-256 63703d1020893a59a4b43ed9698c4920ccb392e7f76bc77030ef019693ea9bda

    NSI(i,T) = ln( S(i,q0) / S(i,q-4) )

This module implements the specification. It does not improve it. Every number
below is transcribed from the frozen document; none was chosen here.

SIX INVARIANTS, each enforced structurally rather than by comment:

1. PIT SELECTION. Group by (ticker, reportperiod), sort by filing `date`
   ASCENDING, take the FIRST. 3.45% of pairs carry multiple ARQ rows because
   Sharadar RETAINS revisions; `.last()` selects the restated figure and would
   be a lookahead violation. Admit only rows with `date <= T`.

2. FORMULA. Natural log of the ratio of two `sharesbas` observations twelve
   months apart. No winsorisation, clipping, smoothing or any other transform.
   The ratio form is MANDATORY, not stylistic: `sharesbas` is retroactively
   split-rebased, so the rebasing factor embeds splits occurring AFTER T and
   cancels only in a ratio. A level-based measure would be lookahead.

3. CORPORATE ACTIONS. Spin-offs, mergers, acquisitions, conversions and any
   ambiguous action inside the window EXCLUDE the security at that date.
   Excluded means missing NSI -- never an adjustment, never a repair. Splits
   need no treatment: the vendor's rebasing already removed them exactly.

4. UNIVERSE ORDERING. NSI is computed AFTER section 3 eligibility, on the
   eligible cross-section only. NSI availability never redefines the universe.

5. RANKING. Ascending -- lowest NSI (largest net repurchase) ranks first.
   Ties resolved by the frozen C10 rule.

6. GOVERNANCE. #001 is closed. Nothing here reads it.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ARQ = "ARQ"
SHARES = "sharesbas"

# Frozen specification section 6. Splits are deliberately ABSENT: the vendor's
# retroactive rebasing removes them exactly, and re-adjusting would double-count.
EXCLUDING_ACTIONS = frozenset({
    "spinoff", "spunofffrom", "spinoffdividend",
    "acquisitionby", "acquisitionof",
    "mergerto", "mergerfrom",
    "conversion", "recapitalization", "recapitalisation",
})

# Frozen specification section 7: four consecutive quarters, ~12 months.
WINDOW_QUARTERS = 4
MIN_WINDOW_DAYS = 270
MAX_WINDOW_DAYS = 460


@dataclass
class NSIReport:
    raw_arq_rows: int = 0
    dropped_impossible_filing: int = 0
    dropped_nonpositive_shares: int = 0
    dropped_revisions: int = 0
    as_filed_rows: int = 0
    securities_with_history: int = 0
    excluded_corporate_action: int = 0
    computed_observations: int = 0
    exact_zero_nsi: int = 0
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def load_as_filed(root: Path, report: NSIReport) -> pd.DataFrame:
    """Invariant 1. Earliest filing per (ticker, reportperiod) -- never the latest."""
    frames = [
        pd.read_csv(p, usecols=["ticker", "dimension", "date", "reportperiod", SHARES])
        for p in sorted(glob.glob(str(root / "raw" / "SF1" / "*.csv")))
    ]
    if not frames:
        raise FileNotFoundError(f"no SF1 slices under {root}")
    frame = pd.concat(frames, ignore_index=True)
    frame = frame[frame["dimension"] == ARQ].copy()
    report.raw_arq_rows = len(frame)

    frame["date"] = pd.to_datetime(frame["date"])
    frame["reportperiod"] = pd.to_datetime(frame["reportperiod"])
    frame[SHARES] = pd.to_numeric(frame[SHARES], errors="coerce")

    impossible = frame["date"] <= frame["reportperiod"]
    report.dropped_impossible_filing = int(impossible.sum())
    frame = frame[~impossible]

    bad = frame[SHARES].isna() | (frame[SHARES] <= 0)
    report.dropped_nonpositive_shares = int(bad.sum())
    frame = frame[~bad]

    before = len(frame)
    # THE CRITICAL LINE. Ascending by filing date, take the FIRST.
    frame = (
        frame.sort_values("date", kind="mergesort")
        .groupby(["ticker", "reportperiod"], as_index=False, sort=False)
        .first()
    )
    report.dropped_revisions = before - len(frame)
    report.as_filed_rows = len(frame)
    return frame.sort_values(["ticker", "reportperiod"], kind="mergesort")


def load_exclusions(root: Path) -> dict:
    """Invariant 3. ticker -> sorted list of excluding action dates."""
    frames = [
        pd.read_csv(p, usecols=["date", "action", "ticker"], dtype=str)
        for p in sorted(glob.glob(str(root / "raw" / "ACTIONS" / "*.csv")))
    ]
    actions = pd.concat(frames, ignore_index=True)
    actions = actions[actions["action"].str.lower().isin(EXCLUDING_ACTIONS)]
    actions["date"] = pd.to_datetime(actions["date"], errors="coerce")
    actions = actions.dropna(subset=["date"])
    return {t: sorted(g) for t, g in actions.groupby("ticker")["date"]}


def build_nsi_panel(
    as_filed: pd.DataFrame,
    exclusions: dict,
    ticker_to_security: dict,
    dates: pd.DatetimeIndex,
    securities: pd.Index,
    report: NSIReport,
) -> pd.DataFrame:
    """Invariants 1-3. Wide NSI frame: rows = formation dates, cols = security_id.

    For each security and each formation date T, the signal uses the most recent
    as-filed observation with `date <= T` and its counterpart ~12 months earlier
    also filed by T. Availability is governed by the FILING date, never by the
    fiscal-period label.
    """
    panel = pd.DataFrame(np.nan, index=dates, columns=securities, dtype="float64")

    for ticker, group in as_filed.groupby("ticker", sort=False):
        security = ticker_to_security.get(ticker)
        if security is None or security not in panel.columns:
            continue

        group = group.sort_values("reportperiod", kind="mergesort")
        shares = group[SHARES].to_numpy()
        filed = group["date"].to_numpy()
        period = group["reportperiod"].to_numpy()
        if len(group) <= WINDOW_QUARTERS:
            continue
        report.securities_with_history += 1

        events = exclusions.get(ticker, ())
        # Row i pairs with row i-4; both must be filed by T.
        pairs = []
        for i in range(WINDOW_QUARTERS, len(group)):
            j = i - WINDOW_QUARTERS
            span = (period[i] - period[j]).astype("timedelta64[D]").astype(int)
            if not (MIN_WINDOW_DAYS <= span <= MAX_WINDOW_DAYS):
                continue
            if any(period[j] < np.datetime64(e) <= period[i] for e in events):
                report.excluded_corporate_action += 1
                continue
            pairs.append((max(filed[i], filed[j]), np.log(shares[i] / shares[j])))

        if not pairs:
            continue
        known_from = np.array([p[0] for p in pairs])
        values = np.array([p[1] for p in pairs])
        # Latest observation whose information was public by T.
        idx = np.searchsorted(known_from, dates.to_numpy(), side="right") - 1
        usable = idx >= 0
        panel.loc[usable, security] = values[idx[usable]]

    stacked = panel.stack()
    report.computed_observations = int(stacked.notna().sum())
    report.exact_zero_nsi = int((stacked == 0).sum())
    return panel


def rank_ascending(nsi: pd.DataFrame, eligible: pd.DataFrame, tie_method: str = "first"):
    """Invariants 4-5. Rank ONLY the eligible cross-section, ascending.

    Lowest NSI -- the largest net repurchaser -- receives rank 1 and the top
    decile, which is what the pre-registered direction states. Eligibility is
    applied FIRST; NSI never widens or narrows the universe.
    """
    restricted = nsi.where(eligible)
    return restricted.rank(axis=1, method=tie_method, ascending=True, pct=True)
