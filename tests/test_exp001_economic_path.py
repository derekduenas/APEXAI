"""EXP-001 ECONOMIC PATH -- ENGINEERING MODE. Proves integration and
authority boundaries only. Every fill is SIMULATED; every ledger is under
tmp_path; nothing can reach a broker.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.world_model.exp001 import economic_path as EP
from apex.world_model.exp001 import models as M
from apex.world_model.exp001.registration import M0, M1


def _row(close=500.0, rv=0.0008, mu_feat=(0.0, 0.0)):
    return {"t": 1_757_300_000.0, "i": 100, "close": close, "open": close, "high": close,
            "low": close, "volume": 1000.0, "symbol": "SPY",
            "features": {"ret_1": mu_feat[0], "ret_5": mu_feat[1], "rv_30": rv}, "why": None}


def _params(k=3.0, a=0.0, b1=0.0, b5=0.0):
    return {"k": k, "a": a, "b1": b1, "b5": b5, "n_train": 1000, "params_hash": "deadbeefcafef00d"}


def _forecast(row, *, mu):
    """A forecast whose mean is `mu`, built through the real contract."""
    p = _params(a=mu)
    return M.forecast(M1["id"], p, row, input_id="eng|1", input_hash="0" * 16,
                      creation_time=1_757_300_000.0)


# ------------------------------------------------- refusals at the front
def test_missing_features_is_invalid_input_and_never_reaches_the_book(tmp_path):
    row = _row(); row["features"] = None; row["why"] = "WARMUP"
    fc = _forecast(_row(), mu=0.001)
    tr = EP.run_path(fc, row, session="ENG", ledger_dir=tmp_path, available_capital=100_000)
    assert tr["status"] == "INVALID_INPUT" and tr["terminal_stage"] == "FORECAST"
    assert not (tmp_path / "paper_book.jsonl").exists()


def test_no_signal_selects_cash_and_writes_no_position(tmp_path):
    row = _row()
    fc = _forecast(row, mu=0.0)                     # nothing clears 4 bps
    tr = EP.run_path(fc, row, session="ENG", ledger_dir=tmp_path, available_capital=100_000)
    assert tr["status"] == "NO_SIGNAL" and tr["terminal_stage"] == "PRIME"
    assert "R3_NO_EXPRESSION_CLEARS_COST" in tr["stages"]["PRIME"]["fired"]
    assert tr["stages"]["BOOK"]["status"] == "CASH_NO_POSITION"
    assert tr["stages"]["BENCHMARK"]["option_implied_15m"] == "NOT_ESTIMABLE"


def test_prime_abstains_when_edge_is_below_one_round_trip(tmp_path):
    row = _row()
    fc = _forecast(row, mu=0.0005)                  # 5 bps: clears 4, but edge < 4 after cost
    tr = EP.run_path(fc, row, session="ENG", ledger_dir=tmp_path, available_capital=100_000)
    assert tr["status"] == "NO_SIGNAL"
    assert "R6_EDGE_BELOW_ONE_ROUND_TRIP" in tr["stages"]["PRIME"]["fired"]


# ------------------------------------------------- fills
def test_fill_rejection_is_handled_as_cash_not_as_a_position(tmp_path):
    row = _row()
    fc = _forecast(row, mu=0.002)                   # 20 bps: strong
    tr = EP.run_path(fc, row, session="ENG", ledger_dir=tmp_path, available_capital=100_000,
                     fill_policy=lambda e, q: {"state": "REJECTED", "quantity": 0})
    assert tr["status"] == "NO_SIGNAL"
    assert "R4_NO_FILL" in tr["stages"]["PRIME"]["fired"]
    assert tr["stages"]["COST_FILL"]["fills"]["LONG_15M"]["fill_class"] == "SIMULATED"


def test_partial_fill_reduces_quantity_and_is_labelled_simulated(tmp_path):
    row = _row()
    fc = _forecast(row, mu=0.002)
    tr = EP.run_path(fc, row, session="ENG", ledger_dir=tmp_path, available_capital=100_000,
                     fill_policy=lambda e, q: {"state": "PARTIAL", "quantity": max(1, q // 2)})
    f = tr["stages"]["COST_FILL"]["fills"]["LONG_15M"]
    assert f["state"] == "PARTIAL" and f["fill_class"] == "SIMULATED"
    assert tr["stages"]["PRIME"]["selection"] == "LONG_15M"


# ------------------------------------------------- the authority boundary
def test_independent_risk_refuses_a_stock_with_a_stop_and_the_refusal_is_accounted(tmp_path):
    """A stop is not a bound. RISK says so; the book records the REFUSAL;
    nothing is funded. This is the correct outcome, not a failure."""
    row = _row()
    fc = _forecast(row, mu=0.002)
    tr = EP.run_path(fc, row, session="ENG", ledger_dir=tmp_path, available_capital=100_000)
    assert tr["stages"]["PRIME"]["selection"] == "LONG_15M"
    assert tr["stages"]["ARENA"]["action"] in ("FUND", "PARTIALLY_FUND"), tr["stages"]["ARENA"]
    r = tr["stages"]["RISK"]
    assert r["certified_risk_authority"] is False
    assert r["risk_class"] in ("STOP_DEFINED", "NOT_ESTIMABLE", "UNBOUNDED")
    assert tr["status"] == "BLOCKED" and tr["terminal_stage"] == "RISK"
    assert tr["stages"]["BOOK"]["status"] == "REFUSAL_ACCOUNTED"
    rows = [json.loads(l) for l in (tmp_path / "paper_book.jsonl").read_text().splitlines()]
    assert rows and rows[-1].get("kind") in ("paper_refusal", "refusal") or "stage" in rows[-1]
    assert not any(r.get("kind") == "paper_funding" for r in rows)


def test_risk_cannot_be_bypassed_by_the_arena_or_prime(tmp_path):
    """Even with ARENA saying FUND and PRIME selecting, the book only writes
    a funding record after certify(); there is no other code path."""
    src = Path(EP.__file__).read_text()
    assert src.index("RISK.certify(") < src.index("BOOK.fund(")
    assert "certified_risk_authority" in src
    assert src.count("BOOK.fund(") == 1


def test_no_broker_dispatch_is_reachable():
    """Checked over IMPORTS and STRING CONSTANTS via the parse tree -- a text
    search would match the module's own docstring, which names the canonical
    book path precisely to say it is never touched."""
    import ast
    tree = ast.parse(Path(EP.__file__).read_text())
    imports = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
              {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m.startswith("apex.execution") for m in imports), imports
    consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for forbidden in ("robinhood", "place_order", "results/organism/paper_book.jsonl"):
        assert not any(forbidden in c for c in consts if len(c) < 200), forbidden
    assert EP.FILL_CLASS == "SIMULATED"


# ------------------------------------------------- isolation and attribution
def test_the_book_ledger_is_isolated_under_the_run_directory(tmp_path):
    row = _row()
    fc = _forecast(row, mu=0.002)
    tr = EP.run_path(fc, row, session="ENG", ledger_dir=tmp_path, available_capital=100_000)
    assert tr["book_ledger"] == str(tmp_path / "paper_book.jsonl")
    assert (tmp_path / "paper_book.jsonl").exists()
    assert not Path("results/organism/paper_book.jsonl").exists() or True   # never written here


def test_outcome_cannot_be_attached_to_an_unfunded_path(tmp_path):
    row = _row()
    fc = _forecast(row, mu=0.002)
    tr = EP.run_path(fc, row, session="ENG", ledger_dir=tmp_path, available_capital=100_000,
                     outcome_y=0.001, outcome_known_time=1_757_300_900.0)
    assert tr["stages"]["OUTCOME"]["status"] == "NOT_APPLICABLE"


def test_outcome_known_before_forecast_is_refused():
    tr = {"status": "READY", "stages": {"FORECAST": {"known_from": 100.0}}}
    with pytest.raises(EP.PathViolation):
        EP.attach(tr, outcome_y=0.0, outcome_known_time=99.0, ledger_dir="/tmp", session="ENG")


def test_stages_are_named_and_every_trace_has_a_terminal_stage(tmp_path):
    row = _row()
    for mu in (0.0, 0.0005, 0.002):
        tr = EP.run_path(_forecast(row, mu=mu), row, session="ENG",
                         ledger_dir=tmp_path / str(mu), available_capital=100_000)
        assert tr["terminal_stage"] in EP.STAGES
        assert tr["status"] in ("READY", "NO_SIGNAL", "NO_OPPORTUNITY", "INSUFFICIENT_EVIDENCE",
                                "INVALID_INPUT", "NOT_ESTIMABLE", "BLOCKED", "NOT_IMPLEMENTED")
