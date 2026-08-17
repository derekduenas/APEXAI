#!/usr/bin/env python
"""SENSORY LOOP — microscope + Captain Eyes, all session long. T1 item 2.

    python scripts/microscope_loop.py [--minutes 390] [--cadence 300]

Every `cadence` seconds during the session:
  1. read the official ledger (consumer only);
  2. if targets exist -> one microscope pass (child-session broker fetch);
  3. for any NEW playbook decision -> captain_eyes build + autonomous
     visual challenge.

Budgeted: at most MAX_CHILD_CALLS child sessions per day, counted in a
state file — the loop degrades to quiet logging when spent, it never
degrades to silence. Nothing here holds decision power; the frozen clock
neither knows nor cares whether this loop runs.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

LEDGER = Path("results/hunter/forward_ledger.jsonl")
STATE = Path("results/hunter/sensory_loop_state.json")
MAX_CHILD_CALLS = 80


def _state() -> dict:
    day = str(pd.Timestamp.now(tz="UTC").date())
    if STATE.exists():
        try:
            st = json.loads(STATE.read_text())
            if st.get("day") == day:
                return st
        except json.JSONDecodeError:
            pass
    return {"day": day, "child_calls": 0, "challenged": []}


def _save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    import os
    os.replace(tmp, STATE)


def _decisions() -> list:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") == "decision" and \
                not str(r.get("playbook_id", "")).startswith("BASELINE-"):
            out.append(r)
    return out


def tick(st: dict) -> None:
    now = pd.Timestamp.now(tz="UTC")
    decisions = _decisions()
    fresh = [d for d in decisions
             if d["decision_id"] not in st["challenged"]]
    budget_left = MAX_CHILD_CALLS - st["child_calls"]

    if decisions and budget_left > 0:
        r = subprocess.run([sys.executable, "scripts/microscope_pass.py"],
                           capture_output=True, text=True, timeout=600)
        st["child_calls"] += 1
        print(f"{now:%H:%M:%S} microscope: "
              f"{(r.stdout.strip().splitlines() or ['no output'])[-1]}")
    for d in fresh[:3]:
        if MAX_CHILD_CALLS - st["child_calls"] < 2:
            print(f"{now:%H:%M:%S} child budget spent — eyes deferred")
            break
        did = d["decision_id"]
        b = subprocess.run([sys.executable, "scripts/captain_eyes.py", did],
                           capture_output=True, text=True, timeout=600)
        eyes = Path(f"results/hunter/eyes/{did}_eyes.json")
        if eyes.exists():
            subprocess.run([sys.executable, "scripts/captain_eyes.py",
                            "--challenge", str(eyes)],
                           capture_output=True, text=True, timeout=600)
            st["child_calls"] += 2
            st["challenged"].append(did)
            print(f"{now:%H:%M:%S} EYES + CHALLENGE complete for {did}")
        else:
            print(f"{now:%H:%M:%S} eyes build failed for {did}: "
                  f"{(b.stdout or b.stderr)[-120:]}")
    if not decisions:
        print(f"{now:%H:%M:%S} no candidates yet — quiet "
              f"(budget {budget_left}/{MAX_CHILD_CALLS})")
    _save(st)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=390)
    ap.add_argument("--cadence", type=float, default=300)
    a = ap.parse_args()
    print("SENSORY LOOP — microscope + eyes, decision_power NONE")
    t_end = time.time() + a.minutes * 60
    while time.time() < t_end:
        try:
            tick(_state())
        except Exception as e:                              # noqa: BLE001
            print(f"tick failed (loop continues): {type(e).__name__}: {e}")
        time.sleep(a.cadence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
