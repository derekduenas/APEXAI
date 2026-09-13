"""FEE-AUTHORIZATION-002-R2 — the computation binding made transitive, and the last two consumers closed.

R1 bound `_side`/`entry`/`exit` and the declared policy. Review found the binding stopped one level too early and
two consumers were still short:

  F1  `_side()` resolved its rounding through the module-level mutable dict `ROUND_MODES`, which was in NEITHER
      digest. `ROUND_MODES["UP"] = ROUND_FLOOR` -- one assignment, no source file touched -- moved the charge from
      0.06 to 0.05 with both digests byte-identical. The original defect, one level down.
  F2  `sec_basis` was recorded and digested but `_side()` dispatched on `sale_principal_rate_per_million`, so the
      digest attested a basis the code never consulted. `sec_basis="NONSENSE"` constructed happily, as did
      `arithmetic="FLOATS"` and `component_order=("commission","commission")`.
  F3  `recompute_fees` compared schedule_id, schedule_hash and the total. Two schedules with identical TERMS but
      different OPERATOR AUTHORIZATIONS share a schedule_hash and produce the same number, so an outcome written
      under one authorization reconciled clean under another.
  F4  `UNVERIFIABLE_IMPLEMENTATION:...` was accepted as an `implementation_digest`, so an authorization carrying
      the sentinel AUTHORIZED precisely the build the sentinel exists to refuse.

Reproductions: docs/evidence/fee_authorization_002/R2_FINDING_REPRODUCTION_before_repair.txt"""
from __future__ import annotations

import ast
import pathlib
import tempfile
from decimal import ROUND_FLOOR

import pytest

from apex.options_pilot import fees as F
from apex.options_pilot import ledger as L
from apex.options_pilot import session as S
from apex.options_pilot.fees import (AUTHORIZED, FeeAuthorization, FeeAuthorizationRefused, FeeComputationPolicy,
                                     FeePolicyRefused, FeeSchedule, NOT_AUTHORIZED, ROBINHOOD_RHF_2026,
                                     SALE_PRINCIPAL_POLICY_V1, identity_problem, is_digest, recompute_fees)
from apex.options_pilot import fee_computation as FC
from apex.options_pilot.fee_computation import FeeComputationRefused, module_digest
from apex.options_pilot.synthetic_harness import SyntheticHarness, T0

RB = ROBINHOOD_RHF_2026
FEES_PY = pathlib.Path(F.__file__)
PILOT = FEES_PY.parent


def sched(**over) -> FeeSchedule:
    return FeeSchedule(**{**RB.__dict__, **over})


def synth(**over) -> FeeSchedule:
    return sched(provenance="SYNTHETIC_FIXTURE", **over)


def auth(s: FeeSchedule, **over) -> FeeAuthorization:
    b = dict(schedule_id=s.schedule_id, version=s.version, source_document_sha256=s.source_document_sha256,
             terms_digest=s.terms_digest, computation_policy_digest=s.computation_digest,
             implementation_digest=s.implementation_digest, effective_date=s.effective_date, status=AUTHORIZED,
             authorized_by="TEST_ONLY_NOT_AN_OPERATOR", authorized_utc="2026-09-13T00:00:00Z", scope="test")
    b.update(over)
    return FeeAuthorization(**b)


# ===================================================== F1: nothing the arithmetic resolves through is unbound


class TestNoMutableDispatchInTheComputationPath:
    def test_the_module_level_rounding_table_is_gone(self):
        assert not hasattr(F, "ROUND_MODES") and not hasattr(FC, "ROUND_MODES")

    def test_the_rounding_mapping_is_inside_the_digested_module(self):
        """SUPERSEDED BY R3: `mode` is no longer named in an allowlist -- it lives in the computation module,
        which is digested whole."""
        blob = FC.canonical_module_ast()
        for name in ("ROUND_CEILING", "ROUND_HALF_UP", "ROUND_FLOOR"):
            assert name in blob

    def test_a_policy_subclass_is_refused_outright(self):
        """SUPERSEDED BY R3, and closed more strongly. Under R2 a policy subclass overriding `mode` changed the
        digest; under R3 the digest covers a MODULE, so a subclass defined elsewhere would be outside it. Rather
        than chase that, `compute_side` refuses any policy that is not exactly FeeComputationPolicy."""
        class SneakyPolicy(FeeComputationPolicy):
            def mode(self, which):
                return ROUND_FLOOR if which == "sec_rounding" else FeeComputationPolicy.mode(self, which)

        s = synth(computation_policy=SneakyPolicy(**SALE_PRINCIPAL_POLICY_V1.__dict__))
        with pytest.raises(FeePolicyRefused, match="POLICY_NOT_CANONICAL"):
            s.exit(1, sale_principal=540.0)

    def test_STRUCTURAL_the_fee_computation_reads_no_module_level_mutable_container(self):
        """THE GUARD. A future edit that reintroduces a rebindable table feeding the arithmetic fails here."""
        tree = ast.parse(pathlib.Path(FC.__file__).read_text())
        mutable = set()
        for node in tree.body:                                   # module level only
            if not isinstance(node, ast.Assign):
                continue
            v = node.value
            is_mutable = isinstance(v, (ast.Dict, ast.List, ast.Set)) or (
                isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id in ("dict", "list", "set"))
            if is_mutable:
                mutable.update(t.id for t in node.targets if isinstance(t, ast.Name))
        read_by_fee_code = set()
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            read_by_fee_code.update(n.id for n in ast.walk(fn)
                                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load))
        offenders = sorted(mutable & read_by_fee_code)
        assert offenders == [], ("fee calculation reads module-level MUTABLE state %s; it can be rebound at "
                                 "runtime without changing any digest" % offenders)


# ===================================================== F2: every policy field controls execution


class TestThePolicyControlsExecutionOrDoesNotExist:
    def test_a_schedule_may_not_declare_one_basis_and_carry_the_other_terms(self):
        lying = FeeComputationPolicy(**{**SALE_PRINCIPAL_POLICY_V1.__dict__, "sec_basis": "PER_CONTRACT_CONSTANT"})
        with pytest.raises(FeePolicyRefused, match="SEC_BASIS_INCONSISTENT"):
            synth(computation_policy=lying)

    def test_a_sale_principal_basis_requires_a_rate_and_declared_components(self):
        pol = SALE_PRINCIPAL_POLICY_V1
        with pytest.raises(FeePolicyRefused, match="SEC_BASIS_INCONSISTENT"):
            synth(computation_policy=pol, sale_principal_rate_per_million=None)
        with pytest.raises(FeePolicyRefused, match="SEC_BASIS_INCONSISTENT"):
            synth(computation_policy=pol, cat_per_contract=None)

    def test_side_dispatches_on_the_declared_basis(self):
        per = FeeComputationPolicy(**{**SALE_PRINCIPAL_POLICY_V1.__dict__, "sec_basis": "PER_CONTRACT_CONSTANT"})
        s = synth(sale_principal_rate_per_million=None, computation_policy=per)
        out = s.exit(1, sale_principal=540.0)
        assert "sec_component" not in (out.get("component_basis") or {}), "the per-contract branch must execute"
        assert out["total"] == 0.07

    @pytest.mark.parametrize("field,value", [
        ("sec_basis", "NONSENSE"), ("regulatory_sum", "ANYTHING"), ("arithmetic", "FLOATS"),
        ("sec_rounding", "SIDEWAYS"), ("cat_sub_cent_to_zero", "yes"),
        ("component_order", ("commission", "commission")),
        ("component_order", ("commission", "exchange")),
        ("component_order", ("commission", "exchange", "regulatory", "invented")),
    ])
    def test_an_unsupported_policy_value_refuses_at_construction(self, field, value):
        with pytest.raises((FeePolicyRefused, FeeComputationRefused)):
            FeeComputationPolicy(**{**SALE_PRINCIPAL_POLICY_V1.__dict__, field: value})

    def test_every_policy_field_appears_in_its_digest(self):
        d = SALE_PRINCIPAL_POLICY_V1.describe()
        assert set(d) == {f for f in SALE_PRINCIPAL_POLICY_V1.__dataclass_fields__}


# ===================================================== F3: the Book compares identity, not just the number


class TestBookRecomputationComparesTheCompleteIdentity:
    def test_a_record_written_under_one_authorization_does_not_reconcile_under_another(self):
        A = synth(authorization=auth(RB))
        B = synth(authorization=auth(RB, authorized_by="SOMEBODY_ELSE", scope="WIDER"))
        rec = A.exit(1, sale_principal=540.0)
        assert A.schedule_hash == B.schedule_hash and rec["total"] == B.exit(1, sale_principal=540.0)["total"]
        problems = recompute_fees(rec, B, contracts=1, side="SELL")
        assert problems and "FEE_IDENTITY_INTEGRITY" in problems[0]

    def test_the_same_authorization_reconciles_clean(self):
        A = synth(authorization=auth(RB))
        assert recompute_fees(A.exit(1, sale_principal=540.0), A, contracts=1, side="SELL") == []

    @pytest.mark.parametrize("field", ["authorization_digest", "implementation_digest",
                                       "computation_policy_digest", "source_document_sha256"])
    def test_a_tampered_identity_field_is_an_integrity_problem(self, field):
        A = synth(authorization=auth(RB))
        rec = dict(A.exit(1, sale_principal=540.0))
        rec["fee_identity"] = dict(rec["fee_identity"], **{field: "0" * 64})
        assert any("FEE_IDENTITY_INTEGRITY" in p for p in recompute_fees(rec, A, contracts=1, side="SELL"))

    def test_a_missing_or_extra_identity_field_is_an_integrity_problem(self):
        A = synth(authorization=auth(RB))
        rec = dict(A.exit(1, sale_principal=540.0))
        short = dict(rec, fee_identity={k: v for k, v in rec["fee_identity"].items() if k != "terms_digest"})
        assert any("FEE_IDENTITY_INTEGRITY" in p for p in recompute_fees(short, A, contracts=1, side="SELL"))
        wide = dict(rec, fee_identity=dict(rec["fee_identity"], invented=1))
        assert any("FEE_IDENTITY_INTEGRITY" in p for p in recompute_fees(wide, A, contracts=1, side="SELL"))


# ===================================================== F4: a sentinel is not a digest


class TestAnUnverifiableImplementationCannotBeAuthorized:
    @staticmethod
    def _no_source_cls():
        class NoSource(FeeSchedule):
            pass
        NoSource._side = type(lambda: 0)(compile("def _side(self,*a,**k): return {}", "<none>", "exec").co_consts[0], {})
        return NoSource

    def test_digest_fields_must_be_64_lowercase_hex(self):
        assert is_digest("a" * 64) and not is_digest("A" * 64)
        assert not is_digest("a" * 63) and not is_digest("UNVERIFIABLE_IMPLEMENTATION: x") and not is_digest(None)

    @pytest.mark.parametrize("field", ["source_document_sha256", "terms_digest",
                                       "computation_policy_digest", "implementation_digest"])
    def test_an_authorization_carrying_a_non_digest_refuses_at_construction(self, field):
        with pytest.raises(FeeAuthorizationRefused, match="AUTHORIZATION_DIGEST_MALFORMED"):
            auth(RB, **{field: "UNVERIFIABLE_IMPLEMENTATION: source unavailable"})

    def test_the_sentinel_specifically_cannot_be_authorized(self):
        sentinel = "UNVERIFIABLE_IMPLEMENTATION: SOURCE_UNAVAILABLE for the fee computation module"
        assert sentinel.startswith("UNVERIFIABLE_IMPLEMENTATION")
        with pytest.raises(FeeAuthorizationRefused):
            auth(RB, implementation_digest=sentinel)

    def test_an_unverifiable_build_refuses_independently_of_any_authorization(self):
        """Checked BEFORE the supplied authorization is examined, so no payload can match its way past."""
        st = self._no_source_cls()(**{**RB.__dict__, "authorization": auth(RB)}).authorization_state()
        assert st["status"] == NOT_AUTHORIZED and st["basis"] == "IMPLEMENTATION_UNVERIFIABLE"
        assert "cannot be verified cannot be authorized" in st["why"]

    def test_it_is_a_named_refusal_and_never_an_exception(self):
        """The sourceless class necessarily replaces `_side` -- that is what makes it sourceless -- so its
        `entry()` is a stub and proves nothing. What matters is asserted directly: the state is computed, named,
        and returned rather than raised, and the schedule is unusable."""
        s = self._no_source_cls()(**{**RB.__dict__, "authorization": auth(RB)})
        st = s.authorization_state()                              # returns; does not raise
        assert isinstance(st, dict) and st["status"] == NOT_AUTHORIZED
        assert s.authorized is False and s.usable is False
        with pytest.raises(FeeAuthorizationRefused, match="FEE_SCHEDULE_NOT_AUTHORIZED"):
            s.assert_usable(what="charge")                        # named refusal, not an arbitrary exception


# ===================================================== the acceptance list


class TestAcceptance:
    def test_1_the_exact_authorization_control_still_charges_004_and_006(self):
        s = sched(authorization=auth(RB))
        assert s.usable
        d = pathlib.Path(tempfile.mkdtemp())
        h = SyntheticHarness(d / "l.jsonl", session_id="R2", t0=T0, risk="certified", fee_schedule=s)
        out = S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        assert out["decision"] == "TRADE"
        assert len([r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_fill"]) == 1
        t = synth()
        assert t.entry(1)["total"] == 0.04 and t.exit(1, sale_principal=540.0)["total"] == 0.06

    def test_4_and_5_every_fee_identity_consumer_uses_the_canonical_comparison(self):
        offenders = []
        for f in sorted(PILOT.glob("*.py")):
            if f.name == "fees.py":
                continue
            for node in ast.walk(ast.parse(f.read_text())):
                if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                    continue
                names = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                if len({"schedule_id", "schedule_hash", "terms_digest"} & names) >= 2:
                    offenders.append("%s: %s" % (f.name, sorted(names)))
        assert offenders == []

    def test_6_an_unverifiable_schedule_requests_no_quote(self):
        asked = []

        class CountingQuotes:
            def __call__(self, *a, **k):
                asked.append(1)
                raise AssertionError("a quote was requested for an unverifiable schedule")

        NoSource = TestAnUnverifiableImplementationCannotBeAuthorized._no_source_cls()
        with pytest.raises(FeeAuthorizationRefused):
            d = pathlib.Path(tempfile.mkdtemp())
            h = SyntheticHarness(d / "l.jsonl", session_id="R2Q", t0=T0, risk="certified",
                                 fee_schedule=NoSource(**{**RB.__dict__, "authorization": auth(RB)}))
            h.quotes = CountingQuotes()
            S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        assert asked == []

    def test_the_shipped_candidate_remains_unauthorized(self):
        assert RB.authorization is None and RB.usable is False
