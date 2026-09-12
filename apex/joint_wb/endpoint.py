"""ENDPOINT_SELECTION_V1 and the per-key lookup (contract §1.4, §1.5).

ONE algorithm serves training, the simulation target and scoring. The selection is JOINT: a single instant `t_e`
at which the frozen ATM keys are all present, mutually coherent, and each within the symmetric permissible offset
of the target. The per-quote SIGNED offsets, receipt lags and slice dispersion are recorded, because the selection
delay is NOT the measurement error. The estimand is labelled TARGET_PROXY_V1 wherever it is reported."""
from __future__ import annotations

import math

from apex.multiverse_wb.pricing import PricingRefused, sanitize_quote

SLICE_COHERENCE_S = 30.0
AVAILABILITY_DEADLINE_S = 60.0      # contract §1.4: an END input must be available by t_e + 60 s
DELTA_MAX_S = 60.0                  # selection delay ceiling
OFFSET_MAX_S = 60.0                 # symmetric per-quote |o_j| ceiling
TIGHT_OFFSET_S = 15.0               # declared sensitivity
ESTIMAND_LABEL = ("TARGET_PROXY_V1: a 15-minute-ahead forecast ASSESSED AGAINST A DELAYED-OR-STALE QUOTE PROXY; "
                  "per-quote offsets, receipt lags and slice dispersion are recorded; no observation model corrects "
                  "the discrepancy in V1")


def _usable(q: dict, *, at: float) -> tuple:
    """(sanitized, reason). Validation precedes every use (r3 rule); age is measured at the candidate instant."""
    try:
        return sanitize_quote(q, now=at, max_age_s=1e9), None      # freshness handled by the offset rule below
    except PricingRefused as e:
        return None, str(e)


def select_endpoint(quotes_by_key: dict, *, target_epoch: float, keys_required: tuple, keys_optional: tuple = (),
                    delta_max_s: float = DELTA_MAX_S, offset_max_s: float = OFFSET_MAX_S,
                    coherence_s: float = SLICE_COHERENCE_S) -> dict:
    """quotes_by_key: {key: [quote, ...]} as RECEIVED. Returns the selection record; `t_e is None` means EXCLUDED.

    A candidate instant `t` is admissible when every required key has at least one quote with
    `event_time <= t`, `available_time <= t`, passing validation, with `|event_time - target| <= offset_max_s`,
    and the chosen quotes' event times span no more than `coherence_s`."""
    census: dict = {}
    admissible: dict = {}                                          # key -> [(event_time, quote, sanitized)]
    for key in tuple(keys_required) + tuple(keys_optional):
        rows = []
        for q in quotes_by_key.get(key, []):
            sq, why = _usable(q, at=target_epoch + delta_max_s)
            if sq is None:
                census.setdefault(str(key), []).append("REJECTED_QUOTE: %s" % why); continue
            o = q["timestamp_epoch"] - target_epoch
            if abs(o) > offset_max_s:
                census.setdefault(str(key), []).append("OFFSET_EXCEEDED: o=%.1fs" % o); continue
            rows.append((q["timestamp_epoch"], q, sq))
        if rows:
            admissible[key] = sorted(rows, key=lambda r: r[0])
        else:
            census.setdefault(str(key), []).append("NO_ADMISSIBLE_QUOTE")

    missing = [k for k in keys_required if k not in admissible]
    if missing:
        return {"t_e": None, "excluded": True, "why": "ENDPOINT_NOT_COHERENT: required key(s) unavailable %s" % (missing[:3],),
                "census": census, "estimand": ESTIMAND_LABEL}

    # candidate instants: the event times of required-key quotes, clipped to the window, earliest first
    cands = sorted({r[0] for k in keys_required for r in admissible[k]} | {target_epoch})
    sane = {k: [r[1] for r in v] for k, v in admissible.items()}
    for t in cands:
        if t < target_epoch or t > target_epoch + delta_max_s:
            continue
        # SELECTION uses ONLY what was available AT t: event_time <= t AND available_time <= t. A quote that
        # arrives after t cannot participate in choosing t (no look-ahead). The registered deadline is a SEPARATE,
        # later check applied once t_e is fixed.
        chosen, ok, ambiguous = {}, True, None
        for key in keys_required:
            look = lookup_at(sane[key], instant=t, key=key)          # the registered deterministic lookup (§1.5)
            if look["quote"] is None:
                if look["why"].startswith("ENDPOINT_AMBIGUOUS"):
                    ambiguous = look["why"]
                ok = False; break
            chosen[key] = look["quote"]
        if ambiguous:
            return {"t_e": None, "excluded": True, "why": ambiguous, "census": census, "estimand": ESTIMAND_LABEL}
        if not ok:
            continue
        ev = [q["timestamp_epoch"] for q in chosen.values()]
        if max(ev) - min(ev) > coherence_s:
            continue
        for key in keys_optional:
            look = lookup_at(sane.get(key, []), instant=t, key=key)
            if look["quote"] is not None:
                e2 = look["quote"]["timestamp_epoch"]
                if max(max(ev), e2) - min(min(ev), e2) <= coherence_s:
                    chosen[key] = look["quote"]
        # registered endpoint deadline, applied AFTER the instant is chosen (§1.4)
        late = {str(k): q.get("available_time", q["timestamp_epoch"]) - (t + AVAILABILITY_DEADLINE_S)
                for k, q in chosen.items() if q.get("available_time", q["timestamp_epoch"]) > t + AVAILABILITY_DEADLINE_S}
        if late:
            return {"t_e": None, "excluded": True, "why": "ENDPOINT_AVAILABILITY_DEADLINE_EXCEEDED: %s" % late,
                    "census": census, "estimand": ESTIMAND_LABEL}
        offsets = {str(k): round(q["timestamp_epoch"] - target_epoch, 6) for k, q in chosen.items()}
        lags = {str(k): round(q.get("available_time", q["timestamp_epoch"]) - q["timestamp_epoch"], 6) for k, q in chosen.items()}
        evs = [q["timestamp_epoch"] for q in chosen.values()]
        sanitized = {}
        for k, q in chosen.items():
            for et, raw, sq in admissible[k]:
                if raw is q:
                    sanitized[k] = sq; break
        return {"t_e": t, "excluded": False, "delta_s": round(t - target_epoch, 6), "quotes": sanitized,
                "raw": dict(chosen), "offsets_s": offsets, "receipt_lags_s": lags,
                "slice_dispersion_s": round(max(evs) - min(evs), 6), "max_abs_offset_s": round(max(abs(v) for v in offsets.values()), 6),
                "mean_offset_s": round(sum(offsets.values()) / len(offsets), 6), "census": census,
                "estimand": ESTIMAND_LABEL, "tight_sensitivity_eligible": max(abs(v) for v in offsets.values()) <= TIGHT_OFFSET_S,
                "selection_rule": "SELECTION: event_time <= t AND available_time <= t (no look-ahead); DEADLINE: available_time <= t_e + %.0f s"
                                  % AVAILABILITY_DEADLINE_S,
                "keys_missing_optional": [str(k) for k in keys_optional if k not in chosen]}
    return {"t_e": None, "excluded": True, "why": "ENDPOINT_NOT_COHERENT: no jointly coherent instant in the window",
            "census": census, "estimand": ESTIMAND_LABEL}


def lookup_at(quotes: list, *, instant: float, key) -> dict:
    """§1.5 per-key lookup at a selected instant: latest event_time <= instant; ties -> earliest available_time;
    ties -> lowest source id; still tied -> ENDPOINT_AMBIGUOUS. Deterministic and total; no container ordering."""
    rows = [q for q in quotes if q["timestamp_epoch"] <= instant and q.get("available_time", q["timestamp_epoch"]) <= instant]
    if not rows:
        return {"quote": None, "why": "ENDPOINT_KEY_ABSENT:%s" % (key,)}
    newest = max(r["timestamp_epoch"] for r in rows)
    rows = [r for r in rows if r["timestamp_epoch"] == newest]
    if len(rows) > 1:
        first_av = min(r.get("available_time", r["timestamp_epoch"]) for r in rows)
        rows = [r for r in rows if r.get("available_time", r["timestamp_epoch"]) == first_av]
    if len(rows) > 1:
        lo = min(str(r.get("source", "")) for r in rows)
        rows = [r for r in rows if str(r.get("source", "")) == lo]
    if len(rows) > 1:
        return {"quote": None, "why": "ENDPOINT_AMBIGUOUS:%s" % (key,)}
    return {"quote": rows[0], "why": None}


def offset_summary(selection: dict) -> dict:
    """What every fit and score reports alongside its numbers (§1.4)."""
    if selection.get("t_e") is None:
        return {"excluded": True, "why": selection.get("why"), "estimand": ESTIMAND_LABEL}
    return {"excluded": False, "delta_s": selection["delta_s"], "max_abs_offset_s": selection["max_abs_offset_s"],
            "mean_offset_s": selection["mean_offset_s"], "slice_dispersion_s": selection["slice_dispersion_s"],
            "receipt_lags_s": selection["receipt_lags_s"], "tight_sensitivity_eligible": selection["tight_sensitivity_eligible"],
            "estimand": ESTIMAND_LABEL}
