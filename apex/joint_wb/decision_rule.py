"""JOINT_DECISION_RULE_V1 (contract §5.3, as amended and accepted).

Ranking is computed WITHOUT size under ASSUME_AVAILABLE, so no candidate can be promoted by another's size
penalty. The selected candidate alone is then re-evaluated under MODELLED_SIZE and can only VETO to WAIT — never
rerank, never substitute. Rules 1 and 4 form an INTERSECTION: adding a gate can only shrink the trade set, which
is conservative for the TRADE decision but is NOT simultaneous coverage across both gate families."""
from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

ALPHA = 0.05
RUNNER_UP_SE = 1.0
U_FRACTION = 0.25
AVAILABILITY_MAX = 0.05
VETO_COMPARATORS = ("C_EXEC", "C_DIAG", "JOINT")
GATES_LABEL = ("GATES_INTERSECTION_NOT_SIMULTANEOUS_COVERAGE: rules 1 and 4 apply adjusted limits over the same 2m "
               "family to the same paths under two size policies; every gate must pass, so the procedure is "
               "conservative for the TRADE decision, but the reported intervals are not a calibrated simultaneous "
               "confidence set over their union")
HEURISTIC_LABEL = "HEURISTIC_SCREEN_NO_CONFIDENCE_CLAIM: a post-selection comparison on the same data"


def paired_se(a: np.ndarray, b: np.ndarray) -> float:
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    n = len(d)
    return float(d.std(ddof=1) / math.sqrt(n)) if n > 1 else float("inf")


def _z(m: int) -> float:
    return float(norm.ppf(1.0 - ALPHA / (2.0 * 2.0 * max(1, m))))


def decide(*, ranked: list, veto_eval=None, comparator: str = "JOINT", eligibility_census: dict | None = None,
           adverse: dict | None = None, prime=None) -> dict:
    """ranked: [{label, acct}] already ordered by acct['E_sel'] DESC, all computed under ASSUME_AVAILABLE.
    veto_eval: callable(label) -> accounting dict under MODELLED_SIZE, or None when the comparator has no veto."""
    m = len(ranked)
    trace = {"m": m, "labels": [GATES_LABEL], "rules": {}}
    if m == 0:
        trace["rules"]["0"] = {"pass": False, "why": "NO_ELIGIBLE_CANDIDATE", "census": eligibility_census or {}}
        return {"decision": "WAIT", "why": "NO_ELIGIBLE_CANDIDATE", "selected": None, "trace": trace}
    trace["rules"]["0"] = {"pass": True, "m": m}
    best = ranked[0]
    runner = ranked[1] if m > 1 else None
    z = _z(m)
    trace["multiplicity"] = {"family": 2 * m, "alpha": ALPHA, "z": z, "naive_z": 2.0,
                             "note": "Bonferroni over candidates x scenarios; naive figures are per SCENARIO, never attached to E_sel"}

    # rule 1: simultaneous over BOTH scenarios versus WAIT
    r1 = {"pass": True, "by_scenario": {}}
    for s in ("S1", "S2"):
        arr = best["acct"][s]
        se = paired_se(arr, np.zeros(len(arr)))
        mean = float(arr.mean())
        lcl = mean - z * se
        r1["by_scenario"][s] = {"mean": mean, "se_paired_vs_wait": se, "lower_limit": lcl,
                                "naive_2se_lower": mean - 2.0 * se, "pass": bool(lcl > 0)}
        if not lcl > 0:
            r1["pass"] = False; r1["first_failure"] = s
    trace["rules"]["1"] = r1
    if not r1["pass"]:
        return {"decision": "WAIT", "why": "MC_NOT_DISTINGUISHED_FROM_WAIT:%s" % r1["first_failure"], "selected": best["label"], "trace": trace}

    # rule 2: runner-up heuristic screen
    r2 = {"label": HEURISTIC_LABEL}
    if runner is None:
        r2.update(pass_=True, vacuous=True, why="SOLE_CANDIDATE")
        trace["rules"]["2"] = r2
    else:
        r2["by_scenario"] = {}; ok = True
        for s in ("S1", "S2"):
            d = float(best["acct"][s].mean() - runner["acct"][s].mean())
            se = paired_se(best["acct"][s], runner["acct"][s])
            tied = abs(d) < 1e-12
            passed = (not tied) and d > RUNNER_UP_SE * se
            r2["by_scenario"][s] = {"diff": d, "se_paired": se, "tied": tied, "pass": passed}
            if tied:
                r2["tied"] = True
            if not passed:
                ok = False
        r2["pass_"] = ok
        trace["rules"]["2"] = r2
        if not ok:
            why = "RANK_TIED" if r2.get("tied") else "RANK_UNCERTAIN"
            return {"decision": "WAIT", "why": why, "selected": best["label"], "trace": trace}

    # rule 3: adverse scenarios (ablations are recorded, never gates)
    r3 = {"pass": True, "scenarios": (adverse or {}).get("scenarios", {}), "ablations_recorded_not_gates": (adverse or {}).get("ablations", {})}
    for name, val in r3["scenarios"].items():
        if val is not None and not val > 0:
            r3["pass"] = False; r3["first_failure"] = name; break
    trace["rules"]["3"] = r3
    if not r3["pass"]:
        return {"decision": "WAIT", "why": "NOT_ROBUST_TO_ASSUMPTIONS:%s" % r3["first_failure"], "selected": best["label"], "trace": trace}

    # rule 4: accounting spread on the ranking value, then the selected-only veto
    r4 = {"U_rank": best["acct"]["U"], "E_sel_rank": best["acct"]["E_sel"],
          "pass_rank_spread": bool(best["acct"]["U"] <= U_FRACTION * abs(best["acct"]["E_sel"]))}
    trace["rules"]["4"] = r4
    if not r4["pass_rank_spread"]:
        return {"decision": "WAIT", "why": "EXIT_ACCOUNTING_UNCERTAIN", "selected": best["label"], "trace": trace}
    if comparator in VETO_COMPARATORS and veto_eval is not None:
        v = veto_eval(best["label"])
        r4["veto"] = {"applied": True, "comparator": comparator,
                      "policy": "SIZE_PROXY_V2 SELECT_THEN_VETO: veto to WAIT only, never rerank or substitute"}
        if v is None or v.get("refused"):
            r4["veto"].update(pass_=False, why="SIZE_VETO_UNDEFINED: %s" % (None if v is None else v.get("refused")))
            return {"decision": "WAIT", "why": "EXIT_LIQUIDITY_RISK", "selected": best["label"], "trace": trace}
        vb = {}
        ok = True
        for s in ("S1", "S2"):
            arr = v[s]
            se = paired_se(arr, np.zeros(len(arr)))
            mean = float(arr.mean())
            lcl = mean - z * se
            vb[s] = {"mean": mean, "se_paired_vs_wait": se, "lower_limit": lcl, "pass": bool(lcl > 0)}
            if not lcl > 0:
                ok = False; r4["veto"]["first_failure"] = s
        r4["veto"].update(by_scenario=vb, E_sel_veto=v["E_sel"], U_veto=v["U"],
                          availability_failure_rate=v["availability_failure_rate"])
        if not ok:
            return {"decision": "WAIT", "why": "SIZE_VETO_NOT_DISTINGUISHED_FROM_WAIT:%s" % r4["veto"]["first_failure"],
                    "selected": best["label"], "trace": trace}
        if not v["U"] <= U_FRACTION * abs(v["E_sel"]):
            return {"decision": "WAIT", "why": "EXIT_ACCOUNTING_UNCERTAIN", "selected": best["label"], "trace": trace}
        if not v["availability_failure_rate"] <= AVAILABILITY_MAX:
            return {"decision": "WAIT", "why": "EXIT_LIQUIDITY_RISK", "selected": best["label"], "trace": trace}
        r4["veto"]["pass_"] = True
    else:
        r4["veto"] = {"applied": False, "why": "comparator %s carries no size model" % comparator}

    # rule 5: PRIME
    if prime is not None:
        p = prime(best["label"])
        trace["rules"]["5"] = p
        if p.get("decision") != "ACT":
            return {"decision": "WAIT", "why": "PRIME_ABSTAIN: " + "; ".join(p.get("reasons", []))[:200],
                    "selected": best["label"], "trace": trace}
    else:
        trace["rules"]["5"] = {"decision": "NOT_SUPPLIED"}
    return {"decision": "TRADE", "why": "JOINT_SELECTED: %s E_sel %.4f (ranking, ASSUME_AVAILABLE)" % (best["label"], best["acct"]["E_sel"]),
            "selected": best["label"], "trace": trace}
