"""LIFETIME HYPOTHESIS IDENTITY — a new id does not create a new idea.

Campaign #001's core finding: within-epoch false-discovery control
held, but the organism birthed 51 "discoveries" that were mostly the
same marginal hypothesis reborn monthly. It knew "this month's
candidate passed this month's hurdle"; it did not know "I have already
tested this economic idea repeatedly." This module is that memory.

THREE IDENTITIES, coarse to fine:

  SPEC_ID       exact immutable specification (every knob).
  FAMILY_ID     economically equivalent variants: same variables,
                direction, horizon, payoff, threshold family --
                PARAMETER DRIFT DOES NOT ESCAPE THE FAMILY. RS>0.62
                vs RS>0.63, lookback 19 vs 20: same idea.
  MECHANISM_ID  the declared causal mechanism under test. Several
                implementations may probe one mechanism.

EQUIVALENCE IS CONSERVATIVE. Where deterministic rules cannot
establish that two specs are distinct ideas, the verdict is
UNKNOWN_EQUIVALENCE -- never NEW_INDEPENDENT_HYPOTHESIS. The organism
does not get the benefit of the doubt about its own originality.

FAILURE HISTORY IS INFORMATION. The calendar does not erase failed
hypotheses. Descendants inherit zero confirmatory evidence and one
hundred percent of the visible failure record.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from apex.chronos.clock import ChronosViolation

NOT_ESTIMABLE = "NOT_ESTIMABLE"

BIRTH_CLASSES = ("NEW_FAMILY", "CLONE_BLOCKED", "DESCENDANT",
                 "UNKNOWN_EQUIVALENCE")

# fields whose exact values define the SPEC but whose drift does NOT
# create a new family
FAMILY_DEFINING = ("variables", "direction", "horizon",
                   "payoff_definition", "threshold_family")

LIFETIME_COUNTERS = (
    "spec_tests_lifetime", "family_tests_lifetime",
    "mechanism_tests_lifetime", "descendants_lifetime",
    "discovery_failures", "validation_failures",
    "sealed_test_failures", "prospective_failures", "null_results")


def _h(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def spec_id(spec: dict) -> str:
    return "SPEC_" + _h(spec)


def family_id(spec: dict) -> str:
    """Deterministic family identity: the family-defining fields with
    variables as an unordered set. Everything else -- exact
    thresholds, lookbacks, minor parameters -- is drift inside the
    family, not a new idea."""
    missing = [f for f in FAMILY_DEFINING if f not in spec]
    if missing:
        raise ChronosViolation(
            f"family identity requires {missing}: a spec that cannot "
            f"state what idea it is cannot claim to be a new one")
    key = {f: (sorted(spec[f]) if f == "variables" else spec[f])
           for f in FAMILY_DEFINING}
    return "FAM_" + _h(key)


def mechanism_id(mechanism_statement: str) -> str:
    """The declared causal mechanism, normalized. Declaring one is
    mandatory: a hypothesis that cannot say WHY it should work is not
    a hypothesis, it is a pattern with ambitions."""
    norm = " ".join(str(mechanism_statement).lower().split())
    if len(norm) < 20:
        raise ChronosViolation(
            "a mechanism statement under 20 characters is a label, "
            "not a causal claim")
    return "MECH_" + _h(norm)


@dataclass
class LifetimeLedger:
    """The scientist's memory of everything it has already tried.

    Keyed at all three identity levels. Append-only counters; a new
    month never resets them."""
    specs: dict = field(default_factory=dict)
    families: dict = field(default_factory=dict)
    mechanisms: dict = field(default_factory=dict)

    def _bucket(self, store, key):
        return store.setdefault(key, {c: 0 for c in LIFETIME_COUNTERS}
                                | {"active": None, "retired": [],
                                   "attempts": []})

    def classify_birth(self, *, spec: dict, mechanism: str,
                       at: str) -> dict:
        """What IS this candidate, relative to everything tried before?

        CLONE_BLOCKED: the family already has an ACTIVE edge -- the
        same idea may not run twice concurrently under two names.
        DESCENDANT: the family exists (retired or previously tested);
        a materially changed spec attaches to the lineage with prior
        failures visible and zero inherited evidence.
        NEW_FAMILY: genuinely unseen family identity."""
        sid, fid = spec_id(spec), family_id(spec)
        mid = mechanism_id(mechanism)
        fam = self.families.get(fid)
        if fam is None:
            cls = "NEW_FAMILY"
            why = "no prior test of this family identity on record"
        elif fam["active"]:
            cls = "CLONE_BLOCKED"
            why = (f"family {fid} already has active edge "
                   f"{fam['active']}: the same idea may not run "
                   f"concurrently under two names")
        else:
            cls = "DESCENDANT"
            why = (f"family {fid} was tested "
                   f"{fam['family_tests_lifetime']} time(s) before; "
                   f"this is attempt "
                   f"{fam['family_tests_lifetime'] + 1}, carrying "
                   f"{fam['discovery_failures']} discovery, "
                   f"{fam['validation_failures']} validation and "
                   f"{fam['sealed_test_failures']} sealed-test "
                   f"failures in full view")
        return {"kind": "birth_classification", "at": at,
                "classification": cls, "why": why,
                "spec_id": sid, "family_id": fid, "mechanism_id": mid,
                "family_attempt_number": (
                    (fam["family_tests_lifetime"] + 1) if fam else 1),
                "debt": self.debt(family=fid, mechanism=mid),
                "law": "a new id does not create a new idea",
                "decision_power": "NONE_RESEARCH"}

    def record_attempt(self, *, spec: dict, mechanism: str, at: str,
                       outcome: str, edge_id: str | None = None
                       ) -> None:
        """outcome: DISCOVERY_FAILURE | VALIDATION_FAILURE |
        BIRTHED | SEALED_TEST_FAILURE | PROSPECTIVE_FAILURE |
        NULL_RESULT | RETIRED"""
        sid, fid = spec_id(spec), family_id(spec)
        mid = mechanism_id(mechanism)
        for store, key in ((self.specs, sid), (self.families, fid),
                           (self.mechanisms, mid)):
            b = self._bucket(store, key)
            if outcome in ("DISCOVERY_FAILURE", "VALIDATION_FAILURE",
                           "BIRTHED", "NULL_RESULT"):
                cname = {"DISCOVERY_FAILURE": "discovery_failures",
                         "VALIDATION_FAILURE": "validation_failures",
                         "NULL_RESULT": "null_results",
                         "BIRTHED": None}[outcome]
                b["spec_tests_lifetime" if store is self.specs else
                  "family_tests_lifetime" if store is self.families
                  else "mechanism_tests_lifetime"] += 1
                if cname:
                    b[cname] += 1
            elif outcome == "SEALED_TEST_FAILURE":
                b["sealed_test_failures"] += 1
            elif outcome == "PROSPECTIVE_FAILURE":
                b["prospective_failures"] += 1
            elif outcome == "RETIRED":
                pass
            else:
                raise ChronosViolation(
                    f"unknown attempt outcome {outcome!r}")
            b["attempts"].append({"at": at, "outcome": outcome,
                                  "edge_id": edge_id})
            if outcome == "BIRTHED":
                if store is self.families and b["active"]:
                    raise ChronosViolation(
                        f"family {key} already has active edge "
                        f"{b['active']}; a clone birth slipped past "
                        f"classification")
                if store is self.families:
                    b["active"] = edge_id
                    if b["family_tests_lifetime"] > 1:
                        b["descendants_lifetime"] += 1
            if outcome == "RETIRED" and store is self.families:
                b["retired"].append(edge_id)
                b["active"] = None
            if outcome == "SEALED_TEST_FAILURE" and \
                    store is self.families:
                pass

    def debt(self, *, family: str, mechanism: str) -> dict:
        """HYPOTHESIS DEBT: permanently visible negative evidence.
        Deliberately NOT collapsed to one number -- a magic scalar
        would immediately become a dial. Self-Critic cites this when
        the organism says 'Family 042 looks exciting!'"""
        f = self.families.get(family,
                              {c: 0 for c in LIFETIME_COUNTERS})
        m = self.mechanisms.get(mechanism,
                                {c: 0 for c in LIFETIME_COUNTERS})
        return {"kind": "hypothesis_debt",
                "family": family, "mechanism": mechanism,
                "family_prior_nulls": f["null_results"],
                "family_discovery_failures": f["discovery_failures"],
                "family_validation_failures": f["validation_failures"],
                "family_sealed_test_failures":
                    f["sealed_test_failures"],
                "family_prospective_failures":
                    f["prospective_failures"],
                "family_descendants": f["descendants_lifetime"],
                "mechanism_tests": m["mechanism_tests_lifetime"],
                "mechanism_failures_all_kinds": (
                    m["discovery_failures"] + m["validation_failures"]
                    + m["sealed_test_failures"]
                    + m["prospective_failures"]),
                "law": "every failure makes the next claim harder, "
                       "not easier; the calendar does not erase "
                       "failed hypotheses",
                "decision_power": "NONE_RESEARCH"}

    def as_record(self) -> dict:
        return {"kind": "lifetime_ledger",
                "unique_specs": len(self.specs),
                "unique_families": len(self.families),
                "unique_mechanisms": len(self.mechanisms),
                "families": {k: {c: v[c] for c in LIFETIME_COUNTERS}
                             | {"active": v["active"],
                                "retired": v["retired"]}
                             for k, v in self.families.items()},
                "decision_power": "NONE_RESEARCH"}
