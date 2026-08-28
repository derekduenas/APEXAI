"""EQUITY SHADOW COMMISSIONING — the second sleeve, zero authority.

The tests that matter most prove it cannot touch Options, cannot place
an order, and cannot promote itself.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from apex.predators.equities import day_trader as DT
from apex.predators.equities import shadow_resolution as SR


def bars(closes, *, start_h=13, start_m=30, high_pad=0.05,
         low_pad=0.05, vol=50_000):
    out = []
    for i, c in enumerate(closes):
        m = start_m + i
        out.append({
            "event_time_utc":
                f"2026-08-27T{start_h + m // 60:02d}:{m % 60:02d}:00.000Z",
            "open": c, "high": c + high_pad, "low": c - low_pad,
            "close": c, "volume": vol})
    return out


def flat(n=40, px=100.0):
    return bars([px + (i % 2) * 0.01 for i in range(n)])


# ============================================================ AUTHORITY

def test_the_sleeve_declares_shadow_only():
    assert DT.AUTHORITY == "SHADOW_ONLY"
    assert SR.resolve.__module__.startswith("apex.predators.equities")


def test_no_order_surface_exists_anywhere_in_the_sleeve():
    """No function that could ever place, route or authorize anything."""
    banned = {"place_order", "submit_order", "send_order", "route_order",
              "buy", "sell", "execute", "authorize", "promote"}
    for f in (Path(DT.__file__), Path(SR.__file__),
              Path("scripts/equity_shadow_session.py")):
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert n.name not in banned, f"{f.name} defines {n.name}"
            if isinstance(n, ast.Call):
                fn = n.func
                name = (fn.id if isinstance(fn, ast.Name)
                        else fn.attr if isinstance(fn, ast.Attribute)
                        else None)
                assert name not in banned, f"{f.name} calls {name}"


def test_equity_never_imports_or_mutates_options():
    """The sleeves share market data, never decisions."""
    for f in (Path(DT.__file__), Path(SR.__file__),
              Path("scripts/equity_shadow_session.py")):
        for n in ast.walk(ast.parse(f.read_text())):
            mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                    else [n.module or ""] if isinstance(n, ast.ImportFrom)
                    else [])
            for m in mods:
                assert "predators.options" not in m, \
                    f"{f.name} imports Options: {m}"
                assert "capital" not in m, f"{f.name} reaches Capital"


def test_options_does_not_import_equity_day_trader():
    """And the coupling must not exist in the other direction either."""
    for p in list(Path("apex/predators/options").rglob("*.py")) + [
            Path("scripts/options_paper_session.py")]:
        for n in ast.walk(ast.parse(p.read_text())):
            mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                    else [n.module or ""] if isinstance(n, ast.ImportFrom)
                    else [])
            assert not any("day_trader" in m or "shadow_resolution" in m
                           for m in mods), f"{p} couples to Equity"


# =========================================================== TWO-SIDED

def test_the_sleeve_is_structurally_two_sided():
    longs = [s for s in DT.SETUP_TYPES if s.startswith("LONG")]
    shorts = [s for s in DT.SETUP_TYPES if s.startswith("SHORT")]
    assert len(longs) == len(shorts) == 2, "hidden directional bias"


@pytest.mark.parametrize("closes,direction,expect", [
    ([100 + i * 0.02 for i in range(30)] + [100.9], "LONG",
     "LONG_BREAKOUT"),
    ([100 - i * 0.02 for i in range(30)] + [99.1], "SHORT",
     "SHORT_BREAKDOWN"),
])
def test_breakout_and_breakdown_are_named(closes, direction, expect):
    got = DT.classify_setup(bars(closes), direction=direction)
    assert got["setup_type"] == expect


def test_failed_breaks_are_named_from_the_wick_not_the_close():
    b = bars([100.0] * 34)
    b[-1] = {**b[-1], "low": 99.0, "close": 100.0}     # poked and held
    assert DT.classify_setup(b, direction="LONG")["setup_type"] == \
        "LONG_FAILED_BREAKDOWN"
    b2 = bars([100.0] * 34)
    b2[-1] = {**b2[-1], "high": 101.0, "close": 100.0}
    assert DT.classify_setup(b2, direction="SHORT")["setup_type"] == \
        "SHORT_FAILED_BREAKOUT"


def test_an_unnameable_tape_yields_no_setup():
    assert DT.classify_setup(flat(), direction="LONG")["setup_type"] is None


# =============================================================== RISK

def test_a_stop_on_the_wrong_side_is_refused():
    r = DT.size_shadow(entry=100.0, stop=101.0, direction="LONG")
    assert r["valid"] is False
    assert "no structural invalidation" in r["why"]


def test_risk_per_share_larger_than_the_budget_is_refused():
    r = DT.size_shadow(entry=100.0, stop=0.5, direction="LONG",
                       budget=10.0)
    assert r["valid"] is False


def test_size_follows_the_stop_never_the_reverse():
    r = DT.size_shadow(entry=100.0, stop=98.0, direction="LONG",
                       budget=300.0)
    assert r["risk_per_share"] == 2.0
    assert r["quantity"] == 150
    assert r["declared_1R"] == 300.0


def test_execution_crosses_the_spread_in_both_directions():
    lo = DT.marketable_fill(100.0, "LONG")
    sh = DT.marketable_fill(100.0, "SHORT")
    assert lo["fill"] > 100.0, "a long filled at or below reference"
    assert sh["fill"] < 100.0, "a short filled at or above reference"
    assert lo["friction_per_share"] > 0
    assert "modelled, not observed" in lo["law"]


# =========================================================== DECISIONS

def _decide(b, **kw):
    return DT.decide(symbol="SPY", session="2026-08-27", bars=b,
                     now=b[-1]["event_time_utc"],
                     known_from=b[-1]["event_time_utc"], **kw)


def test_a_thin_symbol_is_refused_before_anything_else():
    d = _decide(flat(), median_volume=100)
    assert d.decision == "NO_TRADE"
    assert "below the predeclared floor" in d.reasons[0]


def test_insufficient_bars_is_not_a_thesis():
    assert _decide(bars([100.0] * 5)).decision == "INSUFFICIENT_DATA"


def test_price_at_the_anchor_produces_no_thesis():
    d = _decide(flat())
    assert d.decision == "NO_THESIS"
    assert d.direction is None


def test_refusals_are_first_class_states():
    for r in ("WAIT", "NO_THESIS", "GEOMETRY_REFUSED", "CHASE_REFUSED",
              "NO_VALID_STOP", "NO_TRADE"):
        assert r in DT.DECISIONS


def test_an_extended_tape_is_refused_for_chase():
    d = _decide(bars([100 + i * 0.5 for i in range(40)]))
    assert d.decision in ("CHASE_REFUSED", "GEOMETRY_REFUSED")
    assert d.direction == "LONG"


def test_a_sealed_attack_must_carry_stop_setup_and_1R():
    from apex.predators.equities.day_trader import (
        EquityShadowDecision, EquityShadowViolation)
    with pytest.raises(EquityShadowViolation, match="not a decision"):
        EquityShadowDecision(
            decision_id="x", symbol="SPY", session="s",
            decision="ATTACK_READY_SHADOW", event_time="t",
            known_from="t", direction="LONG")


def test_an_unknown_decision_state_is_refused():
    from apex.predators.equities.day_trader import (
        EquityShadowDecision, EquityShadowViolation)
    with pytest.raises(EquityShadowViolation, match="unknown decision"):
        EquityShadowDecision(decision_id="x", symbol="S", session="s",
                             decision="YOLO", event_time="t",
                             known_from="t")


def test_every_decision_is_sealed_prospective_and_shadow():
    rec = _decide(flat()).as_record()
    assert rec["prospective"] is True
    assert rec["authority"] == "SHADOW_ONLY"
    assert rec["decision_power"] == "SHADOW_ONLY"
    assert rec["threshold_set"] == "EQUITY_SHADOW_V1"
    for banned in ("order_id", "broker", "account", "live"):
        assert banned not in rec


# ========================================================= RESOLUTION

def _attack():
    b = bars([100.0] * 30 + [100.0, 100.05, 100.1, 100.02, 100.3])
    d = _decide(b)
    return d, b


def test_only_sealed_attacks_resolve():
    d = _decide(flat())
    out = SR.resolve(decision=d.as_record(), bars=flat(),
                     close_utc="2026-08-27T20:00:00Z")
    assert out["resolvable"] is False


def test_an_unmatured_horizon_is_not_estimable_never_zero():
    dec = {"decision": "ATTACK_READY_SHADOW", "decision_id": "d",
           "symbol": "SPY", "known_from": "2026-08-27T19:55:00Z",
           "direction": "LONG", "entry_fill": 100.0, "stop": 99.0,
           "quantity": 10, "declared_1R": 100.0,
           "friction_per_share": 0.01}
    fut = bars([100.0, 100.2], start_h=19, start_m=56)
    out = SR.resolve(decision=dec, bars=fut,
                     close_utc="2026-08-27T20:00:00Z")
    assert out["signed_horizons"]["30m"] == "NOT_ESTIMABLE_BEYOND_CLOSE"
    assert out["signed_horizons"]["60m"] == "NOT_ESTIMABLE_BEYOND_CLOSE"


def test_the_structural_stop_resolves_before_the_close():
    dec = {"decision": "ATTACK_READY_SHADOW", "decision_id": "d",
           "symbol": "SPY", "known_from": "2026-08-27T13:30:00Z",
           "direction": "LONG", "entry_fill": 100.0, "stop": 99.0,
           "quantity": 10, "declared_1R": 100.0,
           "friction_per_share": 0.01}
    fut = bars([100.0, 99.5, 98.5, 101.0], start_m=31)
    out = SR.resolve(decision=dec, bars=fut,
                     close_utc="2026-08-27T20:00:00Z")
    assert out["exit_reason"] == "STRUCTURAL_STOP"
    assert out["executable_pnl"] < 0
    assert out["R"] < 0


def test_friction_is_charged_on_both_sides():
    dec = {"decision": "ATTACK_READY_SHADOW", "decision_id": "d",
           "symbol": "SPY", "known_from": "2026-08-27T13:30:00Z",
           "direction": "LONG", "entry_fill": 100.0, "stop": 90.0,
           "quantity": 10, "declared_1R": 100.0,
           "friction_per_share": 0.02}
    out = SR.resolve(decision=dec, bars=bars([100.0, 100.0], start_m=31),
                     close_utc="2026-08-27T20:00:00Z")
    assert out["friction"] == pytest.approx(0.4)     # 0.02 * 10 * 2


def test_the_exit_rule_is_predeclared_not_chosen_per_trade():
    assert "pre-declared" in SR.EXIT_RULE
    assert SR.HORIZONS_MIN == (15, 30, 60)


# ======================================================== UNIVERSE

def test_the_liquidity_floor_is_predeclared(tmp_path, monkeypatch):
    import scripts.equity_shadow_session as S
    root = tmp_path / "bars"
    root.mkdir()
    for sym, vol in (("SPY", 90_000), ("THIN", 100)):
        (root / f"{sym}_2026-08-27.json").write_text(json.dumps(
            {"bars": bars([100.0] * 40, vol=vol)}))
    monkeypatch.setattr(S, "BARS_ROOT", root)
    uni = S.eligible_universe("2026-08-27")
    assert uni["eligible"] == ["SPY"]
    assert uni["thin"] == ["THIN"]
    assert uni["floor_shares_per_min"] == 20_000


def test_liquidity_is_measured_over_rth_not_the_whole_file(tmp_path,
                                                           monkeypatch):
    """Caught by running it: measuring the median across the whole file
    drags in overnight hours at ~zero volume, and the floor then
    rejected SPY -- the most liquid instrument on the tape."""
    import scripts.equity_shadow_session as S
    root = tmp_path / "bars"
    root.mkdir()
    rth = bars([100.0] * 40, start_h=13, start_m=30, vol=90_000)
    overnight = bars([100.0] * 300, start_h=1, start_m=0, vol=10)
    (root / "SPY_2026-08-27.json").write_text(
        json.dumps({"bars": overnight + rth}))
    monkeypatch.setattr(S, "BARS_ROOT", root)
    uni = S.eligible_universe("2026-08-27")
    assert uni["eligible"] == ["SPY"], \
        "overnight dead hours vetoed the most liquid symbol on the tape"
