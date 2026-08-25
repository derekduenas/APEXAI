"""V2 SHADOW FEEDER — append-only, strictly one-way.

    V1 sealed records  ──►  V2 observation ledgers
    V2 observation ledgers  ──X──  V1        (never, enforced by test)

The organism's three sockets were built with no feeder on purpose: the
scaffolds had to exist before Day-1, and feeding them before Day-1 was
frozen would have blurred which evidence came from where. Day-1 is now
frozen and corrected, so the sockets may begin recording.

EDGEFORGE DATA LAW. Only CORRECTED analytical records feed V2. A
superseded original is historical evidence, never a training label --
teaching the discovery layer that a pre-entry bar is legitimate MFE, or
that an after-hours print is a session close, would poison the first
dataset EdgeForge ever sees.

decision_power: NONE_SHADOW.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append       # noqa: E402
from apex.organism.cross_predator import (                  # noqa: E402
    SleeveObservation, assemble)
from apex.organism.path_intelligence import realized_path   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frozen", default="results/day1_frozen")
    ap.add_argument("--corrected", default="results/day1_corrected")
    ap.add_argument("--out", default="results/organism")
    a = ap.parse_args()
    frozen, corrected = Path(a.frozen), Path(a.corrected)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = [json.loads(l) for l in
            (frozen / "options_live_ledger.jsonl").read_text().splitlines()
            if l.strip()]
    cards = {r["symbol"]: r for r in rows
             if r.get("kind") == "options_live_card"}
    attacks = {r["symbol"]: r for r in rows
               if r.get("kind") == "options_live_attack"}
    outs = {r["expression"]: r for r in rows
            if r.get("kind") == "options_outcome"}
    rep = json.loads((corrected / "day1_correction_report.json").read_text())

    # ---- PATH: realized paths from CORRECTED records only
    n_path = 0
    for r in rep["records"]:
        sym, expr = r["symbol"], r["expression"]
        o = dict(outs[expr])
        o.update({"mfe": r["corrected_mfe"], "mae": r["corrected_mae"],
                  "underlying_return_pct": r["corrected_ur"],
                  "evidence_class": "PROSPECTIVE_PAPER_CORRECTED"})
        rp = realized_path(outcome_record=o,
                           declared_1R=attacks[sym].get("declared_1R"))
        rp.update({"symbol": sym, "session": "2026-08-24",
                   "source": "DAY1_CORRECTED",
                   "supersedes_original": True,
                   "thesis_path": r.get("thesis_path"),
                   "corrected_primary_class":
                       r.get("corrected_primary_class")})
        chain_append(out / "path_observations.jsonl", rp)
        n_path += 1

    # ---- CROSS-PREDATOR: what each sleeve saw, same session
    obs = []
    for sym, c in cards.items():
        obs.append(SleeveObservation(
            sleeve="options", subject=sym, T=c["T"],
            direction_view=c["direction"],
            state_summary={"expression": c["expression"],
                           "entry_quality": c.get("entry_quality")},
            evidence_class="PROSPECTIVE_PAPER",
            pedigree="DAY1_SEALED_CARD"))
    btc = [json.loads(l) for l in
           (frozen / "btc_paper_ledger.jsonl").read_text().splitlines()
           if l.strip()]
    bd = [r for r in btc if r.get("kind") == "btc_paper_decision"]
    if bd:
        last = bd[-1]
        obs.append(SleeveObservation(
            sleeve="btc", subject="PBTCUCZ50", T=last["T"],
            direction_view="NONE",
            state_summary={"cohort": last["cohort"],
                           "thesis_state": last["thesis_state"]},
            evidence_class="PROSPECTIVE_PAPER",
            pedigree="DAY1_SEALED_DECISION"))
    ctx = assemble(obs, T="2026-08-24")
    chain_append(out / "cross_predator_observations.jsonl",
                 {**ctx.as_record(), "session": "2026-08-24"})

    summary = {"kind": "v2_feed_summary", "session": "2026-08-24",
               "path_observations": n_path,
               "cross_predator_contexts": 1,
               "calibration_claims": 0,
               "calibration_note": "no incumbent emits a probabilistic "
                                   "claim yet; registering one now would "
                                   "be inventing a forecast to calibrate",
               "source_law": "CORRECTED records only; superseded "
                             "originals are evidence, never labels",
               "direction": "V1 -> V2 SHADOW (one-way)",
               "decision_power": "NONE_SHADOW"}
    chain_append(out / "v2_feed_log.jsonl", summary)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
