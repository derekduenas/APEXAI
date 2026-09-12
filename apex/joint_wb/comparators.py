"""The comparator table and the exactly additive decomposition (contract §4.2, §4.3).

`C_PERM` is NOT here: it is a SYNTHETIC-ONLY diagnostic (§6.2) and never enters an attribution report or a
decision path. `JOINT - C_DIAG` is the COMPOUND_COUPLING_LAW_CONTRAST, never an isolated correlation effect."""
from __future__ import annotations

from .sampler import COMPOUND_LABEL

VETO_LABEL = ("INCLUDES_SIZE_VETO_POLICY: on the DECISION-ECONOMICS functional, Sh(F2) and D bundle the spread/size "
              "dynamics with the selected-only veto that only the size-modelling comparators face; the "
              "FORECAST-QUALITY functional is unaffected because scoring a distribution does not invoke the rule")

TABLE = {
    "MATCHED_FROZEN": {"iv_block": False, "exec_block": False, "residual": "none", "size_policy": "ASSUME_AVAILABLE", "veto": False},
    "C_IV": {"iv_block": "first coordinate of shared e1", "exec_block": False, "residual": "e1[:,0]", "size_policy": "ASSUME_AVAILABLE", "veto": False},
    "C_IVSK": {"iv_block": True, "exec_block": False, "residual": "e1", "size_policy": "ASSUME_AVAILABLE", "veto": False},
    "C_EXEC": {"iv_block": False, "exec_block": True, "residual": "e2_diag", "size_policy": "rank without size; selected-only veto", "veto": True},
    "C_DIAG": {"iv_block": True, "exec_block": True, "residual": "e1, e2_diag", "size_policy": "rank without size; selected-only veto", "veto": True},
    "JOINT": {"iv_block": True, "exec_block": True, "residual": "e1, e2_joint", "size_policy": "rank without size; selected-only veto", "veto": True},
}
ORDER = ("MATCHED_FROZEN", "C_IV", "C_IVSK", "C_EXEC", "C_DIAG", "JOINT")
LATTICE = ("MATCHED_FROZEN", "C_IVSK", "C_EXEC", "C_DIAG", "JOINT")


def decompose(V: dict, *, functional: str = "DECISION_ECONOMICS") -> dict:
    """J = Sh(F1) + Sh(F2) + D, exactly (§4.3). V maps comparator id -> functional value."""
    missing = [c for c in LATTICE if c not in V]
    if missing:
        raise KeyError("DECOMPOSITION_MISSING_COMPARATORS: %s" % missing)
    f, ivsk, ex, dg, jt = (V["MATCHED_FROZEN"], V["C_IVSK"], V["C_EXEC"], V["C_DIAG"], V["JOINT"])
    sh1 = 0.5 * (ivsk - f) + 0.5 * (dg - ex)
    sh2 = 0.5 * (ex - f) + 0.5 * (dg - ivsk)
    d = jt - dg
    j = jt - f
    out = {"functional": functional, "Sh_F1_iv_block": sh1, "Sh_F2_exec_block": sh2, "D_coupling": d, "J_total": j,
           "identity_residual": j - (sh1 + sh2 + d),
           "descriptive_C_IV_minus_frozen": (V["C_IV"] - f) if "C_IV" in V else None,
           "labels": {"D": COMPOUND_LABEL}}
    if functional == "DECISION_ECONOMICS":
        out["labels"]["Sh_F2_exec_block"] = VETO_LABEL
        out["labels"]["D"] = COMPOUND_LABEL + " | " + VETO_LABEL
    return out


def describe() -> dict:
    return {"table": TABLE, "order": list(ORDER), "lattice": list(LATTICE),
            "C_PERM": "SYNTHETIC-ONLY diagnostic (§6.2): never in this table, never in an attribution report, never in a decision path",
            "compound_note": COMPOUND_LABEL, "veto_note": VETO_LABEL}
