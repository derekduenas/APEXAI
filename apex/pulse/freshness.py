"""FRESHNESS POLICY — how old is too old, per source and per session.

One global threshold would be wrong in both directions at once. A SIP
quote two minutes old during the regular session is broken; the same
two-minute-old quote at 06:00 premarket is completely normal, because
the name simply has not traded. A catalyst event two HOURS old is
still perfectly current state.

So freshness is declared per (source, session), from how the data
actually behaves -- never tuned against P&L, and never tuned at all.
These are operational data-quality statements.

decision_power: NONE_STATE.
"""
from __future__ import annotations

from apex.intraday.sessions import Session

FRESHNESS_POLICY_VERSION = "PULSE_FRESHNESS_V0"

# seconds. None means "age does not invalidate this source".
POLICY = {
    "sip_quote": {
        Session.REGULAR: 120.0,
        Session.PREMARKET: 600.0,
        Session.POSTMARKET: 600.0,
        Session.CLOSED: 3600.0,
        "why": "continuous two-sided quoting is expected in the "
               "regular session; outside it, sparse quoting is the "
               "normal state of the market, not a provider fault"},
    "sip_trade": {
        Session.REGULAR: 300.0,
        Session.PREMARKET: 1800.0,
        Session.POSTMARKET: 1800.0,
        Session.CLOSED: 7200.0,
        "why": "many ordinary names genuinely do not print for "
               "minutes at a time even mid-session"},
    "rest_snapshot": {
        Session.REGULAR: 90.0,
        Session.PREMARKET: 300.0,
        Session.POSTMARKET: 300.0,
        Session.CLOSED: 3600.0,
        "why": "the snapshot is PULSE's own broad heartbeat; if it is "
               "older than a cycle and a half, the cycle is degraded"},
    "options_nbbo": {
        Session.REGULAR: 300.0,
        Session.PREMARKET: None,
        Session.POSTMARKET: None,
        Session.CLOSED: None,
        "why": "US options do not trade premarket. Absence there is "
               "EXPECTED, not stale -- and Friday's closing quote is "
               "emphatically not Monday's premarket state"},
    "catalyst_event": {
        Session.REGULAR: None, Session.PREMARKET: None,
        Session.POSTMARKET: None, Session.CLOSED: None,
        "why": "an event does not decay. A filing from 02:55 is still "
               "the true state of the world at 15:00; its AGE is "
               "information, not a defect"},
    "btc": {
        Session.REGULAR: 120.0, Session.PREMARKET: 120.0,
        Session.POSTMARKET: 120.0, Session.CLOSED: 120.0,
        "why": "crypto trades continuously, so there is no session "
               "excuse for a stale mark"},
    "cross_sectional": {
        Session.REGULAR: 300.0, Session.PREMARKET: 900.0,
        Session.POSTMARKET: 900.0, Session.CLOSED: None,
        "why": "breadth is a slow aggregate; it does not need to be "
               "second-fresh to be true"},
}


def tolerance_s(source: str, session: Session):
    """The age at which this source stops describing NOW."""
    row = POLICY.get(source)
    if row is None:
        # An unknown source gets the STRICTEST rule, never a
        # permissive default: a source nobody declared is a source
        # nobody vouched for.
        return 60.0
    return row.get(session, 60.0)


def is_fresh(source: str, session: Session, age_s) -> dict:
    """Verdict plus the reason, so a STALE field can explain itself."""
    tol = tolerance_s(source, session)
    if age_s is None:
        return {"fresh": False, "tolerance_s": tol,
                "why": f"{source}: no timestamp, so age is unknowable"}
    if tol is None:
        return {"fresh": True, "tolerance_s": None,
                "why": f"{source}: age does not invalidate this "
                       f"source ({POLICY[source]['why']})"}
    if age_s <= tol:
        return {"fresh": True, "tolerance_s": tol,
                "why": f"{source}: {age_s:.1f}s within the "
                       f"{tol:.0f}s {session.value} tolerance"}
    return {"fresh": False, "tolerance_s": tol,
            "why": f"{source}: {age_s:.1f}s exceeds the {tol:.0f}s "
                   f"{session.value} tolerance"}


def describe() -> dict:
    return {"version": FRESHNESS_POLICY_VERSION,
            "sources": sorted(POLICY),
            "policy": {s: {(k.value if isinstance(k, Session) else k):
                           v for k, v in row.items()}
                       for s, row in POLICY.items()},
            "law": "declared per source and session from how the data "
                   "actually behaves; never tuned against P&L",
            "decision_power": "NONE_STATE"}
