"""Optional secondary-source cross-check -- CONVENTIONS A-002.

    Sharadar is confirmed primary and authoritative for every universe filter.
    Norgate is admitted as an OPTIONAL SECONDARY source for prices and
    cross-checking only, and may never be authoritative for a universe filter,
    for shares outstanding, for market capitalisation, or for security identity.
    Where the two disagree on a price, Sharadar governs and the disagreement is
    reported.

HOW "NEVER AUTHORITATIVE" IS ENFORCED STRUCTURALLY

Not by discipline, and not by a comment. `cross_check` accepts the authoritative
panel and a secondary source, and returns a `CrossCheckReport`. It has NO return
path that produces a `Panel`, a price frame, an eligibility mask, or a security
master. There is therefore no code path by which a secondary reading can reach a
universe filter -- the capability does not exist, so it cannot be misused under
deadline pressure by someone who has forgotten this rule.

The check is genuinely useful and genuinely powerless. It answers "does an
independent vendor agree with the prices we are about to run an experiment on?",
which catches adjustment errors, bad ticks and mis-stitched histories that a
single source cannot reveal about itself. What it must never do is silently
repair them: a disagreement is a fact to investigate, not a value to substitute.

WHAT A DISAGREEMENT MEANS

Compared on RETURNS, not levels. Two vendors routinely differ in adjustment
vintage, which rescales an entire level series by a constant and cancels in a
return. Comparing levels would report a wall of false disagreements and train
everyone to ignore the report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import pandas as pd

from apex.contracts import Panel

# Vendors differ in the last basis point through rounding. A daily return
# discrepancy above this is a real disagreement worth a human look.
RETURN_TOLERANCE = 1e-3


class NotWired(NotImplementedError):
    """A secondary adapter exists as a contract but has no live connection."""


@runtime_checkable
class SecondarySource(Protocol):
    """Prices only. Deliberately has no identity, shares or fundamentals surface.

    A secondary source CANNOT supply shares outstanding, market cap, security
    category, exchange, or delisting information, because this protocol declares
    no method to return any of them. The restriction is in the type, not in a
    convention someone has to remember.
    """

    @property
    def name(self) -> str: ...

    def close_adjusted(self) -> pd.DataFrame:
        """Wide frame: index dates, columns matching the authoritative panel's
        security_id axis. Anything unmatched is simply not compared."""
        ...


@dataclass(frozen=True)
class Disagreement:
    security_id: str
    n_compared: int
    n_disagreeing: int
    max_abs_return_diff: float

    @property
    def rate(self) -> float:
        return self.n_disagreeing / self.n_compared if self.n_compared else 0.0


@dataclass(frozen=True)
class CrossCheckReport:
    """Findings only. Carries no data that could be substituted into a panel."""

    secondary_name: str
    securities_compared: int
    securities_unmatched: int
    observations_compared: int
    disagreements: tuple
    tolerance: float

    @property
    def clean(self) -> bool:
        return not self.disagreements

    def as_dict(self) -> dict:
        return {
            "secondary_name": self.secondary_name,
            "securities_compared": self.securities_compared,
            "securities_unmatched": self.securities_unmatched,
            "observations_compared": self.observations_compared,
            "securities_disagreeing": len(self.disagreements),
            "worst": [
                {
                    "security_id": d.security_id,
                    "disagreement_rate": round(d.rate, 4),
                    "max_abs_return_diff": round(d.max_abs_return_diff, 6),
                }
                for d in sorted(
                    self.disagreements, key=lambda d: d.rate, reverse=True
                )[:10]
            ],
            "tolerance": self.tolerance,
            "authority": (
                "Sharadar governs. This report is diagnostic only; no value here "
                "may be substituted into a panel or into any universe filter "
                "(CONVENTIONS A-002)."
            ),
        }

    def explain(self) -> str:
        if self.clean:
            return (
                f"cross-check against {self.secondary_name}: "
                f"{self.observations_compared} observations across "
                f"{self.securities_compared} securities, no disagreements"
            )
        worst = max(self.disagreements, key=lambda d: d.rate)
        return (
            f"cross-check against {self.secondary_name}: "
            f"{len(self.disagreements)} of {self.securities_compared} securities "
            f"disagree beyond {self.tolerance:g}; worst is {worst.security_id} at "
            f"{worst.rate:.1%} of days. Sharadar governs -- investigate, do not "
            f"substitute."
        )


def cross_check(
    authoritative: Panel,
    secondary: SecondarySource,
    tolerance: float = RETURN_TOLERANCE,
) -> CrossCheckReport:
    """Compare an independent vendor's prices against the authoritative panel.

    Returns findings. There is deliberately no variant of this function that
    returns corrected data.
    """
    if secondary is None:
        raise NotWired(
            "no secondary source supplied. The cross-check is OPTIONAL "
            "(CONVENTIONS A-002) -- the experiment runs on Sharadar alone. Call "
            "this only when a secondary export is actually available."
        )

    other = secondary.close_adjusted()
    shared_securities = authoritative.securities.intersection(other.columns)
    shared_dates = authoritative.dates.intersection(other.index)

    left = authoritative.close_adj.loc[shared_dates, shared_securities].pct_change()
    right = other.loc[shared_dates, shared_securities].pct_change()

    diff = (left - right).abs()
    comparable = left.notna() & right.notna()

    findings: list[Disagreement] = []
    for security in shared_securities:
        mask = comparable[security]
        n = int(mask.sum())
        if not n:
            continue
        values = diff.loc[mask, security]
        bad = int((values > tolerance).sum())
        if bad:
            findings.append(
                Disagreement(
                    security_id=str(security),
                    n_compared=n,
                    n_disagreeing=bad,
                    max_abs_return_diff=float(values.max()),
                )
            )

    return CrossCheckReport(
        secondary_name=secondary.name,
        securities_compared=len(shared_securities),
        securities_unmatched=len(authoritative.securities) - len(shared_securities),
        observations_compared=int(comparable.to_numpy().sum()),
        disagreements=tuple(findings),
        tolerance=tolerance,
    )


class NorgateSecondary:
    """Optional Norgate price export, for cross-check only.

    NOT WIRED. Norgate's updater is Windows-only and this repository runs on
    macOS. The class exists so the seam is real and typed; it raises rather than
    returning empty frames, because an adapter that silently yields nothing is
    indistinguishable from a vendor outage and would turn a missing feed into a
    silently unverified panel.

    Note what this class CANNOT do, by construction: it satisfies
    `SecondarySource`, which exposes prices alone. It has no way to contribute
    shares outstanding, market cap, identity or delisting data, and therefore no
    way to influence a universe filter.
    """

    name = "norgate"

    def __init__(self, export_root=None) -> None:
        self.export_root = export_root

    def close_adjusted(self) -> pd.DataFrame:
        raise NotWired(
            "the Norgate secondary source is not wired.\n"
            "  Norgate Data Updater is Windows-only and this repository runs on "
            "macOS.\n"
            "  Supply a dividend-adjusted close export (dates x security_id) and "
            "implement this method against it.\n"
            "  Nothing depends on it: Sharadar is authoritative for every filter "
            "(CONVENTIONS A-002), and the cross-check is optional."
        )


__all__ = [
    "CrossCheckReport",
    "Disagreement",
    "NorgateSecondary",
    "NotWired",
    "SecondarySource",
    "cross_check",
    "RETURN_TOLERANCE",
]
