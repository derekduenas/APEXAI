"""EQUITY SHADOW FIELD — predator-evidence instrumentation, V1.

    Increase evidence throughput by increasing independent opportunity
    exposure -- NEVER by lowering standards.

Runs the EXACT frozen incumbent hunter (day_trader.decide, unmodified,
same thresholds, same cadence, same 1R semantics) across a broad,
sector-diverse, predeclared universe, and outcome-resolves EVERYTHING
-- attacks AND refusals -- so the organism can finally distinguish
"bad hunter" from "good hunter + selective allocator".

TWO ECONOMIC VIEWS, never pooled (operator law):
    CANONICAL PAPER BOOK        "does the ORGANISM make money?"
    THIS FIELD OUTCOME TAPE     "does this PREDATOR find edge?"

The field has NO capital surface: nothing here emits to the organism
outbox, imports the arena, or touches the book. A field candidate is
evidence about the hunter, not a funding request.

COUNTERFACTUALS ARE SEALED PROSPECTIVELY: a refusal's hypothetical
expression (entry, stop, size, friction) is computed AT DECISION TIME
from the frozen sizer on the sealed geometry -- never reconstructed
after the outcome is known. The question is never "would ignoring the
rule have paid?"; it is "what distribution follows this refusal class,
prospectively?"

decision_power: PREDATOR_EVIDENCE_ONLY.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from apex.governance.chain_ledger import chain_append  # noqa: E402
from apex.ops.heartbeat import Heartbeat  # noqa: E402
from apex.ops.orchestrator import session_bounds  # noqa: E402
from apex.ops.timebase import ET  # noqa: E402
from apex.predators.equities import day_trader  # noqa: E402
from apex.predators.equities import shadow_resolution  # noqa: E402

from equity_shadow_session import (RTH_CLOSE_UTC, RTH_OPEN_UTC,  # noqa: E402
                                   load_bars, release_sha, rth_only)

SERVICE = "equity-field"
AUTHORITY = "PREDATOR_EVIDENCE_ONLY"
ERA = "EQUITY_FIELD_V1"
FIELD_ROOT = Path("results/equities/field")
UNIVERSE_FILE = FIELD_ROOT / "universe_v1.json"
LEDGER = FIELD_ROOT / "decisions.jsonl"
OUTCOMES = FIELD_ROOT / "outcomes.jsonl"
SCAN_INTERVAL_S = 900          # the incumbent cadence, not a new one

# Predeclared, rules-based, sealed BEFORE any outcome exists.
# Selection rule: approximately the largest-capitalization, most liquid
# plain-symbology US common stocks per GICS sector as of 2026-08-29
# (size/liquidity basis ONLY -- never historical strategy performance),
# plus the incumbent capture set. A name that fails the incumbent
# liquidity floor at evaluation time is sealed into the denominator as
# thin, not silently dropped.
FIELD_UNIVERSE_V1 = {
    "TECH": ("AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "AMD"),
    "COMMUNICATION": ("GOOGL", "META", "NFLX", "DIS"),
    "CONSUMER_DISC": ("AMZN", "TSLA", "HD", "MCD"),
    "FINANCIALS": ("JPM", "V", "MA", "BAC"),
    "HEALTH_CARE": ("LLY", "UNH", "JNJ", "ABBV"),
    "INDUSTRIALS": ("GE", "CAT", "RTX", "UNP"),
    "STAPLES": ("WMT", "PG", "COST", "KO"),
    "ENERGY": ("XOM", "CVX", "COP", "SLB"),
    "UTILITIES": ("NEE", "SO", "DUK", "CEG"),
    "REAL_ESTATE": ("PLD", "AMT", "EQIX", "SPG"),
    "MATERIALS": ("LIN", "SHW", "APD", "FCX"),
}
COUNTERFACTUAL_CLASSES = ("CHASE_REFUSED", "GEOMETRY_REFUSED")


def field_symbols() -> list:
    return sorted({s for syms in FIELD_UNIVERSE_V1.values()
                   for s in syms})


def sector_of(sym: str) -> str:
    for sec, syms in FIELD_UNIVERSE_V1.items():
        if sym in syms:
            return sec
    return "UNKNOWN"


def seal_universe() -> dict:
    """Idempotent: the universe is sealed once, before any outcome."""
    if UNIVERSE_FILE.exists():
        return json.loads(UNIVERSE_FILE.read_text())
    FIELD_ROOT.mkdir(parents=True, exist_ok=True)
    rec = {"kind": "equity_field_universe", "era": ERA,
           "selection_rule": (
               "~4 largest-cap liquid plain-symbology US common stocks "
               "per GICS sector as of 2026-08-29; size/liquidity basis "
               "only, never historical strategy performance; sealed "
               "before any outcome exists; no additions without a new "
               "predeclared era"),
           "sectors": {k: list(v) for k, v in
                       FIELD_UNIVERSE_V1.items()},
           "symbols": field_symbols(),
           "count": len(field_symbols()),
           "trader": "INCUMBENT FROZEN day_trader -- same thesis "
                     "logic, setup families, thresholds, gates, "
                     "geometry, friction model, 1R semantics, "
                     "known_from rules. No tuning whatsoever.",
           "sealed_utc": datetime.now(timezone.utc).isoformat(),
           "law": "evidence throughput rises through exposure, never "
                  "through lowered standards",
           "decision_power": AUTHORITY}
    chain_append(UNIVERSE_FILE, rec)
    return rec


# ------------------------------------------------------------- sweep

def eligible_field(session: str) -> dict:
    """Incumbent liquidity floor over RTH, field symbols only. The
    full denominator is sealed: thin and missing are data, not noise."""
    ok, thin, missing = [], [], []
    for sym in field_symbols():
        bars = rth_only(load_bars(sym, session))
        if len(bars) < day_trader.MIN_BARS:
            missing.append(sym)
            continue
        vols = [b.get("volume", 0) for b in bars]
        mv = st.median(vols) if vols else 0
        (ok if mv >= day_trader.MIN_MEDIAN_VOLUME_PER_MIN
         else thin).append(sym)
    return {"eligible": ok, "thin": thin, "missing": missing,
            "floor_shares_per_min":
            day_trader.MIN_MEDIAN_VOLUME_PER_MIN}


def counterfactual_expression(rec: dict) -> dict | None:
    """The frozen sizer applied to the sealed geometry, AT DECISION
    TIME. Stop reconstruction is exact by construction:
    inval_atr = |close - invalidation| / ATR, so
    stop = close -/+ inval_atr * ATR for LONG/SHORT."""
    state = rec.get("market_state") or {}
    close, atr = state.get("close"), state.get("atr")
    dist = rec.get("invalidation_distance_atr")
    direction = rec.get("direction")
    if not (isinstance(close, (int, float))
            and isinstance(atr, (int, float)) and atr > 0
            and isinstance(dist, (int, float)) and dist > 0
            and direction in ("LONG", "SHORT")):
        return None
    stop = close - dist * atr if direction == "LONG" \
        else close + dist * atr
    fill = day_trader.marketable_fill(close, direction)
    sized = day_trader.size_shadow(entry=fill["fill"], stop=stop,
                                   direction=direction)
    if not sized.get("valid"):
        return None
    return {"entry_fill": fill["fill"], "stop": round(stop, 6),
            "quantity": sized["quantity"],
            "declared_1R": sized["declared_1R"],
            "friction_per_share": fill["friction_per_share"],
            "friction_fraction_of_1R":
            sized["friction_fraction_of_1R"],
            "basis": "FROZEN_SIZER_ON_SEALED_GEOMETRY",
            "sealed_prospectively": True}


def sweep_field(session: str, *, beat=None,
                roots: dict | None = None) -> dict:
    r = roots or {}
    led = r.get("ledger", LEDGER)
    uni = eligible_field(session)
    now = datetime.now(timezone.utc)
    n_dec = n_att = n_cf = 0
    errors = []
    for sym in uni["eligible"]:
        bars = [b for b in load_bars(sym, session)
                if b["event_time_utc"] <= now.isoformat()]
        if not bars:
            continue
        vols = [b.get("volume", 0) for b in rth_only(bars)]
        try:
            d = day_trader.decide(
                symbol=sym, session=session, bars=bars,
                now=bars[-1]["event_time_utc"],
                known_from=bars[-1]["event_time_utc"],
                release_sha=release_sha(),
                median_volume=st.median(vols) if vols else None)
        except Exception as e:                          # noqa: BLE001
            errors.append(f"{sym}: {type(e).__name__}")
            continue
        rec = d.as_record()
        rec["kind"] = "equity_field_decision"
        rec["era"] = ERA
        rec["sector"] = sector_of(sym)
        rec["decision_power"] = AUTHORITY
        if rec.get("decision") in COUNTERFACTUAL_CLASSES:
            cf = counterfactual_expression(rec)
            rec["counterfactual_expression"] = cf or "NOT_ESTIMABLE"
            if cf:
                n_cf += 1
        chain_append(led, rec)
        n_dec += 1
        if rec.get("decision") == "ATTACK_READY_SHADOW":
            n_att += 1
    out = {"kind": "equity_field_sweep", "session": session, "era": ERA,
           "swept_utc": now.isoformat(),
           "eligible": len(uni["eligible"]), "thin": len(uni["thin"]),
           "missing": len(uni["missing"]), "decisions": n_dec,
           "attackable": n_att, "counterfactuals_sealed": n_cf,
           "errors": errors, "decision_power": AUTHORITY}
    if beat is not None:
        beat.work(f"field {n_dec} decisions / {n_att} attackable / "
                  f"{n_cf} counterfactuals", backlog=len(errors))
    return out


# ----------------------------------------------------------- resolve

def _resolvable(rec: dict) -> dict | None:
    """Shape any directional field decision for the incumbent resolver.
    The shim exists only in memory; the SEALED outcome is retagged
    honestly with the original decision class."""
    if rec.get("decision") == "ATTACK_READY_SHADOW":
        return dict(rec)
    cf = rec.get("counterfactual_expression")
    if not isinstance(cf, dict):
        return None
    shaped = {k: rec.get(k) for k in
              ("decision_id", "symbol", "session", "known_from",
               "direction", "invalidation_distance_atr")}
    shaped.update(entry_fill=cf["entry_fill"], stop=cf["stop"],
                  quantity=cf["quantity"],
                  declared_1R=cf["declared_1R"],
                  friction_per_share=cf["friction_per_share"],
                  decision="ATTACK_READY_SHADOW")   # resolver shim only
    return shaped


def resolve_field(session: str, *, roots: dict | None = None) -> dict:
    r = roots or {}
    led, outp = r.get("ledger", LEDGER), r.get("outcomes", OUTCOMES)
    if not Path(led).exists():
        return {"resolved": 0, "why": "no decisions"}
    b = session_bounds(session)
    if not b["trading_day"]:
        return {"resolved": 0, "why": "not a trading day"}
    close = b["close_utc"]
    already = set()
    if Path(outp).exists():
        for line in Path(outp).read_text().splitlines():
            try:
                already.add(json.loads(line).get("decision_id"))
            except (json.JSONDecodeError, AttributeError):
                continue
    resolved = skipped = 0
    denominator: dict[str, int] = {}
    for line in Path(led).read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") != "equity_field_decision" \
                or rec.get("session") != session:
            continue
        dclass = rec.get("decision", "UNKNOWN")
        denominator[dclass] = denominator.get(dclass, 0) + 1
        if rec.get("decision_id") in already:
            continue
        shaped = _resolvable(rec)
        if shaped is None:
            skipped += 1
            continue
        bars = load_bars(rec["symbol"], session)
        out = shadow_resolution.resolve(decision=shaped, bars=bars,
                                        close_utc=close)
        out["kind"] = "equity_field_outcome"
        out["era"] = ERA
        out["original_decision"] = dclass
        out["counterfactual"] = dclass != "ATTACK_READY_SHADOW"
        out["sector"] = rec.get("sector", "UNKNOWN")
        out["setup_type"] = rec.get("setup_type")
        out["direction"] = rec.get("direction")
        out["known_from"] = rec.get("known_from")
        out["decision_power"] = AUTHORITY
        out["law"] = ("counterfactual distribution study, sealed "
                      "prospectively -- never a funding claim; this "
                      "tape answers 'does the predator find edge', "
                      "the canonical book answers 'does the organism "
                      "make money'; the two are never pooled")
        already.add(rec.get("decision_id"))
        chain_append(outp, out)
        resolved += 1
    return {"kind": "equity_field_resolution", "session": session,
            "era": ERA, "resolved": resolved,
            "no_expression_skipped": skipped,
            "denominator_by_class": denominator,
            "decision_power": AUTHORITY}


# ------------------------------------------------------------ report

def report() -> dict:
    """The predator-evidence view. Cohorts by original decision class;
    independence NOT_ESTIMABLE; canonical book untouched and unpooled."""
    cohorts: dict[str, list] = {}
    if OUTCOMES.exists():
        for line in OUTCOMES.read_text().splitlines():
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("kind") == "equity_field_outcome" \
                    and o.get("resolvable"):
                cohorts.setdefault(o["original_decision"], []).append(o)

    def med(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return round(st.median(vals), 4) if vals else "NOT_ESTIMABLE"

    out = {"kind": "equity_field_report", "era": ERA,
           "generated_utc": datetime.now(timezone.utc).isoformat(),
           "cohorts": {}, "decision_power": AUTHORITY,
           "independent_episodes": "NOT_ESTIMABLE",
           "law": ("sector and event-hour clusters are correlation "
                   "controls, not independence proofs; cohorts are "
                   "distributions, not verdicts; never pooled with "
                   "the canonical paper book")}
    for cls, os_ in sorted(cohorts.items()):
        rs = [o.get("R") for o in os_
              if isinstance(o.get("R"), (int, float))]
        h60 = [(o.get("signed_horizons") or {}).get("60m")
               for o in os_]
        h60 = [v for v in h60 if isinstance(v, (int, float))]
        out["cohorts"][cls] = {
            "n_resolved": len(os_),
            "sectors": len({o.get("sector") for o in os_}),
            "event_hours": len({str(o.get("known_from", ""))[:13]
                                for o in os_}),
            "signed_60m_median": med(h60),
            "favorable_60m_rate": (round(sum(
                1 for v in h60 if v > 0) / len(h60), 3)
                if h60 else "NOT_ESTIMABLE"),
            "R_median": med(rs),
            "mfe_median": med([o.get("mfe_pct") for o in os_]),
            "mae_median": med([o.get("mae_pct") for o in os_]),
            "stopped_rate": (round(sum(
                1 for o in os_
                if o.get("exit_reason") == "STRUCTURAL_STOP")
                / len(os_), 3) if os_ else "NOT_ESTIMABLE")}
    return out


# -------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seal-universe", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--resolve", metavar="SESSION")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--follow", action="store_true")
    a = ap.parse_args()

    if a.seal_universe:
        print(json.dumps(seal_universe(), indent=1))
        return 0
    if a.report:
        print(json.dumps(report(), indent=1))
        return 0
    if a.resolve:
        seal_universe()
        print(json.dumps(resolve_field(a.resolve), indent=1))
        return 0

    seal_universe()
    session = datetime.now(timezone.utc).astimezone(ET) \
        .strftime("%Y-%m-%d")
    if a.once:
        print(json.dumps(sweep_field(session), indent=1))
        return 0
    if not a.follow:
        return 0

    beat = Heartbeat(SERVICE)
    last_sweep, resolved_session = 0.0, None
    while True:
        try:
            session = datetime.now(timezone.utc).astimezone(ET) \
                .strftime("%Y-%m-%d")
            b = session_bounds(session)
            now = datetime.now(timezone.utc)
            in_rth = (b["trading_day"] and b["open_utc"]
                      and b["open_utc"] <= now <= b["close_utc"])
            if in_rth and time.time() - last_sweep >= SCAN_INTERVAL_S:
                sweep_field(session, beat=beat)
                last_sweep = time.time()
            elif (b["trading_day"] and b["close_utc"]
                    and now > b["close_utc"]
                    and resolved_session != session):
                r = resolve_field(session)
                resolved_session = session
                beat.work(f"field resolved {r['resolved']} outcomes")
            else:
                beat.beat()
        except Exception as e:                          # noqa: BLE001
            beat.error(f"{type(e).__name__}: {str(e)[:120]}")
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
