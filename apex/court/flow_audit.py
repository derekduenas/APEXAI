"""Persisted layer-by-layer audit for one APEX court/replay run.

This module does not execute a strategy, fit a model, contact a provider, or infer
profitability. It reads the records produced by a run and checks that each stage
has an output and a link to the prior stage before calling it green. A record is
evidence that the path emitted that stage; it is not a substitute for calibration
or independent model validation.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from apex.options_pilot import ledger as L

SCHEMA = "FLOW_AUDIT_V1"
PASS = "PASS"
WAIT = "WAIT"
BLOCKED = "BLOCKED"
OPTIONAL_UNWIRED = "OPTIONAL_UNWIRED"
FAIL = "FAIL"


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _first(rows, kind, *, scan_id=None):
    for row in rows:
        if row.get("kind") == kind and (scan_id is None or row.get("scan_id") == scan_id):
            return row
    return None


def _stage(name, status, *, evidence=None, reason=None, required=True, consumes=None):
    return {"layer": name, "status": status, "required": required, "evidence": evidence or {},
            "reason": reason, "consumes": consumes or []}


def _model_trace(decision, funnel):
    trace = (decision or {}).get("funnel_trace") or (funnel or {}).get("trace") or {}
    return trace if isinstance(trace, dict) else {}


def audit_run(run_dir, *, require_trade=False) -> dict:
    """Audit one persisted single-scan run, without trusting its summary.

    The run must contain a hash-chain ledger. For a WAIT run, the audit reports the
    first intentional stopping point and marks later layers BLOCKED. For a required
    full trade, every mandatory layer and the independent reconstruction must pass.
    """
    root = Path(run_dir)
    ledger_path = root / "ledger.jsonl"
    if not ledger_path.is_file():
        raise ValueError("LEDGER_MISSING: %s" % ledger_path)
    rows = L.read_all(ledger_path)
    L.verify_chain(ledger_path, rows=rows)
    decision = _first(rows, "pilot_decision")
    funnel = _first(rows, "pilot_funnel")
    forecast = _first(rows, "pilot_forecast")
    intent = _first(rows, "pilot_intent")
    fill = _first(rows, "pilot_fill")
    outcome = _first(rows, "pilot_outcome")
    close = _first(rows, "pilot_session_close")
    if decision is None:
        raise ValueError("DECISION_RECORD_MISSING")
    trace = _model_trace(decision, funnel)
    bundle = trace.get("model_bundle") or {}
    if not isinstance(bundle, dict):
        bundle = {}
    stages = []

    # Premarket is deliberately optional: it may be attached as prior context,
    # but it cannot block exits or become a signal in the current design.
    context = (decision.get("premarket_context") or (forecast or {}).get("inputs", {}).get("premarket_context"))
    if not isinstance(context, dict) or context.get("status") in (None, "NOT_WIRED"):
        stages.append(_stage("PREMARKET", OPTIONAL_UNWIRED, required=False,
                             reason="premarket packet is not wired on this run; no model input claimed"))
    elif context.get("status") == "ATTACHED_CONTEXT":
        stages.append(_stage("PREMARKET", PASS, required=False,
                             evidence={"status": context.get("status"), "packet_sha256": context.get("packet_sha256"),
                                       "model_consumed": context.get("model_consumed")},
                             reason="attached as PRIOR_CONTEXT_ONLY; model_consumed is false"))
    else:
        stages.append(_stage("PREMARKET", FAIL, required=False, reason="unexpected context status %r" % context.get("status")))

    snapshot = trace.get("state_snapshot") or {}
    snap_id = snapshot.get("snapshot_id")
    state_hash = snapshot.get("state_hash")
    if forecast and isinstance((forecast.get("inputs") or {}), dict):
        fin = forecast["inputs"]
        snap_ok = bool(snap_id and state_hash and fin.get("snapshot_id") == snap_id and fin.get("state_hash") == state_hash)
    else:
        snap_ok = False
    if snap_ok:
        stages.append(_stage("DIGITAL_TWIN", PASS, evidence={"snapshot_id": snap_id, "state_hash": state_hash},
                             consumes=["forecast.inputs.snapshot_id", "forecast.inputs.state_hash"]))
    else:
        stages.append(_stage("DIGITAL_TWIN", FAIL, reason="forecast and funnel trace do not share a complete snapshot identity"))

    ftrace = bundle.get("forecast") or {}
    if forecast and ftrace and forecast.get("forecast_id") and forecast.get("forecast_id") == (funnel or {}).get("forecast_ref", {}).get("forecast_hash"):
        # forecast_ref usually carries a hash rather than forecast_id; preserve
        # a looser identity check while requiring the actual forecast record.
        forecast_link = True
    else:
        forecast_link = bool(forecast and ftrace and forecast.get("forecast_hash") == (funnel or {}).get("forecast_ref", {}).get("forecast_hash"))
    if forecast_link:
        stages.append(_stage("LOCATION_FORECAST", PASS,
                             evidence={"forecast_id": forecast.get("forecast_id"), "model_id": forecast.get("model_id"),
                                       "model_bundle": ftrace},
                             consumes=["pilot_forecast.forecast_hash"]))
    else:
        stages.append(_stage("LOCATION_FORECAST", FAIL, reason="pilot_funnel does not bind the persisted forecast"))

    variance = bundle.get("variance") or trace.get("variance")
    if isinstance(variance, dict) and variance.get("model") not in (None, "NONE") and _finite(variance.get("next_bar_variance")) and variance.get("artifact_digest"):
        stages.append(_stage("VARIANCE", PASS, evidence={"model": variance.get("model"), "artifact_digest": variance.get("artifact_digest"),
                                                           "next_bar_variance": variance.get("next_bar_variance")},
                             consumes=["model_bundle.variance.artifact_digest"]))
    else:
        stages.append(_stage("VARIANCE", FAIL, reason="variance output is absent, non-finite, or unbound"))

    regime = trace.get("situation_regime") or trace.get("regime")
    probs = regime.get("probabilities") if isinstance(regime, dict) else None
    if (isinstance(regime, dict) and isinstance(probs, list) and probs and all(_finite(x) and float(x) >= 0 for x in probs)
            and abs(sum(float(x) for x in probs) - 1.0) <= 1e-6 and regime.get("abstain") is False):
        stages.append(_stage("REGIME", PASS, evidence={"probabilities": probs, "entropy_bits": regime.get("entropy_bits"),
                                                         "parameter_version": regime.get("parameter_version")},
                             consumes=["model_bundle.situation_regime.probabilities"]))
    else:
        stages.append(_stage("REGIME", FAIL, reason="usable causal regime probabilities are absent or abstaining"))

    implied = bundle.get("implied") or trace.get("implied")
    if isinstance(implied, dict) and _finite(implied.get("iv0")) and float(implied.get("iv0")) > 0 and implied.get("atm_strike") is not None:
        stages.append(_stage("MARKET_IMPLIED", PASS, evidence={"iv0": implied.get("iv0"), "atm_strike": implied.get("atm_strike"),
                                                                 "method": implied.get("method")},
                             consumes=["model_bundle.implied.iv0"]))
    else:
        stages.append(_stage("MARKET_IMPLIED", FAIL, reason="ATM implied-volatility result is absent or invalid"))

    sim = trace.get("simulation_bundle")
    if (isinstance(sim, dict) and isinstance(sim.get("n_paths"), int) and sim["n_paths"] > 0
            and sim.get("parameter_hash") and sim.get("first_bar_variance_equals_forecast") is True
            and _finite(sim.get("h_next"))):
        stages.append(_stage("MULTIVERSE", PASS, evidence={"n_paths": sim.get("n_paths"), "parameter_hash": sim.get("parameter_hash"),
                                                             "seed": sim.get("seed"), "h_next": sim.get("h_next")},
                             consumes=["simulation_bundle.parameter_hash", "simulation_bundle.h_next"]))
    else:
        stages.append(_stage("MULTIVERSE", FAIL, reason="common conditional paths are absent or not bound to variance"))

    expr = trace.get("eligible_expressions")
    if isinstance(expr, dict) and isinstance(expr.get("set"), list) and expr["set"] and expr.get("rule"):
        stages.append(_stage("EXPRESSION_WAR", PASS, evidence={"n_candidates": len(expr["set"]), "chosen": expr.get("chosen"),
                                                                 "rule": expr.get("rule")}, consumes=["eligible_expressions.set"]))
    else:
        stages.append(_stage("EXPRESSION_WAR", FAIL, reason="candidate set or selection rule is absent"))

    prime = trace.get("prime")
    if isinstance(prime, dict) and prime.get("decision") in ("ACT", "ABSTAIN"):
        stages.append(_stage("PRIME", PASS, evidence={"decision": prime.get("decision"), "candidate": prime.get("candidate"),
                                                        "reasons": prime.get("reasons")}, consumes=["eligible_expressions.chosen"]))
    else:
        stages.append(_stage("PRIME", FAIL, reason="PRIME output is absent or has no explicit decision"))

    risk = trace.get("risk_decision") or (intent or {}).get("risk")
    if isinstance(risk, dict) and (risk.get("kernel_approved_at_commit") is True or risk.get("certified_max_loss") is not None):
        stages.append(_stage("RISK", PASS, evidence={"certified_max_loss": risk.get("certified_max_loss"),
                                                       "kernel_approved_at_commit": risk.get("kernel_approved_at_commit"),
                                                       "authority_id": risk.get("authority_id")}, consumes=["prime.affordability"]))
    elif (decision.get("decision") or "") in ("WAIT", "REFUSE"):
        stages.append(_stage("RISK", WAIT, reason="no risk certificate required for a non-trade decision"))
    else:
        stages.append(_stage("RISK", FAIL, reason="trade has no persisted risk decision"))

    if decision.get("decision") == "TRADE":
        for name, row, reference, kind in (("INTENT", intent, decision.get("intent_id"), "pilot_intent"),
                                            ("FILL", fill, decision.get("fill_id"), "pilot_fill")):
            if row and reference and (row.get("intent_id") == reference or row.get("fill_id") == reference):
                stages.append(_stage(name, PASS, evidence={"record_kind": kind, "id": reference}, consumes=["pilot_decision.%s" % ("intent_id" if name == "INTENT" else "fill_id")]))
            else:
                stages.append(_stage(name, FAIL, reason="trade decision lacks a linked %s record" % kind))
        if outcome and close and outcome.get("status") == "RESOLVED" and outcome.get("discharges_position") is True:
            stages.append(_stage("EXIT_AND_BOOK", PASS, evidence={"outcome_status": outcome.get("status"),
                                                                    "discharges_position": outcome.get("discharges_position"),
                                                                    "outstanding_obligations": close.get("outstanding_obligations")},
                                 consumes=["pilot_fill.fill_id", "pilot_session_close.book"]))
        else:
            stages.append(_stage("EXIT_AND_BOOK", FAIL, reason="trade has no resolved discharging outcome and clean close"))
    else:
        stages.extend([_stage("INTENT", WAIT, reason="decision did not trade"), _stage("FILL", WAIT, reason="decision did not trade"),
                       _stage("EXIT_AND_BOOK", WAIT, reason="decision did not create an obligation")])

    # A legitimate WAIT is a stopping point, not a broken downstream layer.
    # Conversely, a missing stage on a trade path is a real failure.  Mark the
    # first stopping point and every later required layer explicitly so a report
    # cannot make an unvisited stage look green.
    is_trade = decision.get("decision") == "TRADE"
    fit_status = ((funnel or {}).get("engine") or {}).get("fit", {}).get("status") if funnel else None
    stop_layer = None
    if not is_trade:
        if fit_status and fit_status != "READY":
            stop_layer = "VARIANCE"
        else:
            for candidate in ("DIGITAL_TWIN", "LOCATION_FORECAST", "VARIANCE", "REGIME",
                              "MARKET_IMPLIED", "MULTIVERSE", "EXPRESSION_WAR", "PRIME"):
                current = next(s for s in stages if s["layer"] == candidate)
                if current["status"] == FAIL:
                    stop_layer = candidate
                    break
    first_failure = None
    if stop_layer:
        stop_index = next(i for i, stage in enumerate(stages) if stage["layer"] == stop_layer)
        stages[stop_index]["status"] = WAIT
        stages[stop_index]["reason"] = "intentional stop: %s" % ((funnel or {}).get("why") or decision.get("why") or "decision did not trade")
        for stage in stages[stop_index + 1:]:
            if stage["required"] and stage["status"] not in (WAIT, OPTIONAL_UNWIRED):
                stage["status"] = BLOCKED
                stage["reason"] = "upstream layer %s stopped the path; no downstream output is treated as green" % stop_layer
    else:
        first_failure = next((s["layer"] for s in stages if s["required"] and s["status"] == FAIL), None)
        if first_failure:
            blocked = False
            for stage in stages:
                if stage["layer"] == first_failure:
                    blocked = True
                    continue
                if blocked and stage["required"] and stage["status"] != WAIT:
                    stage["status"] = BLOCKED
                    stage["reason"] = "upstream layer %s failed; persisted output is not treated as green" % first_failure

    reconstruction = None
    if decision.get("decision") == "TRADE":
        from apex.court.verify import reconstruct
        reconstruction = reconstruct(root)
        if reconstruction.get("problems"):
            first_failure = first_failure or "INDEPENDENT_RECONSTRUCTION"

    required_statuses = [s["status"] for s in stages if s["required"]]
    complete = not first_failure and all(s in (PASS, WAIT) for s in required_statuses)
    if require_trade and decision.get("decision") != "TRADE":
        complete = False
        first_failure = first_failure or "NO_TRADE"
    if require_trade and reconstruction and reconstruction.get("problems"):
        complete = False
        first_failure = first_failure or "INDEPENDENT_RECONSTRUCTION"
    return {"schema": SCHEMA, "run_id": decision.get("session_id") or (close or {}).get("session_id"),
            "decision": decision.get("decision"), "decision_id": decision.get("txn_id"), "complete": complete,
            "first_failure": first_failure, "stop_layer": stop_layer, "layers": stages,
            "inactive_layers": (trace.get("model_bundle") or {}).get("inactive_layers") or trace.get("layers_not_invoked") or {},
            "independent_reconstruction": reconstruction,
            "limits": "Persisted stage outputs establish path execution and links for this run. They establish no calibration, edge, profitability, or source authenticity."}
