"""FEE-AUTHORIZATION-002 — source verification and operator authorization are two different facts.

THE FINDING THIS BRICK REPAIRS. `ROBINHOOD_RHF_2026` v2026-09-12b described itself as an unauthorized candidate
and was constructed as `PROVIDER_VERIFIED`. `known` was derived from provenance alone, so it reported
`known=True`; it carried the SUPERSEDED 2026-09-12 authorization inside itself; and because
`LIVE_DEFAULT_FEES = UNVERIFIED_FEES` is a DEFAULT rather than a CONTROL, any caller that simply passed the
candidate explicitly obtained a certified trade.

Verifying a document and authorizing a computation are different acts by different parties. The repair keeps them
apart, binds the authorization into the canonical fee identity, and refuses at the boundary -- before any quote,
certificate, kernel check, intent or fill -- however the schedule was supplied."""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from apex.options_pilot import ledger as L
from apex.options_pilot import session as S
from apex.options_pilot.fees import (AUTHORIZED, AUTHORIZATION_MISMATCH, LIVE_DEFAULT_FEES, NOT_AUTHORIZED,
                                     ROBINHOOD_RHF_2026, ROBINHOOD_RHF_2026_SUPERSEDED_AUTHORIZATION,
                                     SYNTHETIC_FEES, FeeAuthorization, FeeAuthorizationRefused, FeeSchedule)
from apex.options_pilot.synthetic_harness import SyntheticHarness, T0

RB = ROBINHOOD_RHF_2026


def exact_authorization(sched: FeeSchedule, **over) -> FeeAuthorization:
    """A TEST-ONLY authorization matching `sched` exactly. This is the control case; it is constructed here, in
    the test, and no authorization is authored into the product."""
    base = dict(schedule_id=sched.schedule_id, version=sched.version,
                source_document_sha256=sched.source_document_sha256, terms_digest=sched.terms_digest,
                computation_policy_digest=sched.computation_digest,
                implementation_digest=sched.implementation_digest, effective_date=sched.effective_date,
                status=AUTHORIZED, authorized_by="TEST_ONLY_NOT_AN_OPERATOR",
                authorized_utc="2026-09-13T00:00:00Z", scope="test")
    base.update(over)
    return FeeAuthorization(**base)


def boundary_with(fees):
    d = pathlib.Path(tempfile.mkdtemp())
    return SyntheticHarness(d / "l.jsonl", session_id="FA", t0=T0, risk="certified", fee_schedule=fees)


# =============================================================== the two facts are separate


class TestSourceVerificationIsNotAuthorization:
    def test_the_shipped_candidate_is_source_verified_and_NOT_authorized(self):
        assert RB.source_verified is True          # a document backs the terms
        assert RB.known is True                    # the arithmetic is complete
        assert RB.authorized is False              # and nobody has cleared it
        assert RB.usable is False                  # so it may not be used
        assert RB.authorization is None

    def test_no_object_says_both_candidate_and_authorized(self):
        assert "CANDIDATE, NOT AUTHORIZED" in RB.note
        assert "AUTHORIZED by the operator" not in RB.note
        assert "authorization" not in RB.verified_against, "the schedule carries source verification only"

    def test_the_superseded_authorization_is_retained_as_history_and_detached(self):
        h = ROBINHOOD_RHF_2026_SUPERSEDED_AUTHORIZATION
        assert h["applies_to_current_schedule"] is False
        assert "SUPERSEDED_BY_COMPUTATION_CHANGE" in h["status"]
        assert RB.authorization is None, "history must not be reachable as authority"

    def test_the_synthetic_fixture_is_exempt_and_stays_usable(self):
        """Authorizing a fixture that can never be a live cost claim would be theatre, and would break every
        orchestration test for no safety gain."""
        assert SYNTHETIC_FEES.requires_authorization is False and SYNTHETIC_FEES.usable is True


class TestTheAuthorizationIsBoundIntoTheIdentity:
    def test_identity_names_the_authorization_and_the_computation(self):
        i = RB.identity()
        for f in ("authorization_status", "authorization_digest", "computation_policy_digest",
                  "implementation_digest", "source_document_sha256"):
            assert f in i, f
        assert i["authorization_status"] == NOT_AUTHORIZED and i["authorization_digest"] is None

    def test_every_identity_field_is_in_IDENTITY_FIELDS(self):
        assert set(RB.identity()) == set(FeeSchedule.IDENTITY_FIELDS)

    def test_attaching_an_authorization_changes_the_identity(self):
        """So a persisted approval stops verifying the moment the authorization changes or is removed."""
        before = RB.identity()
        after = FeeSchedule(**{**RB.__dict__, "authorization": exact_authorization(RB)}).identity()
        assert before != after
        assert after["authorization_status"] == AUTHORIZED and after["authorization_digest"]

    def test_the_computation_digest_distinguishes_the_two_SEC_computations(self):
        """This is the field that would have caught the supersession. The RATES are unchanged between
        v2026-09-12 and v2026-09-12b; only HOW the SEC component is computed changed."""
        old_style = FeeSchedule(**{**RB.__dict__, "sale_principal_rate_per_million": None})
        assert old_style.computation_digest != RB.computation_digest


# =============================================================== the eight scenarios


class TestTheEightScenarios:

    def test_1_the_explicit_candidate_bypass_is_closed(self):
        """THE FINDING. LIVE_DEFAULT_FEES is a default; passing the candidate explicitly used to trade."""
        with pytest.raises(FeeAuthorizationRefused, match="BOUNDARY_REFUSES_UNAUTHORIZED_FEE_SCHEDULE"):
            boundary_with(RB)

    def test_2_the_prior_v2026_09_12_authorization_does_not_apply_to_v2026_09_12b(self):
        """The superseded authorization, presented for the new computation, is refused on the field that
        actually changed."""
        stale = exact_authorization(RB, version="2026-09-12",
                                    computation_policy_digest=FeeSchedule(
                                        **{**RB.__dict__, "sale_principal_rate_per_million": None}).computation_digest)
        sched = FeeSchedule(**{**RB.__dict__, "authorization": stale})
        st = sched.authorization_state()
        assert st["status"] == AUTHORIZATION_MISMATCH and st["basis"] == "version"
        with pytest.raises(FeeAuthorizationRefused):
            boundary_with(sched)

    def test_3_an_altered_SEC_computation_invalidates_the_authorization(self):
        auth = exact_authorization(RB)
        altered = FeeSchedule(**{**RB.__dict__, "sale_principal_rate_per_million": None, "authorization": auth})
        st = altered.authorization_state()
        assert st["status"] == AUTHORIZATION_MISMATCH
        assert st["basis"] in ("terms_digest", "computation_policy_digest")

    def test_4_an_altered_terms_digest_invalidates_the_authorization(self):
        bad = exact_authorization(RB, terms_digest="0" * 64)
        st = FeeSchedule(**{**RB.__dict__, "authorization": bad}).authorization_state()
        assert st["status"] == AUTHORIZATION_MISMATCH and st["basis"] == "terms_digest"

    def test_5_an_altered_document_digest_invalidates_the_authorization(self):
        bad = exact_authorization(RB, source_document_sha256="deadbeef")
        st = FeeSchedule(**{**RB.__dict__, "authorization": bad}).authorization_state()
        assert st["status"] == AUTHORIZATION_MISMATCH and st["basis"] == "source_document_sha256"

    def test_6_a_missing_authorization_is_NOT_AUTHORIZED_not_a_default(self):
        st = RB.authorization_state()
        assert st["status"] == NOT_AUTHORIZED and "NO_AUTHORIZATION" in st["why"]
        assert "verified source document is not an authorized cost model" in st["why"]

    def test_7_an_authorization_for_another_schedule_does_not_apply(self):
        other = exact_authorization(RB, schedule_id="SOME_OTHER_BROKER")
        st = FeeSchedule(**{**RB.__dict__, "authorization": other}).authorization_state()
        assert st["status"] == AUTHORIZATION_MISMATCH and st["basis"] == "schedule_id"

    def test_8_CONTROL_an_exact_authorization_is_accepted_and_trades(self):
        """The control. With an authorization matching every field, the same schedule becomes usable and the
        pipeline completes -- so the refusals above are the authorization check working, not a broken build."""
        sched = FeeSchedule(**{**RB.__dict__, "authorization": exact_authorization(RB)})
        assert sched.authorized is True and sched.usable is True
        h = boundary_with(sched)
        out = S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        rows = L.read_all(h.bd.ledger)
        assert out["decision"] == "TRADE"
        assert len([r for r in rows if r["kind"] == "pilot_fill"]) == 1


# =============================================================== where the refusal happens


class TestTheRefusalPrecedesEverything:
    def test_no_quote_is_requested_for_an_unauthorized_schedule(self):
        """'Before quote request, certificate, kernel, intent or fill' -- asserted by observing that the quote
        provider is never called, because the boundary cannot even be constructed."""
        asked = []

        class CountingQuotes:
            def __call__(self, *a, **k):
                asked.append(1)
                raise AssertionError("a quote was requested for an unauthorized fee schedule")

        with pytest.raises(FeeAuthorizationRefused):
            d = pathlib.Path(tempfile.mkdtemp())
            h = SyntheticHarness(d / "l.jsonl", session_id="FA", t0=T0, risk="certified", fee_schedule=RB)
            h.quotes = CountingQuotes()
            S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        assert asked == []

    def test_the_risk_authority_refuses_independently_of_the_boundary(self):
        """Defence in depth: even if a boundary were constructed some other way, the authority refuses before
        the certificate and the kernel."""
        from apex.options_pilot.risk_authority import CertifiedRiskAuthority
        ra = CertifiedRiskAuthority(fee_schedule=RB, provenance="SYNTHETIC_FIXTURE")
        h = boundary_with(SYNTHETIC_FEES)
        body = {"expression": "LONG_CALL", "contract": {"expiration": "2026-10-09", "strike": 650.0, "right": "CALL"},
                "quantity": 1, "action": "BUY", "session_id": "S", "scan_id": "S:1",
                "fees": RB.identity(), "signal_used": "LONG",
                "risk_envelope": {"max_loss": 250.0, "reference_ask": 2.50, "max_entry_price": 2.50},
                "intent_id": "T1"}
        r = ra.approve(body, book=h.bd.book())
        assert r["approved"] is False
        assert "FEE_SCHEDULE_NOT_AUTHORIZED" in r["why"]

    def test_charging_an_unauthorized_schedule_returns_NOT_AUTHORIZED_never_a_number(self):
        for side in (RB.entry(1), RB.exit(1, sale_principal=540.0)):
            assert side["total"] is None and side["status"] == "NOT_AUTHORIZED"

    def test_an_unverified_schedule_still_starts_a_session_and_records_refusals(self):
        """UNVERIFIED must NOT block construction: a session that records refusals is evidence, and one that
        cannot start is not."""
        h = boundary_with(LIVE_DEFAULT_FEES)
        out = S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        assert out["decision"] == "REFUSE" and "FEE_SCHEDULE_UNKNOWN" in str(out["why"])
