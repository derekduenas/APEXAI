"""EXP-004 historical adapter: it binds to `run.tournament` and nothing else.

Static AND runtime evidence that `apex.world_model.exp004.synthetic` is
unreachable from an admitted run, directly or transitively, and that every
record the adapter produces is a HISTORICAL one.

Synthetic fixtures only. No historical data, no admission, no execution.
"""
import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from apex.world_model.exp004 import historical as H4, run as R, synthetic as SY
from apex.world_model.exp004.registration import EXPERIMENT_ID, PERIODS, registration_hash
from tests import exp004_fixtures as X

REPO = Path(__file__).resolve().parents[1]
REG_HASH = "9155024f51825d13487cdc035432d85b357d22e39a40f967477873a7a6145bf9"
SYNTHETIC = "apex.world_model.exp004.synthetic"
ADAPTER_CHAIN = ("apex.world_model.exp004.historical", "apex.world_model.exp004.run",
                 "apex.world_model.exp004.features", "apex.world_model.exp004.models",
                 "apex.world_model.exp004.dispersion", "apex.world_model.exp004.inference",
                 "apex.world_model.exp004.bootstrap_adapter", "apex.world_model.exp004.registration")


def _imports(module_name: str) -> set:
    """Every module name this module's source imports, by AST — not by whatever
    happens to be in sys.modules."""
    src = Path(importlib.import_module(module_name).__file__)
    tree = ast.parse(src.read_text())
    pkg = module_name.rsplit(".", 1)[0]
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:                                    # relative import
                base = "%s.%s" % (pkg, base) if base else pkg
            names.add(base)
            names.update("%s.%s" % (base, a.name) for a in node.names)
    return names


# ------------------------------------------------------------------ static evidence

def test_adapter_imports_only_run_tournament_statically():
    names = _imports("apex.world_model.exp004.historical")
    assert "apex.world_model.exp004.run.tournament" in names, names
    assert not any("synthetic" in n for n in names), names
    src = Path(H4.__file__).read_text()
    assert "synthetic" in src, "the module should still NAME the forbidden module in its contract"
    tree = ast.parse(src)
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    attr_called = {"%s.%s" % (n.func.value.id, n.func.attr) for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and isinstance(n.func.value, ast.Name)}
    assert "tournament" in called, called
    assert not any("synthetic" in c for c in called | attr_called)
    assert H4.ENTRY_POINT == "apex.world_model.exp004.run.tournament"
    assert H4.FORBIDDEN_MODULE == SYNTHETIC


def test_no_transitive_route_to_synthetic_from_the_adapter_chain():
    for mod in ADAPTER_CHAIN:
        names = _imports(mod)
        assert not any("synthetic" in n for n in names), (mod, sorted(n for n in names if "synthetic" in n))
    # and the whole chain, imported in a FRESH interpreter, never loads the module
    code = ("import importlib, sys;"
            "[importlib.import_module(m) for m in %r];"
            "print('LOADED' if %r in sys.modules else 'ABSENT')" % (list(ADAPTER_CHAIN), SYNTHETIC))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "ABSENT", out.stdout
    # the synthetic module DOES depend on run -- the exclusion is one-directional
    assert any("run" in n for n in _imports(SYNTHETIC))


def test_execute_script_binds_exp004_to_the_adapter_only():
    src = (REPO / "scripts/alpha_exp_real_execute.py").read_text()
    assert "from apex.world_model.exp004 import historical as H4" in src
    assert "H4.run(" in src and "synthetic" not in src.replace(
        "# B = 10,000 / seed = 20260909, and exp004.synthetic is unreachable from here.", "")
    names = _imports("scripts.alpha_exp_real_execute") if False else set()      # script, not a package module
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.update("%s.%s" % (node.module, a.name) for a in node.names)
    assert not any("synthetic" in n for n in imported), imported


# ------------------------------------------------------------------ runtime evidence

@pytest.fixture(scope="module")
def loaded():
    """A loader over synthetic sessions, shaped like the governed one: it maps a
    path to a session dict and takes identity from the fixture, not the caller."""
    fit = X.fit_sessions()
    dev = X.dev_sessions_years()
    by_path = {"/fixture/%s.json" % s["session_date"]: s for s in fit + dev}
    sbp = {"fit": sorted(p for p, s in by_path.items() if s in fit),
           "development": sorted(p for p, s in by_path.items() if s in dev)}
    return {"sbp": sbp, "loader": lambda p: by_path[p], "n_fit": len(fit), "n_dev": len(dev)}


def test_adapter_run_never_reaches_synthetic_and_records_historical(loaded, monkeypatch, tmp_path):
    calls = {"synthetic_tournament": 0, "synthetic_score": 0, "tournament": 0, "core_modes": []}
    for name in ("synthetic_tournament", "synthetic_score"):
        real = getattr(SY, name)
        def tripwire(*a, _n=name, _r=real, **kw):
            calls[_n] += 1
            return _r(*a, **kw)
        monkeypatch.setattr(SY, name, tripwire)
    real_core = R._core
    def core_spy(*a, params, **kw):
        calls["core_modes"].append(params["run_mode"])
        return real_core(*a, params=params, **kw)
    monkeypatch.setattr(R, "_core", core_spy)
    real_t = R.tournament
    def t_spy(*a, **kw):
        calls["tournament"] += 1
        assert not kw, "the adapter must pass no keyword arguments"
        return real_t(*a, **kw)
    monkeypatch.setattr(H4, "tournament", t_spy)

    rec = H4.run(loaded["sbp"], ledger_dir=tmp_path, session_loader=loaded["loader"])

    assert calls["synthetic_tournament"] == 0 and calls["synthetic_score"] == 0
    assert calls["tournament"] == 1 and calls["core_modes"] == ["HISTORICAL"]
    assert rec["status"] in ("SELECTED", "NOT_SELECTED"), rec.get("refusal")
    assert rec["run_mode"] == "HISTORICAL"
    ip = rec["inference_parameters"]
    assert ip["historical_path_valid"] is True and ip["NOT_FOR_HISTORICAL_USE"] is False
    assert (ip["resamples"], ip["seed"]) == (10000, 20260909)
    assert rec["result"]["run_mode"] == "HISTORICAL" and "NOT_FOR_HISTORICAL_USE" not in rec["result"]
    assert rec["registration_hash"] == registration_hash() == REG_HASH
    assert rec["experiment"] == EXPERIMENT_ID
    assert rec["evaluation"].startswith("SEALED") and set(rec["never_opened"]) == {"evaluation", "reserve"}
    assert set(rec["period_roles"]) == {"fit", "development"}
    assert rec["period_roles"]["fit"] == list(PERIODS["fit"])
    assert [s["stage"] for s in rec["stages"]] == ["load:fit", "load:development"]
    assert rec["stages"][0]["sessions"] == loaded["n_fit"] and rec["stages"][1]["sessions"] == loaded["n_dev"]
    assert rec["economics"].startswith("NONE")
    R.strict_json(rec)
    assert H4.STATUS[rec["status"]] == "SCIENTIFIC_COMPLETE"


def test_adapter_refuses_sealed_periods_and_unexpected_arguments(loaded, tmp_path):
    for sealed in ("evaluation", "reserve"):
        rec = H4.run({**loaded["sbp"], sealed: ["/fixture/sealed.json"]},
                     ledger_dir=tmp_path, session_loader=loaded["loader"])
        assert rec["status"] == "INTEGRITY_FAILURE" and "SEALED_PERIODS_OFFERED" in rec["refusal"]["detail"]
        assert "result" not in rec
    rec = H4.run({"fit": loaded["sbp"]["fit"]}, ledger_dir=tmp_path, session_loader=loaded["loader"])
    assert rec["status"] == "INTEGRITY_FAILURE" and "NO_SESSIONS_FOR_REQUIRED_PERIOD" in rec["refusal"]["detail"]
    # no inference parameter can be smuggled through the adapter's signature
    rec = H4.run(loaded["sbp"], ledger_dir=tmp_path, session_loader=loaded["loader"], bootstrap_resamples=50)
    assert rec["status"] == "INTEGRITY_FAILURE" and "UNEXPECTED_ARGUMENTS" in rec["refusal"]["detail"]
    assert "bootstrap_resamples" in rec["refusal"]["detail"] and "result" not in rec


def test_adapter_refuses_a_non_historical_result(loaded, monkeypatch, tmp_path):
    """If anything ever returned a SYNTHETIC_TEST record, the adapter refuses it
    rather than sealing it as a historical result."""
    real = R.tournament
    def synthetic_shaped(fit, dev):
        out = real(fit, dev)
        out["run_mode"] = "SYNTHETIC_TEST"
        out["inference_parameters"] = {**out["inference_parameters"], "historical_path_valid": False,
                                       "NOT_FOR_HISTORICAL_USE": True, "resamples": 50}
        return out
    monkeypatch.setattr(H4, "tournament", synthetic_shaped)
    rec = H4.run(loaded["sbp"], ledger_dir=tmp_path, session_loader=loaded["loader"])
    assert rec["status"] == "INTEGRITY_FAILURE" and "NON_HISTORICAL_RESULT" in rec["refusal"]["detail"]
    assert H4.STATUS[rec["status"]] == "INVALID_INPUT_OR_FAILURE"


def test_loader_failure_is_a_named_refusal(loaded, tmp_path):
    def broken(path):
        raise KeyError("UNCOMMITTED_FILE: %s" % path)
    rec = H4.run(loaded["sbp"], ledger_dir=tmp_path, session_loader=broken)
    assert rec["status"] == "INTEGRITY_FAILURE" and rec["refusal"]["stage"] == "load"
    assert "UNCOMMITTED_FILE" in rec["refusal"]["detail"] and "result" not in rec
