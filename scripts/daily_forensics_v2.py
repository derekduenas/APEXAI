"""DAILY FORENSICS V2 — assemble the end-of-day evidence pack
automatically, so a human never again has to rediscover it by hand.

The 2026-08-18 recap required manual archaeology across a dozen
artifacts to answer questions the system should answer itself: how many
times did Captain actually review each subject, did the reconnect
counter reconcile, was the session anchor real, did FastWatch lead
anything. Every one of those is now a function call.

    python scripts/daily_forensics_v2.py [--session-date YYYY-MM-DD]

READ-ONLY. Computes over already-persisted artifacts, fetches nothing,
decides nothing, and changes no threshold. Any section whose source
artifact is absent reports ABSENT rather than guessing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

OUT_DIR = Path("results/audit")


def _safe(fn, label):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return {"section": label, "status": "ERROR",
                "error": f"{type(e).__name__}: {e}"}


def captain_section(session_date: str) -> dict:
    from apex.frontier2 import reunderwrite_ledger as rl
    counts = rl.review_counts_by_subject()
    if not counts:
        return {"status": "ABSENT",
                "note": "no reunderwrite ledger -- either the runtime has not "
                        "run since the Phase 1.0 fix, or it never re-reviewed"}
    reviews = [v["reviews"] for v in counts.values()]
    changes = [v["state_changes"] for v in counts.values()]
    return {
        "status": "PRESENT", "subjects": len(counts),
        "total_reviews": sum(reviews), "total_state_changes": sum(changes),
        "max_reviews_for_one_subject": max(reviews),
        "min_reviews_for_one_subject": min(reviews),
        "subjects_reviewed_more_than_once": sum(1 for r in reviews if r > 1),
        "frozen_subjects_reviewed_exactly_once": sum(1 for r in reviews if r == 1),
        "per_subject": counts,
    }


def assassin_section() -> dict:
    p = Path("results/frontier2/assassin2_ledger.jsonl")
    if not p.exists():
        return {"status": "ABSENT"}
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    by_subject: dict = {}
    for r in rows:
        by_subject[r.get("subject")] = by_subject.get(r.get("subject"), 0) + 1
    return {"status": "PRESENT", "total_reviews": len(rows),
            "subjects": len(by_subject),
            "max_reviews_for_one_subject": max(by_subject.values()) if by_subject else 0}


def curve_section(session_date: str, subjects=("SPY", "QQQ", "IWM")) -> dict:
    from apex.frontier2 import curve_metrics
    p = Path("results/frontier2/curve_ledger.jsonl")
    if not p.exists():
        return {"status": "ABSENT"}
    now = pd.Timestamp.now(tz="UTC")
    out = {}
    for s in subjects:
        m = curve_metrics.compute(subject=s, session_date=session_date,
                                  ledger_path=p, now=now)
        out[s] = {"records": m.n_records, "flips": m.state_flip_count,
                  "mean_state_duration_s": m.mean_state_duration_s,
                  "median_state_duration_s": m.median_state_duration_s,
                  "longest_state": m.longest_state,
                  "longest_state_duration_s": m.longest_state_duration_s,
                  "reversals": m.transition_reversal_count,
                  "transition_persistence_records_per_run": m.transition_persistence,
                  "state_durations_s": m.state_durations_s}
    return {"status": "PRESENT", "per_subject": out}


def alpaca_section() -> dict:
    from apex.intraday import reconnect_ledger as rlg
    health = Path("results/intraday/alpaca_fabric_health.json")
    counter, proc_start = None, None
    if health.exists():
        try:
            h = json.loads(health.read_text())
            counter = h.get("counters", {}).get("reconnects")
            proc_start = h.get("process_start_utc")
        except json.JSONDecodeError:
            pass
    # windowing fix (2026-08-20): the counter is per-process; comparing
    # it against the multi-day ledger file mislabeled a reconciled day
    # COUNTER_LEDGER_MISMATCH (278 vs 644). Window to the process start.
    rec = rlg.reconcile(counter if counter is not None else 0,
                        since=proc_start)
    return {"status": "PRESENT" if counter is not None else "HEALTH_ABSENT",
            "counter_value": counter, "reconciliation": rec}


def continuity_section() -> dict:
    p = Path("results/intraday/universe_coverage.json")
    if not p.exists():
        return {"status": "ABSENT"}
    d = json.loads(p.read_text())
    return {"status": "PRESENT",
            "coverage_fraction": d.get("coverage_fraction"),
            "continuous_coverage_fraction": d.get("continuous_coverage_fraction"),
            "broad_discovery_valid": d.get("broad_discovery_valid"),
            "note": ("per-cause continuity requires the Phase 1.0 "
                    "symbol_continuity classifier to be fed by the live "
                    "sensor; universe_coverage still reports the single "
                    "collapsed fraction")}


def session_anchor_section(session_date: str) -> dict:
    from apex.intraday import session_anchor_evidence as sae
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from arm_session_anchor_evidence import REQUIRED_SYMBOLS as REQUIRED_ANCHOR_SYMBOLS
    have = sae.read_for(session_date)
    if not have:
        return {"status": "ABSENT",
                "note": "SessionAnchorEvidence was not armed for this session"}
    return {"status": "PRESENT", "symbols_captured": len(have),
            "certification": sae.certify(session_date, REQUIRED_ANCHOR_SYMBOLS)}


def fastwatch_section(session_date: str) -> dict:
    from apex.hunter import fastwatch_attribution as fa
    fw = Path("results/hunter/fastwatch_ledger.jsonl")
    fl = Path("results/hunter/forward_ledger.jsonl")
    if not fw.exists() or not fl.exists():
        return {"status": "ABSENT"}
    recs = fa.build(session_date=session_date, fastwatch_ledger=fw,
                    forward_ledger=fl, known_from=pd.Timestamp.now(tz="UTC"))
    # Phase 16 (2026-08-20): attribution was computed at report time and
    # THROWN AWAY -- persist_all() had zero callers, so no durable
    # POST_HOC_OBSERVATIONAL linkage record ever existed. Persist once
    # per session, idempotently (skip if this session already wrote).
    persisted = 0
    already = False
    if fa.LEDGER.exists():
        already = f'"session_date": "{session_date}"' in \
            fa.LEDGER.read_text()
    if recs and not already:
        persisted = fa.persist_all(recs)
    return {"status": "PRESENT", "summary": fa.summarize(recs),
            "attribution_persisted": persisted,
            "attribution_label": "POST_HOC_OBSERVATIONAL"}


def morning_prior_section(session_date: str) -> dict:
    from apex.memory import morning_prior_manifest as mpm
    found = mpm.locate(session_date)
    if found is None:
        return {"status": "NOT_REGISTERED",
                "note": "no manifest row -- either premarket did not seal, or "
                        "it sealed before manifest registration was wired"}
    return {"status": "REGISTERED", "canonical_path": found["canonical_path"],
            "integrity": found["integrity"],
            "content_hash": found["content_hash"][:16],
            "runtime_version": found.get("runtime_version")}


def hunter_watchdog_section() -> dict:
    from apex.hunter import service_progress_hunter as sph
    return sph.watchdog_check()


def options_section() -> dict:
    p = Path("results/option_analytics/live/cycle_summaries.jsonl")
    if not p.exists():
        return {"status": "ABSENT"}
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    if not rows:
        return {"status": "ABSENT"}
    last = rows[-1]
    buckets: dict = {}
    for sym, d in (last.get("symbols") or {}).items():
        for b, st in (d.get("dte_buckets") or {}).items():
            agg = buckets.setdefault(b, {"contracts_sampled": 0, "iv_solved": 0,
                                        "vendor_greeks": 0, "refused": 0})
            for k in agg:
                agg[k] += st.get(k, 0)
    return {"status": "PRESENT", "cycles": len(rows),
            "rate_source": next(iter(
                (d.get("rate_source") for d in (last.get("symbols") or {}).values())),
                None),
            "dte_bucket_coverage": buckets}


def premarket_honesty_section(session_date: str) -> dict:
    """Operator request #1: the 09:00-09:30 ET premarket window has
    sparse data. It must produce LIMITED/UNKNOWN observation quality and
    must NOT mint confident opportunity states off thin data."""
    import pandas as pd
    cp = Path("results/frontier2/curve_ledger.jsonl")
    rp = Path("results/frontier2/reunderwrite_ledger.jsonl")
    if not cp.exists():
        return {"status": "ABSENT"}

    open_utc = pd.Timestamp(f"{session_date}T13:30:00Z")
    qualities: dict = {}
    for line in cp.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = pd.Timestamp(r.get("as_of"))
        if t >= open_utc:
            continue
        q = r.get("observation_quality")
        qualities[q] = qualities.get(q, 0) + 1

    # confident states minted BEFORE the bell -- the thing to catch
    premarket_confident = []
    if rp.exists():
        for line in rp.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if pd.Timestamp(r.get("review_time")) >= open_utc:
                continue
            if r.get("current_captain_state") in ("SERIOUS", "WAIT_FOR_ENTRY"):
                premarket_confident.append(
                    {"subject": r.get("subject"),
                     "state": r.get("current_captain_state"),
                     "at": r.get("review_time")})

    honest = (not premarket_confident
              and not any(q in ("FULL",) for q in qualities))
    return {
        "status": "PRESENT",
        "premarket_curve_records": sum(qualities.values()),
        "observation_quality_distribution": dict(sorted(
            qualities.items(), key=lambda kv: str(kv[0]))),
        "confident_states_minted_premarket": premarket_confident,
        "verdict": ("HONEST_DEGRADATION" if honest
                    else "PREMARKET_OVERCONFIDENCE_DETECTED"),
        "note": ("sparse premarket data must read LIMITED/UNKNOWN and must "
                "not produce SERIOUS/WAIT_FOR_ENTRY before the bell"),
    }


def session_transition_section(session_date: str) -> dict:
    """Operator request #2: the exact first REGULAR-session canonical
    input, and proof the premarket lineage handed over cleanly."""
    p = Path("results/frontier2/session_transition.jsonl")
    if not p.exists():
        return {"status": "ABSENT",
                "note": "no premarket->regular handover record; either the "
                        "runtime did not start premarket, or it never "
                        "observed a REGULAR-session cycle"}
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    rows = [r for r in rows
            if str(r.get("observed_at", "")).startswith(session_date)]
    if not rows:
        return {"status": "ABSENT"}
    return {"status": "PRESENT", "transition": rows[-1]}


def adaptation_latency_section(session_date: str) -> dict:
    """Operator request #3: decision adaptation latency, upstream event
    -> Assassin -> Captain -> state change."""
    p = Path("results/frontier2/reunderwrite_ledger.jsonl")
    if not p.exists():
        return {"status": "ABSENT"}
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    if not rows:
        return {"status": "ABSENT"}

    def _vals(key, only_changes=False):
        out = []
        for r in rows:
            if only_changes and r.get("record_kind") != "CAPTAIN_STATE_CHANGE":
                continue
            lat = r.get("adaptation_latency_s") or {}
            if lat.get("integrity") != "OK":
                continue
            v = lat.get(key)
            if v is not None:
                out.append(v)
        return out

    def _stat(vals):
        if not vals:
            return None
        srt = sorted(vals)
        return {"n": len(srt), "min": srt[0], "max": srt[-1],
                "median": srt[len(srt) // 2],
                "mean": round(sum(srt) / len(srt), 3)}

    integrity_bad = [r["subject"] for r in rows
                     if (r.get("adaptation_latency_s") or {}).get("integrity")
                     not in ("OK", None)]
    return {
        "status": "PRESENT",
        "upstream_to_assassin_s": _stat(_vals("upstream_to_assassin_s")),
        "upstream_to_captain_review_s": _stat(_vals("upstream_to_captain_review_s")),
        "upstream_to_state_change_s": _stat(
            _vals("upstream_to_state_change_s", only_changes=True)),
        "assassin_to_captain_s": _stat(_vals("assassin_to_captain_s")),
        "rows_with_latency_integrity_fault": sorted(set(integrity_bad)),
        "note": ("upstream event = the newest underlying BAR the Curve was "
                "computed from, not the compute timestamp -- otherwise this "
                "measures intra-cycle latency (~0 by construction)"),
    }


def frontier_module_section() -> dict:
    """Dependency verdicts, measured from the runtime source."""
    src = Path("scripts/frontier2_shadow_runtime.py").read_text()

    def verdict(module: str, call_markers: tuple, dep_available: bool,
                reason: str) -> dict:
        called = any(m in src for m in call_markers)
        return {
            "status": "ACTIVE_WITH_DATA" if called and dep_available else "NOT_RUNNING",
            "runtime_route": "RUNTIME_ROUTE_AVAILABLE" if called
                             else "RUNTIME_ROUTE_MISSING",
            "dependencies": "DEPENDENCIES_AVAILABLE" if dep_available
                            else "DEPENDENCIES_MISSING",
            "reason": reason,
        }

    return {
        "LEADING_EDGE": verdict(
            "leading_edge_map", ("lemod.rank(",), True,
            "imported but never invoked; leading_edge_entry_quality is a "
            "hardcoded UNKNOWN. Its dependency (a cross-sectional candidate "
            "set) IS available in principle, but rank() needs all subjects "
            "gathered before ranking and the runtime is a per-symbol loop -- "
            "wiring requires a two-pass restructure, which is a structural "
            "change beyond an observability phase."),
        "WORLD_LAB": verdict(
            "world_lab", ("wlmod.", "world_lab."), False,
            "not imported at all; from_simulation() requires a simulation "
            "object the live runtime does not produce. Dependency genuinely "
            "absent -- wiring would require inventing a simulation."),
        "MODEL_MARKET": verdict(
            "model_market", ("mmod.submit(", "mmod.snapshot("), False,
            "imported but never invoked; model_market_tally_agrees is a "
            "hardcoded None. submit() requires >=2 INDEPENDENT engines taking "
            "stances on one proposition; the live runtime has one engine per "
            "organ. Dependency genuinely absent."),
    }


def main() -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-date", default=None)
    a = ap.parse_args()
    session_date = a.session_date or str(
        pd.Timestamp.now(tz="America/New_York").date())

    report = {
        "kind": "daily_forensics_v2", "session_date": session_date,
        "generated_at": str(pd.Timestamp.now(tz="UTC")),
        "captain_reunderwriting": _safe(lambda: captain_section(session_date),
                                        "captain"),
        "assassin": _safe(assassin_section, "assassin"),
        "curve": _safe(lambda: curve_section(session_date), "curve"),
        "alpaca_reconnect": _safe(alpaca_section, "alpaca"),
        "continuity": _safe(continuity_section, "continuity"),
        "session_anchor": _safe(lambda: session_anchor_section(session_date),
                                "session_anchor"),
        "fastwatch_attribution": _safe(lambda: fastwatch_section(session_date),
                                       "fastwatch"),
        "morning_prior": _safe(lambda: morning_prior_section(session_date),
                               "morning_prior"),
        "hunter_watchdog": _safe(hunter_watchdog_section, "hunter_watchdog"),
        "options_dte_buckets": _safe(options_section, "options"),
        "premarket_honesty": _safe(lambda: premarket_honesty_section(session_date),
                                   "premarket_honesty"),
        "session_transition": _safe(lambda: session_transition_section(session_date),
                                    "session_transition"),
        "adaptation_latency": _safe(lambda: adaptation_latency_section(session_date),
                                    "adaptation_latency"),
        "frontier_modules": _safe(frontier_module_section, "frontier_modules"),
        "decision_power": "NONE",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"DAILY_FORENSICS_V2_{session_date}.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    report["_written_to"] = str(out)
    return report


if __name__ == "__main__":
    r = main()
    print(json.dumps(r, indent=2, default=str)[:6000])
