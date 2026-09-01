"""LIVE / REPLAY MIRROR TEST — shared code is not proof.

A shared composer guarantees that live and history apply the same
FORMULA. It does not guarantee they are fed the same THING. A live
5-minute return anchored on a REST snapshot retrieved at 10:05:04 and
a historical one anchored on the 10:00 and 10:05 bar closes pass
through identical code and still mean slightly different things.

So the only honest test is empirical: seal a real packet live, let the
moment pass, reconstruct that exact timestamp from history, and
compare field by field.

DIFFERENCES ARE ALLOWED. Feeds genuinely differ. What is NOT allowed
is an unexplained difference, or a difference hidden behind the
comfort of shared code. Every field lands in one of five classes and
carries its reason.

decision_power: NONE_STATE.
"""
from __future__ import annotations

from apex.pulse.parity import (APPROXIMATE, HISTORICAL_ONLY, LIVE_ONLY,
                               MATRIX, NOT_AVAILABLE,
                               SEMANTICALLY_EQUIVALENT)

MIRROR_VERSION = "PULSE_MIRROR_TEST_V0"

# A field may differ by this much and still be called equivalent.
# Chosen from how the feeds behave, NOT tuned: a live mid is a quote
# midpoint and a historical mid is the last NBBO at or before t, so
# sub-basis-point drift is expected and meaningless.
TOLERANCE_BPS = 2.0
TOLERANCE_REL = 0.002


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _classify(name, live, hist) -> dict:
    """One field, compared honestly."""
    declared = MATRIX.get(name, {})
    lq = (live or {}).get("q")
    hq = (hist or {}).get("q")
    lv = (live or {}).get("v")
    hv = (hist or {}).get("v")

    row = {"field": name,
           "declared": declared.get("status", "UNDECLARED"),
           "live_source": (live or {}).get("src"),
           "replay_source": (hist or {}).get("src"),
           "live_value": lv, "replay_value": hv,
           "live_quality": lq, "replay_quality": hq,
           "live_as_of": (live or {}).get("as_of"),
           "replay_as_of": (hist or {}).get("as_of")}

    if live is None and hist is None:
        row.update(observed=NOT_AVAILABLE,
                   reason="absent from both packets")
        return row
    if live is None:
        row.update(observed=HISTORICAL_ONLY,
                   reason="the live feeder does not produce it")
        return row
    if hist is None:
        row.update(observed=LIVE_ONLY,
                   reason="history cannot reconstruct it")
        return row

    if lq != "VALID" or hq != "VALID":
        # not a value disagreement -- a coverage difference
        row.update(
            observed=(LIVE_ONLY if lq == "VALID"
                      else HISTORICAL_ONLY if hq == "VALID"
                      else NOT_AVAILABLE),
            reason=f"quality differs: live={lq} replay={hq}; a field "
                   f"absent on one side is a COVERAGE difference, not "
                   f"a semantic one")
        return row

    if _num(lv) and _num(hv):
        diff = hv - lv
        denom = max(abs(lv), 1e-9)
        rel = abs(diff) / denom
        row["difference"] = round(diff, 6)
        row["relative_difference"] = round(rel, 8)
        near = (abs(diff) <= TOLERANCE_BPS if name.endswith("_bps")
                else rel <= TOLERANCE_REL)
        if near:
            row.update(observed=SEMANTICALLY_EQUIVALENT,
                       reason="values agree within the declared "
                              "feed-difference tolerance")
        else:
            row.update(
                observed=APPROXIMATE,
                reason=declared.get("limits")
                or "values differ beyond tolerance; the feeds are not "
                   "identical and the difference is recorded rather "
                   "than reconciled")
        return row

    row.update(observed=(SEMANTICALLY_EQUIVALENT if lv == hv
                         else APPROXIMATE),
               reason="non-numeric comparison")
    return row


def mirror(live_packet: dict, replay_packet: dict, *,
           fields=None) -> dict:
    """Compare a sealed live packet against its reconstruction."""
    lf = live_packet.get("features") or {}
    hf = replay_packet.get("features") or {}
    names = sorted(fields or (set(lf) | set(hf)))
    rows = [_classify(n, lf.get(n), hf.get(n)) for n in names]

    counts = {}
    for r in rows:
        counts[r["observed"]] = counts.get(r["observed"], 0) + 1

    # a declared claim that reality contradicts is the real failure
    violations = []
    for r in rows:
        if r["declared"] == SEMANTICALLY_EQUIVALENT and \
                r["observed"] == APPROXIMATE:
            violations.append(
                f"{r['field']}: declared SEMANTICALLY_EQUIVALENT but "
                f"live={r['live_value']} replay={r['replay_value']} "
                f"(rel {r.get('relative_difference')})")
        if r["declared"] == LIVE_ONLY and \
                r["observed"] in (SEMANTICALLY_EQUIVALENT,
                                  APPROXIMATE):
            violations.append(
                f"{r['field']}: declared LIVE_ONLY but history "
                f"supplied a value -- parity was manufactured")

    return {"kind": "pulse_mirror_test", "version": MIRROR_VERSION,
            "subject": live_packet.get("subject"),
            "scheduled_time": live_packet.get("scheduled_time"),
            "live_state_id": live_packet.get("state_id"),
            "replay_state_id": replay_packet.get("state_id"),
            "live_session": live_packet.get("market_session"),
            "fields_compared": len(rows),
            "classification_counts": dict(sorted(counts.items())),
            "declaration_violations": violations,
            "verdict": ("MIRROR_CONSISTENT" if not violations
                        else "DECLARATION_CONTRADICTED_BY_REALITY"),
            "rows": rows,
            "law": "differences between live and history are allowed "
                   "and expected; hiding them behind shared code is "
                   "not",
            "decision_power": "NONE_STATE"}


# the fields the operator named as the minimum mirror set
CORE_FIELDS = ("ret_1m_bps", "ret_5m_bps", "ret_10m_bps",
               "ret_15m_bps", "prior_close", "prior_close_return_bps",
               "cash_open_return_bps", "overnight_gap_bps",
               "session_vwap", "vwap_distance_bps", "session_volume",
               "session_high", "session_low", "mid", "spread_bps",
               "nbbo_size_imbalance", "last_trade",
               "micro_net_signed_volume", "micro_spread_bps_median",
               "opt_state", "catalyst_fact_events_known")
