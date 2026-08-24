"""BTC PAPER_EXPLORATORY COMBAT LOOP.

Authority granted 2026-08-24: OBSERVE -> PAPER_EXPLORATORY. Not
PAPER_AUTHORIZED. Live capital LOCKED. No order ever exists here.

    derivatives ledger ─┐
                        ├─> Inputs -> participant state -> forced-action
    L2 book ledger ─────┘        thesis -> attack geometry -> seal ->
                                 paper fill -> resolve -> outcome

TWO MODES, TWO EVIDENCE CLASSES -- never conflated:

  --follow (the combat loop)      evidence_class = PROSPECTIVE_PAPER
      Each decision is made at wall-clock window close, sealed BEFORE
      its future exists. This is the only mode that produces
      prospective evidence.

  batch (default, plumbing proof) evidence_class =
      HISTORICAL_COMPOSITION_PROOF. It composes over windows whose
      futures are already on disk. It proves the machinery; it may
      never be cited as prospective evidence, and its records say so.

COHORT LAW (operator directive). Every window lands in exactly one
cohort -- NONE_OBSERVED, SUSCEPTIBLE_NOT_TRIGGERED, NEAR_MISS,
REFUSED, ATTACK_READY -- because for a rare-asymmetry Predator the
refusal cohorts ARE the dataset: they are how we will learn whether
SUSCEPTIBLE precedes real events, whether the trigger is early or
late, and whether refusals save capital.

NO TRADE QUOTA. A quiet market should remain quiet. The forced-flow
logic may not be loosened because attack frequency is low.

CROSS-VENUE PROXY, DECLARED. Thesis inputs come from Deribit
(OI_REALTIME) as a NAMED PROXY for the BTC leveraged complex.
Bitnomial's daily OI remains structurally refused for intraday claims,
and Deribit positioning is never presented as Bitnomial positioning.

decision_power: NONE_PAPER.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.btc_sleeve import (                              # noqa: E402
    attack_geometry, forced_action, participant_state)
from apex.btc_sleeve.paper_execution import (              # noqa: E402
    resolve, simulate_entry)
from apex.btc_sleeve.semantics import OI_REALTIME          # noqa: E402
from apex.governance.chain_ledger import chain_append      # noqa: E402
from apex.governance.verification import stamp             # noqa: E402
from apex.ops.heartbeat import Heartbeat                   # noqa: E402
from apex.predators.options.replay import (                # noqa: E402
    seal_before_card)

CODE_PATHS = [
    "scripts/btc_paper_session.py",
    "apex/btc_sleeve/participant_state.py",
    "apex/btc_sleeve/forced_action.py",
    "apex/btc_sleeve/attack_geometry.py",
    "apex/btc_sleeve/paper_execution.py",
]

COHORTS = ("NONE_OBSERVED", "SUSCEPTIBLE_NOT_TRIGGERED", "NEAR_MISS",
           "REFUSED", "ATTACK_READY")

PROTOCOL = {
    "kind": "btc_paper_preregistration",
    "protocol_version": "btc_paper_v2_2026_08_24",
    "authority": "PAPER_EXPLORATORY",
    "authority_granted": "2026-08-24 operator review -- machinery "
                         "trusted; profitability unproven and unclaimed",
    "decision_power": "NONE_PAPER",
    "thesis_inputs": "DERIBIT (OI_REALTIME) as a NAMED PROXY for the "
                     "BTC leveraged complex; never presented as "
                     "Bitnomial positioning",
    "attack_venue": "BITNOMIAL PBTCUCZ50 (the commissioned L2 book)",
    "window_minutes": 15,
    "exit_rule": "invalidation touch, else target touch, else horizon "
                 "= close of the following window; ties resolve "
                 "AGAINST us; gaps realize where the book actually was",
    "risk_basis": "PLANNED_INVALIDATION",
    "sizing": "1 contract, capped by resting touch liquidity",
    "trade_quota": "NONE -- a quiet market should remain quiet",
    "tail_objective": "rare asymmetry: tight invalidation + forced "
                      "participants + favorable liquidity + small "
                      "footprint + large favorable tail. Never "
                      "artificial activity.",
    "live_capital": "LOCKED",
}


# ---------------------------------------------------------------- data

def _rows(path: Path, kinds: set) -> list:
    out = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") in kinds:
            out.append(r)
    return out


def _deribit_series(deriv_rows: list) -> list:
    out = []
    for r in deriv_rows:
        d = (r.get("venues") or {}).get("DERIBIT") or {}
        oi, f = d.get("open_interest"), d.get("funding_current")
        if oi is not None:
            out.append({"t": r["known_from"], "oi": float(oi),
                        "funding": (float(f) if f is not None else None)})
    return out


def _pct(new, old):
    if old in (None, 0) or new is None:
        return None
    return (new / old - 1.0) * 100.0


def build_inputs(window: list, tops: list, prior_tops: list,
                 horizon_min: float) -> participant_state.Inputs:
    oi_ch = _pct(window[-1]["oi"], window[0]["oi"]) if len(window) >= 2 \
        else None
    funding = window[-1].get("funding") if window else None
    f_ann = funding * 3 * 365 if funding is not None else None

    mids = [(t["best_bid_raw"] + t["best_ask_raw"]) / 2 for t in tops
            if t.get("best_bid_raw") and t.get("best_ask_raw")]
    px_ch = _pct(mids[-1], mids[0]) if len(mids) >= 2 else None

    depth = [t.get("depth_bid_levels", 0) + t.get("depth_ask_levels", 0)
             for t in tops]
    pdepth = [t.get("depth_bid_levels", 0) + t.get("depth_ask_levels", 0)
              for t in prior_tops]
    d_ch = _pct(sum(depth) / len(depth) if depth else None,
                sum(pdepth) / len(pdepth) if pdepth else None)

    return participant_state.Inputs(
        price_change_pct=px_ch, oi_change_pct=oi_ch,
        oi_cadence=OI_REALTIME, oi_age_s=0.0,
        funding_rate_annualized=f_ann,
        book_depth_change_pct=d_ch,
        book_quality=(tops[-1].get("book_quality", "UNKNOWN")
                      if tops else "UNKNOWN"),
        horizon_minutes=horizon_min)


def _cohort(thesis, geo) -> str:
    """Exactly one cohort per window, structural before quality."""
    if geo.attackable:
        return "ATTACK_READY"
    if thesis.state == "SUSCEPTIBLE_NOT_TRIGGERED":
        return "SUSCEPTIBLE_NOT_TRIGGERED"
    if geo.thesis_credible is True:
        # the thesis qualified; only the location/execution blocked it
        return "REFUSED" if geo.structural_wounds else "NEAR_MISS"
    return "NONE_OBSERVED"


# ------------------------------------------------------------ decision

def decide_window(*, hi, window, tops, prior_tops, prior_window,
                  horizon_min: float, evidence_class: str,
                  ledger: Path) -> dict:
    """One window: interpret, judge, and (only if earned) seal + fill.

    Preserves the full context the combat law names -- the readings,
    the competing explanations, the thesis, the geometry -- because a
    cohort we cannot later interrogate teaches nothing."""
    inp = build_inputs(window, tops, prior_tops, horizon_min)
    prior_in = build_inputs(prior_window, prior_tops, [], horizon_min) \
        if len(prior_window) >= 2 else None
    ps = participant_state.interpret(symbol="PBTCUCZ50", T=str(hi),
                                     inputs=inp)
    thesis = forced_action.assess(
        participant_state=ps, inputs=inp,
        prior_oi_change_pct=(prior_in.oi_change_pct if prior_in
                             else None))

    mids = [(t["best_bid_raw"] + t["best_ask_raw"]) / 2
            for t in tops if t.get("best_bid_raw")]
    atr = (max(mids) - min(mids)) if mids else None
    ref = mids[-1] if mids else None
    extreme = (min(mids) if thesis.pressured_side == "LONGS"
               else max(mids)) if mids else None
    geo = attack_geometry.assess(
        subject="PBTCUCZ50", T=str(hi), thesis=thesis,
        book_top=tops[-1] if tops else None, atr=atr,
        reference_price=ref, recent_extreme=extreme, intended_size=1)

    rec = {"kind": "btc_paper_decision", "T": str(hi),
           "cohort": _cohort(thesis, geo),
           "evidence_class": evidence_class,
           "thesis_state": thesis.state,
           "pressured_side": thesis.pressured_side,
           "attackable": geo.attackable,
           "structural_wounds": list(geo.structural_wounds),
           "wounds": list(geo.wounds),
           "signal_half_life": "NOT_ESTIMABLE",
           "oi_pedigree": PROTOCOL["thesis_inputs"],
           # full context, preserved not summarized
           "participant_state": ps.as_record(),
           "forced_action": thesis.as_record(),
           "attack_geometry": geo.as_record()}

    fill = None
    if geo.attackable:
        card = seal_before_card({
            "protocol_version": PROTOCOL["protocol_version"],
            "subject": "PBTCUCZ50", "T": str(hi),
            "direction": geo.direction,
            "invalidation": geo.invalidation, "target": geo.target,
            "thesis_state": thesis.state,
            "evidence_class": evidence_class})
        fill = simulate_entry(geometry=geo, T=str(hi),
                              sealed_card_hash=card["card_hash"])
        chain_append(ledger, {"kind": "btc_paper_card", **card})
        chain_append(ledger, fill.as_record())
        rec.update({"card_hash": card["card_hash"],
                    "target": geo.target})
    chain_append(ledger, rec)
    return {"rec": rec, "fill": fill, "geo": geo, "T": hi}


def resolve_attack(open_attack: dict, future_tops: list,
                   ledger: Path) -> dict:
    fill, geo = open_attack["fill"], open_attack["geo"]
    out = resolve(fill=fill, sealed_card_hash=fill.sealed_card_hash,
                  path=future_tops, target=geo.target)
    chain_append(ledger, out.as_record())
    return {"T": str(open_attack["T"]), "pnl_usd": out.pnl_usd,
            "r": out.r_multiple, "exit_reason": out.exit_reason,
            "identity_holds": out.friction_identity_holds}


# --------------------------------------------------------------- modes

def _load(a):
    tops = _rows(Path(a.book_ledger), {"ws_book_top_sample"})
    deriv = _deribit_series(_rows(Path(a.deriv_ledger),
                                  {"btc_derivatives_poll"}))
    return tops, deriv


def _sel(rows, key, lo, hi):
    import pandas as pd
    return [r for r in rows if lo <= pd.Timestamp(r[key]) < hi]


def run_batch(a, ledger: Path) -> int:
    """Plumbing proof over captured windows. NOT prospective."""
    import pandas as pd
    ec = "HISTORICAL_COMPOSITION_PROOF"
    tops, deriv = _load(a)
    print(f"real rows: {len(tops)} book tops, {len(deriv)} Deribit "
          f"polls [{ec}]")
    if not tops or len(deriv) < 3:
        print("INSUFFICIENT_REAL_DATA")
        return 1
    t0 = max(pd.Timestamp(tops[0]["known_from"]),
             pd.Timestamp(deriv[0]["t"]))
    t1 = min(pd.Timestamp(tops[-1]["known_from"]),
             pd.Timestamp(deriv[-1]["t"]))
    step = pd.Timedelta(minutes=a.window_min)
    edges = list(pd.date_range(t0, t1, freq=step))
    counts, resolved = {}, []
    for i in range(1, len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        w = _sel(deriv, "t", lo, hi)
        pw = _sel(deriv, "t", edges[i - 1], lo)
        wt = _sel(tops, "known_from", lo, hi)
        pt = _sel(tops, "known_from", edges[i - 1], lo)
        if len(w) < 2 or len(wt) < 2:
            counts["INSUFFICIENT_WINDOW_DATA"] = \
                counts.get("INSUFFICIENT_WINDOW_DATA", 0) + 1
            continue
        d = decide_window(hi=hi, window=w, tops=wt, prior_tops=pt,
                          prior_window=pw, horizon_min=a.window_min,
                          evidence_class=ec, ledger=ledger)
        counts[d["rec"]["cohort"]] = counts.get(d["rec"]["cohort"], 0) + 1
        if d["fill"] is not None:
            resolved.append(resolve_attack(
                d, _sel(tops, "known_from", hi, hi + step), ledger))
    summary = {"kind": "btc_paper_session_summary", "mode": "BATCH",
               "evidence_class": ec, "cohorts": counts,
               "attacks_resolved": resolved,
               "law": "this composition proves machinery; it may never "
                      "be cited as prospective evidence"}
    chain_append(ledger, summary)
    Path(a.out).write_text(json.dumps(stamp(
        {"summary": summary}, CODE_PATHS), indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))
    return 0


def run_follow(a, ledger: Path) -> int:
    """THE COMBAT LOOP. Decisions at wall-clock window close, sealed
    before their futures exist -- prospective by construction."""
    import pandas as pd
    ec = "PROSPECTIVE_PAPER"
    step = pd.Timedelta(minutes=a.window_min)
    beat = Heartbeat(service="btc-paper",
                     authority="PAPER_EXPLORATORY",
                     notes={"mode": "FOLLOW", "evidence_class": ec})
    beat.beat()
    print(f"combat loop up: {a.window_min}m windows, {ec}", flush=True)

    last_edge = None
    open_attacks: list = []
    cohort_counts: dict = {}
    while True:
        now = pd.Timestamp(datetime.now(timezone.utc))
        edge = now.floor(f"{int(a.window_min)}min")
        if last_edge is not None and edge > last_edge:
            tops, deriv = _load(a)
            lo, hi = edge - step, edge
            w = _sel(deriv, "t", lo, hi)
            pw = _sel(deriv, "t", lo - step, lo)
            wt = _sel(tops, "known_from", lo, hi)
            pt = _sel(tops, "known_from", lo - step, lo)

            # resolve attacks whose horizon has now closed
            still = []
            for oa in open_attacks:
                if edge >= oa["T"] + step:
                    r = resolve_attack(oa, _sel(
                        tops, "known_from", oa["T"], oa["T"] + step),
                        ledger)
                    print(f"  resolved {r['exit_reason']} "
                          f"pnl={r['pnl_usd']}", flush=True)
                    beat.work(f"resolved {r['exit_reason']}")
                else:
                    still.append(oa)
            open_attacks = still

            if len(w) >= 2 and len(wt) >= 2:
                d = decide_window(
                    hi=hi, window=w, tops=wt, prior_tops=pt,
                    prior_window=pw, horizon_min=a.window_min,
                    evidence_class=ec, ledger=ledger)
                c = d["rec"]["cohort"]
                cohort_counts[c] = cohort_counts.get(c, 0) + 1
                if d["fill"] is not None:
                    open_attacks.append(d)
                beat.work(f"{hi} {c}",
                          backlog=len(open_attacks))
                print(f"  {hi} {c}", flush=True)
            else:
                beat.work(f"{hi} INSUFFICIENT_WINDOW_DATA")
                print(f"  {hi} INSUFFICIENT_WINDOW_DATA "
                      f"(deriv={len(w)} tops={len(wt)})", flush=True)
        last_edge = edge
        beat.beat()
        time.sleep(30)
    return 0                                             # unreachable


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-ledger",
                    default="results/btc/ws_book_ledger.g2.jsonl")
    ap.add_argument("--deriv-ledger",
                    default="results/btc/derivatives_ledger.jsonl")
    ap.add_argument("--ledger", default="results/btc/paper_ledger.jsonl")
    ap.add_argument("--out", default="results/btc/paper_session.json")
    ap.add_argument("--window-min", type=float, default=15.0)
    ap.add_argument("--follow", action="store_true",
                    help="run the prospective combat loop")
    a = ap.parse_args()
    ledger = Path(a.ledger)
    chain_append(ledger, {**PROTOCOL,
                          "mode": "FOLLOW" if a.follow else "BATCH"})
    print(f"protocol pre-registered: {PROTOCOL['protocol_version']} "
          f"authority={PROTOCOL['authority']}")
    return run_follow(a, ledger) if a.follow else run_batch(a, ledger)


if __name__ == "__main__":
    raise SystemExit(main())
