"""BTC PAPER SESSION — the full PredatorOpportunity path, composed.

    derivatives ledger ─┐
                        ├─> Inputs -> participant state -> forced-action
    L2 book ledger ─────┘        thesis -> attack geometry -> seal ->
                                 paper fill -> resolve -> outcome

Runs against the REAL captured ledgers on this host. Exists to prove
the composed plumbing before the PAPER_EXPLORATORY review -- not to
prove an edge, and nothing here may be read as one.

CROSS-VENUE PROXY, DECLARED. The attack venue is Bitnomial (that is
where the commissioned L2 book lives), but Bitnomial publishes open
interest DAILY -- structurally unable to support an intraday
positioning claim, and the participant stack correctly refuses it.
Deribit's OI is measured REALTIME, so the thesis inputs come from
Deribit AS A NAMED PROXY for the BTC leveraged complex. That proxy
status is stamped into every record: Deribit positioning describes
Deribit participants, and treating it as Bitnomial's would be the
identification error L3 exists to refuse.

decision_power: NONE_PAPER. Authority OBSERVE (BTC paper review not
yet passed).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.btc_sleeve import (                              # noqa: E402
    attack_geometry, forced_action, participant_state)
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

PROTOCOL = {
    "kind": "btc_paper_preregistration",
    "protocol_version": "btc_paper_v1_2026_08_24",
    "authority": "OBSERVE",
    "decision_power": "NONE_PAPER",
    "thesis_inputs": "DERIBIT (OI_REALTIME) as a NAMED PROXY for the "
                     "BTC leveraged complex; never presented as "
                     "Bitnomial positioning",
    "attack_venue": "BITNOMIAL PBTCUCZ50 (the commissioned L2 book)",
    "window_minutes": 15,
    "exit_rule": "invalidation touch, else horizon = end of the next "
                 "window; ties resolve AGAINST us",
    "risk_basis": "PLANNED_INVALIDATION",
    "sizing": "1 contract, capped by resting touch liquidity",
    "evidence_class": "PROSPECTIVE_PAPER",
    "live_capital": "LOCKED",
}


def _rows(path: Path, kinds: set) -> list:
    out = []
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
    """(known_from, oi, funding) from every poll that carried Deribit."""
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


def build_inputs(window: list, prior: list, tops: list,
                 prior_tops: list, horizon_min: float
                 ) -> participant_state.Inputs:
    """One window's Inputs, from real rows, refusing where data is
    absent rather than defaulting."""
    oi_ch = _pct(window[-1]["oi"], window[0]["oi"]) if len(window) >= 2 \
        else None
    funding = window[-1].get("funding")
    f_ann = funding * 3 * 365 if funding is not None else None  # 8h->yr

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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-ledger", default="results/btc/ws_book_ledger.g2.jsonl")
    ap.add_argument("--deriv-ledger", default="results/btc/derivatives_ledger.jsonl")
    ap.add_argument("--ledger", default="results/btc/paper_ledger.jsonl")
    ap.add_argument("--out", default="results/btc/paper_session.json")
    ap.add_argument("--window-min", type=float, default=15.0)
    a = ap.parse_args()

    import pandas as pd

    beat = Heartbeat(service="btc-paper", authority="OBSERVE")
    ledger = Path(a.ledger)
    chain_append(ledger, PROTOCOL)
    print(f"protocol pre-registered: {PROTOCOL['protocol_version']}")

    tops = _rows(Path(a.book_ledger), {"ws_book_top_sample"})
    deriv = _deribit_series(_rows(Path(a.deriv_ledger),
                                  {"btc_derivatives_poll"}))
    print(f"real rows: {len(tops)} book tops, {len(deriv)} Deribit polls")
    if not tops or len(deriv) < 3:
        print("INSUFFICIENT_REAL_DATA -- refusing to fabricate a session")
        return 1

    # align on overlapping time, bucket into windows
    t0 = max(pd.Timestamp(tops[0]["known_from"]),
             pd.Timestamp(deriv[0]["t"]))
    t1 = min(pd.Timestamp(tops[-1]["known_from"]),
             pd.Timestamp(deriv[-1]["t"]))
    if t1 <= t0:
        print("NO_TEMPORAL_OVERLAP between book and derivatives capture")
        return 1
    step = pd.Timedelta(minutes=a.window_min)
    edges = list(pd.date_range(t0, t1, freq=step))
    print(f"overlap {t0} -> {t1}: {max(0, len(edges) - 2)} decision "
          f"windows")

    def _sel(rows, key, lo, hi):
        return [r for r in rows
                if lo <= pd.Timestamp(r[key]) < hi]

    counts, decisions = {}, []
    for i in range(1, len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        window = _sel(deriv, "t", lo, hi)
        prior_w = _sel(deriv, "t", edges[i - 1], lo)
        wtops = _sel(tops, "known_from", lo, hi)
        ptops = _sel(tops, "known_from", edges[i - 1], lo)
        if len(window) < 2 or len(wtops) < 2:
            counts["INSUFFICIENT_WINDOW_DATA"] = \
                counts.get("INSUFFICIENT_WINDOW_DATA", 0) + 1
            continue

        inp = build_inputs(window, prior_w, wtops, ptops, a.window_min)
        prior_in = build_inputs(prior_w, [], ptops, [], a.window_min) \
            if len(prior_w) >= 2 else None
        ps = participant_state.interpret(
            symbol="PBTCUCZ50", T=str(hi), inputs=inp)
        thesis = forced_action.assess(
            participant_state=ps, inputs=inp,
            prior_oi_change_pct=(prior_in.oi_change_pct
                                 if prior_in else None))
        counts[thesis.state] = counts.get(thesis.state, 0) + 1

        mids = [(t["best_bid_raw"] + t["best_ask_raw"]) / 2
                for t in wtops if t.get("best_bid_raw")]
        atr = (max(mids) - min(mids)) if mids else None
        sign_ref = mids[-1] if mids else None
        extreme = (min(mids) if thesis.pressured_side == "LONGS"
                   else max(mids)) if mids else None
        geo = attack_geometry.assess(
            subject="PBTCUCZ50", T=str(hi), thesis=thesis,
            book_top=wtops[-1], atr=atr, reference_price=sign_ref,
            recent_extreme=extreme, intended_size=1)
        beat.work(f"window {i}: {thesis.state}")

        rec = {"kind": "btc_paper_decision", "T": str(hi),
               "thesis_state": thesis.state,
               "pressured_side": thesis.pressured_side,
               "attackable": geo.attackable,
               "structural_wounds": list(geo.structural_wounds),
               "wounds": list(geo.wounds),
               "proxy_note": PROTOCOL["thesis_inputs"]}

        if geo.attackable:
            from apex.btc_sleeve.paper_execution import (
                resolve, simulate_entry)
            card = seal_before_card({
                "protocol_version": PROTOCOL["protocol_version"],
                "subject": "PBTCUCZ50", "T": str(hi),
                "direction": geo.direction,
                "invalidation": geo.invalidation,
                "target": geo.target,
                "thesis_state": thesis.state})
            fill = simulate_entry(geometry=geo, T=str(hi),
                                  sealed_card_hash=card["card_hash"])
            future = _sel(tops, "known_from", hi, hi + step)
            out = resolve(fill=fill, sealed_card_hash=card["card_hash"],
                          path=future, target=geo.target)
            chain_append(ledger, {"kind": "btc_paper_card", **card})
            chain_append(ledger, fill.as_record())
            chain_append(ledger, out.as_record())
            rec.update({"card_hash": card["card_hash"],
                        "pnl_usd": out.pnl_usd, "r": out.r_multiple,
                        "exit_reason": out.exit_reason,
                        "identity_holds": out.friction_identity_holds})
        decisions.append(rec)
        chain_append(ledger, rec)

    summary = {"kind": "btc_paper_session_summary",
               "windows": len(decisions),
               "thesis_states": counts,
               "attacks": sum(1 for d in decisions if d.get("card_hash")),
               "refusal_law": "a session of honest refusals proves the "
                              "plumbing exactly as well as attacks do",
               "evidence_class": "PROSPECTIVE_PAPER"}
    chain_append(ledger, summary)
    Path(a.out).write_text(json.dumps(
        stamp({"summary": summary, "decisions": decisions}, CODE_PATHS),
        indent=1, default=str))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
