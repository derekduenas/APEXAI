"""COMPLETE LOOP DEMONSTRATION under docs/LOOP_EVALUATION_CONTRACT.md (frozen before this ran).

    python scripts/loop_demonstration.py <collection_dir> <prior_bars.json> <out_dir>

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
from apex.pulse_options import sources as SRC  # noqa: E402

D, PRIOR, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
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
    """Recorded data + clock adapters. Nothing interpolated; nothing after `now` is visible."""
    provider = "ALPACA_DATA_V2"

    def __init__(self):
        self.t = chains[0][0]

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


def run_policy(policy: str) -> dict:
    rec = Rec()
    clock = Clock(lambda: rec.t)
    engine = FunnelEngine() if policy == "FULL_FUNNEL_V1" else None
    twin = SRC.TwinSources(provenance="LIVE_FEED", clock=clock, bar_source=rec, chain_fn=rec.chain_fn, quote_fn=rec.quote_fn,
                           exit_quote_fn=rec.quote_fn, fee_schedule=FEES, sleep_fn=lambda s: None, book_fn=rec.nbbo_fn,
                           selection_policy=("PILOT_RULE_V2" if policy in ("WAIT", "PILOT_RULE_V2") else policy),
                           funnel_engine=engine)
    led = OUT / ("REPLAY_QUARANTINED_%s.jsonl" % policy)
    if led.exists():
        led.unlink()
    bd = B.Boundary(led, clock=clock, provenance="LIVE_FEED",
                    risk_authority=CertifiedRiskAuthority(fee_schedule=FEES, provenance="LIVE_FEED"),
                    session_id="LOOP-%s" % policy, release="LOOP_DEMO_NOT_A_RELEASE", fee_schedule=FEES)
    bd.runtime_identity = runtime_identity()
    S.open_session(bd, symbols=["SPY"])
    src = twin.sources(); src.pop("exit_quote_fn", None)
    out = {"policy": policy, "ledger": str(led), "scans": [], "model_identity": model_identity(twin, policy, engine)}
    fills = []
    for n, i in enumerate(SCANS, start=1):
        rec.t = chains[i][0]
        row = {"scan": n, "t_utc": to_utc_string(rec.t)}
        if policy == "WAIT":
            row.update(decision="WAIT", why="POLICY_WAIT: this policy never trades; it is the null", stage="POLICY")
            out["scans"].append(row); continue
        try:
            d = S.scan(bd, symbol="SPY", seq=n, **src)
        except Exception as e:                                            # noqa: BLE001
            row.update(decision="ERROR", why="%s: %s" % (type(e).__name__, str(e)[:180])); out["scans"].append(row); continue
        row.update(decision=d["decision"], why=(d.get("why") or "")[:220], intent_id=d.get("intent_id"), fill_id=d.get("fill_id"))
        rows_now = L.read_all(led)
        it = next((r for r in rows_now if r["kind"] == "pilot_intent" and r.get("intent_id") == d.get("intent_id")), None)
        if it:
            row["chose"] = it["contract_id"]
            row["entry_ask"] = it.get("reference_ask")
            row["expected_toll"] = (it.get("expected_toll") or {}).get("value")
            row["strike_selection"] = {k: (it.get("strike_selection") or {}).get(k) for k in ("rule", "strike", "distance_pct", "strikes_from_atm")}
        fn = next((r for r in rows_now if r["kind"] == "pilot_funnel" and r.get("scan_id", "").endswith(":%04d:SPY" % n)), None)
        if fn:
            tr = fn.get("trace") or {}
            cands = tr.get("candidates") or {}
            row["funnel"] = {"fit": ((tr.get("variance") or {}).get("status") or (engine.fit_info or {}).get("status")),
                             "n_candidates": len(cands.get("table") or []),
                             "n_eligible": sum(1 for t in (cands.get("table") or []) if t.get("status") == "ELIGIBLE"),
                             "prime": ((tr.get("prime") or {}).get("decision")),
                             "fees_assumption": (tr.get("fees") or {}).get("assumption")}
        if d["decision"] == "TRADE" and d.get("receipts", {}).get("fill"):
            fills.append((rec.t, d["receipts"]["fill"]))
        out["scans"].append(row)
    # exits: at each fill's own due instant, against the ACTUAL recorded quote
    exits = []
    for t0, fr in fills:
        rec.t = t0 + HOLD_S
        for attempt in range(EXIT_POLICY_V1.max_attempts):
            res = S.attempt_exits(bd, exit_quote_fn=twin._exit_quote_fn, sleep_fn=lambda s: None, wait_for_due=False,
                                  positions=None)
            exits.append({"at": to_utc_string(rec.t), "result": res})
            if any(x.get("final") in ("RESOLVED", "DISCHARGED") for x in res) or not res:
                break
            rec.t += 15.0
    book = bd.book()
    closed = book.closed
    net = [p["realized_pnl"] for p in closed if p.get("realized_pnl") is not None]
    out["exits"] = exits
    out["book"] = {"closed": len(closed), "open": len(book.positions), "integrity_problems": book.summary()["integrity_problems"],
                   "session_realized_pnl": book.session_realized_pnl,
                   "positions_detail": [{k: p.get(k) for k in ("intent_id", "debit", "credit", "fees_entry", "fees_exit",
                                                               "gross_pnl", "realized_pnl", "net_status")} for p in closed]}
    c = Counter(r["decision"] for r in out["scans"])
    why = Counter((r.get("why") or "")[:60] for r in out["scans"] if r["decision"] != "TRADE")
    out["totals"] = {"scans": len(out["scans"]), "by_decision": dict(c), "wait_and_refusal_reasons": dict(why),
                     "trades": c.get("TRADE", 0), "unresolved_exits": len(book.positions),
                     "gross_pnl": round(sum((p.get("gross_pnl") or 0.0) for p in closed), 2),
                     "fees": round(sum((p.get("fees_entry") or 0.0) + (p.get("fees_exit") or 0.0) for p in closed), 4),
                     "net_pnl": (round(sum(net), 2) if net else 0.0),
                     "per_trade_net": (round(sum(net) / len(net), 2) if net else None),
                     "worst": (min(net) if net else None), "best": (max(net) if net else None),
                     "wins": sum(1 for x in net if x > 0),
                     "exposure_usd": round(sum((p.get("debit") or 0.0) for p in closed), 2),
                     "scans_blocked_by_unavailable_stage": sum(1 for r in out["scans"] if "UNAVAILABLE" in (r.get("why") or ""))}
    L.verify_chain(led)
    return out


results = {"kind": "LOOP_DEMONSTRATION", "contract": "docs/LOOP_EVALUATION_CONTRACT.md",
           "data": "burned 2026-09-11 SPY collection + retained prior bars (SCOPE_DEVIATION_001.md); no provider request",
           "quarantined": "REPLAY; ledgers never merged", "scan_instants": [to_utc_string(chains[i][0]) for i in SCANS],
           "policies": {}}
for pol in ("WAIT", "PILOT_RULE_V2", "FULL_FUNNEL_V1"):
    results["policies"][pol] = run_policy(pol)

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
(OUT / "loop_demonstration.json").write_text(json.dumps(results, indent=1, default=str) + "\n")
print(json.dumps(results["summary"], indent=1, default=str))
