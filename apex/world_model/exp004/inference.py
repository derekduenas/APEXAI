"""EXP-004 inference, classification and multiplicity (R8-R10).

Integrity has precedence: an integrity failure or any registered refusal
produces INTEGRITY_FAILURE (or the specific refusal) and no statistical
classification. Otherwise SELECTED iff all four primary decisions pass;
NOT_SELECTED otherwise, with two INDEPENDENT flags recorded."""
from __future__ import annotations

import math

import numpy as np

from apex.world_model import inference as INF
from apex.world_model.exp002.run import _holm
from .registration import DECISION_RULE, INHERITED, PRIMARY, SECONDARY

DM_THRESHOLD = INHERITED["dm_threshold"]["value"]
BOOT_P_THRESHOLD = INHERITED["bootstrap"]["value"]["p_threshold"]
REQUIRED = tuple(DECISION_RULE["required"])          # HAC_D0, BOOT_D0, HAC_D1, BOOT_D1
SPECS = ("D0", "D1")
Z95 = 1.96


class InferenceRefused(ValueError):
    """Numerical invalidity inside inference: an integrity refusal, not a NOT_SELECTED."""


def hac_decision(d: list) -> dict:
    arr = np.asarray(list(d), dtype=float)
    if arr.size == 0 or not np.all(np.isfinite(arr)):
        raise InferenceRefused("NONFINITE_DIFFERENTIALS: %d non-finite of %d" % (int(arr.size - np.isfinite(arr).sum()), arr.size))
    s = INF.dm_hac_statistic(arr.tolist())
    for k in ("mean", "t", "hac_se"):
        if not math.isfinite(s[k]):
            raise InferenceRefused("NONFINITE_HAC_STATISTIC: %s" % k)
    passed = bool(s["mean"] > 0 and s["t"] > DM_THRESHOLD)
    return {"mean": s["mean"], "t": s["t"], "hac_se": s["hac_se"], "n": s["n"], "lag": s.get("lag"),
            "kernel": s.get("kernel"), "p_one_sided": 0.5 * math.erfc(s["t"] / math.sqrt(2.0)),
            "interval_95": [s["mean"] - Z95 * s["hac_se"], s["mean"] + Z95 * s["hac_se"]],
            "pass": passed, "rule": "mean > 0 and t > %.1f" % DM_THRESHOLD}


def classify(decisions: dict, *, integrity_ok: bool = True, integrity_reason: str | None = None) -> dict:
    """decisions: {HAC_D0, BOOT_D0, HAC_D1, BOOT_D1} -> bool."""
    if not integrity_ok:
        return {"outcome": "INTEGRITY_FAILURE", "reason": integrity_reason,
                "statistical_classification": "NOT MADE (integrity precedence)"}
    missing = [k for k in REQUIRED if k not in decisions]
    if missing:
        raise ValueError("missing decisions: %s" % missing)
    dec = {k: bool(decisions[k]) for k in REQUIRED}
    spec_pass = {sp: dec["HAC_%s" % sp] and dec["BOOT_%s" % sp] for sp in SPECS}
    flags = {"INFERENCE_DISAGREEMENT_D0": dec["HAC_D0"] != dec["BOOT_D0"],
             "INFERENCE_DISAGREEMENT_D1": dec["HAC_D1"] != dec["BOOT_D1"],
             "SPECIFICATION_SENSITIVE": spec_pass["D0"] != spec_pass["D1"]}
    outcome = "SELECTED" if all(dec.values()) else "NOT_SELECTED"
    return {"outcome": outcome, "decisions": dec, "per_spec_pass": spec_pass, "flags": flags,
            "rule": "SELECTED iff all four pass; flags are independent booleans with no precedence"}


def secondary_family(p_hac: dict, p_boot: dict) -> dict:
    """Six hypotheses per method (S1,S2,S3 x D0,D1); Holm SEPARATELY by method."""
    keys = ["%s_%s" % (s, sp) for s in SECONDARY for sp in SPECS]
    for k in keys:
        if k not in p_hac or k not in p_boot:
            raise ValueError("secondary family incomplete: %s" % k)
    return {"hypotheses": keys, "m": len(keys),
            "holm_hac": _holm({k: p_hac[k] for k in keys}),
            "holm_bootstrap": _holm({k: p_boot[k] for k in keys}),
            "note": "adjusted separately per inference method; none affects primary selection"}


def primary_pair() -> tuple:
    return tuple(PRIMARY["comparison"])
