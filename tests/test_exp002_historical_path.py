"""EXP-002 through the REAL governed path: disposable authority, synthetic
inputs, nothing stubbed.

checkout_root is THIS repository, so source identity and import provenance are
verified for real. That requires a clean bound tree: the module refuses to run
against uncommitted bound-path changes rather than silently skipping.
"""
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apex.world_model.exp001b.registration import EXPERIMENT_ID as EXP001B_ID
from apex.world_model.exp001b.registration import registration_hash as exp001b_hash
from apex.world_model.exp002.registration import EXPERIMENT_ID as EXP002_ID, RV_FLOOR, registration_hash
from apex.world_model.real_data import loader
from apex.world_model.real_data import boundary, manifest
from apex.world_model.real_data.boundary import RealDataRefused, TrustConfig

REPO = Path(__file__).resolve().parents[1]
AVAIL = {"event_time": {"kind": "PER_ROW", "latest": "2021-12-31"},
         "receipt_time": {"kind": "BULK", "at": "2022-01-03"},
         "publication_time": {"kind": "NOT_AVAILABLE"},
         "revision_time": {"kind": "NOT_AVAILABLE"},
         "corporate_actions": "RAW_UNADJUSTED_EXPLICIT",
         "restricted_use": "HISTORICAL_RESEARCH_ONLY: synthetic fixture for the acceptance test"}

# session days on real trading dates, one per role, plus an evaluation trap
FIT_DAYS = ["2017-03-01", "2017-03-02", "2017-03-03", "2017-03-06", "2017-03-07"]
DEV_DAYS = ["2019-06-03", "2019-06-04", "2019-06-05", "2019-06-06"]
OBS_DAYS = ["2020-06-01", "2020-06-02", "2020-06-03"]
EVAL_TRAP = ["2023-06-01"]


def _git(*a, cwd=REPO):
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, check=True).stdout.strip()


def _bound_tree_clean() -> bool:
    return boundary.source_identity(REPO)["dirty"] == []


def _require_clean():
    ident = boundary.source_identity(REPO)
    if ident["dirty"]:
        pytest.fail("ACCEPTANCE TEST REQUIRES A CLEAN BOUND TREE; commit first. dirty=%s" % ident["dirty"][:5])
    return ident


FLAT = {FIT_DAYS[0]: (120, 60)}      # minutes [120,180) identical closes -> rv_30 == 0 rows below RV_FLOOR


def _session(day: str, seed: int, signal: float = 0.0, flat: dict = FLAT):
    """Bars aligned to the calendar's open for admitted-window days. The
    evaluation TRAP lies outside the calendar's verified window, which the
    calendar correctly refuses; that file only has to EXIST so the loader could
    list it, so it is built at a fixed start without consulting the calendar."""
    from apex.world_model.exp001b import exchange_calendar as C
    if day in EVAL_TRAP:
        t0, minutes = datetime.fromisoformat(day + "T13:30:00+00:00"), 390
    else:
        b = C.session_bounds(day, require_verified=True)
        t0, minutes = datetime.fromtimestamp(b["open_utc"], timezone.utc), int(b["regular_minutes"])
    rng = random.Random(seed)
    px, bars, last = 400.0, [], 0.0
    fl = (flat or {}).get(day)
    for i in range(minutes):
        r = signal * last + rng.gauss(0, 3e-4); last = r
        if fl and fl[0] <= i < fl[0] + fl[1]:
            r = 0.0                                       # identical closes: volatility exactly zero
        o = px * math.exp(rng.gauss(0, 5e-5)); px = px * math.exp(r)
        bars.append({"event_time_utc": (t0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": max(o, px) * 1.0001, "low": min(o, px) * 0.9999,
                     "close": px, "volume": 1000})
    return {"source": "alpaca_sip_raw_1m", "bars": bars}


@pytest.fixture
def rig(tmp_path):
    ident = _require_clean()
    ds = tmp_path / "dataset" / "bars"; ds.mkdir(parents=True)
    for i, d in enumerate(FIT_DAYS + DEV_DAYS + OBS_DAYS + EVAL_TRAP):
        (ds / ("SPY_%s.json" % d)).write_text(json.dumps(_session(d, seed=100 + i)))
    man = manifest.build(ds, dataset_id="fixture/etf", source_families=["alpaca_sip_raw_1m"], availability=AVAIL)
    mpath = tmp_path / "manifest.json"; msha = manifest.write(man, mpath)
    keys = tmp_path / "authority"; keys.mkdir()
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "key"), "-C", "t"], check=True)
    trust_dir = tmp_path / "trust"; trust_dir.mkdir(); os.chmod(trust_dir, 0o755)
    pub = (keys / "key.pub").read_text().split()
    signers = trust_dir / "allowed_signers"
    signers.write_text('test-reviewer namespaces="apex-admission" %s %s\n' % (pub[0], pub[1])); os.chmod(signers, 0o644)
    aroot = tmp_path / "admissions"; aroot.mkdir(); os.chmod(aroot, 0o755)
    trust = TrustConfig(admission_root=aroot, allowed_signers=signers, checkout_root=REPO,
                        permitted_roots=(str(tmp_path / "dataset"),), enforce_ownership=False)
    return {"tmp": tmp_path, "ident": ident, "ds": ds, "mpath": mpath, "msha": msha, "keys": keys,
            "aroot": aroot, "out": tmp_path / "out", "trust": trust}


def _body(rig, *, experiment=EXP002_ID, reg=None, **over):
    b = {"contract": boundary.REAL_DATA_CONTRACT, "decision": "ADMIT",
         "dataset": {"dataset_id": "fixture/etf", "root": str(rig["ds"]), "manifest_path": str(rig["mpath"]),
                     "manifest_sha256": rig["msha"]},
         "scope": {"source_families": ["alpaca_sip_raw_1m"],
                   "fields": ["open", "high", "low", "close", "volume", "event_time_utc"], "universe": ["SPY"],
                   "temporal_range": {"start": "2016-01-04", "end": "2021-12-31"}},
         "availability": json.loads(json.dumps(AVAIL)),
         "purpose": {"research_purpose": "EXP-002 acceptance on fixture", "experiment_id": experiment,
                     "registration_hash": reg or registration_hash()},
         "code": {"commit": rig["ident"]["commit"], "source_tree_sha256": rig["ident"]["tree_sha256"]},
         "output": {"root": str(rig["out"]), "authority_classification": "RESEARCH_HISTORICAL"},
         "provenance": {"decided_by": "test-reviewer", "decided_utc": "2026-09-09T05:00:00Z", "review_reference": "T"}}
    for k, v in over.items():
        sec, _, leaf = k.partition("__")
        if leaf:
            b[sec][leaf] = v
        else:
            b[sec] = v
    return b


def _write(rig, body, *, name="d.json", sign=True):
    p = rig["aroot"] / name
    p.write_text(json.dumps(body, indent=1)); os.chmod(p, 0o644)
    sig = p.with_name(p.name + ".sig")
    if sig.exists():
        sig.unlink()
    if sign:
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(rig["keys"] / "key"), "-n", "apex-admission", str(p)],
                       check=True, capture_output=True)
    return p


def _cmd():
    spec = importlib.util.spec_from_file_location("alpha_exp_real_execute", REPO / "scripts/alpha_exp_real_execute.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def _run(rig, p, capsys, *extra):
    mod = _cmd()
    rc = mod.main(["--experiment", EXP002_ID, "--decision", str(p), *extra], trust=rig["trust"])
    return rc, json.loads(capsys.readouterr().out)


# --------------------------------------------------------------- the tests

def test_plan_opens_nothing_and_never_lists_a_sealed_period(rig, capsys, monkeypatch):
    monkeypatch.setattr(boundary, "open_file", lambda *a, **k: (_ for _ in ()).throw(AssertionError("row opened")))
    rc, doc = _run(rig, _write(rig, _body(rig)), capsys, "--plan")
    assert rc == 0 and doc["status"] == "PLAN" and doc["experiment"] == EXP002_ID
    assert doc["sessions"] == {"fit": 5, "development": 4, "observed": 3}
    assert "evaluation" not in doc["sessions"]
    assert set(doc["sealed_periods_never_requested"]) == {"evaluation", "reserve"}


def test_execute_uses_the_roles_correctly_and_never_opens_evaluation(rig, capsys, monkeypatch):
    opened = []
    real = boundary.open_file
    def spy(grant, path, **kw):
        opened.append(kw["session_date"]); return real(grant, path, **kw)
    monkeypatch.setattr(boundary, "open_file", spy)
    rc, doc = _run(rig, _write(rig, _body(rig)), capsys, "--execute")
    assert doc["process_outcome"] == "SCIENTIFIC_COMPLETE", doc
    assert rc == 0
    assert set(opened) == set(FIT_DAYS + DEV_DAYS + OBS_DAYS)
    assert not any(d >= "2022-01-01" for d in opened)          # evaluation trap never opened
    res = json.loads((Path(doc["run_dir"]) / "_RESULT.json").read_text())
    assert res["period_roles"]["fit"] == ["2016-01-04", "2018-12-31"]
    assert res["period_roles"]["development"] == ["2019-01-01", "2019-12-31"]
    assert res["development"]["authority"] == "SELECTION"
    assert res["observed"]["authority"] == "NONE"
    assert res["observed"]["comparisons"]["G1"]["promotion_authority"] is False
    assert res["evaluation"].startswith("SEALED")
    assert res["economics"].startswith("NONE")
    assert res["execution"] == {"observed_requested": True, "observed_outcome": "REPORTED_WITHOUT_SELECTION_AUTHORITY",
                                "failure": None, "complete": True}
    assert res["scientific_status"] == res["development"]["status"] == res["status"]
    assert res["observed"]["status"] in ("MATCHED_IMPROVEMENT", "NOT_SELECTED", "NOT_SELECTED_INFERENCE_DISAGREEMENT")


def test_exactly_five_fits_even_with_the_secondary_period(rig, capsys):
    rc, doc = _run(rig, _write(rig, _body(rig)), capsys, "--execute")
    res = json.loads((Path(doc["run_dir"]) / "_RESULT.json").read_text())
    assert res["fit"]["fits_performed"] == 5 == res["fits_performed_total"]
    assert res["fit"]["within_budget"] is True
    # the observed period was scored with the SAME params: identical params_hash, no new fit key
    assert "fit" not in res["observed"]
    assert res["development"]["comparisons"]["G1"]["pair"] == ["C", "L"]


def test_import_provenance_is_verified_for_real_not_stubbed(rig, capsys):
    rc, doc = _run(rig, _write(rig, _body(rig)), capsys, "--execute")
    res = json.loads((Path(doc["run_dir"]) / "_RESULT.json").read_text())
    imp = res["imports_at_start"]
    assert imp["all_imports_match_admitted_commit"] is True
    assert imp["n_modules"] > 0 and "apex.world_model.exp002.run" in " ".join(map(str, imp.get("verified", [])))
    assert res["acceptance_qualification"] == "VALID"


def test_an_exp001b_admission_cannot_authorise_exp002(rig, capsys):
    p = _write(rig, _body(rig, experiment=EXP001B_ID, reg=exp001b_hash()), name="d1b.json")
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 3 and doc["process_outcome"] == "AUTHORIZATION_REFUSED"
    assert doc["refusal"].startswith("EXPERIMENT_MISMATCH")
    p2 = _write(rig, _body(rig, reg=exp001b_hash()), name="d2.json")     # right experiment, wrong registration
    rc, doc = _run(rig, p2, capsys, "--execute")
    assert rc == 3 and doc["refusal"].startswith("REGISTRATION_MISMATCH")


def test_signature_and_source_refusals(rig, capsys):
    p = _write(rig, _body(rig), sign=False)
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 3 and doc["refusal"].startswith("UNSIGNED_DECISION")
    # and a signature by a key NOT in allowed_signers is refused as invalid
    other = rig["tmp"] / "otherkey"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(other), "-C", "x"], check=True)
    p = _write(rig, _body(rig), name="dbad.json", sign=False)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(other), "-n", "apex-admission", str(p)], check=True, capture_output=True)
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 3 and doc["refusal"].startswith("SIGNATURE_INVALID")
    p = _write(rig, _body(rig, code__commit="0" * 40), name="dc.json")
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 3 and doc["refusal"].startswith("CODE_IDENTITY_MISMATCH")
    p = _write(rig, _body(rig, code__source_tree_sha256="1" * 64), name="dt.json")
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 3 and doc["refusal"].startswith("SOURCE_IDENTITY_MISMATCH")
    assert not rig["out"].exists()                                   # nothing was written on refusal


def test_result_is_sealed_once_and_bound_to_launch(rig, capsys):
    p = _write(rig, _body(rig))
    rc, doc = _run(rig, p, capsys, "--execute")
    d = Path(doc["run_dir"])
    with pytest.raises(RealDataRefused, match="RESULT_EXISTS"):
        boundary.seal_result(d, {"status": "again"})
    runrec = json.loads((d / "_RUN.json").read_text())
    assert runrec["decision_sha256"] == boundary.sha256_of(p)
    # the launcher's binding check accepts it under the right experiment and rejects the wrong one
    spec = importlib.util.spec_from_file_location("_ra", REPO / "scripts" / "research_activation.py")
    RA = importlib.util.module_from_spec(spec); sys.modules["_ra"] = RA; spec.loader.exec_module(RA)
    tg = RA.Targets(research_root=rig["out"].parent)
    got = [c for c in RA._sealed_results_for(tg, boundary.sha256_of(p), set(), EXP002_ID) if c.get("counted")]
    assert got and got[0]["run_id"] == d.name
    assert not [c for c in RA._sealed_results_for(tg, boundary.sha256_of(p), set(), EXP001B_ID) if c.get("counted")]


def test_failure_exit_propagates_and_is_sealed(rig, capsys, monkeypatch):
    from apex.world_model.exp002 import historical as H2
    monkeypatch.setattr(H2, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaboom in exp002")))
    rc, doc = _run(rig, _write(rig, _body(rig)), capsys, "--execute")
    assert rc == 5 and doc["process_outcome"] == "INVALID_INPUT_OR_FAILURE"
    res = json.loads((Path(doc["run_dir"]) / "_RESULT.json").read_text())
    assert res["status"] == "EXECUTION_FAILURE" and "kaboom in exp002" in res["error"]


def test_launcher_names_the_experiment_on_every_command(rig):
    spec = importlib.util.spec_from_file_location("_ra2", REPO / "scripts" / "research_activation.py")
    RA = importlib.util.module_from_spec(spec); sys.modules["_ra2"] = RA; spec.loader.exec_module(RA)
    t = RA.production_targets()
    oc = RA.operator_commands(t, "abc", Path("/etc/apex/admissions/x.json"), EXP002_ID)
    assert "--experiment ALPHA-EXP-002" in oc["prepare"] and oc["execute"] == oc["prepare"] + " --apply"
    assert RA.registration_hash_for(EXP002_ID, REPO) == registration_hash()
    assert RA.registration_hash_for(EXP001B_ID, REPO) == exp001b_hash()


def test_the_real_path_from_a_fresh_clone_in_a_child_process(rig, tmp_path):
    """Strongest form: clone this repo, run the execute script FROM the clone in
    a child interpreter whose checkout_root is the clone. Import provenance and
    source identity are verified against the clone's own commit, nothing stubbed.
    Then dirty one bound file in the clone and require SOURCE_DIRTY."""
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(REPO), str(clone)], check=True)
    assert _git("rev-parse", "HEAD", cwd=clone) == rig["ident"]["commit"]
    driver = tmp_path / "driver.py"
    driver.write_text(textwrap.dedent(f"""
        import json, os, subprocess, sys
        sys.path.insert(0, {str(clone)!r})
        os.chdir({str(clone)!r})
        from pathlib import Path
        from apex.world_model.real_data import boundary
        from apex.world_model.real_data.boundary import TrustConfig
        from apex.world_model.exp002.registration import registration_hash
        import importlib.util
        ident = boundary.source_identity(Path({str(clone)!r}))
        body = json.load(open({str(rig['aroot'] / 'd.json')!r})) if False else None
        # build the decision against the CLONE's identity
        import json as _j
        b = _j.loads(Path(sys.argv[1]).read_text())
        b["code"] = {{"commit": ident["commit"], "source_tree_sha256": ident["tree_sha256"]}}
        b["purpose"]["registration_hash"] = registration_hash()
        b["output"]["root"] = sys.argv[2]
        dec = Path(sys.argv[3]); dec.write_text(_j.dumps(b, indent=1)); os.chmod(dec, 0o644)
        sig = dec.with_name(dec.name + ".sig")
        if sig.exists(): sig.unlink()
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", sys.argv[4], "-n", "apex-admission", str(dec)], check=True, capture_output=True)
        trust = TrustConfig(admission_root=dec.parent, allowed_signers=Path(sys.argv[5]), checkout_root=Path({str(clone)!r}),
                            permitted_roots=(sys.argv[6],), enforce_ownership=False)
        spec = importlib.util.spec_from_file_location("x", Path({str(clone)!r}) / "scripts/alpha_exp_real_execute.py")
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = m.main(["--experiment", "ALPHA-EXP-002", "--decision", str(dec), "--execute"], trust=trust)
        print(json.dumps({{"rc": rc, "doc": json.loads(buf.getvalue()), "clone_commit": ident["commit"],
                          "boundary_file": boundary.__file__}}))
    """))
    template = rig["aroot"] / "template.json"
    template.write_text(json.dumps(_body(rig)))
    out1 = tmp_path / "out_clone"
    env = {**os.environ, "PYTHONPATH": str(clone)}
    args = [sys.executable, str(driver), str(template), str(out1), str(rig["aroot"] / "dclone.json"),
            str(rig["keys"] / "key"), str(rig["trust"].allowed_signers), str(rig["tmp"] / "dataset")]
    r = subprocess.run(args, capture_output=True, text=True, env=env, timeout=1200)
    assert r.returncode == 0, r.stderr[-2000:]
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert res["boundary_file"].startswith(str(clone)), res["boundary_file"]     # the clone's modules ran
    assert res["rc"] == 0 and res["doc"]["process_outcome"] == "SCIENTIFIC_COMPLETE", res["doc"]
    sealed = json.loads((Path(res["doc"]["run_dir"]) / "_RESULT.json").read_text())
    assert sealed["imports_at_start"]["all_imports_match_admitted_commit"] is True
    assert sealed["source_identity_at_completion"]["unchanged"] is True
    # now dirty a BOUND file in the clone: the same decision must be refused as SOURCE_DIRTY
    (clone / "apex/world_model/exp002/registration.py").write_text(
        (clone / "apex/world_model/exp002/registration.py").read_text() + "\n# dirt\n")
    r2 = subprocess.run(args, capture_output=True, text=True, env=env, timeout=600)
    res2 = json.loads(r2.stdout.strip().splitlines()[-1])
    assert res2["rc"] == 3 and res2["doc"]["refusal"].startswith("SOURCE_DIRTY"), res2["doc"]


# ------------------------------------------------ integration repair (review findings)

def _grant_and_sessions(rig, p):
    from apex.world_model.exp002 import historical as H2
    grant = boundary.verify_decision_with(p, rig["trust"], experiment_id=EXP002_ID, registration_hash=registration_hash())
    return grant, loader.sessions_by_period(grant, H2.PERIOD_ROLES, symbol="SPY"), loader.loader_for(grant)


def test_fit_admission_uses_the_qualified_rule_and_reproduces_tournament_params(rig, capsys):
    """Finding 1. The fixture's first fit day carries rows with rv_30 == 0 (< RV_FLOOR).
    They are feature/target-usable, so the old adapter fitted on them while
    scoring refused them. Now the same `_admit` governs both, and the fitted
    params equal what the qualified `tournament()` produces on the same rows."""
    from apex.world_model.exp002 import historical as H2
    from apex.world_model.exp002.run import _admit, tournament
    p = _write(rig, _body(rig))
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 0, doc
    res = json.loads((Path(doc["run_dir"]) / "_RESULT.json").read_text())
    adm = next(s for s in res["stages"] if s["stage"] == "admission:fit")
    assert adm["refused_rows"]["RV_FLOOR"] > 0, adm                     # the mismatch condition exists
    assert adm["admitted_rows"] == adm["usable_rows"] - adm["refused_rows"]["RV_FLOOR"]
    assert res["fit"]["n_train"] == adm["admitted_rows"]                # fitted on admitted rows only
    # independent recomputation on freshly loaded rows: usable rows do contain
    # below-floor volatility, and the qualified runner's fit is identical
    _, sbp, ld = _grant_and_sessions(rig, p)
    fit_usable, _ = H2._rows_for(sbp["fit"], ld)
    dev_usable, _ = H2._rows_for(sbp["development"], ld)
    assert any(r["features"]["rv_30"] < RV_FLOOR for r, _, _ in fit_usable)
    admitted, refused = _admit(fit_usable)
    assert (len(admitted), refused) == (adm["admitted_rows"], adm["refused_rows"]["RV_FLOOR"])
    q = tournament(fit_usable, dev_usable, bootstrap_resamples=50)      # fit is independent of resamples
    assert q["fit"]["params_hash"] == res["fit"]["params_hash"]
    assert q["fit"]["n_train"] == res["fit"]["n_train"]
    assert q["admission"]["fit_refused_rv_floor"] == adm["refused_rows"]["RV_FLOOR"]
    # the persisted params object IS the fitted object (same hash recomputed from its content)
    saved = res["fit"]["params"]
    import hashlib
    rehash = hashlib.sha256(json.dumps({k: v for k, v in saved.items() if k != "params_hash"},
                                       sort_keys=True, default=float).encode()).hexdigest()[:16]
    assert rehash == saved["params_hash"] == res["fit"]["params_hash"]


def test_fit_budget_by_recording_spy_on_the_real_fitters(rig, capsys, monkeypatch):
    """Finding 4. Spies delegate to the real fitters and record every call in
    order: one fit_arms invocation, its four underlying fitter calls (M0+M1 in
    one baseline fit, L, C, t = five model fits), no fitter after the first
    forecast, and forecasts in both periods built from the same params."""
    from apex.world_model.exp002 import models as A, studentt as T
    from apex.world_model.exp001b import models as M01
    events = []
    def spy(mod, name, label):
        real = getattr(mod, name)
        def w(*a, **k):
            out = real(*a, **k)
            if label == "forecast":
                events.append(("forecast", k["input_id"].split("|")[0], a[1]["params_hash"], id(a[1])))
            else:
                events.append((label, out["params_hash"] if isinstance(out, dict) and "params_hash" in out else None))
            return out
        monkeypatch.setattr(mod, name, w)
    spy(A, "fit_arms", "fit_arms"); spy(M01, "fit", "baseline_fit"); spy(A, "_fit_lstsq", "lstsq")
    spy(T, "fit_scale_nu", "student_t_fit"); spy(A, "forecast", "forecast")
    rc, doc = _run(rig, _write(rig, _body(rig)), capsys, "--execute")
    assert rc == 0, doc
    res = json.loads((Path(doc["run_dir"]) / "_RESULT.json").read_text())
    fits = [e for e in events if e[0] != "forecast"]
    assert [e[0] for e in fits] == ["baseline_fit", "lstsq", "lstsq", "student_t_fit", "fit_arms"]
    assert fits[-1][1] == res["fit"]["params_hash"]
    first_fc = next(i for i, e in enumerate(events) if e[0] == "forecast")
    assert all(e[0] == "forecast" for e in events[first_fc:])              # no refit after scoring began
    tags = {e[1] for e in events if e[0] == "forecast"}
    assert tags == {"DEVELOPMENT_2019", "OBSERVED_2020_2021"}
    assert {e[2] for e in events if e[0] == "forecast"} == {res["fit"]["params_hash"]}
    assert len({e[3] for e in events if e[0] == "forecast"}) == 1        # the same object, not a copy
    assert res["development"]["params_hash"] == res["observed"]["params_hash"] == res["fit"]["params_hash"]


def _incomplete_common(rig, p, doc, rc_expected, outcome, status, failure_class):
    assert doc["process_outcome"] == outcome and rc_expected == doc.get("exit", rc_expected)
    res = json.loads((Path(doc["run_dir"]) / "_RESULT.json").read_text())
    assert res["status"] == status
    assert res["execution"]["complete"] is False
    assert res["execution"]["observed_outcome"] == "NOT_REPORTED"
    assert res["execution"]["failure"]["class"] == failure_class
    assert res["observed"]["status"] == "NOT_EVALUATED"
    # development evidence preserved, verdict distinct from completion
    assert res["scientific_status"] in ("MATCHED_IMPROVEMENT", "NOT_SELECTED", "NOT_SELECTED_INFERENCE_DISAGREEMENT")
    assert res["development"]["status"] == res["scientific_status"]
    assert "G1" in res["development"]["comparisons"] and res["development"]["null_control_ok"] is True
    assert res["process_outcome"] == outcome
    # the launcher does not count it as a completed result
    spec = importlib.util.spec_from_file_location("_ra3", REPO / "scripts" / "research_activation.py")
    RA = importlib.util.module_from_spec(spec); sys.modules["_ra3"] = RA; spec.loader.exec_module(RA)
    got = RA._sealed_results_for(RA.Targets(research_root=rig["out"].parent), boundary.sha256_of(p), set(), EXP002_ID)
    assert got and not any(c.get("counted") for c in got), got
    return res


def test_observed_admission_refusal_is_incomplete_not_success(rig, capsys, monkeypatch):
    """Finding 2a. A file-integrity refusal on an observed session."""
    real = boundary.open_file
    def refusing(grant, path, **kw):
        if kw["session_date"] >= "2020-01-01":
            raise RealDataRefused("FILE_INTEGRITY: %s does not match the manifest" % Path(path).name)
        return real(grant, path, **kw)
    monkeypatch.setattr(boundary, "open_file", refusing)
    p = _write(rig, _body(rig))
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 3
    res = _incomplete_common(rig, p, doc, 3, "AUTHORIZATION_REFUSED", "INCOMPLETE_OBSERVED_ADMISSION_REFUSED", "ADMISSION_REFUSED")
    assert res["execution"]["failure"]["kind"] == "RealDataRefused" and "FILE_INTEGRITY" in res["execution"]["failure"]["detail"]
    assert "observed" not in [s["stage"] for s in res["stages"]]


def test_observed_scoring_exception_is_incomplete_not_success(rig, capsys, monkeypatch):
    """Finding 2b. An exception inside observed scoring."""
    from apex.world_model.exp002 import historical as H2
    real = H2.evaluate
    def failing(params, rows, **kw):
        if kw["tag"].startswith("OBSERVED"):
            raise ZeroDivisionError("scoring blew up on observed")
        return real(params, rows, **kw)
    monkeypatch.setattr(H2, "evaluate", failing)
    p = _write(rig, _body(rig))
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 5
    res = _incomplete_common(rig, p, doc, 5, "INVALID_INPUT_OR_FAILURE", "INCOMPLETE_OBSERVED_REPORTING", "EXCEPTION")
    assert res["execution"]["failure"]["kind"] == "ZeroDivisionError"


def test_observed_invalid_result_is_incomplete_not_success(rig, capsys, monkeypatch):
    """Finding 2c. Observed evaluation returns an invalid status."""
    from apex.world_model.exp002 import historical as H2
    real = H2.evaluate
    def invalid(params, rows, **kw):
        out = real(params, rows, **kw)
        if kw["tag"].startswith("OBSERVED"):
            out["status"] = "INVALID_NULL_CONTROL"; out["null_control_ok"] = False
        return out
    monkeypatch.setattr(H2, "evaluate", invalid)
    p = _write(rig, _body(rig))
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 5
    res = _incomplete_common(rig, p, doc, 5, "INVALID_INPUT_OR_FAILURE", "INCOMPLETE_OBSERVED_REPORTING", "INVALID_RESULT")
    assert res["execution"]["failure"]["kind"] == "INVALID_NULL_CONTROL"


def test_forecast_hashes_reconstruct_from_saved_artifacts(rig, capsys):
    """Evidence item. From the sealed result (exact fitted params, per-period
    creation time) and freshly admitted rows, every recorded forecast hash is
    rebuilt and matches the sealed ledger; a perturbed params object does not."""
    from apex.world_model.exp002 import historical as H2
    p = _write(rig, _body(rig))
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 0, doc
    run_dir = Path(doc["run_dir"])
    res = json.loads((run_dir / "_RESULT.json").read_text())
    for period in ("development", "observed"):
        assert isinstance(res[period]["forecast_creation_time"], float)
        assert res[period]["forecast_identity"]["content_hash_excludes_creation_time"] is True
    _, sbp, ld = _grant_and_sessions(rig, p)
    rep = H2.reconstruct(res, sbp, session_loader=ld, ledger_dir=run_dir)
    assert rep["all_match"] is True and rep["status"] == "VERIFIED", rep
    assert rep["required_periods"] == rep["verified_periods"] == ["development", "observed"]
    assert rep["missing"] == []
    for period in ("development", "observed"):
        r = rep["periods"][period]
        assert r["status"] == "VERIFIED"
        assert r["rows_admitted"] == r["rows_in_ledger"] == r["matched_rows"] == res[period]["n_dev"] > 0
        assert r["mismatched_rows"] == 0 and r["unmatched_rows"] == 0
        assert r["creation_time_used"] == res[period]["forecast_creation_time"]
        assert r["ledger_order_matches_admitted"] is True and r["chain_integrity_verified"] is False
    assert rep["ledger_ordering_matches"] is True
    assert "NOT VERIFIED" in rep["verifies"]["chain_integrity"]
    # negative: BOTH required periods lack reconstruction metadata -> never a false success
    none = json.loads(json.dumps(res))
    for period in ("development", "observed"):
        none[period].pop("forecast_creation_time")
    rep_none = H2.reconstruct(none, sbp, session_loader=ld, ledger_dir=run_dir)
    assert rep_none["all_match"] is False and rep_none["status"] == "NOT_VERIFIED"
    assert rep_none["verified_periods"] == [] and set(rep_none["missing"]) == {
        "development.forecast_creation_time", "observed.forecast_creation_time"}
    assert all(rep_none["periods"][p]["status"] == "NOT_VERIFIED" for p in ("development", "observed"))
    # negative: ONE required period missing -> the other alone cannot carry overall success
    one = json.loads(json.dumps(res)); one["observed"].pop("forecast_creation_time")
    rep_one = H2.reconstruct(one, sbp, session_loader=ld, ledger_dir=run_dir)
    assert rep_one["all_match"] is False and rep_one["status"] == "NOT_VERIFIED"
    assert rep_one["verified_periods"] == ["development"] and rep_one["missing"] == ["observed.forecast_creation_time"]
    assert rep_one["periods"]["development"]["status"] == "VERIFIED"
    # a missing ledger artifact is a missing artifact, not a pass
    (run_dir / "forecast_hashes_OBSERVED_2020_2021.jsonl").rename(run_dir / "moved.jsonl")
    rep_led = H2.reconstruct(res, sbp, session_loader=ld, ledger_dir=run_dir)
    assert rep_led["status"] == "NOT_VERIFIED" and rep_led["missing"] == ["observed.ledger"]
    (run_dir / "moved.jsonl").rename(run_dir / "forecast_hashes_OBSERVED_2020_2021.jsonl")
    # requirement is derived from the saved execution record: observed not requested -> not required
    dev_only = json.loads(json.dumps(res)); dev_only["execution"]["observed_requested"] = False; dev_only.pop("observed")
    rep_dev = H2.reconstruct(dev_only, sbp, session_loader=ld, ledger_dir=run_dir)
    assert rep_dev["required_periods"] == ["development"] and rep_dev["status"] == "VERIFIED"
    # no saved params -> nothing can be verified
    nop = json.loads(json.dumps(res)); nop["fit"].pop("params")
    rep_nop = H2.reconstruct(nop, sbp, session_loader=ld, ledger_dir=run_dir)
    assert rep_nop["status"] == "NOT_VERIFIED" and rep_nop["verified_periods"] == [] and "fit.params" in rep_nop["missing"]
    # negative control: the check has teeth
    bad = json.loads(json.dumps(res["fit"]["params"]))
    bad["t"]["s"] *= 1.01
    rep_bad = H2.reconstruct(res, sbp, session_loader=ld, ledger_dir=run_dir, params=bad)
    assert rep_bad["all_match"] is False and rep_bad["status"] == "NOT_VERIFIED"
    assert all(r["status"] == "MISMATCH" and r["matched_rows"] == 0 for r in rep_bad["periods"].values())
    assert all(set(m["arms_differing"]) == {"S", "L", "C"} for m in rep_bad["periods"]["development"]["mismatched"])
