"""LAYER_RECEIPT_V1 — what one layer did, and whether anything downstream actually read it.

WHY THIS SHAPE. Four rounds of fee review turned on one failure repeated at different depths: a producer records
correctly while a consumer inspects less than it claims. A receipt that merely *declares* what a layer used would
drift the same way. So three facts are kept apart and measured differently:

    AVAILABLE   the layer's required inputs and artifacts exist        (runtime-measured)
    EXECUTED    the real production implementation actually ran        (runtime-measured)
    VALID       its output is well-formed, causal and reconstructible  (runtime-measured)
    USED        a DOWNSTREAM READER consumed THAT EXACT OUTPUT         (discovered from persisted records)

USED is deliberately the hardest. It is NOT set by the producer, and NOT set by a caller naming a consumer. It is
discovered after the fact by finding the output's identity inside a record that a real downstream reader wrote.
Absent that, the disposition is RETRIEVED_UNUSED or NOT_CONSUMED -- the same distinction the TradingView seam had
to make when `USED=0` turned out to be the honest answer.

WHAT A RECEIPT DOES NOT ESTABLISH, stated on every one of them:
  - that every FIELD of a digested object was examined (digesting an object proves identity, not inspection);
  - that consumption contributed anything economically;
  - calibration, edge, or predictive validity of any kind.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = "LAYER_RECEIPT_V1"

# the three runtime-measured states, kept separate
AVAILABLE, UNAVAILABLE = "AVAILABLE", "UNAVAILABLE"
EXECUTED, NOT_EXECUTED = "EXECUTED", "NOT_EXECUTED"
VALID, INVALID, NOT_ASSESSED = "VALID", "INVALID", "NOT_ASSESSED"
# the discovered state
USED, NOT_CONSUMED, RETRIEVED_UNUSED = "USED", "NOT_CONSUMED", "RETRIEVED_UNUSED"

LIMITS = ("A receipt establishes identity, execution and consumption. It does NOT establish that every field of a "
          "digested object was examined, that consumption contributed economically, or anything about calibration, "
          "edge or predictive validity.")


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class ReceiptLog:
    """Append-only, content-addressed. Not cryptographically signed: no signing mechanism is used here, and
    claiming one would be the same overstatement this court exists to catch."""

    def __init__(self, *, run_id: str):
        self.run_id = run_id
        self.receipts: list = []

    def emit(self, *, layer: str, operation: str, scan_id=None, snapshot_id=None, parents=(),
             code_identity=None, model_identity=None,
             available: str = AVAILABLE, why_unavailable=None,
             executed: str = EXECUTED, implementation=None,
             valid: str = NOT_ASSESSED, why_invalid=None,
             inputs=(), output=None, output_id=None,
             started=None, ended=None, availability_cutoff=None,
             refusal=None, fallback=None, declared=None) -> dict:
        body = {
            "schema": SCHEMA, "run_id": self.run_id, "scan_id": scan_id, "snapshot_id": snapshot_id,
            "layer": layer, "operation": operation, "parents": list(parents),
            "code_identity": code_identity, "model_identity": model_identity,
            "implementation": implementation,
            # THREE SEPARATE STATES, never collapsed
            "available": available, "why_unavailable": why_unavailable,
            "executed": executed,
            "valid": valid, "why_invalid": why_invalid,
            # inputs by ID AND content digest -- naming one without the other proves nothing
            "inputs": [dict(i) for i in inputs],
            "output_id": output_id,
            "output_digest": (digest(output) if output is not None else None),
            "started_epoch": started, "ended_epoch": ended, "availability_cutoff_epoch": availability_cutoff,
            "refusal": refusal, "fallback": fallback,
            # DISCOVERED LATER, never asserted here
            "consumption": {"state": NOT_CONSUMED, "evidence": [],
                            "note": "set only by scanning persisted downstream records for this output's identity"},
            "declared_not_measured": declared or {},
            "limits": LIMITS,
        }
        body["receipt_id"] = "rcpt:" + digest({k: v for k, v in body.items() if k != "receipt_id"})[:32]
        self.receipts.append(body)
        return body

    # ---------------------------------------------------------------- consumption, discovered not declared
    def discover_consumption(self, records: list) -> dict:
        """Find each receipt's output identity inside a record a DOWNSTREAM READER wrote.

        The evidence is the record's kind, its id, and the field path where the identity was found. A receipt with
        no such hit stays NOT_CONSUMED -- which is a legitimate, reportable outcome, not a failure to look."""
        found = 0
        for r in self.receipts:
            needles = {k: v for k, v in (("output_digest", r["output_digest"]), ("output_id", r["output_id"]),
                                         ("snapshot_id", r["snapshot_id"])) if v}
            hits = []
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                for name, needle in needles.items():
                    path = _find(rec, needle)
                    if path is not None:
                        hits.append({"consumer_record_kind": rec.get("kind"),
                                     "consumer_record_id": rec.get("txn_id") or rec.get("scan_id"),
                                     "matched_on": name, "field_path": path, "value": str(needle)[:40]})
            if hits:
                r["consumption"] = {"state": USED, "evidence": hits,
                                    "note": "discovered in a persisted record written by the real downstream path"}
                found += 1
            else:
                r["consumption"]["state"] = NOT_CONSUMED
        return {"n_receipts": len(self.receipts), "n_used": found,
                "n_not_consumed": len(self.receipts) - found}

    def describe(self) -> dict:
        return {"schema": SCHEMA, "run_id": self.run_id, "n_receipts": len(self.receipts),
                "receipts": self.receipts, "limits": LIMITS}


def _find(obj, needle, path=""):
    """The field path where `needle` appears, or None. Returns WHERE, so 'it is in there somewhere' is never the
    evidence -- the path is."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if v == needle:
                return "%s.%s" % (path, k)
            got = _find(v, needle, "%s.%s" % (path, k))
            if got:
                return got
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if v == needle:
                return "%s[%d]" % (path, i)
            got = _find(v, needle, "%s[%d]" % (path, i))
            if got:
                return got
    return None
