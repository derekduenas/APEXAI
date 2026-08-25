"""OPTIONS LIVE PAPER_EXPLORATORY SESSION.

Authorized 2026-08-23. This is the loop that finally produces
PROSPECTIVE evidence -- the thing the Options Predator has never had.

WHAT IT DOES NOT DO. It places no orders. It touches no capital. It
computes what would have been filled at quoted sides and resolves it
honestly. `PAPER_EXPLORATORY` is permission to learn, not to trade.

NO TRADE QUOTA. NO_TRADE is a legitimate, recorded outcome. A funnel
that refuses everything is broken; so is one that attacks every hour
because it feels productive. Both are visible in the scoreboard.

FRICTION IS THE MISSION. The development replay showed aggregate mid
P&L of -338 against 15,318 of friction, with 75 of 304 attacks right on
mid and losing anyway. So this loop records what the thesis earned and
what the round trip cost, separately, on every attack.

decision_power: NONE_PAPER. Authority PAPER_EXPLORATORY.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append          # noqa: E402
from apex.governance.verification import stamp                 # noqa: E402
from apex.predators.options import (                           # noqa: E402
    attack_geometry, expression, friction_attribution,
    paper_execution, state, underlying_bridge)
from apex.predators.options.live_world import (                # noqa: E402
    FeedUnavailable, observe)
from apex.predators.options.replay import seal_before_card     # noqa: E402
from apex.ops.heartbeat import Heartbeat                       # noqa: E402
from apex.ops.release import build_pedigree                    # noqa: E402
from apex.predators.options.scoreboard import (                # noqa: E402
    SessionScoreboard)

CODE_PATHS = [
    "scripts/options_paper_session.py",
    "apex/predators/options/live_world.py",
    "apex/predators/options/state.py",
    "apex/predators/options/expression.py",
    "apex/predators/options/attack_geometry.py",
    "apex/predators/options/paper_execution.py",
    "apex/predators/options/underlying_bridge.py",
    "apex/predators/options/friction_attribution.py",
    "apex/predators/options/scoreboard.py",
]

UNIVERSE = ["SPY", "QQQ", "AAPL", "NVDA", "MSFT", "IWM"]

# ------------------------------------------------ PRE-REGISTERED
PROTOCOL = {
    "kind": "options_live_paper_preregistration",
    "protocol_version": "live_v1_2026_08_24",
    "authority": "PAPER_EXPLORATORY",
    "decision_power": "NONE_PAPER",
    "universe": UNIVERSE,
    "scan_interval_min": 15,
    "direction_rule":
        "the commissioned equity faculty's trend_state (UP->LONG, "
        "DOWN->SHORT, RANGE->NO_TRADE). Options does not invent a "
        "directional view.",
    "exit_rule":
        "hold to session close and resolve at quoted sides. One fixed "
        "pre-declared horizon; not tuned to outcomes.",
    "risk_basis": "FULL_PREMIUM",
    "risk_basis_note":
        "declared before the session; R is never inferred from capital",
    "sizing": "1 contract; stock comparator sized to the same 100 "
              "shares of underlying exposure",
    "feed_quality_rule":
        "an observation with stale quotes or stale bars may not be "
        "attacked; it is recorded as a refusal, not skipped silently",
    "no_trade_rule": "NO_TRADE is a legitimate outcome; there is no quota",
    "evidence_class": "PROSPECTIVE_PAPER",
    "live_capital": "LOCKED",
}


def _scan_symbol(sym: str, sb: SessionScoreboard, ledger: Path,
                 open_positions: list, as_of=None) -> dict:
    """One symbol, one instant. Returns a record of what happened."""
    rec = {"symbol": sym, "T": None}
    sb.stage("CANDIDATE")
    try:
        obs = observe(sym, now=as_of)
    except FeedUnavailable as e:
        sb.stop("DATA_QUALITY")
        return {**rec, "status": "FEED_UNAVAILABLE", "detail": str(e)}
    except Exception as e:                                 # noqa: BLE001
        sb.stop("DATA_QUALITY")
        return {**rec, "status": "FEED_ERROR",
                "detail": f"{type(e).__name__}: {e}"}

    frozen = obs.frozen
    rec["T"] = frozen.T
    rec["feed_quality"] = obs.feed_quality
    if obs.feed_quality != "GOOD":
        sb.stop("DATA_QUALITY")
        return {**rec, "status": "FEED_DEGRADED",
                "reasons": list(obs.reasons)}

    ost = state.build(frozen)
    rec["options_data_quality"] = ost.data_quality
    if ost.data_quality != "FULL":
        sb.stop("INSUFFICIENT_SURFACE")
        return {**rec, "status": "INSUFFICIENT_SURFACE"}
    sb.stage("SERIOUS")

    probe = underlying_bridge.build(frozen, direction="LONG")
    trend = probe.trend_state
    rec["trend_state"] = trend
    if trend not in ("UP", "DOWN"):
        sb.stop("NO_DIRECTIONAL_THESIS")
        return {**rec, "status": "NO_DIRECTIONAL_THESIS"}
    direction = "LONG" if trend == "UP" else "SHORT"
    ug = underlying_bridge.build(frozen, direction=direction)
    rec.update({"direction": direction,
                "entry_quality": ug.entry_quality,
                "chase_risk": ug.chase_risk})

    cands = expression.build_candidates(
        frozen, direction, iv=ost.atm_iv,
        stock_bid=obs.stock_bid, stock_ask=obs.stock_ask)
    if not cands:
        sb.stop("NO_EXPRESSIONS")
        return {**rec, "status": "NO_EXPRESSIONS"}

    stock_c = next((c for c in cands if c.expression == "STOCK"), None)
    ready, blocked = [], []
    import pandas as _pd
    _T = _pd.Timestamp(frozen.T)
    for c in cands:
        if c.expression == "STOCK":
            continue
        # DTE must be supplied or theta burden is UNKNOWN and the
        # geometry judges a contract it cannot actually see the tenor of
        dte = ((_pd.Timestamp(c.expiration) - _T.normalize()).days
               if c.expiration else None)
        geo = attack_geometry.assess(
            subject=sym, direction=direction, candidate=c,
            underlying_geometry=ug, spot=frozen.spot_ref,
            dte=dte, forecast_pedigree="NOT_ESTIMABLE")
        fin = attack_geometry.assassinate(
            geometry=geo, options_state=ost, candidate=c,
            stock_candidate=stock_c)
        if geo.attackable and fin.verdict not in ("REFUSE",):
            ready.append((c, geo, fin))
        else:
            blocked.append((c.expression,
                            "GEOMETRY" if not geo.attackable
                            else fin.verdict))
    rec["attackable"] = [c.expression for c, _g, _f in ready]
    rec["blocked"] = blocked

    if not ready:
        # WAIT_FOR_ENTRY vs REFUSED is a real distinction, not
        # bookkeeping. If every contract was sound and only the
        # LOCATION was poor, the thesis survives and we are early --
        # that is a setup to revisit. If the CONTRACTS were the
        # problem, no amount of waiting helps.
        location_only = (ug.entry_quality == "POOR" and
                         all(q in ("GEOMETRY",) for _e, q in blocked))
        if location_only:
            sb.stage("WAIT_FOR_ENTRY")
            sb.stop("NO_TRADE")
            return {**rec, "status": "WAIT_FOR_ENTRY",
                    "why": "contracts are sound; the underlying "
                           "location is not attackable yet"}
        if blocked:
            sb.near_miss(symbol=sym, T=frozen.T, missing=blocked[0][1])
        sb.stop("GEOMETRY_REFUSED" if blocked else "NO_TRADE")
        return {**rec, "status": "NO_ATTACKABLE_EXPRESSION"}

    sb.stage("ATTACK_READY")
    # pre-declared selection: the expression whose breakeven demands the
    # least of the move. Deterministic, declared before the session.
    chosen, geo, fin = min(
        ready, key=lambda t: (t[0].breakeven_move_pct
                              if t[0].breakeven_move_pct is not None
                              else 9e9))

    from apex.governance.trade_semantics import (
        OPTIONS_HOLD_TO_CLOSE, TradeAuthorities)
    authorities = TradeAuthorities(
        thesis_invalidation=ug.invalidation, **OPTIONS_HOLD_TO_CLOSE)
    card = seal_before_card({
        "protocol_version": PROTOCOL["protocol_version"],
        "authorities": authorities.as_record(),
        "symbol": sym, "T": frozen.T, "direction": direction,
        "frozen_digest": frozen.digest(),
        "expression": chosen.expression,
        "expiration": chosen.expiration,
        "legs": [list(x) for x in chosen.legs],
        "debit": chosen.debit,
        "round_trip_friction": chosen.round_trip_friction,
        "entry_quality": ug.entry_quality,
        # NAMED for what it is: diagnostic under this protocol, NOT an
        # execution stop. See authorities above.
        "thesis_invalidation": ug.invalidation,
        "atm_iv": ost.atm_iv,
        "assassin_verdict": fin.verdict,
        "exit_rule": PROTOCOL["exit_rule"],
    })
    chain_append(ledger, {"kind": "options_live_card", **card})

    fill = paper_execution.simulate_entry(
        chosen, T=frozen.T, contracts=1,
        sealed_card_hash=card["card_hash"],
        risk_basis=PROTOCOL["risk_basis"])
    sb.stage("PAPER_ATTACKED")
    open_positions.append({
        "symbol": sym, "card_hash": card["card_hash"], "fill": fill,
        "entry_spot": frozen.spot_ref, "expiration": chosen.expiration,
        "candidate": chosen, "entry_iv": ost.atm_iv,
        "opened_T": frozen.T})
    rec.update({"status": "PAPER_ATTACKED",
                "expression": chosen.expression,
                "card_hash": card["card_hash"],
                "net_debit": fill.net_debit,
                "declared_1R": fill.declared_1R_dollars})
    chain_append(ledger, {"kind": "options_live_attack", **rec})
    return rec


def resolve_open(open_positions: list, sb: SessionScoreboard,
                 ledger: Path, as_of=None) -> list:
    """Close every open paper position at quoted sides."""
    import pandas as pd
    out = []
    for pos in open_positions:
        sym = pos["symbol"]
        try:
            obs = observe(sym, now=as_of)
        except Exception as e:                             # noqa: BLE001
            out.append({"symbol": sym, "status": "UNRESOLVED",
                        "detail": f"{type(e).__name__}: {e}"})
            continue
        from apex.governance.resolution_time import (
            eligible_window as _ew, to_utc as _tu)
        _ow = _ew(entry_ts=pos["opened_T"], session=sb.session,
                  symbol=sym, option=True,
                  horizon="REGULAR_SESSION_CLOSE")
        _obound = _tu(_ow["boundary_utc"])
        latest = {}
        for q in obs.frozen.option_quotes:
            if _tu(q["timestamp"], assume="ET") > _obound:
                continue          # an option's own close, not the equity's
            key = (str(q["expiration"]), float(q["strike"]),
                   "C" if q["right"].upper().startswith("C") else "P")
            prev = latest.get(key)
            if prev is None or q["timestamp"] >= prev["timestamp"]:
                latest[key] = q

        def lookup(exp, strike, right):
            r = latest.get((str(exp), float(strike), right))
            if r is None:
                return None
            b, a = float(r["bid"]), float(r["ask"])
            return (b, a) if (b > 0 and a > 0 and a >= b) else None

        # DEFECT A+B REPAIR (2026-08-24). The sealed rule says
        # SESSION_CLOSE, so the boundary comes from the trading
        # calendar -- never from whenever this resolver happens to run.
        # Timestamps are normalized UTC-aware before any comparison.
        from apex.governance.resolution_time import (
            eligible_window, to_utc)
        win = eligible_window(
            entry_ts=pos["opened_T"], session=sb.session, symbol=sym,
            option=False, horizon="REGULAR_SESSION_CLOSE")
        e_utc, b_utc = to_utc(win["entry_utc"]), to_utc(win["boundary_utc"])
        bars = [b for b in obs.frozen.underlying_bars
                if e_utc < to_utc(b["t"], assume="UTC") <= b_utc]
        outcome = paper_execution.resolve(
            fill=pos["fill"], sealed_card_hash=pos["card_hash"],
            future_underlying=bars, future_quote_lookup=lookup,
            entry_underlying=pos["entry_spot"],
            entry_utc=win["entry_utc"], boundary_utc=win["boundary_utc"])
        att = friction_attribution.attribute(
            outcome=outcome, candidate=pos["candidate"])
        sb.attack(symbol=sym, T=pos["opened_T"],
                  expression=outcome.expression, attribution=att)
        chain_append(ledger, {"kind": "options_live_outcome",
                              **outcome.as_record()})
        chain_append(ledger, att.as_record())
        out.append({"symbol": sym, "expression": outcome.expression,
                    "pnl": outcome.pnl, "r": outcome.r_multiple,
                    "class": att.primary_class,
                    "friction": att.total_friction})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--minutes", type=int, default=390)
    ap.add_argument("--interval-min", type=int, default=15)
    ap.add_argument("--symbols", default=",".join(UNIVERSE))
    ap.add_argument("--dry-run", action="store_true",
                    help="one scan cycle, resolve immediately")
    ap.add_argument("--as-of", default=None,
                    help="REHEARSAL ONLY: run the loop as if it were "
                         "this UTC instant, to prove the machinery on "
                         "a closed market. Output is stamped REHEARSAL "
                         "and is NOT prospective evidence.")
    a = ap.parse_args()

    ledger = Path(a.ledger)
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    as_of = None
    if a.as_of:
        as_of = datetime.fromisoformat(a.as_of).replace(
            tzinfo=timezone.utc)
    now0 = as_of or datetime.now(timezone.utc)
    session = now0.strftime("%Y-%m-%d")
    sb = SessionScoreboard(session=session)

    mode = {"evidence_class": "REHEARSAL_NOT_EVIDENCE",
            "as_of": a.as_of,
            "why": "the loop was driven at a past instant to prove the "
                   "machinery; it produces NO prospective evidence"} \
        if as_of else {"evidence_class": "PROSPECTIVE_PAPER"}
    # A live trading session must never be able to die unnoticed.
    ped = build_pedigree(
        service="options-paper",
        release_dir=Path(__file__).resolve().parents[1],
        code_paths=CODE_PATHS, config={"symbols": syms, **PROTOCOL},
        authority="PAPER_EXPLORATORY")
    beat = Heartbeat(service="options-paper",
                     release_commit=ped.get("commit"),
                     release_path=ped["release_path"],
                     authority="PAPER_EXPLORATORY",
                     notes={"session": session, "symbols": syms,
                            "secret_backend": ped["secret_backend"]})
    beat.beat()
    chain_append(ledger, {**PROTOCOL, **mode, "session": session,
                          "symbols": syms, "pedigree": ped})
    print(f"protocol pre-registered for {session}: {syms}", flush=True)

    deadline = datetime.now(timezone.utc) + timedelta(minutes=a.minutes)
    open_positions, scans = [], []
    while datetime.now(timezone.utc) < deadline:
        for sym in syms:
            if any(p["symbol"] == sym for p in open_positions):
                continue          # one open paper position per symbol
            r = _scan_symbol(sym, sb, ledger, open_positions,
                             as_of=as_of)
            scans.append(r)
            print(f"  {sym:5} {r.get('status')}", flush=True)
            # a completed SCAN is the unit of work -- a session that
            # attacks nothing is still working, and must not read as
            # stalled just because it correctly refused
            beat.work(f"{sym} {r.get('status')}",
                      backlog=len(open_positions))
        if a.dry_run:
            break
        time.sleep(a.interval_min * 60)

    beat.work("resolving open positions")
    resolved = resolve_open(open_positions, sb, ledger, as_of=as_of)
    beat.work(f"session complete: {len(resolved)} resolved")
    report = sb.report()
    chain_append(ledger, report)
    Path(a.out).write_text(json.dumps(stamp(
        {"protocol": {**PROTOCOL, **mode}, "scoreboard": report,
         "scans": scans, "resolved": resolved}, CODE_PATHS),
        indent=1, default=str))
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
