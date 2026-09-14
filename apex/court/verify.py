"""INDEPENDENT RECONSTRUCTION — from persisted artifacts only.

It reads the ledger file and the receipt file and rebuilds the chain itself. It does NOT import the runner, call
its summary, or trust `court_run.json`'s conclusions: re-invoking the producer's own summariser would verify
nothing, which is the same mistake as a consumer that inspects less than it claims."""
from __future__ import annotations

import json
import pathlib
import hashlib
import math
from decimal import Decimal


def _audit_execution(rows):
    """Independent, single-scan long-option accounting; no production imports.

    Fees are checked for identity and component arithmetic, not re-derived from
    the broker tariff. A self-consistent rewritten chain needs an external anchor.
    Model correctness and source authenticity are outside this verifier's scope.
    """
    problems = []
    result = {"problems": problems, "chain_verified": False,
              "scope": "SINGLE_SCAN_LONG_OPTION_EXECUTION",
              "fee_tariff_recomputed": False, "model_correctness_verified": False}
    if not rows:
        problems.append("EMPTY_LEDGER")
        return result
    previous = "GENESIS"
    for seq, row in enumerate(rows, 1):
        body = {k: v for k, v in row.items() if k != "entry_hash"}
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest()
        if row.get("prev_hash") != previous or row.get("entry_hash") != digest:
            problems.append("CHAIN_INVALID:%s" % seq)
        previous = row.get("entry_hash")
    if problems:
        return result
    result["chain_verified"] = True
    by = lambda kind: [(i, r) for i, r in enumerate(rows, 1) if r.get("kind") == kind]
    for kind in ("pilot_forecast", "pilot_decision", "pilot_intent", "pilot_funnel"):
        if len(by(kind)) > 1:
            problems.append("UNSUPPORTED_MULTIPLE_RECORDS:" + kind)
    fills = [(i, r) for i, r in by("pilot_fill") if r.get("status") == "FILLED"]
    if len(fills) > 1:
        problems.append("UNSUPPORTED_MULTIPLE_FILLS")
    if problems:
        return result

    def reference(owner_seq, ref, kind):
        seq = ref.get("seq") if isinstance(ref, dict) else None
        if type(seq) is not int or not 1 <= seq < owner_seq:
            raise ValueError("REFERENCE_ORDER:" + kind)
        row = rows[seq - 1]
        if row.get("kind") != kind or ref.get("entry_hash") != row.get("entry_hash"):
            raise ValueError("REFERENCE_BINDING:" + kind)
        return row

    def number(value, label):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("UNKNOWN_OR_INVALID_NUMBER:" + label)
        return Decimal(str(value))

    def equal(actual, expected, label):
        if abs(number(actual, label) - expected) > Decimal("0.000001"):
            raise ValueError("VALUE_MISMATCH:" + label)

    def fee(record, identity, side, quantity):
        if record.get("fee_identity") != identity or not identity:
            raise ValueError("FEE_IDENTITY_MISMATCH:" + side)
        if record.get("side") != side or record.get("contracts") != quantity:
            raise ValueError("FEE_SIDE_OR_QUANTITY:" + side)
        components = record.get("components")
        if not isinstance(components, dict) or not components:
            raise ValueError("FEE_COMPONENTS_MISSING:" + side)
        amounts = [number(v, "fee_component") for v in components.values()]
        total = sum(amounts, Decimal(0))
        if any(amount < 0 for amount in amounts):
            raise ValueError("NEGATIVE_FEE:" + side)
        equal(record.get("total"), total, "fee_total_" + side)
        return total

    try:
        resolved = [(i, r) for i, r in by("pilot_outcome") if r.get("discharges_position")]
        if not fills:
            if resolved:
                raise ValueError("ORPHAN_DISCHARGING_OUTCOME")
            result.update(pnl_recomputed=0.0, open_positions=0)
            return result
        fill_seq, fill = fills[0]
        intent = reference(fill_seq, fill.get("intent_ref"), "pilot_intent")
        intent_seq = fill["intent_ref"]["seq"]
        forecast = reference(intent_seq, intent.get("forecast_ref"), "pilot_forecast")
        if intent.get("forecast_ref", {}).get("forecast_id") != forecast.get("forecast_id"):
            raise ValueError("FORECAST_ID_MISMATCH")
        result["selection_rule"] = intent.get("expression_rule")
        if intent.get("funnel_ref"):
            funnel = reference(intent_seq, intent["funnel_ref"], "pilot_funnel")
            proposal = funnel.get("proposal") or {}
            for key in ("contract", "expression", "action", "quantity", "expression_rule", "reference_ask"):
                if proposal.get(key) != intent.get(key):
                    raise ValueError("PROPOSAL_INTENT_MISMATCH:" + key)
            if funnel.get("decision") != "TRADE" or funnel.get("scan_id") != intent.get("scan_id"):
                raise ValueError("FUNNEL_DECISION_BINDING")
            contract = proposal.get("contract") or {}
            canonical = {key: contract.get(key) for key in ("symbol", "expiration", "right")}
            canonical["strike"] = float(contract["strike"])
            canonical.update({key: proposal.get(key) for key in
                              ("expression", "action", "quantity", "expression_rule")})
            canonical["reference_ask"] = float(proposal["reference_ask"])
            digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                                              allow_nan=False).encode()).hexdigest()
            if intent["funnel_ref"].get("proposal_digest") != digest:
                raise ValueError("PROPOSAL_DIGEST_MISMATCH")
            result["funnel_link_verified"] = True
        elif by("pilot_funnel"):
            raise ValueError("FUNNEL_REFERENCE_MISSING")
        for key in ("intent_id", "contract_id", "contract", "scan_id", "session_id"):
            if fill.get(key) != intent.get(key):
                raise ValueError("FILL_INTENT_MISMATCH:" + key)
        if intent.get("action") != "BUY" or intent.get("expression") not in ("LONG_CALL", "LONG_PUT"):
            raise ValueError("UNSUPPORTED_EXPRESSION")
        quantity = fill.get("quantity_filled")
        if type(quantity) is not int or quantity <= 0 or quantity > intent.get("quantity", 0):
            raise ValueError("INVALID_FILL_QUANTITY")
        multiplier = number(intent["risk"]["certificate"]["derivation"]["multiplier"], "multiplier")
        if multiplier <= 0:
            raise ValueError("INVALID_MULTIPLIER")
        price = number(fill.get("price"), "entry_price")
        if price < 0:
            raise ValueError("NEGATIVE_ENTRY_PRICE")
        equal(fill.get("quote_observed", {}).get("ask"), price, "entry_ask")
        debit = price * multiplier * quantity
        entry_fee = fee(fill.get("fees_entry") or {}, intent.get("fees"), "BUY", quantity)
        equal(fill.get("net_debit"), debit, "entry_debit")
        equal(fill.get("cashflow_entry"), -debit - entry_fee, "entry_cashflow")
        if len(resolved) > 1:
            raise ValueError("DUPLICATE_DISCHARGE")
        result.update(open_positions=0 if resolved else 1, pnl_recomputed=None,
                      gross_recomputed=None, entry_debit=float(debit))
        if resolved:
            outcome_seq, outcome = resolved[0]
            original = reference(outcome_seq, outcome.get("fill_ref"), "pilot_fill")
            if original != fill:
                raise ValueError("OUTCOME_WRONG_FILL")
            for key in ("fill_id", "intent_id", "contract_id", "scan_id", "session_id"):
                if outcome.get(key) != fill.get(key):
                    raise ValueError("OUTCOME_FILL_MISMATCH:" + key)
            exit_price = number(outcome.get("exit_price"), "exit_price")
            if exit_price < 0:
                raise ValueError("NEGATIVE_EXIT_PRICE")
            equal(outcome.get("exit_quote_observed", {}).get("bid"), exit_price, "exit_bid")
            credit = exit_price * multiplier * quantity
            exit_fee = fee(outcome.get("fees_exit") or {}, intent.get("fees"), "SELL", quantity)
            equal(outcome.get("cashflow_exit"), credit - exit_fee, "exit_cashflow")
            gross = credit - debit
            net = gross - entry_fee - exit_fee
            equal(outcome.get("gross_pnl"), gross, "gross_pnl")
            equal(outcome.get("pnl"), net, "net_pnl")
            result.update(pnl_recomputed=float(net), gross_recomputed=float(gross))
        closes = by("pilot_session_close")
        if closes:
            book = closes[-1][1].get("book") or {}
            equal(book.get("n_positions"), Decimal(result["open_positions"]), "book_positions")
            equal(book.get("open_cost"), debit if not resolved else Decimal(0), "book_open_cost")
            if resolved:
                equal(book.get("session_realized_pnl"), net, "book_session_pnl")
        else:
            raise ValueError("SESSION_CLOSE_MISSING")
    except (ValueError, KeyError, TypeError) as exc:
        problems.append(str(exc))
    return result


def reconstruct(run_dir) -> dict:
    d = pathlib.Path(run_dir)
    try:
        def reject_constant(value):
            raise ValueError("NON_FINITE_JSON:" + value)

        def finite_float(value):
            parsed = float(value)
            if not math.isfinite(parsed):
                reject_constant(value)
            return parsed

        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("DUPLICATE_JSON_KEY:" + key)
                result[key] = value
            return result

        rows = [json.loads(x, parse_constant=reject_constant, parse_float=finite_float,
                           object_pairs_hook=unique_keys)
                for x in (d / "ledger.jsonl").read_text().splitlines() if x.strip()]
        if any(not isinstance(r, dict) for r in rows):
            raise ValueError("LEDGER_RECORD_NOT_OBJECT")
        receipts = json.loads((d / "court_run.json").read_text())["receipts"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"run_dir": str(d), "problems": ["INPUT_INVALID:" + str(exc)]}
    by = lambda k: [r for r in rows if r.get("kind") == k]
    out = {"run_dir": str(d), "n_ledger_rows": len(rows), "problems": []}
    out["execution_verification"] = _audit_execution(rows)
    out["problems"].extend(out["execution_verification"]["problems"])
    if out["problems"]:
        return out

    dec = (by("pilot_decision") or [None])[0]
    fc = (by("pilot_forecast") or [None])[0]
    it = (by("pilot_intent") or [None])[0]
    fl = (by("pilot_fill") or [None])[0]
    ocs = by("pilot_outcome")

    # ---- snapshot and receipt links
    snap_id = ((fc or {}).get("inputs") or {}).get("snapshot_id")
    out["snapshot_id"] = snap_id
    out["snapshot_id_in_decision"] = (((dec or {}).get("funnel_trace") or {}).get("state_snapshot") or {}).get("snapshot_id")
    if snap_id and out["snapshot_id_in_decision"] != snap_id:
        out["problems"].append("DECISION_DOES_NOT_NAME_THE_SNAPSHOT")
    out["receipts_linked_to_snapshot"] = sum(1 for r in receipts if r.get("snapshot_id") == snap_id)

    # ---- code / model identity
    out["model_identity"] = {k: (fc or {}).get(k) for k in ("model_id", "model_hash", "params_hash",
                                                            "artifact_digest", "validation_status")}
    # ---- candidate exclusions and selection
    t = (dec or {}).get("funnel_trace") or {}
    out["selection"] = {"expression": (it or {}).get("expression"), "rule": (it or {}).get("expression_rule"),
                        "candidate_set": (t.get("eligible_expressions") or {}),
                        "no_best_option_claim": (it or {}).get("no_best_option_claim")}
    # ---- proposal / intent binding
    out["intent_binding"] = {"intent_id": (it or {}).get("intent_id"),
                             "contract_id": (it or {}).get("contract_id"),
                             "fee_identity_fields": sorted((it or {}).get("fees") or {}),
                             "risk_provenance": ((it or {}).get("risk") or {}).get("risk_provenance"),
                             "certified_max_loss": ((it or {}).get("risk") or {}).get("certified_max_loss")}
    if it and not out["intent_binding"]["risk_provenance"]:
        out["problems"].append("INTENT_CARRIES_NO_RISK_PROVENANCE")
    # ---- reservation / exposure
    out["reservation"] = {"envelope": ((it or {}).get("risk") or {}).get("envelope"),
                          "book_state_hash": ((it or {}).get("risk") or {}).get("book_state_hash")}
    # ---- fill and exit
    out["fill"] = {"status": (fl or {}).get("status"), "price": (fl or {}).get("fill_price") or (fl or {}).get("price"),
                   "fees_entry": ((fl or {}).get("fees_entry") or {}).get("total")}
    out["resolved_exit"] = next(({"status": o.get("status"), "pnl": o.get("pnl"),
                                  "pnl_status": o.get("pnl_status")} for o in ocs if o.get("discharges_position")), None)
    out["exits"] = [{"status": o.get("status"), "exit_price": o.get("exit_price"),
                     "gross_pnl": o.get("gross_pnl"), "pnl": o.get("pnl"), "pnl_status": o.get("pnl_status"),
                     "fees_exit": (o.get("fees_exit") or {}).get("total"),
                     "discharges": o.get("discharges_position")} for o in ocs]
    # ---- fees and P&L, recomputed from the parts rather than read from a summary
    resolved = [o for o in ocs if o.get("discharges_position")]
    if resolved:
        o = resolved[0]
        g, fe, fx = o.get("gross_pnl"), out["fill"]["fees_entry"], (o.get("fees_exit") or {}).get("total")
        if None not in (g, fe, fx):
            recomputed = out["execution_verification"]["pnl_recomputed"]
            out["pnl_recomputed"] = recomputed
            out["pnl_agrees"] = (abs(recomputed - float(o.get("pnl"))) < 1e-9) if o.get("pnl") is not None else None
            if out["pnl_agrees"] is False:
                out["problems"].append("PNL_DISAGREES: recomputed %r vs recorded %r" % (recomputed, o.get("pnl")))
        else:
            out["pnl_recomputed"] = None
            out["pnl_agrees"] = None
            out["problems"].append("PNL_NOT_RECONSTRUCTIBLE: a component is unknown (unknown is not zero)")
    # ---- remaining exposure and obligations
    out["remaining_obligation"] = {"open_position": bool(fl and not resolved),
                                   "unresolved_outcomes": [o.get("status") for o in ocs if not o.get("discharges_position")]}
    out["decision"] = (dec or {}).get("decision")
    out["external_inputs_used"] = (dec or {}).get("external_inputs_used")
    out["reconstructed_without_calling_the_runner"] = True
    return out


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Reconstruct a single-scan court run from persisted artifacts")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    result = reconstruct(args.run_dir)
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(1 if result["problems"] else 0)
