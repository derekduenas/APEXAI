"""Phase 1.0 observability: Hunter service progress + watchdog, Morning
Prior manifest durability, Curve observational metrics, and the
DailyMarketMemory YESTERDAY_STATE law.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from apex.frontier2 import curve_metrics
from apex.hunter import service_progress_hunter as sph
from apex.memory import daily_market_memory as dmm
from apex.memory import morning_prior_manifest as mpm

T0 = pd.Timestamp("2026-08-18T13:30:00Z")


# ---- Hunter observability -------------------------------------------------

def test_hunter_progress_starts_in_starting(tmp_path):
    """API updated in Phase 1.1: hunter_forward_clock is a RECURRING
    ONESHOT, so `start()` became `load_or_advance()` and the cycle
    counter persists across process boundaries. A brand-new state with
    a first cycle recorded but no success yet is STARTING only before
    any cycle is counted."""
    s = sph.HunterProgressState(
        service_name="hunter_forward_clock", pid=1,
        start_time=str(T0), expected_cadence_s=900.0)
    assert s.progress_status() == "STARTING"


def test_pid_alive_is_not_healthy(tmp_path):
    """A cycle that starts but never completes is STALLED even with a
    live PID -- the 2026-08-17 law, applied to Hunter."""
    s = sph.load_or_advance(path=tmp_path / "hp.json")
    s.cycle_number = 5
    s.last_cycle_start = str(T0)
    s.last_successful_cycle = None
    assert s.progress_status() == "STALLED"


def test_hunter_watchdog_reports_stopped_when_no_artifact(tmp_path):
    r = sph.watchdog_check(tmp_path / "nope.json")
    assert r["watchdog_status"] == "STOPPED"


def test_hunter_watchdog_flags_heartbeat_without_progress(tmp_path):
    import os
    s = sph.load_or_advance(path=tmp_path / "seed.json")
    s.pid = os.getpid()
    s.cycle_number = 3
    s.last_cycle_start = str(pd.Timestamp.now(tz="UTC"))
    s.last_successful_cycle = None
    p = tmp_path / "hp.json"
    sph.write(s, p)
    r = sph.watchdog_check(p)
    assert r["watchdog_status"] == "STALLED"
    assert "heartbeat without progress" in r["watchdog_reason"]


def test_hunter_watchdog_healthy_on_recent_success(tmp_path):
    import os
    s = sph.load_or_advance(path=tmp_path / "seed.json")
    s.pid = os.getpid()
    s.cycle_number = 4
    now = pd.Timestamp.now(tz="UTC")
    s.last_cycle_start = str(now)
    s.last_successful_cycle = str(now)
    s.states_computed = 150
    s.watchlist_count = 20
    p = tmp_path / "hp.json"
    sph.write(s, p)
    r = sph.watchdog_check(p)
    assert r["watchdog_status"] == "HEALTHY"
    assert r["agrees_with_self_report"] is True
    assert r["states_computed"] == 150


def test_hunter_progress_grants_no_authority(tmp_path):
    s = sph.load_or_advance(path=tmp_path / "hp.json")
    assert s.decision_power == "NONE_OBSERVABILITY"


# ---- Morning Prior manifest ------------------------------------------------

def test_locate_returns_none_when_never_registered(tmp_path, monkeypatch):
    monkeypatch.setattr(mpm, "LEDGER", tmp_path / "mp.jsonl")
    assert mpm.locate("2026-08-18") is None


def test_register_refuses_a_nonexistent_path(tmp_path, monkeypatch):
    monkeypatch.setattr(mpm, "LEDGER", tmp_path / "mp.jsonl")
    with pytest.raises(mpm.MorningPriorManifestError):
        mpm.register(session_date="2026-08-19",
                     canonical_path=tmp_path / "ghost.json",
                     source_health={}, known_from=T0, now=T0)


def test_registered_prior_is_deterministically_locatable(tmp_path, monkeypatch):
    monkeypatch.setattr(mpm, "LEDGER", tmp_path / "mp.jsonl")
    art = tmp_path / "morning_prior_2026-08-19.json"
    art.write_text(json.dumps({"regime": "UNKNOWN"}))
    mpm.register(session_date="2026-08-19", canonical_path=art,
                 source_health={"alpaca": "HEALTHY"}, known_from=T0, now=T0)
    found = mpm.locate("2026-08-19")
    assert found is not None
    assert found["integrity"] == "INTACT"
    assert found["canonical_path"] == str(art)


def test_tampered_prior_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(mpm, "LEDGER", tmp_path / "mp.jsonl")
    art = tmp_path / "morning_prior_2026-08-19.json"
    art.write_text(json.dumps({"regime": "UNKNOWN"}))
    mpm.register(session_date="2026-08-19", canonical_path=art,
                 source_health={}, known_from=T0, now=T0)
    art.write_text(json.dumps({"regime": "TAMPERED"}))
    assert mpm.locate("2026-08-19")["integrity"] == "CONTENT_HASH_MISMATCH"


def test_deleted_prior_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(mpm, "LEDGER", tmp_path / "mp.jsonl")
    art = tmp_path / "mp_art.json"
    art.write_text("{}")
    mpm.register(session_date="2026-08-19", canonical_path=art,
                 source_health={}, known_from=T0, now=T0)
    art.unlink()
    assert mpm.locate("2026-08-19")["integrity"] == "REGISTERED_BUT_MISSING_ON_DISK"


# ---- Curve observational metrics (measurement only) ------------------------

def test_curve_metrics_on_empty_ledger_is_honest(tmp_path):
    m = curve_metrics.compute(subject="SPY", session_date="2026-08-18",
                              ledger_path=tmp_path / "none.jsonl", now=T0)
    assert m.n_records == 0
    assert m.mean_state_duration_s is None


def test_curve_metrics_counts_flips_and_durations(tmp_path):
    p = tmp_path / "curve.jsonl"
    rows = []
    for i, st in enumerate(["POSITIVE_TRANSITION", "POSITIVE_TRANSITION",
                            "NEGATIVE_TRANSITION", "POSITIVE_TRANSITION"]):
        rows.append(json.dumps({
            "subject": "SPY", "high_level_state": st,
            "transition_direction": "UP" if "POSITIVE" in st else "DOWN",
            "as_of": str(T0 + pd.Timedelta(minutes=i))}))
    p.write_text("\n".join(rows))
    m = curve_metrics.compute(subject="SPY", session_date="2026-08-18",
                              ledger_path=p, now=T0 + pd.Timedelta(minutes=4))
    assert m.n_records == 4
    assert m.state_flip_count == 2
    assert m.transition_reversal_count == 1     # POS -> NEG -> POS
    assert m.state_durations_s["POSITIVE_TRANSITION"] > 0


def test_curve_metrics_module_cannot_change_curve_behavior():
    """Measurement only: this module must not import curve.py at all,
    so it structurally cannot smooth or re-threshold anything. Checked
    against real AST import nodes -- matching raw source text also hit
    the docstring, which merely DESCRIBES the rule."""
    import ast
    from pathlib import Path
    tree = ast.parse(Path("apex/frontier2/curve_metrics.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imported.add(mod)
            imported.update(f"{mod}.{a.name}" for a in node.names)
    assert "apex.frontier2.curve" not in imported
    assert not any(m.endswith(".curve") or m == "curve" for m in imported)


# ---- DailyMarketMemory YESTERDAY_STATE law ---------------------------------

def test_memory_refuses_rule_shaped_fields():
    forbidden = [f for f in dmm.DailyMarketMemory.__dataclass_fields__
                 if any(s in f.lower() for s in dmm.FORBIDDEN_FIELD_SUBSTRINGS)]
    assert forbidden == []


def test_memory_positions_law_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(dmm, "LEDGER", tmp_path / "dmm.jsonl")
    with pytest.raises(dmm.DailyMarketMemoryError):
        dmm.DailyMarketMemory(
            session_date="2026-08-18", day_classification="x", regime={},
            leadership=(), laggards=(), breadth="", volatility="",
            important_transitions=(), persistent_relative_strength=(),
            persistent_weakness=(), failed_breakouts=(), failed_breakdowns=(),
            traps=(), late_day_changes=(), hunter_matches=(),
            fastwatch_observations={}, frontier2_limitations=(),
            data_fabric_limitations=(), options_limitations=(),
            system_blind_spots=(), important_unknowns=(),
            positions_carried_overnight="SOME_POSITIONS",
            sealed_at=str(T0), known_from=str(T0), content_hash="x")


def test_yesterday_state_is_labeled_never_current_truth(tmp_path, monkeypatch):
    monkeypatch.setattr(dmm, "LEDGER", tmp_path / "dmm.jsonl")
    dmm.seal(session_date="2026-08-18", known_from=T0, now=T0,
             day_classification="down day", regime={"SPY": -0.17},
             leadership=(), laggards=(), breadth="", volatility="",
             important_transitions=(), persistent_relative_strength=(),
             persistent_weakness=(), failed_breakouts=(), failed_breakdowns=(),
             traps=(), late_day_changes=(), hunter_matches=(),
             fastwatch_observations={}, frontier2_limitations=(),
             data_fabric_limitations=(), options_limitations=(),
             system_blind_spots=(), important_unknowns=())
    r = dmm.load_as_yesterday_state(before_session_date="2026-08-19")
    assert r["read_as"] == "YESTERDAY_STATE"
    assert r["not"] == "CURRENT_TRUTH"
    assert r["memory_session_date"] == "2026-08-18"


def test_same_day_memory_is_not_returned_as_yesterday_state(tmp_path, monkeypatch):
    """A memory for session D must never be handed back as
    YESTERDAY_STATE while trading session D."""
    monkeypatch.setattr(dmm, "LEDGER", tmp_path / "dmm.jsonl")
    dmm.seal(session_date="2026-08-18", known_from=T0, now=T0,
             day_classification="x", regime={}, leadership=(), laggards=(),
             breadth="", volatility="", important_transitions=(),
             persistent_relative_strength=(), persistent_weakness=(),
             failed_breakouts=(), failed_breakdowns=(), traps=(),
             late_day_changes=(), hunter_matches=(), fastwatch_observations={},
             frontier2_limitations=(), data_fabric_limitations=(),
             options_limitations=(), system_blind_spots=(),
             important_unknowns=())
    assert dmm.load_as_yesterday_state(before_session_date="2026-08-18") is None
