"""TRADINGVIEW-CONNECTOR-001 — normalization of a TradingView observation into APEX's own vocabulary.

THE RULE THIS MODULE EXISTS FOR: **retrieving something today does not mean APEX could have known it earlier.**

A candle stamped 2026-09-11T14:30Z that this connection fetched on 2026-09-12 became knowable to APEX at the moment
the response arrived, not at 14:30 the day before. `known_from` is therefore ALWAYS the response receipt for this
connection, never the candle's own time and never a publication date. `historical_availability` says
`NOT_ESTABLISHED` on every observation, and `valid_for_as_of(t)` refuses any `t` earlier than `known_from` with a
named reason. This is the single largest way a data connector silently manufactures hindsight, and it is closed
here by construction rather than by discipline.

The Twin's existing vocabulary is reused rather than duplicated: `apex.pulse.twin` supplies the quality states
(VALID, STALE, UNKNOWN, NOT_AVAILABLE, NOT_ESTIMABLE, PROVIDER_ERROR, SESSION_INAPPLICABLE) and the `Field` type,
whose own invariant already refuses a `known_from` that precedes its `as_of` and refuses a number on an
untrustworthy field. This module adds the connector-specific provenance around those fields.

WHAT THIS IS NOT. TradingView indicators, ratings and recommendations are EXTERNAL CONTEXT. They are not calibrated
probabilities, they are not authorized signals, and nothing here can turn one into either. Every observation from
`get_technicals_rating` and the news tools carries `authority = EXTERNAL_CONTEXT_ONLY` and `calibrated = False`."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from apex.pulse import twin as TW

from .allowlist import EXTERNAL_CONTEXT_TOOLS, PROVIDER, canonical, live_name

SCHEMA_VERSION = "TRADINGVIEW_OBSERVATION_V0"
SOURCE_CLASS = "EXTERNAL_CONTEXT"          # never a price of record; never substituted for another feed
AUTHORITY_CONTEXT = "EXTERNAL_CONTEXT_ONLY"
AUTHORITY_OBSERVATION = "OBSERVATION_ONLY"

ENTITLEMENT_UNKNOWN = "UNKNOWN"
ENTITLEMENT_PROVIDER_STATED_DELAY = "PROVIDER_STATED_DELAY"
# THE TWO *_VERIFIED STATES MEAN **WE** VERIFIED IT, and nothing else may claim them.
#
# The first live smoke labelled bars DELAYED_VERIFIED because the response said "delayed 15+ minutes". That is the
# PROVIDER'S STATEMENT ABOUT ITSELF -- not a measurement, and not a check of the account's entitlement. A verified
# label on an unverified fact is exactly the kind of quiet upgrade this package exists to prevent, so:
#   PROVIDER_STATED_DELAY  the provider says the data is delayed. Recorded verbatim, believed, NOT verified.
#   DELAYED_VERIFIED       WE measured or confirmed it, and `verification_evidence` says how.
#   REALTIME_VERIFIED      likewise.
# `observation()` REFUSES either *_VERIFIED state unless verification evidence is supplied, so the label cannot be
# set by assertion again.
VERIFIED_STATES = ("REALTIME_VERIFIED", "DELAYED_VERIFIED")
ENTITLEMENT_STATES = VERIFIED_STATES + (ENTITLEMENT_PROVIDER_STATED_DELAY, ENTITLEMENT_UNKNOWN)

# Phrases a provider uses to describe its own delay. Matching is evidence-DERIVED: the statement is pulled out of
# the payload the server sent, never typed in by whoever recorded the call.
DELAY_PHRASES = ("delayed", "delay of", "end-of-day feed", "not a live price", "15 minute", "15+ minute")

AVAILABILITY_LAW = (
    "TRADINGVIEW_AVAILABILITY_V0: known_from is the instant THIS connection received the response. A source event "
    "time or publication date is recorded separately and never used as availability. Historical availability is "
    "NOT_ESTABLISHED: previously published data retrieved today is not valid for an earlier as-of decision.")


class NormalizationRefused(ValueError):
    """An observation that cannot be stated honestly. Named, never silent."""


def _utc(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def delay_statement_from_payload(payload) -> str | None:
    """The provider's own delay statement, extracted FROM THE PAYLOAD.

    Derived rather than asserted: if the server did not say it, this returns None and the observation stays
    UNKNOWN. No hand-written label can put a delay claim on a response that never made one."""
    for key in ("notice", "note", "disclaimer", "warning", "message"):
        v = (payload or {}).get(key) if isinstance(payload, dict) else None
        if isinstance(v, str) and any(ph in v.lower() for ph in DELAY_PHRASES):
            return v
    return None


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def observation(*, tool: str, args: dict, payload, request_start: float, response_receipt: float,
                ingestion: float | None = None, symbol: str | None = None, interval: str | None = None,
                units: str | None = None, source_event_time=None, source_publication_time=None,
                entitlement: str = ENTITLEMENT_UNKNOWN, revision: int = 0, quality: str = TW.VALID,
                refusal: str | None = None, completeness: str = "COMPLETE",
                verification_evidence: str | None = None) -> dict:
    """One normalized observation. Every field the operator's brief lists is present or explicitly unknown."""
    if entitlement not in ENTITLEMENT_STATES:
        raise NormalizationRefused("ENTITLEMENT_STATE_UNKNOWN: %r not in %r" % (entitlement, ENTITLEMENT_STATES))
    if entitlement in VERIFIED_STATES and not verification_evidence:
        raise NormalizationRefused(
            "ENTITLEMENT_NOT_VERIFIED: %r claims verification but no verification_evidence was supplied. A "
            "provider's statement about its own feed is PROVIDER_STATED_DELAY, not a verified entitlement."
            % (entitlement,))
    if quality not in TW.QUALITIES:
        raise NormalizationRefused("QUALITY_NOT_IN_VOCABULARY: %r" % (quality,))
    if response_receipt < request_start:
        raise NormalizationRefused("RECEIPT_BEFORE_REQUEST: %.6f < %.6f" % (response_receipt, request_start))
    # ONE TOOL, ONE IDENTITY. The server exposes `mcp__mcp-tradingview__mcp-tv-get-news`; the reviewed name is
    # `get_news`. Keying off the raw string meant a live-spelled call was never recognised as an EXTERNAL_CONTEXT
    # tool and would have been stamped OBSERVATION_ONLY -- a live news headline silently carrying more authority
    # than the same headline fetched under the bare name. The canonical name governs; the live one is kept for
    # provenance so the record still says exactly which wire name was called.
    tool_as_called = str(tool)
    tool = canonical(tool)
    ing = float(response_receipt if ingestion is None else ingestion)
    if ing < response_receipt:
        raise NormalizationRefused("INGESTION_BEFORE_RECEIPT: %.6f < %.6f" % (ing, response_receipt))
    # The provider's own words about its feed, taken from the payload, and kept SEPARATE from any claim we make.
    stated_delay = delay_statement_from_payload(payload)
    if stated_delay and entitlement == ENTITLEMENT_UNKNOWN:
        entitlement = ENTITLEMENT_PROVIDER_STATED_DELAY
    known_from = float(response_receipt)          # THE RULE: availability is receipt on THIS connection
    ctx = tool in EXTERNAL_CONTEXT_TOOLS
    obs = {
        "schema_version": SCHEMA_VERSION,
        "provider": PROVIDER,
        "tool": tool,                              # the CANONICAL reviewed name, not a category
        "tool_as_called": tool_as_called,          # the exact spelling handed to the transport
        "tool_live_name": live_name(tool),         # the spelling this server actually exposes
        "source_class": SOURCE_CLASS,
        "authority": AUTHORITY_CONTEXT if ctx else AUTHORITY_OBSERVATION,
        "calibrated": False,
        "request_args": dict(args or {}),
        "request_args_digest": digest(args or {}),
        "response_digest": digest(payload),
        "symbol": symbol,
        "interval": interval,
        "units": units,
        "revision": int(revision),
        "source_event_time": source_event_time,             # as supplied, verbatim; may be None
        "source_publication_time": source_publication_time,  # as supplied, verbatim; may be None
        "request_start_epoch": float(request_start),
        "request_start_utc": _utc(request_start),
        "response_receipt_epoch": float(response_receipt),
        "response_receipt_utc": _utc(response_receipt),
        "ingestion_epoch": ing,
        "ingestion_utc": _utc(ing),
        "known_from_epoch": known_from,
        "known_from_utc": _utc(known_from),
        "availability_basis": "RESPONSE_RECEIPT_ON_THIS_CONNECTION",
        "historical_availability": "NOT_ESTABLISHED",
        "availability_law": AVAILABILITY_LAW,
        "entitlement": entitlement,
        # THREE SEPARATE FACTS, never collapsed into one label:
        "provider_delay_statement": stated_delay,          # what the PROVIDER said, verbatim, or None
        "latency_measurement": ("NOT_MEASURED: this connector does not measure feed latency. The request/receipt "
                                "instants bound THIS connection's round trip, which is not the data's age."),
        "account_entitlement": ("NOT_ESTABLISHED: the account's market-data entitlement has not been checked. This "
                                "adapter does not verify the plan and does not claim one."),
        "entitlement_verification": verification_evidence,
        "delay_status": ("UNKNOWN: the server does not state a delay or a real-time entitlement for this response"
                         if entitlement == ENTITLEMENT_UNKNOWN else entitlement),
        "quality": quality,
        "completeness": completeness,
        "refusal": refusal,
        "payload": payload,
    }
    if ctx:
        obs["context_note"] = ("TradingView indicators, ratings and headlines are external context. They are not "
                               "calibrated probabilities and are not authorized signals.")
    return obs


def valid_for_as_of(obs: dict, as_of_epoch: float) -> dict:
    """May this observation inform a decision made at `as_of_epoch`? Only if it was already knowable then."""
    kf = obs["known_from_epoch"]
    if float(as_of_epoch) < kf:
        return {"valid": False,
                "why": ("LATE_ARRIVING_INFORMATION: this observation became knowable at %s and the decision instant "
                        "is %s. Retrieving it later does not make it available earlier."
                        % (obs["known_from_utc"], _utc(as_of_epoch))),
                "known_from_utc": obs["known_from_utc"], "as_of_utc": _utc(as_of_epoch)}
    return {"valid": True, "known_from_utc": obs["known_from_utc"], "as_of_utc": _utc(as_of_epoch)}


# ---------------------------------------------------------------------------- bars


BAR_FIELDS = ("open", "high", "low", "close", "volume")
INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
                    "1D": 86400, "1W": 604800}


def normalize_bars(payload, *, symbol: str, interval: str, request_start: float, response_receipt: float,
                   entitlement: str = ENTITLEMENT_UNKNOWN) -> dict:
    """Bars, with partial candles identified and missing values left unknown.

    A bar is COMPLETE only when its close instant is at or before the response receipt AND every price field is a
    real number. A bar whose window has not closed is PARTIAL and is excluded from the completed-bar list -- it is
    kept, labelled, in `partial`, so nothing disappears. A missing volume is UNKNOWN, never 0."""
    if interval not in INTERVAL_SECONDS:
        raise NormalizationRefused("INTERVAL_UNKNOWN: %r; discovered intervals only" % (interval,))
    step = INTERVAL_SECONDS[interval]
    rows = payload if isinstance(payload, list) else (payload or {}).get("bars") or []
    complete, partial, refused = [], [], []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            refused.append({"index": i, "why": "BAR_NOT_AN_OBJECT"})
            continue
        t = r.get("time", r.get("t", r.get("timestamp")))
        if not _is_number(t):
            refused.append({"index": i, "why": "BAR_TIMESTAMP_MISSING_OR_NOT_A_NUMBER: %r" % (t,)})
            continue
        if t > response_receipt:
            refused.append({"index": i, "why": "BAR_FROM_THE_FUTURE: open %s is after the response %s"
                                               % (_utc(t), _utc(response_receipt))})
            continue
        bar = {"open_epoch": float(t), "open_utc": _utc(t), "close_epoch": float(t) + step,
               "close_utc": _utc(float(t) + step), "interval": interval, "symbol": symbol}
        unknown = []
        for f in BAR_FIELDS:
            v = r.get(f, r.get(f[0] if f != "volume" else "v"))
            if _is_number(v):
                bar[f] = float(v)
            else:
                bar[f] = None                       # UNKNOWN, never zero
                unknown.append(f)
        bar["unknown_fields"] = unknown
        closed = (float(t) + step) <= response_receipt
        bar["window_closed"] = closed
        if not closed:
            bar["status"] = "PARTIAL"
            bar["why"] = ("BAR_WINDOW_NOT_CLOSED: the %s window closing at %s had not closed when the response "
                          "arrived at %s" % (interval, bar["close_utc"], _utc(response_receipt)))
            partial.append(bar)
            continue
        if unknown:
            bar["status"] = "INCOMPLETE"
            bar["why"] = "BAR_FIELDS_UNKNOWN: %s (unknown is not zero)" % ", ".join(unknown)
            partial.append(bar)
            continue
        bar["status"] = "COMPLETE"
        complete.append(bar)
    obs = observation(tool="get_ohlcv", args={"symbol": symbol, "interval": interval}, payload=payload,
                      request_start=request_start, response_receipt=response_receipt, symbol=symbol,
                      interval=interval, units="price in the symbol's quote currency; volume in shares/contracts",
                      entitlement=entitlement,
                      quality=(TW.VALID if complete else TW.UNKNOWN),
                      completeness=("COMPLETE" if not partial and not refused else "PARTIAL"))
    obs["bars_complete"] = complete
    obs["bars_partial"] = partial
    obs["bars_refused"] = refused
    obs["n_complete"], obs["n_partial"], obs["n_refused"] = len(complete), len(partial), len(refused)
    obs["completed_bar_rule"] = ("a bar enters completed-bar inputs only when its window closed at or before the "
                                 "response receipt and every price field is a real number")
    return obs


def completed_bars(obs: dict) -> list:
    """The ONLY accessor a completed-bar consumer may use. Partial and incomplete bars are not reachable through it."""
    if canonical(obs.get("tool") or "") != "get_ohlcv":
        raise NormalizationRefused("NOT_A_BARS_OBSERVATION: %r" % (obs.get("tool"),))
    return list(obs.get("bars_complete") or [])


# ---------------------------------------------------------------------------- idempotence and revisions


def observation_key(obs: dict) -> str:
    """Two retrievals of the SAME content are the same observation; a changed payload is a REVISION, not a
    duplicate. The key deliberately excludes the timestamps, so a re-fetch collapses and a correction does not."""
    return digest({"provider": obs["provider"], "tool": obs["tool"], "args": obs["request_args_digest"],
                   "response": obs["response_digest"]})


def merge(existing: list, obs: dict) -> dict:
    """Idempotent insert. Returns the action taken and the resulting list, so a caller cannot silently overwrite."""
    key = observation_key(obs)
    same_request = [o for o in existing if o["request_args_digest"] == obs["request_args_digest"]
                    and o["tool"] == obs["tool"]]
    if any(observation_key(o) == key for o in same_request):
        return {"action": "DUPLICATE_IGNORED", "key": key, "observations": list(existing)}
    if same_request:
        revised = dict(obs)
        revised["revision"] = max(o["revision"] for o in same_request) + 1
        revised["revises"] = [observation_key(o) for o in same_request]
        return {"action": "REVISION_APPENDED", "key": observation_key(revised),
                "revision": revised["revision"], "observations": list(existing) + [revised]}
    return {"action": "APPENDED", "key": key, "observations": list(existing) + [obs]}


# ---------------------------------------------------------------------------- disagreement with another feed


def compare_price(obs: dict, *, other_source: str, other_value, other_as_of=None, field: str = "close") -> dict:
    """TradingView never overwrites or substitutes another source's price. A difference is RECORDED as a
    disagreement, with both sources and both timings, and left visible."""
    mine = None
    if canonical(obs.get("tool") or "") == "get_ohlcv":
        bars = completed_bars(obs)
        mine = bars[-1][field] if bars else None
    if mine is None or not _is_number(other_value):
        return {"comparable": False, "why": "ONE_SIDE_UNKNOWN: a disagreement needs two numbers",
                "tradingview": mine, other_source: other_value, "field": field}
    delta = round(float(mine) - float(other_value), 6)
    return {"comparable": True, "field": field, "tradingview_value": float(mine), "tradingview_known_from": obs["known_from_utc"],
            "other_source": other_source, "other_value": float(other_value), "other_as_of": other_as_of,
            "delta": delta, "agrees": abs(delta) < 1e-9,
            "resolution": ("NONE: both values are retained with their sources and timings. TradingView is external "
                           "context and never replaces a feed of record.")}
