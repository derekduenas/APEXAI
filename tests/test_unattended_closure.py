"""FINAL UNATTENDED ACCEPTANCE CLOSURE (2026-08-18).

Three pieces of machinery whose whole job is to keep an unattended
system honest, so each is tested for the way it could LIE rather than
the way it could crash:

  * apex.governance.ledger_error   -- a swallowed failure must still be
                                      durable, and recording a failure
                                      must never itself raise.
  * scripts/sidecar_gate.py        -- a sidecar must refuse on absent
                                      input rather than produce a
                                      session of self-referential
                                      REFUSED states.
  * scripts/natural_acceptance_observer.py
                                   -- an acceptance board with any path
                                      to a manual or absent-evidence
                                      PASS is worse than no board.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from apex.governance import ledger_error  # noqa: E402

import natural_acceptance_observer as obs  # noqa: E402
import sidecar_gate as gate  # noqa: E402

T0 = pd.Timestamp("2026-08-19T14:00:00Z")


def _imported_modules(path: str) -> set:
    """AST, not substring. A module's own prose about what it must never
    import trips a naive scan -- that mistake has been made three times in
    this repo already."""
    import ast
    names = set()
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _cli_flags(path: str) -> set:
    """Every string literal passed to an add_argument call."""
    import ast
    flags = set()
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    flags.add(arg.value)
    return flags


# ------------------------------------------------------ ledger_error
def test_record_never_raises_even_when_the_ledger_is_unwritable(monkeypatch,
                                                                tmp_path):
    """Recording a failure must not cascade into a second failure --
    that is how a sensor loop dies from an audit feature."""
    blocked = tmp_path / "nope"
    blocked.write_text("i am a file, not a directory")
    monkeypatch.setattr(ledger_error, "LEDGER", blocked / "x.jsonl")
    rec = ledger_error.record(service="s", operation="LEDGER_WRITE",
                              exc=RuntimeError("boom"))
    assert rec["exception"].startswith("RuntimeError")


def test_unknown_operation_is_normalised_not_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_error, "LEDGER", tmp_path / "e.jsonl")
    rec = ledger_error.record(service="s", operation="NOT_A_REAL_OP",
                              exc=ValueError("v"))
    assert rec["operation"] == "OTHER"


def test_recorded_error_is_readable_back_and_summarised(tmp_path, monkeypatch):
    p = tmp_path / "e.jsonl"
    monkeypatch.setattr(ledger_error, "LEDGER", p)
    ledger_error.record(service="alpaca_fabric", operation="LEDGER_WRITE",
                        exc=OSError("disk"))
    ledger_error.record(service="frontier2_shadow_runtime",
                        operation="HEALTH_READ", exc=KeyError("k"))
    rows = ledger_error.read_all(p)
    assert len(rows) == 2
    s = ledger_error.summarize(path=p)
    assert s["total"] == 2
    assert s["by_operation"]["LEDGER_WRITE"] == 1
    assert s["by_service"]["alpaca_fabric"] == 1


def test_error_record_carries_no_decision_power(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_error, "LEDGER", tmp_path / "e.jsonl")
    rec = ledger_error.record(service="s", operation="OTHER",
                              exc=RuntimeError("x"))
    assert rec["decision_power"] == "NONE"


def test_the_three_swallowing_handlers_are_actually_wired():
    """The audit found three handlers that continued silently. Each must
    now reach the durable path -- a bare `pass` in any of them is the
    regression."""
    fabric = Path("apex/intraday/alpaca_fabric.py").read_text()
    assert "ledger_error import record as _lerr" in fabric
    runtime = Path("scripts/frontier2_shadow_runtime.py").read_text()
    assert runtime.count('_ledger_error("') >= 2
    assert "from apex.governance.ledger_error import record" in runtime


# --------------------------------------------------------- sidecar gate
def _health(tmp_path, monkeypatch, **over):
    p = tmp_path / "alpaca_fabric_health.json"
    d = {"status": "HEALTHY", "counters": {"reconnects": 0}}
    d.update(over)
    p.write_text(json.dumps(d))
    # the fixture clock is T0; without this the freshness check fires
    # first and every status test would pass for the wrong reason
    import os
    os.utime(p, (T0.timestamp(), T0.timestamp()))
    monkeypatch.setattr(gate, "ALPACA_HEALTH", p)
    return p


def test_options_gate_refuses_when_health_artifact_is_absent(tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr(gate, "ALPACA_HEALTH", tmp_path / "absent.json")
    monkeypatch.setattr(gate, "GATE_LEDGER", tmp_path / "g.jsonl")
    d = gate._decide("options-analytics", T0)
    assert d["admitted"] is False
    assert d["cause"] == "UPSTREAM_HEALTH_ARTIFACT_ABSENT"


def test_options_gate_refuses_on_unhealthy_upstream(tmp_path, monkeypatch):
    _health(tmp_path, monkeypatch, status="FAILED")
    monkeypatch.setattr(gate, "GATE_LEDGER", tmp_path / "g.jsonl")
    d = gate._decide("options-analytics", T0)
    assert d["admitted"] is False
    assert d["cause"] == "UPSTREAM_NOT_HEALTHY"


def test_options_gate_refuses_on_stale_health(tmp_path, monkeypatch):
    p = _health(tmp_path, monkeypatch)
    import os
    old = T0.timestamp() - gate.HEALTH_MAX_AGE_S - 60
    os.utime(p, (old, old))
    monkeypatch.setattr(gate, "GATE_LEDGER", tmp_path / "g.jsonl")
    d = gate._decide("options-analytics", T0)
    assert d["admitted"] is False
    assert d["cause"] == "UPSTREAM_HEALTH_STALE"


def test_options_gate_budget_ends_exactly_at_the_close(tmp_path, monkeypatch):
    _health(tmp_path, monkeypatch)
    monkeypatch.setattr(gate, "GATE_LEDGER", tmp_path / "g.jsonl")
    # 14:00Z == 10:00 ET -> 360 minutes to the 16:00 ET close
    d = gate._decide("options-analytics", T0)
    assert d["admitted"] is True
    assert d["budget_minutes"] == pytest.approx(360.0, abs=0.1)


def test_options_gate_refuses_after_the_close(tmp_path, monkeypatch):
    late = pd.Timestamp("2026-08-19T19:58:00Z")     # 15:58 ET
    p = _health(tmp_path, monkeypatch)
    import os
    os.utime(p, (late.timestamp(), late.timestamp()))
    monkeypatch.setattr(gate, "GATE_LEDGER", tmp_path / "g.jsonl")
    d = gate._decide("options-analytics", late)
    assert d["admitted"] is False
    assert d["cause"] == "NO_REGULAR_SESSION_REMAINING"


def test_partial_upstream_still_admits():
    """PARTIAL coverage is a legitimate observation subject -- refusing it
    would discard exactly the degraded sessions worth studying."""
    assert "PARTIAL" in gate.ADMITTING_HEALTH


def test_forensics_gate_refuses_without_close_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gate, "GATE_LEDGER", tmp_path / "g.jsonl")
    d = gate._decide("daily-forensics", T0)
    assert d["admitted"] is False
    assert d["cause"] == "CLOSE_ARTIFACTS_ABSENT"


def test_forensics_gate_admits_once_the_close_artifact_exists(tmp_path,
                                                              monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gate, "GATE_LEDGER", tmp_path / "g.jsonl")
    date = str(T0.tz_convert("America/New_York").date())
    d = tmp_path / "results/frontier/daily_memory"
    d.mkdir(parents=True)
    (d / f"{date}.json").write_text("{}")
    out = gate._decide("daily-forensics", T0)
    assert out["admitted"] is True


def test_gate_refusal_is_durable(tmp_path, monkeypatch):
    """A sidecar that never ran must leave a record saying why -- an empty
    output directory reads identically to 'ran and found nothing'."""
    led = tmp_path / "g.jsonl"
    monkeypatch.setattr(gate, "GATE_LEDGER", led)
    monkeypatch.setattr(gate, "ALPACA_HEALTH", tmp_path / "absent.json")
    gate._append(gate._decide("options-analytics", T0))
    rows = [json.loads(x) for x in led.read_text().splitlines() if x.strip()]
    assert rows[-1]["cause"] == "UPSTREAM_HEALTH_ARTIFACT_ABSENT"


def test_gate_never_imports_decision_authority():
    mods = _imported_modules("scripts/sidecar_gate.py")
    for m in mods:
        assert not m.startswith(("apex.hunter", "apex.captain",
                                 "apex.execution", "apex.frontier")), m


# -------------------------------------------------- acceptance observer
def test_observer_has_no_argument_that_can_force_a_pass():
    """The board must be unforgeable from the command line. Checked
    against the ACTUAL argparse surface -- the module's prose says the
    word "--pass" while promising not to accept one."""
    flags = _cli_flags("scripts/natural_acceptance_observer.py")
    assert flags == {"--session-date"}, flags


def test_absent_evidence_is_never_a_pass(tmp_path, monkeypatch):
    """The whole point. Run the observer against an EMPTY artifact tree:
    not one item may report PASS on the strength of a missing file."""
    monkeypatch.chdir(tmp_path)
    board = obs.observe("2026-08-19")
    verdicts = {i["id"]: i["verdict"] for i in board["items"]}
    evidence_items = {k: v for k, v in verdicts.items()
                      if k not in ("G1", "I1", "Z1")}
    assert obs.PASS not in evidence_items.values(), evidence_items
    assert board["overall"] != "NATURALLY_ACCEPTED"


def test_missing_rate_provenance_fails_rather_than_passes(tmp_path, monkeypatch):
    """The observer's own first draft returned PASS over 336 states that
    carried a hardcoded rate=0.04 and no provenance field, because it read
    absence as cleanliness. That must stay fixed."""
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "results/option_analytics/live"
    p.mkdir(parents=True)
    (p / "states.jsonl").write_text(json.dumps(
        {"as_of": "2026-08-19T17:00:00+00:00", "rate": 0.04}) + "\n")
    item = obs._rate_input_honesty("2026-08-19")
    assert item["verdict"] == obs.FAIL
    assert "provenance" in item["evidence"]


def test_unlabelled_dte_sample_fails_rather_than_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "results/option_analytics/live"
    p.mkdir(parents=True)
    (p / "states.jsonl").write_text(json.dumps(
        {"as_of": "2026-08-19T17:00:00+00:00"}) + "\n")
    item = obs._dte_bucket_coverage("2026-08-19")
    assert item["verdict"] == obs.FAIL


def test_session_date_matching_uses_eastern_not_utc_prefix():
    """An artifact written at 20:22 ET carries the NEXT UTC date. Prefix-
    matching the UTC string against the session date silently drops every
    late-session record -- it made the observer report Hunter as having no
    heartbeat while Hunter was running fine."""
    assert obs._et_date("2026-08-19 03:22:16.148759+00:00") == "2026-08-18"
    assert obs._et_date("2026-08-18 17:33:13+00:00") == "2026-08-18"
    assert obs._et_date(None) is None
    assert obs._et_date("not a timestamp") is None


def test_frozen_captain_state_is_a_fail_not_a_pass(tmp_path, monkeypatch):
    """Decisions recorded but never triggering review IS the 2026-08-18
    freeze. It must not read as a quiet market."""
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "results/frontier2"
    p.mkdir(parents=True)
    rows = [{"as_of": "2026-08-19T15:00:00+00:00", "subject": "AAPL",
             "should_review": False} for _ in range(40)]
    (p / "reunderwrite_ledger.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows))
    item = obs._captain_reunderwrites("2026-08-19")
    assert item["verdict"] == obs.FAIL
    assert "freeze" in item["evidence"]


def test_identical_trigger_run_is_flagged_as_phantom(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "results/frontier2"
    p.mkdir(parents=True)
    rows = [{"as_of": "2026-08-19T15:00:00+00:00", "subject": "AAPL",
             "should_review": True,
             "triggers": ["ASSASSIN_WOUND_CHANGE"]} for _ in range(12)]
    (p / "reunderwrite_ledger.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows))
    item = obs._no_phantom_triggers("2026-08-19")
    assert item["verdict"] == obs.FAIL


def test_reconstructed_anchor_can_never_certify_an_opening(tmp_path,
                                                           monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "results/intraday"
    p.mkdir(parents=True)
    (p / "session_anchor_evidence.jsonl").write_text(json.dumps(
        {"as_of": "2026-08-19T13:30:00+00:00", "certification": "PROVEN_LIVE",
         "reconstructed_after_the_fact": True}) + "\n")
    item = obs._session_anchor("2026-08-19")
    assert item["verdict"] == obs.FAIL


def test_a_crashing_item_reads_as_fail_not_as_pass(monkeypatch):
    def boom(_date):
        raise RuntimeError("observer bug")
    monkeypatch.setattr(obs, "ITEMS", (boom,))
    board = obs.observe("2026-08-19")
    assert board["items"][0]["verdict"] == obs.FAIL
    assert board["overall"] == "NOT_ACCEPTED"


def test_board_declares_zero_manual_checkboxes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    board = obs.observe("2026-08-19")
    assert board["manual_checkboxes"] == 0
    assert board["decision_power"] == "NONE_OBSERVABILITY"


def test_observer_never_imports_decision_authority():
    mods = _imported_modules("scripts/natural_acceptance_observer.py")
    for m in mods:
        assert not m.startswith(("apex.hunter", "apex.captain",
                                 "apex.execution", "apex.frontier2")), m


def test_every_item_names_the_failure_it_catches(tmp_path, monkeypatch):
    """A board item with no stated failure mode is decoration."""
    monkeypatch.chdir(tmp_path)
    board = obs.observe("2026-08-19")
    for it in board["items"]:
        assert it["catches"], f"{it['id']} states no failure mode"
        assert it["source"], f"{it['id']} names no evidence source"


# -------------------------------------------------- scheduling truth
def test_both_sidecar_jobs_are_scheduled_and_classified():
    for name, cls in (("com.apex.option-analytics", "OBSERVATIONAL_SIDECAR"),
                      ("com.apex.daily-forensics", "POST_CLOSE_ANALYTICS")):
        plist = Path(f"ops/{name}.plist")
        assert plist.exists(), f"{name} has no plist"
        assert cls in plist.read_text(), f"{name} is not classified"


def test_sidecar_wrappers_turn_a_refusal_into_a_clean_noop():
    """`|| exit 0` -- a gate refusal must not present as a launchd crash,
    or launchd's own failure semantics start reporting on our honesty."""
    for sh in ("ops/option_analytics_sidecar.sh", "ops/daily_forensics.sh"):
        src = Path(sh).read_text()
        assert "sidecar_gate.py" in src
        assert "exit 0" in src


def test_post_close_job_runs_the_acceptance_board():
    """'0 manual close tasks' requires the board to be part of the job."""
    src = Path("ops/daily_forensics.sh").read_text()
    assert "natural_acceptance_observer.py" in src


def test_the_phase1_memory_module_does_not_compete_for_canonical():
    from apex.memory import daily_market_memory as m
    assert m.ROLE == "ENRICHED_RESEARCH_MEMORY_SIDECAR"
    assert m.CANONICAL_MEMORY_WRITER == "apex.frontier.closing.write_memory"
    assert "results/frontier/daily_memory" in m.CANONICAL_MEMORY_PATH


def test_no_second_memory_writer_is_scheduled():
    """The operator ruling: do not delete it, do not schedule it."""
    for plist in Path("ops").glob("com.apex.*.plist"):
        assert "daily_market_memory" not in plist.read_text(), plist
    for sh in Path("ops").glob("*.sh"):
        assert "daily_market_memory" not in sh.read_text(), sh


def test_every_ops_plist_is_well_formed_xml():
    """`plutil -lint` accepted a comment containing `--`, which is illegal
    inside an XML comment; launchd's own lenient parser loaded it too, and
    only a strict reader caught it. A plist that only SOME parsers accept
    is a job waiting to silently not run."""
    import plistlib
    for f in sorted(Path("ops").glob("com.apex.*.plist")):
        with f.open("rb") as fh:
            d = plistlib.load(fh)
        assert d.get("Label"), f
        assert d.get("ProgramArguments"), f


def test_scheduled_ops_scripts_exist_and_are_executable():
    import sys as _sys
    if _sys.platform != "darwin":
        import pytest
        pytest.skip("verifies the Mac host launchd/ops installation -- "
                    "Darwin-only by nature; cloud uses systemd (C6)")
    """A loaded job pointing at a missing script fails silently at its
    scheduled minute, which is the worst possible time to find out."""
    import plistlib
    import re
    for f in sorted(Path("ops").glob("com.apex.*.plist")):
        with f.open("rb") as fh:
            args = plistlib.load(fh)["ProgramArguments"]
        if "-c" in args:
            # `zsh -c "<command>"`: args[-1] is a SHELL COMMAND, not a path.
            # Treating it as a path is exactly the mistake the forensic
            # audit script made -- extract the real script instead.
            targets = [Path(m) for m in
                       re.findall(r"[\w./$-]+\.(?:sh|py)", args[-1])]
            assert targets, f"{f.name}: no script found in {args[-1]!r}"
        else:
            targets = [Path(args[-1])]
        for t in targets:
            t = Path(str(t).replace("$HOME/apex-equities/", "")
                     .replace("$HOME/apex-equities", "."))
            if t.is_absolute():
                assert t.exists(), f"{f.name} -> missing {t}"
            else:
                assert t.exists(), f"{f.name} -> missing {t} (relative to repo)"


def test_production_error_ledger_is_protected_from_tests():
    """Phase 17 (2026-08-20): 17 pytest rows had accumulated in the
    PRODUCTION error ledger, indistinguishable from live incidents. A
    test reaching the real ledger (unmonkeypatched) is refused; the
    monkeypatched-tmp-path tests above prove normal writes still work."""
    before = (ledger_error._PRODUCTION_LEDGER.read_text()
              if ledger_error._PRODUCTION_LEDGER.exists() else "")
    rec = ledger_error.record(service="test_isolation_probe",
                              operation="OTHER",
                              exc=ValueError("must not persist"))
    assert rec.get("suppressed") == "TEST_CONTEXT"
    after = (ledger_error._PRODUCTION_LEDGER.read_text()
             if ledger_error._PRODUCTION_LEDGER.exists() else "")
    assert before == after, "a test wrote into the production ledger"
