"""WM-0A -- the firewall must refuse, and refuse for the right reason.

The realistic contamination is not malice. `/apex-data/core/btc/
window_outcomes.jsonl` is right there and it is exactly the shape a
label wants. One convenient import and no World Model result is
trustworthy again -- and that cannot be detected afterwards, because you
cannot un-see a label. These tests exist so the boundary is a mechanism
rather than a promise.
"""
import json

import pytest

from apex.world_model import (AUTHORITY_DIGEST, DECISION_POWER,
                              TRAINING_AUTHORIZED,
                              WORLD_MODEL_RESEARCH_AUTHORITY_V0,
                              WorldModelAuthorityViolation, admit,
                              assert_authority)
from apex.world_model.authority import digest
from apex.world_model.sources import (REAL_EVIDENCE_ROOTS,
                                      SourceAdmissionRefused,
                                      real_evidence_root_for, sha256_of)


# ------------------------------------------------- the contract itself
def test_the_package_grants_nothing():
    assert TRAINING_AUTHORIZED is False
    assert DECISION_POWER == "NONE_RESEARCH_ISOLATION"
    m = assert_authority()
    for k in ("REAL_MARKET_LABEL_ACCESS", "REAL_MARKET_MODEL_FITTING",
              "PROSPECTIVE_OUTCOME_ACCESS", "P_AND_L_ACCESS",
              "BOOK_OUTCOME_ACCESS", "ROBINHOOD_ACCESS",
              "PRODUCTION_DEPLOYMENT"):
        assert m[k] == "FORBIDDEN", k
    for k in ("ORDER_AUTHORITY", "TRADING_AUTHORITY", "CAPITAL_AUTHORITY"):
        assert m[k] == "NONE", k


def test_missing_manifest_refuses():
    with pytest.raises(WorldModelAuthorityViolation):
        assert_authority({})


def test_malformed_manifest_refuses():
    for bad in ("not a dict", 42, [], {"contract": "SOMETHING_ELSE"}):
        with pytest.raises(WorldModelAuthorityViolation):
            assert_authority(bad)


def test_a_dropped_prohibition_is_a_widened_permission():
    m = dict(WORLD_MODEL_RESEARCH_AUTHORITY_V0)
    del m["PROSPECTIVE_OUTCOME_ACCESS"]
    with pytest.raises(WorldModelAuthorityViolation, match="missing"):
        assert_authority(m)


def test_a_widened_prohibition_refuses():
    for k, good in (("REAL_MARKET_LABEL_ACCESS", "ALLOWED"),
                    ("ORDER_AUTHORITY", "FULL")):
        m = dict(WORLD_MODEL_RESEARCH_AUTHORITY_V0)
        m[k] = good
        with pytest.raises(WorldModelAuthorityViolation):
            assert_authority(m)


def test_runtime_mutation_of_the_manifest_is_detected():
    """A caller widening its own permissions in-process."""
    original = WORLD_MODEL_RESEARCH_AUTHORITY_V0["ORDER_AUTHORITY"]
    WORLD_MODEL_RESEARCH_AUTHORITY_V0["SOMETHING_EXTRA"] = "ALLOWED"
    try:
        assert digest() != AUTHORITY_DIGEST
        with pytest.raises(WorldModelAuthorityViolation, match="MUTATED"):
            assert_authority()
    finally:
        WORLD_MODEL_RESEARCH_AUTHORITY_V0.pop("SOMETHING_EXTRA", None)
        WORLD_MODEL_RESEARCH_AUTHORITY_V0["ORDER_AUTHORITY"] = original
    assert_authority()          # restored


# ---------------------------------------------- forbidden source classes
@pytest.mark.parametrize("cls", ["REAL_HISTORICAL_LABEL",
                                 "REAL_PROSPECTIVE_OUTCOME",
                                 "BOOK_PNL", "REAL_EXECUTION_RESULT"])
def test_forbidden_source_class_refused(tmp_path, cls):
    f = tmp_path / "x.jsonl"
    f.write_text("{}\n")
    with pytest.raises(SourceAdmissionRefused,
                       match="FORBIDDEN_SOURCE_CLASS"):
        admit(f, declared_class=cls)


def test_unknown_source_class_refused_not_defaulted(tmp_path):
    f = tmp_path / "x.jsonl"
    f.write_text("{}\n")
    with pytest.raises(SourceAdmissionRefused, match="UNKNOWN_SOURCE_CLASS"):
        admit(f, declared_class="PROBABLY_FINE")


# ============================ THE ONE THAT MATTERS =====================
def test_caller_CANNOT_launder_real_evidence_by_declaring_it_synthetic(
        tmp_path):
    """Declaring SYNTHETIC_FIXTURE over a real evidence path must fail.

    If this passes by label, the whole module is decoration."""
    for real in ("/apex-data/core/btc/window_outcomes.jsonl",
                 "/apex-data/core/btc/paper_ledger.jsonl",
                 "/apex-data/core/edgeforge/research_board_v2.jsonl",
                 "/apex-data/runtime/data/live/alpaca_fabric/bars",
                 "/apex-data/history-a/options_history",
                 "/opt/apex-repo/results/organism/edge_sensor.jsonl"):
        with pytest.raises(SourceAdmissionRefused,
                           match="REAL_EVIDENCE_PATH"):
            admit(real, declared_class="SYNTHETIC_FIXTURE")


def test_symlink_into_real_evidence_is_refused(tmp_path):
    """The deny decision is made on the RESOLVED path, so a symlink
    cannot walk out of the fixture root."""
    root = tmp_path / "fixtures"
    root.mkdir()
    link = root / "innocent.jsonl"
    try:
        link.symlink_to("/apex-data/core/btc/window_outcomes.jsonl")
    except OSError:
        pytest.skip("cannot create symlink here")
    with pytest.raises(SourceAdmissionRefused, match="REAL_EVIDENCE_PATH"):
        admit(link, declared_class="SYNTHETIC_FIXTURE", fixture_root=root)


def test_dotdot_traversal_out_of_the_fixture_root_is_refused(tmp_path):
    root = tmp_path / "fixtures"
    root.mkdir()
    escaped = root / ".." / ".." / "etc" / "hostname"
    with pytest.raises(SourceAdmissionRefused, match="OUTSIDE_FIXTURE_ROOT"):
        admit(escaped, declared_class="SYNTHETIC_FIXTURE", fixture_root=root)


def test_every_declared_real_evidence_root_is_actually_denied():
    """The deny list must cover what it claims to cover."""
    for root in REAL_EVIDENCE_ROOTS:
        assert real_evidence_root_for(root + "/anything.jsonl") is not None, \
            "%s is in the list but does not deny" % root


# -------------------------------------------- provenance, not vibes
def _fixture_root(tmp_path, files, declare=True):
    root = tmp_path / "fixtures"
    root.mkdir()
    entries = {}
    for name, body, cls in files:
        p = root / name
        p.write_text(body)
        if declare:
            entries[name] = {"sha256": sha256_of(p), "source_class": cls,
                             "generator": "test"}
    (root / "_PROVENANCE.json").write_text(json.dumps({"fixtures": entries}))
    return root


def test_a_file_merely_present_in_the_fixture_root_is_not_a_fixture(tmp_path):
    root = _fixture_root(tmp_path, [], declare=True)
    sneaked = root / "sneaked.jsonl"
    sneaked.write_text("real looking data\n")
    with pytest.raises(SourceAdmissionRefused, match="UNDECLARED_FIXTURE"):
        admit(sneaked, declared_class="SYNTHETIC_FIXTURE", fixture_root=root)


def test_missing_provenance_manifest_refuses(tmp_path):
    root = tmp_path / "fixtures"
    root.mkdir()
    f = root / "a.jsonl"
    f.write_text("{}\n")
    with pytest.raises(SourceAdmissionRefused, match="NO_PROVENANCE_MANIFEST"):
        admit(f, declared_class="SYNTHETIC_FIXTURE", fixture_root=root)


def test_content_changed_after_declaration_refuses(tmp_path):
    root = _fixture_root(tmp_path, [("a.jsonl", "{}\n", "SYNTHETIC_FIXTURE")])
    (root / "a.jsonl").write_text("{} swapped\n")
    with pytest.raises(SourceAdmissionRefused,
                       match="PROVENANCE_HASH_MISMATCH"):
        admit(root / "a.jsonl", declared_class="SYNTHETIC_FIXTURE",
              fixture_root=root)


def test_the_provenance_record_wins_over_the_caller(tmp_path):
    root = _fixture_root(tmp_path, [("a.jsonl", "{}\n", "NULL_FIXTURE")])
    with pytest.raises(SourceAdmissionRefused,
                       match="PROVENANCE_CLASS_MISMATCH"):
        admit(root / "a.jsonl", declared_class="SYNTHETIC_FIXTURE",
              fixture_root=root)


def test_a_properly_declared_fixture_IS_admitted(tmp_path):
    """The boundary must not be so tight it admits nothing -- a firewall
    that refuses everything is untestable, not safe."""
    root = _fixture_root(tmp_path, [("ok.jsonl", "{}\n", "SYNTHETIC_FIXTURE")])
    r = admit(root / "ok.jsonl", declared_class="SYNTHETIC_FIXTURE",
              fixture_root=root)
    assert r["admitted"] is True
    assert r["source_class"] == "SYNTHETIC_FIXTURE"


def test_admission_refuses_when_the_authority_is_broken(tmp_path):
    root = _fixture_root(tmp_path, [("ok.jsonl", "{}\n", "SYNTHETIC_FIXTURE")])
    with pytest.raises(SourceAdmissionRefused, match="AUTHORITY_INVALID"):
        admit(root / "ok.jsonl", declared_class="SYNTHETIC_FIXTURE",
              fixture_root=root, manifest={"contract": "WRONG"})


# ------------------------------------------------------ broker firewall
def test_the_package_has_no_broker_or_placement_surface():
    """STRUCTURAL, not substring.

    A substring scan fails here for a good reason: the manifest MUST say
    ROBINHOOD_ACCESS = FORBIDDEN, and you cannot forbid what you refuse
    to name. APEX already learned this when its architecture guard had
    to exempt sealing.py and robinhood.py for naming the verbs they deny.
    So the real invariant is about IMPORTS and DEFINITIONS: this package
    may not import a broker, and may not define a placement callable."""
    import ast
    import pathlib
    import apex.world_model as wm
    pkg = pathlib.Path(wm.__file__).parent

    banned_imports = ("robinhood", "robin_stocks", "alpaca", "ib_insync",
                      "apex.execution", "apex.hunter.broker",
                      "apex.organism", "apex.portfolio")
    placement_verbs = ("place_order", "place_equity_order",
                       "place_option_order", "submit_order",
                       "execute_order", "send_order", "buy_shares",
                       "sell_shares")
    for f in pkg.glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    for b in banned_imports:
                        assert not a.name.lower().startswith(b), \
                            "%s imports %s" % (f.name, a.name)
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").lower()
                for b in banned_imports:
                    assert not mod.startswith(b), \
                        "%s imports from %s" % (f.name, node.module)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in placement_verbs, \
                    "%s DEFINES placement callable %s" % (f.name, node.name)
            elif isinstance(node, ast.Call):
                fn = node.func
                nm = getattr(fn, "attr", None) or getattr(fn, "id", None)
                assert nm not in placement_verbs, \
                    "%s CALLS %s" % (f.name, nm)


def test_the_only_apex_imports_are_within_world_model():
    """The package must not reach into production APEX at all."""
    import ast
    import pathlib
    import apex.world_model as wm
    pkg = pathlib.Path(wm.__file__).parent
    for f in pkg.glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            mod = None
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
            elif isinstance(node, ast.Import):
                mod = node.names[0].name
            if mod and mod.startswith("apex"):
                assert mod.startswith("apex.world_model"), \
                    "%s imports production module %s" % (f.name, mod)


def test_no_bypass_switch_exists():
    """No force flag, no env var, no override kwarg."""
    import inspect
    import pathlib
    import apex.world_model as wm
    pkg = pathlib.Path(wm.__file__).parent
    for p in pkg.glob("*.py"):
        src = p.read_text()
        for b in ("os.environ", "getenv", "force=", "override=",
                  "allow_real", "skip_check", "unsafe"):
            assert b not in src, "%s contains a bypass affordance: %s" % (
                p.name, b)
    sig = inspect.signature(admit)
    assert set(sig.parameters) == {"path", "declared_class", "manifest",
                                   "fixture_root"}
