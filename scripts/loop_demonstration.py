"""COMPLETE LOOP DEMONSTRATION under docs/LOOP_EVALUATION_CONTRACT.md (frozen before the 2026-09-12 run).

    python scripts/loop_demonstration.py <collection_dir> <prior_bars.json> <out_base_dir> [run_id] [manifest.json]

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
import time
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
from apex.options_pilot import provenance as PROV  # noqa: E402
from apex.pulse_options import sources as SRC  # noqa: E402


D, PRIOR, BASE = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
RUN_ID = sys.argv[4] if len(sys.argv) > 4 else "loop_demonstration"
if len(sys.argv) <= 5:
    raise SystemExit("MANIFEST_REQUIRED: FLOW-VALIDATION-001 runs only against an independently pinned manifest. "
                     "Produce one with scripts/preserve_inputs.py and pass it as the fifth argument. A digest this "
                     "process computes from the same file it reads is not an independent declaration.")
MANIFEST = Path(sys.argv[5])
AUTHZ = Path(sys.argv[6]) if len(sys.argv) > 6 else None    # operator-authored; never written by this repository
HOLD_S = 900.0
CADENCE = 15                                    # every 15th one-minute snapshot = the pilot's 15-minute cadence
FIT_BUDGET = 3                                  # see docs/FLOW_VALIDATION_001_FIT_CONTRACT.md: one fit() call, at
                                                # most GARCH + regime + the conditional EWMA fallback. 400 is the
                                                # constructor default and has nothing to do with this run.

INPUT_PATHS = {"chain": D / "chain_SPY.jsonl", "nbbo": D / "nbbo_SPY.jsonl",
               "bars": D / "bars_SPY.jsonl", "prior_bars": PRIOR}

# ---------------------------------------------------------------- 1. CLAIM THE RUN DIRECTORY BEFORE OPENING ANYTHING
# Including the manifest. A missing or malformed manifest is a validation failure like any other, and a validation
# failure must leave a record; claiming the directory after reading it would lose exactly those cases.
RUN = RD.new_run(BASE, run_id=RUN_ID, now_epoch=time.time(),
                 config={"policies": ["WAIT", "PILOT_RULE_V2", "FULL_FUNNEL_V1"], "cadence_snapshots": CADENCE,
                         "hold_s": HOLD_S, "route": "RECORDED_REPLAY", "limits": "UNCHANGED",
                         "fit_budget": FIT_BUDGET, "manifest_path": str(MANIFEST),
                         "authorization_path": (str(AUTHZ) if AUTHZ else None)},
                 note="loop demonstration; recorded-replay route; manifest-pinned; no provider request")

def _capture(path):
    """Read a document ONCE and keep its bytes and their digest. Everything downstream uses the capture, so no
    later read can disagree with what was recorded."""
    blob = Path(path).read_bytes()
    return {"path": str(path), "bytes": len(blob), "sha256": RD.digest_obj_bytes(blob), "raw": blob,
            "parsed": json.loads(blob.decode())}


try:
    # ------------------------------------------------------------ 2. CAPTURE THE MANIFEST ONCE
    MANIFEST_CAPTURE = _capture(MANIFEST)
    _m = MANIFEST_CAPTURE["parsed"]
    _declared = {k: (v["sha256"] if isinstance(v, dict) else v) for k, v in (_m.get("inputs") or _m).items()}
    if not _declared:
        raise SystemExit("MANIFEST_EMPTY: %s declares no inputs" % MANIFEST)
    DECLARATION_SOURCE = "INDEPENDENT_MANIFEST: %s (sha256 %s)" % (MANIFEST, MANIFEST_CAPTURE["sha256"][:16])

    # ------------------------------------------------------------ 3. CAPTURE THE OPERATOR AUTHORIZATION ONCE
    AUTHZ_CAPTURE = _capture(AUTHZ) if AUTHZ is not None else None
    AUTHZ_DOC = AUTHZ_CAPTURE["parsed"] if AUTHZ_CAPTURE else None

    # ------------------------------------------------------------ 4. READ THE INPUT BYTES ONCE
    # THE SAME BYTES ARE HASHED AND PARSED. Hashing one read and parsing another cannot establish that the parsed
    # content is what the manifest names: a file replaced between the two operations would pass and then be used.
    RAW = {label: p.read_bytes() for label, p in INPUT_PATHS.items()}

    # ------------------------------------------------------------ 5. VERIFY BEFORE PARSING, BEFORE ANY MODEL EXISTS
    AUTHORIZATION = RP.ReplayAuthorization(
        reason="FLOW-VALIDATION-001 complete-flow diagnostic over the burned 2026-09-11 SPY session",
        input_digests=_declared,
        recorded_window_utc=("SET_AFTER_PARSE", "SET_AFTER_PARSE"),
        operator_note="burned collection; SCOPE_DEVIATION_001.md covers the retained prior-bar file")
    AUTHORIZATION.verify_bytes(RAW)

    # ------------------------------------------------------------ 4. PARSE THOSE BYTES, and only now
    chains, nbbo, sbars = [], [], {}
    bars_without_receipt = 0
    for line in RAW["chain"].decode().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") == "pilot_collection_chain":
            chains.append((r["receipt_epoch"], r["payload"]))          # RECEIPT, the instant APEX received it
    for line in RAW["nbbo"].decode().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") == "pilot_collection_nbbo":
            # AVAILABILITY IS THE RECEIPT, NOT as_of. `as_of` is the quote's own event time; a quote that existed at
            # 13:45 but reached this process at 13:46 is invisible at 13:45:30. The event time is retained beside it.
            nbbo.append((r["receipt_epoch"], {**r["payload"], "event_as_of": r["payload"].get("as_of"),
                                              "received_epoch": r["receipt_epoch"]}))
    for line in RAW["bars"].decode().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") == "pilot_collection_bars":
            for b in r["payload"]:
                # NO INVENTED RECEIPT. A bar with no recorded receipt has unknown availability and is EXCLUDED.
                if not isinstance(b.get("receipt_time"), (int, float)) or isinstance(b.get("receipt_time"), bool):
                    bars_without_receipt += 1
                    continue
                p = sbars.get(b["event_time"])
                if p is None or b["receipt_time"] < p["receipt_time"]:
                    sbars[b["event_time"]] = b
    chains.sort(); nbbo.sort()
    if not chains:
        raise SystemExit("NO_CHAIN_SNAPSHOTS: the collection carries no pilot_collection_chain records")

    PRIOR_BARS = json.loads(RAW["prior_bars"].decode())

    # ---- PROVENANCE: assignment-path evidence and artifact attribution, reported apart and never merged
    SESSION_PROV = PROV.classify("session_bars", list(sbars.values()), assignment_key="alpaca_bar_receipt",
                                 availability_basis=PROV.PER_RECORD_RECORDED,
                                 acquisition_note="presented as written by scripts/options_pilot_collector.py")
    PRIOR_PROV = PROV.classify("prior_bars", PRIOR_BARS, assignment_key=None,
                               availability_basis=PROV.DERIVED_BY_FORMULA,
                               acquisition_note=("bulk historical pull on 2026-09-12; no assigning path is named "
                                                 "(SCOPE_DEVIATION_001.md)"))

    # ---- the acceptance document must name THIS evaluation, THIS manifest and THIS code pin, then accept the
    #      assumption in its exact declared words. Refused before any adapter or model exists.
    ACCEPTANCE = PROV.validate_acceptance(AUTHZ_DOC, evaluation_id="FLOW-VALIDATION-001",
                                          manifest_sha256=MANIFEST_CAPTURE["sha256"],
                                          code_pin=RD.code_pin().get("commit"))
    ASSUMPTION_BINDING = PROV.require_accepted("BULK_PULL_AVAILABILITY_V1", AUTHZ_DOC)

    # ---- COMPUTE the accepted formula. The source receipt is preserved; a row that disagrees refuses the run.
    ASSUMED = PROV.apply_bulk_pull_availability(PRIOR_BARS)
    PRIOR_BARS = ASSUMED["rows"]

    # every bar carries ONE explicit availability field, and says where that value came from
    prior_kept = [{**b, "available_time": b[PROV.ASSUMED_FIELD]} for b in PRIOR_BARS]
    session_kept = [{**b, "available_time": b["receipt_time"], "availability_basis": PROV.PER_RECORD_RECORDED}
                    for b in sbars.values()]
    ALLBARS = sorted(prior_kept + session_kept, key=lambda b: b["event_time"])
    SCANS = list(range(0, len(chains), CADENCE))
    AUTHORIZATION.window = (to_utc_string(chains[0][0]), to_utc_string(chains[-1][0]))
    INPUT_REPORT = {"bars_excluded_no_recorded_receipt": bars_without_receipt,
                    "prior_bars_total": len(PRIOR_BARS), "prior_bars_kept": len(prior_kept),
                    "session_bars_provenance": SESSION_PROV, "prior_bars_provenance": PRIOR_PROV,
                    "accepted_assumption": ASSUMPTION_BINDING, "acceptance": ACCEPTANCE,
                    "assumed_availability": {k: ASSUMED[k] for k in ("assumption_id", "offset_s", "n_rows",
                                                                     "derived_field", "source_field_preserved",
                                                                     "checked")},
                    "manifest_capture": {k: MANIFEST_CAPTURE[k] for k in ("path", "bytes", "sha256")},
                    "authorization_capture": ({k: AUTHZ_CAPTURE[k] for k in ("path", "bytes", "sha256")}
                                              if AUTHZ_CAPTURE else None)}
except BaseException as _e:                                                    # noqa: BLE001
    RUN.failed(now_epoch=time.time(), error=_e,
               summary={"stage": "INPUT_VALIDATION", "note": "refused before any adapter or model was constructed"})
    raise


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
        # NO DEFAULT RECEIPT. Bars without a recorded receipt were excluded at parse time, so `b["receipt_time"]` is
        # present by construction; reaching for a default here would silently backdate an unknown availability.
        return [{"symbol": symbol, "event_time": b["event_time"], "available_time": b["available_time"],
                 "receipt_time": b["available_time"], "availability_basis": b.get("availability_basis"),
                 "source_receipt_time": b.get(PROV.SOURCE_FIELD, b.get("receipt_time")),
                 "open": b["open"], "high": b["high"],
                 "low": b["low"], "close": b["close"], "volume": b.get("volume", 0), "publication_time": b.get("publication_time"),
                 "vwap": b.get("vwap"), "trades": b.get("trades"), "provider": "ALPACA_DATA_V2"}
                for b in ALLBARS if start_epoch <= b["event_time"] < end_epoch and b["available_time"] <= self.t]

    def _snap(self):
        return RP.most_recent_available(chains, self.t)          # THE ONE GATE: recorded receipt, never nearest-time

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
        got = RP.most_recent_available(nbbo, self.t)             # gated on the RECORD'S RECEIPT, not on `as_of`
        if got is None:
            return None
        q = got[1]
        # `t` stays the quote's own event time, which is what a consumer means by "when was this true"; visibility
        # was decided by the receipt above, which is what "when could we know it" means. The two are different.
        return {"bid": q["bid"], "ask": q["ask"], "bid_size": q["bid_size"], "ask_size": q["ask_size"],
                "t": q.get("event_as_of", q.get("as_of")), "received_epoch": q.get("received_epoch"),
                "source": q["source"]}


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
    engine = FunnelEngine(fit_budget=FIT_BUDGET) if policy == "FULL_FUNNEL_V1" else None
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
    # The LifecycleRunner needs exit_quote_fn to service exits; it never forwards it to S.scan, which names the
    # scan sources explicitly. The old driver popped it here because it called S.scan(**src) directly. Popping it
    # under the scheduler crashed the FIRST exit with KeyError: 'exit_quote_fn' -- found by the synthetic exercise
    # in tests/test_flow_validation_readiness.py, which is why that exercise exists.
    src = twin.sources()
    out = {"policy": policy, "ledger": str(led), "scans": [], "route": "RECORDED_REPLAY", "labels": bd.labels,
           # model_identity is filled in AFTER the run. Computed here it would report the engine's fit state before
           # anything was fitted, and would contradict the per-scan pilot_funnel records -- which stay authoritative.
           "model_identity_at_start": model_identity(twin, policy, engine)}
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
    out["model_identity"] = model_identity(twin, policy, engine)     # after the run: what was ACTUALLY used
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


INPUT_PATHS = {"chain": D / "chain_SPY.jsonl", "nbbo": D / "nbbo_SPY.jsonl",
               "bars": D / "bars_SPY.jsonl", "prior_bars": PRIOR}

results = {"kind": "LOOP_DEMONSTRATION", "contract": "docs/LOOP_EVALUATION_CONTRACT.md", "run_id": RUN_ID,
           "run_dir": str(RUN.path),
           "data": "burned 2026-09-11 SPY collection + retained prior bars (SCOPE_DEVIATION_001.md); no provider request",
           "evidence_route": "RECORDED_REPLAY: HISTORICAL_DEVELOPMENT_REPLAY / NONE_REPLAY; excluded from live "
                             "authorization, promotion and prospective-results aggregation",
           "quarantined": "REPLAY; ledgers never merged", "scan_instants": [to_utc_string(chains[i][0]) for i in SCANS],
           "ordering_policy": LC.ORDERING_POLICY, "timestamp_rule": I.CONVERSION_RULE,
           "replay_authorization": AUTHORIZATION.describe(), "declaration_source": DECLARATION_SOURCE,
           "input_report": INPUT_REPORT, "fit_budget": FIT_BUDGET,
           "accepted_assumptions": ([INPUT_REPORT["accepted_assumption"]] if INPUT_REPORT.get("accepted_assumption")
                                    else []),
           "availability_policy": ("every input family is gated on its RECORDED receipt: chain and NBBO on the "
                                   "record's receipt_epoch, session bars on the bar's own receipt_time. A datum with "
                                   "no recorded receipt is EXCLUDED, never backdated. The prior-bar artifact's "
                                   "availability class is reported under input_report and governs what this run may "
                                   "claim."),
           "policies": {}}
try:
    for pol in ("WAIT", "PILOT_RULE_V2", "FULL_FUNNEL_V1"):
        results["policies"][pol] = run_policy(pol, RUN)
except BaseException as _e:                                                    # noqa: BLE001
    RUN.failed(now_epoch=time.time(), error=_e)                                # partial artifacts are PRESERVED
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
RUN.complete(now_epoch=time.time(), summary={**results["summary"], "input_report": INPUT_REPORT})
print(json.dumps({"run_dir": str(RUN.path), "summary": results["summary"]}, indent=1, default=str))
