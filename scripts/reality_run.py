#!/usr/bin/env python
"""Daily Reality Loop run: create predictions on live data, resolve, score.

    python scripts/reality_run.py

Runs after the nightly pull. On each LIVE grid formation date (strictly after
2026-06-30 -- same boundary as the paper track), the frozen producer set
states falsifiable claims; matured claims are resolved by their frozen rules;
the calibration report is rewritten from the full chained record.

Producer set (frozen; a new producer is a recorded amendment, and LLM
producers join HERE when they exist -- v2.0 rule 17: they are never
backtested, only run forward):
  gp_rank / h3_rank        relative claims from the two live signals
  blind_twin               same subjects, zero market data, p=0.5
  baseline_base_rate       SPY direction at the unconditional base rate
  baseline_momentum        SPY direction from trailing 60d sign

Subjects per date: the H1 top-decile and bottom-decile names (deterministic,
no sampling), peers = the whole eligible universe that date.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS.parent))
sys.path.insert(0, str(_SCRIPTS))

import pandas as pd  # noqa: E402

from paper_track import (HOLDOUT_END, PAPER_PANEL_START, build_paper_root,  # noqa: E402
                         composite_scores, locked_grid)

from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.experiments import apex003  # noqa: E402
from apex.reality import producers as P  # noqa: E402
from apex.reality.harness import PredictionLedger, resolve  # noqa: E402

LEDGER = PredictionLedger(Path("results/reality/predictions.jsonl"))
REPORT = Path("results/reality/calibration_report.json")                  # CALENDAR clock, canonical (A-011)
REPORT_LAKE_DIAGNOSTIC = Path("results/reality/calibration_report_lake_diagnostic.json")   # lake clock, diagnostic only


def progress(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def main() -> int:
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    root = build_paper_root()
    lake_through = json.loads((root / "MANIFEST.json").read_text())["lake_through"]
    panel, _ = build_production_panel(root, cfg, PAPER_PANEL_START, lake_through)
    output, _ = apex003.build_gp_output(panel, cfg, root)
    comp = composite_scores(output.scores.apex_score, cfg, panel)
    from apex.features.factory import build_features
    from apex.features.registry import built_specs
    btm_spec = next(x for x in built_specs() if x.feature_id == "val_book_to_market")
    btm_vals = build_features(root, panel, (btm_spec,))[0]["val_book_to_market"]
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    LEDGER.verify()
    seen = {(p["producer"], p["trade_date"], p["subject"])
            for p in LEDGER.predictions()}
    seen |= {("llm_pair", p["producer"].split("/")[1], p["trade_date"], p["subject"])
             for p in LEDGER.predictions() if p["producer"].startswith("llm_")}
    grid = [d for d in locked_grid(root, cfg)
            if d > HOLDOUT_END and d in panel.dates]

    spy = pd.read_csv(root / "raw" / "SFP" / "SFP_SPY.csv",
                      usecols=["date", "closeadj"], parse_dates=["date"]
                      ).set_index("date")["closeadj"].astype(float).sort_index()
    spy = spy[~spy.index.duplicated()]
    prices = panel.close_adj.copy()
    prices["SPY"] = spy.reindex(prices.index)

    created = 0
    for d in grid:
        td = str(d.date())
        elig = output.universe.eligible.loc[d]
        deciles = output.scores.decile.loc[d].where(elig)
        gp_pct = output.scores.apex_score.loc[d].where(elig) / 100.0  # score 100 = top
        h3_pct = comp.loc[d].where(elig)
        subjects = sorted(deciles[(deciles == 1) | (deciles == 10)].index)
        peers = sorted(deciles.dropna().index)
        pos = panel.dates.searchsorted(d)
        r60 = (panel.close_adj.iloc[pos] / panel.close_adj.iloc[max(0, pos - 60)]
               - 1).where(elig)
        batch = (
            P.rank_producer("gp_rank", td, now, gp_pct, subjects, peers)
            + P.rank_producer("h3_rank", td, now, h3_pct.fillna(0.5), subjects, peers)
            + P.blind_producer("blind_twin", td, now, subjects, peers)
            + P.momentum_rank_producer(td, now, r60.fillna(0.0), subjects, peers)
        )
        # LLM pair on a FROZEN deterministic 20-name subset (10 top / 10
        # bottom decile, ordered by security_id): the Group B clock. Never
        # backtested (rule 17); pairs only, so the full/stripped comparison
        # stays unbiased. Skipped cleanly when the CLI is unavailable.
        # RULE 17 GUARD: an LLM prediction may only be created while its
        # outcome does NOT yet exist. A pair minted for a grid date whose
        # horizon has already elapsed would be a backdated claim scored as
        # forward evidence. Mechanical producers are deterministic functions
        # of as-of data (reproducible, so backfill is defensible and is
        # labeled by created_at); the LLM's never is.
        days_elapsed = int(panel.dates.searchsorted(pd.Timestamp(lake_through),
                                                    side="right") - 1 - pos)
        import shutil as _sh
        if (_sh.which("claude") and "--no-llm" not in sys.argv
                and days_elapsed < P.HORIZON):
            from apex.reality.llm_producer import MODELS, llm_predictions
            top10 = sorted(deciles[deciles == 1].index)[:10]
            bot10 = sorted(deciles[deciles == 10].index)[:10]
            for s, model in [(s, m) for s in top10 + bot10 for m in MODELS]:
                if ("llm_pair", model, td, s) in seen:
                    continue
                r20 = float(panel.close_adj.iloc[pos][s]
                            / panel.close_adj.iloc[max(0, pos - 20)][s] - 1)
                r120 = float(panel.close_adj.iloc[pos][s]
                             / panel.close_adj.iloc[max(0, pos - 120)][s] - 1)
                ctx = {"security_id": s, "ticker": s, "trade_date": td,
                       "close": float(panel.close_unadj.loc[d, s]),
                       "mcap_m": float(panel.market_cap.loc[d, s] / 1e6),
                       "r20": r20, "r60": float(r60[s]), "r120": r120,
                       "gp_assets": float(output.signal.loc[d, s]),
                       "btm": float(btm_vals.loc[d, s])}
                if any(v != v for v in ctx.values() if isinstance(v, float)):
                    continue          # a NaN in the context would prompt "nan"
                pair = llm_predictions(ctx, peers, now, model)
                for pred in pair:
                    LEDGER.append_prediction(pred)
                    created += 1
                if pair:
                    seen.add(("llm_pair", model, td, s))
        if d in spy.index:
            past = spy[spy.index <= d]
            if len(past) > 60:
                batch.append(P.base_rate_producer(td, now, "SPY"))
                batch.append(P.momentum_producer(
                    td, now, "SPY", float(past.iloc[-1] / past.iloc[-61] - 1)))
        for pred in batch:
            if (pred.producer, pred.trade_date, pred.subject) not in seen:
                LEDGER.append_prediction(pred)
                seen.add((pred.producer, pred.trade_date, pred.subject))
                created += 1

    resolved = 0
    resolutions = LEDGER.resolutions()
    for p in LEDGER.predictions():
        if p["prediction_id"] in resolutions:
            continue
        outcome = resolve(prices, p)
        if outcome is not None:
            LEDGER.append_resolution(p["prediction_id"], outcome, now)
            resolved += 1

    from apex.reality.harness import score_by_producer
    # CLOCK SEMANTICS (CONVENTIONS A-011, 2026-09-11): CALENDAR IS CANONICAL, LAKE IS DIAGNOSTIC. A due date must be
    # measured by a clock the system cannot influence. The lake clock is system-controlled: under it a prediction never
    # comes due if the pull stops, so the machine avoids every penalty by going quiet.
    calendar_through = dt.datetime.now(dt.timezone.utc).date().isoformat()
    chain_entries = LEDGER.verify()
    report = {
        "generated_at": now, "clock": "CALENDAR_CANONICAL", "data_through": calendar_through, "lake_through": lake_through,
        "clock_rule": ("CONVENTIONS A-011: past-due unresolved predictions score as failure against the CALENDAR; the lake "
                       "clock is reported separately as a diagnostic and never decides a penalty"),
        "chain_entries": chain_entries,
        "producers": score_by_producer(LEDGER.predictions(), LEDGER.resolutions(), calendar_through),
    }
    diagnostic = {
        "generated_at": now, "clock": "LAKE_DIAGNOSTIC", "data_through": lake_through, "lake_through": lake_through,
        "label": ("DIAGNOSTIC ONLY, NOT A SCORING RECORD: scored against the lake clock, which the system controls. It "
                  "shows what the producers look like on the data actually held; it cannot be cited for standing."),
        "chain_entries": chain_entries,
        "producers": score_by_producer(LEDGER.predictions(), LEDGER.resolutions(), lake_through),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    REPORT_LAKE_DIAGNOSTIC.write_text(json.dumps(diagnostic, indent=2, sort_keys=True) + "\n")
    print(f"created {created} predictions, resolved {resolved}; "
          f"chain {report['chain_entries']} entries verified; calendar {calendar_through}, lake {lake_through}")
    for name, s in report["producers"].items():
        print(f"  {name:<22} n={s['n_scored']:<5} dates={s['n_effective_dates']:<3} brier={s['brier']:.4f} "
              f"rel={s['reliability']:.4f} res={s['resolution']:.4f} "
              f"penalised={s['n_penalised_unresolved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
