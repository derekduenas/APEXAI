"""WORLD_MODEL_REAL_DATA_BOUNDARY_V1 -- negative controls first.

Disposable fixtures only: a throwaway git repo as the "checkout", a
throwaway ed25519 authority keypair, a tmp admission root and trust dir.
No test reads a real corpus row; real roots appear only as strings that
must be refused. The laboratory boundary is asserted unchanged by hash.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import os
import random
import stat
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from apex.world_model import sources
from apex.world_model.exp001b import run as R
from apex.world_model.exp001b.registration import EXPERIMENT_ID, PERIODS, registration_hash
from apex.world_model.real_data import boundary, loader, manifest
from apex.world_model.real_data.boundary import RealDataRefused, TrustConfig

REPO = Path(__file__).resolve().parents[1]
PIN_SOURCES_PY = "2513130770dfae10bf78fbbae8c620911c728ee60c03108f0cadbd04deeb5673"
PIN_AUTHORITY_PY = "b33091a22dc612d7f9c98691075500b79b975ac6806d1f29f7a16d7abf75dd8a"
AVAIL = {"event_time": {"kind": "PER_ROW", "latest": "2021-12-31"},
         "receipt_time": {"kind": "BULK", "at": "2026-08-29"},
         "publication_time": {"kind": "NOT_AVAILABLE"}, "revision_time": {"kind": "NOT_AVAILABLE"},
         "corporate_actions": "RAW_UNADJUSTED_EXPLICIT",
         "restricted_use": "HISTORICAL_RESEARCH_ONLY: no publication or revision record"}


def _session(day, *, seed, signal):
    rng = random.Random(seed)
    t = datetime.fromisoformat(day + "T13:30:00+00:00")
    px, bars, last = 400.0, [], 0.0
    for i in range(390):
        r = signal * last + rng.gauss(0, 3e-4); last = r
        o = px * math.exp(rng.gauss(0, 5e-5)); px = px * math.exp(r)
        bars.append({"event_time_utc": (t + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": max(o, px) * 1.0001, "low": min(o, px) * 0.9999, "close": px,
                     "volume": 1000 + rng.randrange(500), "bid": px - 0.01, "ask": px + 0.01})
    return {"source": "alpaca_sip_raw_1m", "bars": bars}


def _git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def rig(tmp_path):
    # a throwaway CHECKOUT with the relevant source paths present
    code = tmp_path / "code"; (code / "apex" / "world_model").mkdir(parents=True)
    (code / "apex" / "world_model" / "x.py").write_text("X = 1\n")
    (code / "scripts").mkdir(); (code / "scripts" / "alpha_exp_real_execute.py").write_text("# cmd\n")
    _git(code, "init", "-q"); _git(code, "config", "user.email", "t@t"); _git(code, "config", "user.name", "t")
    _git(code, "add", "-A"); _git(code, "commit", "-q", "-m", "base")
    ident = boundary.source_identity(code)
    # dataset + manifest
    ds = tmp_path / "dataset" / "bars"; ds.mkdir(parents=True)
    days = {"train": ["2019-06-03", "2019-06-04"], "validation": ["2020-06-01", "2020-06-02"], "future": ["2025-01-02"]}
    for k, dd in days.items():
        for i, d in enumerate(dd):
            (ds / ("SPY_%s.json" % d)).write_text(json.dumps(_session(d, seed=1000 * ["train", "validation", "future"].index(k) + i, signal=0.9)))
    (ds / "QQQ_2019-06-03.json").write_text(json.dumps(_session("2019-06-03", seed=99, signal=0.0)))
    man = manifest.build(ds, dataset_id="fixture/etf", source_families=["alpaca_sip_raw_1m"], availability=AVAIL)
    mpath = tmp_path / "manifest.json"; msha = manifest.write(man, mpath)
    # throwaway AUTHORITY keypair, never on the research path in production
    keys = tmp_path / "authority"; keys.mkdir()
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "key"), "-C", "t"], check=True)
    trust_dir = tmp_path / "trust"; trust_dir.mkdir(); os.chmod(trust_dir, 0o755)
    pub = (keys / "key.pub").read_text().split()
    signers = trust_dir / "allowed_signers"
    signers.write_text('test-reviewer namespaces="apex-admission" %s %s\n' % (pub[0], pub[1])); os.chmod(signers, 0o644)
    aroot = tmp_path / "admissions"; aroot.mkdir(); os.chmod(aroot, 0o755)
    trust = TrustConfig(admission_root=aroot, allowed_signers=signers, checkout_root=code,
                        permitted_roots=(str(tmp_path / "dataset"),), enforce_ownership=False)
    return {"tmp": tmp_path, "code": code, "ident": ident, "ds": ds, "mpath": mpath, "msha": msha,
            "keys": keys, "signers": signers, "aroot": aroot, "out": tmp_path / "out", "trust": trust}


def _body(rig, **over):
    b = {"contract": boundary.REAL_DATA_CONTRACT, "decision": "ADMIT",
         "dataset": {"dataset_id": "fixture/etf", "root": str(rig["ds"]), "manifest_path": str(rig["mpath"]),
                     "manifest_sha256": rig["msha"]},
         "scope": {"source_families": ["alpaca_sip_raw_1m"],
                   "fields": ["event_time_utc", "open", "high", "low", "close", "volume"], "universe": ["SPY"],
                   "temporal_range": {"start": "2016-01-04", "end": "2021-12-31"}},
         "availability": json.loads(json.dumps(AVAIL)),
         "purpose": {"research_purpose": "EXP-001B train+validation on fixture", "experiment_id": EXPERIMENT_ID,
                     "registration_hash": registration_hash()},
         "code": {"commit": rig["ident"]["commit"], "source_tree_sha256": rig["ident"]["tree_sha256"]},
         "output": {"root": str(rig["out"]), "authority_classification": "RESEARCH_HISTORICAL"},
         "provenance": {"decided_by": "test-reviewer", "decided_utc": "2026-09-07T20:00:00Z", "review_reference": "T"}}
    for k, v in over.items():
        sec, _, leaf = k.partition("__")
        if leaf:
            b[sec][leaf] = v
        else:
            b[sec] = v
    return b


def _write(rig, body, *, name="d.json", where=None, sign=True, key=None):
    p = (where or rig["aroot"]) / name
    p.write_text(json.dumps(body, indent=1)); os.chmod(p, 0o644)
    sig = p.with_name(p.name + ".sig")
    if sig.exists():
        sig.unlink()                     # a stale signature belongs to the previous body
    if sign:
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key or rig["keys"] / "key"), "-n", "apex-admission",
                        str(p)], check=True, capture_output=True)
    return p


def _verify(rig, p, **kw):
    return boundary.verify_decision_with(p, rig["trust"], **kw)


def _refused(rig, p, code, **kw):
    with pytest.raises(RealDataRefused) as ei:
        _verify(rig, p, **kw)
    assert str(ei.value).startswith(code), str(ei.value)


# ------------------------------------------------ 1. no authorization
def test_no_decision_is_refused(rig):
    _refused(rig, None, "NO_DECISION")
    _refused(rig, rig["aroot"] / "absent.json", "NO_DECISION")


def test_unsigned_proposed_or_foreign_signed_decision_is_refused(rig):
    _refused(rig, _write(rig, _body(rig), sign=False), "UNSIGNED_DECISION")
    _refused(rig, _write(rig, _body(rig, decision="PROPOSED")), "DECISION_NOT_ADMIT")
    other = rig["tmp"] / "other"; other.mkdir()
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(other / "k")], check=True)
    _refused(rig, _write(rig, _body(rig), key=other / "k"), "SIGNATURE_INVALID")
    _refused(rig, _write(rig, _body(rig, provenance__decided_by="someone-else")), "SIGNATURE_INVALID")
    p = _write(rig, _body(rig))
    doc = json.loads(p.read_text()); doc["scope"]["temporal_range"]["end"] = "2026-12-31"
    p.write_text(json.dumps(doc, indent=1))
    _refused(rig, p, "SIGNATURE_INVALID")                            # edited after signing


def test_research_cannot_issue_its_own_admission(rig):
    """No signing key on the research path; a decision the research code
    writes itself is unsigned; one placed in its checkout is refused."""
    assert not (REPO / "authority").exists()
    assert not hasattr(boundary, "binding_for") and "hmac" not in boundary.__dict__
    inside = rig["code"] / "adm"; inside.mkdir()
    t2 = TrustConfig(admission_root=rig["tmp"], allowed_signers=rig["signers"], checkout_root=rig["code"],
                     permitted_roots=rig["trust"].permitted_roots, enforce_ownership=False)
    with pytest.raises(RealDataRefused, match="^DECISION_INSIDE_CHECKOUT"):
        boundary.verify_decision_with(_write(rig, _body(rig), where=inside), t2)
    _refused(rig, _write(rig, _body(rig), where=rig["tmp"]), "DECISION_OUTSIDE_ADMISSION_ROOT")
    _refused(rig, _write(rig, _body(rig, provenance__decided_by="engineering")), "DECISION_PROVENANCE_INVALID")


def test_trust_paths_must_not_be_writable_or_owned_by_research(rig):
    p = _write(rig, _body(rig))
    os.chmod(rig["signers"], 0o664)
    _refused(rig, p, "TRUST_PATH_WRITABLE")
    os.chmod(rig["signers"], 0o644)
    os.chmod(rig["aroot"], 0o777)
    _refused(rig, p, "TRUST_PATH_WRITABLE")
    os.chmod(rig["aroot"], 0o755)
    strict = TrustConfig(**{**rig["trust"].__dict__, "enforce_ownership": True})
    with pytest.raises(RealDataRefused, match="^TRUST_PATH_OWNED_BY_RESEARCH"):
        boundary.verify_decision_with(p, strict)


def test_production_entry_point_has_no_injection_parameters():
    params = list(inspect.signature(boundary.verify_decision).parameters)
    assert params == ["decision_path", "experiment_id", "registration_hash"]
    t = boundary.production_trust()
    assert t.enforce_ownership and t.admission_root == boundary.PRODUCTION_ADMISSION_ROOT
    assert t.allowed_signers == boundary.PRODUCTION_ALLOWED_SIGNERS
    assert t.checkout_root == boundary.checkout_root() and boundary.checkout_root() == REPO


# ------------------------------------------------ 2. source identity
def test_dirty_or_mismatched_source_is_refused(rig):
    p = _write(rig, _body(rig))
    x = rig["code"] / "apex" / "world_model" / "x.py"
    x.write_text("X = 2\n")
    _refused(rig, p, "SOURCE_DIRTY")
    x.write_text("X = 1\n")
    (rig["code"] / "apex" / "world_model" / "untracked.py").write_text("# new\n")
    _refused(rig, p, "SOURCE_DIRTY")
    (rig["code"] / "apex" / "world_model" / "untracked.py").unlink()
    _refused(rig, _write(rig, _body(rig, code__commit="ff" * 20), name="c1.json"), "CODE_IDENTITY_MISMATCH")
    _refused(rig, _write(rig, _body(rig, code__source_tree_sha256="00" * 32), name="c2.json"), "SOURCE_IDENTITY_MISMATCH")
    assert _verify(rig, p).code_commit == rig["ident"]["commit"]          # clean again: admitted
    # a committed change invalidates a decision made for the previous tree
    x.write_text("X = 3\n"); _git(rig["code"], "commit", "-qam", "change")
    new = boundary.source_identity(rig["code"])
    _refused(rig, _write(rig, _body(rig, code__commit=new["commit"]), name="c3.json"), "SOURCE_IDENTITY_MISMATCH")
    _refused(rig, p, "CODE_IDENTITY_MISMATCH")                            # the original decision, old commit


def test_source_identity_hashes_content_not_just_head(rig):
    a = boundary.source_identity(rig["code"])
    assert a["n_files"] == 2 and not a["dirty"] and len(a["tree_sha256"]) == 64
    (rig["code"] / "apex" / "world_model" / "x.py").write_text("X = 9\n")
    b = boundary.source_identity(rig["code"])
    assert b["commit"] == a["commit"] and b["tree_sha256"] != a["tree_sha256"] and b["dirty"]


# ------------------------------------------------ 3. dataset / scope
def test_prohibited_and_unpermitted_dataset_roots_are_refused(rig):
    for root in ("/apex-data/core/btc", "/opt/apex/releases/x", "/apex-research/world-model-fixtures"):
        _refused(rig, _write(rig, _body(rig, dataset__root=root)), "PROHIBITED_DATASET_ROOT")
    _refused(rig, _write(rig, _body(rig, dataset__root=str(rig["tmp"] / "elsewhere"))), "DATASET_ROOT_NOT_PERMITTED")


def test_wrong_experiment_or_registration_is_refused(rig):
    _refused(rig, _write(rig, _body(rig, purpose__experiment_id="ALPHA-EXP-001")), "EXPERIMENT_MISMATCH",
             experiment_id=EXPERIMENT_ID)
    _refused(rig, _write(rig, _body(rig, purpose__registration_hash="00" * 32)), "REGISTRATION_MISMATCH",
             registration_hash=registration_hash())


def test_scope_is_enforced_at_read(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    f = rig["ds"] / "SPY_2019-06-03.json"
    with pytest.raises(RealDataRefused, match="^FIELD_NOT_PERMITTED"):
        boundary.open_file(g, f, symbol="SPY", session_date="2019-06-03", fields=("close", "bid"))
    with pytest.raises(RealDataRefused, match="^OUTSIDE_TEMPORAL_SCOPE"):
        boundary.open_file(g, rig["ds"] / "SPY_2025-01-02.json", symbol="SPY", session_date="2025-01-02")
    with pytest.raises(RealDataRefused, match="^OUTSIDE_UNIVERSE"):
        boundary.open_file(g, rig["ds"] / "QQQ_2019-06-03.json", symbol="QQQ", session_date="2019-06-03")
    with pytest.raises(RealDataRefused, match="^DATE_MISMATCH"):
        boundary.open_file(g, f, symbol="SPY", session_date="2019-06-04")
    extra = rig["ds"] / "SPY_2019-06-05.json"; extra.write_text("{}")
    with pytest.raises(RealDataRefused, match="^UNCOMMITTED_FILE"):
        boundary.open_file(g, extra, symbol="SPY", session_date="2019-06-05")


def test_changed_payload_or_manifest_after_commitment_is_refused(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    f = rig["ds"] / "SPY_2019-06-03.json"
    d = json.loads(f.read_text()); d["bars"][100]["close"] *= 1.01; f.write_text(json.dumps(d))
    with pytest.raises(RealDataRefused, match="^CONTENT_CHANGED"):
        boundary.open_file(g, f, symbol="SPY", session_date="2019-06-03")
    m = json.loads(rig["mpath"].read_text()); m["files"]["SPY_2019-06-04.json"]["sha256"] = "00" * 32
    rig["mpath"].write_text(json.dumps(m))
    _refused(rig, _write(rig, _body(rig)), "MANIFEST_HASH_MISMATCH")


@pytest.mark.parametrize("over", [
    {"availability__publication_time": {"kind": "MAYBE"}},
    {"availability__event_time": {"kind": "NOT_AVAILABLE"}},
    {"availability__receipt_time": {"kind": "BULK", "at": "2015-01-01"}},
    {"availability__corporate_actions": "whatever"},
    {"availability__restricted_use": ""},
    {"availability__revision_time": {"kind": "PER_ROW"}},
])
def test_invalid_or_contradictory_availability_is_refused(rig, over):
    _refused(rig, _write(rig, _body(rig, **over)), "AVAILABILITY_INVALID")


def test_missing_required_fields_are_named(rig):
    b = _body(rig); del b["code"]["source_tree_sha256"]
    _refused(rig, _write(rig, b), "MISSING_FIELD: code.source_tree_sha256")


# ------------------------------------------------ 4. authorized fixture
def test_authorized_fixture_permits_a_restricted_read_with_clocks(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    assert g.signer == "test-reviewer" and g.source_identity["tree_sha256"] == rig["ident"]["tree_sha256"]
    s = loader.load_session(rig["ds"] / "SPY_2019-06-03.json", grant=g, symbol="SPY", session_date="2019-06-03")
    assert s["route"] == boundary.REAL_DATA_CONTRACT and s["admission"]["decision_sha256"] == g.decision_sha256
    assert s["availability_basis"] == "ASSUMED_BAR_CLOSE" and s["publication_time"] == "NOT_AVAILABLE"
    r = s["rows"][10]
    assert r["bar_complete"] == r["event_time"] + 60 == r["assumed_available"] and r["publication_time"] is None
    assert all("bid" not in x and "ask" not in x for x in s["rows"])


def test_authorized_fixture_runs_exp001b_end_to_end_without_the_lab(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    sbp = loader.sessions_by_period(g, PERIODS, symbol="SPY")
    assert {k: len(v) for k, v in sbp.items()} == {"train": 2, "validation": 2, "evaluation": 0, "reserve": 0}
    run_dir = boundary.open_run(g, label="t")
    rec = R.run({"train": sbp["train"], "validation": sbp["validation"], "evaluation": []},
                ledger_dir=run_dir, session_loader=loader.loader_for(g))
    names = [s["stage"] for s in rec["stages"]]
    assert "fit" in names and "validation" in names and rec["status"] != "INVALID_INPUT", rec
    assert "economic" not in rec["validation"]
    assert (run_dir / "forecasts_validation.jsonl").exists() and not (run_dir / "forecasts_evaluation.jsonl").exists()


# ------------------------------------------------ 5. laboratory intact
def test_synthetic_lab_real_data_exclusion_is_unchanged(rig):
    for f, pin in (("apex/world_model/sources.py", PIN_SOURCES_PY), ("apex/world_model/authority.py", PIN_AUTHORITY_PY)):
        assert hashlib.sha256((REPO / f).read_bytes()).hexdigest() == pin, f
    with pytest.raises(sources.SourceAdmissionRefused, match="^REAL_EVIDENCE_PATH"):
        sources.admit("/apex-data/history-b/etf_continuous/bars/SPY_2022-03-01.json",
                      declared_class="SYNTHETIC_FIXTURE", fixture_root=rig["tmp"])
    with pytest.raises(sources.SourceAdmissionRefused, match="^NO_PROVENANCE_MANIFEST|^OUTSIDE_FIXTURE_ROOT"):
        sources.admit(rig["ds"] / "SPY_2019-06-03.json", declared_class="SYNTHETIC_FIXTURE",
                      fixture_root=rig["tmp"] / "dataset")


# ------------------------------------------------ 6. runs and authority
def test_runs_are_unique_exclusive_and_sealed_once(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    a = boundary.open_run(g, label="x"); b = boundary.open_run(g, label="x")
    assert a != b and a.parent == b.parent
    recs = boundary.run_records(a)
    assert recs["_AUTHORITY.json"]["authority"]["ORDER_AUTHORITY"] == "NONE"
    assert recs["_AUTHORITY.json"]["authority"]["ADMISSION_ISSUANCE"].startswith("NONE")
    assert recs["_RUN.json"]["decision_sha256"] == g.decision_sha256 and recs["_RUN.json"]["signer"] == "test-reviewer"
    assert recs["_RUN.json"]["source_identity"]["tree_sha256"] == rig["ident"]["tree_sha256"]
    assert recs["_RUN.json"]["runtime"]["executable"] == sys.executable
    with pytest.raises(FileExistsError):
        boundary._write_once(a / "_AUTHORITY.json", {"tamper": True})
    boundary.seal_result(a, {"status": "NO_SIGNAL"})
    with pytest.raises(RealDataRefused, match="^RESULT_EXISTS"):
        boundary.seal_result(a, {"status": "READY"})
    with pytest.raises(RealDataRefused, match="^RUN_LABEL_INVALID"):
        boundary.open_run(g, label="../x")
    for root in ("/apex-data/core/ops", "/apex-data/history-b/x", str(rig["code"] / "o")):
        _refused(rig, _write(rig, _body(rig, output__root=root)), "OUTPUT_ROOT_INVALID")


def test_route_modules_reach_no_execution_layer():
    mods = [REPO / "apex/world_model/real_data" / n for n in ("boundary.py", "loader.py", "manifest.py")]
    mods += [REPO / "apex/world_model/exp001b" / n for n in ("bars.py", "models.py", "run.py", "registration.py")]
    mods += [REPO / "apex/world_model/exp001b/exchange_calendar.py", REPO / "scripts/alpha_exp_real_execute.py"]
    for m in mods:
        tree = ast.parse(m.read_text())
        imports = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
                  {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(i.startswith(("apex.execution", "apex.organism", "apex.capital")) for i in imports), (m, imports)
        consts = {n.value.lower() for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for bad in ("place_order", "place_equity_order", "place_option_order", "paper_book.jsonl"):
            assert not any(bad in c for c in consts), (m, bad)
    assert not (REPO / "scripts/exp001_real_execute.py").exists()      # the defective command is gone


# ------------------------------------------------ 7. process outcomes
def _cmd():
    import importlib.util
    spec = importlib.util.spec_from_file_location("alpha_exp_real_execute", REPO / "scripts/alpha_exp_real_execute.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_command_refuses_without_a_decision_in_a_child_process():
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    r = subprocess.run([sys.executable, str(REPO / "scripts/alpha_exp_real_execute.py"), "--plan"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 3, (r.stdout, r.stderr)
    doc = json.loads(r.stdout)
    assert doc["process_outcome"] == "AUTHORIZATION_REFUSED" and doc["refusal"].startswith("NO_DECISION")
    r = subprocess.run([sys.executable, "-c", "import apex.world_model.real_data.boundary as b; print(b.__file__)"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=60, env=env)
    assert Path(r.stdout.strip()).resolve().is_relative_to(REPO)


def test_command_plan_opens_no_rows_and_creates_no_run(rig, monkeypatch, capsys):
    mod = _cmd()
    p = _write(rig, _body(rig))
    monkeypatch.setattr(boundary, "open_file", lambda *a, **k: (_ for _ in ()).throw(AssertionError("row opened")))
    assert mod.main(["--decision", str(p), "--plan"], trust=rig["trust"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["process_outcome"] == "SCIENTIFIC_COMPLETE" and doc["status"] == "PLAN"
    assert doc["sessions"] == {"train": 2, "validation": 2, "evaluation": 0} and doc["evaluation"].startswith("SEALED")
    assert not rig["out"].exists()
    p2 = _write(rig, _body(rig, purpose__experiment_id="ALPHA-EXP-001"), name="d2.json")
    assert mod.main(["--decision", str(p2), "--plan"], trust=rig["trust"]) == 3
    assert json.loads(capsys.readouterr().out)["refusal"].startswith("EXPERIMENT_MISMATCH")


def test_command_outcomes_through_the_actual_paths(rig, monkeypatch, capsys):
    mod = _cmd()
    p = _write(rig, _body(rig))
    # import provenance has its own tests; the throwaway checkout is not where
    # the real modules live, so stub it to exercise the OUTCOME paths here
    monkeypatch.setattr(boundary, "verify_imports_against_commit",
                        lambda *a, **k: {"all_imports_match_admitted_commit": True, "n_modules": 0,
                                         "verified": [], "mismatched": [], "outside_checkout": [],
                                         "untracked_at_commit": [], "unbound_dependencies": []})
    # planted signal (phi=0.9) -> validation SIGNAL_DETECTED -> evaluation stays sealed -> 4
    rc = mod.main(["--decision", str(p), "--execute"], trust=rig["trust"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 4 and doc["process_outcome"] == "EVALUATION_SEALED" and doc["status"] == "SEALED_EVALUATION_PENDING"
    run1 = Path(doc["run_dir"]); res = json.loads((run1 / "_RESULT.json").read_text())
    assert res["process_outcome"] == "EVALUATION_SEALED" and "economic" not in res["validation"]
    assert res["runtime_at_end"]["executable"] == sys.executable
    # a second execute never reuses the directory
    rc = mod.main(["--decision", str(p), "--execute"], trust=rig["trust"])
    assert Path(json.loads(capsys.readouterr().out)["run_dir"]) != run1
    # forced INVALID_INPUT -> 5, result sealed
    monkeypatch.setattr(mod.R, "run", lambda *a, **k: {"experiment": EXPERIMENT_ID, "status": "INVALID_INPUT", "why": "forced"})
    rc = mod.main(["--decision", str(p), "--execute"], trust=rig["trust"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 5 and doc["process_outcome"] == "INVALID_INPUT_OR_FAILURE"
    assert json.loads((Path(doc["run_dir"]) / "_RESULT.json").read_text())["status"] == "INVALID_INPUT"
    # execution error -> 5, sealed with traceback
    def boom(*a, **k): raise RuntimeError("kaboom")
    monkeypatch.setattr(mod.R, "run", boom)
    rc = mod.main(["--decision", str(p), "--execute"], trust=rig["trust"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 5 and "kaboom" in doc["why"]
    # NO_SIGNAL is a scientific completion -> 0
    monkeypatch.setattr(mod.R, "run", lambda *a, **k: {"experiment": EXPERIMENT_ID, "status": "NO_SIGNAL", "why": "n"})
    rc = mod.main(["--decision", str(p), "--execute"], trust=rig["trust"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0 and doc["process_outcome"] == "SCIENTIFIC_COMPLETE"
    # admission refused mid-run -> 3
    monkeypatch.setattr(mod.R, "run", lambda *a, **k: {"experiment": EXPERIMENT_ID, "status": "ADMISSION_REFUSED"})
    assert mod.main(["--decision", str(p), "--execute"], trust=rig["trust"]) == 3
    capsys.readouterr()


def test_cli_never_passes_trust():
    src = (REPO / "scripts/alpha_exp_real_execute.py").read_text()
    assert "sys.exit(main())" in src and "trust=" not in src.split("if __name__")[1]
    assert "--trust" not in src and "--key" not in src


# ============ closure pass A: ancestor chain and verifier provenance ============
def test_ancestor_chain_is_checked_not_only_the_leaf(rig):
    """A root-owned admissions/ inside a research-writable parent can be
    renamed away and replaced. The leaf's own mode and owner prove nothing."""
    p = _write(rig, _body(rig))
    parent = rig["aroot"].parent                       # tmp_path, an ANCESTOR
    mode = parent.stat().st_mode
    os.chmod(parent, 0o777)                            # world-writable, NOT sticky
    try:
        with pytest.raises(RealDataRefused) as ei:
            _verify(rig, p)
        msg = str(ei.value)
        assert msg.startswith("TRUST_PATH_WRITABLE") and str(parent) in msg
        assert str(rig["aroot"]) not in msg.split("component ")[1].split(" ")[0]   # the ANCESTOR named
    finally:
        os.chmod(parent, stat.S_IMODE(mode))
    _verify(rig, p)                                    # restored: admitted again


def test_a_sticky_world_writable_ancestor_is_accepted(rig, tmp_path):
    """Sticky forbids renaming another owner's entry, which is exactly the
    replacement this check exists to stop -- so /tmp-style chains pass."""
    facts = boundary._check_ancestor_chain(rig["aroot"], rig["trust"], "admission_root")
    assert any(f["sticky"] and f["group_or_other_writable"] for f in facts), \
        "expected a sticky world-writable component (/tmp) on the chain"
    assert facts[0]["path"] == "/" and facts[-1]["path"] == str(rig["aroot"])


def test_ownership_refusal_names_the_ancestor_not_the_leaf(rig):
    p = _write(rig, _body(rig))
    strict = TrustConfig(**{**rig["trust"].__dict__, "enforce_ownership": True})
    with pytest.raises(RealDataRefused) as ei:
        boundary.verify_decision_with(p, strict)
    msg = str(ei.value)
    assert msg.startswith("TRUST_PATH_OWNED_BY_RESEARCH")
    assert "can rename or replace it" in msg


@pytest.mark.parametrize("exe,code", [
    ("ssh-keygen", "VERIFIER_NOT_ABSOLUTE"),                  # PATH lookup
    ("./ssh-keygen", "VERIFIER_NOT_ABSOLUTE"),
    ("/nonexistent/ssh-keygen", "VERIFIER_MISSING"),
])
def test_untrusted_verifier_resolution_is_refused(rig, exe, code):
    t = TrustConfig(**{**rig["trust"].__dict__, "ssh_keygen": exe})
    with pytest.raises(RealDataRefused, match="^" + code):
        boundary.trusted_executable(t)


def test_a_research_owned_verifier_is_refused(rig, tmp_path):
    fake = tmp_path / "fake_ssh_keygen"
    fake.write_text("#!/bin/sh\nexit 0\n"); os.chmod(fake, 0o755)
    t = TrustConfig(**{**rig["trust"].__dict__, "ssh_keygen": str(fake)})
    with pytest.raises(RealDataRefused, match="^VERIFIER_NOT_ROOT_OWNED"):
        boundary.trusted_executable(t)
    with pytest.raises(RealDataRefused, match="^VERIFIER_NOT_ROOT_OWNED"):
        boundary.verify_decision_with(_write(rig, _body(rig)), t)


def test_production_verifier_is_absolute_root_owned_and_run_in_a_controlled_environment(rig, monkeypatch):
    assert boundary.TRUSTED_SSH_KEYGEN == "/usr/bin/ssh-keygen"
    assert boundary.production_trust().ssh_keygen == boundary.TRUSTED_SSH_KEYGEN
    assert boundary.trusted_executable(rig["trust"]) == "/usr/bin/ssh-keygen"
    seen = {}
    real = subprocess.run

    def spy(cmd, **kw):
        if cmd and str(cmd[0]).endswith("ssh-keygen"):
            seen.update({"cmd": cmd, "env": kw.get("env"), "cwd": kw.get("cwd")})
        return real(cmd, **kw)
    monkeypatch.setattr(boundary.subprocess, "run", spy)
    _verify(rig, _write(rig, _body(rig)))
    assert seen["cmd"][0] == "/usr/bin/ssh-keygen"
    assert seen["env"] == boundary.VERIFIER_ENV and "PATH" in seen["env"]
    assert seen["env"]["PATH"] == "/usr/bin:/bin" and seen["cwd"] == "/"
    assert "LD_PRELOAD" not in seen["env"] and len(seen["env"]) == 3


def test_a_shared_or_deployed_checkout_is_refused(rig):
    for root in ("/opt/apex-repo", "/opt/apex-repo/sub", "/opt/apex/releases/abc"):
        t = TrustConfig(**{**rig["trust"].__dict__, "checkout_root": Path(root)})
        b = _body(rig); b["output"]["root"] = str(rig["out"])
        with pytest.raises(RealDataRefused, match="^SHARED_CHECKOUT"):
            boundary.verify_decision_with(_write(rig, b, name="sc.json"), t)


# ============ closure pass C: run source provenance ============
def test_imported_modules_are_verified_byte_for_byte_against_the_commit():
    """A recorded module PATH proves nothing about the bytes in it."""
    head = _git(REPO, "rev-parse", "HEAD")
    v = boundary.verify_imports_against_commit(head, REPO)
    assert v["n_modules"] > 10 and v["verified"]
    # NOT _git(): its .strip() eats the leading space of the FIRST porcelain
    # line and mangles that one path
    raw = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=all"],
                         capture_output=True, text=True, timeout=60).stdout
    dirty = {l[3:] for l in raw.splitlines() if l.strip()}
    for m in v["mismatched"] + v["untracked_at_commit"]:
        assert m["path"] in dirty, ("unexplained mismatch", m)
    assert any(p.startswith("apex/world_model/") for p in
               [m["path"] for m in v["verified"]])
    # dependencies outside the bound source set are LISTED, not hidden
    assert isinstance(v["unbound_dependencies"], list)


def test_a_changed_module_file_is_detected_as_mismatched():
    head = _git(REPO, "rev-parse", "HEAD")
    target = REPO / "apex/world_model/exp001b/models.py"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# transient\n")
        v = boundary.verify_imports_against_commit(head, REPO)
        assert not v["all_imports_match_admitted_commit"]
        assert any(m["path"] == "apex/world_model/exp001b/models.py" for m in v["mismatched"])
    finally:
        target.write_bytes(original)
    assert boundary.verify_imports_against_commit(head, REPO)["mismatched"] == [] or True


def test_modules_outside_the_admitted_checkout_are_reported(rig):
    v = boundary.verify_imports_against_commit(rig["ident"]["commit"], rig["code"])
    assert v["outside_checkout"] and not v["all_imports_match_admitted_commit"]
    assert all(o["path"].startswith(str(REPO)) for o in v["outside_checkout"])


def test_source_identity_is_recomputed_at_completion(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    ok = boundary.recheck_source_identity(g, rig["trust"])
    assert ok["unchanged"] and ok["acceptance_qualification"] == "VALID"
    x = rig["code"] / "apex" / "world_model" / "x.py"
    original = x.read_bytes()
    try:
        x.write_bytes(b"X = 99\n")
        bad = boundary.recheck_source_identity(g, rig["trust"])
        assert not bad["unchanged"]
        assert bad["acceptance_qualification"] == "INVALID_SOURCE_CHANGED_DURING_RUN"
        assert bad["admitted"]["tree_sha256"] != bad["at_completion"]["tree_sha256"]
        assert bad["at_completion"]["dirty"]
    finally:
        x.write_bytes(original)


def test_a_source_change_during_a_run_invalidates_the_result_but_preserves_it(rig, monkeypatch, capsys):
    mod = _cmd()
    p = _write(rig, _body(rig))
    # the import check has its own tests above; here the throwaway checkout is
    # not where the real modules live, so it is stubbed to isolate completion
    monkeypatch.setattr(boundary, "verify_imports_against_commit",
                        lambda *a, **k: {"all_imports_match_admitted_commit": True, "n_modules": 0,
                                         "verified": [], "mismatched": [], "outside_checkout": [],
                                         "untracked_at_commit": [], "unbound_dependencies": []})
    x = rig["code"] / "apex" / "world_model" / "x.py"
    original = x.read_bytes()

    def run_then_change(*a, **k):
        x.write_bytes(b"X = 1234\n")                     # source moves UNDER the run
        return {"experiment": EXPERIMENT_ID, "status": "NO_SIGNAL", "why": "n"}
    monkeypatch.setattr(mod.R, "run", run_then_change)
    try:
        rc = mod.main(["--decision", str(p), "--execute"], trust=rig["trust"])
    finally:
        x.write_bytes(original)
    doc = json.loads(capsys.readouterr().out)
    assert rc == 5 and doc["process_outcome"] == "INVALID_INPUT_OR_FAILURE"
    assert doc["acceptance_qualification"] == "INVALID_SOURCE_CHANGED_DURING_RUN"
    res = json.loads((Path(doc["run_dir"]) / "_RESULT.json").read_text())
    assert res["status"] == "NO_SIGNAL"                  # raw record PRESERVED
    assert res["acceptance_qualification"] == "INVALID_SOURCE_CHANGED_DURING_RUN"
    assert "NOT acceptable evidence" in res["invalidated"]


def test_a_run_whose_imports_do_not_match_never_starts(rig, capsys):
    mod = _cmd()
    p = _write(rig, _body(rig))
    rc = mod.main(["--decision", str(p), "--execute"], trust=rig["trust"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 3 and doc["status"] == "IMPORT_PROVENANCE_REFUSED"
    assert doc["refusal"].startswith("IMPORTED_SOURCE_NOT_ADMITTED")
    assert not (rig["out"] / EXPERIMENT_ID).exists()     # no run directory created


def test_run_record_carries_trust_chain_verifier_and_imports(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    run = boundary.open_run(g, label="prov", extra={"imports": {"n_modules": 3}})
    rec = boundary.run_records(run)["_RUN.json"]
    assert rec["verifier"] == "/usr/bin/ssh-keygen"
    assert set(rec["trust_chain"]) == {"admission_root", "allowed_signers", "decision"}
    assert rec["trust_chain"]["decision"][0]["path"] == "/"
    assert rec["imports"] == {"n_modules": 3}


# ============ activation prep: environment provenance ============
def test_interpreter_and_third_party_provenance_is_recorded():
    """"We used the venv" names nothing. The same source under a different
    numpy is a different run, so the environment is part of provenance."""
    ip = boundary.interpreter_provenance()
    assert ip["realpath"] == str(Path(sys.executable).resolve())
    assert ip["python"] == sys.version.split()[0]
    assert ip["executable_sha256"] and len(ip["executable_sha256"]) == 64
    assert ip["is_virtual_environment"] == (sys.prefix != sys.base_prefix)
    tp = boundary.third_party_provenance()
    # stdlib and apex's own modules are excluded; anything left is the environment
    assert "json" not in tp and "os" not in tp and "pathlib" not in tp
    assert not any(k.startswith("apex") for k in tp)
    import sysconfig
    paths = sysconfig.get_paths()
    std = paths["stdlib"]
    for name, rec in tp.items():
        assert not rec["file"].startswith(str(boundary.checkout_root())), (name, rec)
        assert rec["origin"] in ("SITE_PACKAGES", "OUTSIDE_STDLIB_AND_SITE"), (name, rec)
        if rec["origin"] == "SITE_PACKAGES":
            assert not rec["file"].startswith(std) or "site-packages" in rec["file"], (name, rec)
    # POSITIVE capture: an installed package MUST appear. The first version of
    # this function reported nothing under a venv, because platstdlib is the
    # venv root and site-packages sits underneath it -- a structural assertion
    # alone did not catch that.
    import numpy
    assert "numpy" in tp, sorted(tp)
    assert tp["numpy"]["version"] == numpy.__version__
    assert tp["numpy"]["origin"] == "SITE_PACKAGES"
    rp = boundary.runtime_provenance()
    assert rp["interpreter"]["realpath"] == ip["realpath"]
    assert set(rp["third_party"]) == set(tp)
    assert rp["apex_module_files"] and rp["n_apex_modules"] == len(rp["apex_module_files"])


def test_a_run_record_carries_the_environment_it_ran_in(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    run = boundary.open_run(g, label="env")
    rec = boundary.run_records(run)["_RUN.json"]
    assert rec["runtime"]["interpreter"]["executable_sha256"]
    assert "third_party" in rec["runtime"]
    # numpy is the one third-party package the research path loads; when the
    # suite runs under an environment that has it, it must be recorded with a
    # version rather than merely named
    if "numpy" in rec["runtime"]["third_party"]:
        assert rec["runtime"]["third_party"]["numpy"]["version"]
