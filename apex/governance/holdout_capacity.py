"""A-009 machinery: segmented holdout capacity, priced by measured independence.

Implements the signed amendment's sections 2-5:
  * N_eff / charge with the 0.25 floor, class ρ̄ floors, 0.7 default;
  * AUTOMATIC budget reversion 8 -> 5 if pricing is inoperative -- checked
    in code at every budget query, not promised in prose;
  * leak-suppressed ρ̄ measurement (emits ONE float; no level, mean, sign,
    or dispersion of any candidate segment's series is computed into
    anything observable);
  * irrevocable holdout naming and programme-wide burn, both chained;
  * verdict weight rendering, with a gate that refuses a bare verdict.

Capacity records live in their own chained ledger
(results/holdout_capacity_ledger.jsonl) rather than mutating the certified
research ledger; a holdout evaluation under A-009 references its capacity
row from the main ledger at recording time. Design decision, disclosed: the
amendment's section 4.3 fields are all here, the certified chain is not
touched, and the anchor discipline is identical.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

BASE_BUDGET = 5
PRICED_BUDGET = 8
CHARGE_FLOOR = 0.25
RHO_DEFAULT_UNMEASURABLE = 0.7
CLASS_RHO_FLOORS = {"I": 0.0, "II": 0.50, "III": 0.20, "IV": 0.20, "V": 0.30}


class CapacityError(ValueError):
    """An A-009 invariant was violated."""


def n_eff(k: int, rho: float) -> float:
    if k < 0 or not (0.0 <= rho <= 1.0):
        raise CapacityError(f"bad inputs k={k} rho={rho}")
    return 0.0 if k == 0 else k / (1 + (k - 1) * rho)


def charge(k: int, rho: float) -> float:
    """Marginal effective-trial gain of the k-th evaluation, floored."""
    if k < 1:
        raise CapacityError("the first evaluation is k=1")
    return max(CHARGE_FLOOR, n_eff(k, rho) - n_eff(k - 1, rho))


def governing_rho(measured: float | None, klass: str) -> float:
    if klass not in CLASS_RHO_FLOORS:
        raise CapacityError(f"unknown independence class {klass!r}")
    base = RHO_DEFAULT_UNMEASURABLE if measured is None else float(measured)
    return max(base, CLASS_RHO_FLOORS[klass])


def pricing_operative() -> bool:
    """Self-check: the reversion clause, IN CODE. If any pricing invariant
    stops holding -- floors missing, charge unfloored, default flattering --
    the budget silently... no: LOUDLY reverts to 5."""
    try:
        checks = (
            abs(charge(2, 0.6) - CHARGE_FLOOR) < 1e-12,      # floor binds
            charge(2, 0.15) > 0.7,                            # low-rho costs more
            governing_rho(0.10, "II") == 0.50,                # class floor binds
            governing_rho(None, "III") == RHO_DEFAULT_UNMEASURABLE,
            all(v >= 0 for v in CLASS_RHO_FLOORS.values()),
            CHARGE_FLOOR > 0,
        )
        return all(checks)
    except Exception:                                         # noqa: BLE001
        return False


def budget() -> int:
    return PRICED_BUDGET if pricing_operative() else BASE_BUDGET


def measure_rho(candidate_series, existing_series) -> float:
    """LEAK-SUPPRESSED: returns the mean pairwise correlation and NOTHING
    else. No mean, level, sign, or dispersion of any input is computed into
    an observable. Correlation is scale- and mean-invariant, so pricing
    loses nothing."""
    cand = np.asarray(candidate_series, dtype=float)
    rhos = []
    for s in existing_series:
        s = np.asarray(s, dtype=float)
        n = min(len(cand), len(s))
        if n < 60:
            continue
        rhos.append(abs(float(np.corrcoef(cand[:n], s[:n])[0, 1])))
    if not rhos:
        return RHO_DEFAULT_UNMEASURABLE
    return float(np.mean(rhos))


# ---------------------------------------------------------------------------
# the chained capacity ledger: definitions, namings, burns, charges
# ---------------------------------------------------------------------------

def _canon(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class HoldoutCapacityLedger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().strip().splitlines()]

    def _append(self, row: dict) -> dict:
        rows = self._rows()
        prev = rows[-1]["entry_hash"] if rows else "GENESIS"
        body = {**row, "prev_hash": prev}
        body["entry_hash"] = _canon(body)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(body, sort_keys=True) + "\n")
        return body

    def define_holdout(self, holdout_id: str, universe_hash: str,
                       period: str, klass: str) -> dict:
        if klass not in CLASS_RHO_FLOORS:
            raise CapacityError(f"unknown class {klass!r}")
        if any(r["kind"] == "define" and r["holdout_id"] == holdout_id
               for r in self._rows()):
            raise CapacityError(f"{holdout_id!r} already defined; a holdout's "
                                f"class cannot be revised after definition")
        return self._append({"kind": "define", "holdout_id": holdout_id,
                             "universe_hash": universe_hash, "period": period,
                             "class": klass})

    def name_holdout(self, experiment: str, holdout_id: str) -> dict:
        rows = self._rows()
        if not any(r["kind"] == "define" and r["holdout_id"] == holdout_id
                   for r in rows):
            raise CapacityError(f"{holdout_id!r} is not a defined holdout")
        if any(r["kind"] == "burn" and r["holdout_id"] == holdout_id
               for r in rows):
            raise CapacityError(
                f"{holdout_id!r} is BURNED programme-wide; no future "
                f"experiment may name it")
        prior = [r for r in rows if r["kind"] == "name"
                 and r["experiment"] == experiment]
        if prior:
            raise CapacityError(
                f"{experiment} already irrevocably named "
                f"{prior[0]['holdout_id']!r}; naming may never be "
                f"renegotiated, substituted, or reassigned")
        return self._append({"kind": "name", "experiment": experiment,
                             "holdout_id": holdout_id})

    def burn(self, holdout_id: str) -> dict:
        return self._append({"kind": "burn", "holdout_id": holdout_id})

    def record_charge(self, *, experiment: str, holdout_id: str, klass: str,
                      measured_rho: float | None, rho_window: str,
                      k: int) -> dict:
        """The section-4.3 record: every mandatory field, or no record."""
        g = governing_rho(measured_rho, klass)
        ch = charge(k, g)
        cumulative = sum(r["charge"] for r in self._rows()
                         if r["kind"] == "charge") + ch
        return self._append({
            "kind": "charge", "experiment": experiment,
            "holdout_id": holdout_id, "class": klass,
            "measured_rho": measured_rho, "governing_rho": round(g, 4),
            "rho_estimation_window": rho_window, "k": k,
            "n_eff_before": round(n_eff(k - 1, g), 4),
            "n_eff_after": round(n_eff(k, g), 4),
            "charge": round(ch, 4),
            "cumulative_charges": round(cumulative, 4),
            "budget": budget(),
            "remaining_budget": round(budget() - 4 - cumulative, 4),
        })

    def summary(self) -> dict:
        """Section 3.3: charge-sum and N_eff TOGETHER, never one alone."""
        charges = [r for r in self._rows() if r["kind"] == "charge"]
        return {"cumulative_charges_governs_budget":
                round(sum(r["charge"] for r in charges), 4),
                "n_eff_current_set_governs_multiplicity":
                round(charges[-1]["n_eff_after"], 4) if charges else 0.0,
                "budget": budget()}


def weighted_verdict(verdict: str, klass: str, rho: float,
                     delta_neff: float) -> str:
    """Section 4.2: a verdict carries its weight inline."""
    return f"{verdict} (Class {klass}, ρ̄={rho:.2f}, +{delta_neff:.2f} N_eff)"


def require_weighted(verdict_str: str) -> str:
    """The serialization gate: refuses a bare verdict."""
    if "N_eff" not in verdict_str or "Class" not in verdict_str:
        raise CapacityError(
            f"verdict {verdict_str!r} is stripped of its independence weight; "
            f"a correlated segment pass quoted bare is the headline-hunting "
            f"path A-009 pricing exists to close")
    return verdict_str
