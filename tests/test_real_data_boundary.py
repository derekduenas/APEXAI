"""WORLD_MODEL_REAL_DATA_BOUNDARY_V0 -- negative controls first.

Every fixture here is DISPOSABLE and lives under tmp_path. No test reads a
real corpus row; the real roots appear only as strings that must be
refused. The laboratory boundary is asserted unchanged by hash.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apex.world_model import sources
from apex.world_model.exp001 import run as R
from apex.world_model.exp001.registration import (EXPERIMENT_ID, PERIODS,
                                                  registration_hash)
from apex.world_model.real_data import boundary, loader, manifest
from apex.world_model.real_data.boundary import RealDataRefused

REPO = Path(__file__).resolve().parents[1]
CODE = "0123456789abcdef0123456789abcdef01234567"

# ---- pins: sealed things that this milestone must leave byte-identical ----
PIN_REGISTRATION_HASH = "1a3f55a522f7595f179033827ad10d87e873b7839f1cc08fb05624067c8f391c"
PIN_REGISTRATION_JSON = "96ea6edc1f89dfc2a6c3188d30e460067c13ad0561b75feebdbe26c0dc803367"
PIN_REGISTRATION_PY = "11afb3428d0df660497b6c03e7f677edf6dfe8a23ebf990f07ccc2ce0eace6ea"
PIN_SOURCES_PY = "2513130770dfae10bf78fbbae8c620911c728ee60c03108f0cadbd04deeb5673"
PIN_AUTHORITY_PY = "b33091a22dc612d7f9c98691075500b79b975ac6806d1f29f7a16d7abf75dd8a"

AVAIL = {"event_time": {"kind": "PER_ROW", "latest": "2021-12-31"},
         "receipt_time": {"kind": "BULK", "at": "2026-08-29"},
         "publication_time": {"kind": "NOT_AVAILABLE"},
         "revision_time": {"kind": "NOT_AVAILABLE"},
         "corporate_actions": "RAW_UNADJUSTED_EXPLICIT",
         "restricted_use": "HISTORICAL_RESEARCH_ONLY: no publication or revision record; "
                           "rows may not be used to claim point-in-time availability"}


# ------------------------------------------------------------ fixtures
def _session(day: str, *, seed: int, signal: float) -> dict:
    rng = random.Random(seed)
    t = datetime.fromisoformat(day + "T13:30:00+00:00")
    px, bars, last = 400.0, [], 0.0
    for i in range(390):
        r = signal * last + rng.gauss(0, 3e-4)
        last = r
        o = px; px = px * math.exp(r)
        bars.append({"event_time_utc": (t + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": max(o, px) * 1.0001, "low": min(o, px) * 0.9999,
                     "close": px, "volume": 1000 + rng.randrange(500),
                     "bid": px - 0.01, "ask": px + 0.01})           # NOT admitted fields
    return {"source": "alpaca_sip_raw_1m", "bars": bars}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Disposable dataset, manifest, key, admission root, output root."""
    ds = tmp_path / "dataset" / "bars"; ds.mkdir(parents=True)
    days = {"train": ["2019-06-03", "2019-06-04"], "validation": ["2020-06-01", "2020-06-02"],
            "future": ["2025-01-02"]}
    for k, ds_days in days.items():
        for i, d in enumerate(ds_days):
            (ds / ("SPY_%s.json" % d)).write_text(json.dumps(_session(d, seed=hash((k, i)) & 0xffff,
                                                                        signal=0.9)))
    (ds / "QQQ_2019-06-03.json").write_text(json.dumps(_session("2019-06-03", seed=99, signal=0.0)))
    man = manifest.build(ds, dataset_id="fixture/etf", source_families=["alpaca_sip_raw_1m"],
                         availability=AVAIL, corpus_version="fixture")
    mpath = tmp_path / "manifest.json"
    msha = manifest.write(man, mpath)
    key = tmp_path / "key"; key.write_bytes(os.urandom(32).hex().encode())
    aroot = tmp_path / "admissions"; aroot.mkdir()
    out = tmp_path / "out"
    monkeypatch.setattr(boundary, "checkout_root", lambda: tmp_path / "code")
    (tmp_path / "code").mkdir()
    return {"ds": ds, "mpath": mpath, "msha": msha, "key": key, "aroot": aroot, "out": out,
            "tmp": tmp_path}


def _body(rig, **over):
    b = {"contract": boundary.REAL_DATA_CONTRACT, "decision": "ADMIT",
         "dataset": {"dataset_id": "fixture/etf", "root": str(rig["ds"]),
                     "manifest_path": str(rig["mpath"]), "manifest_sha256": rig["msha"]},
         "scope": {"source_families": ["alpaca_sip_raw_1m"],
                   "fields": ["event_time_utc", "open", "high", "low", "close", "volume"],
                   "universe": ["SPY"],
                   "temporal_range": {"start": "2016-01-04", "end": "2021-12-31"}},
         "availability": json.loads(json.dumps(AVAIL)),
         "purpose": {"research_purpose": "EXP-001 train+validation on fixture",
                     "experiment_id": EXPERIMENT_ID, "registration_hash": registration_hash()},
         "code": {"commit": CODE},
         "output": {"root": str(rig["out"]), "authority_classification": "RESEARCH_HISTORICAL"},
         "provenance": {"decided_by": "test-reviewer", "decided_utc": "2026-09-07T20:00:00Z",
                        "review_reference": "TEST"}}
    for k, v in over.items():
        sec, _, leaf = k.partition("__")
        if leaf:
            b[sec][leaf] = v
        else:
            b[sec] = v
    return b


def _write(rig, body, *, key=None, name="d.json", where=None):
    k = (key or rig["key"]).read_bytes().strip()
    doc = {**body, "binding": boundary.binding_for(body, k)}
    p = (where or rig["aroot"]) / name
    p.write_text(json.dumps(doc, indent=1))
    return p


def _verify(rig, p, **kw):
    return boundary.verify_decision(p, key_path=rig["key"], admission_root=rig["aroot"],
                                    permitted_roots=(rig["tmp"] / "dataset",),
                                    code_commit=CODE, **kw)


def _refused(rig, p, code, **kw):
    with pytest.raises(RealDataRefused) as ei:
        _verify(rig, p, **kw)
    assert str(ei.value).startswith(code), str(ei.value)


# ------------------------------------------------- 1. no authorization
def test_no_decision_is_refused(rig):
    _refused(rig, None, "NO_DECISION")
    _refused(rig, rig["aroot"] / "absent.json", "NO_DECISION")


def test_unbound_or_proposed_decision_is_refused(rig):
    b = _body(rig)
    p = rig["aroot"] / "draft.json"; p.write_text(json.dumps(b))
    _refused(rig, p, "UNBOUND_DECISION")
    _refused(rig, _write(rig, _body(rig, decision="PROPOSED")), "DECISION_NOT_ADMIT")
    _refused(rig, _write(rig, _body(rig, decision="ELIGIBLE_WITH_LIMITATIONS")), "DECISION_NOT_ADMIT")


def test_missing_key_refuses_even_a_well_formed_decision(rig):
    p = _write(rig, _body(rig))
    with pytest.raises(RealDataRefused) as ei:
        boundary.verify_decision(p, key_path=rig["tmp"] / "no_key", admission_root=rig["aroot"],
                                 permitted_roots=(rig["tmp"] / "dataset",), code_commit=CODE)
    assert str(ei.value).startswith("NO_ADMISSION_KEY")


def test_caller_cannot_admit_itself(rig):
    """Decision inside the checkout, outside the admission root, or bound
    under a key the caller made up: all refused."""
    inside = rig["tmp"] / "code" / "adm"; inside.mkdir()
    p = _write(rig, _body(rig), where=inside)
    with pytest.raises(RealDataRefused) as ei:
        boundary.verify_decision(p, key_path=rig["key"], admission_root=rig["tmp"],
                                 permitted_roots=(rig["tmp"] / "dataset",), code_commit=CODE)
    assert str(ei.value).startswith("DECISION_INSIDE_CHECKOUT")
    _refused(rig, _write(rig, _body(rig), where=rig["tmp"]), "DECISION_OUTSIDE_ADMISSION_ROOT")
    own = rig["tmp"] / "own_key"; own.write_bytes(b"x" * 40)
    _refused(rig, _write(rig, _body(rig), key=own), "BINDING_MISMATCH")
    _refused(rig, _write(rig, _body(rig, provenance__decided_by="engineering")),
             "DECISION_PROVENANCE_INVALID")


# ------------------------------------------ 2. wrong dataset / scope
def test_prohibited_and_unpermitted_dataset_roots_are_refused(rig):
    for root in ("/apex-data/core/btc", "/apex-data/core/intraday", "/opt/apex/releases/x",
                 "/apex-research/world-model-fixtures"):
        _refused(rig, _write(rig, _body(rig, dataset__root=root)), "PROHIBITED_DATASET_ROOT")
    _refused(rig, _write(rig, _body(rig, dataset__root=str(rig["tmp"] / "elsewhere"))),
             "DATASET_ROOT_NOT_PERMITTED")


def test_wrong_experiment_or_registration_is_refused(rig):
    p = _write(rig, _body(rig, purpose__experiment_id="ALPHA-EXP-002"))
    _refused(rig, p, "EXPERIMENT_MISMATCH", experiment_id=EXPERIMENT_ID)
    p = _write(rig, _body(rig, purpose__registration_hash="00" * 32))
    _refused(rig, p, "REGISTRATION_MISMATCH", registration_hash=registration_hash())


def test_code_identity_mismatch_is_refused(rig):
    p = _write(rig, _body(rig))
    with pytest.raises(RealDataRefused) as ei:
        boundary.verify_decision(p, key_path=rig["key"], admission_root=rig["aroot"],
                                 permitted_roots=(rig["tmp"] / "dataset",), code_commit="ff" * 20)
    assert str(ei.value).startswith("CODE_IDENTITY_MISMATCH")


def test_field_temporal_and_universe_scope_are_enforced_at_read(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    f = rig["ds"] / "SPY_2019-06-03.json"
    with pytest.raises(RealDataRefused, match="^FIELD_NOT_PERMITTED"):
        boundary.open_file(g, f, symbol="SPY", session_date="2019-06-03", fields=("close", "bid"))
    with pytest.raises(RealDataRefused, match="^OUTSIDE_TEMPORAL_SCOPE"):
        boundary.open_file(g, rig["ds"] / "SPY_2025-01-02.json", symbol="SPY",
                           session_date="2025-01-02")
    with pytest.raises(RealDataRefused, match="^OUTSIDE_UNIVERSE"):
        boundary.open_file(g, rig["ds"] / "QQQ_2019-06-03.json", symbol="QQQ",
                           session_date="2019-06-03")
    with pytest.raises(RealDataRefused, match="^DATE_MISMATCH"):
        boundary.open_file(g, f, symbol="SPY", session_date="2019-06-04")
    with pytest.raises(RealDataRefused, match="^UNCOMMITTED_FILE"):
        extra = rig["ds"] / "SPY_2019-06-05.json"; extra.write_text("{}")
        boundary.open_file(g, extra, symbol="SPY", session_date="2019-06-05")
    with pytest.raises(RealDataRefused, match="^OUTSIDE_DATASET_ROOT"):
        boundary.open_file(g, rig["tmp"] / "manifest.json", symbol="SPY", session_date="2019-06-03")


# ------------------------------------- 3. changed after commitment
def test_changed_payload_after_commitment_is_refused(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    f = rig["ds"] / "SPY_2019-06-03.json"
    doc = json.loads(f.read_text()); doc["bars"][100]["close"] *= 1.01
    f.write_text(json.dumps(doc))
    with pytest.raises(RealDataRefused, match="^CONTENT_CHANGED"):
        boundary.open_file(g, f, symbol="SPY", session_date="2019-06-03")


def test_changed_manifest_or_body_after_binding_is_refused(rig):
    p = _write(rig, _body(rig))
    man = json.loads(rig["mpath"].read_text()); man["files"]["SPY_2019-06-03.json"]["sha256"] = "00" * 32
    rig["mpath"].write_text(json.dumps(man))
    _refused(rig, p, "MANIFEST_HASH_MISMATCH")
    manifest.write(manifest.build(rig["ds"], dataset_id="fixture/etf",
                                  source_families=["alpaca_sip_raw_1m"], availability=AVAIL),
                   rig["mpath"])
    p = _write(rig, _body(rig))
    doc = json.loads(p.read_text()); doc["scope"]["temporal_range"]["end"] = "2026-12-31"
    p.write_text(json.dumps(doc))
    _refused(rig, p, "BODY_DIGEST_MISMATCH")


# ------------------------------------------- 4. availability metadata
@pytest.mark.parametrize("over,code", [
    ({"availability__publication_time": {"kind": "MAYBE"}}, "AVAILABILITY_INVALID"),
    ({"availability__event_time": {"kind": "NOT_AVAILABLE"}}, "AVAILABILITY_INVALID"),
    ({"availability__receipt_time": {"kind": "BULK", "at": "2015-01-01"}}, "AVAILABILITY_INVALID"),
    ({"availability__corporate_actions": "whatever"}, "AVAILABILITY_INVALID"),
    ({"availability__restricted_use": ""}, "AVAILABILITY_INVALID"),
    ({"availability__revision_time": {"kind": "PER_ROW"}}, "AVAILABILITY_INVALID"),  # contradicts manifest
])
def test_invalid_or_contradictory_availability_is_refused(rig, over, code):
    _refused(rig, _write(rig, _body(rig, **over)), code)


def test_missing_required_fields_are_named(rig):
    b = _body(rig); del b["provenance"]["review_reference"]
    _refused(rig, _write(rig, b), "MISSING_FIELD: provenance.review_reference")


# ------------------------------------------ 5. authorized fixture
def test_authorized_fixture_permits_a_restricted_read(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    assert g.contract == boundary.REAL_DATA_CONTRACT
    s = loader.load_session(rig["ds"] / "SPY_2019-06-03.json", grant=g, symbol="SPY",
                            session_date="2019-06-03")
    assert s["route"] == boundary.REAL_DATA_CONTRACT and s["admission"]["decision_digest"] == g.decision_digest
    assert s["restricted_use"].startswith("HISTORICAL_RESEARCH_ONLY")
    assert len(s["rows"]) == 390
    assert all(r["known_from"] == r["t"] + 60 for r in s["rows"])
    assert all("bid" not in r and "ask" not in r for r in s["rows"])   # field restriction is real


def test_authorized_fixture_runs_exp001_end_to_end_without_the_lab(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    sbp = loader.sessions_by_period(g, PERIODS, symbol="SPY")
    assert {k: len(v) for k, v in sbp.items()} == {"train": 2, "validation": 2, "evaluation": 0,
                                                    "reserve": 0}     # 2025 file is out of scope
    out = boundary.open_output(g, "exp001_real")
    rec = R.run({"train": sbp["train"], "validation": sbp["validation"], "evaluation": []},
                ledger_dir=out, declared_class="REAL_HISTORICAL_ADMITTED",
                session_loader=loader.loader_for(g))
    assert rec["route"] == "SESSION_LOADER_SUPPLIED"
    names = [s["stage"] for s in rec["stages"]]
    assert "fit" in names and "validation" in names, rec
    assert rec["status"] in ("NO_SIGNAL", "BLOCKED", "READY", "NO_OPPORTUNITY"), rec["status"]
    assert rec["status"] != "INVALID_INPUT"
    assert (out / "forecasts_validation.jsonl").exists()
    assert any(s["stage"] == "evaluation" and s["status"] == "BLOCKED" for s in rec["stages"])


# ------------------------------------ 6. laboratory boundary intact
def test_synthetic_lab_real_data_exclusion_is_unchanged(rig):
    for f, pin in (("apex/world_model/sources.py", PIN_SOURCES_PY),
                   ("apex/world_model/authority.py", PIN_AUTHORITY_PY)):
        assert hashlib.sha256((REPO / f).read_bytes()).hexdigest() == pin, f
    assert "/apex-data/history-a" in sources.REAL_EVIDENCE_ROOTS
    assert "/apex-data/history-b" in sources.REAL_EVIDENCE_ROOTS
    with pytest.raises(sources.SourceAdmissionRefused, match="^REAL_EVIDENCE_PATH"):
        sources.admit("/apex-data/history-b/etf_continuous/bars/SPY_2022-03-01.json",
                      declared_class="SYNTHETIC_FIXTURE", fixture_root=rig["tmp"])
    # a file THIS route admits is still not a laboratory fixture
    with pytest.raises(sources.SourceAdmissionRefused, match="^NO_PROVENANCE_MANIFEST|^OUTSIDE_FIXTURE_ROOT"):
        sources.admit(rig["ds"] / "SPY_2019-06-03.json", declared_class="SYNTHETIC_FIXTURE",
                      fixture_root=rig["tmp"] / "dataset")
    # and run() with no loader is the laboratory route: it refuses the dataset
    rec = R.run({"train": [str(rig["ds"] / "SPY_2019-06-03.json")], "validation": []},
                ledger_dir=rig["tmp"] / "lab_led", declared_class="SYNTHETIC_FIXTURE",
                fixture_root=rig["tmp"] / "nowhere")
    assert rec["status"] == "BLOCKED" and rec["route"] == "LABORATORY"
    assert rec["refusal"]["kind"] == "SourceAdmissionRefused"


# ----------------------------- 7. outputs cannot acquire authority
def test_research_outputs_carry_no_broker_or_live_authority(rig):
    g = _verify(rig, _write(rig, _body(rig)))
    out = boundary.open_output(g, "x")
    st = boundary.output_authority(out)
    assert st["authority_classification"] == "RESEARCH_HISTORICAL"
    for k in ("ORDER_AUTHORITY", "TRADING_AUTHORITY", "CAPITAL_AUTHORITY",
              "LIVE_DECISION_AUTHORITY", "MODEL_PROMOTION_AUTHORITY"):
        assert st["authority"][k] == "NONE"
    assert st["authority"]["ROBINHOOD_ACCESS"] == "FORBIDDEN"
    assert st["binding_spoof_resistance"] == "PARTIAL"
    for root in ("/apex-data/core/ops", "/apex-data/history-b/x", str(rig["tmp"] / "code" / "o")):
        _refused(rig, _write(rig, _body(rig, output__root=root)), "OUTPUT_ROOT_INVALID")
    with pytest.raises(RealDataRefused, match="^OUTPUT_UNSTAMPED"):
        boundary.output_authority(rig["tmp"])


def test_route_modules_reach_no_execution_layer():
    mods = [REPO / "apex/world_model/real_data" / n for n in ("boundary.py", "loader.py", "manifest.py")]
    mods.append(REPO / "scripts/exp001_real_execute.py")
    for m in mods:
        tree = ast.parse(m.read_text())
        imports = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
                  {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(i.startswith(("apex.execution", "apex.organism", "apex.capital")) for i in imports), (m, imports)
        consts = {n.value.lower() for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for bad in ("place_order", "place_equity_order", "place_option_order", "paper_book.jsonl"):
            assert not any(bad in c for c in consts), (m, bad)


# ---------------------------------- 8. child process provenance
def test_child_process_imports_the_intended_checkout():
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    r = subprocess.run([sys.executable, "-c",
                        "import apex.world_model.real_data.boundary as b, apex; print(b.__file__); print(apex.__file__)"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=60, env=env)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert all(Path(l).resolve().is_relative_to(REPO) for l in lines), lines


def test_execute_command_refuses_without_a_decision():
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    r = subprocess.run([sys.executable, str(REPO / "scripts/exp001_real_execute.py"), "--plan"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 3, (r.stdout, r.stderr)
    doc = json.loads(r.stdout)
    assert doc["status"] == "REFUSED" and doc["refusal"].startswith("NO_DECISION")


def test_execute_command_plan_opens_no_rows_and_keeps_evaluation_sealed(rig, monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("exp001_real_execute", REPO / "scripts/exp001_real_execute.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    monkeypatch.setattr(boundary, "ADMISSION_ROOT", rig["aroot"])
    monkeypatch.setattr(boundary, "ADMISSION_KEY_PATH", rig["key"])
    monkeypatch.setattr(boundary, "PERMITTED_HISTORICAL_ROOTS", (str(rig["tmp"] / "dataset"),))
    monkeypatch.setattr(boundary, "checkout_commit", lambda root=None: CODE)
    p = _write(rig, _body(rig))
    opened = []
    monkeypatch.setattr(boundary, "open_file", lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(AssertionError))
    assert mod.main(["--decision", str(p), "--plan"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "PLAN" and doc["sessions"] == {"train": 2, "validation": 2, "evaluation": 0}
    assert doc["evaluation"].startswith("SEALED") and opened == []
    assert not rig["out"].exists()                          # plan writes nothing
    # a decision for another experiment is refused by the command too
    p2 = _write(rig, _body(rig, purpose__experiment_id="ALPHA-EXP-002"), name="d2.json")
    assert mod.main(["--decision", str(p2), "--plan"]) == 3
    assert json.loads(capsys.readouterr().out)["refusal"].startswith("EXPERIMENT_MISMATCH")


# -------------------------- 9. registration and sealed evidence
def test_registration_and_sealed_evidence_unchanged():
    assert registration_hash() == PIN_REGISTRATION_HASH
    assert hashlib.sha256((REPO / "results/exp001_registration.json").read_bytes()).hexdigest() == PIN_REGISTRATION_JSON
    assert hashlib.sha256((REPO / "apex/world_model/exp001/registration.py").read_bytes()).hexdigest() == PIN_REGISTRATION_PY
