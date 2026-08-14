#!/usr/bin/env python
"""APEX-004 DRY-RUN CERTIFICATION (gross profitability, SMALL-CAP). NO credit.

Runs the full production path on the SMALL-CAP universe (build_gp_output --
the same certified module as APEX-003; the experiment differs only in the
config universe) and answers seven conformance sections with numbers. Two
runs must be byte-identical: the report carries no timestamps (progress goes
to stderr).

Registration is NOT complete: config still names APEX-003 (closed) and the
APEX-004 protocol is unsigned. Both are HUMAN acts, reported as PENDING. The
config is therefore overridden IN MEMORY, transparently: experiment.id ->
APEX-004 plus the gate-ruled section-3 universe (floor $100M, ceiling $2B,
ADDV $1M, close $2). The in-sample period is unlocked and free; no gated path
is invoked.

NO IC, no decile spread, no t-stat, no moment of any forward return. The
orientation checks compare SIGNAL values across deciles, never returns.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apex.audit.execution_path import certify_experiment  # noqa: E402
from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.experiments import apex003  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
ROOT = Path("data/snapshots/sharadar/current")
PROTOCOL = REPO / "APEX-004-DRAFT-Protocol-Smallcap.md"
MEMO = REPO / "SMALL-CAP-JUSTIFICATION.md"
CENSUS = Path("results/004_universe_census.json")
RECAL = Path("results/004_null_recalibration.json")
DEC = 12

# The gate-ruled section 3 universe, applied in memory until registration.
UNIVERSE_OVERRIDES = {
    "min_market_cap_usd": 100e6,
    "max_market_cap_usd": 2e9,
    "min_addv_usd": 1e6,
    "min_close_usd": 2.0,
}


def progress(msg: str) -> None:
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.data: dict = {}
        self.failures: list[str] = []
        self.pending: list[str] = []

    def say(self, line: str = "") -> None:
        self.lines.append(line)

    def head(self, n: int, title: str) -> None:
        self.say("=" * 78)
        self.say(f"SECTION {n}. {title}")
        self.say("=" * 78)

    def check(self, label: str, passed: bool, detail: str = "") -> None:
        self.say(f"  [{'PASS' if passed else 'FAIL'}] {label}"
                 + (f"   {detail}" if detail else ""))
        if not passed:
            self.failures.append(label)

    def pend(self, label: str, detail: str = "") -> None:
        """A known HUMAN act, reported honestly -- neither PASS nor FAIL."""
        self.say(f"  [PENDING] {label}" + (f"   {detail}" if detail else ""))
        self.pending.append(label)

    def fact(self, label: str, value) -> None:
        self.say(f"         {label:<38} {value}")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def q(x) -> float:
    return float(np.round(float(x), DEC))


def main() -> int:  # noqa: C901
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    r = Report()
    base = load_config("experiment", "costs", "synthetic", "sharadar")
    data = copy.deepcopy(base.data)
    data["experiment"]["id"] = "APEX-004"
    data["universe"].update(UNIVERSE_OVERRIDES)
    cfg = type(base)(data=data, sources=base.sources)
    period = "in_sample"

    r.say("=" * 78)
    r.say("APEX-004 -- DRY-RUN CERTIFICATION (gross profitability, SMALL-CAP)")
    r.say("A specification validator. Not a predictive research run.")
    r.say("=" * 78)
    r.say()

    # === 1. PROTOCOL / GOVERNANCE ========================================
    r.head(1, "PROTOCOL / GOVERNANCE")
    proto_text = PROTOCOL.read_text()
    proto_hash = hashlib.sha256(proto_text.encode()).hexdigest()
    memo_text = MEMO.read_text()

    r.check("gate ruling recorded in the justification memo",
            "APPROVED — H-GP-SC" in memo_text and "2.92" in memo_text,
            "descendant-of-failure CONTESTED disclosure retained")
    r.check("draft protocol drafted", PROTOCOL.exists())
    r.fact("protocol SHA-256 (unsigned draft)", proto_hash)
    r.check("protocol carries the ruled bar and explicit orientation",
            "t >= **2.92**" in proto_text and "decile 1 (TOP)" in proto_text
            and "seed\n**20260814**" in proto_text)
    census = json.loads(CENSUS.read_text())
    r.check("section 5a census on disk and matches the declared floors",
            census["floors"]["min_market_cap_usd"] == 100e6
            and census["floors"]["market_cap_ceiling_usd"] == 2e9)
    recal = json.loads(RECAL.read_text())
    r.check("section 8a recalibration on disk; ruled bar is the STRICTER one",
            recal["registered_002_003_bar"] == 2.92
            and recal["derived_critical_value_1pct_one_sided"] <= 2.92,
            f"derived {recal['derived_critical_value_1pct_one_sided']} vs ruled 2.92")
    r.pend("operator signature on the protocol",
           "human act -- 'Registered/Author' lines are PENDING by design")
    r.pend("config registration (experiment.id -> APEX-004) + CONVENTIONS pin",
           "human-authorised registration act; config still names "
           + base.get("experiment.id"))
    r.check("validation period locked", cfg.period("validation").get("locked") is True)
    r.check("holdout period locked", cfg.period("holdout").get("locked") is True)
    from apex.registration import unlock_token_status
    tok = unlock_token_status("validation", REPO)
    r.check("no token authorises APEX-004",
            not (tok["present"] and "APEX-004" in (tok["authorises"] or "")),
            f"token present: {tok['present']}"
            + (f" -- authorises {tok['authorises']!r} (STALE; delete before "
               f"writing 004's)" if tok["present"] else ""))
    wiring = certify_experiment(REPO, "APEX-004")
    r.check("execution-path isolation certifies (shared certified GP path)",
            wiring == [], str(wiring or "clean"))
    r.say()
    r.data["governance"] = {"protocol_draft_sha256": proto_hash,
                            "ruled_bar": 2.92}

    # === RUN THE PRODUCTION PATH =========================================
    progress("building production panel (small-cap floors, in memory)")
    panel, _ = build_production_panel(
        ROOT, cfg, cfg.get("calendar.lake_start"), cfg.period(period)["end"])
    known_from = pd.DataFrame(pd.NaT, index=panel.dates, columns=panel.securities,
                              dtype="datetime64[ns]")
    progress("running build_gp_output (production entry, returns for shape only)")
    output, factory_report = apex003.build_gp_output(
        panel, cfg, ROOT, known_from_out=known_from)
    progress("pipeline complete")

    grid = output.calendar.grid_formation_dates(
        cfg.period(period)["start"], cfg.period(period)["end"])
    eligible = output.universe.eligible.loc[grid]
    signal = output.signal.loc[grid]
    score = output.scores.apex_score.loc[grid]
    decile = output.scores.decile.loc[grid]
    kf = known_from.loc[grid]
    present = eligible & signal.notna()
    pop = present.to_numpy()

    # === 2. PIT / SF1 ====================================================
    r.head(2, "PIT / SF1 VERIFICATION")
    kfa = kf.to_numpy()
    form = np.repeat(kf.index.to_numpy()[:, None], kf.shape[1], axis=1)
    total = int(pop.sum())
    violations = int((kfa[pop] > form[pop]).sum())
    missing_kf = int(pd.isna(kfa[pop]).sum())
    r.check("filing_date <= formation_date is EXACTLY 100%",
            violations == 0 and missing_kf == 0,
            f"{(total - violations) / total * 100:.6f}%")
    r.fact("observations checked", f"{total:,}")
    r.fact("PIT violations", f"{violations}   (must be 0)")
    r.fact("missing knowability date", f"{missing_kf}   (must be 0)")
    lag = (form[pop] - kfa[pop]).astype("timedelta64[D]").astype(float)
    r.fact("knowledge lag p50 (days)", f"{q(np.nanmedian(lag)):.1f}")
    r.say()
    r.data["pit"] = {"observations": total, "violations": violations}

    # === 3. ORIENTATION (the erratum-class risk) =========================
    r.head(3, "ORIENTATION -- higher profitability = top")
    stacked = signal.where(present).stack()
    lo_idx, hi_idx = stacked.idxmin(), stacked.idxmax()
    d_flat = decile.where(present).stack()
    s_flat = signal.where(present).stack()
    by_dec = s_flat.groupby(d_flat).mean()
    r.check("HIGHEST gp scores 100", float(score.loc[hi_idx]) == 100.0,
            f"gp {stacked.max():+.4f} -> score {score.loc[hi_idx]:.2f}")
    r.check("HIGHEST gp is DECILE 1 (top)", float(decile.loc[hi_idx]) == 1.0)
    r.check("LOWEST gp is decile 10", float(decile.loc[lo_idx]) == 10.0,
            f"gp {stacked.min():+.4f} -> decile {int(decile.loc[lo_idx])}")
    r.check("mean gp is strictly DECREASING across deciles 1..10",
            bool(by_dec.reindex(range(1, 11)).is_monotonic_decreasing),
            "decile 1 holds the most profitable names on real data")
    r.fact("decile 1 mean gp", f"{q(by_dec.loc[1.0]):+.6f}")
    r.fact("decile 10 mean gp", f"{q(by_dec.loc[10.0]):+.6f}")
    r.say()
    r.data["orientation"] = {f"decile_{int(k)}_mean_gp": q(v)
                             for k, v in by_dec.items()}

    # === 4. SIGNAL CONSTRUCTION ==========================================
    r.head(4, "SIGNAL CONSTRUCTION (distribution, no returns)")
    vals = s_flat.dropna()
    r.fact("observations", f"{len(vals):,}")
    for p in (1, 25, 50, 75, 99):
        r.fact(f"p{p}", f"{q(vals.quantile(p / 100)):+.6f}")
    r.fact("min / max", f"{q(vals.min()):+.6f} / {q(vals.max()):+.6f}")
    r.check("no transformation: tails are unbounded beyond p1/p99",
            bool(vals.min() < vals.quantile(0.01) and vals.max() > vals.quantile(0.99)))
    neg = int((vals < 0).sum())
    r.fact("negative gp/assets observations", f"{neg:,}  ({neg/len(vals):.4%})"
           f"   (real losses; NOT clipped)")
    r.say()
    r.data["signal"] = {"observations": int(len(vals)),
                        **{f"p{p}": q(vals.quantile(p / 100)) for p in (1, 25, 50, 75, 99)}}

    # === 5. UNIVERSE / JOIN / THE CEILING ================================
    r.head(5, "UNIVERSE / JOIN ALIGNMENT / MARKET-CAP BAND")
    per_e = eligible.sum(axis=1)
    per_p = present.sum(axis=1)
    cover = (per_p / per_e.replace(0, np.nan)).dropna()
    r.fact("formation dates", f"{len(grid):,}")
    r.fact("eligible per date  min/med/max",
           f"{int(per_e.min()):,} / {int(per_e.median()):,} / {int(per_e.max()):,}")
    r.fact("coverage  min/med/max",
           f"{q(cover.min()*100):.4f}% / {q(cover.median()*100):.4f}% / "
           f"{q(cover.max()*100):.4f}%")
    # THE experimental change: every eligible name sits inside [$100M, $2B).
    mc = panel.market_cap.loc[grid].where(eligible)
    mc_max, mc_min = float(mc.max().max()), float(mc.min().min())
    r.check("every eligible market cap is BELOW the $2B ceiling", mc_max < 2e9,
            f"max eligible mcap ${mc_max/1e9:.4f}B")
    r.check("every eligible market cap is AT/ABOVE the $100M floor",
            mc_min >= 100e6, f"min eligible mcap ${mc_min/1e6:.1f}M")
    r.check("breadth is census-consistent (>= 800 median on the grid)",
            per_e.median() >= 800, f"median {int(per_e.median()):,}"
            f" (census daily median 1,250 incl. warm-up years)")
    ranked = score.notna()
    extra = int((ranked & ~present).to_numpy().sum())
    dropped = int((present & ~ranked).to_numpy().sum())
    r.check("join alignment SYMMETRIC on every date", extra == 0 and dropped == 0,
            f"{extra} ranked-but-ineligible, {dropped} eligible-but-unranked")
    r.check("zero duplicate (security_id, date)",
            not signal.index.duplicated().any() and not signal.columns.duplicated().any())
    r.check("coverage is not the binding constraint", bool(cover.median() > 0.90),
            f"median {q(cover.median()*100):.4f}%")
    r.say()
    r.data["universe"] = {"eligible_median": q(per_e.median()),
                          "coverage_median_pct": q(cover.median() * 100),
                          "mcap_max_eligible": q(mc_max),
                          "mcap_min_eligible": q(mc_min)}

    # === 6. RANKING / DECILES ============================================
    r.head(6, "RANKING / DECILE CONSTRUCTION")
    rerun = apex003.gp_percentile_score(signal, eligible,
                                        cfg.get("evaluation.rank_tie_method"))
    shuf = signal.columns[::-1]
    reord = apex003.gp_percentile_score(
        signal.reindex(columns=shuf), eligible.reindex(columns=shuf),
        cfg.get("evaluation.rank_tie_method")).reindex(columns=signal.columns)
    r.check("re-running the same dates is identical", score.equals(rerun))
    r.check("column-order invariant (C10 tie-break)", score.equals(reord))
    counts = [decile.loc[d].value_counts() for d in grid]
    imbalance = max(int(v.max() - v.min()) for v in counts if len(v))
    labels = sorted({int(x) for v in counts for x in v.index})
    r.check("decile labels exactly 1..10", labels == list(range(1, 11)), str(labels))
    r.check("equal-count (max within-date imbalance <= 1)", imbalance <= 1,
            f"imbalance {imbalance}")
    r.check("ScorePanel declares top_decile_label = 1",
            output.scores.top_decile_label == 1)
    r.say()

    # === 7. TRANSACTION LAYER + DETERMINISM ==============================
    r.head(7, "TRANSACTION LAYER / DETERMINISM")
    from apex.evaluate.criteria import SuccessCriteria
    from apex.report.attribution import attribute
    crit = SuccessCriteria.from_config(cfg, "validation")
    r.check("criteria load from config: t >= 2.92 (the RULED bar), IC positive",
            crit.t_stat.threshold == 2.92 and crit.mean_ic.rule == "positive")
    attribution = attribute(output, cfg, cfg.period(period)["start"],
                            cfg.period(period)["end"])
    r.check("attribution executes on GPOutput (INCIDENT-001 class)",
            type(attribution).__name__ == "Attribution",
            "no value it computed is read or reported")
    r.check("forward returns constructed (shape only)",
            output.forward_returns.excess.shape == (len(panel.dates), len(panel.securities)))
    r.check("smoke gate already binds APEX-004 to THIS report",
            "004_dry_run_A" in (REPO / "scripts" / "run_validation.py").read_text(),
            "per-experiment SMOKE_EVIDENCE map (the 003 lesson, applied early)")
    r.say("         apex.pipeline.evaluate NOT called. No IC, spread, or")
    r.say("         t-statistic appears anywhere in this report.")
    r.say()
    payload = json.dumps(r.data, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    r.fact("measurement digest", digest)
    r.say()

    r.say("=" * 78)
    r.say("CERTIFICATION SUMMARY")
    r.say("=" * 78)
    if r.failures:
        r.say(f"  STATUS: FAIL ({len(r.failures)} check(s))")
        for f in r.failures:
            r.say(f"    - {f}")
    else:
        r.say("  STATUS: PASS -- every mechanical check green")
    r.say(f"  PENDING HUMAN ACTS: {len(r.pending)}")
    for p_ in r.pending:
        r.say(f"    * {p_}")
    r.say()
    r.say("  Credit NOT spent (3/5). Holdout SEALED. Registration NOT complete.")
    r.say("=" * 78)

    out = Path(args.out)
    out.write_text(r.text())
    out.with_suffix(".json").write_text(json.dumps(
        {"measurement_digest": digest, "failures": r.failures,
         "pending": r.pending, **r.data}, sort_keys=True, indent=2) + "\n")
    progress(f"wrote {out}  digest={digest[:16]}")
    return 1 if r.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
