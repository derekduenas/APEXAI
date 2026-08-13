"""Redundancy detection. Make duplication VISIBLE; never delete automatically.

The f1_mom_63 / f4_vs_market identity proved that semantic names are not a
control: two registered components were rank-identical by construction and
nothing noticed. This module notices, at two levels:

  STRUCTURAL   compares registry descriptors, before anything is computed. It
               catches identical formulas and algebraically equivalent ones (a
               ratio and its reciprocal, the same growth measure written twice).

  EMPIRICAL    compares computed feature frames cross-sectionally: rank-identical
               transformations, features differing only by a per-date scalar,
               and merely-correlated pairs.

The distinction the brief insists on is preserved throughout:

  IDENTICAL INFORMATION   same formula, or rank-identical, or per-date-scalar
                          apart -- these are the SAME feature wearing two names.
  CORRELATED INFORMATION  high |rho| but not identical -- economically related,
                          legitimately distinct, and NOT flagged for removal.

Nothing here computes a forward return or ranks features by performance.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

# A per-date scalar difference cannot change a cross-sectional rank; this is the
# exact mechanism behind f1_mom_63 / f4_vs_market. "Identical" means rho at or
# above this; below CORRELATED_FLOOR features are reported as merely related.
RANK_IDENTICAL = 0.9999
CORRELATED_FLOOR = 0.50


@dataclass(frozen=True)
class RedundancyFinding:
    left: str
    right: str
    kind: str          # identical_formula | algebraic_equivalent | rank_identical
                       # | per_date_scalar | correlated
    detail: str

    def is_identical_information(self) -> bool:
        return self.kind in (
            "identical_formula", "algebraic_equivalent",
            "rank_identical", "per_date_scalar",
        )


# ---------------------------------------------------------------------------
# STRUCTURAL -- descriptor comparison, no data required
# ---------------------------------------------------------------------------


def _normalise(formula: dict) -> tuple:
    """A canonical, comparable form of a descriptor.

    Two descriptors that normalise equal define the same feature. Ratios are
    order-normalised so num/den and its explicit duplicate collide; a
    subtraction inside the numerator keeps its order because a-b != b-a.
    """
    kind = formula["kind"]
    if kind == "ratio":
        num = (formula.get("num"), formula.get("num_op"), formula.get("num2"))
        return ("ratio", num, formula.get("den"))
    if kind in ("growth", "log_ratio"):
        return (kind, formula.get("field"), formula.get("quarters"))
    if kind in ("valuation", "scaled_flow"):
        return (kind, formula.get("num"), formula.get("sign", 1))
    if kind == "price":
        return ("price", formula.get("op"))
    return (kind,)


def structural_findings(specs) -> list[RedundancyFinding]:
    findings: list[RedundancyFinding] = []
    items = list(specs)
    for a, b in combinations(items, 2):
        na, nb = _normalise(a.formula), _normalise(b.formula)
        if na == nb:
            findings.append(RedundancyFinding(
                a.feature_id, b.feature_id, "identical_formula",
                f"both normalise to {na}",
            ))
            continue
        # reciprocal ratios: num/den vs den/num, no subtraction on either side.
        if (a.formula.get("kind") == b.formula.get("kind") == "ratio"
                and a.formula.get("num_op") is None
                and b.formula.get("num_op") is None
                and a.formula.get("num") == b.formula.get("den")
                and a.formula.get("den") == b.formula.get("num")):
            findings.append(RedundancyFinding(
                a.feature_id, b.feature_id, "algebraic_equivalent",
                "reciprocal ratios carry the same cross-sectional information",
            ))
    return findings


# ---------------------------------------------------------------------------
# EMPIRICAL -- computed frames, cross-sectional, no returns
# ---------------------------------------------------------------------------


def _mean_rank_corr(a: pd.DataFrame, b: pd.DataFrame, eligible: pd.DataFrame) -> float:
    ra = a.where(eligible).rank(axis=1)
    rb = b.where(eligible).rank(axis=1)
    mask = ra.notna() & rb.notna()
    ra, rb = ra.where(mask), rb.where(mask)
    da = ra.sub(ra.mean(axis=1), axis=0)
    db = rb.sub(rb.mean(axis=1), axis=0)
    num = (da * db).sum(axis=1)
    den = np.sqrt((da**2).sum(axis=1) * (db**2).sum(axis=1))
    per_date = (num / den.where(den > 0)).dropna()
    return float(per_date.mean()) if len(per_date) else float("nan")


def _differs_by_per_date_scalar(a: pd.DataFrame, b: pd.DataFrame,
                                eligible: pd.DataFrame) -> bool:
    """True if a - b is (numerically) constant across securities each date.

    This is the f1_mom_63 / f4_vs_market signature: two features that are the
    same underlying quantity minus a per-date benchmark. Checked on raw values,
    not ranks, so it is a stronger statement than rank-identity.
    """
    diff = (a - b).where(eligible)
    spread = diff.max(axis=1) - diff.min(axis=1)
    scale = a.where(eligible).abs().median(axis=1).replace(0, np.nan)
    rel = (spread / scale).dropna()
    return bool(len(rel)) and bool((rel < 1e-9).mean() > 0.99)


def _corr_from_ranks(ra: pd.DataFrame, rb: pd.DataFrame) -> float:
    mask = ra.notna() & rb.notna()
    xa, xb = ra.where(mask), rb.where(mask)
    da = xa.sub(xa.mean(axis=1), axis=0)
    db = xb.sub(xb.mean(axis=1), axis=0)
    num = (da * db).sum(axis=1)
    den = np.sqrt((da**2).sum(axis=1) * (db**2).sum(axis=1))
    per_date = (num / den.where(den > 0)).dropna()
    return float(per_date.mean()) if len(per_date) else float("nan")


def correlation_matrix(
    frames: dict[str, pd.DataFrame], eligible: pd.DataFrame
) -> dict[tuple[str, str], float]:
    """Every pairwise mean rank correlation, ranks computed ONCE.

    Shared by `empirical_findings` and any caller that needs the matrix (e.g.
    dimension clustering), so the frames are not re-ranked per consumer.
    """
    names = sorted(frames)
    ranked = {n: frames[n].reindex_like(eligible).where(eligible).rank(axis=1)
              for n in names}
    return {(a, b): _corr_from_ranks(ranked[a], ranked[b])
            for a, b in combinations(names, 2)}


def empirical_findings(
    frames: dict[str, pd.DataFrame],
    eligible: pd.DataFrame,
    corr: dict[tuple[str, str], float] | None = None,
) -> list[RedundancyFinding]:
    findings: list[RedundancyFinding] = []
    corr = corr or correlation_matrix(frames, eligible)
    for (a, b), rho in corr.items():
        # The per-date-scalar check is the expensive one (raw-value subtraction
        # over the whole frame). A per-date scalar difference always produces a
        # near-perfect rank correlation, so only run it when rho warrants.
        if abs(rho) >= RANK_IDENTICAL and _differs_by_per_date_scalar(
            frames[a].reindex_like(eligible), frames[b].reindex_like(eligible),
            eligible,
        ):
            findings.append(RedundancyFinding(
                a, b, "per_date_scalar",
                f"differ only by a per-date scalar; rank rho {rho:+.4f}",
            ))
        elif rho >= RANK_IDENTICAL:
            findings.append(RedundancyFinding(
                a, b, "rank_identical",
                f"cross-sectional rank rho {rho:+.4f}",
            ))
        elif abs(rho) >= CORRELATED_FLOOR:
            findings.append(RedundancyFinding(
                a, b, "correlated",
                f"rank rho {rho:+.4f} -- related, NOT flagged for removal",
            ))
    return findings


def summarise(findings: list[RedundancyFinding]) -> dict:
    identical = [f for f in findings if f.is_identical_information()]
    correlated = [f for f in findings if f.kind == "correlated"]
    return {
        "identical_information": [
            {"left": f.left, "right": f.right, "kind": f.kind, "detail": f.detail}
            for f in identical
        ],
        "correlated_information": [
            {"left": f.left, "right": f.right, "detail": f.detail}
            for f in correlated
        ],
        "n_identical": len(identical),
        "n_correlated": len(correlated),
    }
