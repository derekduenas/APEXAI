"""FEE-AUTHORIZATION-002-R1 — the two joins made real.

FEE-AUTHORIZATION-002 separated source verification from operator authorization and added the fields. Review found
that neither join was actually complete:

  F1  `CertifiedRiskAuthority.accepts()` and `fee_identity_problem()` each carried their OWN hand-written tuple of
      seven fields. The identity had grown to twelve. So an approval issued under ONE operator authorization was
      honoured by an authority running a DIFFERENT one, and an intent sealed under one passed the gate on another.
      The producer recorded the right information; the consumers did not inspect it.

  F2  `computation_digest` hashed a hand-written DESCRIPTION of the arithmetic while `_side()` carried its own
      parallel hard-coded rules. Changing ROUND_CEILING to ROUND_FLOOR changed the charge from 0.06 to 0.05 and
      left the digest byte-identical. It was a declared recipe, not a binding to executable computation.

Both reproductions are in docs/evidence/fee_authorization_002/R1_FINDING_REPRODUCTION_before_repair.txt."""
from __future__ import annotations

import ast
import pathlib
import tempfile
from decimal import Decimal, ROUND_FLOOR

import pytest

from apex.options_pilot import ledger as L
from apex.options_pilot import session as S
from apex.options_pilot.fees import (AUTHORIZED, AUTHORIZATION_MISMATCH, FeeAuthorization, FeeComputationPolicy,
                                     FeeSchedule, ROBINHOOD_RHF_2026, SALE_PRINCIPAL_POLICY_V1,
                                     identity_problem, implementation_digest_of)
from apex.options_pilot.risk_authority import CertifiedRiskAuthority
from apex.options_pilot.synthetic_harness import SyntheticHarness, T0

RB = ROBINHOOD_RHF_2026


def auth(s: FeeSchedule, **over) -> FeeAuthorization:
    """TEST-ONLY authorization matching `s` exactly. No authorization is authored into the product."""
    b = dict(schedule_id=s.schedule_id, version=s.version, source_document_sha256=s.source_document_sha256,
             terms_digest=s.terms_digest, computation_policy_digest=s.computation_digest,
             implementation_digest=s.implementation_digest, effective_date=s.effective_date,
             status=AUTHORIZED, authorized_by="TEST_ONLY_NOT_AN_OPERATOR",
             authorized_utc="2026-09-13T00:00:00Z", scope="test")
    b.update(over)
    return FeeAuthorization(**b)


def sched(**over) -> FeeSchedule:
    return FeeSchedule(**{**RB.__dict__, **over})


def authority_for(s: FeeSchedule) -> CertifiedRiskAuthority:
    return CertifiedRiskAuthority(fee_schedule=s, provenance="SYNTHETIC_FIXTURE")


# ================================================ F1: every consumer compares the WHOLE identity


class TestTheAuthorizationItselfIsCompared:
    """Scenarios 1-4. Two authorizations can match the schedule on every arithmetic field and still be different
    acts by different people with different scope. The identity must notice."""

    @pytest.mark.parametrize("differing,value", [
        ("authorized_by", "SOMEBODY_ELSE"),
        ("authorized_utc", "1999-01-01T00:00:00Z"),
        ("scope", "A DIFFERENT AND WIDER SCOPE"),
    ])
    def test_a_persisted_approval_is_refused_when_only_the_authorization_differs(self, differing, value):
        A = sched(authorization=auth(RB))
        B = sched(authorization=auth(RB, **{differing: value}))
        assert A.identity() != B.identity(), "the identity must distinguish them"
        ra = authority_for(B)
        problem = ra.accepts({"risk_provenance": "CERTIFIED_KERNEL", "authority_id": ra.authority_id,
                              "fee_identity": A.identity()})
        assert problem is not None and "authorization_digest" in problem
        assert ra.fee_identity_problem({"fees": A.identity()}) is not None

    def test_a_changed_authorization_digest_refuses(self):
        A = sched(authorization=auth(RB))
        tampered = dict(A.identity(), authorization_digest="0" * 64)
        ra = authority_for(A)
        assert "authorization_digest" in ra.accepts(
            {"risk_provenance": "CERTIFIED_KERNEL", "authority_id": ra.authority_id, "fee_identity": tampered})


class TestTheComparisonIsExactInBothDirections:
    """Scenarios 5-6."""

    @pytest.mark.parametrize("field", list(FeeSchedule.IDENTITY_FIELDS))
    def test_a_missing_identity_field_refuses_by_name(self, field):
        A = sched(authorization=auth(RB))
        partial = {k: v for k, v in A.identity().items() if k != field}
        p = identity_problem(A.identity(), partial, what="x")
        assert p is not None and "FEE_IDENTITY_INCOMPLETE" in p and field in p

    def test_an_extra_undeclared_identity_field_refuses(self):
        A = sched(authorization=auth(RB))
        p = identity_problem(A.identity(), dict(A.identity(), invented_field=1), what="x")
        assert p is not None and "UNDECLARED_FIELDS" in p and "invented_field" in p

    def test_a_non_dict_identity_refuses(self):
        assert "FEE_IDENTITY_MISSING" in identity_problem(sched().identity(), None, what="x")


class TestNoConsumerKeepsItsOwnFieldList:
    """THE STRUCTURAL GUARD. This is the defect family, not just this instance: a producer records the right
    information and a consumer quietly inspects a hand-written subset of it. A new partial comparison fails here."""

    PILOT = pathlib.Path(__file__).resolve().parents[1] / "apex/options_pilot"

    def test_no_module_hard_codes_a_fee_identity_field_tuple(self):
        offenders = []
        for f in sorted(self.PILOT.glob("*.py")):
            if f.name == "fees.py":
                continue                                  # fees.py DEFINES IDENTITY_FIELDS
            src = f.read_text()
            for node in ast.walk(ast.parse(src)):
                if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                    continue
                names = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                if len({"schedule_id", "schedule_hash", "terms_digest"} & names) >= 2:
                    offenders.append("%s: %s" % (f.name, sorted(names)))
        assert offenders == [], ("a consumer is comparing a hand-written fee-identity subset again; call "
                                 "fees.identity_problem() instead: %s" % offenders)

    def test_every_identity_key_is_declared(self):
        assert set(sched().identity()) == set(FeeSchedule.IDENTITY_FIELDS)

    def test_the_authority_and_the_boundary_both_use_the_shared_comparison(self):
        for name in ("risk_authority.py", "boundary.py"):
            assert "identity_problem(" in (self.PILOT / name).read_text(), name


# ================================================ F2: the digest binds the computation, not a description


class TestTheComputationIsActuallyBound:
    """Scenarios 7-8."""

    def test_7_changing_the_fee_ARITHMETIC_changes_the_implementation_digest(self):
        """The F2 reproduction: a subclass overriding `_side` changed the charge 0.06 -> 0.05 while the old
        label-based digest stayed byte-identical."""
        class ArithmeticChanged(FeeSchedule):
            def _side(self, contracts, side, *, sale_principal=None):
                out = FeeSchedule._side(self, contracts, side, sale_principal=sale_principal)
                if out.get("total") is not None and side == "SELL" and sale_principal:
                    sec = Decimal(str(sale_principal)) * Decimal("20.60") / Decimal("1000000")
                    out["components"]["regulatory"] = float(sec.quantize(Decimal("0.01"), rounding=ROUND_FLOOR))
                    out["total"] = round(sum(out["components"].values()), 2)
                return out

        honest = sched(provenance="SYNTHETIC_FIXTURE")
        changed = ArithmeticChanged(**{**RB.__dict__, "provenance": "SYNTHETIC_FIXTURE"})
        assert honest.exit(1, sale_principal=540.0)["total"] == 0.06
        assert changed.exit(1, sale_principal=540.0)["total"] == 0.05      # the CHARGE really changed
        assert honest.implementation_digest != changed.implementation_digest

    def test_8_changing_a_POLICY_rounding_rule_changes_the_computation_policy_digest(self):
        down = FeeComputationPolicy(**{**SALE_PRINCIPAL_POLICY_V1.__dict__, "sec_rounding": "DOWN"})
        honest, changed = sched(provenance="SYNTHETIC_FIXTURE"), sched(provenance="SYNTHETIC_FIXTURE",
                                                                      computation_policy=down)
        assert honest.exit(1, sale_principal=540.0)["total"] == 0.06
        assert changed.exit(1, sale_principal=540.0)["total"] == 0.05
        assert honest.computation_digest != changed.computation_digest

    def test_component_ordering_is_part_of_the_policy_digest(self):
        reordered = FeeComputationPolicy(**{**SALE_PRINCIPAL_POLICY_V1.__dict__,
                                            "component_order": ("regulatory", "exchange", "commission")})
        assert reordered.digest != SALE_PRINCIPAL_POLICY_V1.digest

    def test_the_arithmetic_EXECUTES_from_the_policy_not_from_literals(self):
        """If `_side` still used its own constants, changing the policy would not change the charge."""
        nearest = FeeComputationPolicy(**{**SALE_PRINCIPAL_POLICY_V1.__dict__, "sec_rounding": "NEAREST"})
        s = sched(provenance="SYNTHETIC_FIXTURE", computation_policy=nearest)
        assert s.exit(1, sale_principal=540.0)["total"] == 0.05          # 0.011124 -> 0.01 nearest, not 0.02 up
        assert s.exit(1, sale_principal=540.0)["computation_policy"]["sec_rounding"] == "NEAREST"

    def test_the_implementation_digest_is_independently_recomputable(self):
        """Recomputed here from the AST rather than trusting the property."""
        assert sched().implementation_digest == implementation_digest_of(FeeSchedule)
        assert len(sched().implementation_digest) == 64

    def test_unreadable_source_fails_closed_rather_than_raising_or_matching(self):
        class NoSource(FeeSchedule):
            pass
        NoSource._side = type(lambda: 0)(compile("def _side(self,*a,**k): return {}", "<none>", "exec")
                                         .co_consts[0], {})
        d = implementation_digest_of(NoSource)
        assert d.startswith("UNVERIFIABLE_IMPLEMENTATION"), d
        assert d != implementation_digest_of(FeeSchedule), "an unverifiable build can never match an authorization"

    def test_an_authorization_bound_to_the_old_policy_no_longer_matches(self):
        old = sched(sale_principal_rate_per_million=None)
        stale = auth(RB, computation_policy_digest=old.computation_digest)
        st = sched(authorization=stale).authorization_state()
        assert st["status"] == AUTHORIZATION_MISMATCH and st["basis"] == "computation_policy_digest"

    def test_an_authorization_bound_to_different_code_no_longer_matches(self):
        stale = auth(RB, implementation_digest="0" * 64)
        st = sched(authorization=stale).authorization_state()
        assert st["status"] == AUTHORIZATION_MISMATCH and st["basis"] == "implementation_digest"


# ================================================ 9 and 10: the end-to-end bookends


class TestTheBookends:
    def test_9_a_superseded_authorization_refuses_before_any_quote(self):
        asked = []

        class CountingQuotes:
            def __call__(self, *a, **k):
                asked.append(1)
                raise AssertionError("a quote was requested under a superseded authorization")

        stale = auth(RB, version="2026-09-12")
        with pytest.raises(Exception) as ei:
            d = pathlib.Path(tempfile.mkdtemp())
            h = SyntheticHarness(d / "l.jsonl", session_id="R1", t0=T0, risk="certified",
                                 fee_schedule=sched(authorization=stale))
            h.quotes = CountingQuotes()
            S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        assert "BOUNDARY_REFUSES_UNAUTHORIZED_FEE_SCHEDULE" in str(ei.value)
        assert asked == []

    def test_10_CONTROL_an_exact_authorization_completes_the_lifecycle(self):
        """Every refusal above is the check working, not a broken build."""
        s = sched(authorization=auth(RB))
        assert s.authorized and s.usable
        d = pathlib.Path(tempfile.mkdtemp())
        h = SyntheticHarness(d / "l.jsonl", session_id="R1OK", t0=T0, risk="certified", fee_schedule=s)
        out = S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        rows = L.read_all(h.bd.ledger)
        assert out["decision"] == "TRADE"
        assert len([r for r in rows if r["kind"] == "pilot_fill"]) == 1
        sealed = [r for r in rows if r["kind"] == "pilot_intent"][0]["fees"]
        assert set(sealed) == set(FeeSchedule.IDENTITY_FIELDS)
        assert sealed["authorization_status"] == AUTHORIZED

    def test_the_robinhood_arithmetic_is_unchanged_by_this_repair(self):
        s = sched(provenance="SYNTHETIC_FIXTURE")
        assert s.entry(1)["total"] == 0.04
        x = s.exit(1, sale_principal=540.0)
        assert x["total"] == 0.06 and x["component_basis"]["sec_component"] == 0.02
        assert x["component_basis"]["cat"] == 0.0 and x["component_basis"]["taf"] == 0.0
