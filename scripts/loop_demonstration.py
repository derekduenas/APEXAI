"""COMPLETE LOOP DEMONSTRATION under docs/LOOP_EVALUATION_CONTRACT.md (frozen before the 2026-09-12 run).

    python scripts/loop_demonstration.py <collection_dir> <prior_bars.json> <out_base_dir> [run_id]

REPAIRED BY OPERATING-LOOP-001, AND NOT RE-RUN. Three defects of the 2026-09-12 driver are removed here; no
recorded evaluation was executed in the repairing brick (its scope is synthetic inputs only), so this file is
REPAIRED BUT UNEXERCISED ON RECORDED DATA. Its building blocks -- the lifecycle scheduler, the run directory and
the replay route -- are covered by tests/test_operating_loop_001.py.

    1. IT REWOUND THE CLOCK. It ran every scan, then set `rec.t = t0 + HOLD_S` to value the exits, moving time from
       16:15Z back to 13:45Z. Eleven of twelve scans had already been refused for capacity that was never released.
       Now the shared lifecycle scheduler owns time, services each exit at its own deadline, and refuses a rewind.
    2. IT DESTROYED THE RUN IT CORRECTED. It wrote to a fixed directory and unlinked its ledgers on start, so the
       corrected re-run overwrote the original run's JSON and all three ledgers. Now every run claims its own
       directory and a collision is refused.
    3. IT CLAIMED PROSPECTIVE EVIDENCE FOR RECORDED DATA. It built a boundary with provenance LIVE_FEED over a
       burned session. Now it takes the explicit, fail-closed RECORDED_REPLAY route, whose records are sealed
       ineligible for live authorization, promotion and prospective-results aggregation.

Three policies — WAIT, PILOT_RULE_V2, FULL_FUNNEL_V1 — over the SAME scan instants, through the SAME real boundary,
risk authority, kernel, fees, execution policy, exit policy and Book. Only the selection policy differs. Every scan
is recorded whether it trades or not, with the model identity actually used at each stage or the literal
UNAVAILABLE and its reason. Retained artifacts only; no provider request. Quarantined replay ledgers."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, ".")
from apex.decision_wb.engine import FUNNEL_RULE_ID, FunnelEngine  # noqa: E402
from apex.options_pilot import boundary as B, expression_rule as ER, ledger as L, session as S  # noqa: E402
from apex.options_pilot.clock import Clock, to_utc_string  # noqa: E402
from apex.options_pilot.exit_policy import EXIT_POLICY_V1  # noqa: E402
from apex.options_pilot.fees import ROBINHOOD_RHF_2026 as FEES  # noqa: E402
from apex.options_pilot.risk_authority import CertifiedRiskAuthority  # noqa: E402
from apex.options_pilot.runtime_identity import runtime_identity  # noqa: E402
from apex.options_pilot import accounting as ACC  # noqa: E402
from apex.options_pilot import instant as I  # noqa: E402
from apex.options_pilot import lifecycle as LC  # noqa: E402
from apex.options_pilot import replay as RP  # noqa: E402
from apex.options_pilot import run_dir as RD  # noqa: E402
from apex.pulse_options import sources as SRC  # noqa: E402

D, PRIOR, BASE = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
RUN_ID = sys.argv[4] if len(sys.argv) > 4 else "loop_demonstration"
HOLD_S = 900.0
CADENCE = 15                                    # every 15th one-minute snapshot = the pilot's 15-minute cadence

chains, nbbo, sbars = [], [], {}
for line in open(D / "chain_SPY.jsonl"):
    r = json.loads(line)
    if r.get("kind") == "pilot_collection_chain":
        chains.append((r["receipt_epoch"], r["payload"]))
for line in open(D / "nbbo_SPY.jsonl"):
    r = json.loads(line)
    if r.get("kind") == "pilot_collection_nbbo":
        nbbo.append((r["payload"]["as_of"], r["payload"]))
for line in open(D / "bars_SPY.jsonl"):
    r = json.loads(line)
    if r.get("kind") == "pilot_collection_bars":
        for b in r["payload"]:
            p = sbars.get(b["event_time"])
            if p is None or b["receipt_time"] < p["receipt_time"]:
                sbars[b["event_time"]] = b
chains.sort(); nbbo.sort()
ALLBARS = sorted(list(json.loads(PRIOR.read_text())) + list(sbars.values()), key=lambda b: b["event_time"])
SCANS = list(range(0, len(chains), CADENCE))


class Rec:
    """Recorded data + clock adapters. Nothing interpolated; nothing after `now` is visible.

    `t` is READ-ONLY and comes from the lifecycle clock. The 2026-09-12 driver assigned to it directly, which is how
    it rewound time; assignment is refused here."""
    provider = "ALPACA_DATA_V2"

    def __init__(self, now_fn=None):
        self._now = now_fn or (lambda: chains[0][0])

    @property
    def t(self) -> float:
        return self._now()

    def bars(self, symbol, *, start_epoch, end_epoch):
        return [{"symbol": symbol, "event_time": b["event_time"], "available_time": b.get("receipt_time", b["event_time"] + 60.0),
                 "receipt_time": b.get("receipt_time", b["event_time"] + 60.0), "open": b["open"], "high": b["high"],
                 "low": b["low"], "close": b["close"], "volume": b.get("volume", 0), "publication_time": b.get("publication_time"),
                 "vwap": b.get("vwap"), "trades": b.get("trades"), "provider": "ALPACA_DATA_V2"}
                for b in ALLBARS if start_epoch <= b["event_time"] < end_epoch and b.get("receipt_time", b["event_time"] + 60.0) <= self.t]

    def _snap(self):
        p = [(ts, pl) for ts, pl in chains if ts <= self.t]
        return p[-1] if p else None

    def chain_fn(self, symbol, as_of):
        s = self._snap()
        if s is None:
            from apex.pulse_options.providers import ProviderUnavailable
            raise ProviderUnavailable("NO_RECORDED_CHAIN_SNAPSHOT")
        ts, pl = s
        return SRC.live_chain_rows([{**q, "expiration": q.get("expiration", pl["expiration"]), "symbol": symbol} for q in pl["quotes"]],
                                   symbol=symbol, receipt_time=ts)

    def quote_fn(self, contract):
        rows = self.chain_fn(contract["symbol"], self.t)
        want = (contract["expiration"], float(contract["strike"]), contract["right"])
        for r in rows:
            if (r["expiration"], r["strike"], r["right"]) == want:
                return r
        from apex.pulse_options.providers import ProviderUnavailable
        raise ProviderUnavailable("QUOTE_NOT_IN_RECORDED_SNAPSHOT: %s at %s" % (want, to_utc_string(self.t)))

    def nbbo_fn(self, symbol, t):
        p = [x for ts, x in nbbo if ts <= self.t]
        if not p:
            return None
        q = p[-1]
        return {"bid": q["bid"], "ask": q["ask"], "bid_size": q["bid_size"], "ask_size": q["ask_size"], "t": q["as_of"], "source": q["source"]}


def model_identity(twin, policy, engine):
    """The model actually used at each stage, or UNAVAILABLE with a reason. Never a silent placeholder."""
    art = twin.artifact
    fit = (engine.fit_info or {}) if engine is not None else {}
    ident = {
        "signal": {"model": SRC.DIRECTION_RULE, "kind": "HEURISTIC_PLACEHOLDER",
                   "status": "PLACEHOLDER_NOT_A_SIGNAL (SIGNAL_STATUS_001.md)"},
        "forecast": {"model": getattr(art, "model_id", None) or "EXP002_L", "validation": "NOT_VALIDATED: INVALID_NULL_CONTROL",
                     "drives_selection": False},
        "variance": ({"model": fit.get("model") or "GARCH-t/EWMA (decision_wb)", "status": fit.get("status"),
                      "why": fit.get("why")} if policy == "FULL_FUNNEL_V1"
                     else {"model": None, "status": "UNAVAILABLE", "why": "the rule path runs no variance model by design"}),
        "regime": ({"model": "CAUSAL_REGIME_FILTER_V1", "status": "RAN" if fit.get("status") == "READY" else "NOT_REACHED"}
                   if policy == "FULL_FUNNEL_V1"
                   else {"model": None, "status": "UNAVAILABLE", "why": "the rule path runs no regime model by design"}),
        "simulation": ({"model": "ConditionalSimulator", "paths": getattr(engine, "n_paths", None)} if policy == "FULL_FUNNEL_V1"
                       else {"model": None, "status": "UNAVAILABLE", "why": "the rule path consults no simulator by design"}),
        "ranking": ({"model": FUNNEL_RULE_ID[:60]} if policy == "FULL_FUNNEL_V1"
                    else {"model": ER.RULE_ID_V2[:60], "kind": "DETERMINISTIC_RULE"}),
        "joint_engine": {"model": "JOINT_FUNNEL_V1 (R4)", "status": "UNAVAILABLE",
                         "why": "no authorized R4 fit (R4-FIT-001/002 not granted); the constructor refuses without one"},
        "risk": {"certificate": "RISK_CERTIFICATE_V0", "kernel": "ORGANISM_PAPER_V1", "envelope": "RISK_ENVELOPE_V1",
                 "fees": FEES.identity()},
        "exit": {"policy": EXIT_POLICY_V1.policy_id, "hash": EXIT_POLICY_V1.policy_hash},
    }
    return ident


def run_policy(policy: str, rd) -> dict:
    """One policy, driven by the SHARED LIFECYCLE SCHEDULER over the recorded timeline. Time moves forward only; each
    exit is serviced at its own deadline; every due obligation precedes new risk at the same instant."""
    lclock = LC.MonotonicClock(chains[0][0])
    rec = Rec(lclock.now)                     # the recorded adapter READS the lifecycle clock; it cannot move it
    clock = lclock.clock()
    engine = FunnelEngine() if policy == "FULL_FUNNEL_V1" else None
    twin = SRC.TwinSources(provenance="LIVE_FEED", clock=clock, bar_source=rec, chain_fn=rec.chain_fn, quote_fn=rec.quote_fn,
                           exit_quote_fn=rec.quote_fn, fee_schedule=FEES, sleep_fn=lclock.sleep, book_fn=rec.nbbo_fn,
                           selection_policy=("PILOT_RULE_V2" if policy in ("WAIT", "PILOT_RULE_V2") else policy),
                           funnel_engine=engine)
    # RUN-SCOPED and COLLISION-REFUSED: a ledger name is claimed once and no previous artifact is ever removed.
    led = rd.path_for("REPLAY_QUARANTINED_%s.jsonl" % policy)
    # THE HONEST ROUTE: recorded data is RECORDED_REPLAY, never LIVE_FEED, and its records are sealed ineligible for
    # live authorization, promotion and prospective-results aggregation.
    bd = RP.replay_boundary(led, clock=clock,
                            risk_authority=CertifiedRiskAuthority(fee_schedule=FEES, provenance="RECORDED_REPLAY"),
                            session_id="LOOP-%s" % policy, release="LOOP_DEMO_NOT_A_RELEASE", fee_schedule=FEES,
                            authorization=AUTHORIZATION)
    bd.runtime_identity = runtime_identity()
    src = twin.sources(); src.pop("exit_quote_fn", None)
    out = {"policy": policy, "ledger": str(led), "scans": [], "model_identity": model_identity(twin, policy, engine),
           "route": "RECORDED_REPLAY", "labels": bd.labels}
    if policy == "WAIT":
        # the null policy never reaches the boundary; it is recorded here as the floor every other policy must clear
        S.open_session(bd, symbols=["SPY"])
        for n, i in enumerate(SCANS, start=1):
            out["scans"].append({"scan": n, "t_utc": to_utc_string(chains[i][0]), "decision": "WAIT", "stage": "POLICY",
                                 "why": "POLICY_WAIT: this policy never trades; it is the null"})
        S.close_session(bd)
        out["lifecycle"] = {"note": "no scheduler events: the null policy admits no risk and creates no obligation"}
    else:
        runner = LC.LifecycleRunner(boundary=bd, sources=src, clock=lclock, symbols=["SPY"],
                                    selection_policy=twin.selection_policy,
                                    scan_epochs=[chains[i][0] for i in SCANS])
        lrep = runner.run()
        out["lifecycle"] = {k: lrep[k] for k in ("ordering_policy", "n_events", "final_clock_utc", "clock_advances",
                                                 "completion", "outstanding_obligations")}
        out["event_stream"] = LC.event_trace(lrep)
        out["exit_entries"] = lrep["exit_entries"]
        rows_now = L.read_all(led)
        for n, d in enumerate(lrep["decisions"], start=1):
            row = {"scan": n, "t_utc": d.get("at_utc"), "decision": d["decision"], "why": (d.get("why") or "")[:220],
                   "intent_id": d.get("intent_id"), "fill_id": d.get("fill_id")}
            it = next((r for r in rows_now if r["kind"] == "pilot_intent" and r.get("intent_id") == d.get("intent_id")), None)
            if it:
                row["chose"] = it["contract_id"]
                row["entry_ask"] = it.get("reference_ask")
                row["expected_toll"] = (it.get("expected_toll") or {}).get("value")
                row["strike_selection"] = {k: (it.get("strike_selection") or {}).get(k)
                                           for k in ("rule", "strike", "distance_pct", "strikes_from_atm")}
            fn = next((r for r in rows_now if r["kind"] == "pilot_funnel" and r.get("scan_id", "").endswith(":%04d:SPY" % n)), None)
            if fn:
                tr = fn.get("trace") or {}
                cands = tr.get("candidates") or {}
                row["funnel"] = {"fit": ((tr.get("variance") or {}).get("status") or (engine.fit_info or {}).get("status")),
                                 "n_candidates": len(cands.get("table") or []),
                                 "n_eligible": sum(1 for t in (cands.get("table") or []) if t.get("status") == "ELIGIBLE"),
                                 "prime": ((tr.get("prime") or {}).get("decision")),
                                 "fees_assumption": (tr.get("fees") or {}).get("assumption")}
            out["scans"].append(row)
    book = bd.book()
    closed = book.closed
    rows_all = L.read_all(led)
    out["book"] = {"closed": len(closed), "open": len(book.positions), "integrity_problems": book.summary()["integrity_problems"],
                   "session_realized_pnl": book.session_realized_pnl,
                   "positions_detail": [{k: p.get(k) for k in ("intent_id", "debit", "credit", "fees_entry", "fees_exit",
                                                               "gross_pnl", "realized_pnl", "net_status")} for p in closed]}
    # PRESERVED UNKNOWN ACCOUNTING. The 2026-09-12 driver summed `p.get("realized_pnl") or 0.0` and reported a net,
    # which turns an unknown into a zero. The aggregate below is null unless it is genuinely complete, and it names
    # every missing input. It is also reconciled against an INDEPENDENT recomputation from the primary ledger fields.
    agg = ACC.net_result(book)
    ACC.assert_no_phantom_zero(agg)
    out["net_result"] = agg
    out["independent_reconciliation"] = ACC.reconcile(book, rows_all, fee_schedules={FEES.schedule_id: FEES})
    c = Counter(r["decision"] for r in out["scans"])
    why = Counter((r.get("why") or "")[:60] for r in out["scans"] if r["decision"] != "TRADE")
    nets = [p["realized_pnl"] for p in closed if p.get("realized_pnl") is not None]
    out["totals"] = {"scans": len(out["scans"]), "by_decision": dict(c), "wait_and_refusal_reasons": dict(why),
                     "trades": c.get("TRADE", 0), "unresolved_exits": len(book.positions),
                     "net_pnl": agg["total_net_pnl"], "net_status": agg["total_net_status"],
                     "known_realized_pnl": agg["known_realized_pnl"], "why_not_estimable": agg["why_not_estimable"],
                     "per_trade_net": (round(sum(nets) / len(nets), 2) if nets else None),
                     "worst": (min(nets) if nets else None), "best": (max(nets) if nets else None),
                     "wins": sum(1 for x in nets if x > 0),
                     "exposure_usd": round(sum(p["debit"] for p in closed + book.positions), 2),
                     "scans_blocked_by_unavailable_stage": sum(1 for r in out["scans"] if "UNAVAILABLE" in (r.get("why") or ""))}
    L.verify_chain(led)
    return out


AUTHORIZATION = RP.ReplayAuthorization(
    reason="LOOP_EVALUATION_CONTRACT.md demonstration over the burned 2026-09-11 SPY session",
    input_digests={k: RD.digest_file(p)["sha256"] for k, p in
                   (("chain", D / "chain_SPY.jsonl"), ("nbbo", D / "nbbo_SPY.jsonl"),
                    ("bars", D / "bars_SPY.jsonl"), ("prior_bars", PRIOR))},
    recorded_window_utc=(to_utc_string(chains[0][0]), to_utc_string(chains[-1][0])),
    operator_note="burned collection; SCOPE_DEVIATION_001.md covers the retained prior-bar file")

RUN = RD.new_run(BASE, run_id=RUN_ID, now_epoch=chains[0][0],
                 inputs={"chain": D / "chain_SPY.jsonl", "nbbo": D / "nbbo_SPY.jsonl", "bars": D / "bars_SPY.jsonl",
                         "prior_bars": PRIOR},
                 config={"policies": ["WAIT", "PILOT_RULE_V2", "FULL_FUNNEL_V1"], "cadence_snapshots": CADENCE,
                         "hold_s": HOLD_S, "route": "RECORDED_REPLAY", "limits": "UNCHANGED"},
                 note="loop demonstration; recorded-replay route; no provider request")

results = {"kind": "LOOP_DEMONSTRATION", "contract": "docs/LOOP_EVALUATION_CONTRACT.md", "run_id": RUN_ID,
           "run_dir": str(RUN.path),
           "data": "burned 2026-09-11 SPY collection + retained prior bars (SCOPE_DEVIATION_001.md); no provider request",
           "evidence_route": "RECORDED_REPLAY: HISTORICAL_DEVELOPMENT_REPLAY / NONE_REPLAY; excluded from live "
                             "authorization, promotion and prospective-results aggregation",
           "quarantined": "REPLAY; ledgers never merged", "scan_instants": [to_utc_string(chains[i][0]) for i in SCANS],
           "ordering_policy": LC.ORDERING_POLICY, "timestamp_rule": I.CONVERSION_RULE, "policies": {}}
try:
    for pol in ("WAIT", "PILOT_RULE_V2", "FULL_FUNNEL_V1"):
        results["policies"][pol] = run_policy(pol, RUN)
except BaseException as _e:                                                    # noqa: BLE001
    RUN.failed(now_epoch=chains[0][0], error=_e)                               # partial artifacts are PRESERVED
    raise

# head to head on identical instants
hh = []
for n in range(len(SCANS)):
    row = {"scan": n + 1, "t_utc": results["policies"]["WAIT"]["scans"][n]["t_utc"]}
    for pol in ("WAIT", "PILOT_RULE_V2", "FULL_FUNNEL_V1"):
        s = results["policies"][pol]["scans"][n]
        row[pol] = {"decision": s["decision"], "chose": s.get("chose"), "why": (s.get("why") or "")[:70]}
    row["agree"] = len({row[p]["decision"] for p in ("PILOT_RULE_V2", "FULL_FUNNEL_V1")}) == 1
    row["same_contract"] = (row["PILOT_RULE_V2"].get("chose") == row["FULL_FUNNEL_V1"].get("chose"))
    hh.append(row)
results["head_to_head"] = hh
results["summary"] = {p: results["policies"][p]["totals"] for p in results["policies"]}
RUN.write_json("loop_demonstration.json", results)
RUN.complete(now_epoch=chains[-1][0], summary=results["summary"])
print(json.dumps({"run_dir": str(RUN.path), "summary": results["summary"]}, indent=1, default=str))
