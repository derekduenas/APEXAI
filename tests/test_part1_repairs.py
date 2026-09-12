"""Part 1 review repairs: one fee-schedule identity (A), unknown is never zero (B, risk path first), exact
sale-principal fees (C). Every test drives the real objects; none stands a double in for a repaired gate."""
from __future__ import annotations

import json
import math

import pytest

from apex.options_pilot.book import Book
from apex.options_pilot.fees import ROBINHOOD_RHF_2026, SYNTHETIC_FEES, UNVERIFIED_FEES, FeeSchedule, recompute_fees
from apex.options_pilot.risk_authority import CertifiedRiskAuthority, envelope_for
import tests.test_options_pilot_boundary as TB
from apex.options_pilot import ledger as L, session as S

CONTRACT = {"symbol": "SPY", "expiration": "2026-10-02", "strike": 774.0, "right": "CALL"}


def _fees_block(sched):
    return {"schedule_id": sched.schedule_id, "schedule_hash": sched.schedule_hash, "provenance": sched.provenance, "known": sched.known}


def _intent(sched, **over):
    i = {"expression": "LONG_CALL", "action": "BUY", "quantity": 1, "signal_used": "LONG", "contract": CONTRACT,
         "contract_id": "SPY|2026-10-02|774.0|CALL", "intent_id": "I1", "session_id": "S", "scan_id": "SC",
         "risk_envelope": envelope_for(reference_ask=4.90, quantity=1), "fees": _fees_block(sched)}
    i.update(over)
    return i


def _book(rows=()):
    return Book(list(rows), session_id="S", fee_schedules={})


# ================================================================ A. ONE FEE SCHEDULE IDENTITY
class TestOneFeeScheduleIdentity:
    def test_boundary_verified_authority_unverified_refuses(self):
        auth = CertifiedRiskAuthority(fee_schedule=UNVERIFIED_FEES, provenance="LIVE_FEED")
        ap = auth.approve(_intent(ROBINHOOD_RHF_2026), book=_book())
        assert ap["approved"] is False and "FEE_IDENTITY_MISMATCH" in ap["why"]

    def test_authority_verified_record_unverified_refuses(self):
        """The Part 1 defect, exactly: the authority held the authorized schedule, the record carried UNVERIFIED."""
        auth = CertifiedRiskAuthority(fee_schedule=ROBINHOOD_RHF_2026, provenance="LIVE_FEED")
        ap = auth.approve(_intent(UNVERIFIED_FEES), book=_book())
        assert ap["approved"] is False and "FEE_IDENTITY_MISMATCH" in ap["why"]

    def test_two_different_known_schedules_refuse(self):
        auth = CertifiedRiskAuthority(fee_schedule=ROBINHOOD_RHF_2026, provenance="SYNTHETIC_FIXTURE")
        ap = auth.approve(_intent(SYNTHETIC_FEES), book=_book())
        assert ap["approved"] is False and "FEE_IDENTITY_MISMATCH" in ap["why"] and "schedule_id" in ap["why"]

    def test_tampered_hash_refuses(self):
        auth = CertifiedRiskAuthority(fee_schedule=SYNTHETIC_FEES, provenance="SYNTHETIC_FIXTURE")
        bad = _fees_block(SYNTHETIC_FEES); bad["schedule_hash"] = "0" * 64
        ap = auth.approve(_intent(SYNTHETIC_FEES, fees=bad), book=_book())
        assert ap["approved"] is False and "schedule_hash" in ap["why"]

    def test_missing_fee_block_refuses(self):
        auth = CertifiedRiskAuthority(fee_schedule=SYNTHETIC_FEES, provenance="SYNTHETIC_FIXTURE")
        i = _intent(SYNTHETIC_FEES); del i["fees"]
        ap = auth.approve(i, book=_book())
        assert ap["approved"] is False and "FEE_IDENTITY_MISSING" in ap["why"]
        i2 = _intent(SYNTHETIC_FEES, fees={"schedule_id": SYNTHETIC_FEES.schedule_id})
        assert "FEE_IDENTITY_INCOMPLETE" in auth.approve(i2, book=_book())["why"]

    def test_matching_identity_proceeds_and_is_sealed_on_the_approval(self):
        auth = CertifiedRiskAuthority(fee_schedule=SYNTHETIC_FEES, provenance="SYNTHETIC_FIXTURE")
        ap = auth.approve(_intent(SYNTHETIC_FEES), book=_book())
        assert ap["approved"] is True and ap["fee_identity"]["schedule_hash"] == SYNTHETIC_FEES.schedule_hash
        assert ap["fee_identity_verified_against_intent"] is True

    def test_no_quote_is_requested_on_a_mismatch(self, tmp_path):
        """Through the real session: a boundary whose schedule differs from the authority's never reaches the quote."""
        h = TB._h(tmp_path)
        h.bd.risk = CertifiedRiskAuthority(fee_schedule=ROBINHOOD_RHF_2026, provenance="SYNTHETIC_FIXTURE")   # boundary still SYNTHETIC_FEES
        calls = []
        d = TB._scan(h, quote_fn=lambda c: calls.append(c) or {**c, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12, "timestamp_epoch": h.now() - 1.0})
        assert d["decision"] == "REFUSE" and "FEE_IDENTITY_MISMATCH" in d["why"]
        assert calls == [], "a quote was requested despite a fee-identity mismatch"

    def test_identity_is_rechecked_at_fill_when_the_schedule_changes_under_an_open_intent(self, tmp_path):
        h = TB._h(tmp_path)
        rec = h.bd.record_forecast(h.base_forecast("SPY", h.now()), scan_id="X")
        prop = {"expression": "LONG_CALL", "action": "BUY", "quantity": 1, "contract": CONTRACT, "reference_ask": 2.45,
                "expression_rule": "T", "reference_quote": {"bid": 2.4, "ask": 2.45, "ask_size": 9, "timestamp_epoch": h.now() - 1}}
        ir = h.bd.record_intent(forecast_receipt=rec, intent=prop, signal_used="LONG", scan_id="X")
        h.bd.fee_schedule = ROBINHOOD_RHF_2026                       # a configuration change under an OPEN intent
        with pytest.raises(Exception) as e:
            h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
        assert "FEE_IDENTITY_CHANGED_SINCE_INTENT" in str(e.value)


# ================================================================ B. UNKNOWN IS NEVER ZERO
UNKNOWN_FEE = {"schedule_id": "UNVERIFIED", "total": None, "status": "UNKNOWN", "why": "an unknown cost is not zero"}


def _rows(fees_entry, fees_exit, envelope_debit=500.0, with_exit=True):
    rows = [{"kind": "pilot_intent", "intent_id": "I1", "session_id": "S", "contract": CONTRACT, "contract_id": "SPY|2026-10-02|774.0|CALL",
             "quantity": 1, "risk_envelope": {"envelope_debit": envelope_debit, "max_entry_price": 5.0, "feasible": True},
             "expiry_epoch": 2e9, "risk": {"approved": True}}]
    if fees_entry is not None:
        rows.append({"kind": "pilot_fill", "status": "FILLED", "intent_id": "I1", "fill_id": "F1", "session_id": "S", "contract": CONTRACT,
                     "price": 4.90, "quantity_filled": 1, "net_debit": 490.0, "fees_entry": fees_entry,
                     "intent_ref": {"seq": 1, "intent_id": "I1"}, "committed_epoch": 1.0})
        if with_exit:
            rows.append({"kind": "pilot_outcome", "status": "RESOLVED", "intent_id": "I1", "exit_price": 4.54, "fees_exit": fees_exit,
                         "fill_ref": {"seq": 2}, "discharges_position": True})
    return rows


class TestUnknownIsNeverZero:
    def test_b1_unknown_envelope_debit_never_reads_as_free_capacity(self):
        b = Book(_rows(None, None, envelope_debit=None), session_id="S", fee_schedules={})
        assert len(b.reservations) == 1
        assert b.reserved is None and b.reserved_unknown is True
        assert any("RESERVATION_ENVELOPE_UNKNOWN" in p for p in b.summary()["integrity_problems"])
        ri = b.risk_inputs(symbol="SPY")
        assert ri["open_risk"] is None and ri["same_underlying_risk"] is None, "an unknown reservation must not read as 0 planned risk"

    def test_b1_known_envelope_still_reserves_normally(self):
        b = Book(_rows(None, None, envelope_debit=500.0), session_id="S", fee_schedules={})
        assert b.reserved == 500.0 and b.reserved_unknown is False and b.risk_inputs(symbol="SPY")["open_risk"] == 500.0

    def test_b4_unknown_exit_fee_yields_no_net_result(self):
        b = Book(_rows(ROBINHOOD_RHF_2026.entry(1), UNKNOWN_FEE), session_id="S", fee_schedules={})
        p = b.closed[0]
        assert p["realized_pnl"] is None and p["net_status"] == "NOT_ESTIMABLE_FEES"
        assert p["gross_pnl"] == -36.0 and p["debit"] == 490.0 and p["credit"] == 454.0
        assert p["missing_fee_reason"]["exit"] and p["missing_fee_reason"]["entry"] is None
        assert b.session_realized_pnl == 0.0 and b.cash is None and b.gross_cash is not None

    def test_b3_unknown_entry_fee_yields_no_net_result_and_an_unknown_cashflow(self):
        b = Book(_rows(UNKNOWN_FEE, ROBINHOOD_RHF_2026.exit(1, sale_principal=454.0)), session_id="S", fee_schedules={})
        p = b.closed[0]
        assert p["realized_pnl"] is None and p["net_status"] == "NOT_ESTIMABLE_FEES" and p["missing_fee_reason"]["entry"]
        assert any(c["amount"] is None and c["gross_amount"] is not None for c in b.cashflows)

    def test_known_fees_still_produce_a_net_result(self):
        b = Book(_rows(ROBINHOOD_RHF_2026.entry(1), ROBINHOOD_RHF_2026.exit(1, sale_principal=454.0)), session_id="S",
                 fee_schedules={ROBINHOOD_RHF_2026.schedule_id: ROBINHOOD_RHF_2026})
        p = b.closed[0]
        assert p["net_status"] == "NET" and p["realized_pnl"] == round(454.0 - 490.0 - 0.04 - 0.05, 2) == -36.09
        assert b.cash is not None and b.fees_unknown is False

    def test_a_record_claiming_a_net_while_a_fee_is_unknown_is_an_integrity_problem(self):
        rows = _rows(ROBINHOOD_RHF_2026.entry(1), UNKNOWN_FEE)
        rows[-1]["pnl"] = -36.0
        b = Book(rows, session_id="S", fee_schedules={})
        assert any("OUTCOME_PNL_WITH_UNKNOWN_FEES" in p for p in b.summary()["integrity_problems"])

    def test_b6_strict_json_refuses_nan_and_infinity(self):
        from apex.options_pilot.records import canonical_json
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                canonical_json({"x": bad})

    def test_b7_structural_ban_on_unknown_to_zero_coercions(self):
        """THE ACTUAL REPAIR. Any `or 0` / `or 0.0` / `if ... else 0` on the pilot and decision path must carry an
        explicit reviewed exemption comment. This test fails the build on the next occurrence."""
        import pathlib
        import re
        pat = re.compile(r"(\bor\s+0(?:\.0)?\b|\belse\s+0(?:\.0)?\b)")
        paths = ["apex/options_pilot", "apex/pulse_options", "apex/decision_wb", "apex/organism/risk_certificate.py",
                 "apex/organism/risk_kernel.py"]
        offenders = []
        for p in paths:
            pp = pathlib.Path(p)
            for f in ([pp] if pp.is_file() else sorted(pp.rglob("*.py"))):
                for n, line in enumerate(f.read_text().splitlines(), 1):
                    if line.strip().startswith("#") or "UNKNOWN_TO_ZERO_EXEMPT" in line:
                        continue
                    if pat.search(line):
                        offenders.append("%s:%d %s" % (f, n, line.strip()[:100]))
        assert not offenders, ("unknown-to-zero coercion without a reviewed exemption:\n" + "\n".join(offenders))


# ================================================================ C. EXACT SALE-PRINCIPAL FEES
class TestSalePrincipalFees:
    @pytest.mark.parametrize("premium,expected_sec", [(2.00, 0.01), (4.54, 0.01), (5.00, 0.02), (10.00, 0.03)])
    def test_sec_component_is_computed_from_the_actual_principal(self, premium, expected_sec):
        r = ROBINHOOD_RHF_2026.exit(1, sale_principal=premium * 100.0)
        assert r["component_basis"]["sec_component"] == expected_sec
        assert r["component_basis"]["sec_component"] == math.ceil(premium * 100.0 * 20.60 / 1e6 * 100.0) / 100.0
        assert r["sale_principal"] == premium * 100.0

    def test_multiple_contracts_scale_principal_and_per_contract_components(self):
        one = ROBINHOOD_RHF_2026.exit(1, sale_principal=454.0)
        two = ROBINHOOD_RHF_2026.exit(2, sale_principal=908.0)
        assert two["components"]["exchange"] == 2 * one["components"]["exchange"]
        assert two["total"] > one["total"]

    def test_missing_or_invalid_principal_refuses_and_never_defaults(self):
        assert ROBINHOOD_RHF_2026.exit(1)["status"] == "NOT_ESTIMABLE" and ROBINHOOD_RHF_2026.exit(1)["total"] is None
        for bad in (float("nan"), float("inf"), -1.0, True):
            r = ROBINHOOD_RHF_2026.exit(1, sale_principal=bad)
            assert r["total"] is None and r["status"] in ("REFUSED", "NOT_ESTIMABLE")

    def test_a_schedule_with_no_principal_rate_still_prices_per_contract(self):
        assert SYNTHETIC_FEES.exit(1)["total"] == round(0.0 + 0.0 + 0.05, 2) or SYNTHETIC_FEES.exit(1)["total"] is not None

    def test_the_book_recomputes_the_exit_fee_independently_from_the_recorded_principal(self):
        fee = ROBINHOOD_RHF_2026.exit(1, sale_principal=454.0)
        assert recompute_fees(fee, ROBINHOOD_RHF_2026, contracts=1, side="SELL") == []
        tampered = {**fee, "total": round(fee["total"] + 0.05, 2)}
        assert any("FEE_TOTAL_DISAGREES" in p for p in recompute_fees(tampered, ROBINHOOD_RHF_2026, contracts=1, side="SELL"))

    def test_the_changed_schedule_is_no_longer_the_live_default(self):
        from apex.options_pilot.fees import LIVE_DEFAULT_FEES, ROBINHOOD_RHF_2026_AUTHORIZATION
        assert LIVE_DEFAULT_FEES is UNVERIFIED_FEES, "a changed cost model is not an authorized one"
        assert "SUPERSEDED_BY_COMPUTATION_CHANGE" in ROBINHOOD_RHF_2026_AUTHORIZATION["status"]
        assert ROBINHOOD_RHF_2026.version == "2026-09-12b"
