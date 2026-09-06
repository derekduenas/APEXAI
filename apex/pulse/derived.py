"""DERIVED_FIELD_CONTRACT_V1 -- a field is no more trustworthy than its inputs.

WHY THIS EXISTS (DERIVED-FIELD-STALENESS-001)
NKLA's sealed packet of 2026-09-01 carried a quote from 2025-02-26. The
composer applied its freshness policy and correctly marked the RAW quote
fields STALE:

    mid                 STALE   "sip_quote: 47738725.6s exceeds the 120s
    spread_bps          STALE    REGULAR tolerance"
    nbbo_size_imbalance STALE

and then computed four more fields from that same refused mid and marked
them VALID:

    quote_age_s            VALID    47738725.63
    prior_close_return_bps VALID    -2869.94
    cash_open_return_bps   VALID    -2039.13
    vwap_distance_bps      VALID    -910.31
    session_range_position VALID    0.108

A consumer filtering on quality would have discarded the price and kept a
-2869.94 bps return computed from it. The verdict was applied where the
value was read and never travelled to what was built from it.

THE CONTRACT
A derived field inherits the trustworthiness of every ingredient it
consumes. The dependency of each derived field on each ingredient is
declared here, in data, so the rule can be checked rather than believed,
and so a future consumer can ask WHICH ingredient failed instead of
pattern-matching on field names.

  VALID          only when every required ingredient is VALID.
  STALE          when every ingredient has a value but at least one is
                 STALE. The value is omitted (see REPRESENTATION).
  ABSENT         when at least one ingredient has no value at all. The
                 dependent takes the first matching reason in
                 ABSENCE_PRECEDENCE, so PROVIDER_ERROR is not flattened
                 into NOT_AVAILABLE and neither is flattened into STALE.
  INVALID INPUT  a raw ingredient that is not a finite real number is
                 NOT_ESTIMABLE at the ingredient, and propagates as an
                 absence. bool is not a number.
  INDEPENDENT    a field whose ingredients are all fine is untouched. A
                 stale QUOTE must not contaminate prior_close, which is
                 read from the prior daily bar and shares nothing with it,
                 and a stale ANCHOR must not contaminate the current
                 session's cash open. Enforced from both ends: each caller
                 passes exactly its declared ingredients, and derive()
                 refuses any ingredient that was not declared.
  SESSION        SESSION_INAPPLICABLE is decided by the session, before
                 ingredients are consulted, and is never overwritten by
                 ingredient propagation.

REPRESENTATION -- decided by the existing schema, not by preference.
`apex.pulse.twin.Field.__post_init__` already refuses a non-TRUSTWORTHY
field that carries a number:

    "a {quality} field carries the number {value!r}: an untrustworthy
     field must not present a consumable measurement"

So a stale derived field OMITS its value. There is no representation in
which a downstream consumer can read a number off a non-VALID field: the
constructor raises, `Field.usable` is False, and the serialised record
carries `"v": null` with its own `"q"`. The note names the ingredient that
caused it, so the reason survives serialisation too.

decision_power: NONE_STATE.
"""
from __future__ import annotations

import math

from apex.pulse.twin import (NOT_AVAILABLE, NOT_ESTIMABLE, PROVIDER_ERROR,
                             SESSION_INAPPLICABLE, STALE, UNKNOWN, VALID,
                             Field, absent, ok)

DERIVED_FIELD_CONTRACT = "DERIVED_FIELD_CONTRACT_V1"
DEFECT_CLOSED = "DERIVED-FIELD-STALENESS-001"

# An ingredient with no value at all beats one that merely cannot be
# trusted: without a value the dependent cannot be computed, so the reason
# reported is the absence. Order is the reporting precedence among absences.
ABSENCE_PRECEDENCE = (PROVIDER_ERROR, NOT_AVAILABLE, UNKNOWN, NOT_ESTIMABLE)
CONTAMINATING = (STALE,)

# ---------------------------------------------------------------- the map
# Every derived PULSE field, the ingredients it consumes, and the formula.
# `inputs` are FIELD NAMES in the same packet unless prefixed "raw:", which
# marks an ingredient the composer holds but does not itself publish.
DEPENDENCIES = {
    # ---- straight off the quote
    "mid": {"inputs": ("raw:quote.bid", "raw:quote.ask"),
            "formula": "(bid + ask) / 2", "gated_by": "sip_quote freshness"},
    "spread_bps": {"inputs": ("raw:quote.bid", "raw:quote.ask"),
                   "formula": "(ask - bid) / mid * 1e4", "gated_by": "sip_quote freshness"},
    "spread_rel": {"inputs": ("raw:quote.bid", "raw:quote.ask"),
                   "formula": "(ask - bid) / mid", "gated_by": "sip_quote freshness"},
    "touch_size": {"inputs": ("raw:quote.bid_size", "raw:quote.ask_size"),
                   "formula": "bid_size + ask_size", "gated_by": "sip_quote freshness"},
    "nbbo_size_imbalance": {"inputs": ("raw:quote.bid_size", "raw:quote.ask_size"),
                            "formula": "(bid_size - ask_size) / (bid_size + ask_size)",
                            "gated_by": "sip_quote freshness"},
    # ---- the one deliberate exception, stated rather than hidden
    "quote_age_s": {"inputs": ("raw:quote.timestamp",),
                    "formula": "now - quote.timestamp",
                    "exception": "STALENESS_IS_THE_MEASUREMENT",
                    "why": "this field measures HOW OLD the quote is. Marking it untrustworthy "
                           "because the quote is old would delete the only number that says so. "
                           "It depends on the quote's TIMESTAMP, not on its prices, and it is "
                           "NOT_AVAILABLE when there is no quote at all."},
    # ---- quote combined with an anchor or a session aggregate
    "prior_close_return_bps": {"inputs": ("mid", "prior_close"),
                               "formula": "(mid / prior_close - 1) * 1e4"},
    "cash_open_return_bps": {"inputs": ("mid", "session_open"),
                             "formula": "(mid / session_open - 1) * 1e4",
                             "session_gated": ("PREMARKET", "CLOSED")},
    "session_range_position": {"inputs": ("mid", "session_high", "session_low"),
                               "formula": "(mid - low) / (high - low)"},
    "vwap_distance_bps": {"inputs": ("mid", "session_vwap"),
                          "formula": "(mid / vwap - 1) * 1e4"},
    # ---- no quote in these at all: a stale quote must NOT touch them
    "overnight_gap_bps": {"inputs": ("session_open", "prior_close"),
                          "formula": "(session_open / prior_close - 1) * 1e4",
                          "session_gated": ("PREMARKET", "CLOSED")},
    "relative_volume": {"inputs": ("session_volume", "raw:prior_session.volume"),
                        "formula": "session_volume / prior_session_volume"},
    # ---- PULSE's own rolling memory, fed by the mid
    **{"ret_%dm_bps" % m: {"inputs": ("mid",),
                           "formula": "rolling return over %d observed minutes" % m,
                           "note": "the rolling store is only OBSERVED with a usable mid, so an "
                                   "untrusted price cannot enter PULSE's own memory and "
                                   "contaminate later cycles"}
       for m in (1, 5, 10, 15, 30, 60)},
    **{name: {"inputs": ("mid", "prior_close"), "formula": "premarket path from observed mids"}
       for name in ("premarket_first", "premarket_high", "premarket_low",
                    "premarket_range_bps", "premarket_return_bps",
                    "premarket_travel_bps", "overnight_first_gap_bps",
                    "premarket_observations")},
}
# Fields that are NOT derived: read straight from one source, no propagation.
# prior_close_session is PULSE-010 provenance: which exchange session the
# anchor belongs to. Read from one source, computes nothing.
INDEPENDENT_FIELDS = ("prior_close", "prior_close_session", "session_open", "session_high",
                      "session_low", "session_vwap", "session_volume", "last_trade",
                      "last_minute_volume")


class DerivationViolation(RuntimeError):
    """A derived field was built without declaring what it consumes."""


def is_finite_number(v) -> bool:
    """bool is not a number: isinstance(True, int) is True in Python, and a
    bool that reaches a price would become 1.0."""
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(float(v)))


def raw_field(value, *, source, as_of=None, note=None) -> Field:
    """Admit a raw ingredient. A non-finite or non-numeric value is
    NOT_ESTIMABLE at the ingredient rather than a number nobody checked."""
    if value is None:
        return absent(NOT_AVAILABLE, source=source, note=note or "ingredient absent")
    if not is_finite_number(value):
        return absent(NOT_ESTIMABLE, source=source,
                      note="ingredient %r is not a finite real number" % (value,))
    return ok(value, source=source, as_of=as_of, note=note)


def resolve(name: str, inputs: dict) -> tuple:
    """(quality, reason) the dependent must take, or (None, None) when every
    ingredient is VALID. Pure: no I/O, no clock."""
    if name not in DEPENDENCIES:
        raise DerivationViolation(
            "%r is not in DEPENDENCIES: a derived field must declare what it consumes" % name)
    declared = DEPENDENCIES[name]["inputs"]
    missing = [k for k in declared if k not in inputs]
    if missing:
        raise DerivationViolation("%s: ingredients %s were not supplied" % (name, missing))
    # PULSE-010 HARDENING (behaviour unchanged). An ingredient that was not
    # declared must not even be OFFERED. resolve() has only ever consulted
    # `declared`, so a wider dict was inert and no over-propagation ever
    # occurred -- measured across four scenarios before and after, with
    # identical results. What it did leave was the declaration as the single
    # thing standing between unrelated fields and accidental coupling. A
    # caller that hands over more than it declared is now an error.
    undeclared = sorted(k for k in inputs if k not in declared)
    if undeclared:
        raise DerivationViolation(
            "%s: ingredients %s were supplied but are NOT declared in DEPENDENCIES. A derived "
            "field must receive exactly what it declares, so that a failure in an unrelated "
            "ingredient can never reach it." % (name, undeclared))
    bad, notes = {}, {}
    for k in declared:
        f = inputs[k]
        if f is None:
            bad[k] = NOT_AVAILABLE
        elif not isinstance(f, Field):
            raise DerivationViolation("%s: ingredient %s is %s, not a Field"
                                      % (name, k, type(f).__name__))
        elif f.quality != VALID:
            bad[k] = f.quality
            if f.note:
                notes[k] = f.note
    if not bad:
        return None, None

    def because(culprits):
        """Carry the INGREDIENT's own explanation into the dependent, so the
        original verdict -- the freshness tolerance that refused the quote --
        survives the propagation instead of being replaced by a summary."""
        seen, out = set(), []
        for k in culprits:
            n = notes.get(k)
            if n and n not in seen:
                seen.add(n); out.append(n)
        return (" (%s)" % "; ".join(out)) if out else ""

    for q in ABSENCE_PRECEDENCE:
        culprits = sorted(k for k, v in bad.items() if v == q)
        if culprits:
            return q, "%s: ingredient(s) %s are %s%s" % (name, culprits, q, because(culprits))
    for q in CONTAMINATING:
        culprits = sorted(k for k, v in bad.items() if v == q)
        if culprits:
            return q, ("%s: ingredient(s) %s are %s, so this value cannot be trusted either "
                       "[%s]%s" % (name, culprits, q, DEFECT_CLOSED, because(culprits)))
    q = sorted(bad.values())[0]
    return q, "%s: ingredient(s) %s are %s" % (name, sorted(bad), q)


def derive(name: str, inputs: dict, compute, *, source="derived", as_of=None,
           note=None, session_inapplicable=None) -> Field:
    """Build a derived field under the contract.

    `compute` is called ONLY when every declared ingredient is VALID, so a
    formula can never see an untrusted number. If it returns None the field
    is NOT_ESTIMABLE -- computable in principle, not computable here."""
    if session_inapplicable:
        return absent(SESSION_INAPPLICABLE, source=source, note=session_inapplicable)
    quality, reason = resolve(name, inputs)
    if quality is not None:
        return absent(quality, source=source, note=reason)
    value = compute()
    if value is None or not is_finite_number(value):
        return absent(NOT_ESTIMABLE, source=source,
                      note=note or "%s: inputs were usable but the result is not a finite "
                                   "number" % name)
    return ok(value, source=source, as_of=as_of, note=note)


def contract() -> dict:
    return {
        "contract": DERIVED_FIELD_CONTRACT,
        "defect_closed": DEFECT_CLOSED,
        "rule": "a derived field is VALID only when every declared ingredient is VALID",
        "absence_precedence": list(ABSENCE_PRECEDENCE),
        "contaminating": list(CONTAMINATING),
        "representation": "the value is OMITTED on any non-VALID quality -- enforced by "
                          "apex.pulse.twin.Field, which refuses a non-trustworthy field that "
                          "carries a number",
        "session_inapplicable": "decided before ingredients and never overwritten",
        "independent_fields": list(INDEPENDENT_FIELDS),
        "dependencies": DEPENDENCIES,
        "consumer_guidance": "filter on q == 'VALID'. The note names the failing ingredient, so "
                             "no consumer needs field-name knowledge to know why a field is "
                             "unusable.",
    }
