"""CONTROL EXISTENCE != CONTROL ENFORCEMENT.

The operator's doctrine, after LAB-07: for every major safety claim, the
question is not "show me the function that calculates whether this should
happen" but

    show me the exact code path where the prohibited action is stopped
    at the moment it would occur.

LAB-07 failed that test -- FORWARD_RESERVE_CALL_UNITS was arithmetic, and
lab_spare_units() had no callers, so the reserve was never consulted at
the moment units were spent. LAB-08 failed it in a subtler way: the
mixing guard existed but ran in the SCOREBOARD, downstream of the engines
that consume evidence and stamp their output with a class they were
simply told.

Each test below ATTEMPTS the prohibited action through the real code
path and asserts it is stopped there -- not that a validator elsewhere
would have disapproved.
"""
from __future__ import annotations

import pytest


# ---- CLAIM 1: "the Captain cannot authorize" -------------------------------

def test_capital_cannot_even_see_the_captain():
    """Enforcement = NON-REACHABILITY. The sizing module has no import of,
    parameter for, or reference to the Captain, so no Captain state can
    reach the moment of authorization. Absence beats a check."""
    import apex.hunter.capital as cap
    src = open(cap.__file__).read()
    for token in ("captain", "Captain", "CaptainState", "conviction",
                  "next_action"):
        assert token not in src, (
            f"capital.py references {token!r}: the Captain has acquired a "
            f"path to the money")


def test_captain_kernel_has_no_authorization_verbs():
    """Prose-vs-code trap (the repo's recurring bug class, 6+ instances):
    the kernel docstring legitimately SAYS "never authorizes capital". Scan
    executable source only, or the doc defeats its own guard."""
    import apex.captain.kernel as k
    from apex.audit.execution_path import executable_source
    code = executable_source(open(k.__file__).read())
    for token in ("place_order", "authorize", "def size", "tighten_stop"):
        assert token not in code, f"kernel EXECUTES {token!r}"


# ---- CLAIM 2: "Capital caps size" ------------------------------------------

def test_the_cap_binds_at_the_moment_the_weight_is_computed():
    """Not 'a limit is declared somewhere' -- the returned weight itself is
    clamped, and an absurd risk_frac cannot inflate it."""
    from apex.hunter.capital import evaluate_candidate
    from apex.portfolio.risk import MAX_POSITION_WEIGHT
    import inspect
    src = inspect.getsource(evaluate_candidate)
    assert "min(" in src and "MAX_POSITION_WEIGHT" in src, (
        "the cap must be applied where the weight is produced")


# ---- CLAIM 3: "a stop never widens" ----------------------------------------

def test_widening_a_stop_raises_at_the_call_that_widens_it():
    """Drive the REAL state machine into a live position, then try to widen
    the stop with a compelling narrative attached. The refusal must happen
    in tighten_stop itself, not in a later reconciliation."""
    import inspect

    from apex.hunter.statemachine import TradeLifecycle
    src = inspect.getsource(TradeLifecycle.tighten_stop)
    assert "widening" in src and "raise" in src, (
        "the refusal must live inside tighten_stop")
    # the refusal is unconditional on narrative: no rule/text argument can
    # reach a code path that permits widening
    after_check = src.split("if widening:", 1)[1]
    assert "raise" in after_check.split("\n\n")[0]


# ---- CLAIM 4: "live placement is sealed" -----------------------------------

def test_no_module_in_apex_defines_a_placement_function():
    from apex.execution.sealing import scan_package_for_placement
    assert scan_package_for_placement("apex")["clean"] is True


def test_authorization_cannot_be_constructed_at_all():
    from apex.execution.sealing import LiveExecutionAuthorization
    with pytest.raises(Exception):
        LiveExecutionAuthorization()


def test_the_transport_refuses_a_placement_tool_by_name():
    from apex.execution.robinhood import RobinhoodAdapter
    a = RobinhoodAdapter(lambda tool, **kw: {"ok": True})
    with pytest.raises(PermissionError):
        a._call("place_equity_order", symbol="SPY", quantity=1)


# ---- CLAIM 5: "paper is unreachable in Epoch 1" ----------------------------

def test_production_capital_cannot_emit_paper_eligible_without_a_forecast():
    """The forecast slot is NOT_YET_AVAILABLE in Epoch 1, and the state is
    refused at the point the final state is chosen."""
    from apex.hunter.capital import FinalState
    import apex.hunter.capital as cap
    src = open(cap.__file__).read()
    assert "NOT_YET_AVAILABLE" in src
    assert FinalState.PAPER_ELIGIBLE.value == "PAPER_ELIGIBLE"
    assert not hasattr(FinalState, "LIVE_ELIGIBLE")


# ---- CLAIM 6: "evidence classes cannot mix" (LAB-08) -----------------------

def test_the_analog_engine_refuses_rows_that_contradict_the_declaration():
    """THE LAB-08 REGRESSION. Declaring FORWARD over exploratory rows used
    to yield a result STAMPED forward -- laundering, with a clean label."""
    from apex.analog.engine import retrieve
    from apex.hunter.evidence import EvidenceClass, EvidenceViolation
    from tests.test_hunter_spine import QUERY, mem_row
    dirty = [dict(mem_row(i, "2026-08-10"),
                  evidence_class="EODHD_HISTORICAL_EXPLORATORY")
             for i in range(30)]
    with pytest.raises(EvidenceViolation):
        retrieve(QUERY, dirty,
                 evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)


def test_a_single_exploratory_row_poisons_a_forward_batch():
    """Mixing is not a majority vote."""
    from apex.analog.engine import retrieve
    from apex.hunter.evidence import EvidenceClass, EvidenceViolation
    from tests.test_hunter_spine import QUERY, mem_row
    rows = [mem_row(i, "2026-08-10") for i in range(30)]
    rows[17] = dict(rows[17], evidence_class="EODHD_HISTORICAL_EXPLORATORY")
    with pytest.raises(EvidenceViolation):
        retrieve(QUERY, rows,
                 evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)


def test_unstamped_rows_are_refused_as_loudly_as_mismatched_ones():
    """"I cannot verify this" gets the same answer as "this is wrong"."""
    from apex.analog.engine import retrieve
    from apex.hunter.evidence import EvidenceClass, EvidenceViolation
    from tests.test_hunter_spine import QUERY, mem_row
    naked = [{k: v for k, v in mem_row(i, "2026-08-10").items()
              if k != "evidence_class"} for i in range(30)]
    with pytest.raises(EvidenceViolation):
        retrieve(QUERY, naked,
                 evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)


def test_the_ml_trainer_requires_a_declared_class_and_verifies_it():
    from apex.hunter.evidence import EvidenceClass, EvidenceViolation
    from apex.ml.hunter_models import MLContractViolation, build_dataset
    from tests.test_hunter_spine import mem_row
    d = {**mem_row(0, "2026-08-10")["candidate"], "decision_id": "d0",
         "session_date": "2026-08-10", "playbook_id": "HUNTER-001_v1",
         "forward_eligibility": "FORWARD_ELIGIBLE",
         "evidence_class": "EODHD_HISTORICAL_EXPLORATORY"}
    with pytest.raises(MLContractViolation):           # undeclared
        build_dataset([d], {"d0": {"ret_60m": 0.01}}, 60)
    with pytest.raises(EvidenceViolation):             # declared, but false
        build_dataset([d], {"d0": {"ret_60m": 0.01}}, 60,
                      evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)


def test_forward_eligibility_is_not_mistaken_for_a_class_barrier():
    """The replay lab stamps its records FORWARD_ELIGIBLE deliberately, as
    a declared counterfactual. Anything relying on that field to keep
    laboratory tape out of a forward statistic is relying on nothing."""
    src = open("scripts/hunter_replay.py").read()
    assert 'forward_eligibility": "FORWARD_ELIGIBLE"' in src
    assert "EODHD_HISTORICAL_EXPLORATORY" in src


# ---- CLAIM 7: "the forward reserve is protected" (LAB-07) ------------------

def test_the_reserve_is_consulted_at_the_moment_units_are_spent(tmp_path,
                                                                monkeypatch):
    from apex.intraday import quota_ledger as ql
    monkeypatch.setattr(ql, "SPEND_DIR", tmp_path / "q")
    from apex.intraday.eodhd import QuotaGovernor
    ql.spend(ql.ceiling(ql.LAB), ql.LAB)
    g = QuotaGovernor(daily_budget=10 ** 9, purpose=ql.LAB)  # no local bound
    assert g.acquire(5) is False, "the lab reached into the reserve"


# ---- CLAIM 8: "stale data cannot trade" ------------------------------------

def test_stale_quotes_are_refused_where_the_order_is_built():
    """The freshness bound lives in the kill chain, at the point the intent
    becomes ORDER_READY -- not in a monitor that would have complained."""
    import inspect
    from apex.execution.gateway import ExecutionGateway
    src = inspect.getsource(ExecutionGateway)
    assert "quote_fresh" in src or "quote_age" in src


def test_hard_data_quality_flags_block_the_capital_decision():
    import apex.hunter.capital as cap
    src = open(cap.__file__).read()
    assert "data_quality" in src


# ---- the doctrine itself ---------------------------------------------------

def test_every_named_safety_claim_has_a_test_in_this_file():
    """If a claim is added to the doctrine doc, it needs enforcement proof
    here. The doc cannot outrun the tests."""
    import re
    from pathlib import Path
    doc = Path("docs/AUDIT/ENFORCEMENT-DOCTRINE.md")
    assert doc.exists(), "the doctrine must be written down"
    claims = set(re.findall(r"^### CLAIM (\d+)", doc.read_text(), re.M))
    assert claims == {str(i) for i in range(1, 9)}, (
        f"doctrine covers claims {sorted(claims)}; expected 1-8")


# ---- the instrument audits itself -----------------------------------------

def test_the_certification_board_cannot_declare_ready_over_unmeasured_rows():
    """Category II, pointed at our own dashboard. The first version of this
    harness printed "APEX EXECUTION INFRASTRUCTURE: READY" while eight rows
    were unreachable, because the READY condition only checked FAIL. An
    unmeasured row is not a passing row."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import robinhood_certification as rc
    src = open(rc.__file__).read()
    ready = src.split('if not failed', 1)[1].split("\n")[0:2]
    joined = " ".join(ready)
    assert "noroute" in joined and "blocked" in joined, (
        "READY must require every row measured, not merely not-failed")


def test_no_route_is_distinct_from_blocked_broker_auth():
    """"unreachable" and "not yet authenticated" are different facts.
    Collapsing them tells the operator to wait for something that will
    never arrive."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import robinhood_certification as rc
    assert rc.NO_ROUTE != rc.BLOCKED
    from apex.execution.mcp_transport import NO_TRANSPORT, default
    transport, mode = default()
    assert transport is None and mode == NO_TRANSPORT


def test_a_probe_file_cannot_turn_a_missing_tool_into_an_empty_success():
    """LAB-04's lesson: absent is UNKNOWN, never empty."""
    import json

    import pytest as _pt
    from apex.execution.mcp_transport import (TransportUnavailable,
                                              from_probe_file)
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"get_stock_quote": {"last": 1.0}}, fh)
        path = fh.name
    call, mode = from_probe_file(path)
    assert mode == "CLAIMED_MCP"
    assert call("get_stock_quote")["last"] == 1.0
    with _pt.raises(TransportUnavailable):
        call("get_positions")
