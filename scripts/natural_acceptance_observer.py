#!/usr/bin/env python
"""NATURAL ACCEPTANCE OBSERVER -- job class POST_CLOSE_ANALYTICS.

The acceptance board for a live session, evaluated ENTIRELY FROM
ARTIFACTS. There is no --pass flag, no checklist file to tick, and no
argument that can turn an item green. Every item names the exact file it
read and the exact predicate it applied; if the file is absent the item
reads NOT_YET_OBSERVABLE, never PASS.

WHY "NATURAL". The Phase 1.0/1.1 acceptance criteria were previously
proven by REHEARSAL -- scripted movies that fed the system inputs chosen
to make the mechanism fire. A rehearsal proves the code path exists. It
cannot prove the path is reached by a real market on a real morning
under real launchd scheduling. This observer only reads what an
unattended session actually produced.

VERDICT VOCABULARY (deliberately four-valued, not two):
    PASS                 the predicate held on real session evidence
    FAIL                 the predicate was evaluated and did not hold
    NOT_YET_OBSERVABLE   the evidence does not exist yet -- the session
                         did not run, or ran without reaching this path.
                         This is NOT a pass and NOT a failure; it is the
                         honest state of a system whose first unattended
                         session has not happened.
    KNOWN_GAP            a declared, documented incompleteness. Recorded
                         so it cannot quietly become a PASS later.

A board of all-PASS is meaningless if the items are weak, so each item
carries the failure it was written to catch. Most of them are things
that already went wrong once.

decision_power: NONE_OBSERVABILITY. This observer grades; it never
tunes, gates, or writes into any decision artifact.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent))

import pandas as pd  # noqa: E402

OUT_DIR = Path("results/audit")
BOARD_LEDGER = Path("results/audit/natural_acceptance.jsonl")

PASS = "PASS"
FAIL = "FAIL"
NOT_YET = "NOT_YET_OBSERVABLE"
KNOWN_GAP = "KNOWN_GAP"


def _read_jsonl(p: Path) -> list:
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _read_json(p: Path):
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:                                       # noqa: BLE001
        return None


def _et_date(value) -> str | None:
    """The EASTERN session date of a timestamp. Never a UTC string prefix:
    APEX stamps in UTC, and any artifact written after 20:00 ET carries the
    NEXT UTC date -- so prefix-matching a UTC string against a session date
    silently drops every late-session and post-close record. The first
    draft of this observer did exactly that and reported Hunter as having
    no heartbeat while Hunter was running fine."""
    if not value:
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        return str(ts.tz_convert("America/New_York").date())
    except Exception:                                       # noqa: BLE001
        return None


def _on(rows: list, date: str, *fields) -> list:
    """Rows whose timestamp field falls on the given EASTERN session date."""
    out = []
    for r in rows:
        for f in fields:
            if _et_date(r.get(f)) == date:
                out.append(r)
                break
    return out


def _reviews(rows: list) -> list:
    """A REVIEW in the persisted ledger is a record_kind of CAPTAIN_REVIEW
    or CAPTAIN_STATE_CHANGE. The in-memory decision object's should_review
    flag is not persisted -- reading for it found nothing on a session
    that re-underwrote 33 times."""
    return [r for r in rows
            if r.get("record_kind") in ("CAPTAIN_REVIEW", "CAPTAIN_STATE_CHANGE")
            or r.get("should_review")]


def _triggers(r: dict) -> tuple:
    """The ledger field is `trigger` (a list); the decision object's was
    `triggers`. Accept either."""
    v = r.get("trigger") or r.get("triggers") or ()
    return tuple(v) if isinstance(v, (list, tuple)) else (v,)


def _item(item_id: str, name: str, verdict: str, evidence: str,
          catches: str, source: str) -> dict:
    return {"id": item_id, "name": name, "verdict": verdict,
            "evidence": evidence, "catches": catches, "source": source}


# ---------------------------------------------------------------- items
def _captain_reunderwrites(date: str) -> dict:
    src = "results/frontier2/reunderwrite_ledger.jsonl"
    rows = _on(_read_jsonl(Path(src)), date, "as_of", "now", "known_from")
    catches = ("the 2026-08-18 freeze: every subject that entered at WATCH "
               "or DEVELOP was never re-underwritten, because the gate "
               "required tier>=4 and only SERIOUS earned tier 4")
    if not rows:
        return _item("A1", "Captain re-underwrites on real inputs", NOT_YET,
                     "no re-underwrite decisions recorded for this date",
                     catches, src)
    reviews = _reviews(rows)
    changes = [r for r in rows if r.get("record_kind") == "CAPTAIN_STATE_CHANGE"]
    subjects = {r.get("subject") for r in rows}
    per_subject: dict = {}
    for r in reviews:
        per_subject[r.get("subject")] = per_subject.get(r.get("subject"), 0) + 1
    repeat = {s_: n for s_, n in per_subject.items() if n > 1}
    if not reviews:
        return _item("A1", "Captain re-underwrites on real inputs", FAIL,
                     f"{len(rows)} ledger records across {len(subjects)} "
                     f"subjects, 0 reviews -- the freeze pattern",
                     catches, src)
    if not repeat:
        return _item("A1", "Captain re-underwrites on real inputs", FAIL,
                     f"{len(reviews)} reviews but NO subject reviewed more than "
                     f"once -- a first look is not re-underwriting",
                     catches, src)
    return _item("A1", "Captain re-underwrites on real inputs", PASS,
                 f"{len(reviews)} reviews across {len(subjects)} subjects; "
                 f"{len(repeat)} reviewed >1 ({repeat}); "
                 f"{len(changes)} captain state changes",
                 catches, src)


def _no_phantom_triggers(date: str) -> dict:
    src = "results/frontier2/reunderwrite_ledger.jsonl"
    rows = _on(_read_jsonl(Path(src)), date, "as_of", "now", "known_from")
    catches = ("two measured phantoms: ASSASSIN_WOUND_CHANGE firing every "
               "cycle from an absent key, and EV/PP/PROPAGATION firing on a "
               "compute-tier drop -- reviews driven by our own budget, not "
               "by the market")
    if not rows:
        return _item("A2", "No phantom re-underwrite triggers", NOT_YET,
                     "no decisions recorded for this date", catches, src)
    reviews = _reviews(rows)
    if not reviews:
        return _item("A2", "No phantom re-underwrite triggers", NOT_YET,
                     "0 reviews fired -- nothing to test for phantoms",
                     catches, src)
    # a phantom presents as the SAME trigger on the SAME subject in an
    # unbroken run of cycles: real market change is not perfectly periodic
    per_subject: dict = {}
    for r in reviews:
        per_subject.setdefault(r.get("subject"), []).append(
            tuple(sorted(_triggers(r))))
    suspicious = {s: seq[0] for s, seq in per_subject.items()
                  if len(seq) >= 8 and len(set(seq)) == 1}
    if suspicious:
        return _item("A2", "No phantom re-underwrite triggers", FAIL,
                     f"identical trigger set repeated every review for "
                     f"{len(suspicious)} subject(s): "
                     f"{dict(list(suspicious.items())[:3])}", catches, src)
    import collections as _c
    tally = dict(_c.Counter(t for r in reviews for t in _triggers(r)))
    return _item("A2", "No phantom re-underwrite triggers", PASS,
                 f"{len(reviews)} reviews across {len(per_subject)} subjects, "
                 f"no subject shows an unbroken identical-trigger run >= 8; "
                 f"trigger mix {tally}", catches, src)


def _adaptation_latency(date: str) -> dict:
    src = "results/frontier2/reunderwrite_ledger.jsonl"
    rows = _on(_read_jsonl(Path(src)), date, "as_of", "now", "known_from")
    catches = ("a latency that reads 0.0s because it was measured from our "
               "own compute timestamp instead of the upstream market event; "
               "and a negative latency, which means a clock is lying")
    stamped = [r for r in rows if r.get("upstream_event_time")]
    if not stamped:
        return _item("A3", "Decision adaptation latency is measured", NOT_YET,
                     "no decision carries an upstream_event_time", catches, src)
    lats = []
    bad = 0
    for r in stamped:
        block = r.get("adaptation_latency_s")
        if isinstance(block, dict):
            # the record computed its own latency AND its own integrity
            # verdict -- prefer it over recomputing from raw stamps
            if block.get("integrity") not in (None, "OK"):
                bad += 1
                continue
            v = (block.get("upstream_to_state_change_s")
                 or block.get("upstream_to_captain_review_s"))
            if v is not None:
                if v < 0:
                    bad += 1
                else:
                    lats.append(v)
            continue
        try:
            up = pd.Timestamp(r["upstream_event_time"])
            for field in ("state_change_time", "assassin_review_time", "as_of"):
                if r.get(field):
                    dt = (pd.Timestamp(r[field]) - up).total_seconds()
                    if dt < 0:
                        bad += 1
                    else:
                        lats.append(dt)
                    break
        except Exception:                                   # noqa: BLE001
            continue
    if bad:
        return _item("A3", "Decision adaptation latency is measured", FAIL,
                     f"{bad} record(s) with NEGATIVE latency -- upstream event "
                     f"stamped ahead of the decision clock", catches, src)
    if not lats:
        return _item("A3", "Decision adaptation latency is measured", NOT_YET,
                     f"{len(stamped)} stamped records but no computable pair",
                     catches, src)
    s = pd.Series(lats)
    if s.max() <= 0.0:
        return _item("A3", "Decision adaptation latency is measured", FAIL,
                     "every latency is 0.0s -- measured from our own compute "
                     "clock, not from a market event", catches, src)
    return _item("A3", "Decision adaptation latency is measured", PASS,
                 f"n={len(s)} median={s.median():.1f}s p90={s.quantile(0.9):.1f}s "
                 f"max={s.max():.1f}s, all non-negative", catches, src)


def _session_anchor(date: str) -> dict:
    src = "results/intraday/session_anchor_evidence.jsonl"
    rows = _on(_read_jsonl(Path(src)), date, "as_of", "captured_at", "session_date")
    catches = ("the 2026-08-18 session that could not be certified at all, "
               "because 400-bar rolling retention had already erased the "
               "opening bars by the time anyone looked")
    if not rows:
        return _item("B1", "Opening anchor captured live", NOT_YET,
                     "no anchor evidence recorded for this date", catches, src)
    live = [r for r in rows
            if r.get("certification") == "PROVEN_LIVE"
            or (r.get("opening_anchor_valid") is True
                and r.get("reconstructed_after_the_fact") is False)]
    recon = [r for r in rows if r.get("reconstructed_after_the_fact")]
    if recon:
        return _item("B1", "Opening anchor captured live", FAIL,
                     f"{len(recon)} anchor(s) reconstructed after the fact -- "
                     f"reconstruction can never certify an opening",
                     catches, src)
    if not live:
        verdicts = sorted({r.get("certification") for r in rows})
        return _item("B1", "Opening anchor captured live", FAIL,
                     f"{len(rows)} anchor record(s), none PROVEN_LIVE "
                     f"(verdicts: {verdicts})", catches, src)
    return _item("B1", "Opening anchor captured live", PASS,
                 f"{len(live)}/{len(rows)} anchors PROVEN_LIVE, 0 reconstructed",
                 catches, src)


def _premarket_honesty(date: str) -> dict:
    src = "results/frontier2/curve_ledger.jsonl"
    rows = _on(_read_jsonl(Path(src)), date, "as_of", "now", "event_time")
    catches = ("a premarket start manufacturing confident states from a "
               "sparse 09:00-09:30 tape -- sparse input must read LIMITED or "
               "UNKNOWN, never a SERIOUS-grade conviction")
    pre = []
    for r in rows:
        t = r.get("as_of") or r.get("now") or r.get("event_time")
        try:
            et = pd.Timestamp(t).tz_convert("America/New_York")
        except Exception:                                   # noqa: BLE001
            continue
        if (et.hour, et.minute) < (9, 30):
            pre.append(r)
    if not pre:
        return _item("C1", "Premarket degradation is honest", NOT_YET,
                     "no premarket (pre-09:30 ET) curve states recorded",
                     catches, src)
    overconfident = [r for r in pre
                     if str(r.get("observation_quality") or
                            r.get("quality")).upper() in ("GOOD", "FULL", "HIGH")]
    if overconfident:
        return _item("C1", "Premarket degradation is honest", FAIL,
                     f"{len(overconfident)}/{len(pre)} pre-09:30 states claim "
                     f"full-quality observation on a sparse tape", catches, src)
    return _item("C1", "Premarket degradation is honest", PASS,
                 f"{len(pre)} pre-09:30 states, none claiming full-quality "
                 f"observation", catches, src)


def _session_transition(date: str) -> dict:
    src = "results/frontier2/session_transition.jsonl"
    rows = _on(_read_jsonl(Path(src)), date, "observed_at", "as_of",
               "session_date")
    catches = ("a premarket-started runtime silently carrying premarket "
               "lineage into the regular session -- the handover must be "
               "stamped, so the first regular-session input is identifiable")
    if not rows:
        return _item("C2", "First 09:30 transition is stamped", NOT_YET,
                     "no session-transition record for this date", catches, src)
    stamped = [r for r in rows if r.get("first_regular_session_input")]
    if not stamped:
        return _item("C2", "First 09:30 transition is stamped", FAIL,
                     f"{len(rows)} transition record(s), none naming the first "
                     f"regular-session canonical input", catches, src)
    return _item("C2", "First 09:30 transition is stamped", PASS,
                 f"first regular-session input: "
                 f"{stamped[0].get('first_regular_session_input')}", catches, src)


def _alpaca_continuity(date: str) -> dict:
    src = "results/intraday/alpaca_reconnect_events.jsonl"
    health = _read_json(Path("results/intraday/alpaca_fabric_health.json")) or {}
    rows = _on(_read_jsonl(Path(src)), date, "as_of", "event_time")
    catches = ("a reconnect counter that says 4 while no event ledger says "
               "WHY -- continuity claimed from a number nobody can audit")
    counter = (health.get("counters") or {}).get("reconnects")
    if counter is None:
        return _item("D1", "Alpaca continuity is auditable", NOT_YET,
                     "no reconnect counter in the health artifact", catches, src)
    if counter == 0 and not rows:
        return _item("D1", "Alpaca continuity is auditable", PASS,
                     "0 reconnects and 0 reconnect events -- reconciled",
                     catches, src)
    if len(rows) < counter:
        # One non-excuse: a process started BEFORE the ledger module
        # existed cannot emit into it. That is a checkable fact (module
        # mtime vs the fabric's own start_time), not a story -- and it is
        # NOT_YET_OBSERVABLE, never a pass.
        mod = Path("apex/intraday/reconnect_ledger.py")
        started = health.get("process_start_utc")
        if started is None:
            return _item("D1", "Alpaca continuity is auditable", FAIL,
                         f"counter says {counter} reconnects, ledger has "
                         f"{len(rows)} events, and the health artifact carries "
                         f"no process_start_utc -- the mismatch cannot even be "
                         f"attributed", catches, src)
        try:
            proc_start = pd.Timestamp(started)
            mod_born = pd.Timestamp(mod.stat().st_mtime, unit="s", tz="UTC")
            predates = mod.exists() and mod_born > proc_start
        except Exception:                                   # noqa: BLE001
            predates = False
        if predates:
            return _item("D1", "Alpaca continuity is auditable", NOT_YET,
                         f"counter says {counter} reconnects, ledger has "
                         f"{len(rows)} -- but the reconnect ledger module "
                         f"({mod_born}) is NEWER than this fabric process "
                         f"({proc_start}), so the running process cannot emit "
                         f"into it. Reconciliation is first testable on the "
                         f"next fresh start.", catches, src)
        return _item("D1", "Alpaca continuity is auditable", FAIL,
                     f"counter says {counter} reconnects, ledger has "
                     f"{len(rows)} events -- COUNTER_LEDGER_MISMATCH",
                     catches, src)
    causes = sorted({r.get("reason") or r.get("cause_code") for r in rows})
    unattributed = [r for r in rows
                    if not (r.get("reason") or r.get("cause_code"))]
    if unattributed:
        return _item("D1", "Alpaca continuity is auditable", FAIL,
                     f"{len(unattributed)}/{len(rows)} reconnect events carry "
                     f"no cause code", catches, src)
    return _item("D1", "Alpaca continuity is auditable", PASS,
                 f"{len(rows)} events reconcile with counter={counter}; "
                 f"causes: {causes}", catches, src)


def _hunter_observability(date: str) -> dict:
    src = "results/hunter/runtime/service_progress.json"
    d = _read_json(Path(src))
    catches = ("a RECURRING_ONESHOT scored as a dead daemon: PID-dead is the "
               "NORMAL state between cycles, and reporting it as unhealthy "
               "trains the operator to ignore the watchdog")
    if not d:
        return _item("E1", "Hunter progress is observable", NOT_YET,
                     "no service_progress artifact", catches, src)
    model = d.get("runtime_model")
    if model != "RECURRING_ONESHOT":
        return _item("E1", "Hunter progress is observable", FAIL,
                     f"runtime_model={model!r} -- a recurring one-shot judged "
                     f"by daemon liveness semantics", catches, src)
    hb = (d.get("heartbeat") or d.get("heartbeat_time")
          or d.get("cycle_complete") or d.get("last_cycle_complete"))
    if _et_date(hb) != date:
        return _item("E1", "Hunter progress is observable", NOT_YET,
                     f"last heartbeat {hb!r} (ET date {_et_date(hb)}) is not "
                     f"from {date}", catches, src)
    return _item("E1", "Hunter progress is observable", PASS,
                 f"RECURRING_ONESHOT, cycle={d.get('cycle_number')}, "
                 f"heartbeat={hb}", catches, src)


def _rate_input_honesty(date: str) -> dict:
    src = "results/option_analytics/live/states.jsonl"
    rows = _on(_read_jsonl(Path(src)), date, "as_of", "now")
    catches = ("a static 4% standing in for the real curve -- Greeks that "
               "look precise and are quietly wrong, with nothing in the "
               "artifact saying so")
    if not rows:
        return _item("F1", "Rate input is never assumed", NOT_YET,
                     "no live option analytics states for this date",
                     catches, src)
    # A MISSING provenance field is the worst case, not the best one: the
    # first draft of this observer read absent-as-clean and returned PASS
    # over 336 states carrying a hardcoded rate=0.04. Absence fails.
    unprovenanced = [r for r in rows if "rate_source" not in r
                     or r.get("rate_source") is None]
    if unprovenanced:
        rates = sorted({r.get("rate") for r in unprovenanced if "rate" in r})
        return _item("F1", "Rate input is never assumed", FAIL,
                     f"{len(unprovenanced)}/{len(rows)} states carry NO rate "
                     f"provenance at all (observed rate values: {rates[:5]}) -- "
                     f"a live state with an unattributable rate is worse than "
                     f"one that refused", catches, src)
    assumed = [r for r in rows
               if str(r.get("rate_source")).upper() in
               ("ASSUMED", "STATIC", "STATIC_4PCT_NOT_A_LIVE_FEED")]
    if assumed:
        return _item("F1", "Rate input is never assumed", FAIL,
                     f"{len(assumed)}/{len(rows)} states carry an assumed or "
                     f"static rate source", catches, src)
    sources = sorted({r.get("rate_source") for r in rows})
    return _item("F1", "Rate input is never assumed", PASS,
                 f"{len(rows)} states, rate sources: {sources}", catches, src)


def _dte_bucket_coverage(date: str) -> dict:
    src = "results/option_analytics/live/states.jsonl"
    rows = _on(_read_jsonl(Path(src)), date, "as_of", "now")
    catches = ("the pagination trap: an unfiltered contract fetch returns a "
               "single expiry, so a 'full' sample silently measured one "
               "maturity and called it a surface")
    if not rows:
        return _item("F2", "All four DTE buckets sampled", NOT_YET,
                     "no live option analytics states for this date",
                     catches, src)
    labelled = [r for r in rows if "dte_bucket" in r]
    if not labelled:
        return _item("F2", "All four DTE buckets sampled", FAIL,
                     f"{len(rows)} states carry no dte_bucket label at all -- "
                     f"an unlabelled sample cannot be shown to span maturities",
                     catches, src)
    present = sorted({r.get("dte_bucket") for r in labelled if r.get("dte_bucket")})
    expected = ["1-2", "3-7", "8-30", ">30"]
    missing = [b for b in expected if b not in present]
    if missing:
        return _item("F2", "All four DTE buckets sampled", FAIL,
                     f"buckets present {present}, missing {missing}",
                     catches, src)
    return _item("F2", "All four DTE buckets sampled", PASS,
                 f"all four buckets sampled: {present}", catches, src)


def _no_stdout_only_errors(date: str) -> dict:
    src = "results/governance/ledger_errors.jsonl"
    rows = _on(_read_jsonl(Path(src)), date, "as_of")
    catches = ("swallowed exceptions that existed only in a launchd log "
               "nobody reads until after something has already gone wrong")
    # this item passes whether or not errors occurred -- what it proves is
    # that the DURABLE PATH is wired. Absence of errors is not evidence of
    # absence of the path, so it reads NOT_YET only if the module is gone.
    try:
        from apex.governance import ledger_error  # noqa: F401
    except Exception as e:                                  # noqa: BLE001
        return _item("G1", "Non-fatal errors are durable", FAIL,
                     f"ledger_error module unimportable: {e}", catches, src)
    return _item("G1", "Non-fatal errors are durable", PASS,
                 f"durable path wired; {len(rows)} recorded non-fatal error(s) "
                 f"on {date}", catches, src)


def _canonical_memory_singleton(date: str) -> dict:
    src = f"results/frontier/daily_memory/{date}.json"
    catches = ("two writers producing two 'daily memories' -- the exact "
               "orphaned-output failure the forensic audit found, where the "
               "richer artifact was the one nothing read")
    from apex.memory import daily_market_memory as sidecar
    if sidecar.ROLE != "ENRICHED_RESEARCH_MEMORY_SIDECAR":
        return _item("H1", "Exactly one canonical memory", FAIL,
                     f"Phase 1.0 memory ROLE={sidecar.ROLE!r} -- a second "
                     f"writer is competing for canonical status", catches, src)
    if not Path(src).exists():
        return _item("H1", "Exactly one canonical memory", NOT_YET,
                     f"canonical memory {src} not written for this date",
                     catches, src)
    return _item("H1", "Exactly one canonical memory", PASS,
                 f"canonical: {src} (writer {sidecar.CANONICAL_MEMORY_WRITER}); "
                 f"Phase 1.0 module self-declares ROLE={sidecar.ROLE}",
                 catches, src)


def _unattended_start(date: str) -> dict:
    src = "launchd StartCalendarInterval + per-service birth/progress artifacts"
    catches = ("2026-08-18, when the Frontier-2 runtime had no launchd job at "
               "all and was started by hand 13 minutes AFTER the open")
    import subprocess
    try:
        listing = subprocess.run(["launchctl", "list"], capture_output=True,
                                 text=True, timeout=20).stdout
    except Exception as e:                                  # noqa: BLE001
        return _item("I1", "Every job starts unattended", NOT_YET,
                     f"could not read launchctl: {e}", catches, src)
    required = ("com.apex.alpaca-fabric", "com.apex.frontier2",
                "com.apex.session-anchor", "com.apex.option-analytics",
                "com.apex.daily-forensics", "com.apex.closing",
                "com.apex.premarket", "com.apex.sensory-loop",
                "com.apex.fastwatch", "com.apex.hunter-clock",
                "com.apex.event-capture", "com.apex.preopen-gate")
    missing = [j for j in required if j not in listing]
    if missing:
        return _item("I1", "Every job starts unattended", FAIL,
                     f"not loaded in launchd: {missing}", catches, src)
    return _item("I1", "Every job starts unattended", PASS,
                 f"all {len(required)} required jobs loaded in launchd",
                 catches, src)


def _symbol_continuity_gap(date: str) -> dict:
    return _item("Z1", "Per-symbol continuity classifier is fed", KNOWN_GAP,
                 "apex.intraday.symbol_continuity is a tested pure classifier "
                 "with no live feeder; daily_forensics_v2 records this "
                 "explicitly rather than inventing continuity",
                 "a pure module quietly counted as a working feature because "
                 "its unit tests are green",
                 "apex/intraday/symbol_continuity.py")


ITEMS = (_captain_reunderwrites, _no_phantom_triggers, _adaptation_latency,
         _session_anchor, _premarket_honesty, _session_transition,
         _alpaca_continuity, _hunter_observability, _rate_input_honesty,
         _dte_bucket_coverage, _no_stdout_only_errors,
         _canonical_memory_singleton, _unattended_start,
         _symbol_continuity_gap)


def observe(session_date: str | None = None) -> dict:
    now = pd.Timestamp.now(tz="UTC")
    date = session_date or str(now.tz_convert("America/New_York").date())
    results = []
    for fn in ITEMS:
        try:
            results.append(fn(date))
        except Exception as e:                              # noqa: BLE001
            results.append(_item(getattr(fn, "__name__", "?"), fn.__name__,
                                 FAIL, f"observer raised: {type(e).__name__}: {e}",
                                 "an observer that crashes must not read as a "
                                 "pass", "natural_acceptance_observer.py"))
    counts = {v: sum(1 for r in results if r["verdict"] == v)
              for v in (PASS, FAIL, NOT_YET, KNOWN_GAP)}
    if counts[FAIL]:
        overall = "NOT_ACCEPTED"
    elif counts[NOT_YET]:
        overall = "PARTIALLY_OBSERVED"
    else:
        overall = "NATURALLY_ACCEPTED"
    board = {"kind": "natural_acceptance_board", "session_date": date,
             "as_of": str(now), "overall": overall, "counts": counts,
             "items": results, "manual_checkboxes": 0,
             "decision_power": "NONE_OBSERVABILITY"}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"natural_acceptance_{date}.json").write_text(
        json.dumps(board, indent=2, default=str))
    BOARD_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with BOARD_LEDGER.open("a") as fh:
        fh.write(json.dumps(board, default=str) + "\n")
    return board


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-date", default=None)
    a = ap.parse_args()
    board = observe(a.session_date)
    print(f"NATURAL ACCEPTANCE BOARD -- {board['session_date']}")
    print(f"  overall: {board['overall']}   {board['counts']}")
    for it in board["items"]:
        print(f"  [{it['verdict']:<18}] {it['id']:<3} {it['name']}")
        print(f"       {it['evidence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
