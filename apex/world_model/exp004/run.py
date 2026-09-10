"""EXP-004 orchestrator under the frozen registration. Preprocessing order is
the registered one (PREPROCESSING_ORDER). Integrity precedence: any refusal
returns INTEGRITY_FAILURE with the specific reason and no statistical
classification. Nothing here reads files or decides admission."""
from __future__ import annotations

import time

import numpy as np

from . import bootstrap_adapter as BA, dispersion as D, features as F, inference as I, models as M
from .registration import (ARMS, BUDGET, CONTEXTUAL, DEVELOPMENT_STATUS, EXPERIMENT_ID, INHERITED,
                           PREPROCESSING_ORDER, PRIMARY, SECONDARY, registration_hash)

BOOT = INHERITED["bootstrap"]["value"]
COMPARISONS = {"P1": tuple(PRIMARY["comparison"]), **{k: tuple(v) for k, v in SECONDARY.items()},
               "C_vs_L": tuple(CONTEXTUAL["C_vs_L"])}
SCIENTIFIC_STATUSES = ("SELECTED", "NOT_SELECTED")


def _refusal(kind: str, detail: str, stage: str, rec: dict) -> dict:
    rec.update(status="INTEGRITY_FAILURE", refusal={"kind": kind, "detail": detail[:600], "stage": stage},
               classification=I.classify({}, integrity_ok=False, integrity_reason="%s at %s" % (kind, stage)))
    return rec


def prepare_fit(fit_sessions: list) -> dict:
    """Steps 1-7 on ONE common eligible fit-row population."""
    base = F.fit_baselines(fit_sessions)                                        # 1-2
    rows, ref = F.eligible_rows_many(fit_sessions, base["vbar"])                # 3
    if len(rows) < D.MIN_RESIDUALS:
        raise F.FeatureRefused("INSUFFICIENT_FIT_ROWS: %d eligible" % len(rows))
    consts = F.clipping_constants(rows)                                         # 4
    clip = F.apply_clipping(rows, consts)                                       # 5 (standardisation inside fits)
    fits = M.fit_all(rows)                                                      # 6
    ys = np.array([y for _, y, _ in rows]); rr = [r for r, _, _ in rows]
    rv = np.array([r["features"]["rv_30"] for r in rr]); pc = np.array([r["features"]["P_c"] for r in rr])
    z = (ys - M.means_of(fits["specs"]["AX"], rr)) / rv                          # 7: AX reference residuals
    d0 = D.fit_d0(z)
    d1 = D.fit_d1(z, pc, nu0=d0["nu0"], s0=d0["s0"])
    for spec in (d0, d1):
        D.check_scales(spec, rv, pc, "fit rows")
    return {"baselines": {k: v for k, v in base.items() if k != "vbar"}, "vbar": base["vbar"],
            "fit_refusals": ref, "clipping": {**consts, **clip}, "location": fits,
            "dispersion": {"D0": d0, "D1": d1, "reference": "AX residuals / rv_30 on the common fit rows"},
            "n_fit_rows": len(rows),
            "estimations": {"baselines": 1, "clipping_constants": 3, "location_fits": fits["fits_performed"],
                            "dispersion_fits": 2, "total": 1 + 3 + fits["fits_performed"] + 2}}


def score(prep: dict, dev_sessions: list, *, bootstrap_resamples: int = BOOT["resamples"],
          seed: int = BOOT["seed"]) -> dict:
    """Development scoring on the common eligible rows, both specs, all comparisons."""
    rows, ref = F.eligible_rows_many(dev_sessions, prep["vbar"])
    if len(rows) < 60:
        raise F.FeatureRefused("INSUFFICIENT_DEVELOPMENT_ROWS: %d eligible" % len(rows))
    clip = F.apply_clipping(rows, prep["clipping"])
    rr = [r for r, _, _ in rows]
    ys = np.array([y for _, y, _ in rows])
    rv = np.array([r["features"]["rv_30"] for r in rr]); pc = np.array([r["features"]["P_c"] for r in rr])
    sess = [r["session_id"] for r in rr]
    keys = [(r["session_id"], r["event_time"]) for r in rr]
    mus = {arm: M.means_of(prep["location"]["specs"][arm], rr) for arm in ARMS}
    ll = {}
    for sp in ("D0", "D1"):
        spec = prep["dispersion"][sp]
        D.check_scales(spec, rv, pc, "development rows")
        sc = D.scales(spec, rv, pc)
        ll[sp] = {arm: D.logpdf(ys, mus[arm], sc, spec["nu0"]) for arm in ARMS}

    def compare(a, b, sp):
        d = (ll[sp][a] - ll[sp][b]).tolist()
        hac = I.hac_decision(d)
        boots = {str(L): BA.strip_arrays(BA.session_stationary_bootstrap_ext(
                    d, sess, expected_block_sessions=L, n_resamples=bootstrap_resamples, seed=seed,
                    threshold=BOOT["p_threshold"]))
                 for L in (BOOT["expected_block_sessions"], *BOOT["sensitivities"])}
        return {"pair": [a, b], "spec": sp, "n_rows": len(d), "hac": hac,
                "bootstrap": boots[str(BOOT["expected_block_sessions"])], "bootstrap_sensitivities":
                {L: boots[L] for L in boots if L != str(BOOT["expected_block_sessions"])}}

    comps = {name: {sp: compare(a, b, sp) for sp in ("D0", "D1")} for name, (a, b) in COMPARISONS.items()}
    p1 = comps["P1"]
    decisions = {"HAC_D0": p1["D0"]["hac"]["pass"], "BOOT_D0": p1["D0"]["bootstrap"]["pass"],
                 "HAC_D1": p1["D1"]["hac"]["pass"], "BOOT_D1": p1["D1"]["bootstrap"]["pass"]}
    cls = I.classify(decisions)
    fam = I.secondary_family({"%s_%s" % (s, sp): comps[s][sp]["hac"]["p_one_sided"] for s in SECONDARY for sp in ("D0", "D1")},
                             {"%s_%s" % (s, sp): comps[s][sp]["bootstrap"]["p_one_sided"] for s in SECONDARY for sp in ("D0", "D1")})
    # dispersion improvement: AX under D1 vs AX under D0 (same location, same nu)
    disp = (ll["D1"]["AX"] - ll["D0"]["AX"]).tolist()
    disp_rec = {"pair": "AX@D1 - AX@D0", "hac": I.hac_decision(disp)}
    # fixed per-year summaries of every primary statistic (descriptive)
    years = sorted({k[0][:4] for k in keys})
    per_year = {}
    for yr in years:
        idx = [i for i, k in enumerate(keys) if k[0].startswith(yr)]
        per_year[yr] = {"n_rows": len(idx), "P1": {sp: I.hac_decision((ll[sp]["C"][idx] - ll[sp]["AX"][idx]).tolist())
                                                   for sp in ("D0", "D1")}}
    theta = {sp: prep["location"]["specs"]["C"]["beta"][-1] for sp in ("D0",)}["D0"]
    return {"development_refusals": ref, "clipping_applied": clip, "n_rows": len(rows),
            "row_key_population": {"n_keys": len(keys), "identical_across_all_comparisons": True,
                                   "first": list(keys[0]), "last": list(keys[-1])},
            "comparisons": comps, "primary_decisions": decisions, "classification": cls,
            "secondary_family": fam, "dispersion_improvement": disp_rec, "per_year": per_year,
            "theta_F_c_in_C": {"value": theta, "meaning": "partial association on standardised F~, other regressors fixed; "
                                                          "mu_C - mu_AX != theta*F~ in general"}}


def tournament(fit_sessions: list, dev_sessions: list, *, bootstrap_resamples: int = BOOT["resamples"],
               seed: int = BOOT["seed"]) -> dict:
    t0 = time.time()
    rec = {"experiment": EXPERIMENT_ID, "registration_hash": registration_hash(),
           "development_status": DEVELOPMENT_STATUS, "preprocessing_order": list(PREPROCESSING_ORDER),
           "budget_declared": BUDGET, "economics": "NONE (distributional only)"}
    try:
        prep = prepare_fit(fit_sessions)
    except (F.FeatureRefused, M.ArmRefused, D.DispersionRefused, ValueError) as e:
        return _refusal(type(e).__name__, str(e), "fit", rec)
    rec["fit"] = {k: v for k, v in prep.items() if k != "vbar"}
    try:
        dev = score(prep, dev_sessions, bootstrap_resamples=bootstrap_resamples, seed=seed)
    except (F.FeatureRefused, D.DispersionRefused, ValueError) as e:
        return _refusal(type(e).__name__, str(e), "development", rec)
    rec["development"] = dev
    rec["status"] = dev["classification"]["outcome"]
    rec["elapsed_s"] = round(time.time() - t0, 2)
    return rec
