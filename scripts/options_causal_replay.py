"""OPTIONS CAUSAL HISTORICAL REPLAY over the frozen PhD boundary.

This is the first end-to-end run of the Options Predator against REAL
acquired history. It exists to prove the PLUMBING carries real data
honestly -- temporal firewall, sealed cards, quoted-side fills, declared
risk -- not to prove profitability. Nothing it produces is prospective
evidence.

PROTOCOL IS PRE-REGISTERED. The full protocol (decision cadence, exit
rule, direction rule, risk bases) is hash-sealed into the ledger BEFORE
a single outcome is read. No parameter here may be revised after
results are inspected without a new pre-registration and a new run.

SAMPLE LAW. Four decision instants inside one session are FOUR VIEWS OF
ONE DAY, not four independent samples. n_effective is bounded by unique
symbol-sessions and is reported as such.

decision_power: NONE -- replay. Authority OBSERVE.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append          # noqa: E402
from apex.predators.options import (                           # noqa: E402
    attack_geometry, expression, paper_execution, state,
    underlying_bridge)
from apex.predators.options.replay import (                    # noqa: E402
    ReplayWorld, sample_accounting, seal_before_card)

NOT_ESTIMABLE = "NOT_ESTIMABLE"

# ------------------------------------------------ PRE-REGISTERED PROTOCOL
PROTOCOL = {
    "kind": "options_replay_preregistration",
    "protocol_version": "v1_2026_08_23",
    "decision_cadence_et": ["10:00", "11:30", "13:00", "14:30"],
    "cadence_rationale":
        "a fixed clock grid chosen before any outcome was seen; spread "
        "across the session so the run is not concentrated in one "
        "regime. NOT selected for productivity.",
    "direction_rule":
        "taken from the commissioned equity faculty's trend_state at T "
        "(UP->LONG, DOWN->SHORT, RANGE->no decision). The Options "
        "Predator does not invent its own directional view.",
    "exit_rule":
        "hold to the LAST option-quote instant of the same session. One "
        "fixed horizon, pre-declared, never tuned to outcomes.",
    "risk_basis_options": "FULL_PREMIUM",
    "risk_basis_stock": "PLANNED_INVALIDATION",
    "risk_basis_note":
        "option and stock R rest on DIFFERENT declared bases and are "
        "therefore NOT directly comparable as R-multiples; cross-"
        "expression comparison is reported per normalization basis "
        "only, and no winner is crowned.",
    "gates_are_quality_priors_not_thresholds":
        "attack geometry may REFUSE on structural invalidity only; no "
        "learned economic threshold is authorized at this authority.",
    "evidence_class": "HISTORICAL_DEVELOPMENT_REPLAY",
    "live_promotion_eligible": False,
    "decision_power": "NONE",
}


def _last_quotes_by_contract(rows: list) -> dict:
    """Collapse revealed future quotes to the LAST quote per contract --
    the pre-declared session-close exit.

    Keyed on FULL contract identity. Keying on strike alone let a
    different expiration close the position (caught by the first real
    replay: a long vertical showed a loss larger than its debit)."""
    out = {}
    for r in rows:
        key = (str(r["expiration"]), float(r["strike"]),
               "C" if r["right"].upper().startswith("C") else "P")
        prev = out.get(key)
        if prev is None or r["timestamp"] >= prev["timestamp"]:
            out[key] = r
    return out


def _quote_lookup(last_by_contract: dict):
    def lookup(expiration, strike, right):
        r = last_by_contract.get((str(expiration), float(strike), right))
        if r is None:
            return None
        try:
            b, a = float(r["bid"]), float(r["ask"])
        except (TypeError, ValueError):
            return None
        if b <= 0 or a <= 0 or a < b:
            return None
        return (b, a)
    return lookup


def _instant_at(instants: list, session: str, hhmm: str) -> str | None:
    """First quote instant at or after the pre-declared clock time."""
    want = f"{session}T{hhmm}"
    for t in instants:
        if str(t).replace(" ", "T")[:16] >= want:
            return t
    return None


def run_session(root: Path, symbol: str, session: str,
                ledger: Path) -> list:
    """Replay one symbol-day. Returns per-decision records."""
    import pandas as pd

    world = ReplayWorld.load(root, symbol, session)
    instants = world.instants()
    if not instants:
        return [{"symbol": symbol, "session": session,
                 "status": "NO_ELIGIBLE_QUOTES"}]
    exit_T = instants[-1]
    records = []

    for hhmm in PROTOCOL["decision_cadence_et"]:
        T = _instant_at(instants, session, hhmm)
        rec = {"symbol": symbol, "session": session, "clock_et": hhmm,
               "T": str(T) if T else None}
        if T is None or T == exit_T:
            rec["status"] = "NO_INSTANT_AT_CLOCK"
            records.append(rec)
            continue

        frozen = world.at(T)
        if frozen.spot_ref is None:
            rec["status"] = "NO_CAUSAL_SPOT"
            records.append(rec)
            continue

        # ---- domain state (observation only)
        ost = state.build(frozen)
        rec["options_data_quality"] = ost.data_quality
        rec["atm_iv"] = ost.atm_iv
        rec["surface_points"] = ost.surface_points

        # ---- direction from the commissioned equity faculty
        probe = underlying_bridge.build(frozen, direction="LONG")
        trend = probe.trend_state
        if trend not in ("UP", "DOWN"):
            rec["status"] = "NO_DIRECTIONAL_THESIS"
            rec["trend_state"] = trend
            records.append(rec)
            continue
        direction = "LONG" if trend == "UP" else "SHORT"
        ug = underlying_bridge.build(frozen, direction=direction)
        rec.update({"direction": direction, "trend_state": trend,
                    "entry_quality": ug.entry_quality,
                    "chase_risk": ug.chase_risk,
                    "underlying_data_quality": ug.data_quality})

        # ---- expressions
        iv = ost.atm_iv if ost.data_quality == "FULL" else None
        cands = expression.build_candidates(frozen, direction, iv=iv)
        if not cands:
            rec["status"] = "NO_EXPRESSIONS"
            records.append(rec)
            continue

        # ---- geometry + assassin per option expression
        stock_c = next((c for c in cands if c.expression == "STOCK"),
                       None)
        assessed = []
        for c in cands:
            if c.expression == "STOCK":
                continue
            geo = attack_geometry.assess(
                subject=symbol, direction=direction, candidate=c,
                underlying_geometry=ug, spot=frozen.spot_ref,
                forecast_pedigree="NOT_ESTIMABLE")
            fin = attack_geometry.assassinate(
                geometry=geo, options_state=ost, candidate=c,
                stock_candidate=stock_c)
            assessed.append((c, geo, fin))
        rec["expressions_assessed"] = len(assessed)
        rec["attackable"] = [c.expression for c, g, _f in assessed
                             if g.attackable]

        # ---- planned invalidation loss for the STOCK leg (knowable at T)
        planned = {}
        if stock_c is not None and ug.invalidation is not None:
            per_share = abs(frozen.spot_ref - ug.invalidation)
            planned["STOCK"] = round(
                per_share * paper_execution.CONTRACT_MULTIPLIER, 2)

        # ---- SEAL THE CARD (before any future is touched)
        card = seal_before_card({
            "protocol_version": PROTOCOL["protocol_version"],
            "symbol": symbol, "session": session, "T": str(T),
            "direction": direction,
            "frozen_digest": frozen.digest(),
            "expressions": [c.expression for c in cands],
            "attackable": rec["attackable"],
            "entry_quality": ug.entry_quality,
            "invalidation": ug.invalidation,
            "planned_invalidation_loss": planned,
            "exit_rule": PROTOCOL["exit_rule"], "exit_T": str(exit_T),
        })
        rec["card_hash"] = card["card_hash"]
        chain_append(ledger, {"kind": "options_replay_card", **card})

        # ---- reveal the future ONLY now
        fq, fb = world.reveal_after(T, card["card_hash"])
        exit_rows = [r for r in fq if r["timestamp"] == exit_T]
        lookup = _quote_lookup(_last_quotes_by_contract(exit_rows))
        future_bars = [b for b in fb]
        if not future_bars or not exit_rows:
            rec["status"] = "NO_FUTURE_AT_EXIT"
            records.append(rec)
            continue

        # ---- resolve every expression (measurement only)
        cf = paper_execution.counterfactual_expressions(
            candidates=cands, T=str(T), sealed_card_hash=card["card_hash"],
            future_underlying=future_bars, future_quote_lookup=lookup,
            entry_underlying=frozen.spot_ref,
            risk_basis=PROTOCOL["risk_basis_options"],
            planned_losses=planned)
        rec["counterfactuals"] = {
            k: v for k, v in cf.items() if not k.startswith("_")}
        rec["winner"] = cf["_winner"]

        # ---- normalization: every basis, side by side
        rec["normalization"] = expression.normalize(
            cands, risk_budget_dollars=500.0,
            risk_basis=PROTOCOL["risk_basis_options"],
            planned_losses=planned)

        rec["status"] = "RESOLVED"
        rec["setup_family"] = f"{trend}_{ug.entry_quality}"
        records.append(rec)
        chain_append(ledger, {"kind": "options_replay_outcome",
                              **{k: v for k, v in rec.items()
                                 if k != "normalization"}})
    return records


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--boundary", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    boundary = json.loads(Path(a.boundary).read_text())
    ledger = Path(a.ledger)

    # PRE-REGISTER BEFORE ANY RESULT IS READ
    chain_append(ledger, {**PROTOCOL,
                          "boundary_sha256": boundary["boundary_sha256"],
                          "n_symbol_days": boundary["n_symbol_days"]})
    print(f"protocol pre-registered against boundary "
          f"{boundary['boundary_sha256'][:12]}")

    members = boundary["members"]
    if a.limit:
        members = members[:a.limit]
    all_recs = []
    for i, m in enumerate(members, 1):
        try:
            recs = run_session(Path(a.root), m["symbol"], m["date"],
                               ledger)
        except Exception as e:                             # noqa: BLE001
            recs = [{"symbol": m["symbol"], "session": m["date"],
                     "status": "ERROR", "error": f"{type(e).__name__}: {e}"}]
        all_recs.extend(recs)
        if i % 10 == 0 or i == len(members):
            print(f"  {i}/{len(members)} symbol-days", flush=True)

    resolved = [r for r in all_recs if r.get("status") == "RESOLVED"]
    summary = {
        "kind": "options_replay_summary",
        "protocol_version": PROTOCOL["protocol_version"],
        "boundary_sha256": boundary["boundary_sha256"],
        "symbol_days_attempted": len(members),
        "decisions_raw": len(all_recs),
        "decisions_resolved": len(resolved),
        "status_counts": {},
        "sample_accounting": sample_accounting(resolved),
        "evidence_class": "HISTORICAL_DEVELOPMENT_REPLAY",
        "live_promotion_eligible": False,
    }
    for r in all_recs:
        s = r.get("status", "?")
        summary["status_counts"][s] = summary["status_counts"].get(s, 0) + 1
    chain_append(ledger, summary)
    Path(a.out).write_text(json.dumps(
        {"summary": summary, "records": all_recs}, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
