"""ROSTER MULTIPLICITY — the family of families is also a hypothesis.

PREDECLARED 2026-08-25, BEFORE ANY CAMPAIGN #003 OUTCOME EXISTS.

Campaign #002 closed the rebirth channel for ONE family. But per-
family control does not control the number of different families a
research factory can generate: give every family a fresh lifetime
budget and you are back to "run enough families until something
survives" -- the same laundering, one level up.

THE METHOD: hierarchical alpha-spending, respecting the hierarchy
MECHANISM -> FAMILY -> SPEC, valid under arbitrary dependence (a
spending schedule never pretends dependent hypotheses are
independent -- it simply bounds what the whole tree may claim):

    ALPHA_GLOBAL = 0.10          the research programme's lifetime
    mechanism m (1-indexed by first-test order)
        receives ALPHA_GLOBAL * 2^-m
    family j within its mechanism (1-indexed by first-test order)
        receives the mechanism share * 2^-j
    attempt k within its family
        spends the family share * 2^-k

Every level is a bounded series, so the ENTIRE EVOLVING ROSTER --
however many mechanisms and families are ever invented -- can claim
at most ALPHA_GLOBAL of false-discovery probability, forever. Later
mechanisms are more expensive by construction: research opportunity
is consumed, not printed. With the capped null budget this also
means the roster has a finite horizon of askable questions; that is
the design, not a bug.

ROSTER NEGATIVE CONTROLS: synthetic nonsense families run through
the IDENTICAL birth + sequential process on a separate control
roster, measuring false families / mechanisms / descendants
admitted. Hallucination is reported at THREE levels -- spec, family,
mechanism -- never pooled, because pooling is how a hierarchy hides
its weakest level.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apex.chronos.clock import ChronosViolation
from apex.chronos.sequential import MAX_NULL_BUDGET

ALPHA_GLOBAL = 0.10
PREDECLARED_ROSTER = ("2026-08-25 before any Campaign #003 outcome "
                      "existed")


def hierarchical_alpha(*, mechanism_order: int, family_order: int,
                       attempt: int) -> float:
    """The alpha one attempt may spend, from its position in the tree.
    Order indices are assigned by FIRST-TEST TIME and never reassigned
    -- re-sorting the tree to give a favorite idea an earlier, cheaper
    slot would be the laundering this exists to stop."""
    for name, v in (("mechanism_order", mechanism_order),
                    ("family_order", family_order),
                    ("attempt", attempt)):
        if not isinstance(v, int) or v < 1:
            raise ChronosViolation(f"{name} must be a positive "
                                   f"integer, got {v!r}")
    return (ALPHA_GLOBAL * (0.5 ** mechanism_order)
            * (0.5 ** family_order) * (0.5 ** attempt))


def roster_null_budget(alpha_required: float) -> int | None:
    """Null budget from the preregistered ladder {100, 320}; None when
    even the maximum cannot resolve the required tail (the caller
    then records TEST_NOT_ESTIMABLE and consults closure -- never a
    bigger ad-hoc budget)."""
    if alpha_required >= 1.0 / 101:
        return 100
    if alpha_required >= 1.0 / (MAX_NULL_BUDGET + 1):
        return MAX_NULL_BUDGET
    return None


@dataclass
class HypothesisRoster:
    """Persistent roster accounting. A new family consumes research
    opportunity; the calendar never refunds it."""
    label: str
    mechanism_order: dict = field(default_factory=dict)
    family_order: dict = field(default_factory=dict)     # fid -> (mech, j)
    family_state: dict = field(default_factory=dict)
    families_of_mech: dict = field(default_factory=dict)

    def register_attempt_position(self, *, mechanism: str,
                                  family: str) -> dict:
        """Assign (or recall) the tree position. First-test order is
        permanent."""
        if mechanism not in self.mechanism_order:
            self.mechanism_order[mechanism] = \
                len(self.mechanism_order) + 1
        if family not in self.family_order:
            sibs = self.families_of_mech.setdefault(mechanism, [])
            sibs.append(family)
            self.family_order[family] = (mechanism, len(sibs))
            self.family_state[family] = {
                "attempts": 0, "admitted": 0, "failed": 0,
                "closed": False, "mechanism": mechanism}
        m = self.mechanism_order[mechanism]
        _mech, j = self.family_order[family]
        st = self.family_state[family]
        st["attempts"] += 1
        k = st["attempts"]
        alpha = hierarchical_alpha(mechanism_order=m, family_order=j,
                                   attempt=k)
        budget = roster_null_budget(alpha)
        if budget is None and not st["closed"]:
            st["closed"] = True
        return {"kind": "roster_position", "roster": self.label,
                "mechanism": mechanism, "mechanism_order": m,
                "family": family, "family_order": j, "attempt": k,
                "alpha": alpha, "null_budget": budget,
                "family_closed": st["closed"],
                "closure_reason": ("SEQUENTIAL_BUDGET_EXHAUSTED"
                                   if st["closed"] else None),
                "decision_power": "NONE_RESEARCH"}

    def record_outcome(self, *, family: str, admitted: bool) -> None:
        st = self.family_state.get(family)
        if st is None:
            raise ChronosViolation(
                f"unknown family {family!r}: an outcome without a "
                f"registered attempt is a book being cooked")
        st["admitted" if admitted else "failed"] += 1

    def accounting(self) -> dict:
        fams = self.family_state
        return {"kind": "roster_accounting", "roster": self.label,
                "mechanisms_ever_tested": len(self.mechanism_order),
                "families_ever_born": len(fams),
                "families_currently_active": sum(
                    1 for s in fams.values()
                    if s["admitted"] > s["failed"] and not s["closed"]),
                "families_failed": sum(1 for s in fams.values()
                                       if s["failed"] and
                                       not s["admitted"]),
                "families_closed": sum(1 for s in fams.values()
                                       if s["closed"]),
                "total_attempts": sum(s["attempts"]
                                      for s in fams.values()),
                "law": "a new family consumes research opportunity; "
                       "no unlimited fresh family budgets",
                "decision_power": "NONE_RESEARCH"}


def three_level_hallucination(*, control_roster: HypothesisRoster,
                              control_admissions: list) -> dict:
    """Hallucination at SPEC, FAMILY and MECHANISM level, separately.

    control_admissions: [{"spec_admitted": bool,
                          "family": str, "mechanism": str}, ...]
    drawn from nonsense families pushed through the identical
    process. Pooling is refused by construction: three numbers, three
    denominators."""
    acct = control_roster.accounting()
    n_attempts = acct["total_attempts"]
    if n_attempts == 0:
        return {"kind": "three_level_hallucination",
                "verdict": "NO_CONTROLS_RUN",
                "why": "an unmeasured roster is not a clean one",
                "decision_power": "NONE_RESEARCH"}
    spec_hits = sum(1 for a in control_admissions
                    if a.get("spec_admitted"))
    fam_hit = {a["family"] for a in control_admissions
               if a.get("spec_admitted")}
    mech_hit = {a["mechanism"] for a in control_admissions
                if a.get("spec_admitted")}
    n_fams = max(acct["families_ever_born"], 1)
    n_mechs = max(acct["mechanisms_ever_tested"], 1)
    return {"kind": "three_level_hallucination",
            "SPEC_HALLUCINATION_RATE": round(spec_hits / n_attempts, 4),
            "spec_hits": spec_hits, "spec_attempts": n_attempts,
            "FAMILY_HALLUCINATION_RATE": round(len(fam_hit) / n_fams, 4),
            "false_families_admitted": sorted(fam_hit),
            "families_tested": n_fams,
            "MECHANISM_HALLUCINATION_RATE": round(
                len(mech_hit) / n_mechs, 4),
            "false_mechanisms_admitted": sorted(mech_hit),
            "mechanisms_tested": n_mechs,
            "verdict": ("ROSTER_MULTIPLICITY_CONTROL_FAILED"
                        if fam_hit else
                        "ROSTER_MULTIPLICITY_CONTROLLED"),
            "law": "three numbers, three denominators; pooling is how "
                   "a hierarchy hides its weakest level",
            "predeclared": PREDECLARED_ROSTER,
            "decision_power": "NONE_RESEARCH"}
