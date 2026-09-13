"""AVAILABILITY PROVENANCE, and the assumptions that stand in for it.

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

MEASURED_BY_COLLECTOR = "MEASURED_BY_COLLECTOR"
ASSUMED = "ASSUMED"
UNVERIFIED = "PROVENANCE_UNVERIFIED"
ABSENT = "ABSENT"

REPO = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------- the code paths that assign an availability field
# Each entry names the file, the marker that must still be present in it, and what the marker establishes. The
# marker check is what stops this registry from making a claim the code stopped supporting.
ASSIGNMENT_PATHS = {
    "pilot_collection_record": {
        "file": "scripts/options_pilot_collector.py",
        "marker": '"receipt_epoch": time.time()',
        "establishes": ("the collector reads the wall clock at the instant it writes each record, so a record's "
                        "receipt_epoch is a measurement of when this system received the payload"),
        "field": "record.receipt_epoch"},
    "alpaca_bar_receipt": {
        "file": "apex/pulse_options/providers.py",
        "marker": "return self.parse_bars(txt, symbol=symbol, receipt_time=self.clock())",
        "establishes": ("the bars adapter stamps receipt_time from its own clock at the instant the response is "
                        "parsed, so a bar's receipt_time is a measurement"),
        "field": "bar.receipt_time"},
    "alpaca_nbbo_available": {
        "file": "apex/pulse_options/providers.py",
        "marker": "return self.parse_nbbo(txt, receipt_time=self.clock())",
        "establishes": "the NBBO adapter stamps `available` from its own clock at parse time",
        "field": "nbbo.available"},
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
             event_field: str = "event_time", receipt_field: str = "receipt_time") -> dict:
    """The availability provenance of one artifact.

    `assignment_key` names an entry in ASSIGNMENT_PATHS. Supply it only when the artifact really was produced by
    that path. With no key the answer is PROVENANCE_UNVERIFIED, whatever the offsets look like."""
    diag = offset_diagnostics(rows, event_field=event_field, receipt_field=receipt_field)
    out = {"artifact": label, "diagnostics": diag, "acquisition_note": acquisition_note}
    if diag.get("n_with_receipt", 0) == 0:
        out.update(provenance=ABSENT, evidence=None,
                   why="no row carries a receipt field; availability is not present at all")
        return out
    if assignment_key is None:
        out.update(provenance=UNVERIFIED, evidence=None,
                   why=("no assigning code path is named for this artifact, so how its receipts were produced is "
                        "not established. Using them as availability requires a declared, accepted assumption."))
        return out
    if assignment_key not in ASSIGNMENT_PATHS:
        raise ProvenanceRefused("ASSIGNMENT_PATH_UNKNOWN: %r" % (assignment_key,))
    check = _marker_present(assignment_key)
    spec = ASSIGNMENT_PATHS[assignment_key]
    if not check.get("checked") or not check.get("present"):
        out.update(provenance=UNVERIFIED, evidence=check,
                   why=("the named assigning path no longer contains its marker, so the claim it supported cannot "
                        "be made: %s" % spec["file"]))
        return out
    out.update(provenance=MEASURED_BY_COLLECTOR, evidence={**check, "establishes": spec["establishes"],
                                                           "field": spec["field"]},
               why=spec["establishes"])
    return out


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
