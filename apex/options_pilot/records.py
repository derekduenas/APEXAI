"""OPTIONS-PILOT-001 record contracts.

What a forecast, an intent, a quote, a fill and an outcome MUST say before the
boundary will persist them. Every value that is a number is checked to be a
finite real (never a bool); every instant is parsed as a timezone-aware
timestamp; serialization is strict JSON with allow_nan=False, so a malformed
value cannot become persisted evidence.

Labels: every record carries the PROSPECTIVE PAPER labels and a separate
PROVENANCE field. Execution mode and data provenance are distinct: a synthetic
fixture may exercise prospective orchestration, and its records say so.

A forecast is a DISTRIBUTION with explicit meaning. It is RECORDED; in this
brick it does not drive expression selection — direction comes from a
heuristic signal, which is persisted as the signal ACTUALLY USED."""
from __future__ import annotations

import hashlib
import json

from .clock import ClockRefused, is_exact_int, is_real, parse_utc, to_utc_string

EVIDENCE_CLASS = "PROSPECTIVE_PAPER"
DECISION_POWER = "NONE_PAPER"
FORBIDDEN_CLASSES = ("HISTORICAL_DEVELOPMENT_REPLAY", "NONE_REPLAY")
PROVENANCE = ("SYNTHETIC_FIXTURE", "LIVE_FEED")
EXECUTION_MODES = ("PROSPECTIVE_ORCHESTRATION",)
SIGNAL_STATUS_REF = {
    "document": "SIGNAL_STATUS_001.md",
    "statement": ("there is no validated directional signal on the options path; HEURISTIC_DIRECTION_V1 is a placeholder "
                  "that exists so the pipeline has an input; no P&L produced under it is evidence about anything except "
                  "the pipeline; a negative result under it is the EXPECTED result, not a finding about the system"),
    "hurdle": "docs/SIGNAL_HURDLE_001.md"}
LABELS = {"evidence_class": EVIDENCE_CLASS, "decision_power": DECISION_POWER,
          "live_capital": "LOCKED", "live_promotion_eligible": False,
          # sealed on EVERY record so a placeholder cannot become a strategy by accumulation
          "signal_status": SIGNAL_STATUS_REF}

TIMESTAMP_GRANULARITY_S = 1e-6      # records serialize epochs as microsecond strings; comparisons honour that
FORECAST_TARGET = "log(close[bar at t+15min] / close[bar at t])"
FORECAST_UNITS = "log return, dimensionless"
FORECAST_HORIZON_MINUTES = 15
FORECAST_HORIZON_S = 15 * 60
FORECAST_FAMILIES = ("STUDENT_T", "GAUSSIAN")
HORIZON_RELATIONSHIP = ("the forecast horizon is 15 minutes; the pilot holds a filled contract to the regular-session "
                        "close. These are DIFFERENT horizons. The forecast is recorded and is NOT extrapolated to the "
                        "hold horizon; any request to use it as a hold-horizon expectation is refused")
INTENT_TTL_S = 120.0
FORECAST_FRESHNESS_S = 120.0
FORECAST_ELIGIBILITY_POLICY = ("FORECAST_ELIGIBILITY_V1: created <= clock; clock < target_end (the target is still in the "
                               "future -- a forecast about a completed target is not prospective decision evidence); "
                               "clock - input_cutoff <= 120s; re-checked at intent creation and at fill commit")

KINDS = ("pilot_forecast", "pilot_intent", "pilot_fill", "pilot_outcome", "pilot_refusal", "pilot_decision",
         "pilot_duplicate_delivery", "pilot_intent_expired", "pilot_intent_cancelled", "pilot_exit_exhausted",
         "pilot_session_open", "pilot_session_close")


class RecordRefused(ValueError):
    """A record that does not say what it must say. Named, never silent."""


# ---------------------------------------------------------------- strict serialization

def canonical_json(obj) -> str:
    """The canonicalization recipe used for every hash in this package:
    json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).
    This hashes the CANONICAL RE-SERIALIZATION of a parsed object, not the
    literal bytes of a file line."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_hash(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def strict_serializable(obj, *, what: str) -> None:
    try:
        canonical_json(obj)
    except (ValueError, TypeError) as e:
        raise RecordRefused("NOT_STRICT_JSON: %s: %s" % (what, e)) from e


def _real(x, field: str, *, positive=False, non_negative=False) -> float:
    if not is_real(x):
        raise RecordRefused("%s: must be a finite real number (no bool, nan or inf), got %r" % (field, x))
    if positive and not x > 0:
        raise RecordRefused("%s: must be > 0, got %r" % (field, x))
    if non_negative and x < 0:
        raise RecordRefused("%s: must be >= 0, got %r" % (field, x))
    return float(x)


def _int(x, field: str, *, minimum: int | None = None) -> int:
    if not is_exact_int(x):
        raise RecordRefused("%s: must be an exact int (not bool/float/str), got %r" % (field, x))
    if minimum is not None and x < minimum:
        raise RecordRefused("%s: must be >= %d, got %d" % (field, minimum, x))
    return x


def _ts(rec: dict, field: str) -> float:
    try:
        return parse_utc(rec.get(field), field=field)
    except ClockRefused as e:
        raise RecordRefused(str(e)) from e


def labels_for(provenance: str, execution_mode: str = "PROSPECTIVE_ORCHESTRATION") -> dict:
    if provenance not in PROVENANCE:
        raise RecordRefused("PROVENANCE_UNKNOWN: %r" % provenance)
    if execution_mode not in EXECUTION_MODES:
        raise RecordRefused("EXECUTION_MODE_UNKNOWN: %r" % execution_mode)
    return {**LABELS, "data_provenance": provenance, "execution_mode": execution_mode,
            "synthetic": provenance == "SYNTHETIC_FIXTURE"}


def assert_prospective(rec: dict) -> None:
    for k in ("evidence_class", "decision_power", "law"):
        v = rec.get(k)
        if isinstance(v, str) and any(bad in v for bad in FORBIDDEN_CLASSES):
            raise RecordRefused("REPLAY_LABEL_ON_PROSPECTIVE_RECORD: %s=%r" % (k, v))
    if rec.get("evidence_class") != EVIDENCE_CLASS or rec.get("decision_power") != DECISION_POWER:
        raise RecordRefused("LABELS_NOT_PROSPECTIVE: %r/%r" % (rec.get("evidence_class"), rec.get("decision_power")))
    if rec.get("data_provenance") not in PROVENANCE:
        raise RecordRefused("PROVENANCE_MISSING")
    strict_serializable(rec, what=str(rec.get("kind")))


# ---------------------------------------------------------------- forecast

FORECAST_REQUIRED = ("symbol", "target", "units", "horizon_minutes", "family", "location", "scale",
                     "model_id", "model_hash", "params_hash", "artifact_digest",
                     "reference_time_utc", "target_end_utc", "input_event_time_utc",
                     "input_available_utc", "input_cutoff_utc", "created_utc")


def validate_forecast(f: dict, *, now_epoch: float, provenance: str, session_id: str, scan_id: str) -> dict:
    """Normalise a forecast or refuse with the reason. Meaning is explicit;
    instants are parsed and checked for causal consistency and against the
    controlled clock."""
    if not isinstance(f, dict):
        raise RecordRefused("FORECAST_NOT_A_RECORD")
    missing = [k for k in FORECAST_REQUIRED if k not in f]
    if missing:
        raise RecordRefused("FORECAST_MISSING_FIELDS: %s" % missing)
    if f["target"] != FORECAST_TARGET:
        raise RecordRefused("FORECAST_TARGET_INCOMPATIBLE: %r" % f["target"])
    if f["units"] != FORECAST_UNITS:
        raise RecordRefused("FORECAST_UNITS_INCOMPATIBLE: %r" % f["units"])
    if not is_exact_int(f["horizon_minutes"]) or f["horizon_minutes"] != FORECAST_HORIZON_MINUTES:
        raise RecordRefused("FORECAST_HORIZON_INCOMPATIBLE: %r != %d" % (f["horizon_minutes"], FORECAST_HORIZON_MINUTES))
    if f["family"] not in FORECAST_FAMILIES:
        raise RecordRefused("FORECAST_FAMILY_UNKNOWN: %r" % f["family"])
    loc = _real(f["location"], "location")
    scale = _real(f["scale"], "scale", positive=True)
    nu = None
    if f["family"] == "STUDENT_T":
        nu = f.get("nu")
        if not is_real(nu) or nu <= 2.0:
            raise RecordRefused("FORECAST_NU_INVALID: %r (Student-t needs finite nu > 2)" % (nu,))
        nu = float(nu)
    for k in ("model_hash", "params_hash", "artifact_digest"):
        v = f[k]
        if not isinstance(v, str) or len(v) < 16:
            raise RecordRefused("FORECAST_%s_INVALID: %r" % (k.upper(), v))
    # ---- causal clock contract
    ref = _ts(f, "reference_time_utc"); end = _ts(f, "target_end_utc")
    ev = _ts(f, "input_event_time_utc"); av = _ts(f, "input_available_utc")
    cut = _ts(f, "input_cutoff_utc"); cre = _ts(f, "created_utc")
    if abs((end - ref) - FORECAST_HORIZON_S) > 1e-6:
        raise RecordRefused("FORECAST_TARGET_END_INCOMPATIBLE: target_end - reference = %.3fs != %ds" % (end - ref, FORECAST_HORIZON_S))
    if ev > ref:
        raise RecordRefused("FORECAST_INPUT_AFTER_REFERENCE: input event %.3f > reference %.3f" % (ev, ref))
    if av < ev:
        raise RecordRefused("FORECAST_AVAILABLE_BEFORE_EVENT")
    if cut < av:
        raise RecordRefused("FORECAST_INPUT_NOT_AVAILABLE_BY_CUTOFF: available %.3f > cutoff %.3f" % (av, cut))
    if cre < cut:
        raise RecordRefused("FORECAST_CREATED_BEFORE_INPUT_CUTOFF")
    # SERIALIZATION GRANULARITY. `created_utc` is written as a microsecond string and parsed back, which can return a
    # value up to half a microsecond LARGER than the epoch it was written from. Comparing that against a
    # full-precision clock read refused forecasts created at exactly the current instant. Live running masks it (the
    # clock advances between creation and this check); every controlled-clock path — replay, backtest, tests — hit it
    # about half the time and silently lost the scan. The comparison is now made at the record's own granularity.
    if cre > now_epoch + TIMESTAMP_GRANULARITY_S:
        raise RecordRefused("FORECAST_FROM_THE_FUTURE: created %.6f > clock %.6f (granularity %.0e s)"
                            % (cre, now_epoch, TIMESTAMP_GRANULARITY_S))
    if now_epoch >= end:
        raise RecordRefused("FORECAST_TARGET_ALREADY_ENDED: target_end %s is not after clock %s"
                            % (to_utc_string(end), to_utc_string(now_epoch)))
    if now_epoch - cut > FORECAST_FRESHNESS_S:
        raise RecordRefused("FORECAST_STALE: input cutoff %.1fs before clock > %.0fs policy" % (now_epoch - cut, FORECAST_FRESHNESS_S))
    sig = f.get("direction_signal")
    if sig is not None and sig not in ("LONG", "SHORT"):
        raise RecordRefused("DIRECTION_SIGNAL_INVALID: %r" % (sig,))
    body = {k: f[k] for k in FORECAST_REQUIRED}
    body.update({"location": loc, "scale": scale, "nu": nu, "kind": "pilot_forecast",
                 "session_id": session_id, "scan_id": scan_id,
                 "epoch": {"reference": ref, "target_end": end, "input_event": ev, "input_available": av,
                           "input_cutoff": cut, "created": cre},
                 "forecast_meaning": ("a predictive DISTRIBUTION for the registered 15-minute log return at the native "
                                      "horizon of the identified parameter artifact; NOT an expected directional move, "
                                      "NOT a hold-to-close forecast"),
                 "horizon_relationship": HORIZON_RELATIONSHIP,
                 "eligibility_policy": FORECAST_ELIGIBILITY_POLICY,
                 "drives_expression_selection": False,
                 "direction_signal": sig, "inputs": f.get("inputs"),
                 "direction_signal_meaning": "HEURISTIC trend label; not part of the forecast distribution",
                 "validation_status": f.get("validation_status", "NOT_VALIDATED"),
                 "specification_note": ("a fully specified distribution is not proof of statistical specification "
                                        "correctness")})
    body.update(labels_for(provenance))
    body["forecast_hash"] = canonical_hash({k: body[k] for k in FORECAST_REQUIRED + ("nu",)})
    body["forecast_id"] = canonical_hash({"session_id": session_id, "scan_id": scan_id, "forecast_hash": body["forecast_hash"]})[:24]
    strict_serializable(body, what="pilot_forecast")
    return body


# ---------------------------------------------------------------- contracts and quotes

CONTRACT_FIELDS = ("symbol", "expiration", "strike", "right")
QUOTE_CONTRACT = ("QUOTE_CONTRACT_V1: one provider snapshot per contract with ONE timestamp covering both sides; "
                  "bid >= 0, ask > 0, ask >= bid (crossed refused), sizes exact non-negative ints; the provider's "
                  "timestamp is recorded as asserted and its freshness is measured at RECEIPT, per selected side")


def validate_contract(c: dict) -> dict:
    if not isinstance(c, dict):
        raise RecordRefused("CONTRACT_NOT_A_RECORD")
    missing = [k for k in CONTRACT_FIELDS if k not in c]
    if missing:
        raise RecordRefused("CONTRACT_MISSING_FIELDS: %s" % missing)
    if c["right"] not in ("CALL", "PUT"):
        raise RecordRefused("CONTRACT_RIGHT_INVALID: %r" % (c["right"],))
    if not isinstance(c["symbol"], str) or not c["symbol"]:
        raise RecordRefused("CONTRACT_SYMBOL_INVALID")
    try:
        parse_utc(c["expiration"] + "T00:00:00Z", field="expiration")
    except (ClockRefused, TypeError):
        raise RecordRefused("CONTRACT_EXPIRATION_INVALID: %r" % (c["expiration"],))
    return {"symbol": c["symbol"], "expiration": c["expiration"],
            "strike": _real(c["strike"], "strike", positive=True), "right": c["right"]}


def contract_id(c: dict) -> str:
    return "%s|%s|%s|%s" % (c["symbol"], c["expiration"], float(c["strike"]), c["right"])


def validate_quote(q, *, contract: dict) -> dict:
    """Refuses malformed provider returns; never coerces. Returns the
    normalised quote. Does NOT judge freshness — that needs the clock."""
    if not isinstance(q, dict):
        raise RecordRefused("QUOTE_NOT_A_RECORD: %r" % type(q).__name__)
    try:
        qc = validate_contract({k: q.get(k) for k in CONTRACT_FIELDS})
    except RecordRefused as e:
        raise RecordRefused("QUOTE_%s" % e) from e
    if contract_id(qc) != contract_id(contract):
        raise RecordRefused("CONTRACT_MISMATCH: quote is for %s, intent is for %s" % (contract_id(qc), contract_id(contract)))
    bid = _real(q.get("bid"), "bid", non_negative=True)
    ask = _real(q.get("ask"), "ask", positive=True)
    if ask < bid:
        raise RecordRefused("QUOTE_CROSSED: bid %r > ask %r" % (bid, ask))
    bs = _int(q.get("bid_size"), "bid_size", minimum=0)
    as_ = _int(q.get("ask_size"), "ask_size", minimum=0)
    ts = _real(q.get("timestamp_epoch"), "timestamp_epoch")
    return {"contract": qc, "contract_id": contract_id(qc), "bid": bid, "ask": ask, "bid_size": bs, "ask_size": as_,
            "timestamp_epoch": ts, "timestamp_utc": to_utc_string(ts),
            "timestamp_meaning": "PROVIDER_SNAPSHOT: one asserted timestamp for both sides; side update times are NOT inferred",
            "quote_contract": QUOTE_CONTRACT}


# ---------------------------------------------------------------- intent

TOLL_FORMULA_V1_TEXT = ("expected_toll_$ = 100 x (ask_ref - bid_ref) + fee_in + fee_out ; ask_ref/bid_ref = the INDICATIVE quote the "
                        "selection was made on, at intent time; the exit half-spread is ASSUMED equal to the entry half-spread")
TOLL_FORMULA_V1 = {"id": "TOLL_FORMULA_V1", "text": TOLL_FORMULA_V1_TEXT,
                   "hash": hashlib.sha256(TOLL_FORMULA_V1_TEXT.encode("ascii")).hexdigest(),
                   "assumption": "exit half-spread = entry half-spread (declared, not estimated); no fill quote exists at intent time",
                   "realised_counterpart": "REALISED_TOLL_V1: 100 x [(ask_fill - mid_fill) + (mid_exit - bid_exit)] + fees, from sealed fill and exit quotes"}
DOCTRINE_FIELDS = ("capacity_suitability", "giant_competition_risk", "signal_half_life", "our_expected_footprint", "crowding",
                   "forced_participant_strength")


def expected_toll(reference_quote: dict | None, fees_in, fees_out) -> dict:
    """Intent-time toll under TOLL_FORMULA_V1 from the INDICATIVE reference quote only. Unavailable inputs give
    NOT_ESTIMABLE with the reason; nothing is fabricated and no later quote is consulted."""
    rq = reference_quote or {}
    bid, ask = rq.get("bid"), rq.get("ask")
    out = {"formula": TOLL_FORMULA_V1["id"], "formula_hash": TOLL_FORMULA_V1["hash"],
           "inputs": {"ask_ref": ask, "bid_ref": bid, "fee_in": fees_in, "fee_out": fees_out, "reference_timestamp_epoch": rq.get("timestamp_epoch")}}
    if not (is_real(ask) and is_real(bid)) or ask <= 0 or bid < 0 or ask < bid:
        return {**out, "value": None, "status": "NOT_ESTIMABLE", "why": "reference quote lacks a valid bid/ask"}
    if not (is_real(fees_in) and is_real(fees_out)):
        return {**out, "value": None, "status": "NOT_ESTIMABLE", "why": "fee schedule unknown; an unknown cost is not zero"}
    return {**out, "value": round(100.0 * (ask - bid) + float(fees_in) + float(fees_out), 4), "status": "ESTIMATED_AT_INTENT_TIME"}


def doctrine_stamp(reference_quote: dict | None) -> dict:
    """The six doctrine fields + tail_asymmetry, each sealed with a value or an explicit NOT_MEASURED and its source.
    Only our_expected_footprint is computable at intent time (1 contract against the indicative ask size)."""
    rq = reference_quote or {}
    fields = {f: {"value": "NOT_MEASURED", "source": "no measurement contract activated for the pilot"} for f in DOCTRINE_FIELDS}
    if isinstance(rq.get("ask_size"), int) and not isinstance(rq.get("ask_size"), bool) and rq["ask_size"] > 0:
        fields["our_expected_footprint"] = {"value": round(1.0 / rq["ask_size"], 6), "source": "1 contract / indicative ask_size %d" % rq["ask_size"],
                                            "definition": "fraction of the displayed ask size our order would consume"}
    fields["tail_asymmetry"] = {"value": "UNKNOWN", "source": "apex/options_research/forward_distribution.py default; never measured"}
    return {"fields": fields, "definition_source": "SMALL_CAPITAL_ADVANTAGE_DOCTRINE.md (opportunity characteristics)"}


def validate_intent(i: dict, *, forecast: dict, forecast_receipt: dict, signal_used: str, session_id: str,
                    scan_id: str, release: str, created_epoch: float, risk_envelope: dict | None = None,
                    fees: dict | None = None, execution_policy: dict | None = None, pins: dict | None = None,
                    fee_totals: tuple | None = None) -> dict:
    for k in ("expression", "action", "contract", "quantity"):
        if k not in i:
            raise RecordRefused("INTENT_MISSING_FIELD: %s" % k)
    if i["expression"] not in ("LONG_CALL", "LONG_PUT"):
        raise RecordRefused("INTENT_EXPRESSION_NOT_IN_PILOT_RULE: %r" % (i["expression"],))
    if i["action"] != "BUY":
        raise RecordRefused("INTENT_ACTION_NOT_IN_PILOT_RULE: %r" % (i["action"],))
    if not is_exact_int(i["quantity"]) or i["quantity"] != 1:
        raise RecordRefused("INTENT_QUANTITY_NOT_ONE: pilot is one contract, filled or unfilled")
    if signal_used not in ("LONG", "SHORT"):
        raise RecordRefused("INTENT_SIGNAL_USED_INVALID: %r" % (signal_used,))
    expected_right = "CALL" if signal_used == "LONG" else "PUT"
    contract = validate_contract(i["contract"])
    if contract["right"] != expected_right or i["expression"] != ("LONG_CALL" if expected_right == "CALL" else "LONG_PUT"):
        raise RecordRefused("INTENT_SIGNAL_CONTRACT_DISAGREE: signal %s vs %s/%s" % (signal_used, i["expression"], contract["right"]))
    if forecast.get("direction_signal") is not None and forecast["direction_signal"] != signal_used:
        raise RecordRefused("SIGNAL_DISAGREES_WITH_FORECAST_RECORD: forecast says %r, rule used %r"
                            % (forecast["direction_signal"], signal_used))
    if contract["symbol"] != forecast["symbol"]:
        raise RecordRefused("INTENT_SYMBOL_MISMATCH: contract %r vs forecast %r" % (contract["symbol"], forecast["symbol"]))
    if forecast.get("session_id") != session_id or forecast.get("scan_id") != scan_id:
        raise RecordRefused("INTENT_SESSION_MISMATCH: forecast %s/%s vs intent %s/%s"
                            % (forecast.get("session_id"), forecast.get("scan_id"), session_id, scan_id))
    if i.get("use_forecast_as_hold_expectation"):
        raise RecordRefused("HORIZON_EXTRAPOLATION_REFUSED: " + HORIZON_RELATIONSHIP)
    body = {"kind": "pilot_intent", "expression": i["expression"], "action": "BUY", "contract": contract,
            "contract_id": contract_id(contract), "quantity": 1, "signal_used": signal_used,
            "expression_rule": i.get("expression_rule"), "strike_selection": i.get("strike_selection"), "no_best_option_claim": True,
            "session_id": session_id, "scan_id": scan_id, "release": release,
            "forecast_ref": {"seq": forecast_receipt["seq"], "entry_hash": forecast_receipt["entry_hash"],
                             "forecast_hash": forecast["forecast_hash"], "forecast_id": forecast["forecast_id"]},
            "horizon_relationship": HORIZON_RELATIONSHIP,
            "created_utc": to_utc_string(created_epoch), "created_epoch": created_epoch,
            "expiry_utc": to_utc_string(created_epoch + INTENT_TTL_S), "expiry_epoch": created_epoch + INTENT_TTL_S,
            "ttl_s": INTENT_TTL_S,
            "reference_ask": i.get("reference_ask") if is_real(i.get("reference_ask")) else None,
            "reference_quote": (i.get("reference_quote") if isinstance(i.get("reference_quote"), dict) else None),
            "risk_envelope": risk_envelope, "fees": fees, "execution_policy": execution_policy,
            # BEFORE fields (decision-path review of b9998d02, finding 6): sealed at intent time from information that
            # exists at intent time; a later requote or fill NEVER rewrites these
            "expected_toll": expected_toll(i.get("reference_quote"), *(fee_totals or (None, None))),
            "doctrine": doctrine_stamp(i.get("reference_quote")),
            "pins": pins}
    body["intent_id"] = canonical_hash({"forecast_id": forecast["forecast_id"], "contract_id": body["contract_id"],
                                        "signal_used": signal_used, "session_id": session_id})[:24]
    return body
