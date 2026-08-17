#!/usr/bin/env python
"""CAPTAIN EYES — one command turns a persisted decision into everything
the visual challenger needs.

    python scripts/captain_eyes.py <decision_id> [--date 2026-08-17]
    python scripts/captain_eyes.py --latest

T1 item 4, the live wiring. For a decision already in the official
forward ledger this:

  1. assembles the CaptainMarketContextPacket from PERSISTED records
     (decision, world_state, assassin_review, capital_decision, bundle,
     catalyst state from the EDGAR archive);
  2. renders the as-of-T chart snapshot pair — one labeled for the
     operator, one symbol-withheld for the challenger — from the bars the
     decision itself saw (visible_bars at the decision's own t_utc; the
     renderer cannot be handed the future);
  3. writes packet + snapshot metadata next to the images.

The agent session then: Reads the challenger PNG, emits the structured
JSON, runs it through `apex.vision.challenger.parse` (which refuses
trading vocabulary), and appends the VisualChallenge to
results/hunter/visual_ledger.jsonl.

Rule 17: this script REFUSES replay/exploratory records. Prospective
imagery only — historical charts never reach the model.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

LEDGER = Path("results/hunter/forward_ledger.jsonl")
OUT = Path("results/hunter/eyes")


def _rows() -> list:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _find(rows, kind, decision_id=None):
    for r in reversed(rows):
        if r.get("kind") != kind:
            continue
        if decision_id and r.get("decision_id") != decision_id:
            continue
        return r
    return None


def build(decision_id: str | None, latest: bool) -> int:
    rows = _rows()
    decisions = [r for r in rows if r.get("kind") == "decision"
                 and not str(r.get("playbook_id", "")).startswith("BASELINE-")]
    if not decisions:
        print("no playbook decisions in the forward ledger yet — the Eyes "
              "have nothing to look at (correct before the first candidate)")
        return 2
    d = (decisions[-1] if latest
         else next((x for x in decisions
                    if x["decision_id"] == decision_id), None))
    if d is None:
        print(f"decision {decision_id!r} not found")
        return 2

    # RULE 17 TRIPWIRE: prospective imagery only
    if d.get("evidence_class") != "EODHD_FORWARD_OBSERVATION":
        raise RuntimeError(
            f"RULE 17: refusing to build challenger imagery for evidence "
            f"class {d.get('evidence_class')!r} — historical charts never "
            f"reach the model")

    t = pd.Timestamp(d["t_utc"])
    sym = d["symbol"]

    # bars the decision itself could see, through THE choke point
    from apex.hunter.chartstate import visible_bars
    from apex.intraday.eodhd import QuotaGovernor, fetch_intraday_chunk, \
        normalize_rows
    day = str(t.date())
    gov = QuotaGovernor(purpose="FORWARD")   # decision-adjacent, tiny spend
    raw, _src = fetch_intraday_chunk(sym, day, day, gov)
    bars = visible_bars(normalize_rows(raw or [], sym), t)
    ohlc = [(float(r.open), float(r.high), float(r.low), float(r.close))
            for r in bars.itertuples()]

    from apex.captain.context import assemble
    from apex.events.catalyst import catalyst_state
    cat = catalyst_state(sym, t, cik=None)   # bridge arrives later; honest
    packet = assemble(
        decision=d,
        world_record=_find(rows, "world_state"),
        assassin_record=_find(rows, "assassin_review", d["decision_id"]),
        capital_record=_find(rows, "capital_decision", d["decision_id"]),
        bundle_record=_find(rows, "forecast_bundle", d["decision_id"]),
        microscope={"status": "NOT_REQUESTED"},
        as_of=str(t))

    from apex.vision.render import snapshot
    OUT.mkdir(parents=True, exist_ok=True)
    vwap = (d.get("chart_state") or {}).get("vwap")
    labeled = snapshot(ohlc, OUT / f"{d['decision_id']}_operator.png",
                       symbol=sym, as_of=str(t), vwap=vwap,
                       levels=tuple(x for x in (d.get("stop"),
                                                d.get("target")) if x),
                       context_hash=packet.packet_hash())
    blind = snapshot(ohlc, OUT / f"{d['decision_id']}_challenger.png",
                     symbol=sym, as_of=str(t), vwap=vwap,
                     for_challenger=True,
                     context_hash=packet.packet_hash())

    bundle = {"decision_id": d["decision_id"], "symbol": sym,
              "as_of": str(t), "packet": packet.as_record(),
              "catalyst": cat.as_record(),
              "operator_snapshot": labeled,
              "challenger_snapshot": blind,
              "next_step": ("agent: Read the challenger PNG, emit the "
                            "structured JSON, parse() it, append to "
                            "results/hunter/visual_ledger.jsonl")}
    out = OUT / f"{d['decision_id']}_eyes.json"
    out.write_text(json.dumps(bundle, indent=2, default=str))
    print(f"eyes ready: {out}")
    print(f"  operator   {labeled['image_sha256'][:12]} "
          f"({labeled['bars_visible']} bars, future_bars=0)")
    print(f"  challenger {blind['image_sha256'][:12]} (symbol withheld)")
    print(f"  packet     {packet.health} | catalyst {cat.status}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("decision_id", nargs="?")
    ap.add_argument("--latest", action="store_true")
    a = ap.parse_args()
    if not a.decision_id and not a.latest:
        ap.error("give a decision_id or --latest")
    return build(a.decision_id, a.latest)


if __name__ == "__main__":
    raise SystemExit(main())
