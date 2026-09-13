"""INDEPENDENT RECONSTRUCTION — from persisted artifacts only.

It reads the ledger file and the receipt file and rebuilds the chain itself. It does NOT import the runner, call
its summary, or trust `court_run.json`'s conclusions: re-invoking the producer's own summariser would verify
nothing, which is the same mistake as a consumer that inspects less than it claims."""
from __future__ import annotations

import json
import pathlib


def reconstruct(run_dir) -> dict:
    d = pathlib.Path(run_dir)
    rows = [json.loads(x) for x in (d / "ledger.jsonl").read_text().splitlines() if x.strip()]
    receipts = json.loads((d / "court_run.json").read_text())["receipts"]
    by = lambda k: [r for r in rows if r.get("kind") == k]
    out = {"run_dir": str(d), "n_ledger_rows": len(rows), "problems": []}

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
            recomputed = round(g - fe - fx, 6)
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
