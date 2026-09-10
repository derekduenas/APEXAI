"""EXP-004 orchestrator under the frozen registration. Preprocessing order is
the registered one (PREPROCESSING_ORDER). Integrity precedence: any refusal —
including numerical invalidity anywhere in scoring or inference — returns
INTEGRITY_FAILURE with the specific reason and no statistical classification.
The runner validates the sessions it is given; it does not trust the caller.
Nothing here reads files or decides admission."""
from __future__ import annotations

import contextlib
import json
import time

import numpy as np

from apex.world_model.exp001b.bars import BarsRefused
from . import bootstrap_adapter as BA, dispersion as D, features as F, inference as I, models as M
from .registration import (ARMS, BUDGET, CONTEXTUAL, DEVELOPMENT_STATUS, EXPERIMENT_ID, INHERITED,
                           PREPROCESSING_ORDER, PRIMARY, SECONDARY, registration_hash)

BOOT = INHERITED["bootstrap"]["value"]
COMPARISONS = {"P1": tuple(PRIMARY["comparison"]), **{k: tuple(v) for k, v in SECONDARY.items()},
               "C_vs_L": tuple(CONTEXTUAL["C_vs_L"])}
REPORT_YEARS = tuple(str(y) for y in CONTEXTUAL["per_year"])          # fixed cells: 2019, 2020, 2021
YEAR_MIN_ROWS = 60                                                     # below this a year cell is NOT_AVAILABLE
MIN_DEV_ROWS = 60
# BarsRefused subclasses Exception (not ValueError) and ArithmeticError covers
# OverflowError/FloatingPointError/ZeroDivisionError: both are named here so no
# numerical or input failure can terminate the runner without a sealed record.
REFUSALS = (F.FeatureRefused, M.ArmRefused, D.DispersionRefused, I.InferenceRefused,
            BarsRefused, ArithmeticError, ValueError)


class BudgetExceeded(ValueError):
    """More estimation calls than the registered budget."""


# ---------------------------------------------------------------- fit-call accounting

class FitAccounting:
    """Counts calls to the REAL estimation functions by wrapping them for the
    duration of prepare_fit. The budget is enforced, not merely reported."""
    EXPECTED = {"baselines": 1, "clipping_constants": 3, "location_fits": 4, "dispersion_fits": 2}

    def __init__(self):
        self.calls = {k: 0 for k in self.EXPECTED}
        self.log = []

    def _wrap(self, fn, key, label):
        def wrapped(*a, **k):
            self.calls[key] += 1
            self.log.append((key, label))
            if self.calls[key] > self.EXPECTED[key]:
                raise BudgetExceeded("BUDGET_EXCEEDED: %s call %d > %d" % (key, self.calls[key], self.EXPECTED[key]))
            return fn(*a, **k)
        return wrapped

    @contextlib.contextmanager
    def armed(self):
        targets = [(F, "fit_baselines", "baselines"), (F, "order_statistic", "clipping_constants"),
                   (M, "fit_arm", "location_fits"), (D, "fit_d0", "dispersion_fits"), (D, "fit_d1", "dispersion_fits")]
        originals = [(mod, name, getattr(mod, name)) for mod, name, _ in targets]
        try:
            for mod, name, key in targets:
                setattr(mod, name, self._wrap(getattr(mod, name), key, name))
            yield self
        finally:
            for mod, name, fn in originals:
                setattr(mod, name, fn)

    def report(self) -> dict:
        total = sum(self.calls.values())
        if self.calls != self.EXPECTED:
            raise BudgetExceeded("BUDGET_MISMATCH: counted %s, registered %s" % (self.calls, self.EXPECTED))
        return {**self.calls, "total": total, "enforced_by": "counting wrappers on the real fitters",
                "call_log": self.log}


# ---------------------------------------------------------------- helpers

def _refusal(kind: str, detail: str, stage: str, rec: dict) -> dict:
    rec.update(status="INTEGRITY_FAILURE", refusal={"kind": kind, "detail": detail[:600], "stage": stage},
               classification=I.classify({}, integrity_ok=False, integrity_reason="%s at %s" % (kind, stage)))
    return rec


def _keys(rows) -> list:
    return [(r["session_id"], r["event_time"]) for r, _, _ in rows]


def _check_row_order(keys: list, label: str) -> None:
    """Rows must be contiguous per session and strictly increasing in
    (session_date, event_time); the session-order bootstrap depends on it."""
    for a, b in zip(keys, keys[1:]):
        if b <= a:
            raise F.FeatureRefused("ROWS_OUT_OF_ORDER: %s at %s -> %s" % (label, a, b))
    seen_sessions, last = set(), None
    for s, _ in keys:
        if s != last and s in seen_sessions:
            raise F.FeatureRefused("INTERLEAVED_SESSIONS: %s session %s reappears" % (label, s))
        seen_sessions.add(s); last = s


def strict_json(obj) -> str:
    """Sealed records must be standard JSON: NaN/Infinity are refused, not emitted."""
    return json.dumps(obj, sort_keys=True, allow_nan=False, default=_json_default)


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, tuple):
        return list(o)
    raise TypeError("not serialisable: %r" % type(o))


# ---------------------------------------------------------------- fit

def prepare_fit(fit_sessions: list) -> dict:
    """Steps 1-7 on ONE common eligible fit-row population, with enforced accounting."""
    acct = FitAccounting()
    with acct.armed():
        ident = F.validate_sessions(fit_sessions, role="fit")
        bars = F.validate_fit_bars(fit_sessions)                                   # 1: refuses by name
        base = F.fit_baselines(fit_sessions)                                        # 2
        rows, ref, per_sess = F.eligible_rows_many(fit_sessions, base["vbar"], role="fit")   # 3
        if len(rows) < D.MIN_RESIDUALS:
            raise F.FeatureRefused("INSUFFICIENT_FIT_ROWS: %d eligible" % len(rows))
        _check_row_order(_keys(rows), "fit")
        consts = F.clipping_constants(rows)                                         # 4 (3 counted calls)
        clip = F.apply_clipping(rows, consts)                                       # 5
        # every input to the fits is checked BEFORE fitting, not only afterward
        rr = [r for r, _, _ in rows]
        ys = D.require_finite([y for _, y, _ in rows], "fit targets")
        for col in ("ret_1", "ret_5", "rv_30", "Bbar_c", "P_c", "F_c"):
            D.require_finite([r["features"][col] for r in rr], "fit feature %s" % col)
        rv = D.require_finite([r["features"]["rv_30"] for r in rr], "fit rv_30")
        pc = D.require_finite([r["features"]["P_c"] for r in rr], "fit P~")
        fits = M.fit_all(rows)                                                      # 6 (4 counted calls)
        mu_ax = D.require_finite(M.means_of(fits["specs"]["AX"], rr), "fit AX means")
        z = D.require_finite((ys - mu_ax) / rv, "fit reference residuals")            # 7
        d0 = D.fit_d0(z)
        d1 = D.fit_d1(z, pc, nu0=d0["nu0"], s0=d0["s0"])
    for spec in (d0, d1):
        D.check_scales(spec, rv, pc, "fit rows")
    return {"sessions": ident, "fit_bars": bars,
            "baselines": {k: v for k, v in base.items() if k != "vbar"}, "vbar": base["vbar"],
            "fit_refusals": ref, "fit_refusals_by_session": per_sess, "clipping": {**consts, **clip},
            "location": fits, "dispersion": {"D0": d0, "D1": d1, "reference": "AX residuals / rv_30 on the common fit rows"},
            "n_fit_rows": len(rows), "estimations": acct.report()}


# ---------------------------------------------------------------- development scoring

def _stat_record(diff, sess, keys, label, *, B, seed, blocks):
    """One comparison cell: HAC (with interval) and bootstrap (with percentile
    interval) plus sensitivities. Used for EVERY comparison, pairwise or not,
    so the contextual dispersion comparison reports the same contents."""
    d = D.require_finite(diff, "differential %s" % label)
    hac = I.hac_decision(d.tolist())
    boots = {}
    for L in blocks:
        r = BA.session_stationary_bootstrap_ext(d.tolist(), sess, expected_block_sessions=L, n_resamples=B,
                                                seed=seed, threshold=BOOT["p_threshold"])
        D.require_finite([r["mean"], r["boot_se"], r["p_one_sided"], r["percentile_interval"]["lower"],
                          r["percentile_interval"]["upper"]], "bootstrap %s L=%d" % (label, L))
        boots[str(L)] = BA.strip_arrays(r)
    prim = str(BOOT["expected_block_sessions"])
    return {"label": label, "n_rows": int(len(d)), "row_keys_sha": _keys_sha(keys), "hac": hac,
            "bootstrap": boots[prim], "bootstrap_sensitivities": {L: boots[L] for L in boots if L != prim}}


def _compare(ll, sess, a, b, sp, keys, *, B, seed, blocks):
    rec = _stat_record(ll[sp][a] - ll[sp][b], sess, keys, "%s-%s %s" % (a, b, sp), B=B, seed=seed, blocks=blocks)
    return {"pair": [a, b], "spec": sp, **rec}


def _dispersion_record(ll, sess, keys, *, B, seed, blocks):
    """Contextual: AX under D1 vs AX under D0 — same location, same nu."""
    rec = _stat_record(ll["D1"]["AX"] - ll["D0"]["AX"], sess, keys, "AX@D1 - AX@D0", B=B, seed=seed, blocks=blocks)
    return {"pair": "AX@D1 - AX@D0", "authority": "NONE (contextual)", **rec}


def _keys_sha(keys) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(keys, default=_json_default).encode()).hexdigest()[:16]


def _year_cell(year, rows_idx, ll, sess_all, keys_all, ref_by_year, *, B, seed):
    """One fixed report cell. NOT_AVAILABLE when a year has too few rows;
    otherwise every comparison, both specs, HAC + bootstrap, and dispersion."""
    cell = {"year": year, "n_rows": len(rows_idx), "refusals": ref_by_year.get(year),
            "min_rows_for_statistics": YEAR_MIN_ROWS}
    if len(rows_idx) < YEAR_MIN_ROWS:
        cell.update(status="NOT_AVAILABLE", why="%d eligible rows < %d" % (len(rows_idx), YEAR_MIN_ROWS),
                    comparisons=None, dispersion_improvement=None)
        return cell
    idx = np.array(rows_idx)
    sub_ll = {sp: {arm: ll[sp][arm][idx] for arm in ARMS} for sp in ll}
    sub_sess = [sess_all[i] for i in rows_idx]; sub_keys = [keys_all[i] for i in rows_idx]
    blocks = (BOOT["expected_block_sessions"], *BOOT["sensitivities"])
    comps = {name: {sp: _compare(sub_ll, sub_sess, a, b, sp, sub_keys, B=B, seed=seed, blocks=blocks)
                    for sp in ("D0", "D1")} for name, (a, b) in COMPARISONS.items()}
    # row-key identity is verified INSIDE this year cell, against this cell's own keys
    cell_sha, cell_n = _keys_sha(sub_keys), len(sub_keys)
    shas = {c[sp]["row_keys_sha"] for c in comps.values() for sp in ("D0", "D1")}
    ns = {c[sp]["n_rows"] for c in comps.values() for sp in ("D0", "D1")}
    if shas != {cell_sha} or ns != {cell_n}:
        raise F.FeatureRefused("YEAR_ROW_POPULATION_MISMATCH: %s expected sha %s n %d, saw %d key set(s), sizes %s"
                               % (year, cell_sha, cell_n, len(shas), sorted(ns)))
    cell["row_keys_sha"] = cell_sha
    disp = _dispersion_record(sub_ll, sub_sess, sub_keys, B=B, seed=seed, blocks=blocks)
    if disp["row_keys_sha"] != cell_sha or disp["n_rows"] != cell_n:
        raise F.FeatureRefused("YEAR_ROW_POPULATION_MISMATCH: %s dispersion cell" % year)
    cell.update(status="REPORTED", comparisons=comps, dispersion_improvement=disp)
    return cell


def score(prep: dict, dev_sessions: list, *, bootstrap_resamples: int = BOOT["resamples"],
          seed: int = BOOT["seed"]) -> dict:
    ident = F.validate_sessions(dev_sessions, role="development")
    rows, ref, per_sess = F.eligible_rows_many(dev_sessions, prep["vbar"], role="development")
    if len(rows) < MIN_DEV_ROWS:
        raise F.FeatureRefused("INSUFFICIENT_DEVELOPMENT_ROWS: %d eligible" % len(rows))
    keys = _keys(rows)
    _check_row_order(keys, "development")
    clip = F.apply_clipping(rows, prep["clipping"])
    rr = [r for r, _, _ in rows]
    ys = D.require_finite([y for _, y, _ in rows], "development targets")
    rv = D.require_finite([r["features"]["rv_30"] for r in rr], "development rv_30")
    pc = D.require_finite([r["features"]["P_c"] for r in rr], "development P~")
    sess = [r["session_id"] for r in rr]
    mus = {arm: D.require_finite(M.means_of(prep["location"]["specs"][arm], rr), "means %s" % arm) for arm in ARMS}
    ll = {}
    for sp in ("D0", "D1"):
        spec = prep["dispersion"][sp]
        D.check_scales(spec, rv, pc, "development rows")
        sc = D.scales(spec, rv, pc)
        ll[sp] = {arm: D.logpdf(ys, mus[arm], sc, spec["nu0"], label="log density %s %s" % (arm, sp)) for arm in ARMS}
    blocks = (BOOT["expected_block_sessions"], *BOOT["sensitivities"])
    comps = {name: {sp: _compare(ll, sess, a, b, sp, keys, B=bootstrap_resamples, seed=seed, blocks=blocks)
                    for sp in ("D0", "D1")} for name, (a, b) in COMPARISONS.items()}
    # row-key identity is COMPUTED across every comparison cell, not asserted
    shas = {c[sp]["row_keys_sha"] for c in comps.values() for sp in ("D0", "D1")}
    ns = {c[sp]["n_rows"] for c in comps.values() for sp in ("D0", "D1")}
    identical = (len(shas) == 1 and ns == {len(keys)})
    if not identical:
        raise F.FeatureRefused("ROW_POPULATION_MISMATCH: %d key sets, sizes %s" % (len(shas), sorted(ns)))
    p1 = comps["P1"]
    decisions = {"HAC_D0": p1["D0"]["hac"]["pass"], "BOOT_D0": p1["D0"]["bootstrap"]["pass"],
                 "HAC_D1": p1["D1"]["hac"]["pass"], "BOOT_D1": p1["D1"]["bootstrap"]["pass"]}
    cls = I.classify(decisions)
    fam = I.secondary_family({"%s_%s" % (s, sp): comps[s][sp]["hac"]["p_one_sided"] for s in SECONDARY for sp in ("D0", "D1")},
                             {"%s_%s" % (s, sp): comps[s][sp]["bootstrap"]["p_one_sided"] for s in SECONDARY for sp in ("D0", "D1")})
    disp_rec = _dispersion_record(ll, sess, keys, B=bootstrap_resamples, seed=seed, blocks=blocks)
    if disp_rec["row_keys_sha"] != _keys_sha(keys) or disp_rec["n_rows"] != len(keys):
        raise F.FeatureRefused("ROW_POPULATION_MISMATCH: dispersion comparison")
    # fixed per-year cells: every registered year is present, with refusals, or NOT_AVAILABLE
    ref_by_year = {}
    for sdate, r in per_sess.items():
        y = sdate[:4]
        ref_by_year[y] = r if y not in ref_by_year else {k: ref_by_year[y][k] + r[k] for k in r}
    per_year = {}
    for yr in REPORT_YEARS:
        idx = [i for i, k in enumerate(keys) if k[0].startswith(yr)]
        per_year[yr] = _year_cell(yr, idx, ll, sess, keys, ref_by_year, B=bootstrap_resamples, seed=seed)
    unregistered = sorted({k[0][:4] for k in keys} - set(REPORT_YEARS))
    theta = prep["location"]["specs"]["C"]["beta"][-1]
    out = {"sessions": ident, "development_refusals": ref, "development_refusals_by_session": per_sess,
           "clipping_applied": clip, "n_rows": len(rows),
           "row_key_population": {"n_keys": len(keys), "identical_across_all_comparisons": identical,
                                  "computed_from": "sha256 of each comparison cell's row keys", "key_sets": len(shas),
                                  "first": list(keys[0]), "last": list(keys[-1])},
           "comparisons": comps, "primary_decisions": decisions, "classification": cls,
           "secondary_family": fam, "dispersion_improvement": disp_rec,
           "per_year": per_year, "years_outside_registered_report": unregistered,
           "theta_F_c_in_C": {"value": theta, "meaning": "partial association on standardised F~, other regressors "
                                                          "fixed; mu_C - mu_AX != theta*F~ in general"}}
    strict_json(out)                                           # refuse NaN/Infinity before anything is sealed
    return out


def tournament(fit_sessions: list, dev_sessions: list, *, bootstrap_resamples: int = BOOT["resamples"],
               seed: int = BOOT["seed"]) -> dict:
    t0 = time.time()
    rec = {"experiment": EXPERIMENT_ID, "registration_hash": registration_hash(),
           "development_status": DEVELOPMENT_STATUS, "preprocessing_order": list(PREPROCESSING_ORDER),
           "budget_declared": BUDGET, "economics": "NONE (distributional only)"}
    try:
        F.validate_sessions(fit_sessions, role="fit")                     # registered fit range
        F.validate_sessions(dev_sessions, role="development")             # registered development range
        rec["periods"] = F.validate_disjoint(fit_sessions, dev_sessions)  # no shared or overlapping sessions
    except REFUSALS as e:
        return _refusal(type(e).__name__, str(e), "period_scope", rec)
    try:
        prep = prepare_fit(fit_sessions)
    except REFUSALS as e:
        return _refusal(type(e).__name__, str(e), "fit", rec)
    rec["fit"] = {k: v for k, v in prep.items() if k != "vbar"}
    try:
        dev = score(prep, dev_sessions, bootstrap_resamples=bootstrap_resamples, seed=seed)
    except REFUSALS as e:
        return _refusal(type(e).__name__, str(e), "development", rec)
    rec["development"] = dev
    rec["status"] = dev["classification"]["outcome"]
    rec["elapsed_s"] = round(time.time() - t0, 2)
    strict_json(rec)
    return rec
