"""OPTIONS-PILOT-001 record contracts: what a forecast, an intent, a fill and
an outcome MUST say before the boundary will persist them.

Every record produced by this package carries the PROSPECTIVE PAPER labels.
The replay labels that the earlier live session stamped on its cards are a
recorded defect (see docs/OPTIONS_PILOT_RECORDING_BOUNDARY.md); nothing here
can emit them.

A forecast is a DISTRIBUTION with explicit meaning. A trend label is a
heuristic signal and is stored as one, never as a forecast."""
from __future__ import annotations

import hashlib
import json
import math

EVIDENCE_CLASS = "PROSPECTIVE_PAPER"
DECISION_POWER = "NONE_PAPER"
LIVE_CAPITAL = "LOCKED"
FORBIDDEN_CLASSES = ("HISTORICAL_DEVELOPMENT_REPLAY", "NONE_REPLAY")
LABELS = {"evidence_class": EVIDENCE_CLASS, "decision_power": DECISION_POWER,
          "live_capital": LIVE_CAPITAL, "live_promotion_eligible": False}

# the native horizon of the identified forecast artifact; nothing else is accepted
FORECAST_TARGET = "log(close[bar at t+15min] / close[bar at t])"
FORECAST_UNITS = "log return, dimensionless"
FORECAST_HORIZON_MINUTES = 15
FORECAST_FAMILIES = ("STUDENT_T", "GAUSSIAN")

KINDS = ("pilot_forecast", "pilot_intent", "pilot_fill", "pilot_outcome", "pilot_refusal",
         "pilot_session_open", "pilot_session_close")


class RecordRefused(ValueError):
    """A record that does not say what it must say. Named, never silent."""


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def canonical_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---------------------------------------------------------------- forecast

FORECAST_REQUIRED = ("symbol", "target", "units", "horizon_minutes", "family", "location", "scale",
                     "model_id", "model_hash", "params_hash", "input_cutoff_utc", "created_utc")


def validate_forecast(f: dict) -> dict:
    """Return a normalised forecast body or raise RecordRefused with the reason.

    Meaning is explicit and checked; a forecast that is missing a field, at
    the wrong horizon, of an unknown family, or non-finite is refused."""
    if not isinstance(f, dict):
        raise RecordRefused("FORECAST_NOT_A_RECORD")
    missing = [k for k in FORECAST_REQUIRED if k not in f]
    if missing:
        raise RecordRefused("FORECAST_MISSING_FIELDS: %s" % missing)
    if f["target"] != FORECAST_TARGET:
        raise RecordRefused("FORECAST_TARGET_INCOMPATIBLE: %r" % f["target"])
    if f["units"] != FORECAST_UNITS:
        raise RecordRefused("FORECAST_UNITS_INCOMPATIBLE: %r" % f["units"])
    if f["horizon_minutes"] != FORECAST_HORIZON_MINUTES:
        raise RecordRefused("FORECAST_HORIZON_INCOMPATIBLE: %r != %d" % (f["horizon_minutes"], FORECAST_HORIZON_MINUTES))
    if f["family"] not in FORECAST_FAMILIES:
        raise RecordRefused("FORECAST_FAMILY_UNKNOWN: %r" % f["family"])
    if not _finite(f["location"]) or not _finite(f["scale"]) or f["scale"] <= 0:
        raise RecordRefused("FORECAST_PARAMETERS_INVALID: location=%r scale=%r" % (f["location"], f["scale"]))
    if f["family"] == "STUDENT_T":
        nu = f.get("nu")
        if not _finite(nu) or nu <= 2.0:
            raise RecordRefused("FORECAST_NU_INVALID: %r (Student-t needs finite nu > 2)" % nu)
    for k in ("model_hash", "params_hash"):
        v = f[k]
        if not isinstance(v, str) or len(v) < 16:
            raise RecordRefused("FORECAST_%s_INVALID: %r" % (k.upper(), v))
    for k in ("input_cutoff_utc", "created_utc"):
        if not isinstance(f[k], str) or not f[k].endswith("Z"):
            raise RecordRefused("FORECAST_%s_NOT_UTC: %r" % (k.upper(), f[k]))
    if f["created_utc"] < f["input_cutoff_utc"]:
        raise RecordRefused("FORECAST_CREATED_BEFORE_INPUT_CUTOFF")
    sig = f.get("direction_signal")
    if sig is not None and sig not in ("LONG", "SHORT"):
        raise RecordRefused("DIRECTION_SIGNAL_INVALID: %r" % sig)
    body = {k: f[k] for k in FORECAST_REQUIRED}
    body["nu"] = f.get("nu")
    body["kind"] = "pilot_forecast"
    body["forecast_meaning"] = ("a predictive DISTRIBUTION for the registered 15-minute log return at the "
                                "native horizon of the identified parameter artifact; NOT an expected "
                                "directional move, NOT a hold-to-close forecast")
    body["direction_signal"] = sig
    body["direction_signal_meaning"] = "HEURISTIC trend label from the equity faculty; not part of the forecast distribution"
    body["validation_status"] = f.get("validation_status", "NOT_VALIDATED")
    body.update(LABELS)
    body["forecast_hash"] = canonical_hash({k: body[k] for k in FORECAST_REQUIRED + ("nu",)})
    return body


# ---------------------------------------------------------------- intent

CONTRACT_FIELDS = ("symbol", "expiration", "strike", "right")


def validate_contract(c: dict) -> dict:
    if not isinstance(c, dict):
        raise RecordRefused("CONTRACT_NOT_A_RECORD")
    missing = [k for k in CONTRACT_FIELDS if k not in c]
    if missing:
        raise RecordRefused("CONTRACT_MISSING_FIELDS: %s" % missing)
    if c["right"] not in ("CALL", "PUT"):
        raise RecordRefused("CONTRACT_RIGHT_INVALID: %r" % c["right"])
    if not _finite(c["strike"]) or c["strike"] <= 0:
        raise RecordRefused("CONTRACT_STRIKE_INVALID: %r" % c["strike"])
    return {k: c[k] for k in CONTRACT_FIELDS}


def contract_id(c: dict) -> str:
    return "%s|%s|%s|%s" % (c["symbol"], c["expiration"], float(c["strike"]), c["right"])


def validate_intent(i: dict, *, forecast_receipt: dict) -> dict:
    for k in ("expression", "action", "contract", "quantity", "risk"):
        if k not in i:
            raise RecordRefused("INTENT_MISSING_FIELD: %s" % k)
    if i["expression"] not in ("LONG_CALL", "LONG_PUT"):
        raise RecordRefused("INTENT_EXPRESSION_NOT_IN_PILOT_RULE: %r" % i["expression"])
    if i["action"] != "BUY":
        raise RecordRefused("INTENT_ACTION_NOT_IN_PILOT_RULE: %r" % i["action"])
    if i["quantity"] != 1:
        raise RecordRefused("INTENT_QUANTITY_NOT_ONE: pilot is one contract, filled or unfilled")
    risk = i["risk"]
    if not isinstance(risk, dict) or risk.get("approved") is not True:
        raise RecordRefused("INTENT_NOT_RISK_APPROVED: %r" % (risk if isinstance(risk, dict) else type(risk).__name__))
    body = {"kind": "pilot_intent", "expression": i["expression"], "action": i["action"],
            "contract": validate_contract(i["contract"]), "quantity": 1,
            "risk": risk, "expression_rule": i.get("expression_rule"),
            "forecast_ref": {"seq": forecast_receipt["seq"], "entry_hash": forecast_receipt["entry_hash"],
                             "forecast_hash": forecast_receipt["forecast_hash"]},
            "no_best_option_claim": True}
    body["contract_id"] = contract_id(body["contract"])
    body.update(LABELS)
    return body


def assert_prospective(rec: dict) -> None:
    for k in ("evidence_class", "decision_power", "law"):
        v = rec.get(k)
        if isinstance(v, str) and any(bad in v for bad in FORBIDDEN_CLASSES):
            raise RecordRefused("REPLAY_LABEL_ON_PROSPECTIVE_RECORD: %s=%r" % (k, v))
    if rec.get("evidence_class") != EVIDENCE_CLASS or rec.get("decision_power") != DECISION_POWER:
        raise RecordRefused("LABELS_NOT_PROSPECTIVE: %r/%r" % (rec.get("evidence_class"), rec.get("decision_power")))
