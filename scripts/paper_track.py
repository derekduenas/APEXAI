#!/usr/bin/env python
"""LIVE PAPER TRACK: continuous zero-credit evaluation on the nightly lake.

    python scripts/paper_track.py            # mark portfolios to latest lake data

WHAT THIS IS
------------
The final layer of the loop: discover -> validate -> test extraction ->
OBSERVE LIVE. Every candidate portfolio is formed and marked ONLY on live-lake
dates (strictly after 2026-06-30, where the frozen snapshot and the sealed
holdout both end), so the paper record is genuine out-of-sample by
construction -- data that did not exist when any experiment was designed.
It consumes no credits, produces no verdicts, and cannot: the merged data
root it builds carries a dev-namespace fingerprint, so every confirmatory
gate refuses it structurally.

THE PORTFOLIO SET IS FROZEN HERE (denominator recorded, all reported):

  H1-A     GP top-decile equal-weight        (the validated signal, baseline)
  H1-B     GP top-3-deciles equal-weight
  H1-E     H1-B with hold-to-decile-5 banding (best in-sample net, +0.45%)
  H3-QV-T  quality-value composite, top decile EW   (the unspent hypothesis)
  H3-QV-B  quality-value composite, top-3 deciles EW
  CONTROL  eligible-universe equal-weight    (must track ~zero excess; a
                                              control that can fail)

H3's composite is the REGISTERED packet definition: equal pre-committed rank
weights on val_book_to_market + prof_gross_profitability, higher = better.
Nothing here is fitted; adding a portfolio later is a recorded amendment.

HOLDOUT GUARD: this script refuses to compute any portfolio return dated on
or before the holdout end. Formation uses trailing history (prices inside
the sealed window are inputs to eligibility, which deployment necessarily
requires); RETURNS are only ever taken on lake dates.

Rebalance: every 3rd grid formation date (~quarterly), same as the study.
State: results/paper/positions.json (current holdings per portfolio) and
results/paper/paper_ledger.jsonl (hash-chained marks, append-only).
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nightly_pull import _chain_append  # noqa: E402  (same chained-log discipline)

from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.dev.namespace import dev_fingerprint  # noqa: E402
from apex.experiments import apex003  # noqa: E402
from apex.features.factory import build_features  # noqa: E402
from apex.features.registry import built_specs  # noqa: E402

SNAPSHOT = Path("data/snapshots/sharadar/current")
LAKE = Path("data/live/sharadar")
PAPER_ROOT = Path("data/live/paper_root")
STATE_DIR = Path("results/paper")
HOLDOUT_END = pd.Timestamp("2026-06-30")   # protocol section 7; the seal
PORTFOLIOS = ("H1-A", "H1-B", "H1-E", "H3-QV-T", "H3-QV-B", "CONTROL")
REBALANCE_EVERY = 3                        # grid steps (~quarterly)

# The tracker loads a SHORT panel -- the full 22-year lake was OOM-killed on
# this machine (exit 137, 2026-08-14), and live marking only needs enough
# trailing history for the 252-day universe filters. The LOCKED grid is still
# reproduced exactly: its anchor counts trading days from the 2004 lake
# start, and the merged SFP/SPY series spans the whole lake, so grid
# membership is derived from SPY's trading-day index, never re-anchored.
PAPER_PANEL_START = "2025-01-01"


def locked_grid(root: Path, cfg) -> pd.DatetimeIndex:
    """The section-9 grid, derived from the full-lake SPY calendar."""
    spy = pd.read_csv(root / "raw" / "SFP" / "SFP_SPY.csv", usecols=["date"])
    days = pd.DatetimeIndex(sorted(pd.to_datetime(spy["date"]).unique()))
    anchor = int(cfg.get("calendar.anchor_trading_days"))
    step = int(cfg.get("schedule.rebalance_step_days"))
    return days[anchor::step]


def progress(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def build_paper_root() -> Path:
    """Merged read-only view: frozen snapshot + live lake, dev-fingerprinted.

    Symlinks for the dated tables (the loader globs raw/<T>/*.csv); TICKERS
    from the single freshest source; SFP_SPY.csv materialised as the concat
    of the snapshot file and every lake SFP slice (the loader reads that one
    path directly).
    """
    if not (LAKE / "MANIFEST.json").exists():
        raise SystemExit(
            "live lake is empty -- arm the nightly pull first "
            "(ops/nightly_pull.sh header has the two commands)")
    import shutil
    if PAPER_ROOT.exists():
        shutil.rmtree(PAPER_ROOT)
    for table in ("SEP", "DAILY", "ACTIONS", "SF1"):
        d = PAPER_ROOT / "raw" / table
        d.mkdir(parents=True)
        for src_root in (SNAPSHOT, LAKE):
            for f in sorted((src_root / "raw" / table).glob("*.csv")):
                (d / f.name).symlink_to(f.resolve())
    # TICKERS: freshest single source only (two copies would duplicate rows)
    td = PAPER_ROOT / "raw" / "TICKERS"
    td.mkdir(parents=True)
    lake_tickers = sorted((LAKE / "raw" / "TICKERS").glob("TICKERS_*.csv"))
    src = lake_tickers[-1] if lake_tickers else SNAPSHOT / "raw" / "TICKERS" / "TICKERS.csv"
    (td / "TICKERS.csv").symlink_to(src.resolve())
    # SFP: materialised concat, de-duplicated on date, snapshot first
    sd = PAPER_ROOT / "raw" / "SFP"
    sd.mkdir(parents=True)
    frames = [pd.read_csv(SNAPSHOT / "raw" / "SFP" / "SFP_SPY.csv", dtype=str)]
    for f in sorted((LAKE / "raw" / "SFP").glob("SFP_SPY_*.csv")):
        frames.append(pd.read_csv(f, dtype=str))
    spy = pd.concat(frames).drop_duplicates(subset=["date"], keep="last")
    spy.to_csv(sd / "SFP_SPY.csv", index=False)

    lake_manifest = json.loads((LAKE / "MANIFEST.json").read_text())
    manifest = {
        "role": "PAPER ROOT -- merged snapshot+lake view, NEVER evidence",
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lake_through": lake_manifest["lake_through"],
        "dataset_fingerprint": dev_fingerprint(
            "paper", lake_manifest["dataset_fingerprint"]),
    }
    (PAPER_ROOT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    return PAPER_ROOT


def composite_scores(gp_scores, cfg, panel):
    """H3's REGISTERED composite: equal rank weights, value + profitability."""
    spec = next(x for x in built_specs() if x.feature_id == "val_book_to_market")
    values, known, _ = build_features(PAPER_ROOT, panel, (spec,))
    btm = values["val_book_to_market"]
    r_gp = gp_scores.rank(axis=1, ascending=True, pct=True)      # score already high=good
    r_val = btm.rank(axis=1, ascending=True, pct=True)           # high btm = cheap = good
    return (r_gp + r_val) / 2


def target_names(name, score_row, decile_row, comp_row, held):
    if name == "H1-A":
        return list(decile_row[decile_row == 1].index)
    if name == "H1-B":
        return list(decile_row[decile_row <= 3].index)
    if name == "H1-E":
        keep = [s for s in held if decile_row.get(s, 99) <= 5]
        return keep + [s for s in decile_row[decile_row <= 3].index if s not in keep]
    if name in ("H3-QV-T", "H3-QV-B"):
        ranked = comp_row.dropna().sort_values(ascending=False)
        n = len(ranked)
        top = max(1, n // 10) if name == "H3-QV-T" else max(1, 3 * n // 10)
        return list(ranked.index[:top])
    if name == "CONTROL":
        return list(decile_row.dropna().index)
    raise ValueError(name)


def main() -> int:
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    root = build_paper_root()
    lake_through = json.loads((root / "MANIFEST.json").read_text())["lake_through"]
    progress(f"paper root built through {lake_through}")

    panel, _ = build_production_panel(root, cfg, PAPER_PANEL_START, lake_through)
    output, _ = apex003.build_gp_output(panel, cfg, root)
    comp = composite_scores(output.scores.apex_score, cfg, panel)

    # LIVE dates only, on the LOCKED grid (derived from the full-lake SPY
    # calendar, not the short panel's re-anchored one): strictly after the
    # sealed holdout's end, and present in the loaded panel.
    grid = [d for d in locked_grid(root, cfg)
            if d > HOLDOUT_END and d in panel.dates]
    if not grid:
        print(f"lake through {lake_through}: no live grid formation date yet "
              f"(first is 20 trading days past {HOLDOUT_END.date()}); "
              f"marks begin then. No state written.")
        return 0

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = STATE_DIR / "positions.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "portfolios": {}, "last_marked": None, "rebalances_seen": 0}

    close = panel.close_adj
    marks = {}
    for i, d in enumerate(grid):
        if state["last_marked"] and d <= pd.Timestamp(state["last_marked"]):
            continue
        assert d > HOLDOUT_END, "paper mark inside the sealed window"
        elig = output.universe.eligible.loc[d]
        score_row = output.scores.apex_score.loc[d].where(elig).dropna()
        decile_row = output.scores.decile.loc[d].where(elig).dropna()
        comp_row = comp.loc[d].where(elig)
        for name in PORTFOLIOS:
            port = state["portfolios"].setdefault(
                name, {"names": [], "since": None})
            # mark the PREVIOUS holding period's return before rebalancing
            if port["names"] and port["since"]:
                p0, p1 = pd.Timestamp(port["since"]), d
                assert p0 > HOLDOUT_END
                r = (close.loc[p1].reindex(port["names"])
                     / close.loc[p0].reindex(port["names"]) - 1).dropna()
                univ = (close.loc[p1].where(elig) / close.loc[p0].where(elig) - 1
                        ).dropna()
                marks.setdefault(str(d.date()), {})[name] = {
                    "period_return": round(float(r.mean()), 6),
                    "universe_return": round(float(univ.mean()), 6),
                    "excess": round(float(r.mean() - univ.mean()), 6),
                    "names": len(r),
                }
            if state["rebalances_seen"] % REBALANCE_EVERY == 0 or not port["names"]:
                port["names"] = target_names(name, score_row, decile_row,
                                             comp_row, port["names"])
            port["since"] = str(d.date())
        state["rebalances_seen"] += 1
        state["last_marked"] = str(d.date())

    state_path.write_text(json.dumps(state, indent=2))
    if marks:
        entry = _chain_append(STATE_DIR / "paper_ledger.jsonl", {
            "marked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "lake_through": lake_through, "marks": marks,
            "denominator": len(PORTFOLIOS),
        })
        print(json.dumps(marks, indent=2))
        print(f"chained mark {entry['entry_hash'][:16]}")
    else:
        print(f"positions formed/updated through {state['last_marked']}; "
              f"first excess marks land next grid date after new lake data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
