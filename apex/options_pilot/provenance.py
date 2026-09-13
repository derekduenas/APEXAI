"""AVAILABILITY PROVENANCE, and the assumptions that stand in for it.

**TWO SEPARATE QUESTIONS, NEVER MERGED.** (1) What does the inspected source say about how a field is assigned?
(2) Were THESE PARTICULAR RECORDS produced by an execution of that path? A marker in today's source answers the
first and says nothing about the second: a fabricated artifact handed over with the same assignment key would look
identical. So `assignment_path_evidence` and `artifact_execution_attribution` are reported apart, and attribution
stays UNVERIFIED unless something actually binds the rows to a run.

**A WRITE-TIME OR PARSE-TIME STAMP IS NOT A NETWORK RECEIPT.** `time.time()` when a record is written measures the
write. `self.clock()` when a response is parsed measures the parse. Both are upper bounds on when the payload
arrived over the network, and neither is that arrival. The distinction is recorded on every classification.

**A PATTERN IN TIMESTAMPS IS NOT EVIDENCE OF HOW THEY WERE PRODUCED.** An earlier version of this check declared a
field MEASURED whenever its receipt offsets varied. That is unsound in both directions: fabricated timestamps can
vary, and a genuine per-record clock read can happen to land on a constant offset. Varied offsets are a
*diagnostic*, never a provenance claim.

Provenance is established ONE way here: by naming the code path that assigns the field, and checking that the path
still says what this module claims it says. Anything else is `PROVENANCE_UNVERIFIED`, which is the default and is
not a failure. It is an honest statement that we do not know, and it is what forces an explicit assumption before
the data may be used as availability.

WHERE THE ASSUMPTION FITS. An artifact whose availability is unverified may still be usable for a diagnostic, but
only under an assumption that is DECLARED here, ACCEPTED by the operator, and BOUND into the run record. This
module declares the assumption text. It does not accept it: acceptance is an operator act, supplied to a run as
authorization, and a run refuses to use assumed availability without it."""
from __future__ import annotations

from pathlib import Path

# assignment_path_evidence
MARKER_PRESENT = "MARKER_PRESENT"
MARKER_ABSENT = "MARKER_ABSENT"
PATH_NOT_CLAIMED = "NO_ASSIGNMENT_PATH_CLAIMED"
PATH_UNREADABLE = "ASSIGNMENT_PATH_UNREADABLE"

# artifact_execution_attribution
VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"

# availability_basis: how THIS RUN obtains the availability it gates on
PER_RECORD_RECORDED = "PER_RECORD_RECORDED"
DERIVED_BY_FORMULA = "DERIVED_BY_FORMULA"
ABSENT = "ABSENT"

ATTRIBUTION_GAP = (
    "Nothing binds these particular records to an execution of the named path. There is no signed run identity on "
    "the rows, no chained run receipt covering the artifact, and no execution id to match. A fabricated artifact "
    "presented with the same assignment key would receive the same assignment-path evidence, so attribution is "
    "UNVERIFIED and must be read as such.")

WHAT_WOULD_ESTABLISH_ATTRIBUTION = [
    "a run identity written into each record by the producing execution, chained and verifiable",
    "a signed manifest produced by the collector at the end of its session, covering the file's digest",
    "a host-side execution log that names the output path and its digest at write time",
]

REPO = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------- the code paths that assign an availability field
# Each entry names the file, the marker that must still be present in it, and what the marker establishes. The
# marker check is what stops this registry from making a claim the code stopped supporting.
ASSIGNMENT_PATHS = {
    "pilot_collection_record": {
        "file": "scripts/options_pilot_collector.py",
        "marker": '"receipt_epoch": time.time()',
        "establishes": ("the source contains a wall-clock read at the moment a record is written, so where that "
                        "code produced a record, its receipt_epoch is the WRITE instant"),
        "field": "record.receipt_epoch",
        "measures": "WRITE_TIME",
        "not": ("network receipt. The payload arrived at or before this instant; how much earlier is not recorded "
                "anywhere in the artifact.")},
    "alpaca_bar_receipt": {
        "file": "apex/pulse_options/providers.py",
        "marker": "return self.parse_bars(txt, symbol=symbol, receipt_time=self.clock())",
        "establishes": ("the source stamps receipt_time from the adapter's clock when the HTTP body is parsed, so "
                        "where that code produced a bar, its receipt_time is the PARSE instant"),
        "field": "bar.receipt_time",
        "measures": "PARSE_TIME",
        "not": "network receipt. Parsing happens after the bytes arrive, so this is an upper bound on arrival."},
    "alpaca_nbbo_available": {
        "file": "apex/pulse_options/providers.py",
        "marker": "return self.parse_nbbo(txt, receipt_time=self.clock())",
        "establishes": "the source stamps `available` from the adapter's clock at parse time",
        "field": "nbbo.available",
        "measures": "PARSE_TIME",
        "not": "network receipt. An upper bound on arrival, not arrival."},
}


class ProvenanceRefused(RuntimeError):
    """An availability claim that cannot be supported, or an assumption used without acceptance."""


def _marker_present(key: str) -> dict:
    spec = ASSIGNMENT_PATHS[key]
    p = REPO / spec["file"]
    try:
        present = spec["marker"] in p.read_text()
    except OSError as e:
        return {"checked": False, "why": "%s: %s" % (type(e).__name__, str(e)[:120])}
    return {"checked": True, "present": present, "file": spec["file"], "marker": spec["marker"]}


def offset_diagnostics(rows: list, *, event_field: str = "event_time", receipt_field: str = "receipt_time") -> dict:
    """Offset statistics. DIAGNOSTIC ONLY: they describe a pattern and prove nothing about how it was produced."""
    have = [r for r in rows if isinstance(r.get(receipt_field), (int, float))
            and not isinstance(r.get(receipt_field), bool)
            and isinstance(r.get(event_field), (int, float))]
    if not have:
        return {"n_rows": len(rows), "n_with_receipt": 0,
                "note": "no row carries a usable receipt; nothing to describe"}
    offsets = sorted({round(r[receipt_field] - r[event_field], 3) for r in have})
    return {"n_rows": len(rows), "n_with_receipt": len(have), "n_distinct_offsets": len(offsets),
            "min_offset_s": offsets[0], "max_offset_s": offsets[-1],
            "constant_offset_s": (offsets[0] if len(offsets) == 1 else None),
            "note": ("DIAGNOSTIC ONLY. A varied offset does not establish that a receipt was measured, and a "
                     "constant one does not establish that it was not. Provenance comes from the assigning code "
                     "path, never from this table.")}


def classify(label: str, rows: list, *, assignment_key: str | None = None, acquisition_note: str | None = None,
             availability_basis: str = PER_RECORD_RECORDED, event_field: str = "event_time",
             receipt_field: str = "receipt_time") -> dict:
    """What is known about one artifact's availability, in three separate parts that are never merged.

    `assignment_path_evidence` -- what the inspected source contains TODAY. Nothing more.
    `artifact_execution_attribution` -- whether THESE ROWS came from an execution of that path. UNVERIFIED unless
        something binds them, which nothing currently does. Supplying an assignment key does not change this.
    `availability_basis` -- how THIS RUN obtains the value it gates on: carried per record, or derived by an
        accepted formula.
    `diagnostics` -- offset statistics, which prove nothing either way."""
    diag = offset_diagnostics(rows, event_field=event_field, receipt_field=receipt_field)
    if diag.get("n_with_receipt", 0) == 0 and availability_basis != DERIVED_BY_FORMULA:
        availability_basis = ABSENT

    if assignment_key is None:
        path_ev = {"status": PATH_NOT_CLAIMED,
                   "why": "no assigning code path is named for this artifact"}
        semantics = {"status": "UNKNOWN", "why": "with no named path, what any timestamp measures is not established"}
    else:
        if assignment_key not in ASSIGNMENT_PATHS:
            raise ProvenanceRefused("ASSIGNMENT_PATH_UNKNOWN: %r" % (assignment_key,))
        spec = ASSIGNMENT_PATHS[assignment_key]
        check = _marker_present(assignment_key)
        if not check.get("checked"):
            path_ev = {"status": PATH_UNREADABLE, "file": spec["file"], "why": check.get("why")}
            semantics = {"status": "UNKNOWN", "why": "the named source could not be read"}
        elif not check.get("present"):
            path_ev = {"status": MARKER_ABSENT, "file": spec["file"], "marker": spec["marker"],
                       "why": ("the named path no longer contains its marker, so the claim it supported cannot be "
                               "made from today's source")}
            semantics = {"status": "UNKNOWN", "why": "the marker that defined the semantics is gone"}
        else:
            path_ev = {"status": MARKER_PRESENT, "file": spec["file"], "marker": spec["marker"],
                       "field": spec["field"], "establishes": spec["establishes"],
                       "scope": ("this establishes only what the inspected source contains now. It does not "
                                 "establish that any particular artifact was produced by running it.")}
            semantics = {"measures": spec["measures"], "not": spec["not"], "field": spec["field"]}

    attribution = {"status": UNVERIFIED, "why": ATTRIBUTION_GAP,
                   "what_would_establish_it": list(WHAT_WOULD_ESTABLISH_ATTRIBUTION)}

    return {"artifact": label,
            "assignment_path_evidence": path_ev,
            "artifact_execution_attribution": attribution,
            "timestamp_semantics": semantics,
            "availability_basis": availability_basis,
            "acquisition_note": acquisition_note,
            "diagnostics": diag,
            "reading": ("availability_basis says where the gating value comes from; attribution says whether these "
                        "rows can be tied to the code that would have produced it. Both must be read; neither "
                        "substitutes for the other.")}


# ---------------------------------------------------------------- computing an assumed availability

ASSUMED_FIELD = "assumed_available_time"
SOURCE_FIELD = "source_receipt_time"


def apply_bulk_pull_availability(rows: list, *, assumption_id: str = "BULK_PULL_AVAILABILITY_V1",
                                 offset_s: float = 60.0, event_field: str = "event_time",
                                 receipt_field: str = "receipt_time") -> dict:
    """COMPUTE the accepted formula rather than trusting whatever the artifact happens to carry.

    The accepted assumption says availability is `event_time + 60`. If the run then gates on each row's supplied
    `receipt_time`, the accepted words and the executed computation are two different things, and a row carrying a
    different receipt would quietly change the assumption. So the derived value is computed here, the source value
    is PRESERVED beside it, and any row whose supplied receipt disagrees with the formula is REFUSED rather than
    silently overridden."""
    out, disagreements = [], []
    for i, r in enumerate(rows):
        ev = r.get(event_field)
        if not isinstance(ev, (int, float)) or isinstance(ev, bool):
            raise ProvenanceRefused("ASSUMED_AVAILABILITY_NEEDS_EVENT_TIME: row %d has %r" % (i, ev))
        derived = float(ev) + float(offset_s)
        src = r.get(receipt_field)
        if isinstance(src, (int, float)) and not isinstance(src, bool) and abs(float(src) - derived) > 1e-6:
            disagreements.append({"row": i, event_field: ev, receipt_field: src, ASSUMED_FIELD: derived,
                                  "delta_s": round(float(src) - derived, 6)})
        out.append({**r, SOURCE_FIELD: src, ASSUMED_FIELD: derived,
                    "availability_assumption": assumption_id, "availability_basis": DERIVED_BY_FORMULA})
    if disagreements:
        raise ProvenanceRefused(
            "ASSUMED_AVAILABILITY_INCONSISTENT: %d row(s) carry a receipt that is not %s + %.0fs, which is what "
            "%s says availability is. The accepted assumption and the values in the artifact disagree, so the run "
            "refuses rather than applying one while the operator accepted the other. First: %r"
            % (len(disagreements), event_field, offset_s, assumption_id, disagreements[:3]))
    return {"rows": out, "assumption_id": assumption_id, "offset_s": offset_s, "n_rows": len(out),
            "derived_field": ASSUMED_FIELD, "source_field_preserved": SOURCE_FIELD,
            "checked": ("every supplied receipt was compared with the formula; a disagreement would have refused "
                        "the run")}


# ---------------------------------------------------------------- declared assumptions (declared here, accepted elsewhere)

ASSUMPTIONS = {
    "BULK_PULL_AVAILABILITY_V1": (
        "A one-minute bar in a bulk historical pull is treated as available at its event time plus sixty seconds. "
        "This is a formula, not a recorded receipt: the artifact carries no evidence of when this system could "
        "first have seen each bar. Any claim resting on it is diagnostic only."),
}


def assumption_text(assumption_id: str) -> str:
    if assumption_id not in ASSUMPTIONS:
        raise ProvenanceRefused("ASSUMPTION_UNKNOWN: %r (declared: %s)" % (assumption_id, sorted(ASSUMPTIONS)))
    return ASSUMPTIONS[assumption_id]


ACCEPTANCE_REQUIRED_FIELDS = ("accepted_by", "accepted_utc", "evaluation_id", "input_manifest_sha256",
                              "code_pin", "scope", "accepted_assumptions")

AUTHORSHIP_BOUNDARY = (
    "PROCEDURAL_UNAUTHENTICATED: this is a JSON file on disk. Nothing here verifies who wrote it, and no test can: "
    "there is no signature, no key and no identity check. What is enforced is that the document EXISTS, names this "
    "evaluation, binds to this input manifest and this code pin, states a scope, and accepts the assumption in its "
    "exact declared words. Treat `accepted_by` as a claim recorded on the run, not as an authenticated identity.")


def validate_acceptance(doc: dict | None, *, evaluation_id: str, manifest_sha256: str, code_pin: str) -> dict:
    """Check the acceptance document's required fields and BIND it to this run.

    An acceptance that does not name this evaluation, this manifest and this code pin could have been written for
    something else and reused. That is the part a file on disk can establish; who typed it is not."""
    if not isinstance(doc, dict):
        raise ProvenanceRefused("ACCEPTANCE_MISSING: no authorization document was supplied")
    missing = [k for k in ACCEPTANCE_REQUIRED_FIELDS if not doc.get(k)]
    if missing:
        raise ProvenanceRefused("ACCEPTANCE_INCOMPLETE: missing or empty %s" % ", ".join(missing))
    if doc["evaluation_id"] != evaluation_id:
        raise ProvenanceRefused("ACCEPTANCE_WRONG_EVALUATION: names %r, this run is %r"
                                % (doc["evaluation_id"], evaluation_id))
    if doc["input_manifest_sha256"] != manifest_sha256:
        raise ProvenanceRefused("ACCEPTANCE_WRONG_MANIFEST: names %s, this run captured %s"
                                % (str(doc["input_manifest_sha256"])[:16], manifest_sha256[:16]))
    if doc["code_pin"] != code_pin:
        raise ProvenanceRefused("ACCEPTANCE_WRONG_CODE_PIN: names %s, this run is at %s"
                                % (str(doc["code_pin"])[:12], str(code_pin)[:12]))
    return {"evaluation_id": doc["evaluation_id"], "input_manifest_sha256": doc["input_manifest_sha256"],
            "code_pin": doc["code_pin"], "scope": doc["scope"],
            "accepted_by_claimed": doc["accepted_by"], "accepted_utc_claimed": doc["accepted_utc"],
            "authorship": AUTHORSHIP_BOUNDARY}


def require_accepted(assumption_id: str, authorization: dict | None) -> dict:
    """REFUSE unless the operator's authorization accepts THIS assumption, in these exact words.

    `authorization` is the operator-supplied document. Nothing in this repository may write it: an acceptance
    authored by the same process that needs it is not an acceptance."""
    text = assumption_text(assumption_id)
    if not isinstance(authorization, dict):
        raise ProvenanceRefused(
            "ASSUMPTION_NOT_ACCEPTED: %s is required and no authorization document was supplied. The run needs an "
            "operator-authored file with accepted_assumptions naming this id and its exact declared text."
            % assumption_id)
    accepted = authorization.get("accepted_assumptions")
    if not isinstance(accepted, list) or not accepted:
        raise ProvenanceRefused("ASSUMPTION_NOT_ACCEPTED: the authorization carries no accepted_assumptions list")
    for entry in accepted:
        if not isinstance(entry, dict) or entry.get("id") != assumption_id:
            continue
        got = entry.get("text")
        if not isinstance(got, str) or " ".join(got.split()) != " ".join(text.split()):
            raise ProvenanceRefused(
                "ASSUMPTION_TEXT_MISMATCH: %s was accepted with different words. An acceptance binds to the exact "
                "declared text, so a reader of the run cannot be shown one assumption while another was agreed."
                % assumption_id)
        return {"assumption_id": assumption_id, "text": text, "accepted": True,
                "accepted_by": authorization.get("accepted_by"),
                "accepted_utc": authorization.get("accepted_utc"),
                "binding": "the id and its exact text are recorded on the run"}
    raise ProvenanceRefused("ASSUMPTION_NOT_ACCEPTED: %s does not appear in accepted_assumptions" % assumption_id)
