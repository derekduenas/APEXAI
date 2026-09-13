"""THE PRODUCTION SEAM — TradingView external context bound to ONE market state, on the real pilot path.

This is what `seam.py` said was NOT wired. It is wired here, and the wiring is deliberately the narrowest thing
that can carry the join end to end:

    TradingView observation -> snapshot_id -> market state -> model inputs -> candidate set -> decision record

FIVE RULES, EACH ENFORCED RATHER THAN DOCUMENTED.

1. **A decision names the state it was made on.** `TwinSources.snapshot()` emits a content-addressed
   `snapshot_id` (see apex/pulse_options/snapshot.compose). Context that is not bound to one is refused with
   `NO_SNAPSHOT_ID` -- an observation floating free of a market state cannot be said to have informed anything.

2. **Every decision record carries `external_inputs_used`, including when it is empty.** A scan that consulted
   nothing says so with a named status. Silence and "no external input" are different facts and are never
   conflated: an omitted field would let a missing connector read as a considered abstention.

3. **Every observation records what became of it**: USED, RETRIEVED_UNUSED, or REFUSED_LATE_ARRIVING. Retrieval
   is not use. An observation that fed no field is recorded as retrieved and unused, so "what did the eyes
   contribute to this trade" is read off the record instead of inferred from the fact that a call was made.

4. **Premarket is PRIOR_CONTEXT, never decision-time evidence.** It is knowable before the snapshot by
   construction; it guides attention, and the intraday snapshot decides whether the setup exists.

5. **It is EXTERNAL_CONTEXT_ONLY.** Never a calibrated probability, never a standalone signal. `attach` re-checks
   the observation's own authority labels, so a record altered on the way here is refused rather than joined.

INDEPENDENCE IS THE POINT OF THE UNAVAILABLE STATES. Every failure -- no tools, timeout, auth, rate limit, budget,
malformed payload, stale data, a raised exception, a missing snapshot -- becomes a NAMED status on a packet that
is still returned. `external_context()` does not raise. Exits, risk authorization, reservations and order handling
never call this module and never wait for it; `blocks_nothing()` states that, a test asserts the import set, and
the pilot path treats an unavailable packet exactly like an available one for control flow."""
from __future__ import annotations

import time

from . import allowlist as AL
from . import normalize as N
from . import seam as S

KIND = "EXTERNAL_CONTEXT_V1"
AUTHORITY = "EXTERNAL_CONTEXT_ONLY"

AVAILABLE = "AVAILABLE"
NOT_WIRED = "NOT_WIRED"                          # no context provider on this twin
NO_SNAPSHOT_ID = "NO_SNAPSHOT_ID"                # the market state carries no id: nothing to bind to
TOOLS_MISSING = "TOOLS_MISSING"                  # the session exposes no TradingView tool at all
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
TIMEOUT = "TIMEOUT"
AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
RATE_LIMITED = "RATE_LIMITED"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
TOOL_DENIED = "TOOL_DENIED"
MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
STALE_DATA = "STALE_DATA"
PROVIDER_RAISED = "PROVIDER_RAISED"

UNAVAILABLE_STATES = (NOT_WIRED, NO_SNAPSHOT_ID, TOOLS_MISSING, PROVIDER_UNAVAILABLE, TIMEOUT,
                      AUTHENTICATION_FAILED, RATE_LIMITED, BUDGET_EXHAUSTED, TOOL_DENIED, MALFORMED_RESPONSE,
                      STALE_DATA, PROVIDER_RAISED)
STATES = (AVAILABLE,) + UNAVAILABLE_STATES

# An adapter envelope's named state maps onto ours one-for-one. A state nobody has mapped becomes
# PROVIDER_UNAVAILABLE rather than AVAILABLE: an unrecognised state is never treated as success.
_FROM_ADAPTER = {"OK": AVAILABLE, "TOOL_DENIED": TOOL_DENIED, "BUDGET_EXHAUSTED": BUDGET_EXHAUSTED,
                 "RATE_LIMITED": RATE_LIMITED, "TIMEOUT": TIMEOUT, "AUTHENTICATION_FAILED": AUTHENTICATION_FAILED,
                 "PROVIDER_UNAVAILABLE": PROVIDER_UNAVAILABLE, "MALFORMED_RESPONSE": MALFORMED_RESPONSE}

DEFAULT_MAX_AGE_S = 900.0        # an observation older than this at the decision instant is STALE, and says so

LAW = ("EXTERNAL_CONTEXT_ONLY: TradingView context informs a decision record by being NAMED in it. It is never a "
       "calibrated probability, never a standalone signal, never a model promotion and never an order "
       "authorization. It cannot enter risk authorization, exit servicing, reservations or order handling.")


def state_from_adapter(state: str) -> str:
    return _FROM_ADAPTER.get(str(state), PROVIDER_UNAVAILABLE)


def unavailable(*, symbol, as_of, status: str, why: str, snapshot_id=None, wired: bool = True) -> dict:
    """A packet that carries a NAMED reason instead of data. It is a full packet, not a None: every consumer sees
    the same shape whether the eyes worked or not, so no caller can accidentally branch on presence."""
    if status not in UNAVAILABLE_STATES:
        raise ValueError("UNAVAILABLE_STATE_UNKNOWN: %r not in %r" % (status, UNAVAILABLE_STATES))
    return {"kind": KIND, "provider": AL.PROVIDER, "symbol": symbol, "as_of_epoch": as_of,
            "snapshot_id": snapshot_id, "wired": wired, "status": status, "why": why,
            "authority": AUTHORITY, "calibrated": False,
            "external_inputs_used": [], "n_used": 0, "n_retrieved_unused": 0, "n_refused_late": 0,
            "law": LAW, "blocks_nothing": blocks_nothing()}


def blocks_nothing() -> dict:
    return {"contract": ("EXITS_RISK_RESERVATIONS_AND_ORDERS_ARE_INDEPENDENT: none of them calls this module or "
                         "waits for it. An unavailable packet is returned, never raised, so a TradingView failure "
                         "cannot become control flow on a path that must not depend on it."),
            "enforced_by": "tests/test_tradingview_pilot_seam_003.py"}


def build(*, symbol: str, as_of: float, snapshot: dict | None, observations, model_identities=None,
          premarket_refs=None, feeds_by_key=None, max_age_s: float = DEFAULT_MAX_AGE_S, now_fn=time.time) -> dict:
    """Join observations to ONE market state and return the packet a decision record will carry.

    `observations` is a sequence of `(observation, role, feeds)`; `feeds` names the fields the observation
    informs and MAY be empty -- that is what RETRIEVED_UNUSED means and it is recorded, not dropped."""
    snap_id = (snapshot or {}).get("snapshot_id")
    if not snap_id:
        return unavailable(symbol=symbol, as_of=as_of, status=NO_SNAPSHOT_ID,
                           why=("the market state carries no snapshot_id, so an observation cannot be bound to it. "
                                "Context is refused rather than attached to an unnamed state."))
    join = S.SnapshotJoin(snapshot=snapshot, symbol=symbol, as_of_epoch=as_of,
                          model_identities=model_identities,
                          premarket_packet_ref=(premarket_refs or {}).get("packet_ref"))
    stale = []
    for item in (observations or []):
        obs, role, feeds = (list(item) + [None, None])[:3] if not isinstance(item, dict) else (
            item.get("observation"), item.get("role"), item.get("feeds"))
        role = role or S.DECISION_TIME_CONTEXT
        try:
            entry = join.attach(obs, role=role, feeds=feeds)
        except S.JoinRefused as e:
            # A record whose authority labels were altered is refused HERE and recorded as a refusal, so the
            # tampering is visible in the decision record instead of vanishing.
            join.attached.append({"observation_key": None, "tool": (obs or {}).get("tool"),
                                  "role": role, "disposition": S.REFUSED_LATE, "attached_to": None,
                                  "feeds": [], "why": "JOIN_REFUSED: %s" % str(e)[:200]})
            continue
        # STALENESS is about the decision instant, not the wall clock: an observation knowable long before the
        # snapshot is stale FOR THIS DECISION however recently it was fetched.
        age = float(as_of) - float(obs["known_from_epoch"])
        entry["age_s_at_decision"] = round(age, 6)
        if role == S.DECISION_TIME_CONTEXT and entry["disposition"] != S.REFUSED_LATE and age > float(max_age_s):
            entry["disposition"] = S.RETRIEVED_UNUSED
            entry["feeds"] = []
            entry["why"] = ("STALE_DATA: known from %s, %.1fs before the decision instant, past the %.0fs bound; "
                            "retained as retrieved and unused rather than fed to a decision"
                            % (obs["known_from_utc"], age, float(max_age_s)))
            stale.append(entry["tool"])
    rec = join.decision_record()
    status = AVAILABLE
    why = None
    if not join.attached:
        status, why = PROVIDER_UNAVAILABLE, "no observation reached this decision instant"
    elif stale and rec["n_external_used"] == 0:
        status, why = STALE_DATA, "every decision-time observation was past the staleness bound: %s" % sorted(set(stale))
    return {"kind": KIND, "provider": AL.PROVIDER, "symbol": symbol, "as_of_epoch": as_of,
            "snapshot_id": snap_id, "wired": True, "status": status, "why": why,
            "authority": AUTHORITY, "calibrated": False,
            "market_state_digest": rec["market_state_digest"],
            "model_identities": rec["model_identities"],
            "premarket_packet_ref": rec["premarket_packet_ref"],
            "external_inputs_used": rec["external_inputs_used"],
            "n_used": rec["n_external_used"], "n_retrieved_unused": rec["n_external_retrieved_unused"],
            "n_refused_late": rec["n_external_refused_late"], "stale_tools": sorted(set(stale)),
            "max_age_s": float(max_age_s), "law": LAW, "blocks_nothing": blocks_nothing()}


def external_context(*, symbol: str, as_of: float, snapshot: dict | None, fetch_fn=None, **kw) -> dict:
    """The twin-facing entry point. **It never raises.**

    `fetch_fn(symbol, as_of) -> sequence of (observation, role, feeds)` does whatever retrieval the operator has
    authorized. Anything it throws -- and anything the adapter reports as a named non-OK state -- becomes a named
    unavailable packet, because a sense that fails must report a failure, not interrupt a decision."""
    if fetch_fn is None:
        return unavailable(symbol=symbol, as_of=as_of, wired=False, status=NOT_WIRED,
                           snapshot_id=(snapshot or {}).get("snapshot_id"),
                           why="no TradingView context provider is wired to this twin")
    try:
        fetched = fetch_fn(symbol, as_of)
    except AL.ToolNotAllowed as e:
        return unavailable(symbol=symbol, as_of=as_of, status=TOOL_DENIED, why=str(e)[:200],
                           snapshot_id=(snapshot or {}).get("snapshot_id"))
    except TimeoutError as e:
        return unavailable(symbol=symbol, as_of=as_of, status=TIMEOUT, why=str(e)[:200] or "timeout",
                           snapshot_id=(snapshot or {}).get("snapshot_id"))
    except Exception as e:                                     # noqa: BLE001 - a failing sense is a state
        return unavailable(symbol=symbol, as_of=as_of, status=PROVIDER_RAISED,
                           why="%s: %s" % (type(e).__name__, str(e)[:200]),
                           snapshot_id=(snapshot or {}).get("snapshot_id"))
    # An adapter envelope handed straight through: map its named state rather than treating it as observations.
    if isinstance(fetched, dict) and "state" in fetched and "tool" in fetched:
        st = state_from_adapter(fetched["state"])
        if st != AVAILABLE:
            return unavailable(symbol=symbol, as_of=as_of, status=st,
                               why=str(fetched.get("why") or fetched["state"])[:200],
                               snapshot_id=(snapshot or {}).get("snapshot_id"))
        fetched = [(fetched.get("observation"), S.DECISION_TIME_CONTEXT, [])]
    if fetched is None:
        return unavailable(symbol=symbol, as_of=as_of, status=TOOLS_MISSING,
                           why="the context provider returned nothing; no TradingView tool answered",
                           snapshot_id=(snapshot or {}).get("snapshot_id"))
    try:
        return build(symbol=symbol, as_of=as_of, snapshot=snapshot, observations=fetched, **kw)
    except Exception as e:                                     # noqa: BLE001
        return unavailable(symbol=symbol, as_of=as_of, status=MALFORMED_RESPONSE,
                           why="%s: %s" % (type(e).__name__, str(e)[:200]),
                           snapshot_id=(snapshot or {}).get("snapshot_id"))


def for_decision_record(ctx: dict | None) -> dict:
    """What the DECISION RECORD carries. Never None and never absent: a scan that consulted nothing says so."""
    if not ctx:
        return {"status": NOT_WIRED, "authority": AUTHORITY, "calibrated": False, "snapshot_id": None,
                "external_inputs_used": [], "n_used": 0, "n_retrieved_unused": 0, "n_refused_late": 0,
                "why": "no external context was computed for this scan", "law": LAW}
    return {"status": ctx.get("status"), "authority": ctx.get("authority"), "calibrated": ctx.get("calibrated"),
            "snapshot_id": ctx.get("snapshot_id"), "why": ctx.get("why"),
            "external_inputs_used": [
                {k: v for k, v in e.items() if k in ("observation_key", "tool", "role", "disposition", "feeds",
                                                     "known_from_utc", "attached_to", "age_s_at_decision",
                                                     "entitlement", "authority", "calibrated", "why")}
                for e in (ctx.get("external_inputs_used") or [])],
            "n_used": ctx.get("n_used", 0), "n_retrieved_unused": ctx.get("n_retrieved_unused", 0),
            "n_refused_late": ctx.get("n_refused_late", 0), "law": LAW}
