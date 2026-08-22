"""Phase 1.1 pre-tomorrow wiring: SessionAnchorEvidence, FastWatch->Hunter
attribution, the Hunter one-shot progress model, and Morning Prior
manifest registration at the real seal site.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from apex.hunter import fastwatch_attribution as fa
from apex.hunter import service_progress_hunter as sph
from apex.intraday import session_anchor_evidence as sae
from apex.memory import morning_prior_manifest as mpm

OPEN = pd.Timestamp("2026-08-19T13:30:00Z")
CLOSE = pd.Timestamp("2026-08-19T20:00:00Z")


def _ev(**over):
    kw = dict(symbol="SPY", session_date="2026-08-19", scheduled_open=OPEN,
              scheduled_close=CLOSE, now=OPEN, provider="ALPACA_WEBSOCKET_SIP_V1")
    kw.update(over)
    return sae.capture(**kw)


# ---- SessionAnchorEvidence -------------------------------------------------

def test_trade_at_the_open_is_live_valid():
    ev = _ev(first_regular_trade_time=OPEN)
    assert ev.opening_anchor_source == "LIVE_FIRST_REGULAR_TRADE"
    assert ev.opening_anchor_valid is True


def test_premarket_observation_counts_as_reaching_the_open():
    ev = _ev(first_regular_trade_time=OPEN - pd.Timedelta(minutes=40))
    assert ev.opening_anchor_valid is True


def test_late_first_observation_is_not_valid():
    ev = _ev(first_regular_trade_time=OPEN + pd.Timedelta(minutes=45))
    assert ev.opening_anchor_valid is False


def test_reconstruction_can_never_claim_live_validity():
    ev = _ev(first_regular_trade_time=OPEN, reconstructed_after_the_fact=True)
    assert ev.opening_anchor_source == "POST_CLOSE_RECONSTRUCTION"
    assert ev.opening_anchor_valid is False


def test_reconstructed_record_marked_valid_is_structurally_refused():
    with pytest.raises(sae.SessionAnchorEvidenceError):
        sae.SessionAnchorEvidence(
            symbol="SPY", session_date="2026-08-19", exchange_calendar="NYSE",
            scheduled_open=str(OPEN), scheduled_close=str(CLOSE),
            first_regular_trade_time=str(OPEN), first_regular_quote_time=None,
            first_completed_regular_bar=None,
            opening_anchor_source="POST_CLOSE_RECONSTRUCTION",
            opening_anchor_valid=True, opening_bar_open=None,
            opening_bar_high=None, opening_bar_low=None, opening_bar_close=None,
            opening_bar_volume=None, known_from=str(OPEN), as_of=str(OPEN),
            provider="X", transport_birth=None,
            reconstructed_after_the_fact=True)


def test_certify_refuses_silence_and_hindsight(tmp_path, monkeypatch):
    monkeypatch.setattr(sae, "LEDGER", tmp_path / "anchor.jsonl")
    sae.persist(_ev(symbol="SPY", first_regular_trade_time=OPEN))
    sae.persist(_ev(symbol="QQQ", first_regular_trade_time=OPEN,
                    reconstructed_after_the_fact=True))
    cert = sae.certify("2026-08-19", ("SPY", "QQQ", "IWM"),
                       tmp_path / "anchor.jsonl")
    assert cert["verdict"] == "SESSION_ANCHOR_UNPROVEN"
    assert cert["live_valid"] == ["SPY"]
    assert cert["reconstructed_only"] == ["QQQ"]
    assert cert["missing"] == ["IWM"]


def test_certify_proven_when_every_symbol_is_live_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(sae, "LEDGER", tmp_path / "anchor.jsonl")
    for s in ("SPY", "QQQ"):
        sae.persist(_ev(symbol=s, first_regular_trade_time=OPEN))
    cert = sae.certify("2026-08-19", ("SPY", "QQQ"), tmp_path / "anchor.jsonl")
    assert cert["verdict"] == "SESSION_ANCHOR_PROVEN_LIVE"


def test_a_genuinely_late_symbol_fails_the_session(tmp_path, monkeypatch):
    monkeypatch.setattr(sae, "LEDGER", tmp_path / "anchor.jsonl")
    sae.persist(_ev(symbol="SPY", first_regular_trade_time=OPEN))
    sae.persist(_ev(symbol="QQQ",
                    first_regular_trade_time=OPEN + pd.Timedelta(minutes=45)))
    cert = sae.certify("2026-08-19", ("SPY", "QQQ"), tmp_path / "anchor.jsonl")
    assert cert["verdict"] == "SESSION_ANCHOR_INVALID"


# ---- FastWatch attribution -------------------------------------------------

def _write(p, rows):
    p.write_text("\n".join(json.dumps(r) for r in rows))


def test_attribution_is_strictly_forward_in_time(tmp_path):
    fw = tmp_path / "fw.jsonl"
    fl = tmp_path / "fl.jsonl"
    _write(fw, [{"symbol": "HD", "observed_at": "2026-08-19T15:00:00+00:00",
                 "fastwatch_condition_observed": ["VWAP_RECLAIM_SHAPE"]}])
    # Hunter saw HD BEFORE the FastWatch event -> not attributable
    _write(fl, [{"kind": "scan", "t_utc": "2026-08-19T14:00:00+00:00",
                 "watchlist": [{"symbol": "HD"}]}])
    recs = fa.build(session_date="2026-08-19", fastwatch_ledger=fw,
                    forward_ledger=fl, known_from=OPEN)
    assert recs[0].eventual_match == "NO_LATER_HUNTER_WATCHLIST"
    assert recs[0].lead_minutes is None


def test_attribution_measures_real_lead(tmp_path):
    fw = tmp_path / "fw.jsonl"
    fl = tmp_path / "fl.jsonl"
    _write(fw, [{"symbol": "HD", "observed_at": "2026-08-19T14:00:00+00:00",
                 "fastwatch_condition_observed": ["VWAP_RECLAIM_SHAPE"]}])
    _write(fl, [{"kind": "scan", "t_utc": "2026-08-19T14:30:00+00:00",
                 "watchlist": [{"symbol": "HD"}]},
                {"kind": "decision", "t_utc": "2026-08-19T15:00:00+00:00",
                 "symbol": "HD", "playbook_id": "HUNTER-001_v1",
                 "decision_id": "abc"}])
    recs = fa.build(session_date="2026-08-19", fastwatch_ledger=fw,
                    forward_ledger=fl, known_from=OPEN)
    assert recs[0].eventual_match == "MATCHED"
    assert recs[0].lead_minutes == pytest.approx(60.0)
    assert recs[0].outcome_ref == "abc"


def test_baseline_playbooks_are_never_counted_as_matches(tmp_path):
    fw = tmp_path / "fw.jsonl"
    fl = tmp_path / "fl.jsonl"
    _write(fw, [{"symbol": "HD", "observed_at": "2026-08-19T14:00:00+00:00",
                 "fastwatch_condition_observed": ["SESSION_HIGH_TOUCH"]}])
    _write(fl, [{"kind": "decision", "t_utc": "2026-08-19T15:00:00+00:00",
                 "symbol": "HD", "playbook_id": "BASELINE-MARKET",
                 "decision_id": "x"}])
    recs = fa.build(session_date="2026-08-19", fastwatch_ledger=fw,
                    forward_ledger=fl, known_from=OPEN)
    assert recs[0].eventual_match == "NO_LATER_HUNTER_WATCHLIST"


def test_matched_requires_a_match_time():
    with pytest.raises(fa.FastWatchAttributionError):
        fa.FastWatchAttribution(
            fastwatch_event_id="x", symbol="HD", condition="c",
            fastwatch_event_time=str(OPEN), hunter_first_watchlist_time=None,
            hunter_match_time=None, eventual_playbook=None, lead_minutes=None,
            eventual_match="MATCHED", outcome_ref=None,
            session_date="2026-08-19", known_from=str(OPEN))


def test_fastwatch_has_no_authority():
    """Checked against real CODE (AST function/attribute names), not raw
    source text -- the module's own docstring says it "cannot promote a
    FastWatch event", and a substring scan flags that disclaimer as if
    it were the offence."""
    import ast
    from pathlib import Path
    tree = ast.parse(Path("apex/hunter/fastwatch_attribution.py").read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            names.add(node.name.lower())
        elif isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, ast.Name):
            names.add(node.id.lower())
    for w in ("place_order", "submit_order", "promote", "size_position"):
        assert not any(w in n for n in names), f"{w!r} appears in real code"


# ---- Hunter one-shot progress model ----------------------------------------

def test_cycle_advances_across_process_boundaries(tmp_path):
    p = tmp_path / "hp.json"
    for expected in (1, 2, 3):
        s = sph.load_or_advance(path=p)
        assert s.cycle_number == expected
        sph.mark_success(s)
        sph.write(s, p)


def test_dead_pid_between_ticks_is_not_stopped(tmp_path):
    """THE ONE-SHOT LAW. hunter_forward_clock exits after each tick;
    between ticks no process exists. A daemon-shaped watchdog would
    report STOPPED on a perfectly healthy Hunter every time."""
    p = tmp_path / "hp.json"
    s = sph.load_or_advance(path=p)
    sph.mark_success(s)
    s.pid = 999999                      # a pid that is certainly not alive
    sph.write(s, p)
    r = sph.watchdog_check(p)
    assert r["pid_alive"] is False
    assert r["watchdog_status"] == "HEALTHY"
    assert r["pid_liveness_is_informational_only"] is True


def test_missed_scheduled_runs_go_stalled(tmp_path):
    p = tmp_path / "hp.json"
    s = sph.load_or_advance(path=p, expected_cadence_s=900.0)
    sph.mark_success(s)
    s.last_successful_cycle = str(pd.Timestamp.now(tz="UTC")
                                  - pd.Timedelta(seconds=4000))
    sph.write(s, p)
    assert sph.watchdog_check(p)["watchdog_status"] == "STALLED"


def test_runtime_model_is_declared():
    assert sph.RUNTIME_MODEL == "RECURRING_ONESHOT"
    assert sph.DEFAULT_CADENCE_S == 900.0


# ---- Morning Prior manifest wiring -----------------------------------------

def test_manifest_entry_carries_runtime_version(tmp_path, monkeypatch):
    monkeypatch.setattr(mpm, "LEDGER", tmp_path / "mp.jsonl")
    art = tmp_path / "prior.json"
    art.write_text("{}")
    e = mpm.register(session_date="2026-08-19", canonical_path=art,
                     source_health={}, known_from=OPEN, now=OPEN,
                     runtime_version="premarket_seal_v1")
    assert e.runtime_version == "premarket_seal_v1"
    assert mpm.locate("2026-08-19")["runtime_version"] == "premarket_seal_v1"


def test_premarket_seal_registers_into_the_manifest():
    """The real seal site must call register() -- a manifest nothing
    writes to is exactly the 2026-08-18 failure."""
    src = __import__("pathlib").Path("apex/frontier/premarket.py").read_text()
    assert "morning_prior_manifest" in src
    assert "_mpm.register(" in src
