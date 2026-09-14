#!/usr/bin/env python
"""PREMARKET-1 runner — LEGACY. Retained as a PARITY ORACLE, no longer a production entry point.

STATUS AFTER R4. The production scheduler invokes scripts/premarket_stage.py, one bounded process per stage.
This file keeps its original one-process-sleeps-through-the-morning shape ON PURPOSE, so the staged producer can
be compared against it on identical frozen inputs. Its two `time.sleep()` calls are the defect under repair and
are deliberately NOT fixed here — fixing them would destroy the oracle.

Everything it absorbs, briefs and seals now goes through apex.frontier.premarket_stages, so the two paths cannot
disagree about WHAT they collect. The only thing they disagree about is WHEN, which is the point.

Original header follows.

PREMARKET-1 runner — absorb, refresh, seal, brief. One launchd start.

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

import sys
import time
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

from apex.frontier import premarket_stages as PS  # noqa: E402

# One definition, in the library. These names stay bound here because other readers import them.
PREMARKET_LAB_BUDGET = PS.PREMARKET_LAB_BUDGET
BRIEF_DIR = Path("results/frontier/premarket")
FORBIDDEN_IN_BRIEF = PS.FORBIDDEN_IN_BRIEF
BRIEF_PROMPT = PS.BRIEF_PROMPT



def absorb(label: str) -> dict:
    """Delegates to THE absorb. There is no second implementation to drift from."""
    from apex.frontier import premarket_runtime as RT
    pkt = PS.absorb(label)
    s = PS.absorb_summary(pkt)
    print(f"{RT.now_utc():%H:%M:%S} absorb[{label}] "
          f"indices_ok={s['indices_ok']}/4 movers={s['movers']} "
          f"unknown_catalyst={s['unknown_catalyst']}")
    return pkt


def brief(sealed: dict) -> str:
    """Delegates to THE Captain path: same prompt, same firewall, same artifact."""
    text = PS.captain_call(PS.brief_prompt(sealed))
    return PS.write_brief(sealed, text, PS.brief_verdict(text))


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    from apex.frontier.premarket import seal

    if a.once:
        pkt = absorb("manual")
        return 0

    from apex.frontier import premarket_runtime as RT
    et = RT.now_et
    schedule = list(PS.ABSORB_STAGES)
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
    target = et().normalize() + pd.Timedelta(hours=PS.SEAL_STAGE[1],
                                              minutes=PS.SEAL_STAGE[2])
    wait = (target - et()).total_seconds()
    if wait > 0:
        time.sleep(wait)
    if last is None:
        print("nothing to seal — every absorption failed (DEGRADED)")
        return 1
    last["as_of_time"] = str(RT.now_utc())
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
