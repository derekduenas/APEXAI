"""THE OPPORTUNITY FUNNEL — where opportunities die, counted.

One cycle of the organism, measured stage by stage from the ledgers
the runtime actually writes. Ends with the verdict the operator
demanded: when attacks are zero, was it MARKET_ABSENCE (the market
offered nothing after costs) or SYSTEM_FAILURE (an organ was
unreachable, stale, or had no consumer)?

CASH-win taxonomy (sealed PROFIT-COMBAT-COMMISSIONING-2026-08-31):
  NO_ALPHA | EDGE_TOO_SMALL | COST_DESTROYS_EDGE |
  UNCERTAINTY_TOO_HIGH | EXPRESSION_UNAVAILABLE |
  RISK_KERNEL_REFUSAL | DATA_INVALID | SYSTEM_PATH_BROKEN

Usage: python3 scripts/opportunity_funnel.py [--session YYYY-MM-DD]
decision_power: NONE_REPORTING.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RUNTIME = Path("/apex-data/runtime")
CORE = Path("/apex-data/core")


def rows(p: Path, tail: int | None = None) -> list:
    if not p.exists():
        return []
    lines = p.read_text().splitlines()
    if tail:
        lines = lines[-tail:]
    out = []
    for line in lines:
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def age_min(p: Path):
    return round((time.time() - p.stat().st_mtime) / 60, 1) \
        if p.exists() else None


def main() -> None:
    ap = argparse.ArgumentParser()
    # sessions are New-York-dated; a UTC default mislabeled Sunday
    # evening as Monday (commissioning integrity defect A, fixed)
    ap.add_argument("--session",
                    default=datetime.now(
                        ZoneInfo("America/New_York"))
                    .strftime("%Y-%m-%d"))
    a = ap.parse_args()
    S = a.session

    # ---- stage 0: sensing health
    feeds = {}
    for name, p, live_when in [
        ("ALPACA_SIP_EQUITY", CORE / "intraday/"
         "alpaca_fabric_health.json", "US_RTH"),
        ("BTC_ORDERBOOK_WS", CORE / "btc/ws_health.json", "24/7"),
        ("BTC_DERIVATIVES", CORE / "btc/derivatives_health.json",
         "24/7"),
        ("CATALYST_EVENTS", RUNTIME / "results/outbox/"
         "catalyst_observations.jsonl", "CONTINUOUS"),
    ]:
        am = age_min(Path(p))
        feeds[name] = {"age_min": am, "expected_live": live_when,
                       "fresh": am is not None and (
                           am < 30 if live_when == "24/7" else True)}

    # ---- stages: what each organ produced this session
    def sess_rows(p, kinds, tail=5000):
        return [r for r in rows(Path(p), tail)
                if str(r.get("session") or r.get("T")
                       or r.get("known_from") or "")[:10] == S
                and (not kinds or r.get("kind") in kinds
                     or r.get("record_kind") in kinds)]

    eq_field = sess_rows(CORE / "equities/shadow_decisions.jsonl",
                         None)
    eq_out = sess_rows(RUNTIME / "results/outbox/"
                       "equity_shadow_decisions.jsonl", None)
    opt_out = sess_rows(RUNTIME / "results/outbox/v1_decisions.jsonl",
                        None)
    btc = sess_rows(CORE / "btc/paper_ledger.jsonl", None)
    btc_windows = [r for r in btc
                   if r.get("kind") == "btc_paper_decision"]
    btc_attacks = [r for r in btc_windows
                   if r.get("cohort", "").startswith("ATTACK")
                   or r.get("susceptible") is True]
    book = rows(RUNTIME / "results/organism/paper_book.jsonl")
    fundings = [r for r in book if r.get("kind") == "paper_funding"
                and str(r.get("session", ""))[:10] == S]
    refusals = [r for r in book if r.get("kind") == "paper_refusal"
                and str(r.get("session", ""))[:10] == S]

    refusal_reasons: dict = {}
    for r in refusals:
        refusal_reasons[r.get("refused_at_stage", "UNKNOWN")] = \
            refusal_reasons.get(r.get("refused_at_stage",
                                      "UNKNOWN"), 0) + 1

    # universe observed: fabric symbols + BTC
    try:
        uni = json.loads((CORE / "intraday/universe_coverage.json")
                         .read_text())
        n_universe = uni.get("coverage_count", 0) + 1  # + BTC
    except Exception:                                   # noqa: BLE001
        n_universe = "UNKNOWN"

    funnel = {
        "kind": "opportunity_funnel", "session": S,
        "measured_utc": datetime.now(timezone.utc).isoformat(),
        "FEED_HEALTH": feeds,
        "UNIVERSE_OBSERVED": n_universe,
        "EQUITY_FIELD_DECISIONS": len(eq_field),
        "ALPHA_PROPOSALS": {
            "equity_outbox": len(eq_out),
            "options_outbox": len(opt_out),
            "btc_windows_sealed": len(btc_windows),
            "btc_susceptible_or_attack": len(btc_attacks)},
        "REACHED_ALLOCATOR": len(fundings) + len(refusals),
        "ATTACKED_PAPER": len(fundings),
        "REFUSED": refusal_reasons or 0,
    }

    # ---- the verdict
    market_open = feeds["ALPACA_SIP_EQUITY"]["age_min"] is not None \
        and feeds["ALPACA_SIP_EQUITY"]["age_min"] < 30
    btc_alive = bool(feeds["BTC_ORDERBOOK_WS"]["fresh"])
    broken = [k for k, v in feeds.items()
              if v["expected_live"] == "24/7" and not v["fresh"]]
    if funnel["ATTACKED_PAPER"] == 0:
        if broken:
            verdict = {"zero_attacks": "SYSTEM_FAILURE",
                       "broken_organs": broken}
        elif not market_open and btc_alive:
            # operator correction: equities being closed is NOT full
            # market absence -- only the 24/7 sleeves were observable
            verdict = {
                "zero_attacks":
                    "NO_ELIGIBLE_OPPORTUNITY_IN_OBSERVABLE_24_7"
                    "_SLEEVES",
                "detail": "US equities closed; BTC feeds live and "
                          "its predator sealed windows without "
                          "finding a susceptible setup -- refusal, "
                          "not blindness"
                if btc_windows and not btc_attacks else
                "US equities closed; BTC live"
                + (f"; {len(btc_attacks)} susceptible windows "
                   f"sealed (paper loop owns them)"
                   if btc_attacks else "; no BTC windows this "
                   "session yet -- check the paper loop host")}
        else:
            verdict = {"zero_attacks": "MARKET_ABSENCE",
                       "detail": "organs healthy; no proposal "
                                 "survived costs/arena/kernel; see "
                                 "REFUSED counts"}
    else:
        verdict = {"zero_attacks": False,
                   "attacks": funnel["ATTACKED_PAPER"]}
    funnel["VERDICT"] = verdict
    funnel["decision_power"] = "NONE_REPORTING"
    print(json.dumps(funnel, indent=1))


if __name__ == "__main__":
    main()
