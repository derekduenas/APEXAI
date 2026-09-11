"""SHARADAR-DAILYVOL-001 — a declared walk-forward comparison of the M3 variance candidates on SPY DAILY returns
from the frozen Sharadar snapshot (SFP_SPY.csv, split+dividend adjusted closes). Daily horizon: a DIFFERENT problem
from the 15-minute pilot; recorded as forecast-score evidence for the workbench, never as options-pilot evidence.

Contract (validated before any read; period policy: rows dated <= 2021-12-31 only, matching the exposed periods):
    target        next-day log return r_{t+1} = log(closeadj_{t+1} / closeadj_t)
    candidates    ROLLING_VAR(30) [comparator], EWMA(0.94), GARCH(1,1)-t, GJR-GARCH(1,1)-t — one fit per fold each
    folds         walk-forward by calendar year 2013..2021 (train = all rows before the fold year, embargo 1 day)
    scores        log score of the candidate's predictive density on the realized return; PIT calibration (KS)
    comparison    paired log-score differences vs ROLLING_VAR on common rows; session-independent rows assumed
                  (daily, non-overlapping); a year-block bootstrap CI is reported
    budget        4 models x 9 folds = 36 fits, registered; no hyperparameter is varied"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.worldmodel_wb import tournament as TN, vol_models as VM                        # noqa: E402
from apex.worldmodel_wb.contracts import ModelRefused                                    # noqa: E402
from apex.worldmodel_wb.study_contract import HistoricalStudyContract                    # noqa: E402

LAST_DATE = "2021-12-31"
CONTRACT = HistoricalStudyContract(
    study_id="SHARADAR-DAILYVOL-001", primary_target="next-day SPY log return (closeadj), predictive density log score",
    primary_hypothesis="GARCH-family candidates improve the out-of-fold log score over the rolling-variance comparator (null: no improvement)",
    comparator="ROLLING_VAR(30)", eligible_rows="SPY SFP rows 2004-01-02..2021-12-31; folds = calendar years 2013..2021; train before the fold year; embargo 1 day",
    null_and_assumptions="daily returns; zero conditional mean; rows non-overlapping; year-block bootstrap for the CI; no dividend/split effects (closeadj)",
    fitting_cadence="one fit per candidate per fold on the training rows; the filter rolls forward through the fold without refit",
    parameter_budget=36, selection_rule="pre-declared: report all four; no tuning; the comparator is fixed", reporting_family="FORECAST_SCORE",
    horizon_minutes=1440, information_cutoff_rule="the fold's first date minus one day; the firewall hands models only earlier rows",
    dependence_inference="year-block bootstrap of the mean paired log-score difference (2000 draws, seed 11)", search_budget=4,
    planned_comparisons=["EWMA vs ROLLING", "GARCH11_T vs ROLLING", "GJR_GARCH11_T vs ROLLING", "PIT calibration per candidate"],
    notes="rows after 2021-12-31 are excluded before any use, matching the exposed-period policy of PILOT-REPLAY-001")


def load_spy(path: Path) -> list:
    rows = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            if r["ticker"] != "SPY" or r["date"] > LAST_DATE:
                continue
            rows.append((r["date"], float(r["closeadj"])))
    rows.sort()
    out = []
    for i in range(1, len(rows)):
        d, c = rows[i]; c0 = rows[i - 1][1]
        t = datetime.fromisoformat(d).timestamp()
        out.append({"date": d, "event_time": t, "available": t + 1.0, "ret_1": math.log(c / c0)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sfp", default=str(Path.home() / "apex-equities/data/snapshots/sharadar/current/raw/SFP/SFP_SPY.csv"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    contract = CONTRACT.validate()
    rows = load_spy(Path(a.sfp))
    reg = TN.TrialRegistry(budget=4, study_id=CONTRACT.study_id)
    factories = {"ROLLING_VAR": lambda: VM.RollingVariance(30), "EWMA": lambda: VM.EWMA(0.94),
                 "GARCH11_T": lambda: VM.GARCH(), "GJR_GARCH11_T": lambda: VM.GARCH(gjr=True)}
    trials = {n: reg.register(family=n, features=["ret_1"], transform="log(closeadj ratio)", window="train before fold year", hyperparameters={}, seed=0)
              for n in factories}
    scores = {n: {} for n in factories}; pits = {n: [] for n in factories}; fit_log = []
    years = list(range(2013, 2022))
    for y in years:
        train = [r for r in rows if r["date"] < "%d-01-01" % y]
        val = [r for r in rows if r["date"].startswith(str(y))]
        cutoff = datetime.fromisoformat("%d-01-01" % y).timestamp() - 86400.0
        fw = TN.DataFirewall(train)
        tv = fw.train_view(cutoff)
        for n, mk in factories.items():
            m = mk()
            try:
                m.fit(tv, cutoff_epoch=cutoff)
            except ModelRefused as e:
                fit_log.append({"year": y, "model": n, "fit": "REFUSED", "why": str(e)[:160]}); continue
            fit_log.append({"year": y, "model": n, "fit": "OK", "artifact": m.serialize()["artifact_digest"], "fit_count": m.fit_count})
            recent = []
            for r in val:
                f = m.forecast(cutoff_epoch=r["event_time"] - 1, created_epoch=r["event_time"], horizon_bars=1, recent=recent)
                d = f.density(); y_ = r["ret_1"]
                if d["family"] == "STUDENT_T":
                    s = TN.log_score_t(y_, 0.0, d["scale"], d["nu"]); p = TN.pit_t(y_, 0.0, d["scale"], d["nu"])
                else:
                    s = TN.log_score_normal(y_, 0.0, d["variance"]); p = TN.pit_normal(y_, 0.0, math.sqrt(d["variance"]))
                scores[n][r["date"]] = s; pits[n].append(p)
                recent.append(y_)
    out = {"study_id": CONTRACT.study_id, "contract": contract, "rows": len(rows), "first": rows[0]["date"], "last": rows[-1]["date"], "folds": years,
           "fits": fit_log, "mean_log_score": {n: (float(np.mean(list(v.values()))) if v else None) for n, v in scores.items()},
           "calibration": {n: TN.calibration_report(p) for n, p in pits.items()}, "comparisons": {}}
    base = scores["ROLLING_VAR"]
    rng = random.Random(11)
    for n in ("EWMA", "GARCH11_T", "GJR_GARCH11_T"):
        cmp = TN.paired_comparison(scores[n], base)
        common = TN.common_rows(scores[n], base)
        by_year = {}
        for d in common:
            by_year.setdefault(d[:4], []).append(scores[n][d] - base[d])
        ys = sorted(by_year); means = []
        for _ in range(2000):
            pick = [rng.choice(ys) for _ in ys]
            vals = [x for yy in pick for x in by_year[yy]]
            means.append(sum(vals) / len(vals))
        means.sort()
        cmp["year_block_bootstrap_ci95"] = [means[50], means[1949]]
        cmp["per_year_mean_diff"] = {yy: float(np.mean(v)) for yy, v in by_year.items()}
        cmp["conclusion"] = "IMPROVES_OVER_COMPARATOR_ON_THIS_SAMPLE" if means[50] > 0 else "DID_NOT_DEMONSTRATE_IMPROVEMENT"
        out["comparisons"][n + "_vs_ROLLING_VAR"] = cmp
        reg.record(trials[n]["trial"], status="SCORED", result={"mean_log_score": out["mean_log_score"][n], "vs_rolling": cmp["mean_diff"]})
    reg.record(trials["ROLLING_VAR"]["trial"], status="SCORED", result={"mean_log_score": out["mean_log_score"]["ROLLING_VAR"]})
    out["registry"] = reg.summary()
    out["evidence_class"] = "HISTORICAL_DEVELOPMENT_STUDY"; out["not_evidence_for"] = "the 15-minute options pilot (different horizon, different target)"
    Path(a.out).write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("rows", "first", "last", "mean_log_score", "comparisons")}, indent=1, default=str))
    print(json.dumps({n: {k: v for k, v in c.items() if k in ("n", "ks_pvalue", "mean_pit")} for n, c in out["calibration"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
