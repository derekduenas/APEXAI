"""WORLD_MODEL_INPUT_V0 -- what causal factual state was AVAILABLE.

The contract answers exactly one question:

    what factual state could a forecasting system have known at this
    moment, without seeing anything it could not have seen?

It carries no opinion, no signal, no direction and no decision. It is
the input side of a firewall, and everything in it is either an observed
fact or an explicit statement that a fact was not observed.

THREE TIMES, NOT ONE
The most expensive mistake available here is treating "when the world
was like this" and "when we could act on knowing it" as the same
instant. PULSE_V0 already demonstrated the cost: `latency.total_s`
started counting AFTER restore(), so it never saw a 42.6x startup growth
and reported within_budget=True on 100% of cycles while the true slot
occupancy blew past 60s on 61 of them. One clock, measured from the
wrong place, made a failure invisible.

    state_time           the market instant the state DESCRIBES
    state_complete_time  when assembly of that state finished
    known_from           the AUTHORITATIVE availability boundary --
                         nothing inside may have become knowable later

The enforced inequalities are stated explicitly rather than left to a
test to imply:

    state_time      <= state_complete_time <= known_from
    scheduled_time  <= state_complete_time           (when present)
    component.as_of <= state_time                    (per component)
    component.known_from <= input.known_from         (per component)

ASYNCHRONY IS FIRST-CLASS
Components do NOT become known simultaneously and the contract must
never imply they did. A daily bar from yesterday, an NBBO from 40ms ago
and a catalyst headline from 06:00 legitimately coexist in one state,
each with its own as_of, known_from, age and quality. Flattening them
into one timestamp would be a comfortable fiction.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any

from apex.world_model.canonical import (NumericContractViolation,
                                        content_hash, strict_float)
from apex.world_model.quality import (QualityContractViolation,
                                      assert_quality,
                                      assert_value_matches_quality)

INPUT_SCHEMA_VERSION = "WORLD_MODEL_INPUT_V0"

# Information tiers. These are AVAILABILITY classes, not quality tiers:
# a tier says which families of fact a forecast was permitted to see,
# so A0 and A1 results are never silently compared as if they had the
# same information.
A0_CORE = "A0_CORE"
A1_OPTIONS = "A1_OPTIONS"
B_FULL_JOINT = "B_FULL_JOINT"
INFORMATION_TIERS = (A0_CORE, A1_OPTIONS, B_FULL_JOINT)

# Families each tier may carry. A tier may not carry a family belonging
# to a HIGHER tier -- that is the leak this guards.
A0_FAMILIES = frozenset({
    "price_path", "session_structure", "premarket", "sip_trades",
    "sip_quotes_nbbo", "microstructure", "volume", "breadth_context",
    "market_relative", "sector_relative", "pit_population"})
A1_FAMILIES = frozenset({
    "implied_volatility", "implied_move", "skew", "term_structure",
    "options_liquidity", "surface_descriptors", "open_interest"})
B_FAMILIES = frozenset({"catalyst", "macro_politics", "cross_asset_btc"})

TIER_FAMILIES = {
    A0_CORE: A0_FAMILIES,
    A1_OPTIONS: A0_FAMILIES | A1_FAMILIES,
    B_FULL_JOINT: A0_FAMILIES | A1_FAMILIES | B_FAMILIES,
}

# Decision vocabulary. An INPUT may not contain any of it: the moment a
# factual contract can carry BUY or POSITION_SIZE, something downstream
# will read it as authority.
DECISION_TOKENS = frozenset({
    "buy", "sell", "attack", "hold", "exit", "position_size", "kelly",
    "order_ready", "trade_confidence", "signal", "action", "side",
    "direction_call", "recommendation", "target_size", "conviction"})

# DOCUMENTED FACTUAL NAMES -- the ambiguity is resolved in the open.
#
# Some genuine microstructure MEASUREMENTS unavoidably contain a word
# that is elsewhere an instruction. `buy_volume_fraction` is the share
# of volume that was buyer-initiated (Lee-Ready style classification):
# an observation about what already happened, not a direction to act.
# Banning it would push a real fact out of the contract; silently
# allowing anything prefixed "buy_" would let `buy_signal` walk in.
#
# So each such name is enumerated HERE, with its reason, rather than
# handled by a looser pattern. Adding to this list is a deliberate act
# that shows up in review -- which is the point.
DOCUMENTED_FACTUAL_NAMES = frozenset({
    "buy_volume_fraction",       # buyer-initiated share of volume
    "sell_volume_fraction",      # seller-initiated share of volume
    "buy_initiated_volume",      # absolute buyer-initiated volume
    "sell_initiated_volume",     # absolute seller-initiated volume
    "buy_sell_imbalance",        # signed order-flow imbalance
})


class InputContractViolation(ValueError):
    pass


@dataclass(frozen=True)
class Component:
    """One factual component with its OWN timing and quality."""
    name: str
    family: str
    as_of: float                 # the instant this value describes
    known_from: float            # when THIS component became knowable
    quality: str
    value: Any = None
    source: str = "UNDECLARED"

    def __post_init__(self):
        # Validate AT CONSTRUCTION. Lazy validation means a malformed
        # component can be built, passed through several stages and only
        # explode when something happens to hash it -- or never, if
        # nothing does. An invalid contract object must not be able to
        # exist.
        self.canonical()

    def canonical(self) -> dict:
        assert_quality(self.quality, field=self.name)
        assert_value_matches_quality(self.quality, self.value,
                                     field=self.name)
        strict_float(self.as_of, field="%s.as_of" % self.name)
        strict_float(self.known_from, field="%s.known_from" % self.name)
        if self.value is not None and isinstance(self.value, (int, float)):
            strict_float(self.value, field="%s.value" % self.name)
        return {"name": self.name, "family": self.family,
                "as_of": float(self.as_of),
                "known_from": float(self.known_from),
                "quality": self.quality, "value": self.value,
                "source": self.source}


@dataclass(frozen=True)
class WorldModelInput:
    input_id: str
    information_tier: str
    subject: str
    state_time: float
    known_from: float
    source_state_id: str
    source_state_hash: str
    feature_family_versions: dict
    components: tuple = ()
    state_complete_time: float | None = None
    scheduled_time: float | None = None
    market_context_state_id: str | None = None
    market_context_hash: str | None = None
    provenance: dict = _field(default_factory=dict)
    schema_version: str = INPUT_SCHEMA_VERSION

    def __post_init__(self):
        # Same reason as Component: an invalid input may not exist.
        self._validate()

    # ------------------------------------------------------ validation
    def _validate(self) -> None:
        if self.information_tier not in INFORMATION_TIERS:
            raise InputContractViolation(
                "unknown information_tier %r; permitted %s"
                % (self.information_tier, list(INFORMATION_TIERS)))
        st = strict_float(self.state_time, field="state_time")
        kf = strict_float(self.known_from, field="known_from")
        sct = strict_float(self.state_complete_time,
                           field="state_complete_time", allow_none=True)
        sch = strict_float(self.scheduled_time, field="scheduled_time",
                           allow_none=True)

        # --- the causal inequalities, stated not implied
        if sct is not None:
            if st > sct:
                raise InputContractViolation(
                    "state_time %r > state_complete_time %r: a state "
                    "cannot finish being assembled before the instant it "
                    "describes" % (st, sct))
            if sct > kf:
                raise InputContractViolation(
                    "state_complete_time %r > known_from %r: known_from "
                    "is the authoritative availability boundary, so "
                    "nothing may complete after it" % (sct, kf))
        if st > kf:
            raise InputContractViolation(
                "state_time %r > known_from %r: this state describes a "
                "moment later than it was knowable -- future leakage"
                % (st, kf))
        if sch is not None and sct is not None and sch > sct:
            raise InputContractViolation(
                "scheduled_time %r > state_complete_time %r" % (sch, sct))

        allowed = TIER_FAMILIES[self.information_tier]
        seen_names = set()
        for c in self.components:
            if not isinstance(c, Component):
                raise InputContractViolation(
                    "component %r is not a Component" % (c,))
            if c.name in seen_names:
                raise InputContractViolation(
                    "duplicate component name %r" % c.name)
            seen_names.add(c.name)
            if c.family not in allowed:
                higher = ("A1/B" if c.family in (A1_FAMILIES | B_FAMILIES)
                          else "unknown")
                raise InputContractViolation(
                    "component %r has family %r which is not permitted in "
                    "tier %s (%s). Admitting it would let a lower-tier "
                    "forecast see higher-tier information."
                    % (c.name, c.family, self.information_tier, higher))
            c.canonical()
            if c.as_of > st:
                raise InputContractViolation(
                    "component %r as_of %r > state_time %r: a component "
                    "cannot describe a moment later than the state it "
                    "belongs to" % (c.name, c.as_of, st))
            if c.known_from > kf:
                raise InputContractViolation(
                    "component %r known_from %r > input known_from %r: "
                    "the sealed input would contain something not yet "
                    "knowable when it was sealed"
                    % (c.name, c.known_from, kf))
            low = c.name.lower()
            if low in DOCUMENTED_FACTUAL_NAMES:
                continue          # ambiguity resolved explicitly above
            for tok in DECISION_TOKENS:
                if tok == low or low.startswith(tok + "_") \
                        or low.endswith("_" + tok):
                    raise InputContractViolation(
                        "component %r carries decision vocabulary (%r). "
                        "WORLD_MODEL_INPUT_V0 is factual state only; it "
                        "holds no decision authority." % (c.name, tok))

    # ------------------------------------------------------- identity
    def canonical(self) -> dict:
        self._validate()
        return {
            "schema_version": self.schema_version,
            "information_tier": self.information_tier,
            "subject": self.subject,
            "state_time": float(self.state_time),
            "state_complete_time": (None if self.state_complete_time is None
                                    else float(self.state_complete_time)),
            "scheduled_time": (None if self.scheduled_time is None
                               else float(self.scheduled_time)),
            "known_from": float(self.known_from),
            "source_state_id": self.source_state_id,
            "source_state_hash": self.source_state_hash,
            "market_context_state_id": self.market_context_state_id,
            "market_context_hash": self.market_context_hash,
            "feature_family_versions": dict(self.feature_family_versions),
            "components": [c.canonical() for c in
                           sorted(self.components, key=lambda x: x.name)],
            "provenance": dict(self.provenance),
        }

    @property
    def input_hash(self) -> str:
        return content_hash(self.canonical())

    def missingness(self) -> dict:
        out: dict = {}
        for c in self.components:
            out[c.quality] = out.get(c.quality, 0) + 1
        return out

    def sealed(self) -> dict:
        body = self.canonical()
        body["input_id"] = self.input_id
        body["input_hash"] = content_hash(self.canonical())
        body["PREDICTION_AUTHORITY"] = "NONE"
        body["TRADING_AUTHORITY"] = "NONE"
        body["CAPITAL_AUTHORITY"] = "NONE"
        body["ORDER_AUTHORITY"] = "NONE"
        return body


__all__ = ["DOCUMENTED_FACTUAL_NAMES", "INPUT_SCHEMA_VERSION", "A0_CORE", "A1_OPTIONS", "B_FULL_JOINT",
           "INFORMATION_TIERS", "TIER_FAMILIES", "A0_FAMILIES",
           "A1_FAMILIES", "B_FAMILIES", "DECISION_TOKENS", "Component",
           "WorldModelInput", "InputContractViolation",
           "NumericContractViolation", "QualityContractViolation"]
