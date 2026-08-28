"""PARALLAX commissioning — the firewall, the denominator, the fences.

The tests that matter most prove what it CANNOT do: create an
expectation after the fact, influence any trading component, or turn a
violation into a score.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from apex.organism import parallax as PX


def ev(de="POSITIVE", sym="NVDA", ekf="2026-08-28T14:00:00Z"):
    return {"event_id": "E1", "event_type": "EARNINGS",
            "event_time": "2026-08-28T13:55:00Z",
            "known_from": "2026-08-28T14:00:00Z",
            "directional_expectation": de,
            "expectation_known_from": ekf,
            "expectation_contract_sha": "abc",
            "affected_symbols": [sym], "importance": "HIGH",
            "mechanism_hypotheses": ["strong results drive demand"],
            "uncertainty": ["guidance unclear"]}


def bars(closes, *, start_m=1):
    out = []
    for i, c in enumerate(closes):
        m = start_m + i
        out.append({"event_time_utc":
                    f"2026-08-28T{14 + m // 60:02d}:{m % 60:02d}"
                    f":00.000Z",
                    "open": c, "high": c + 0.1, "low": c - 0.1,
                    "close": c, "volume": 9})
    return out


CLOSE = "2026-08-28T20:00:00Z"


# ========================================================== AUTHORITY

def test_the_authority_is_shadow_observatory_and_nothing_stronger():
    assert PX.AUTHORITY == "PARALLAX_SHADOW_OBSERVATORY"


def test_no_trading_surface_no_score_no_threshold():
    src = Path(PX.__file__).read_text()
    for banned in ("PARALLAX_SCORE", "buy", "sell", "place_order",
                   "fund(", "allocate(", "confidence_score"):
        assert banned not in src, f"parallax contains {banned}"
    tree = ast.parse(src)
    for n in ast.walk(tree):
        mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                else [n.module or ""] if isinstance(n, ast.ImportFrom)
                else [])
        for m in mods:
            assert "predators" not in m, f"parallax imports sleeve {m}"
            assert "allocator" not in m and "book" not in m, \
                f"parallax reaches capital: {m}"


def test_nothing_in_the_organism_consumes_parallax():
    """CAPITAL ARENA MUST NOT SEE IT; neither may any sleeve."""
    for mod in list(Path("apex/predators").rglob("*.py")) + [
            Path("apex/organism/allocator.py"),
            Path("apex/organism/book.py"),
            Path("apex/capital/arena.py"),
            Path("scripts/options_paper_session.py"),
            Path("scripts/equity_shadow_session.py")]:
        for n in ast.walk(ast.parse(mod.read_text())):
            mods = ([a.name for a in n.names]
                    if isinstance(n, ast.Import)
                    else [n.module or ""]
                    if isinstance(n, ast.ImportFrom) else [])
            assert not any("parallax" in m for m in mods), \
                f"{mod} consumes PARALLAX"


# ================================================ HINDSIGHT FIREWALL

def test_no_expectation_means_not_parallax_eligible():
    assert PX.expectation_from_event(ev(de="UNKNOWN")) is None
    e = ev()
    e["expectation_known_from"] = "NONE"
    assert PX.expectation_from_event(e) is None


def test_an_expectation_formed_mid_reaction_is_refused(tmp_path):
    exp = PX.expectation_from_event(ev())
    exp["expectation_created_at"] = "2026-08-28T15:00:00Z"  # after kf
    with pytest.raises(PX.ParallaxViolation, match="hindsight"):
        PX.measure_violation(exp, bars_by_symbol={"NVDA": bars(
            [100] * 10)}, close_utc=CLOSE, atr=1.0,
            ledger=tmp_path / "v.jsonl")


def test_a_huge_move_without_a_sealed_expectation_is_simply_absent():
    """Not success, not failure -- absent from the record entirely."""
    assert PX.expectation_from_event(
        {"event_id": "x", "affected_symbols": ["NVDA"],
         "directional_expectation": "UNKNOWN"}) is None


# ================================================= VIOLATION CLASSES

def _measure(de, closes, tmp_path, sym="NVDA", extra=None):
    exp = PX.expectation_from_event(ev(de=de, sym=sym))
    b = {sym: bars(closes)}
    if extra:
        b.update(extra)
    return PX.measure_violation(exp, bars_by_symbol=b, close_utc=CLOSE,
                                atr=1.0, ledger=tmp_path / "v.jsonl")


def test_positive_expectation_positive_reaction(tmp_path):
    v = _measure("POSITIVE", [100 + i * 0.2 for i in range(30)],
                 tmp_path)
    assert v["violation_class"] == "EXPECTED_REACTION"
    assert v["informational_vs_expressible"] == "NOT_A_VIOLATION"


def test_positive_expectation_failure(tmp_path):
    v = _measure("POSITIVE", [100 - i * 0.2 for i in range(30)],
                 tmp_path)
    assert v["violation_class"] == "FAILED_POSITIVE_REACTION"
    assert v["expectation_debt"] in ("MODERATE", "HIGH", "EXTREME")


def test_negative_expectation_failure(tmp_path):
    v = _measure("NEGATIVE", [100 + i * 0.2 for i in range(30)],
                 tmp_path)
    assert v["violation_class"] == "FAILED_NEGATIVE_REACTION"


def test_flat_tape_is_no_identifiable_reaction_low_debt(tmp_path):
    v = _measure("POSITIVE", [100 + (i % 2) * 0.01 for i in range(30)],
                 tmp_path)
    assert v["violation_class"] == "NO_IDENTIFIABLE_REACTION"
    assert v["expectation_debt"] in ("NONE", "LOW", "MODERATE")


def test_relative_dislocation_when_the_index_confirms_but_symbol_fails(
        tmp_path):
    """NVDA weak while SPY rallies on a positive expectation."""
    v = _measure("POSITIVE",
                 [100 - i * 0.05 for i in range(30)], tmp_path,
                 extra={"SPY": bars([500 + i * 1.0 for i in range(30)]),
                        "XLK": bars([200] * 30)})
    assert v["relative"]["INDEX"] == "NEGATIVE_RELATIVE_DISLOCATION"
    assert v["violation_class"] in ("RELATIVE_DISLOCATION",
                                    "FAILED_POSITIVE_REACTION")


def test_atr_not_estimable_is_ineligible_not_a_crash(tmp_path):
    exp = PX.expectation_from_event(ev())
    v = PX.measure_violation(exp, bars_by_symbol={"NVDA": bars(
        [100] * 10)}, close_utc=CLOSE, atr="NOT_ESTIMABLE",
        ledger=tmp_path / "v.jsonl")
    assert v["eligible"] is False


# ==================================================== RESOLUTION

def test_resolution_classes_from_later_path_only():
    v = {"violation_class": "FAILED_POSITIVE_REACTION",
         "expected_direction": "POSITIVE", "parallax_id": "p",
         "episode_id": "e"}
    up = PX.resolve_debt(v, later_signed_return=0.02, atr=1.0,
                         price0=100.0)
    dn = PX.resolve_debt(v, later_signed_return=-0.02, atr=1.0,
                         price0=100.0)
    flat = PX.resolve_debt(v, later_signed_return=0.0001, atr=1.0,
                           price0=100.0)
    assert up["resolution_class"] == "PRICE_CATCHES_UP"
    assert dn["resolution_class"] == "EXPECTATION_PROVEN_WRONG"
    assert flat["resolution_class"] == "DISLOCATION_PERSISTS"
    none = PX.resolve_debt(v, later_signed_return=None, atr=1.0,
                           price0=100.0)
    assert none["resolution_class"] == "UNKNOWN"


# =============================================== EPISODE ACCOUNTING

def test_horizons_of_one_event_are_one_episode():
    vs = [{"eligible": True, "episode_id": "E1", "symbol": "NVDA",
           "measured_utc": "2026-08-28T15:00"} for _ in range(4)]
    a = PX.episode_accounting(vs)
    assert a["raw_observations"] == 4
    assert a["episodes"] == 1


def test_a_same_family_cluster_is_correlated_not_independent():
    vs = [{"eligible": True, "episode_id": f"E{i}", "symbol": s,
           "measured_utc": "2026-08-28T15:00"}
          for i, s in enumerate(("NVDA", "AAPL", "MSFT"))]
    a = PX.episode_accounting(vs)
    assert a["episodes"] == 3
    assert a["correlated_clusters"] == 1
    assert a["independent_episode_estimate"] == 1


# ================================================== SESSION PASS

def test_observe_session_seals_the_full_denominator(tmp_path):
    events = [ev(),                                   # eligible
              ev(de="UNKNOWN"),                       # no expectation
              {**ev(), "affected_symbols": ["ZZZZ"]}]  # off-universe
    rep = PX.observe_session(
        session="2026-08-28", close_utc=CLOSE, events=events,
        load_bars=lambda s: bars([100 + i * 0.2 for i in range(30)]),
        atr_fn=lambda b: 1.0,
        expectations_ledger=tmp_path / "e.jsonl",
        violations_ledger=tmp_path / "v.jsonl")
    d = rep["denominator"]
    assert d["events_considered"] == 3
    assert d["eligible"] == 1 and d["measured"] == 1
    assert d["ineligible"]["NO_PRE_REACTION_EXPECTATION"] == 1
    assert d["ineligible"]["NO_UNIVERSE_SYMBOL"] == 1
    assert rep["parallax_edge"] == "NOT_ESTIMABLE"
    assert rep["label"] == "PROSPECTIVE"


def test_a_parallax_failure_never_breaks_the_catalyst_seal(
        monkeypatch):
    """The observatory is downstream furniture: if it dies, the seal
    still stands."""
    import scripts.catalyst_service as cs
    monkeypatch.setattr(cs, "run_cycle",
                        lambda **k: {"sources_succeeded": 0,
                                     "sources_checked": 0,
                                     "sources_failed": 0,
                                     "new_observations": 0,
                                     "new_events": 0})
    monkeypatch.setattr(cs, "attach_reactions", lambda **k: {"n": 0})
    monkeypatch.setattr(cs, "eligible_events", lambda **k: [])
    monkeypatch.setattr(
        cs, "_parallax_pass",
        lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    rec = cs.do_cycle("POST_CLOSE_SEAL", session="2026-08-28",
                      interpreter=None)
    assert rec["reaction_pass"] == {"n": 0}
    assert rec["parallax_pass"]["error"] == "RuntimeError"


# =========================================== FULL DENOMINATOR LAW

def test_every_eligible_measurement_is_sealed_including_boring_ones(
        tmp_path):
    led = tmp_path / "v.jsonl"
    for closes in ([100 + i * 0.2 for i in range(30)],       # confirms
                   [100 - i * 0.2 for i in range(30)],       # fails
                   [100 + (i % 2) * 0.01 for i in range(30)]):  # flat
        exp = PX.expectation_from_event(ev())
        PX.measure_violation(exp, bars_by_symbol={"NVDA": bars(closes)},
                             close_utc=CLOSE, atr=1.0, ledger=led)
    rows = [json.loads(l) for l in led.read_text().splitlines()]
    assert len(rows) == 3, "a boring outcome was dropped from the "\
                           "denominator"
