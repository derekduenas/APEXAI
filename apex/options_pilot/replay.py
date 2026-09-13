"""THE FAIL-CLOSED RECORDED-DATA ROUTE (OPERATING-LOOP-001 item 5).

THE FINDING THIS ANSWERS. The boundary could not represent replay: `records.PROVENANCE` was
`("SYNTHETIC_FIXTURE", "LIVE_FEED")` and `assert_prospective` refused the replay labels outright. So the loop
demonstration ran RECORDED data through a boundary labelled `LIVE_FEED`, and every record it wrote claims
`PROSPECTIVE_PAPER` evidence about a session that had already happened. `scripts/trace_replay_one.py` names the same
defect in its own header. The route below fixes it WITHOUT touching the prospective route: `assert_prospective` is
unchanged, and a replay record cannot pass it.

FAIL CLOSED, AND SELECTED BY NAME.
    * A replay boundary exists only if the caller constructs a `ReplayAuthorization` and hands it over. There is no
      default, no flag that flips a live boundary into replay, and no inference from the data.
    * The authorization must name the recorded inputs BY DIGEST and the recorded window. An authorization with no
      digests is refused: an unnamed input cannot be reproduced or audited.
    * Records carry `evidence_class = HISTORICAL_DEVELOPMENT_REPLAY`, `decision_power = NONE_REPLAY`, and the three
      exclusion flags sealed to exactly False.
    * A replay ledger and a prospective ledger are never the same file (`Boundary._assert_ledger_route`).
    * `records.assert_live_authorizable` and `records.prospective_only` are the tested exclusion points for live
      authorization, promotion and prospective aggregation.

RECORDED INPUTS ARE INVISIBLE BEFORE THEIR RECORDED AVAILABILITY. `RecordedInputs` answers only with data whose
recorded availability instant is at or before the clock. A datum's EVENT time and its AVAILABILITY time are kept
separately, and it is availability that gates visibility -- an observation that existed at 13:45 but did not reach a
consumer until 13:46 is invisible at 13:45:30, which is the only honest way to replay a decision."""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import boundary as B
from . import instant as I
from . import records as R
from .fees import UNVERIFIED_FEES

REPLAY_PROVENANCE = "RECORDED_REPLAY"
REPLAY_EXECUTION_MODE = "RECORDED_REPLAY_ORCHESTRATION"

REPLAY_ROUTE_POLICY = (
    "REPLAY_ROUTE_V1: recorded-data execution is a separate route selected by an explicit ReplayAuthorization naming "
    "the recorded inputs by digest. Its records carry HISTORICAL_DEVELOPMENT_REPLAY / NONE_REPLAY and are sealed "
    "ineligible for live authorization, promotion and prospective-results aggregation. The prospective route is "
    "unchanged: a replay record cannot pass assert_prospective, and the two classes never share a ledger.")


class ReplayRefused(RuntimeError):
    """The replay route was selected without the evidence that makes it legible. Fail closed."""


class ReplayAuthorization:
    """The explicit, named selection of the recorded-data route."""

    def __init__(self, *, reason: str, input_digests: dict, recorded_window_utc: tuple, operator_note: str | None = None):
        if not reason or not isinstance(reason, str):
            raise ReplayRefused("REPLAY_REASON_REQUIRED: say what this replay is for")
        if not input_digests or not isinstance(input_digests, dict):
            raise ReplayRefused("REPLAY_INPUT_DIGESTS_REQUIRED: recorded inputs must be named by digest, or the run "
                                "cannot be reproduced or audited")
        for k, v in input_digests.items():
            if not isinstance(v, str) or len(v) < 32:
                raise ReplayRefused("REPLAY_INPUT_DIGEST_INVALID: %r -> %r" % (k, v))
        if not (isinstance(recorded_window_utc, (tuple, list)) and len(recorded_window_utc) == 2):
            raise ReplayRefused("REPLAY_WINDOW_REQUIRED: (start_utc, end_utc) of the recorded data")
        self.reason = reason
        self.input_digests = dict(input_digests)
        self.window = (str(recorded_window_utc[0]), str(recorded_window_utc[1]))
        self.operator_note = operator_note
        self.verified_inputs: dict | None = None      # set only by verify_inputs(), and required before a run

    @property
    def digest(self) -> str:
        """One identity for this authorization, so a run can be bound to it without restating it."""
        return R.canonical_hash({"reason": self.reason, "input_digests": self.input_digests,
                                 "recorded_window_utc": list(self.window)})

    def verify_inputs(self, paths: dict) -> dict:
        """BIND THE AUTHORIZATION TO THE BYTES. Recompute each named input's digest from the file that will actually
        be read and refuse any mismatch, any missing label and any unnamed extra.

        Without this the authorization records what someone SAID the inputs were. Declaring a digest is a claim;
        recomputing it is evidence, and only evidence may gate a run."""
        missing = sorted(set(self.input_digests) - set(paths))
        extra = sorted(set(paths) - set(self.input_digests))
        if missing or extra:
            raise ReplayRefused("REPLAY_INPUT_SET_MISMATCH: declared but not supplied %r; supplied but not declared %r"
                                % (missing, extra))
        out = {}
        for label in sorted(paths):
            p = Path(paths[label])
            if not p.is_file():
                raise ReplayRefused("REPLAY_INPUT_MISSING: %s -> %s" % (label, p))
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            actual = h.hexdigest()
            if actual != self.input_digests[label]:
                raise ReplayRefused("REPLAY_INPUT_DIGEST_MISMATCH: %s declared %s, on disk %s (%s). The recorded "
                                    "inputs are not the ones this authorization names."
                                    % (label, self.input_digests[label][:16], actual[:16], p))
            out[label] = {"path": str(p), "sha256": actual, "bytes": p.stat().st_size}
        self.verified_inputs = out
        return out

    def describe(self) -> dict:
        return {"route": REPLAY_PROVENANCE, "policy": REPLAY_ROUTE_POLICY, "reason": self.reason,
                "authorization_digest": self.digest,
                "inputs_verified": (self.verified_inputs if self.verified_inputs is not None
                                    else "NOT_VERIFIED: verify_inputs() was never called against the files on disk"),
                "input_digests": self.input_digests, "recorded_window_utc": list(self.window),
                "operator_note": self.operator_note,
                "excluded_from": ["live authorization", "promotion", "prospective-results aggregation"],
                "trading_authority": "NONE: this route cannot authorize anything"}


def replay_boundary(ledger, *, clock, risk_authority, session_id: str, release: str, authorization: ReplayAuthorization,
                    fee_schedule=UNVERIFIED_FEES, require_verified_inputs: bool = True, **kw) -> B.Boundary:
    """Build the ONE boundary the recorded route may use. Every other constructor path stays prospective."""
    if not isinstance(authorization, ReplayAuthorization):
        raise ReplayRefused("REPLAY_AUTHORIZATION_REQUIRED: the recorded route is selected explicitly, never inferred")
    if require_verified_inputs and authorization.verified_inputs is None:
        raise ReplayRefused("REPLAY_INPUTS_NOT_VERIFIED: call authorization.verify_inputs({label: path}) first. A "
                            "declared digest is a claim; a recomputed one is evidence, and the run is gated on "
                            "evidence.")
    bd = B.Boundary(ledger, clock=clock, provenance=REPLAY_PROVENANCE, risk_authority=risk_authority,
                    session_id=session_id, release=release, fee_schedule=fee_schedule, **kw)
    bd.replay_authorization = authorization
    if not bd.replay:
        raise ReplayRefused("REPLAY_LABELS_NOT_APPLIED: the boundary did not take the replay route")
    return bd


def assert_excluded_from_prospective_results(rows: list) -> dict:
    """The aggregation guard: prove that no replay row can enter a prospective results set."""
    kept = R.prospective_only(rows)
    dropped = [r for r in rows if R.is_replay(r)]
    return {"n_total": len(rows), "n_prospective": len(kept), "n_replay_excluded": len(dropped),
            "classes_kept": sorted({r.get("evidence_class") for r in kept if r.get("evidence_class")}),
            "classes_excluded": sorted({r.get("evidence_class") for r in dropped if r.get("evidence_class")})}


# ---------------------------------------------------------------------------- recorded inputs


class RecordedInputs:
    """Recorded observations with an EVENT instant and a separate AVAILABILITY instant. Nothing is visible before its
    recorded availability, and the source's own timestamps are preserved verbatim beside the canonical ones."""

    def __init__(self, items: list, *, event_field: str = "event_time", available_field: str = "available_time"):
        self.items = []
        for i, it in enumerate(items):
            if event_field not in it or available_field not in it:
                raise ReplayRefused("RECORDED_ITEM_MISSING_INSTANTS: item %d needs %r and %r" % (i, event_field, available_field))
            ev, av = it[event_field], it[available_field]
            ev_us, av_us = I.canonical_micros(ev, field="event"), I.canonical_micros(av, field="available")
            if av_us < ev_us:
                raise ReplayRefused("RECORDED_AVAILABLE_BEFORE_EVENT: item %d available %s < event %s"
                                    % (i, I.canonical_utc(av), I.canonical_utc(ev)))
            self.items.append({"payload": it, "event_us": ev_us, "available_us": av_us,
                               "source_timestamps": {event_field: ev, available_field: av}})
        self.items.sort(key=lambda x: (x["available_us"], x["event_us"]))
        self.event_field, self.available_field = event_field, available_field

    def visible(self, now) -> list:
        """Everything whose recorded AVAILABILITY is at or before `now`, in event order. Nothing else exists yet."""
        now_us = I.canonical_micros(now, field="now")
        return [x["payload"] for x in sorted((y for y in self.items if y["available_us"] <= now_us),
                                             key=lambda y: y["event_us"])]

    def hidden(self, now) -> list:
        now_us = I.canonical_micros(now, field="now")
        return [x["payload"] for x in self.items if x["available_us"] > now_us]

    def availability_epochs(self) -> list:
        """The instants at which new data becomes visible: the DATA_AVAILABLE events the lifecycle should schedule."""
        return sorted({I.from_micros(x["available_us"]) for x in self.items})

    def describe(self) -> dict:
        return {"n_items": len(self.items), "event_field": self.event_field, "available_field": self.available_field,
                "visibility_rule": ("a recorded observation is invisible until its recorded availability instant; the "
                                    "event instant and the availability instant are preserved separately"),
                "first_available_utc": (I.canonical_utc(I.from_micros(self.items[0]["available_us"])) if self.items else None),
                "last_available_utc": (I.canonical_utc(I.from_micros(self.items[-1]["available_us"])) if self.items else None)}
