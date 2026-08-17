#!/usr/bin/env python
"""CLOSE-1 runner — final-hour checkpoints, seal, brief, card outcomes,
daily memory. One launchd start at 12:00 PT.

    python scripts/closing_run.py [--once]

Schedule (PT): 12:00 / 12:30 / 12:50 / 12:58 checkpoints -> 13:02 close
capture + seal -> closing brief (child session, sealed facts only) ->
attach outcomes + SETUP_PERSISTENCE to today's decision cards from the
realizations ledger -> write DailyMarketMemory.

DAILY-FLAT: this script reads and remembers; it cannot hold, place, or
carry anything. decision_power NONE_FRONTIER_SHADOW.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

CLOSING_LAB_BUDGET = 4_000
FORBIDDEN_IN_BRIEF = ("buy ", "sell ", "position size", "probability",
                      "expected return", "hold overnight", "carry ")

BRIEF_PROMPT = """You are the APEX closing desk. Read ONLY the sealed
facts (JSON): today's closing packet, and the SEALED morning packet hash
+ scenarios if present. Produce a CAPTAIN CLOSING BRIEF in EXACTLY these
sections: WHAT THE DAY BECAME / WHAT THE MORNING THESIS GOT RIGHT / WHAT
THE MORNING THESIS GOT WRONG / WHAT CHANGED IN THE FINAL HOUR / WHERE
CAPITAL FINISHED / STRONGEST CLOSING LEADERS / WEAKEST CLOSING AREAS /
IMPORTANT FAILED MOVES / IMPORTANT TRAPPED PARTICIPANTS (mechanism
stated or NONE_OBSERVED) / KNOWN OVERNIGHT RISKS (state NOT_CONNECTED
sources plainly) / BIGGEST DATA BLIND SPOTS / WHAT SHOULD MATTER
TOMORROW MORNING.

The reaction-vs-expectation lens is mandatory where catalysts exist:
good news that could not hold its gap IS information; bad news the
market refused to sell IS information. Every claim cites a JSON field.
This is NOT tomorrow's trading thesis and NEVER a holding decision.
Never use: buy, sell, position size, probability, hold overnight.

SEALED FACTS:
{facts}
"""


def checkpoint(label: str):
    from apex.frontier.closing import assemble
    from apex.frontier.premarket import INDICES
    from apex.intraday.eodhd import QuotaGovernor
    gov = QuotaGovernor(daily_budget=CLOSING_LAB_BUDGET, purpose="LAB")
    symbols = list(INDICES)
    led = Path("results/hunter/forward_ledger.jsonl")
    if led.exists():
        for line in led.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == "decision" and not str(
                    r.get("playbook_id", "")).startswith("BASELINE-"):
                if r["symbol"] not in symbols:
                    symbols.append(r["symbol"])
    pkt = assemble(symbols=symbols[:12], gov=gov)
    pkt["checkpoint"] = label
    print(f"{pd.Timestamp.now(tz='UTC'):%H:%M:%S} close[{label}] "
          f"{len(pkt['day_structures'])} symbols, used {gov.used}u")
    return pkt


def attach_card_outcomes(day: str) -> int:
    """Attach realizations + SETUP_PERSISTENCE to today's sealed cards."""
    from apex.frontier.closing import setup_persistence
    from apex.frontier.decision_card import persist
    led = Path("results/hunter/forward_ledger.jsonl")
    if not led.exists():
        return 0
    decisions, realized = {}, {}
    for line in led.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") == "decision":
            decisions[r["decision_id"]] = r
        elif r.get("kind") == "realization" and r.get("resolvable"):
            realized[r["decision_id"]] = r
    n = 0
    cdir = Path(f"results/decision_cards/{day}")
    if not cdir.exists():
        return 0
    for p in cdir.glob("*.json"):
        if p.name == "traces.jsonl":
            continue
        payload = json.loads(p.read_text())
        if "after" in payload:
            continue
        card = payload["before"]
        did = card["decision_id"]
        rz = realized.get(did)
        if rz is None:
            continue
        outcome = {k: rz.get(k) for k in
                   ("ret_15m", "ret_30m", "ret_60m", "ret_90m",
                    "mae_60m", "mfe_60m", "target_before_stop")}
        outcome["setup_persistence"] = setup_persistence(
            decisions.get(did, {}), rz)
        persist(card, outcome=outcome)
        n += 1
    return n


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    from apex.frontier.closing import seal, write_memory
    from apex.frontier.premarket import load_sealed

    if a.once:
        checkpoint("manual")
        return 0

    et = lambda: pd.Timestamp.now(tz="America/New_York")  # noqa: E731
    last = None
    for label, h, m in (("1500_ET", 15, 0), ("1530_ET", 15, 30),
                        ("1550_ET", 15, 50), ("1558_ET", 15, 58),
                        ("close_capture", 16, 2)):
        target = et().normalize() + pd.Timedelta(hours=h, minutes=m)
        wait = (target - et()).total_seconds()
        if wait > 0:
            time.sleep(min(wait, 3600))
        try:
            last = checkpoint(label)
        except Exception as e:                              # noqa: BLE001
            print(f"close[{label}] DEGRADED: {type(e).__name__}: {e}")
    if last is None:
        print("no closing packet — every checkpoint failed")
        return 1
    sealed = seal(last)
    day = sealed["market_date"]
    morning = load_sealed(day)
    print(f"CLOSING SEALED {sealed['packet_sha256'][:12]}")

    # brief (commentary; firewalled)
    facts = json.dumps({
        "closing": {k: sealed[k] for k in ("market_date", "day_structures",
                                           "closing_auction_imbalance")},
        "morning_packet_sha256": (morning or {}).get("packet_sha256",
                                                     "NO_MORNING_PACKET"),
        "morning_watch_map": (morning or {}).get("watch_map", {}),
    }, indent=1, default=str)[:12000]
    try:
        r = subprocess.run(["claude", "-p", "--output-format", "text"],
                           input=BRIEF_PROMPT.format(facts=facts),
                           capture_output=True, text=True, timeout=420)
        text = r.stdout.strip()
        if any(b in text.lower() for b in FORBIDDEN_IN_BRIEF):
            text = "BRIEF REFUSED BY FIREWALL; the sealed packet stands."
        out = Path(f"results/frontier/closing/{day}_closing_brief.md")
        out.write_text(f"# CAPTAIN CLOSING BRIEF — {day}\n"
                       f"closing packet: {sealed['packet_sha256']}\n"
                       f"NOT tomorrow's thesis; NEVER a holding decision "
                       f"(DAILY_FLAT).\n\n{text}\n")
        print("brief ->", out)
    except Exception as e:                                  # noqa: BLE001
        print(f"closing brief DEGRADED ({type(e).__name__})")

    # wait for 90m horizons on late decisions, then attach card outcomes
    time.sleep(600)
    n = attach_card_outcomes(day)
    print(f"card outcomes attached: {n}")

    mem = write_memory(market_date=day, closing_packet=sealed,
                       morning_packet_hash=(morning or {}).get(
                           "packet_sha256"))
    print(f"DAILY MEMORY {mem['memory_sha256'][:12]} — positions carried "
          f"overnight: {mem['positions_carried_overnight']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
