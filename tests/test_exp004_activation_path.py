"""EXP-004 through the REAL governed path and the activation wrapper:
disposable authority, synthetic admitted files, nothing stubbed.

checkout_root is THIS repository, so source identity and import provenance are
verified for real. That requires a clean bound tree: the module refuses to run
against uncommitted bound-path changes rather than silently skipping.

No admission exists, nothing is signed by the real authority, and no historical
data is touched. The admitted files here are synthetic bars in a tmp_path.
"""
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from apex.world_model.exp002.registration import EXPERIMENT_ID as EXP002_ID
from apex.world_model.exp002.registration import registration_hash as exp002_hash
from apex.world_model.exp004 import historical as H4
from apex.world_model.exp004.registration import EXPERIMENT_ID as EXP004_ID, PERIODS, registration_hash
from apex.world_model.exp001b import exchange_calendar as C
from apex.world_model.real_data import boundary, manifest
from apex.world_model.real_data.boundary import RealDataRefused, TrustConfig

REPO = Path(__file__).resolve().parents[1]
SEED = 20260914
N_FIT = 112                     # > the registered baseline support of 100 unique sessions
N_DEV = 6
AVAIL = {"event_time": {"kind": "PER_ROW", "latest": "2021-12-31"},
         "receipt_time": {"kind": "BULK", "at": "2022-01-03"},
         "publication_time": {"kind": "NOT_AVAILABLE"},
         "revision_time": {"kind": "NOT_AVAILABLE"},
         "corporate_actions": "RAW_UNADJUSTED_EXPLICIT",
         "restricted_use": "HISTORICAL_RESEARCH_ONLY: synthetic fixture for the EXP-004 activation test"}


def _require_clean():
    ident = boundary.source_identity(REPO)
    if ident["dirty"]:
        pytest.fail("REQUIRES A CLEAN BOUND TREE; commit first. dirty=%s" % ident["dirty"][:5])
    return ident


def _days(start: str, n: int) -> list:
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            try:
                C.session_bounds(d.isoformat(), require_verified=True)
                out.append(d.isoformat())
            except C.NotASession:
                pass
        d += timedelta(days=1)
    return out


def _bars(day: str, seed: int) -> dict:
    b = C.session_bounds(day, require_verified=True)
    t0, minutes = datetime.fromtimestamp(b["open_utc"], timezone.utc), int(b["regular_minutes"])
    rng = random.Random(seed)
    px, bars = 400.0, []
    for i in range(minutes):
        c = px * math.exp(rng.gauss(0, 3e-4)); px = c
        o = c - rng.uniform(-1, 1) * abs(rng.gauss(0, 2e-4)) * c
        wick = abs(rng.gauss(0, 1.5e-4)) * c
        u = (i - minutes / 2) / (minutes / 2)
        bars.append({"event_time_utc": (t0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": max(o, c) + wick, "low": min(o, c) - wick, "close": c,
                     "volume": float(int((60_000 * (1 + 2.5 * u * u)) * math.exp(rng.gauss(0, 0.35))))})
    return {"source": "alpaca_sip_raw_1m", "bars": bars}


@pytest.fixture(scope="module")
def rig(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("exp004act")
    ident = _require_clean()
    ds = tmp / "dataset" / "bars"; ds.mkdir(parents=True)
    fit_days = _days(PERIODS["fit"][0], N_FIT)
    dev_days = _days(PERIODS["development"][0], N_DEV)
    for i, d in enumerate(fit_days + dev_days):
        (ds / ("SPY_%s.json" % d)).write_text(json.dumps(_bars(d, SEED + i)))
    man = manifest.build(ds, dataset_id="fixture/exp004", source_families=["alpaca_sip_raw_1m"], availability=AVAIL)
    mpath = tmp / "manifest.json"; msha = manifest.write(man, mpath)
    keys = tmp / "authority"; keys.mkdir()
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "key"), "-C", "t"], check=True)
    trust_dir = tmp / "trust"; trust_dir.mkdir(); os.chmod(trust_dir, 0o755)
    pub = (keys / "key.pub").read_text().split()
    signers = trust_dir / "allowed_signers"
    signers.write_text('test-reviewer namespaces="apex-admission" %s %s\n' % (pub[0], pub[1])); os.chmod(signers, 0o644)
    aroot = tmp / "admissions"; aroot.mkdir(); os.chmod(aroot, 0o755)
    trust = TrustConfig(admission_root=aroot, allowed_signers=signers, checkout_root=REPO,
                        permitted_roots=(str(tmp / "dataset"),), enforce_ownership=False)
    return {"tmp": tmp, "ident": ident, "ds": ds, "mpath": mpath, "msha": msha, "keys": keys,
            "aroot": aroot, "out": tmp / "out", "trust": trust,
            "fit_days": fit_days, "dev_days": dev_days}


def _body(rig, *, experiment=EXP004_ID, reg=None, **over):
    b = {"contract": boundary.REAL_DATA_CONTRACT, "decision": "ADMIT",
         "dataset": {"dataset_id": "fixture/exp004", "root": str(rig["ds"]), "manifest_path": str(rig["mpath"]),
                     "manifest_sha256": rig["msha"]},
         "scope": {"source_families": ["alpaca_sip_raw_1m"],
                   "fields": ["open", "high", "low", "close", "volume", "event_time_utc"], "universe": ["SPY"],
                   "temporal_range": {"start": "2016-01-04", "end": "2021-12-31"}},
         "availability": json.loads(json.dumps(AVAIL)),
         "purpose": {"research_purpose": "EXP-004 activation test on a synthetic fixture",
                     "experiment_id": experiment, "registration_hash": reg or registration_hash()},
         "code": {"commit": rig["ident"]["commit"], "source_tree_sha256": rig["ident"]["tree_sha256"]},
         "output": {"root": str(rig["out"]), "authority_classification": "RESEARCH_HISTORICAL"},
         "provenance": {"decided_by": "test-reviewer", "decided_utc": "2026-09-10T06:00:00Z", "review_reference": "T4"}}
    for k, v in over.items():
        sec, _, leaf = k.partition("__")
        if leaf:
            b[sec][leaf] = v
        else:
            b[sec] = v
    return b


def _write(rig, body, *, name="d4.json", sign=True):
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
    spec = importlib.util.spec_from_file_location("alpha_exp_real_execute4", REPO / "scripts/alpha_exp_real_execute.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def _run(rig, p, capsys, *extra, experiment=EXP004_ID):
    mod = _cmd()
    rc = mod.main(["--experiment", experiment, "--decision", str(p), *extra], trust=rig["trust"])
    return rc, json.loads(capsys.readouterr().out)


def _RA():
    spec = importlib.util.spec_from_file_location("_ra4", REPO / "scripts" / "research_activation.py")
    RA = importlib.util.module_from_spec(spec); sys.modules["_ra4"] = RA; spec.loader.exec_module(RA)
    return RA


# ------------------------------------------------------------------ wrapper support

def test_wrapper_knows_exp004_and_resolves_its_registration_from_the_checkout():
    RA = _RA()
    assert "ALPHA-EXP-004" in RA.EXPERIMENTS
    assert RA.registration_hash_for(EXP004_ID, REPO) == registration_hash()
    assert RA.registration_hash_for(EXP002_ID, REPO) == exp002_hash()
    assert RA.registration_hash_for(EXP004_ID, REPO) != RA.registration_hash_for(EXP002_ID, REPO)
    with pytest.raises(RA.ActivationRefused, match="UNKNOWN_EXPERIMENT"):
        RA.registration_hash_for("ALPHA-EXP-999", REPO)
    with pytest.raises(RA.ActivationRefused, match="REGISTRATION_MISSING"):
        RA.registration_hash_for(EXP004_ID, Path("/nonexistent-checkout"))


def test_wrapper_commands_name_exp004_on_every_invocation():
    RA = _RA()
    t = RA.production_targets()
    oc = RA.operator_commands(t, "abc123", Path("/etc/apex/admissions/exp004_admission.json"), EXP004_ID)
    assert "--experiment ALPHA-EXP-004" in oc["prepare"]
    assert oc["execute"] == oc["prepare"] + " --apply"
    assert "--experiment ALPHA-EXP-002" not in oc["prepare"]


def test_wrapper_cli_accepts_exp004_and_refuses_an_unregistered_experiment():
    out = subprocess.run([sys.executable, str(REPO / "scripts/research_activation.py"), "--help"],
                         capture_output=True, text=True, timeout=120)
    assert "ALPHA-EXP-004" in out.stdout
    bad = subprocess.run([sys.executable, str(REPO / "scripts/research_activation.py"), "preflight",
                          "--experiment", "ALPHA-EXP-999"], capture_output=True, text=True, timeout=120)
    assert bad.returncode != 0 and "invalid choice" in (bad.stderr + bad.stdout)


def test_sealed_results_are_counted_per_experiment(rig, capsys, monkeypatch):
    """`_sealed_results_for` returns REJECTED candidates too, marked
    counted: false. Discovery is not counting, so assert counting."""
    p = _write(rig, _body(rig), name="d4_count.json")
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 0 and doc["process_outcome"] == "SCIENTIFIC_COMPLETE", doc
    RA = _RA()
    tg = RA.Targets(research_root=rig["out"].parent)
    sha = boundary.sha256_of(p)

    found = RA._sealed_results_for(tg, sha, set(), EXP004_ID)
    counted = [c for c in found if c.get("counted")]
    assert len(counted) == 1, found
    assert counted[0]["run_id"] == Path(doc["run_dir"]).name
    # the same sealed result is not counted for another experiment
    assert not [c for c in RA._sealed_results_for(tg, sha, set(), EXP002_ID) if c.get("counted")]

    # now force an INTEGRITY_FAILURE under the SAME decision: it must be
    # discovered as a candidate but must NOT be counted
    import apex.world_model.exp004.historical as H
    mod = _cmd()
    monkeypatch.setattr(mod.H4, "run", lambda *a, **k: {
        "experiment": EXP004_ID, "registration_hash": registration_hash(),
        "status": "INTEGRITY_FAILURE",
        "refusal": {"kind": "AdapterRefused", "stage": "test", "detail": "forced for the counting assertion"}})
    rc2 = mod.main(["--experiment", EXP004_ID, "--decision", str(p), "--execute"], trust=rig["trust"])
    doc2 = json.loads(capsys.readouterr().out)
    assert rc2 == 5 and doc2["process_outcome"] == "INVALID_INPUT_OR_FAILURE"
    monkeypatch.undo()

    found2 = RA._sealed_results_for(tg, sha, set(), EXP004_ID)
    counted2 = [c for c in found2 if c.get("counted")]
    rejected = [c for c in found2 if not c.get("counted")]
    assert len(found2) == 2, found2                      # both discovered
    assert len(counted2) == 1 and counted2[0]["run_id"] == Path(doc["run_dir"]).name
    assert len(rejected) == 1 and rejected[0]["run_id"] == Path(doc2["run_dir"]).name
    assert "INTEGRITY_FAILURE" in rejected[0]["why"] or "not a completed outcome" in rejected[0]["why"]


# ------------------------------------------------------------------ dispatch and refusals through the real path

def test_plan_lists_only_the_two_open_periods_and_opens_nothing(rig, capsys, monkeypatch):
    monkeypatch.setattr(boundary, "open_file", lambda *a, **k: (_ for _ in ()).throw(AssertionError("row opened")))
    rc, doc = _run(rig, _write(rig, _body(rig)), capsys, "--plan")
    assert rc == 0 and doc["status"] == "PLAN" and doc["experiment"] == EXP004_ID
    assert doc["sessions"] == {"fit": N_FIT, "development": N_DEV}
    assert "evaluation" not in doc["sessions"] and "reserve" not in doc["sessions"]
    assert set(doc["sealed_periods_never_requested"]) == {"evaluation", "reserve"}


def test_an_exp002_admission_cannot_authorise_exp004_and_the_reverse(rig, capsys):
    p = _write(rig, _body(rig, experiment=EXP002_ID, reg=exp002_hash()), name="d4_as002.json")
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 3 and doc["process_outcome"] == "AUTHORIZATION_REFUSED"
    assert doc["refusal"].startswith("EXPERIMENT_MISMATCH")
    p2 = _write(rig, _body(rig), name="d4_ok.json")
    rc, doc = _run(rig, p2, capsys, "--execute", experiment=EXP002_ID)
    assert rc == 3 and doc["refusal"].startswith("EXPERIMENT_MISMATCH")
    p3 = _write(rig, _body(rig, reg=exp002_hash()), name="d4_wrongreg.json")
    rc, doc = _run(rig, p3, capsys, "--execute")
    assert rc == 3 and doc["refusal"].startswith("REGISTRATION_MISMATCH")


def test_signature_and_source_refusals_for_exp004(rig, capsys):
    p = _write(rig, _body(rig), name="d4_unsigned.json", sign=False)
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 3 and doc["refusal"].startswith("UNSIGNED_DECISION")
    other = rig["tmp"] / "otherkey"
    if not other.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(other), "-C", "x"], check=True)
    p = _write(rig, _body(rig), name="d4_badsig.json", sign=False)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(other), "-n", "apex-admission", str(p)],
                   check=True, capture_output=True)
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 3 and doc["refusal"].startswith("SIGNATURE_INVALID")
    p = _write(rig, _body(rig, code__commit="0" * 40), name="d4_commit.json")
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 3 and doc["refusal"].startswith("CODE_IDENTITY_MISMATCH")
    p = _write(rig, _body(rig, code__source_tree_sha256="1" * 64), name="d4_tree.json")
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 3 and doc["refusal"].startswith("SOURCE_IDENTITY_MISMATCH")


def test_governed_execute_runs_the_adapter_seals_a_historical_result(rig, capsys, monkeypatch):
    """The whole path: signature, import provenance, run directory, adapter
    dispatch, sealing. Synthetic admitted files; registered inference."""
    import apex.world_model.exp004.synthetic as SY
    calls = {"synthetic": 0}
    real_syn = SY.synthetic_tournament
    monkeypatch.setattr(SY, "synthetic_tournament",
                        lambda *a, **k: (calls.__setitem__("synthetic", calls["synthetic"] + 1),
                                         real_syn(*a, **k))[1])
    opened = []
    real_open = boundary.open_file
    def spy(grant, path, **kw):
        opened.append(kw["session_date"]); return real_open(grant, path, **kw)
    monkeypatch.setattr(boundary, "open_file", spy)

    rc, doc = _run(rig, _write(rig, _body(rig), name="d4_exec.json"), capsys, "--execute")
    assert doc["experiment"] == EXP004_ID
    res = json.loads((Path(doc["run_dir"]) / "_RESULT.json").read_text())
    print("\nGOVERNED EXECUTE OUTCOME: rc=%s process_outcome=%s status=%s run_mode=%s refusal=%s"
          % (rc, doc["process_outcome"], res.get("status"), res.get("run_mode"),
             (res.get("refusal") or {}).get("detail", "")[:120]))
    assert res["experiment"] == EXP004_ID and res["registration_hash"] == registration_hash()
    assert res["adapter"]["entry_point"] == "apex.world_model.exp004.run.tournament"
    assert calls["synthetic"] == 0, "the governed path reached the synthetic entry point"
    assert set(opened) == set(rig["fit_days"] + rig["dev_days"])
    assert not any(d >= "2022-01-01" for d in opened)               # sealed periods never opened
    assert res["evaluation"].startswith("SEALED")
    assert res["imports_at_start"]["all_imports_match_admitted_commit"] is True
    assert res["acceptance_qualification"] == "VALID"
    assert res["source_identity_at_completion"]["unchanged"] is True
    # completion is REQUIRED on this fixed fixture: a regression that always
    # refused would otherwise pass. Named refusals are exercised separately.
    assert rc == 0 and doc["process_outcome"] == "SCIENTIFIC_COMPLETE", res.get("refusal")
    assert res["status"] in ("SELECTED", "NOT_SELECTED")
    assert res["run_mode"] == "HISTORICAL"
    ip = res["inference_parameters"]
    assert (ip["resamples"], ip["seed"]) == (10000, 20260909)
    assert ip["historical_path_valid"] is True and ip["NOT_FOR_HISTORICAL_USE"] is False
    assert res["result"]["development"]["inference_parameters"]["registered_values"] is True
    assert res["result"]["development"]["n_rows"] > 0 and res["result"]["fit"]["n_fit_rows"] > 0
    with pytest.raises(RealDataRefused, match="RESULT_EXISTS"):
        boundary.seal_result(Path(doc["run_dir"]), {"status": "again"})


def test_governed_execute_refuses_when_the_admitted_scope_starves_the_fit(rig, capsys):
    """A named refusal through the FULL path, driven by the decision itself:
    narrowing the admitted range leaves fewer than the registered 100 baseline
    sessions, so the adapter refuses and the run is sealed as a failure."""
    body = _body(rig)
    body["scope"]["temporal_range"] = {"start": "2016-03-01", "end": "2021-12-31"}
    p = _write(rig, body, name="d4_starved.json")
    rc, doc = _run(rig, p, capsys, "--execute")
    assert rc == 5 and doc["process_outcome"] == "INVALID_INPUT_OR_FAILURE"
    res = json.loads((Path(doc["run_dir"]) / "_RESULT.json").read_text())
    assert res["status"] == "INTEGRITY_FAILURE"
    detail = res["refusal"]["detail"]
    assert "INSUFFICIENT_FIT_ROWS" in detail or "NO_BASELINE_SUPPORT" in detail, detail
    assert "result" not in res                                   # no statistics were produced
    RA = _RA()
    tg = RA.Targets(research_root=rig["out"].parent)
    got = RA._sealed_results_for(tg, boundary.sha256_of(p), set(), EXP004_ID)
    assert got and not any(c.get("counted") for c in got)        # discovered, never counted
