"""OBSERVATION_TIME_CONTRACT_V1 -- which instant a sealed packet actually observed.

WHY THIS EXISTS
PULSE-007 repaired both historical anchor defects and left one residual: the
quote fields still disagreed between live and replay. The tape showed why --
same source, same convention, DIFFERENT event. The live packet is stamped
with its SCHEDULED slot but its NBBO was current 1.275-1.669 s later, while
the replay reconstructed at the slot exactly. Between those two instants sat
up to 473 NBBO updates. Nothing was broken; two different moments were being
compared.

WHAT THE PACKET ACTUALLY RECORDS. Read from the six frozen packets, not
assumed:

  scheduled_time        13:45:00.000000Z   the slot the cycle was due
  capture_start         13:45:00.995494Z   IDENTICAL on all six subjects
  capture_end           13:45:01.804905Z   IDENTICAL on all six subjects
  state_complete_time   +17.1s to +31.0s   PER SUBJECT, after enrichment
  known_from            == state_complete_time
  features[f].as_of     per ingredient

capture_start/capture_end are identical across every subject because one
bulk snapshot call served them all: they bound the FETCH, they do not
identify the NBBO event any single subject received. state_complete_time is
17 to 31 seconds later because deep microstructure and the options surface
are gathered after the snapshot; reconstructing a quote there would import
half a minute of tape the live quote field never saw. Neither is the
observation time of the quote.

THE CONTRACT

  AUTHORITATIVE OBSERVATION TIME
      the feature-level `as_of` carried by the QUOTE-DERIVED block. The
      composer stamps every one of those fields with the NBBO event time
      (`qt` in compose.py), so the packet already records, per ingredient,
      the instant it observed. That is the twin's own law -- "a packet is
      NOT synchronous and must not pretend to be; every field keeps its own
      clock" -- and this contract reads that clock instead of overriding it.

  UNANIMITY REQUIRED
      every VALID quote-derived field in the packet must carry the SAME
      as_of. They are all stamped from one variable by one composer, so a
      disagreement means the packet is not what this contract can read, and
      the answer is CONFLICTING, not a guess at which one is right.

  FAIL CLOSED
      no VALID quote-derived field -> MISSING. Disagreement -> CONFLICTING.
      An as_of later than the packet's capture_end -> IMPOSSIBLE, because a
      quote cannot be newer than the fetch that returned it. An as_of older
      than the GOVERNED freshness tolerance for (sip_quote, this session) ->
      STALE_BEYOND_POLICY: it is not an observation of this cycle at all.
      That last case is not hypothetical. NKLA's sealed packet carries
      quote-derived fields stamped 2025-02-26 -- 553 days before the slot --
      because the vendor snapshot for a dead name keeps returning its last
      known quote. The composer correctly marked mid, spread_bps and
      nbbo_size_imbalance STALE for exactly that reason, and then stamped the
      DERIVED fields computed from the same stale mid as VALID. Reusing the
      composer's own policy number, rather than inventing one, refuses it.
      In every case the caller gets a refusal and a reason, never a
      substituted instant.

  WHAT MOVES, AND WHAT DOES NOT
      ONLY the quote ingredient is re-selected at the observation time. Bar
      ingredients stay anchored at the scheduled slot, for two reasons that
      are measurements rather than preferences:
        - each ingredient keeps its own clock, and the bar ingredients carry
          their own (different) as_of values in the same packet;
        - TDOC's quote as_of is 7 MILLISECONDS BEFORE the scheduled slot.
          Moving the whole reconstruction there would drop the 13:44 minute
          bar, which closes exactly at 13:45:00.000, and break the anchor
          result PULSE-007 established. A single packet-level instant is
          wrong in both directions.

  CAUSAL CUTOFF
      the observation time is bounded above by the live packet's own
      capture_end. Nothing after the moment live finished fetching may enter
      a reconstruction, and the bound is asserted rather than assumed.

  WHAT THIS DOES NOT DO
      it does not relax a declaration, widen a tolerance, or change what the
      mirror is allowed to call agreement. It changes WHICH INSTANT the
      historical side reads, so that the comparison is between two readings
      of the same moment. Whether that is the right question to ask is
      Astra's ruling, not this module's.

decision_power: NONE_STATE.
"""
from __future__ import annotations

from datetime import datetime, timezone

from apex.intraday.sessions import Session
from apex.pulse import freshness

OBSERVATION_CONTRACT = "OBSERVATION_TIME_CONTRACT_V1"
QUOTE_SOURCE = "sip_quote"          # the freshness policy key the composer uses

# The fields compose.py stamps with the NBBO event time `qt`. Read from the
# composer, not inferred: mid, spread_bps, spread_rel, quote_age_s,
# touch_size and nbbo_size_imbalance come straight off the quote; the four
# derived ones combine it with an anchor or a session aggregate.
QUOTE_DERIVED_FIELDS = ("mid", "spread_bps", "spread_rel", "quote_age_s",
                        "touch_size", "nbbo_size_imbalance",
                        "prior_close_return_bps", "cash_open_return_bps",
                        "session_range_position", "vwap_distance_bps")
# Never the observation time of a quote, and why.
REJECTED_CANDIDATES = {
    "scheduled_time": "the slot the cycle was due, not a moment anything was read",
    "capture_start": "identical across every subject in the cycle -- it bounds one bulk "
                     "snapshot fetch and cannot identify a per-subject NBBO event",
    "capture_end": "same: the fetch boundary. Used only as the upper causal bound",
    "state_complete_time": "17 to 31 seconds after the snapshot on the observed packets, "
                           "because enrichment runs afterwards. Reconstructing a quote there "
                           "imports tape the live quote field never saw",
    "known_from": "equal to state_complete_time in every observed packet",
}
MISSING, CONFLICTING, IMPOSSIBLE = "MISSING", "CONFLICTING", "IMPOSSIBLE"
STALE_BEYOND_POLICY, RESOLVED = "STALE_BEYOND_POLICY", "RESOLVED"


class ObservationTimeUnavailable(RuntimeError):
    """The packet does not record an unambiguous observation time. Never
    repaired by substitution."""


def _dt(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if "." in s:
        head, _, rest = s.partition(".")
        off = ""
        for i, ch in enumerate(rest):
            if ch in "+-" and i > 0:
                off, rest = rest[i:], rest[:i]
                break
        s = head + "." + rest[:6].ljust(6, "0") + (off or "+00:00")
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def quote_stamps(packet: dict) -> dict:
    """Every distinct as_of carried by a VALID quote-derived field, with the
    fields that carry it. The raw material for the decision, exposed so the
    evidence can show it rather than assert it."""
    out = {}
    for name in QUOTE_DERIVED_FIELDS:
        f = (packet.get("features") or {}).get(name)
        if not isinstance(f, dict) or f.get("q") != "VALID" or not f.get("as_of"):
            continue
        out.setdefault(str(f["as_of"]), []).append(name)
    return {k: sorted(v) for k, v in out.items()}


def observation_time(packet: dict) -> dict:
    """The authoritative observation instant, or a refusal with its reason.

    Returns a provenance record in both cases; `status` is RESOLVED only
    when a single unambiguous instant exists and respects the causal bound."""
    stamps = quote_stamps(packet)
    rec = {"contract": OBSERVATION_CONTRACT,
           "scheduled_time": packet.get("scheduled_time"),
           "capture_start": packet.get("capture_start"),
           "capture_end": packet.get("capture_end"),
           "state_complete_time": packet.get("state_complete_time"),
           "candidate_stamps": stamps,
           "rejected_candidates": REJECTED_CANDIDATES,
           "source": "features[*].as_of of the quote-derived block"}
    if not stamps:
        rec.update(status=MISSING, observation_time=None,
                   reason="no VALID quote-derived field carries an as_of; this packet records "
                          "no NBBO observation and cannot be reconciled on quote fields")
        return rec
    if len(stamps) > 1:
        rec.update(status=CONFLICTING, observation_time=None,
                   reason="quote-derived fields disagree on as_of (%s); the composer stamps them "
                          "from one value, so a disagreement means this packet is not what the "
                          "contract can read" % list(stamps))
        return rec
    obs = list(stamps)[0]
    rec["observation_time"] = obs
    rec["fields_agreeing"] = stamps[obs]
    rec["field_count"] = len(stamps[obs])
    ce = packet.get("capture_end")
    if ce and _dt(obs) > _dt(ce):
        rec.update(status=IMPOSSIBLE, observation_time=None,
                   reason="observation as_of %s is AFTER the packet's capture_end %s; a quote "
                          "cannot be newer than the fetch that returned it" % (obs, ce))
        return rec
    sch = packet.get("scheduled_time")
    rec["offset_from_scheduled_s"] = round((_dt(obs) - _dt(sch)).total_seconds(), 6) if sch else None
    age = round((_dt(ce) - _dt(obs)).total_seconds(), 6) if ce else None
    rec["age_at_capture_end_s"] = age
    rec["within_capture_window"] = bool(
        packet.get("capture_start") and ce
        and _dt(packet["capture_start"]) <= _dt(obs) <= _dt(ce))
    # the GOVERNED bound: the composer's own freshness policy for this source
    # and session. An instant older than that is not an observation of this
    # cycle, whatever the packet stamped on it.
    try:
        session = Session(packet.get("market_session"))
    except ValueError:
        session = None
    if age is not None and session is not None:
        verdict = freshness.is_fresh(QUOTE_SOURCE, session, age)
        rec["freshness_check"] = {"policy": freshness.FRESHNESS_POLICY_VERSION,
                                  "source": QUOTE_SOURCE, "session": session.value,
                                  "age_s": age, **verdict}
        if not verdict["fresh"]:
            rec.update(status=STALE_BEYOND_POLICY, observation_time=None,
                       reason="the unanimous quote-derived as_of is %s, which is %s. It is not an "
                              "observation of this cycle. Note the packet marked the RAW quote "
                              "fields STALE for the same reason and still stamped the DERIVED "
                              "fields VALID." % (obs, verdict["why"]))
            return rec
    rec["status"] = RESOLVED
    rec["reason"] = ("unanimous across %d quote-derived field(s); %s the packet's capture window"
                     % (rec["field_count"],
                        "inside" if rec["within_capture_window"] else "outside (older than) "))
    return rec


def require_observation_time(packet: dict) -> tuple:
    rec = observation_time(packet)
    if rec["status"] != RESOLVED:
        raise ObservationTimeUnavailable("%s: %s" % (rec["status"], rec["reason"]))
    return rec["observation_time"], rec


def contract() -> dict:
    return {
        "contract": OBSERVATION_CONTRACT,
        "authoritative_timestamp": "features[*].as_of of the quote-derived block, required unanimous",
        "quote_derived_fields": list(QUOTE_DERIVED_FIELDS),
        "rejected_candidates": REJECTED_CANDIDATES,
        "what_moves": "the quote ingredient only",
        "what_does_not_move": "bar ingredients stay anchored at the scheduled slot; each "
                              "ingredient keeps its own clock, and one packet-level instant is "
                              "wrong in both directions (TDOC observes 7 ms BEFORE the slot)",
        "causal_cutoff": "observation time <= the live packet's capture_end, asserted",
        "failure_modes": {MISSING: "no VALID quote-derived as_of",
                          CONFLICTING: "quote-derived fields disagree",
                          IMPOSSIBLE: "as_of after capture_end",
                          STALE_BEYOND_POLICY: "as_of older than the governed freshness "
                                               "tolerance for (sip_quote, session)"},
        "freshness_bound": "apex.pulse.freshness -- the composer's own policy, not a new number",
        "does_not": "relax a declaration, widen a tolerance, or change what counts as agreement",
    }
