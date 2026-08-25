"""COUNTERFACTUAL MULTIVERSE — analog worlds first, stress worlds always.

V0 deliberately begins with the most defensible world generator there
is: REALITY. For a current state, find historically similar PRE-states
-- similarity computed only from what was knowable at each historical T
-- and let the actual subsequent paths of those analogs be the world
branches. EMPIRICAL_MULTIVERSE_V0 establishes a reality anchor before
any model capable of hallucinating persuasive fake markets is allowed
in the building.

ANALOG LAW
    Membership is fixed by pre-state similarity alone. Futures are
    revealed only after membership is fixed. The API enforces this
    ordering structurally: selection never sees a future, and famous
    episodes get no special treatment -- a date is an analog because
    its morning looked similar, never because we remember its
    afternoon.

ADVERSARIAL WORLDS answer a different question -- not "what is likely"
but "does the edge survive plausible degradation" -- and are labelled
ADVERSARIAL_STRESS so no one can later mistake a stress test for a
probability claim.

Branch weights are UNWEIGHTED or UNCALIBRATED. A branch fraction is a
fraction of worlds, not a probability, until calibration is earned.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"

GENERATION_METHODS = ("EMPIRICAL_HISTORICAL_ANALOG", "ADVERSARIAL_STRESS")
WEIGHT_STATUSES = ("UNWEIGHTED", "UNCALIBRATED")


class MultiverseViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class WorldBranch:
    branch_id: str
    parent_state_hash: str
    hypothesis_condition: str            # or "UNCONDITIONED_EMPIRICAL"
    generation_method: str
    generation_pedigree: str
    path: tuple                          # ((t_offset_min, price), ...)
    liquidity_path: tuple = ()
    volatility_path: tuple = ()
    events: tuple = ()
    branch_weight_status: str = "UNWEIGHTED"
    source_session: str | None = None

    def __post_init__(self):
        if self.generation_method not in GENERATION_METHODS:
            raise MultiverseViolation(
                f"unknown generation method {self.generation_method!r}")
        if self.branch_weight_status not in WEIGHT_STATUSES:
            raise MultiverseViolation(
                f"branch weights are {WEIGHT_STATUSES} until calibration "
                f"is earned; {self.branch_weight_status!r} is a fake "
                f"probability wearing a status")
        if not self.path:
            raise MultiverseViolation("a world with no path is not a world")

    def as_record(self) -> dict:
        return {"kind": "world_branch", **asdict(self)}


# ------------------------------------------------------------- analogs

@dataclass(frozen=True)
class AnalogMatch:
    session: str
    distance: float
    feature_coverage: float
    features: dict


def select_analogs(*, current_features: dict, candidates: dict,
                   k: int = 40, min_coverage: float = 0.8) -> dict:
    """Fix analog membership from PRE-STATE features only.

    `candidates` maps session -> pre-state feature dict. This function
    cannot leak the future because no future is passed to it -- the
    causal ordering is the signature, not a promise. Distances are
    z-normalized per feature across the candidate pool so no single
    scale dominates."""
    names = sorted(current_features)
    if not names:
        raise MultiverseViolation("no features: similarity undefined")

    # per-feature normalization stats from the candidate pool
    stats = {}
    for n in names:
        vals = [c[n] for c in candidates.values()
                if isinstance(c.get(n), (int, float))]
        if len(vals) >= 2:
            mu = sum(vals) / len(vals)
            sd = math.sqrt(sum((v - mu) ** 2 for v in vals)
                           / (len(vals) - 1)) or 1.0
            stats[n] = (mu, sd)

    matches = []
    for sess, feats in candidates.items():
        used, d2 = 0, 0.0
        for n in names:
            v = feats.get(n)
            if not isinstance(v, (int, float)) or n not in stats:
                continue
            mu, sd = stats[n]
            d2 += ((v - mu) / sd - (current_features[n] - mu) / sd) ** 2
            used += 1
        cov = used / len(names)
        if cov < min_coverage:
            continue
        matches.append(AnalogMatch(
            session=sess, distance=round(math.sqrt(d2 / max(used, 1)), 6),
            feature_coverage=round(cov, 4), features=feats))

    matches.sort(key=lambda m: m.distance)
    chosen = matches[:k]
    sessions = {m.session for m in chosen}
    years = sorted({s[:4] for s in sessions})
    return {"kind": "analog_selection",
            "n_candidates": len(candidates),
            "n_raw": len(chosen),
            "n_effective_lower_bound": len(sessions),
            "unique_sessions": len(sessions),
            "years": years,
            "min_coverage": min_coverage,
            "features_used": names,
            "analogs": chosen,
            "law": "membership fixed by pre-state similarity alone; "
                   "futures revealed only after this record exists",
            "decision_power": "NONE_RESEARCH"}


def branches_from_analogs(*, selection: dict, futures: dict,
                          parent_state_hash: str) -> list:
    """Reveal the analogs' actual subsequent paths as world branches.

    `futures` maps session -> ((t_offset_min, price), ...). Sessions
    are looked up only AFTER selection is fixed; a session missing its
    future is dropped and reported, never silently substituted."""
    branches, missing = [], []
    for m in selection["analogs"]:
        path = futures.get(m.session)
        if not path:
            missing.append(m.session)
            continue
        bid = hashlib.sha256(
            f"{parent_state_hash}:{m.session}".encode()).hexdigest()[:16]
        branches.append(WorldBranch(
            branch_id=f"analog_{m.session}_{bid}",
            parent_state_hash=parent_state_hash,
            hypothesis_condition="UNCONDITIONED_EMPIRICAL",
            generation_method="EMPIRICAL_HISTORICAL_ANALOG",
            generation_pedigree=(
                f"actual market path of {m.session}; analog distance "
                f"{m.distance}, coverage {m.feature_coverage}"),
            path=tuple(tuple(p) for p in path),
            branch_weight_status="UNWEIGHTED",
            source_session=m.session))
    if missing:
        # dropped and REPORTED via the returned record, never silently
        # substituted -- a fabricated future would poison the multiverse
        return {"branches": branches, "missing_futures": sorted(missing),
                "note": f"{len(missing)} analog(s) lacked futures and "
                        f"were dropped"}
    return {"branches": branches, "missing_futures": [],
            "note": "all analog futures present"}


# -------------------------------------------------------- adversarial

STRESS_KINDS = ("ENTRY_SLIPPAGE", "SPREAD_WIDENING", "DELAYED_ENTRY",
                "SIGNAL_DECAY", "LIQUIDITY_WITHDRAWAL", "FALSE_BREAKOUT",
                "IV_CRUSH", "IV_EXPANSION", "GAP_THROUGH_INVALIDATION",
                "CORRELATION_SPIKE", "SECTOR_REVERSAL", "PARTIAL_FILL",
                "PROVIDER_LATENCY")


def adversarial_branch(*, base: WorldBranch, kind: str,
                       transform, note: str) -> WorldBranch:
    """One declared stress applied to one world. The stressed branch
    answers 'does the edge survive this degradation', and its pedigree
    says so -- it is never a probability claim about the market."""
    if kind not in STRESS_KINDS:
        raise MultiverseViolation(f"unknown stress kind {kind!r}")
    new_path = tuple(tuple(p) for p in transform(list(base.path)))
    return WorldBranch(
        branch_id=f"stress_{kind}_{base.branch_id}",
        parent_state_hash=base.parent_state_hash,
        hypothesis_condition=base.hypothesis_condition,
        generation_method="ADVERSARIAL_STRESS",
        generation_pedigree=(f"{kind} applied to {base.branch_id}: "
                             f"{note}. ADVERSARIAL_STRESS, not a "
                             f"market probability."),
        path=new_path,
        branch_weight_status="UNWEIGHTED",
        source_session=base.source_session)
