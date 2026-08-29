"""Equity Shadow Field commissioning — frozen-logic proof, capital
blindness, prospective counterfactuals, canonical-universe pin.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import scripts.equity_field_session as F
import scripts.equity_shadow_session as CANON
from apex.predators.equities import day_trader


# ==================================================== FROZEN LOGIC

def test_field_defines_no_thresholds_of_its_own():
    """The field is instrumentation around the incumbent hunter. A
    threshold defined here would be a second trader wearing a lab
    coat."""
    src = Path(F.__file__).read_text()
    tree = ast.parse(src)
    banned_fragments = ("MIN_MEDIAN", "THRESHOLD", "SPREAD_BPS",
                        "RISK_BUDGET", "ATR_", "CHASE_", "_FLOOR")
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                name = getattr(t, "id", "")
                assert not any(b in name for b in banned_fragments), \
                    f"field defines threshold-like constant {name}"
    assert "day_trader.decide(" in src, "field must call the frozen " \
                                        "hunter"


def test_field_cadence_is_the_incumbent_cadence():
    assert F.SCAN_INTERVAL_S == CANON.SCAN_INTERVAL_S


# ================================================ CAPITAL BLINDNESS

def test_field_has_no_capital_surface():
    """No arena, no book, no allocator, no organism outbox: a field
    candidate is evidence, never a funding request."""
    src = Path(F.__file__).read_text()
    assert "outbox_emit" not in src
    for n in ast.walk(ast.parse(src)):
        mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                else [n.module or ""] if isinstance(n, ast.ImportFrom)
                else [])
        for m in mods:
            for banned in ("organism.allocator", "organism.book",
                           "capital.arena", "organism.risk_kernel"):
                assert banned not in m, f"field imports {banned}"


def test_field_writes_only_under_its_own_root():
    for p in (F.UNIVERSE_FILE, F.LEDGER, F.OUTCOMES):
        assert str(p).startswith("results/equities/field"), p


# ============================================ CANONICAL UNIVERSE PIN

def test_new_bar_files_cannot_widen_the_canonical_trader(tmp_path,
                                                         monkeypatch):
    """The sensor now captures ~60 names for the FIELD. The canonical
    trader's universe must not widen because a bar file appeared --
    that would be a quiet symbol add, forbidden by the sealed
    universe-expansion law."""
    bars = [{"event_time_utc": f"2026-08-28T{14 + m // 60:02d}"
             f":{m % 60:02d}:00.000Z", "open": 100, "high": 100.1,
             "low": 99.9, "close": 100, "volume": 50_000}
            for m in range(1, 200)]
    for sym in ("SPY", "AVGO", "GOOGL"):       # AVGO/GOOGL = field-only
        (tmp_path / f"{sym}_2026-08-28.json").write_text(
            json.dumps({"bars": bars}))
    monkeypatch.setattr(CANON, "BARS_ROOT", tmp_path)
    uni = CANON.eligible_universe("2026-08-28")
    assert "SPY" in uni["eligible"]
    assert "AVGO" not in uni["eligible"] + uni["thin"] + uni["missing"]
    assert "GOOGL" not in uni["eligible"] + uni["thin"] + uni["missing"]


def test_canonical_pin_matches_the_current_capture_set():
    assert len(CANON.EQUITY_UNIVERSE_V1) == 17
    for s in ("AAPL", "MSFT", "NVDA", "SPY", "QQQ", "IWM"):
        assert s in CANON.EQUITY_UNIVERSE_V1


# ======================================== PROSPECTIVE COUNTERFACTUAL

def _refusal(dist=1.2, close=100.0, atr=0.5, direction="LONG"):
    return {"decision": "CHASE_REFUSED", "decision_id": "EQF_x",
            "symbol": "GOOGL", "session": "2026-08-28",
            "known_from": "2026-08-28T14:30:00Z",
            "direction": direction, "setup_type": "RANGE_BREAK_LONG",
            "invalidation_distance_atr": dist,
            "market_state": {"close": close, "atr": atr}}


def test_counterfactual_uses_the_frozen_sizer_exactly():
    cf = F.counterfactual_expression(_refusal())
    assert cf is not None and cf["sealed_prospectively"] is True
    # reproduce with the frozen functions directly -- byte-equal math
    fill = day_trader.marketable_fill(100.0, "LONG")
    sized = day_trader.size_shadow(entry=fill["fill"],
                                   stop=100.0 - 1.2 * 0.5,
                                   direction="LONG")
    assert cf["quantity"] == sized["quantity"]
    assert cf["declared_1R"] == sized["declared_1R"]
    assert cf["basis"] == "FROZEN_SIZER_ON_SEALED_GEOMETRY"


def test_unmeasurable_geometry_is_not_estimable_not_invented():
    assert F.counterfactual_expression(_refusal(dist=None)) is None
    assert F.counterfactual_expression(_refusal(dist=0.0)) is None
    r = _refusal()
    r["market_state"] = {}
    assert F.counterfactual_expression(r) is None


# ================================================ HONEST RESOLUTION

def test_counterfactual_outcome_is_retagged_with_the_truth(tmp_path,
                                                           monkeypatch):
    rec = _refusal()
    rec["kind"] = "equity_field_decision"
    rec["counterfactual_expression"] = F.counterfactual_expression(rec)
    rec["sector"] = "COMMUNICATION"
    led = tmp_path / "d.jsonl"
    outp = tmp_path / "o.jsonl"
    led.write_text(json.dumps(rec) + "\n")

    bars = [{"event_time_utc": f"2026-08-28T{14 + m // 60:02d}"
             f":{m % 60:02d}:00.000Z", "open": 100 + m * 0.05,
             "high": 100.1 + m * 0.05, "low": 99.9 + m * 0.05,
             "close": 100 + m * 0.05, "volume": 9}
            for m in range(31, 120)]
    monkeypatch.setattr(F, "load_bars", lambda s, sess: bars)
    monkeypatch.setattr(F, "session_bounds", lambda s: {
        "trading_day": True,
        "close_utc": __import__("datetime").datetime(
            2026, 8, 28, 20, 0,
            tzinfo=__import__("datetime").timezone.utc)})
    r = F.resolve_field("2026-08-28",
                        roots={"ledger": led, "outcomes": outp})
    assert r["resolved"] == 1
    o = json.loads(outp.read_text().splitlines()[0])
    assert o["kind"] == "equity_field_outcome"
    assert o["original_decision"] == "CHASE_REFUSED"
    assert o["counterfactual"] is True
    assert o["decision_power"] == "PREDATOR_EVIDENCE_ONLY"
    # idempotent on rerun
    r2 = F.resolve_field("2026-08-28",
                         roots={"ledger": led, "outcomes": outp})
    assert r2["resolved"] == 0


# ===================================================== UNIVERSE SEAL

def test_universe_is_rules_based_and_sector_diverse():
    syms = F.field_symbols()
    assert len(syms) >= 40
    assert len(F.FIELD_UNIVERSE_V1) == 11          # every GICS sector
    assert "AAPL" in syms and "XOM" in syms and "NEE" in syms


def test_report_never_claims_independence(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "OUTCOMES", tmp_path / "o.jsonl")
    rep = F.report()
    assert rep["independent_episodes"] == "NOT_ESTIMABLE"
    assert "never pooled" in rep["law"]
