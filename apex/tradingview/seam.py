"""THE SNAPSHOT JOIN SEAM — binding an external observation to the exact decision that used it.

**THIS SEAM IS NOT WIRED INTO THE LIVE DECISION PATH.** It is built and tested on its own so the join can be
reviewed before anything depends on it. `TwinSources.snapshot` still returns a snapshot with no id, and no
production decision record carries `external_inputs_used` yet. `docs/TRADINGVIEW_INTEGRATION_002.md` reports that
as the remaining gap rather than this module pretending to close it.

WHAT IT JOINS, and why each link is needed:

    snapshot_id      a content-addressed id for ONE market state at ONE instant. The options-path Twin does not
                     have one today (`snapshot_id` exists only in apex/catalyst and apex/vision), so a decision
                     cannot currently name the market state it was made on. Everything downstream needs it.
      -> market_state_digest   the snapshot's own values, digested, so the id is falsifiable rather than a label
      -> model_identities      which forecast / variance / regime models and parameter hashes were in force
      -> candidate_set         which expressions were generated and scored under that state
      -> decision_record       what was decided, and WHICH external observations informed it

THE TWO RULES THIS MODULE EXISTS TO ENFORCE.

1. **Nothing informs a decision it was not knowable for.** An observation whose `known_from` is after the
   snapshot's `as_of` is refused as decision-time context, reusing `normalize.valid_for_as_of`. Retrieving
   something later never makes it available earlier. A premarket packet observation is different in kind: it is
   attached as PRIOR_CONTEXT, is knowable before the snapshot by construction, and is never counted as
   decision-time evidence.

2. **An observation that fed nothing says so.** Attaching requires declaring what the observation feeds. One with
   no declared consumer is recorded `RETRIEVED_UNUSED`, so "what did the eyes contribute to this trade" is answered
   from the record instead of inferred from the fact that a call was made.

WHAT A JOINED OBSERVATION IS NEVER ALLOWED TO BECOME, asserted here and not merely documented: a calibrated
probability, a trading signal on its own, a model promotion, or an order authorization. `_assert_context_only`
refuses to attach anything whose authority labels have been tampered with, and the seam has no path to execution,
risk, exits or order submission -- it imports none of them, and a test asserts that."""
from __future__ import annotations

import hashlib
import json

from . import normalize as N

SEAM_SCHEMA = "EXTERNAL_CONTEXT_JOIN_V0"

# how an observation relates to the decision instant
PRIOR_CONTEXT = "PRIOR_CONTEXT"                   # the premarket packet: knowable before, guides attention only
DECISION_TIME_CONTEXT = "DECISION_TIME_CONTEXT"   # attached to the current intraday snapshot
ROLES = (PRIOR_CONTEXT, DECISION_TIME_CONTEXT)

# what became of it
USED = "USED"
RETRIEVED_UNUSED = "RETRIEVED_UNUSED"
REFUSED_LATE = "REFUSED_LATE_ARRIVING"
DISPOSITIONS = (USED, RETRIEVED_UNUSED, REFUSED_LATE)

AUTHORITY_LAW = (
    "EXTERNAL_CONTEXT_JOIN_V0: a joined TradingView observation is EXTERNAL CONTEXT. It is never a calibrated "
    "probability, never a trading signal by itself, never a model promotion and never an order authorization. It "
    "informs a decision record by being named in it; it does not make the decision, size it, or permit it.")

JOIN_LAW = (
    "An observation may inform a decision only if it was knowable at that decision's instant. Premarket "
    "observations are PRIOR_CONTEXT and are referenced, never counted as decision-time evidence. An observation "
    "with no declared consumer is RETRIEVED_UNUSED, stated rather than omitted.")

NOT_WIRED = (
    "SEAM_NOT_WIRED: this join is implemented and tested in isolation. The options-path Twin snapshot carries no "
    "snapshot_id today and no production decision record carries external_inputs_used. Production Twin wiring is "
    "NOT complete and is not claimed to be.")


class JoinRefused(ValueError):
    """A join that would misstate what informed a decision. Named, never silent."""


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def market_state_digest(snapshot) -> str:
    """A digest over the snapshot's own values. The id below is only meaningful because this is falsifiable: a
    reviewer holding the snapshot can recompute it and prove the decision names the state it was made on."""
    if snapshot is None:
        raise JoinRefused("SNAPSHOT_REQUIRED: a decision cannot name a market state it does not have")
    return _digest(snapshot)


def snapshot_id(snapshot, *, symbol: str, as_of_epoch: float) -> str:
    """The content-addressed id of one market state at one instant.

    THIS IS THE SEAM THE OPTIONS PATH IS MISSING. Two snapshots of the same symbol at the same instant with the
    same values are the same state and get the same id; any difference in symbol, instant or content changes it."""
    if not symbol or not isinstance(symbol, str):
        raise JoinRefused("SYMBOL_REQUIRED: %r" % (symbol,))
    if not isinstance(as_of_epoch, (int, float)) or isinstance(as_of_epoch, bool):
        raise JoinRefused("AS_OF_REQUIRED: %r" % (as_of_epoch,))
    return _digest({"symbol": symbol, "as_of_us": int(round(float(as_of_epoch) * 1_000_000)),
                    "market_state": market_state_digest(snapshot)})[:32]


def _assert_context_only(obs: dict) -> None:
    """The observation's own labels must still say what the normalizer stamped. A record whose authority or
    calibration has been altered on the way here is refused rather than joined."""
    if obs.get("provider") != N.PROVIDER:
        raise JoinRefused("NOT_A_TRADINGVIEW_OBSERVATION: provider %r" % (obs.get("provider"),))
    if obs.get("calibrated") is not False:
        raise JoinRefused("CALIBRATION_CLAIMED: an external observation is never a calibrated probability "
                          "(calibrated=%r)" % (obs.get("calibrated"),))
    if obs.get("authority") not in (N.AUTHORITY_CONTEXT, N.AUTHORITY_OBSERVATION):
        raise JoinRefused("AUTHORITY_NOT_RECOGNISED: %r; this seam joins observations, not authorities"
                          % (obs.get("authority"),))
    if obs.get("source_class") != N.SOURCE_CLASS:
        raise JoinRefused("SOURCE_CLASS_ALTERED: %r" % (obs.get("source_class"),))


class SnapshotJoin:
    """One decision's external context: the state it was made on, and every observation that reached it."""

    def __init__(self, *, snapshot, symbol: str, as_of_epoch: float, model_identities: dict | None = None,
                 premarket_packet_ref: str | None = None):
        self.symbol, self.as_of_epoch = symbol, float(as_of_epoch)
        # ADOPT THE STATE'S OWN ID; never mint a competing one.
        #
        # This module originally always computed its own id, because when it was written the options-path snapshot
        # had none. The snapshot now emits `snapshot_id` (apex/pulse_options/snapshot.compose), and computing a
        # second one produced TWO different identities for one market state -- a decision record naming an id that
        # no snapshot carries, which is worse than having no id at all: it looks like a join and joins nothing.
        # The snapshot's own id governs whenever it has one, and `snapshot_id_source` says which happened.
        own = (snapshot or {}).get("snapshot_id") if isinstance(snapshot, dict) else None
        if own:
            self.snapshot_id = own
            self.snapshot_id_source = "SNAPSHOT_OWN_ID: adopted from the market state itself"
        else:
            self.snapshot_id = snapshot_id(snapshot, symbol=symbol, as_of_epoch=as_of_epoch)
            self.snapshot_id_source = ("SEAM_COMPUTED: the market state carries no snapshot_id of its own, so the "
                                       "seam content-addressed it here")
        self.market_state_digest = market_state_digest(snapshot)
        # WHICH MODELS were in force. `None` is recorded as UNAVAILABLE rather than omitted, because a decision
        # whose model identity is unknown is a different thing from one made with no model.
        self.model_identities = dict(model_identities or {}) or {"status": "UNAVAILABLE: no model identity supplied"}
        self.premarket_packet_ref = premarket_packet_ref
        self.attached: list = []

    # ------------------------------------------------------------------ attaching

    def attach(self, obs: dict, *, role: str, feeds=None) -> dict:
        """Attach one observation. `feeds` names the fields it informs; empty means RETRIEVED_UNUSED."""
        _assert_context_only(obs)
        if role not in ROLES:
            raise JoinRefused("ROLE_NOT_RECOGNISED: %r not in %r" % (role, ROLES))
        feeds = [str(f) for f in (feeds or [])]
        entry = {"observation_key": N.observation_key(obs), "tool": obs["tool"],
                 "response_digest": obs["response_digest"], "request_args_digest": obs["request_args_digest"],
                 "symbol": obs.get("symbol"), "role": role,
                 "known_from_utc": obs["known_from_utc"], "known_from_epoch": obs["known_from_epoch"],
                 "entitlement": obs["entitlement"], "authority": obs["authority"], "calibrated": obs["calibrated"],
                 "feeds": feeds}
        if role == DECISION_TIME_CONTEXT:
            v = N.valid_for_as_of(obs, self.as_of_epoch)
            if not v["valid"]:
                # LATE-ARRIVING INFORMATION. Attached as evidence of the refusal, never as context.
                entry.update(disposition=REFUSED_LATE, attached_to=None, why=v["why"], feeds=[])
                self.attached.append(entry)
                return entry
            entry["attached_to"] = self.snapshot_id
        else:
            # PRIOR CONTEXT is referenced against the packet, never against the decision snapshot, and never
            # counted as decision-time evidence however useful it was for pointing attention.
            entry["attached_to"] = self.premarket_packet_ref
            entry["note"] = ("premarket observation: prior context that guided attention. It is not evidence about "
                             "the decision instant, and the intraday snapshot decides whether the setup exists.")
        entry["disposition"] = USED if feeds else RETRIEVED_UNUSED
        self.attached.append(entry)
        return entry

    # ------------------------------------------------------------------ the record

    def external_inputs_used(self) -> list:
        return [dict(e) for e in self.attached]

    def decision_record(self, *, candidate_set=None, decision=None) -> dict:
        """The join, rendered for a decision record: state, models, candidates, and what the eyes contributed."""
        used = [e for e in self.attached if e["disposition"] == USED]
        return {
            "schema": SEAM_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "snapshot_id_source": self.snapshot_id_source,
            "symbol": self.symbol,
            "as_of_epoch": self.as_of_epoch,
            "market_state_digest": self.market_state_digest,
            "model_identities": dict(self.model_identities),
            "premarket_packet_ref": self.premarket_packet_ref,
            "candidate_set": ([dict(c) for c in candidate_set] if candidate_set is not None
                              else {"status": "UNAVAILABLE: no candidate set supplied"}),
            "decision": decision if decision is not None else {"status": "UNAVAILABLE: no decision supplied"},
            "external_inputs_used": self.external_inputs_used(),
            "n_external_used": len(used),
            "n_external_retrieved_unused": len([e for e in self.attached if e["disposition"] == RETRIEVED_UNUSED]),
            "n_external_refused_late": len([e for e in self.attached if e["disposition"] == REFUSED_LATE]),
            "authority_law": AUTHORITY_LAW,
            "join_law": JOIN_LAW,
            "wiring_status": NOT_WIRED,
        }
