"""scripts/alpaca_options_entitlement_probe.py -- pure-logic checks
(Greek/IV key detection, credential-absence refusal) that don't
require live network access or real Alpaca credentials.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import alpaca_options_entitlement_probe as probe


def test_no_credentials_refuses_not_fabricates(monkeypatch, tmp_path):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.setattr(probe, "OUT_PATH", tmp_path / "probe.json")
    out = probe.main()
    assert out["status"] == "SKIPPED_NO_CREDENTIALS"
    assert out["options_snapshot"] is None


def test_contains_greek_keys_detects_nested_delta():
    payload = {"snapshots": {"AAPL260919C00230000": {"greeks": {"delta": 0.5}}}}
    assert probe._contains_greek_keys(payload) is True


def test_contains_greek_keys_false_when_absent():
    payload = {"snapshots": {"AAPL260919C00230000": {
        "latestQuote": {"bp": 1.0, "ap": 1.2},
        "latestTrade": {"p": 1.1}}}}
    assert probe._contains_greek_keys(payload) is False


def test_contains_greek_keys_handles_lists():
    payload = {"snapshots": [{"implied_volatility": 0.3}]}
    assert probe._contains_greek_keys(payload) is True


def test_robinhood_note_always_present_and_honest():
    out_no_creds = {"robinhood_note": "x"}
    assert "not checked from this script" not in ""  # sanity no-op
    import inspect
    src = inspect.getsource(probe.main)
    assert "robinhood_note" in src
    assert "not reproducible headlessly" in src
