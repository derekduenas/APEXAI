#!/usr/bin/env python
"""PREMARKET-1 runner — absorb, refresh, seal, brief. One launchd start.

    python scripts/premarket_run.py            # full 05:15->06:26 schedule
    python scripts/premarket_run.py --once     # single absorption now

Refreshes at ~05:15 / 05:32 / 06:05 / 06:20 PT; SEALS the opening packet
at ~06:25; generates the Captain Morning Brief via ONE bounded child
session that receives the SEALED FACTS as JSON and may interpret but
never invent — every summarized item must cite a packet field, trading
vocabulary is firewalled, and the raw packet always outranks the prose.

Quota: LAB purpose, own local budget. decision_power NONE_FRONTIER_SHADOW.
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

PREMARKET_LAB_BUDGET = 6_000        # units; ~4 refreshes x ~30 symbols x 5u
BRIEF_DIR = Path("results/frontier/premarket")

FORBIDDEN_IN_BRIEF = ("buy ", "sell ", "position size", "probability",
                      "expected return", "place ", "authorize")

BRIEF_PROMPT = """You are the APEX premarket desk: five seats, one pass.
Read ONLY the sealed facts below (JSON). Roles: TAPE READER (what does
price/volume/sector behavior say), CATALYST ANALYST (which moves have
identified events; UNKNOWN_CATALYST_DISLOCATION names are flagged),
MACRO/CROSS-ASSET (note that MACRO_CALENDAR and CROSS_ASSET are
NOT_CONNECTED — treat that as a stated blind spot, never fill it from
memory), ADVERSARIAL TRADER (what obvious narrative may be misleading;
who may be crowded/trapped), CAPTAIN (synthesis).

Produce a CAPTAIN MORNING BRIEF in EXACTLY these sections:
WHAT CHANGED OVERNIGHT / MARKET WORLD / LEADING AREAS / WEAK AREAS /
IMPORTANT GAP NAMES / KNOWN CATALYSTS / NO CATALYST WITHIN ACTIVE
SOURCES / TODAY'S KNOWN SCHEDULED RISKS (state NOT_CONNECTED if the
calendar source is) / BIGGEST DATA BLIND SPOTS / WHAT COULD FOOL US AT
THE OPEN / SCENARIO A / SCENARIO B / SCENARIO C (each scenario: WOULD
EXPECT + INVALIDATED BY; qualitative, NO probabilities) / NAMES WORTH
WATCHING.

ELITE LENS (mandatory where catalysts exist): expectation vs reaction —
WHAT HAPPENED vs HOW PRICE REACTED. Good news + weak/negative reaction
IS information; bad news + refusal to fall IS information. Distinguish
gap QUALITY from gap size; sector sympathy from idiosyncratic moves;
note extension of overnight moves and possibly-trapped overnight
participants; end with WHAT WOULD MAKE THE CAPTAIN ABANDON THIS THESIS.

Rules: every factual claim must cite a field from the JSON (cite as
[field]). Anything not in the JSON is UNKNOWN. Never use the words: buy,
sell, position size, probability, expected return. These are PRIORS, not
truth — the tape gets the final vote.

SEALED FACTS:
{facts}
"""


def absorb(label: str) -> dict:
    from apex.events.catalyst import catalyst_state
    from apex.events.cik_bridge import cik_of
    from apex.frontier.premarket import INDICES, assemble
    from apex.intraday.eodhd import QuotaGovernor

    # bounded symbol set: indices + liquidity-top names from the frozen
    # scan universe (consumer read; no new selection logic)
    symbols = list(INDICES)
    uni = sorted(Path("results/hunter").glob("scan_universe_*.json"))
    if uni:
        try:
            u = json.loads(uni[-1].read_text())
            symbols += list(u.get("symbols", {}))[:25]
        except json.JSONDecodeError:
            pass
    gov = QuotaGovernor(daily_budget=PREMARKET_LAB_BUDGET, purpose="LAB")

    def cat(sym, now):
        return catalyst_state(sym, now, cik=cik_of(sym))

    pkt = assemble(symbols=symbols, gov=gov, catalyst_lookup=cat)
    pkt["absorption_label"] = label
    ok = sum(1 for v in pkt["indices"].values() if v.get("status") == "OK")
    print(f"{pd.Timestamp.now(tz='UTC'):%H:%M:%S} absorb[{label}] "
          f"indices_ok={ok}/4 movers={len(pkt['gap_map'])} "
          f"unknown_catalyst={len(pkt['watch_map']['UNKNOWN_CATALYST_MOVERS'])} "
          f"quota_used={gov.used}u")
    return pkt


def brief(sealed: dict) -> str:
    facts = json.dumps({k: sealed[k] for k in
                        ("market_date", "indices", "gap_map", "watch_map",
                         "source_coverage", "blind_spots")},
                       indent=1, default=str)[:14000]
    r = subprocess.run(["claude", "-p", "--output-format", "text"],
                       input=BRIEF_PROMPT.format(facts=facts),
                       capture_output=True, text=True, timeout=420)
    text = r.stdout.strip()
    low = text.lower()
    for bad in FORBIDDEN_IN_BRIEF:
        if bad in low:
            text = (f"BRIEF REFUSED BY FIREWALL (contained {bad!r}); the "
                    f"sealed packet stands alone this morning.")
            break
    out = BRIEF_DIR / f"{sealed['market_date']}_morning_brief.md"
    out.write_text(
        f"# CAPTAIN MORNING BRIEF — {sealed['market_date']}\n"
        f"packet sha256: {sealed['packet_sha256']}\n"
        f"PRIORS, NOT TRUTH — the tape gets the final vote; if the open "
        f"contradicts this brief, THE BRIEF LOSES.\n"
        f"decision_power: NONE_FRONTIER_SHADOW\n\n{text}\n")
    return str(out)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    from apex.frontier.premarket import seal

    if a.once:
        pkt = absorb("manual")
        return 0

    et = lambda: pd.Timestamp.now(tz="America/New_York")  # noqa: E731
    schedule = [("0815_ET_initial", 8, 15), ("0832_ET_post_macro", 8, 32),
                ("0905_ET_refresh", 9, 5), ("0920_ET_final", 9, 20)]
    last = None
    for label, h, m in schedule:
        target = et().normalize() + pd.Timedelta(hours=h, minutes=m)
        wait = (target - et()).total_seconds()
        if wait > 0:
            time.sleep(min(wait, 3600))
        try:
            last = absorb(label)
        except Exception as e:                              # noqa: BLE001
            print(f"absorb[{label}] DEGRADED: {type(e).__name__}: {e}")
    # seal at ~09:25 ET
    target = et().normalize() + pd.Timedelta(hours=9, minutes=25)
    wait = (target - et()).total_seconds()
    if wait > 0:
        time.sleep(wait)
    if last is None:
        print("nothing to seal — every absorption failed (DEGRADED)")
        return 1
    last["as_of_time"] = str(pd.Timestamp.now(tz="UTC"))
    sealed = seal(last)
    print(f"PACKET SEALED {sealed['packet_sha256'][:12]} "
          f"-> {BRIEF_DIR}/{sealed['market_date']}.json")
    try:
        print("brief ->", brief(sealed))
    except Exception as e:                                  # noqa: BLE001
        print(f"morning brief DEGRADED ({type(e).__name__}) — the sealed "
              f"packet stands alone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
