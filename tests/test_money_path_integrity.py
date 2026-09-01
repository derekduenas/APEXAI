"""PHASE 1 -- the money path must be semantically true.

Contracts under test:
  BOOK_NUMERIC_INTEGRITY_V2   no malformed number reaches the ledger
  RISK_INPUT_INTEGRITY_V2     the kernel validates what it compares
  RISK_CERTIFICATE_V0         a label is not a risk bound, and an
                              upstream certificate is not authority
  ECONOMIC_RISK_SEMANTICS_V1  only DEFINED_MAX_LOSS carries certified
                              risk; STOP_DEFINED / UNBOUNDED are
                              research observation, never relabelled

Plus the properties that make the hardening trustworthy:
  EQUIVALENCE  on well-formed inputs the new kernel decides exactly
               what the pre-patch kernel decided
  BOUNDARY     the limits trip on the correct side of the threshold
  TAMPER       every load-bearing certificate field is defended
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import math
from pathlib import Path

import pytest

from apex.organism import book, risk_kernel
from apex.organism.numeric_integrity import (NumericIntegrityViolation,
                                             scan_ledger_integrity,
                                             validate_risk_inputs)
from apex.organism.risk_certificate import (DEFINED_MAX_LOSS,
                                            NOT_ESTIMABLE, STOP_DEFINED,
                                            UNBOUNDED,
                                            canonical_planned_risk,
                                            certificate_hash, certify,
                                            verify)

MALFORMED = [float("nan"), float("inf"), float("-inf"), None,
             "300", True, False, [], {}]

# PRIMARY FACTS, not an aggregate: 3.00 x 100 x 1 = 300.00
OPTION_PAYLOAD = {"net_debit": 300.0, "multiplier": 100.0,
                  "expiration": "2026-09-04",
                  "legs": [["BUY", "C", 100.0, 3.0]]}


def opt(debit, **over):
    """A consistent option payload for a given debit."""
    p = {"net_debit": debit, "multiplier": 100.0,
         "expiration": "2026-09-04",
         "legs": [["BUY", "C", 100.0, round(debit / 100.0, 6)]]}
    p.update(over)
    return p
# the real XLU shadow decision from 2026-08-31
XLU = {"entry_fill": 42.203439, "entry_reference": 42.195,
       "stop": 42.19, "quantity": 9894,
       "entry_cost_per_share": 0.008439,
       "stop_exit_cost_per_share": 0.008439}
FACT_KEYS = ("expression", "direction", "declared_risk",
             "sleeve_payload")


def _ok(**over):
    """A well-formed kernel call whose certificate is CONSISTENT with
    the position facts, since the kernel now recomputes it."""
    facts = {"expression": "LONG_CALL", "direction": "LONG",
             "declared_risk": 300.0, "sleeve_payload": OPTION_PAYLOAD}
    facts.update({k: over[k] for k in FACT_KEYS if k in over})
    base = dict(certificate=certify(**facts), symbol="SPY",
                beta_family="US_LARGE_BETA", open_risk=0.0,
                same_underlying_risk=0.0, same_family_risk=0.0,
                session_realized_pnl=0.0, available_capital=10_000.0,
                open_certified_risk=0.0, **facts)
    base.update(over)
    return base


# ------------------------------------------ RISK_CERTIFICATE_V0

def test_long_option_bound_is_the_debit_not_the_label():
    c = certify(expression="LONG_PUT", direction="LONG",
                declared_risk=301.0,
                sleeve_payload=opt(301.0))
    assert c["risk_class"] == DEFINED_MAX_LOSS
    assert c["certified_max_loss"] == 301.0
    assert c["label_equals_bound"] is True
    assert c["gap_exposed"] is False
    assert c["certified_risk_authority"] is True
    assert c["prime_v0_eligible"] is True


def test_long_option_label_may_disagree_with_its_bound():
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0,
                sleeve_payload=opt(375.0))
    assert c["certified_max_loss"] == 375.0
    assert c["upstream_declared_risk"] == 300.0
    assert c["label_equals_bound"] is False


def test_the_bound_is_derived_from_legs_not_from_the_aggregate():
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0, sleeve_payload=OPTION_PAYLOAD)
    assert c["certified_max_loss"] == 300.0
    d = c["derivation"]
    assert d["per_contract_net"] == 3.0
    assert d["multiplier"] == 100.0 and d["contracts"] == 1
    assert "sum(+price if BUY else -price)" in d["formula"]


def test_legs_absent_means_no_bound_even_with_a_net_debit():
    """The whole point: an aggregate alone is no longer sufficient."""
    c = certify(expression="LONG_PUT", direction="LONG",
                declared_risk=300.0,
                sleeve_payload={"net_debit": 300.0})
    assert c["risk_class"] == NOT_ESTIMABLE
    assert any("LEGS_ABSENT" in r for r in c["refusals"])


@pytest.mark.parametrize("bad_mult", [1.0, 10.0, 1000.0])
def test_a_wrong_multiplier_is_refused_not_absorbed(bad_mult):
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0,
                sleeve_payload=opt(300.0, multiplier=bad_mult))
    assert c["risk_class"] == NOT_ESTIMABLE
    assert any("MULTIPLIER_DISAGREEMENT" in r for r in c["refusals"])


def test_an_aggregate_that_contradicts_the_legs_is_refused():
    """THE ATTACK THAT MATTERED. certificate and upstream agree on
    net_debit=250, but the legs imply 300. Before primary-fact
    derivation this produced a perfectly self-consistent $250
    certificate."""
    c = certify(expression="LONG_PUT", direction="LONG",
                declared_risk=250.0,
                sleeve_payload=opt(300.0, net_debit=250.0))
    assert c["risk_class"] == NOT_ESTIMABLE
    assert any("PRIMARY_FACT_DISAGREEMENT" in r for r in c["refusals"])


def test_long_stock_is_stop_defined_with_no_certified_authority():
    c = certify(expression="STOCK", direction="LONG",
                declared_risk=300.0, sleeve_payload=XLU)
    assert c["risk_class"] == STOP_DEFINED
    # the operator decision: no certified max loss, at any notional
    assert c["certified_max_loss"] is None
    assert c["certified_risk_authority"] is False
    assert c["prime_v0_eligible"] is False
    assert c["research_observation_only"] is True
    # the structural worst case is still REPORTED, just not certified
    assert c["structural_worst_case"] == pytest.approx(417560.83,
                                                       abs=0.01)
    assert c["gap_exposed"] is True


def test_short_stock_is_unbounded_and_carries_no_authority():
    c = certify(expression="STOCK", direction="SHORT",
                declared_risk=300.0,
                sleeve_payload={"entry_fill": 225.635364,
                                "stop": 225.73, "quantity": 3170})
    assert c["risk_class"] == UNBOUNDED
    assert c["certified_max_loss"] is None
    assert c["structural_worst_case"] is None
    assert c["certified_risk_authority"] is False
    assert c["gross_notional"] == pytest.approx(715264.10, abs=1.0)


def test_unsupported_expression_is_not_estimable_not_zero():
    for expr in ("LONG_CALL_SPREAD", "BTC_PERP", "CASH", ""):
        c = certify(expression=expr, direction="LONG",
                    declared_risk=300.0, sleeve_payload={})
        assert c["risk_class"] == NOT_ESTIMABLE
        assert c["certified_max_loss"] is None
        assert c["certified_risk_authority"] is False
        assert c["refusals"]


@pytest.mark.parametrize("bad", [b for b in MALFORMED if b is not None])
def test_a_malformed_debit_CLAIM_is_refused(bad):
    """A malformed aggregate is a malformed claim, and a claim that
    cannot be compared to the legs cannot be cleared."""
    c = certify(expression="LONG_PUT", direction="LONG",
                declared_risk=300.0,
                sleeve_payload=opt(300.0, net_debit=bad))
    assert c["risk_class"] == NOT_ESTIMABLE


def test_an_ABSENT_debit_claim_is_fine_because_legs_are_authority():
    """There is nothing to reconcile when no aggregate is asserted --
    the legs alone determine the bound. This is the inversion the
    whole change is about."""
    c = certify(expression="LONG_PUT", direction="LONG",
                declared_risk=300.0,
                sleeve_payload=opt(300.0, net_debit=None))
    assert c["risk_class"] == DEFINED_MAX_LOSS
    assert c["certified_max_loss"] == 300.0


def test_stock_direction_must_be_known():
    c = certify(expression="STOCK", direction="UNKNOWN",
                declared_risk=300.0, sleeve_payload=XLU)
    assert c["risk_class"] == NOT_ESTIMABLE


# ------------------------- PRIMARY-FACT TAMPER BATTERY
# Every attack here leaves the certificate and the upstream aggregate
# in agreement. Only the LEG ECONOMICS reveal the lie.

@pytest.mark.parametrize("legs,why", [
    ([["BUY", "C", 100.0, 4.0]], "one leg price modified"),
    ([["SELL", "C", 100.0, 3.0]], "side flipped"),
    ([], "leg missing"),
    ([["BUY", "C", 100.0]], "leg truncated"),
    ([["BUY", "C", 100.0, -3.0]], "negative leg price"),
    ([["BUY", "C", 100.0, float("nan")]], "NaN leg price"),
    ([["HOLD", "C", 100.0, 3.0]], "invalid side token"),
])
def test_leg_level_tampering_is_caught(legs, why):
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0,
                sleeve_payload=opt(300.0, legs=legs))
    assert c["risk_class"] == NOT_ESTIMABLE, why


def test_contract_count_tampering_changes_the_derived_debit():
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0,
                sleeve_payload=opt(300.0, contracts=2))
    assert c["risk_class"] == NOT_ESTIMABLE
    assert any("PRIMARY_FACT_DISAGREEMENT" in r for r in c["refusals"])


def test_unrecorded_contract_count_is_declared_not_assumed_silently():
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0, sleeve_payload=OPTION_PAYLOAD)
    basis = c["planned_risk_components"]["contracts_basis"]
    assert "PROTOCOL_DEFAULT_UNRECORDED_1" in basis


def test_a_credit_structure_is_not_bounded_by_what_was_paid():
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0,
                sleeve_payload=opt(300.0,
                                   legs=[["SELL", "C", 100.0, 3.0],
                                         ["BUY", "C", 110.0, 1.0]],
                                   net_debit=None))
    assert c["risk_class"] == NOT_ESTIMABLE
    assert any("NOT_A_DEBIT" in r for r in c["refusals"])


def test_risk_refuses_a_leg_tampered_certificate_end_to_end():
    """Kernel-level: the certificate is sealed and internally
    consistent, but describes different legs than Risk was handed."""
    honest = opt(300.0)
    lying = opt(300.0, legs=[["BUY", "C", 100.0, 9.0]])
    cert = certify(expression="LONG_CALL", direction="LONG",
                   declared_risk=300.0, sleeve_payload=honest)
    out = risk_kernel.check(**_ok(certificate=cert,
                                  sleeve_payload=lying))
    assert out["approved"] is False
    assert any("CERTIFICATE_NOT_INDEPENDENTLY_VERIFIED" in r
               for r in out["refusals"])


# --------------------------------- VERTICALS: EXIT RULE DECIDES

VERT = {"net_debit": 335.0, "multiplier": 100.0,
        "expiration": "2026-09-04",
        "legs": [["BUY", "C", 487.5, 6.5], ["SELL", "C", 495.0, 3.15]]}


def test_a_debit_vertical_is_not_certifiable_under_this_exit_rule():
    """Real MSFT CALL_VERTICAL from the sealed ledger. Its debit bounds
    the loss ONLY at expiry; the pre-declared rule closes at quoted
    sides, which requires buying the short leg back."""
    c = certify(expression="CALL_VERTICAL", direction="LONG",
                declared_risk=335.0, sleeve_payload=VERT)
    assert c["risk_class"] == NOT_ESTIMABLE
    assert c["certified_risk_authority"] is False
    assert c["prime_v0_eligible"] is False
    assert any("NOT_CERTIFIABLE_UNDER_THIS_EXIT_RULE" in r
               for r in c["refusals"])
    # the at-expiry figure is still DERIVED and reported, just not
    # certified -- 6.50 - 3.15 = 3.35 x 100
    assert c["bound_at_expiry_only"] == 335.0
    assert c["derivation"]["leg_count"] == 2


def test_vertical_leg_width_tampering_still_changes_the_derivation():
    c = certify(expression="CALL_VERTICAL", direction="LONG",
                declared_risk=335.0,
                sleeve_payload={**VERT, "net_debit": None,
                                "legs": [["BUY", "C", 487.5, 6.5],
                                         ["SELL", "C", 520.0, 0.10]]})
    # with no aggregate asserted there is nothing to reconcile, so the
    # derivation survives and shows the tampered width: 6.50 - 0.10
    assert c["derivation"]["derived_net_debit"] == 640.0
    assert c["bound_at_expiry_only"] == 640.0


def test_the_kernel_refuses_an_uncertifiable_vertical():
    out = risk_kernel.check(**_ok(expression="CALL_VERTICAL",
                                  declared_risk=335.0,
                                  sleeve_payload=VERT))
    assert out["approved"] is False
    assert any("UNCERTIFIABLE_ECONOMIC_RISK" in r
               for r in out["refusals"])


# ------------------------------------------- FEE SEMANTICS

def test_certification_is_explicitly_pre_fee_never_silently_so():
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0, sleeve_payload=OPTION_PAYLOAD)
    assert c["certification_completeness"] == "PRE_FEE"
    ft = c["fee_treatment"]
    assert ft["entry_fees"] == "NOT_RECORDED_IN_ANY_APEX_ARTIFACT"
    assert "EXIT TRADE OCCURS" in ft["fees_on_the_max_loss_path"]


def test_an_uncertified_class_claims_no_completeness():
    c = certify(expression="STOCK", direction="SHORT",
                declared_risk=300.0,
                sleeve_payload={"entry_fill": 225.64, "stop": 225.73,
                                "quantity": 3170})
    assert c["certification_completeness"] == "NONE"


def test_no_leg_carries_a_quote_timestamp():
    """Documented residual, asserted so it cannot be forgotten: leg
    prices have no individual timestamp, so a STALE executable quote
    is NOT detectable at leg level. Staleness is governed upstream by
    known_from, not by the certificate."""
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0, sleeve_payload=OPTION_PAYLOAD)
    for leg in c["inputs"]["legs"]:
        assert len(leg) == 4        # action, right, strike, price only


# -------------------------- RISK-005 CANONICAL PLANNED RISK

def test_entry_slippage_is_never_counted_twice():
    """The executable fill ALREADY crossed the spread, so only the EXIT
    crossing may be added. The incumbent sleeve added both."""
    p = canonical_planned_risk(
        entry_fill=42.203439, stop=42.19, quantity=9894,
        exit_cost_per_share=0.008439, entry_cost_per_share=0.008439)
    stop_distance = (42.203439 - 42.19) * 9894          # 132.96
    exit_only = 0.008439 * 9894                         # 83.49
    assert p["planned_risk_amount"] == pytest.approx(
        stop_distance + exit_only, abs=0.02)
    # the incumbent number was 299.99 -- one whole entry crossing more
    assert p["planned_risk_amount"] < 299.99 - 80


def test_planned_risk_keeps_its_components_visible():
    p = canonical_planned_risk(
        entry_fill=42.203439, stop=42.19, quantity=9894,
        exit_cost_per_share=0.008439, entry_cost_per_share=0.008439)
    c = p["components"]
    assert c["stop_distance_per_share"] == pytest.approx(0.013439,
                                                         abs=1e-6)
    assert c["exit_friction_per_share"] == pytest.approx(0.008439,
                                                         abs=1e-6)
    assert c["multiplier"] == 1.0
    # entry slippage is reported but NOT added
    assert c["entry_slippage_already_inside_entry_fill"] == \
        pytest.approx(83.49, abs=0.02)
    assert c["entry_fees"] == "NOT_MODELLED_IN_THIS_MONEY_PATH"


def test_stop_defined_certificate_uses_the_canonical_planned_risk():
    c = certify(expression="STOCK", direction="LONG",
                declared_risk=299.99, sleeve_payload=XLU)
    assert c["planned_risk_basis"].startswith("CANONICAL_V1")
    assert c["planned_risk_amount"] == pytest.approx(216.46, abs=0.05)
    # the upstream label is preserved, never overwritten
    assert c["upstream_declared_risk"] == 299.99


# ------------------------------- RISK_INPUT_INTEGRITY_V2

@pytest.mark.parametrize("bad", MALFORMED)
def test_malformed_declared_risk_fails_closed(bad):
    out = risk_kernel.check(**_ok(declared_risk=bad))
    assert out["approved"] is False
    assert any("declared_risk" in r for r in out["refusals"])


@pytest.mark.parametrize("field", ["open_risk", "same_underlying_risk",
                                   "same_family_risk",
                                   "session_realized_pnl",
                                   "available_capital",
                                   "open_certified_risk"])
def test_nan_in_any_risk_input_fails_closed(field):
    """NaN defeats every comparison by returning False, so a NaN in ANY
    of these silently DISABLED the limit it feeds rather than tripping
    it. A single guard on declared_risk left five live fail-open
    paths."""
    out = risk_kernel.check(**_ok(**{field: float("nan")}))
    assert out["approved"] is False
    assert any(field in r for r in out["refusals"])


def test_negative_size_fails_closed_not_silently_approved():
    for bad in (-1.0, -300.0, 0.0):
        assert risk_kernel.check(**_ok(declared_risk=bad))[
            "approved"] is False


def test_signed_fields_keep_their_sign():
    """A drawdown halt that cannot accept a negative number is not a
    drawdown halt."""
    assert validate_risk_inputs(
        declared_risk=300.0, open_risk=0.0, same_underlying_risk=0.0,
        same_family_risk=0.0, session_realized_pnl=-950.0,
        available_capital=-25.0) == []


def test_drawdown_halt_actually_fires_on_a_real_negative():
    out = risk_kernel.check(**_ok(session_realized_pnl=-1000.0))
    assert out["approved"] is False
    assert any("drawdown" in r for r in out["refusals"])


def test_missing_risk_input_is_an_absence_that_refuses():
    assert any("absent" in v for v in validate_risk_inputs(
        declared_risk=300.0, open_risk=0.0))


# ---------------- the certificate gates the risk budget

def test_certificate_and_facts_are_required_with_no_defaults():
    for missing in ("certificate", "expression", "direction",
                    "sleeve_payload", "open_certified_risk"):
        args = _ok()
        args.pop(missing)
        with pytest.raises(TypeError):
            risk_kernel.check(**args)


@pytest.mark.parametrize("cert", [None, {}, {"risk_class": "SAFE"},
                                  "DEFINED_MAX_LOSS", 1.0])
def test_absent_or_forged_certificate_refuses(cert):
    out = risk_kernel.check(**_ok(certificate=cert))
    assert out["approved"] is False
    assert any("CERTIFICATE" in r for r in out["refusals"])


def test_uncertifiable_risk_refuses():
    out = risk_kernel.check(**_ok(expression="LONG_CALL_SPREAD",
                                  sleeve_payload={}))
    assert out["approved"] is False
    assert any("UNCERTIFIABLE" in r for r in out["refusals"])


def test_btc_refuses_with_the_missing_contract_spec_named():
    out = risk_kernel.check(**_ok(expression="BTC_PERP",
                                  sleeve_payload={}))
    assert out["approved"] is False
    assert any("UNBOUNDABLE_BTC_PERP" in r for r in out["refusals"])


def test_unbounded_short_funds_only_as_research_never_as_certified():
    """The operator decision: no invented notional cap, but no
    certified authority either. It funds in the research lane with its
    status stamped into the record."""
    out = risk_kernel.check(**_ok(
        expression="STOCK", direction="SHORT",
        sleeve_payload={"entry_fill": 225.64, "stop": 225.73,
                        "quantity": 3170}))
    assert out["approved"] is True
    assert out["economic_risk"]["certified_risk_authority"] is False
    assert out["economic_risk"]["prime_v0_eligible"] is False
    assert out["economic_risk"]["certified_max_loss"] is None
    assert any("NO_CERTIFIED_RISK_AUTHORITY" in w
               for w in out["warnings"])
    assert any("UNBOUNDED_STRUCTURAL_LOSS" in w
               for w in out["warnings"])


def test_kernel_output_carries_the_bound_for_the_book_to_seal():
    out = risk_kernel.check(**_ok())
    assert out["economic_risk"]["certified_max_loss"] == 300.0
    assert out["economic_risk"]["prime_v0_eligible"] is True
    assert out["limit_denomination"] == "PLANNED_RISK_DECLARED_1R"
    assert out["certified_aggregate_basis"] == \
        "SUM_OF_VERIFIED_CERTIFIED_MAX_LOSS"


# ----------------------------------------- TAMPER BATTERY

def _tampered(**edits):
    """A certificate altered after sealing, exactly as a compromised or
    buggy upstream would produce."""
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0, sleeve_payload=OPTION_PAYLOAD)
    c.update(edits)
    return c


@pytest.mark.parametrize("edits", [
    {"certified_max_loss": 1.0},              # amount understated
    {"certified_max_loss": 100000.0},         # amount overstated
    {"planned_risk_amount": 1.0},
    {"gross_notional": 1.0},
    {"expression": "LONG_PUT"},
    {"direction": "SHORT"},
    {"certificate_hash": "0" * 64},           # hash forged
    {"inputs": {"net_debit": 1.0}},           # inputs swapped
])
def test_risk_refuses_every_tampered_certificate(edits):
    """Upstream certificate generation is NOT authority."""
    out = risk_kernel.check(**_ok(certificate=_tampered(**edits)))
    assert out["approved"] is False
    assert any("CERTIFICATE_NOT_INDEPENDENTLY_VERIFIED" in r
               for r in out["refusals"]), out["refusals"]


def test_an_unbounded_position_cannot_self_grant_certified_authority():
    """The attack that matters most: an unbounded short rewriting its
    own certificate to claim a finite bound and PRIME eligibility."""
    payload = {"entry_fill": 225.635364, "stop": 225.73,
               "quantity": 3170}
    forged = certify(expression="STOCK", direction="SHORT",
                     declared_risk=300.0, sleeve_payload=payload)
    forged.update({"risk_class": DEFINED_MAX_LOSS,
                   "certified_max_loss": 300.0,
                   "certified_risk_authority": True,
                   "prime_v0_eligible": True,
                   "research_observation_only": False})
    out = risk_kernel.check(**_ok(expression="STOCK", direction="SHORT",
                                  sleeve_payload=payload,
                                  certificate=forged))
    assert out["approved"] is False
    assert any("CERTIFICATE_NOT_INDEPENDENTLY_VERIFIED" in r
               for r in out["refusals"])


def test_a_valid_certificate_for_a_different_position_is_refused():
    """A perfectly-sealed certificate is still wrong if it describes
    another trade."""
    other = certify(expression="LONG_CALL", direction="LONG",
                    declared_risk=50.0,
                    sleeve_payload=opt(50.0))
    out = risk_kernel.check(**_ok(certificate=other))
    assert out["approved"] is False
    assert any("CERTIFICATE_IS_FOR_A_DIFFERENT_POSITION" in r
               or "RECOMPUTATION_DISAGREEMENT" in r
               for r in out["refusals"])


def test_altered_quantity_changes_the_verdict():
    """Quantity is load-bearing for stock: altering it must not slip
    past independent recomputation."""
    payload = dict(XLU)
    cert = certify(expression="STOCK", direction="LONG",
                   declared_risk=299.99, sleeve_payload=payload)
    lying = dict(payload, quantity=1)      # facts say 1, cert says 9894
    problems = verify(cert, expression="STOCK", direction="LONG",
                      declared_risk=299.99, sleeve_payload=lying)
    assert problems


def test_the_hash_covers_every_load_bearing_field():
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0, sleeve_payload=OPTION_PAYLOAD)
    baseline = certificate_hash(c)
    for field, value in (("certified_max_loss", 1.0),
                         ("risk_class", UNBOUNDED),
                         ("expression", "LONG_PUT"),
                         ("direction", "SHORT"),
                         ("planned_risk_amount", 7.0),
                         ("gross_notional", 7.0),
                         ("certified_risk_authority", False),
                         ("prime_v0_eligible", False),
                         ("inputs", {})):
        altered = dict(c)
        altered[field] = value
        assert certificate_hash(altered) != baseline, field


def test_an_untampered_certificate_verifies_clean():
    c = certify(expression="LONG_CALL", direction="LONG",
                declared_risk=300.0, sleeve_payload=OPTION_PAYLOAD)
    assert verify(c, expression="LONG_CALL", direction="LONG",
                  declared_risk=300.0,
                  sleeve_payload=OPTION_PAYLOAD) == []


# -------------------------------------------------- BOUNDARY

@pytest.mark.parametrize("value,approved", [(500.0, True),
                                            (500.01, False)])
def test_per_trade_limit_boundary(value, approved):
    out = risk_kernel.check(**_ok(
        declared_risk=value, sleeve_payload=opt(value)))
    assert out["approved"] is approved


@pytest.mark.parametrize("open_risk,approved", [(1200.0, True),
                                                (1200.01, False)])
def test_aggregate_limit_boundary(open_risk, approved):
    out = risk_kernel.check(**_ok(open_risk=open_risk,
                                  beta_family="UNKNOWN"))
    assert out["approved"] is approved


@pytest.mark.parametrize("open_cert,approved", [(1200.0, True),
                                                (1200.01, False)])
def test_certified_aggregate_binds_on_verified_bounds(open_cert,
                                                      approved):
    """The semantically correct aggregate: a sum of verified bounds."""
    out = risk_kernel.check(**_ok(open_certified_risk=open_cert,
                                  beta_family="UNKNOWN"))
    assert out["approved"] is approved
    if not approved:
        assert any("aggregate CERTIFIED loss" in r
                   for r in out["refusals"])


def test_uncertified_positions_cannot_consume_the_certified_budget():
    """An unbounded short has no bound to add, so it must not silently
    occupy certified capacity at its label value."""
    out = risk_kernel.check(**_ok(
        expression="STOCK", direction="SHORT",
        sleeve_payload={"entry_fill": 225.64, "stop": 225.73,
                        "quantity": 3170},
        open_certified_risk=1499.0, beta_family="UNKNOWN"))
    assert out["approved"] is True
    assert not any("aggregate CERTIFIED" in r for r in out["refusals"])


@pytest.mark.parametrize("pnl,approved", [(-999.99, True),
                                          (-1000.0, False)])
def test_drawdown_halt_boundary(pnl, approved):
    assert risk_kernel.check(**_ok(session_realized_pnl=pnl))[
        "approved"] is approved


# ------------------------------------------------ EQUIVALENCE

def _pre_patch_kernel():
    src = Path("/tmp/risk_kernel.py.pre")
    if not src.exists():
        pytest.skip("pre-patch kernel snapshot unavailable")
    loader = importlib.machinery.SourceFileLoader("_rk_pre", str(src))
    spec = importlib.util.spec_from_loader("_rk_pre", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_valid_inputs_decide_exactly_as_before():
    """The hardening must change NOTHING for well-formed inputs.

    Compared at open_certified_risk=0, which is the apples-to-apples
    configuration: the pre-patch kernel had no certified-aggregate
    concept at all, so the comparable case is the one where that new
    constraint does not bind. It is proven to bind separately in
    test_certified_aggregate_binds_on_verified_bounds."""
    pre = _pre_patch_kernel()
    grid = [(dr, orisk, ur, fr, pnl, cap)
            for dr in (1.0, 300.0, 499.99, 500.0, 500.01)
            for orisk in (0.0, 1000.0, 1200.01)
            for ur in (0.0, 300.0)
            for fr in (0.0, 700.01)
            for pnl in (0.0, -999.99, -1000.0)
            for cap in (10_000.0, 100.0)]
    assert len(grid) == 360
    for dr, orisk, ur, fr, pnl, cap in grid:
        common = dict(declared_risk=dr, symbol="SPY",
                      beta_family="US_LARGE_BETA", open_risk=orisk,
                      same_underlying_risk=ur, same_family_risk=fr,
                      session_realized_pnl=pnl, available_capital=cap)
        old = pre.check(**common)
        new = risk_kernel.check(
            expression="LONG_CALL", direction="LONG",
            sleeve_payload=opt(dr), open_certified_risk=0.0,
            certificate=certify(expression="LONG_CALL",
                                direction="LONG", declared_risk=dr,
                                sleeve_payload=opt(dr)),
            **common)
        assert new["approved"] == old["approved"], common
        assert new["refusals"] == old["refusals"], common


# ------------------------------ BOOK_NUMERIC_INTEGRITY_V2

def _env(declared_risk=300.0):
    return {"candidate_id": "T1", "sleeve": "OPTIONS", "symbol": "SPY",
            "direction": "LONG", "expression": "LONG_CALL",
            "declared_risk": declared_risk, "known_from": "2026-08-31",
            "sleeve_payload": {"net_debit": 300.0}}


def _kernel_stub(approved=True):
    return {"threshold_set": "T", "approved": approved,
            "economic_risk": {"certified_max_loss": 300.0,
                              "certified_risk_authority": True},
            "warnings": []}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 0.0])
def test_book_refuses_to_seal_a_malformed_funding(tmp_path, bad):
    led = tmp_path / "b.jsonl"
    with pytest.raises(NumericIntegrityViolation):
        book.fund(_env(bad), arena_action="FUND", arena_reasons=[],
                  kernel=_kernel_stub(), ledger=led)
    assert not led.exists() or led.read_text().strip() == ""


def test_book_refuses_a_malformed_sleeve_payload_number(tmp_path):
    led = tmp_path / "b.jsonl"
    env = _env()
    env["sleeve_payload"] = {"net_debit": float("nan")}
    with pytest.raises(NumericIntegrityViolation):
        book.fund(env, arena_action="FUND", arena_reasons=[],
                  kernel=_kernel_stub(), ledger=led)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), None,
                                 "oops", True])
def test_book_refuses_a_malformed_outcome(tmp_path, bad):
    led = tmp_path / "b.jsonl"
    with pytest.raises(NumericIntegrityViolation):
        book.attach_outcome(candidate_id="T1", session="S",
                            executable_pnl=bad, outcome_class="X",
                            ledger=led)


@pytest.mark.parametrize("good", [0.0, -586.16, 12.5])
def test_book_accepts_real_outcomes_including_losses(tmp_path, good):
    led = tmp_path / "b.jsonl"
    book.attach_outcome(candidate_id="T1", session="S",
                        executable_pnl=good, outcome_class="X",
                        ledger=led)
    assert json.loads(led.read_text().splitlines()[0])[
        "executable_pnl"] == good


def test_execution_failure_sentinel_survives(tmp_path):
    led = tmp_path / "b.jsonl"
    book.attach_outcome(candidate_id="T1", session="S",
                        executable_pnl="NOT_ESTIMABLE",
                        outcome_class="EXECUTION_FAILURE", ledger=led)
    assert json.loads(led.read_text().splitlines()[0])[
        "executable_pnl"] == "NOT_ESTIMABLE"


def test_a_refusal_can_still_record_the_malformed_size(tmp_path):
    led = tmp_path / "b.jsonl"
    book.refuse(_env(float("nan")), stage="RISK_KERNEL",
                reasons=["malformed"], ledger=led)
    assert json.loads(led.read_text().splitlines()[0])[
        "declared_risk_repr"] == "nan"


def test_state_reports_inherited_contamination_and_does_not_hide_it():
    rows = [{"kind": "paper_outcome", "candidate_id": "X",
             "executable_pnl": float("nan")}]
    scan = scan_ledger_integrity(rows)
    assert scan["integrity"] == "CONTAMINATED"
    assert scan["contaminated_records"][0]["candidate_id"] == "X"


def test_nan_outcome_poisons_state_and_the_kernel_then_refuses(tmp_path):
    """End-to-end proof of the original defect and its fix."""
    led = tmp_path / "b.jsonl"
    led.write_text(json.dumps(
        {"kind": "paper_outcome", "candidate_id": "X", "session": "S",
         "executable_pnl": float("nan")}) + "\n")
    st = book.state(ledger=led, session="S")
    assert st["integrity"] == "CONTAMINATED"
    assert math.isnan(st["session_realized_pnl"])
    out = risk_kernel.check(**_ok(
        session_realized_pnl=st["session_realized_pnl"],
        available_capital=st["available_capital"]))
    assert out["approved"] is False


def test_book_separates_certified_from_uncertified_exposure(tmp_path):
    """The accounting fiction that hid 148x leverage was summing
    labels. Certified and research exposure are now separate lines."""
    led = tmp_path / "b.jsonl"
    book.fund(_env(), arena_action="FUND", arena_reasons=[],
              kernel=_kernel_stub(), ledger=led)
    env2 = {**_env(), "candidate_id": "T2", "symbol": "NVDA",
            "sleeve": "EQUITY", "expression": "STOCK",
            "direction": "SHORT",
            "sleeve_payload": {"entry_fill": 225.64, "stop": 225.73,
                               "quantity": 3170}}
    book.fund(env2, arena_action="FUND", arena_reasons=[],
              kernel={"threshold_set": "T", "approved": True,
                      "economic_risk": {"certified_max_loss": None,
                                        "certified_risk_authority":
                                            False,
                                        "gross_notional": 715264.10},
                      "warnings": []}, ledger=led)
    st = book.state(ledger=led)
    assert st["open_certified_risk"] == 300.0
    assert st["open_uncertified_positions"] == 1
    assert st["open_uncertified_notional"] == pytest.approx(715264.10,
                                                            abs=1.0)
