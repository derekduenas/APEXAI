#!/usr/bin/env python
"""APEX-002 Step 4 -- DRY-RUN CERTIFICATION. A specification validator.

Runs the FULL production pipeline including forward returns, then answers the
seven registered conformance sections with numbers.

WHAT IS DELIBERATELY ABSENT
---------------------------
No IC. No decile spread. No factor performance. No t-statistic. No moment of
any forward return. `compute_forward_returns` runs because the registered
contract says the dry run exercises the full pipeline, and its OUTPUT SHAPE is
reported as pipeline integrity -- but `apex.pipeline.evaluate` is never called
and no statistic is derived from a return. If a predictive number appeared
here, the process would already be compromised.

No unlock token is created, no credit is spent, no ledger entry is written, and
the holdout is not read. The period is in-sample, which `config.periods` marks
unlocked; validation and holdout are `locked: true` and are not touched.

DETERMINISM
-----------
The report body carries NO timestamps and NO elapsed times -- progress goes to
stderr, outside the artifact. Two runs from the same snapshot must therefore be
byte-identical, and a difference means a difference in computation rather than
in when the clock was read.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apex.audit.execution_path import (  # noqa: E402
    EXPERIMENT_ENTRY,
    certify_experiment,
    module_closure,
)
from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.experiments import apex002  # noqa: E402
from apex.features import nsi as nsi_mod  # noqa: E402
from apex.features import nsi_scores as scores_mod  # noqa: E402
from apex.registration import protocol_pin_status, signature_status  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
ROOT = Path("data/snapshots/sharadar/current")
B1 = Path("results/002_b1_measurement.json")
EXPERIMENT = "APEX-002"
DEC = 12


def progress(msg: str) -> None:
    """stderr only -- never enters the artifact being compared."""
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.data: dict = {}
        self.failures: list[str] = []

    def say(self, line: str = "") -> None:
        self.lines.append(line)

    def head(self, n: int, title: str) -> None:
        self.say("=" * 78)
        self.say(f"SECTION {n}. {title}")
        self.say("=" * 78)

    def check(self, label: str, passed: bool, detail: str = "") -> bool:
        self.say(f"  [{'PASS' if passed else 'FAIL'}] {label}"
                 + (f"   {detail}" if detail else ""))
        if not passed:
            self.failures.append(label)
        return passed

    def fact(self, label: str, value) -> None:
        self.say(f"         {label:<38} {value}")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def q(x) -> float:
    return float(np.round(float(x), DEC))


def main() -> int:  # noqa: C901
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="report path (txt)")
    args = ap.parse_args()

    r = Report()
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    period = "in_sample"

    r.say("=" * 78)
    r.say("APEX-002 -- DRY-RUN CERTIFICATION")
    r.say("A specification validator. Not a predictive research run.")
    r.say("=" * 78)
    r.say()

    # ==================================================================
    # 1. PROTOCOL / GOVERNANCE
    # ==================================================================
    r.head(1, "PROTOCOL / GOVERNANCE")
    pinned = cfg.get("experiment.protocol_file")
    pin = protocol_pin_status(cfg, REPO)
    sig = signature_status(cfg, REPO)
    digest = pin["actual_hash"]
    expected_pin = "63703d1020893a59a4b43ed9698c4920ccb392e7f76bc77030ef019693ea9bda"
    manifest = json.loads((ROOT / "MANIFEST.json").read_text())
    fingerprint = manifest["dataset_fingerprint"]

    r.check("registered experiment is APEX-002",
            cfg.get("experiment.id") == EXPERIMENT, cfg.get("experiment.id"))
    r.check("frozen protocol hash intact", digest == expected_pin)
    r.check("pre-registration is signed", bool(sig.get("signed")))
    r.fact("protocol file", pinned)
    r.fact("SHA-256", digest)
    r.check("validation period still locked",
            cfg.period("validation").get("locked") is True)
    r.check("holdout period still locked",
            cfg.period("holdout").get("locked") is True)
    r.check("no validation unlock token exists",
            not (REPO / "validation.unlock").exists())
    r.fact("evaluation period", f"{cfg.period(period)['start']} .. "
                                f"{cfg.period(period)['end']}  ({period}, unlocked)")
    r.fact("dataset fingerprint", fingerprint)

    wiring = certify_experiment(REPO, EXPERIMENT)
    closure = module_closure(REPO, EXPERIMENT_ENTRY[EXPERIMENT])
    r.check("execution path wiring conforms", not wiring,
            f"{len(closure)} modules from {EXPERIMENT_ENTRY[EXPERIMENT]}")
    foreign = sorted(m for m in closure if m in {
        "apex.features.composite", "apex.features.f1_momentum",
        "apex.features.f2_trend", "apex.features.f3_volatility",
        "apex.features.f4_relative_strength"})
    r.check("no APEX-001 scoring machinery on the path", not foreign,
            str(foreign or "none"))
    for f in wiring:
        r.say(f"         FINDING: {f}")
    r.say()
    r.data["governance"] = {
        "experiment": cfg.get("experiment.id"), "protocol_sha256": digest,
        "dataset_fingerprint": fingerprint, "closure_modules": len(closure),
    }

    # ==================================================================
    # RUN THE FULL PRODUCTION PIPELINE (returns included)
    # ==================================================================
    progress("building production panel")
    panel, _ = build_production_panel(
        ROOT, cfg, cfg.get("calendar.lake_start"), cfg.period(period)["end"]
    )
    known_from = pd.DataFrame(pd.NaT, index=panel.dates, columns=panel.securities,
                              dtype="datetime64[ns]")
    progress("running build_nsi_output -- the production entry point, returns included")
    # THE production function. run_period dispatches APEX-002 to exactly this
    # call; the dry run does not reassemble the pipeline from its parts.
    output, rep_out = apex002.build_nsi_output(
        panel, cfg, ROOT, known_from_out=known_from
    )
    signal = output
    forward = output.forward_returns
    progress("pipeline complete")

    grid = signal.calendar.grid_formation_dates(
        cfg.period(period)["start"], cfg.period(period)["end"]
    )
    eligible = signal.universe.eligible.loc[grid]
    nsi = signal.nsi.loc[grid]
    score = signal.scores.apex_score.loc[grid]
    decile = signal.scores.decile.loc[grid]
    kf = known_from.loc[grid]
    rep = rep_out
    present = eligible & nsi.notna()
    pop = present.to_numpy()

    # ==================================================================
    # 2. PIT / SF1 VERIFICATION
    # ==================================================================
    r.head(2, "PIT / SF1 VERIFICATION")
    kfa, form = kf.to_numpy(), np.repeat(kf.index.to_numpy()[:, None], kf.shape[1], axis=1)
    total = int(pop.sum())
    violations = int((kfa[pop] > form[pop]).sum())
    missing_kf = int(pd.isna(kfa[pop]).sum())
    pit_pct = q((total - violations) / total * 100.0)

    r.check("filing_date <= formation_date is EXACTLY 100%",
            violations == 0 and missing_kf == 0 and pit_pct == 100.0,
            f"{pit_pct:.6f}%")
    r.fact("observations checked", f"{total:,}")
    r.fact("PIT violations", f"{violations}   (must be 0)")
    r.fact("missing knowability date", f"{missing_kf}   (must be 0)")
    r.check("earliest filing selected per (ticker, reportperiod)",
            rep.dropped_revisions > 0,
            f"{rep.dropped_revisions:,} later revisions discarded")
    r.fact("ARQ rows read", f"{rep.raw_arq_rows:,}")
    r.fact("as-filed rows retained", f"{rep.as_filed_rows:,}")
    r.fact("impossible filings excluded", f"{rep.dropped_impossible_filing:,}"
                                          f"   (date <= reportperiod)")
    r.fact("non-positive sharesbas excluded", f"{rep.dropped_nonpositive_shares:,}")
    lag = (form[pop] - kfa[pop]).astype("timedelta64[D]").astype(float)
    r.fact("knowledge lag p50 (days)", f"{q(np.nanmedian(lag)):.1f}")
    r.say()
    r.data["pit"] = {"observations": total, "violations": violations,
                     "pct": pit_pct, "revisions_dropped": rep.dropped_revisions,
                     "impossible_filings": rep.dropped_impossible_filing}

    # ==================================================================
    # 3. CORPORATE-ACTION MEASUREMENT
    # ==================================================================
    r.head(3, "CORPORATE-ACTION MEASUREMENT")
    excl, acc = rep.excluded_corporate_action, rep.accepted_corporate_action
    considered = excl + acc
    pair_rate = q(excl / considered * 100.0)

    frames = [pd.read_csv(p, usecols=["date", "action", "ticker"], dtype=str)
              for p in sorted(glob.glob(str(ROOT / "raw" / "ACTIONS" / "*.csv")))]
    actions = pd.concat(frames, ignore_index=True)
    actions["action"] = actions["action"].str.lower()
    excluding = actions[actions["action"].isin(nsi_mod.EXCLUDING_ACTIONS)]

    r.fact("security-quarter pairs excluded", f"{excl:,}")
    r.fact("security-quarter pairs accepted", f"{acc:,}")
    r.fact("pairs considered", f"{considered:,}")
    r.fact("EXCLUSION RATE (pairs/pairs)", f"{pair_rate:.4f}%")
    r.say()
    r.say("         breakdown of excluding ACTION EVENTS by type:")
    breakdown = {}
    for action, n in excluding["action"].value_counts().sort_index().items():
        r.say(f"           {action:<22} {n:>8,}")
        breakdown[str(action)] = int(n)
    r.fact("total excluding events", f"{len(excluding):,}")
    r.say("         (event counts, not pair attributions: one action can void")
    r.say("          several pairs, and several actions can void one pair)")
    r.say()

    split_actions = sorted(a for a in actions["action"].dropna().unique()
                           if "split" in a)
    r.check("splits are NOT in the exclusion set",
            not any(a in nsi_mod.EXCLUDING_ACTIONS for a in split_actions),
            f"present in vendor data: {split_actions}")
    r.say("         sharesbas is retroactively split-rebased; excluding splits")
    r.say("         would double-count an adjustment already applied.")

    # Cell-level view: eligible security-dates with no usable NSI.
    elig_no_nsi = int((eligible & nsi.isna()).to_numpy().sum())
    elig_total = int(eligible.to_numpy().sum())
    cell_rate = q(elig_no_nsi / elig_total * 100.0)
    r.say()
    r.fact("eligible security-dates", f"{elig_total:,}")
    r.fact("eligible WITHOUT usable NSI", f"{elig_no_nsi:,}  ({cell_rate:.4f}%)")
    r.say("         (this cell-level figure mixes corporate-action exclusions")
    r.say("          with insufficient filing history; it is NOT the pair rate)")
    r.say()
    r.data["corporate_actions"] = {
        "excluded_pairs": excl, "accepted_pairs": acc,
        "pair_rate_pct": pair_rate, "events_by_type": breakdown,
        "eligible_without_nsi": elig_no_nsi, "cell_rate_pct": cell_rate,
    }

    # ==================================================================
    # 4. NSI CONSTRUCTION
    # ==================================================================
    r.head(4, "NSI CONSTRUCTION")
    vals = nsi.where(present).stack().dropna()
    n = len(vals)
    pos, neg, zero = int((vals > 0).sum()), int((vals < 0).sum()), int((vals == 0).sum())
    dist = {f"p{p}": q(vals.quantile(p / 100)) for p in (1, 25, 50, 75, 99)}

    r.fact("observations", f"{n:,}")
    for k, v in dist.items():
        r.fact(k, f"{v:+.9f}")
    r.fact("mean", f"{q(vals.mean()):+.9f}")
    r.fact("min / max", f"{q(vals.min()):+.9f} / {q(vals.max()):+.9f}")
    r.say()
    r.fact("positive (net issuance)", f"{pos:,}  ({q(pos/n*100):.4f}%)")
    r.fact("negative (net repurchase)", f"{neg:,}  ({q(neg/n*100):.4f}%)")
    r.fact("exactly zero (tie rate)", f"{zero:,}  ({q(zero/n*100):.4f}%)")
    r.check("positive + negative + zero == observations", pos + neg + zero == n)
    r.say()

    b1 = json.loads(B1.read_text()) if B1.exists() else {}
    if b1:
        prior = b1.get("nsi_distribution", {})
        agree = all(abs(prior.get(k, 1e9) - v) < 1e-12 for k, v in dist.items())
        r.check("B1 distribution reproduced exactly", agree)
        for k, v in dist.items():
            r.fact(f"  {k}  B1 / dry run", f"{prior.get(k):+.9f} / {v:+.9f}")
        r.check("B1 observation count reproduced",
                prior.get("observations") == n, f"{prior.get('observations'):,} / {n:,}")
    r.say()
    r.data["nsi"] = {"observations": n, **dist, "positive": pos,
                     "negative": neg, "zero": zero}

    # ==================================================================
    # 5. UNIVERSE / JOIN ALIGNMENT
    # ==================================================================
    r.head(5, "UNIVERSE / JOIN ALIGNMENT")
    per_elig = eligible.sum(axis=1)
    per_nsi = present.sum(axis=1)
    cover = (per_nsi / per_elig.replace(0, np.nan)).dropna()

    r.fact("formation dates", f"{len(grid):,}")
    r.fact("eligible per date  min/med/max",
           f"{int(per_elig.min()):,} / {int(per_elig.median()):,} / {int(per_elig.max()):,}")
    r.fact("with NSI per date  min/med/max",
           f"{int(per_nsi.min()):,} / {int(per_nsi.median()):,} / {int(per_nsi.max()):,}")
    r.fact("coverage  min/med/max",
           f"{q(cover.min()*100):.4f}% / {q(cover.median()*100):.4f}% / "
           f"{q(cover.max()*100):.4f}%")
    r.fact("missingness (1 - coverage) median", f"{q((1-cover.median())*100):.4f}%")

    expected_set = eligible & nsi.notna()
    ranked = score.notna()
    extra = int((ranked & ~expected_set).to_numpy().sum())
    dropped = int((expected_set & ~ranked).to_numpy().sum())
    r.say()
    r.check("join alignment is SYMMETRIC on every date",
            extra == 0 and dropped == 0,
            f"{extra} ranked-but-ineligible, {dropped} eligible-but-unranked")
    r.check("zero duplicate (security_id, date)",
            not nsi.index.duplicated().any() and not nsi.columns.duplicated().any())
    r.check("no silent drop in the SF1 -> universe join",
            bool(nsi.columns.equals(panel.securities)
                 and eligible.columns.equals(panel.securities)),
            "signal and universe share the security axis")
    r.check("NSI availability is not the binding constraint",
            bool(cover.median() > 0.90),
            f"median coverage {q(cover.median()*100):.4f}%")
    r.say()
    r.data["universe"] = {
        "formation_dates": len(grid),
        "eligible_min": int(per_elig.min()), "eligible_median": q(per_elig.median()),
        "eligible_max": int(per_elig.max()),
        "coverage_median_pct": q(cover.median() * 100),
        "join_extra": extra, "join_dropped": dropped,
    }

    # ==================================================================
    # 6. RANKING / DECILE CONSTRUCTION
    # ==================================================================
    r.head(6, "RANKING / DECILE CONSTRUCTION")
    tie = cfg.get("evaluation.rank_tie_method")
    n_dec = int(cfg.get("evaluation.n_deciles"))
    stacked = nsi.where(present).stack()
    lo, hi = stacked.idxmin(), stacked.idxmax()

    rerun = scores_mod.nsi_percentile_score(nsi, eligible, tie)
    shuf = nsi.columns[::-1]
    reord = scores_mod.nsi_percentile_score(
        nsi.reindex(columns=shuf), eligible.reindex(columns=shuf), tie
    ).reindex(columns=nsi.columns)

    r.fact("tie method (C10)", repr(tie))
    r.fact("lowest NSI", f"{stacked.min():+.9f} -> score {score.loc[lo]:.6f}, "
                         f"decile {int(decile.loc[lo])}")
    r.fact("highest NSI", f"{stacked.max():+.9f} -> score {score.loc[hi]:.6f}, "
                          f"decile {int(decile.loc[hi])}")
    r.check("re-running the same dates gives identical ordering",
            score.equals(rerun))
    r.check("tie-break is stable under column permutation",
            score.equals(reord), "security_id-sorted ranking view")
    r.check("lowest NSI scores highest (section 13 IC orientation)",
            float(score.loc[lo]) == 100.0)
    r.check("lowest NSI is DECILE 1 (section 9 top decile)",
            float(decile.loc[lo]) == 1.0)
    r.check("highest NSI is the bottom decile",
            float(decile.loc[hi]) == float(n_dec))

    counts = [decile.loc[d].value_counts() for d in grid]
    imbalance = max(int(v.max() - v.min()) for v in counts if len(v))
    labels = sorted({int(x) for v in counts for x in v.index})
    r.check("decile labels are exactly 1..n", labels == list(range(1, n_dec + 1)),
            str(labels))
    r.check("deciles are equal-count (max imbalance <= 1)", imbalance <= 1,
            f"max within-date imbalance {imbalance}")
    r.check("decile set equals score set", bool(decile.notna().equals(ranked)))
    r.say()
    r.data["ranking"] = {
        "tie_method": tie, "lowest_score": q(score.loc[lo]),
        "lowest_decile": int(decile.loc[lo]), "highest_decile": int(decile.loc[hi]),
        "decile_labels": labels, "max_imbalance": imbalance,
    }

    # ==================================================================
    # 7. DETERMINISM / CONFORMANCE
    # ==================================================================
    r.head(7, "DETERMINISM / CONFORMANCE")
    src_nsi = (REPO / "apex/features/nsi.py").read_text()
    src_sco = (REPO / "apex/features/nsi_scores.py").read_text()

    from apex.audit.execution_path import executable_source
    code = executable_source(src_nsi) + executable_source(src_sco)
    banned = [b for b in ("winsor", "zscore", "z_score", "ewm(", "rolling(",
                          "fillna(", ".quantile(", "interpolate(")
              if b in code]
    r.check("no transformation construct in executable code", not banned,
            str(banned or "none"))
    r.check("runtime distribution is unbounded (not winsorised)",
            bool(vals.min() < dist["p1"] and vals.max() > dist["p99"]),
            f"tails extend beyond p1/p99: {q(vals.min()):+.6f} .. {q(vals.max()):+.6f}")
    r.check("no implicit NA filling",
            int((score.notna() & nsi.isna()).to_numpy().sum()) == 0)

    r.say()
    r.check("panel built end-to-end", bool(len(panel.dates) and len(panel.securities)))
    r.fact("panel shape", f"{len(panel.dates):,} dates x {len(panel.securities):,} securities")
    r.fact("signal frame shape", f"{nsi.shape[0]:,} x {nsi.shape[1]:,}")
    shapes_ok = nsi.shape == score.shape == decile.shape
    r.check("no shape drift across signal/score/decile", shapes_ok)
    r.check("forward returns constructed (shape only; no statistic derived)",
            forward.excess.shape == (len(panel.dates), len(panel.securities)),
            f"{forward.excess.shape[0]:,} x {forward.excess.shape[1]:,}")
    r.say("         apex.pipeline.evaluate was NOT called. No IC, no spread,")
    r.say("         no t-statistic, no moment of any forward return appears")
    r.say("         anywhere in this report.")
    r.say()
    r.fact("float_output_decimals", DEC)
    r.fact("config hash", cfg.hash)
    r.say()

    payload = json.dumps(r.data, sort_keys=True, separators=(",", ":"))
    r.data_digest = hashlib.sha256(payload.encode()).hexdigest()
    r.fact("measurement digest", r.data_digest)
    r.say()

    # ==================================================================
    r.say("=" * 78)
    r.say("CERTIFICATION SUMMARY")
    r.say("=" * 78)
    if r.failures:
        r.say(f"  CERTIFICATION STATUS: FAIL   ({len(r.failures)} check(s) failed)")
        for f in r.failures:
            r.say(f"    - {f}")
    else:
        r.say("  CERTIFICATION STATUS: PASS")
        r.say("  Every registered check passed on the executed pipeline.")
    r.say()
    r.say("  No unlock token created. Credit 2 UNSPENT. Holdout SEALED.")
    r.say("  Two-run bit-for-bit equality is verified OUTSIDE this script.")
    r.say("=" * 78)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(r.text())
    out.with_suffix(".json").write_text(
        json.dumps({"measurement_digest": r.data_digest,
                    "failures": r.failures, **r.data},
                   sort_keys=True, indent=2) + "\n")
    progress(f"wrote {out}  digest={r.data_digest[:16]}...")
    return 1 if r.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
