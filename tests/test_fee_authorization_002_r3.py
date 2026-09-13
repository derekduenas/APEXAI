"""FEE-AUTHORIZATION-002-R3 — identity closure and computation closure.

Two holes, both the same recurring failure: a verifier inspects less than it claims.

  F1  `risk_gate.verify_approval` iterated FEE_IDENTITY_FIELDS with `a_id.get(k, "__ABSENT__")`. That proves the
      NAMED fields match and says nothing about an UNDECLARED field on the approval -- a consumer walking the
      declared fields cannot see an extra one. Other checks sometimes refused such a record anyway; a verifier
      that is only accidentally correct is not one.

  F2  `implementation_digest` hashed four hand-picked functions. Reproduced with two ORDINARY COMMITS (no
      monkeypatching): refactor the SEC component into a helper, then edit only that helper -- charge 0.06 -> 0.05,
      digest unchanged. See docs/evidence/fee_authorization_002/R3_FINDING_REPRODUCTION_before_repair.txt.

THE CLOSURES. One mapping comparator with exact key equality on both sides, used by every consumer. All executable
arithmetic in apex/options_pilot/fee_computation.py, digested as a whole module, with its dependency set proved
closed here and non-canonical policy/schedule classes refused outright."""
from __future__ import annotations

import ast
import hashlib
import pathlib
import tempfile

import pytest

from apex.options_pilot import fee_computation as FC
from apex.options_pilot import fees as F
from apex.options_pilot import ledger as L
from apex.options_pilot import risk_gate as RG
from apex.options_pilot import session as S
from apex.options_pilot.fees import (AUTHORIZED, FeeAuthorization, FeeAuthorizationRefused, FeePolicyRefused,
                                     FeeSchedule, ROBINHOOD_RHF_2026, identity_disagreement, identity_problem)
from apex.options_pilot.risk_authority import CertifiedRiskAuthority
from apex.options_pilot.risk_gate import RiskRefused
from apex.options_pilot.synthetic_harness import SyntheticHarness, T0

RB = ROBINHOOD_RHF_2026
FC_PY = pathlib.Path(FC.__file__)
PILOT = FC_PY.parent


def synth(**o):
    return FeeSchedule(**{**RB.__dict__, "provenance": "SYNTHETIC_FIXTURE", **o})


def auth(s, **o):
    b = dict(schedule_id=s.schedule_id, version=s.version, source_document_sha256=s.source_document_sha256,
             terms_digest=s.terms_digest, computation_policy_digest=s.computation_digest,
             implementation_digest=s.implementation_digest, effective_date=s.effective_date, status=AUTHORIZED,
             authorized_by="TEST_ONLY_NOT_AN_OPERATOR", authorized_utc="2026-09-13T00:00:00Z", scope="test")
    b.update(o)
    return FeeAuthorization(**b)


def digest_of_source(src: str) -> str:
    """The same canonicalization the product uses, applied to arbitrary source text -- so a mutation can be
    digested WITHOUT writing to the repository."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body.pop(0)
    return hashlib.sha256(ast.dump(tree, annotate_fields=True, include_attributes=False).encode()).hexdigest()


# ============================================== F1: one comparator, exact both ways, at every consumer


def canonical_intent(s: FeeSchedule) -> dict:
    return {"expression": "LONG_CALL", "contract": {"expiration": "2026-10-09", "strike": 650.0, "right": "CALL"},
            "quantity": 1, "action": "BUY", "session_id": "S", "scan_id": "S:1", "intent_id": "I1",
            "contract_id": "SPY|2026-10-09|650.0|CALL", "forecast_id": "F1",
            "signal_used": "LONG", "fees": s.identity(),
            "risk_envelope": {"max_loss": 250.0, "reference_ask": 2.50, "max_entry_price": 2.50,
                              "envelope_debit": 250.0}}


def approval_for(intent: dict, s: FeeSchedule, *, fee_identity=None) -> dict:
    return {"approved": True, "risk_provenance": "CERTIFIED_KERNEL", "authority_id": "AUTH-1",
            "binding_hash": RG.binding_hash(RG._binding_view(intent)),
            "envelope_binding_hash": RG.envelope_binding_hash(intent),
            "certified_max_loss": 250.0,
            "fee_identity": fee_identity if fee_identity is not None else s.identity()}


class TestVerifyApprovalIsAnExactIdentityVerifier:
    """Cases A-E from review, exercised on verify_approval DIRECTLY."""

    def test_control_a_clean_approval_verifies(self):
        s = synth(authorization=auth(RB))
        i = canonical_intent(s)
        assert RG.verify_approval(i, approval_for(i, s)) is not None

    def test_A_an_undeclared_extra_on_the_APPROVAL_identity_refuses(self):
        """THE FINDING. The old loop could not see this field at all."""
        s = synth(authorization=auth(RB))
        i = canonical_intent(s)
        a = approval_for(i, s, fee_identity=dict(s.identity(), smuggled="x"))
        with pytest.raises(RiskRefused, match="UNDECLARED_FIELDS"):
            RG.verify_approval(i, a)

    def test_B_an_undeclared_extra_on_the_INTENT_identity_refuses(self):
        s = synth(authorization=auth(RB))
        i = canonical_intent(s)
        a = approval_for(i, s)
        i2 = dict(i, fees=dict(s.identity(), smuggled="x"))
        with pytest.raises(RiskRefused):
            RG.verify_approval(i2, a)

    def test_C_the_same_undeclared_field_on_BOTH_refuses(self):
        """Equal values must not excuse an undeclared field: it is still not an identity this code understands."""
        s = synth(authorization=auth(RB))
        i = canonical_intent(s)
        i2 = dict(i, fees=dict(s.identity(), smuggled="x"))
        a = approval_for(i2, s, fee_identity=dict(s.identity(), smuggled="x"))
        with pytest.raises(RiskRefused, match="UNDECLARED_FIELDS"):
            RG.verify_approval(i2, a)

    def test_D_a_missing_canonical_field_refuses(self):
        s = synth(authorization=auth(RB))
        i = canonical_intent(s)
        short = {k: v for k, v in s.identity().items() if k != "authorization_digest"}
        with pytest.raises(RiskRefused, match="INCOMPLETE"):
            RG.verify_approval(i, approval_for(i, s, fee_identity=short))

    def test_E_an_altered_canonical_field_refuses_and_names_it(self):
        s = synth(authorization=auth(RB))
        i = canonical_intent(s)
        bad = dict(s.identity(), terms_digest="0" * 64)
        with pytest.raises(RiskRefused, match="terms_digest"):
            RG.verify_approval(i, approval_for(i, s, fee_identity=bad))

    @pytest.mark.parametrize("with_authority", [False, True])
    def test_the_refusal_does_not_depend_on_an_active_authority_being_passed(self, with_authority):
        s = synth(authorization=auth(RB))
        i = canonical_intent(s)
        a = approval_for(i, s, fee_identity=dict(s.identity(), smuggled="x"))
        authority = CertifiedRiskAuthority(fee_schedule=s, provenance="SYNTHETIC_FIXTURE") if with_authority else None
        with pytest.raises(RiskRefused):
            RG.verify_approval(i, a, authority=authority)


class TestOneComparatorEverywhere:
    def test_the_comparator_names_the_side_and_the_field(self):
        s = synth(authorization=auth(RB))
        msg = identity_disagreement(dict(s.identity(), terms_digest="0" * 64), s.identity(),
                                    left_name="LEFTOBJ", right_name="RIGHTOBJ")
        assert "LEFTOBJ" in msg and "RIGHTOBJ" in msg and "terms_digest" in msg

    @pytest.mark.parametrize("side", ["left", "right"])
    def test_an_extra_refuses_on_either_side(self, side):
        s = synth(authorization=auth(RB))
        a, b = s.identity(), s.identity()
        if side == "left":
            a = dict(a, extra=1)
        else:
            b = dict(b, extra=1)
        assert "UNDECLARED_FIELDS" in identity_disagreement(a, b, left_name="L", right_name="R")

    def test_identity_problem_is_a_thin_form_of_the_same_comparator(self):
        s = synth(authorization=auth(RB))
        assert identity_problem(s.identity(), dict(s.identity(), extra=1), what="X") is not None

    def test_STRUCTURAL_no_consumer_iterates_the_identity_fields_itself(self):
        """A consumer that loops the declared fields cannot see an undeclared one. Only the shared comparator may."""
        offenders = []
        for f in sorted(PILOT.glob("*.py")):
            if f.name == "fees.py":
                continue
            for node in ast.walk(ast.parse(f.read_text())):
                if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) \
                        and "IDENTITY_FIELDS" in node.iter.id:
                    offenders.append("%s: for %s" % (f.name, node.iter.id))
                if isinstance(node, ast.For) and isinstance(node.iter, ast.Attribute) \
                        and "IDENTITY_FIELDS" in node.iter.attr:
                    offenders.append("%s: for ...%s" % (f.name, node.iter.attr))
        assert offenders == [], offenders


# ============================================== F2: the computation module is a closure


class TestTheComputationModuleIsClosed:
    def test_the_digest_is_over_the_whole_module(self):
        assert synth().implementation_digest == FC.module_digest()
        assert FC.module_digest() == hashlib.sha256(FC.canonical_module_ast().encode()).hexdigest()

    def test_changing_a_TRANSITIVE_HELPER_changes_the_digest(self):
        """The R3 reproduction, digested without touching the repository: the helper edit that previously left the
        digest identical now changes it, because the digest covers the module rather than a list of functions."""
        src = FC_PY.read_text()
        mutated = src.replace('rounding=policy.mode("sec_rounding")', "rounding=ROUND_FLOOR")
        assert mutated != src
        assert digest_of_source(mutated) != digest_of_source(src) == FC.module_digest()

    def test_adding_a_new_helper_changes_the_digest(self):
        src = FC_PY.read_text()
        mutated = src + "\n\ndef _a_new_helper(x):\n    return x\n"
        assert digest_of_source(mutated) != digest_of_source(src)

    def test_changing_only_comments_docstrings_or_blank_lines_does_not(self):
        """The declared behaviour: reformatting is not a computation change."""
        src = FC_PY.read_text()
        same = src.replace('"""HOW the rates are applied -- declared once, and EXECUTED FROM.',
                           '"""COMPLETELY DIFFERENT DOCSTRING TEXT.') + "\n# a trailing comment\n\n\n"
        assert digest_of_source(same) == digest_of_source(src)

    def test_STRUCTURAL_the_dependency_set_is_closed(self):
        """Every free name the computation uses resolves inside the module or to the declared externals. A new
        unresolved global dependency fails here -- which is what makes the module digest a closure."""
        import builtins
        tree = ast.parse(FC_PY.read_text())
        defined = set(FC.EXTERNAL_DEPENDENCIES) | set(dir(builtins))
        for n in tree.body:
            if isinstance(n, ast.Assign):
                defined.update(t.id for t in n.targets if isinstance(t, ast.Name))
            elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                defined.add(n.name)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                defined.update((a.asname or a.name).split(".")[0] for a in n.names)
        # a function nested inside another legitimately reads its enclosing scope, so analyse only OUTERMOST
        # functions; ast.walk from them already covers every nested binding
        nested = set()
        for outer in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            for sub in ast.walk(outer):
                if isinstance(sub, ast.FunctionDef) and sub is not outer:
                    nested.add(id(sub))
        unresolved = set()
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and id(n) not in nested):
            # every binding visible inside this function, including nested defs, args, except-names and comprehensions
            local = set()
            for sub in ast.walk(fn):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    a = sub.args
                    local.update(x.arg for x in list(a.args) + list(a.kwonlyargs) + list(a.posonlyargs))
                    if a.vararg:
                        local.add(a.vararg.arg)
                    if a.kwarg:
                        local.add(a.kwarg.arg)
                    if isinstance(sub, ast.FunctionDef):
                        local.add(sub.name)
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    local.add(sub.id)
                if isinstance(sub, ast.ExceptHandler) and sub.name:
                    local.add(sub.name)
            for sub in ast.walk(fn):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) \
                        and sub.id not in defined and sub.id not in local:
                    unresolved.add(sub.id)
        assert unresolved == set(), ("the fee computation reaches names outside its closure: %s -- add them to "
                                     "the module or to EXTERNAL_DEPENDENCIES deliberately" % sorted(unresolved))

    def test_the_module_contains_no_authorization_data(self):
        """SUPERSEDED BY R3.1 and made precise. The runtime now CALLS the gate and REPORTS its verdict, so the
        strings `authorization_status` and `identity()` legitimately appear. What must never appear is an
        authorization PAYLOAD -- that is what would make the digest circular."""
        src = FC_PY.read_text()
        for forbidden in ("class FeeAuthorization", "authorized_by", "authorized_utc", "source_document_sha256"):
            assert forbidden not in src, forbidden

    def test_the_gate_performs_no_arithmetic(self):
        """All numeric work must be on the digested side."""
        tree = ast.parse(pathlib.Path(F.__file__).read_text())
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "FeeSchedule"):
            for fn in (m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in ("_side", "entry", "exit")):
                names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
                assert "Decimal" not in names, "%s performs arithmetic outside the digested module" % fn.name

    def test_a_non_canonical_policy_or_schedule_class_is_unverifiable_or_refused(self):
        class P(FC.FeeComputationPolicy):
            pass
        with pytest.raises(FC.FeeComputationRefused, match="POLICY_NOT_CANONICAL"):
            synth(computation_policy=P(**FC.SALE_PRINCIPAL_POLICY_V1.__dict__)).exit(1, sale_principal=540.0)

        class Sub(FeeSchedule):
            pass
        assert Sub(**{**RB.__dict__}).implementation_digest.startswith("UNVERIFIABLE_IMPLEMENTATION")

    def test_authorization_data_does_not_change_the_implementation_digest(self):
        a = synth(authorization=auth(RB)).implementation_digest
        b = synth(authorization=auth(RB, authorized_by="SOMEONE", scope="OTHER")).implementation_digest
        assert a == b == FC.module_digest()

    @pytest.mark.parametrize("field", ["sec_rounding", "cat_rounding", "taf_rounding",
                                       "commission_rounding", "exchange_rounding"])
    def test_every_rounding_mode_is_executable_and_changes_the_charge_or_is_a_no_op_by_value(self, field):
        """Each declared rounding mode must reach the arithmetic. Changing it either moves a charge or provably
        cannot for these particular rates -- never silently ignored."""
        base = synth()
        b_entry, b_exit = base.entry(1)["total"], base.exit(1, sale_principal=540.0)["total"]
        changed = synth(computation_policy=FC.FeeComputationPolicy(
            **{**FC.SALE_PRINCIPAL_POLICY_V1.__dict__, field: "DOWN"}))
        c_entry, c_exit = changed.entry(1)["total"], changed.exit(1, sale_principal=540.0)["total"]
        assert changed.computation_digest != base.computation_digest         # always visible in the identity
        moved = (b_entry, b_exit) != (c_entry, c_exit)
        rr = changed.exit(1, sale_principal=540.0)["rounding_rules"]
        assert moved or any("DOWN" in str(v) for v in rr.values()), \
            "%s must reach the arithmetic; it changed neither a charge nor a recorded rounding decision" % field


# ============================================== acceptance


class TestAcceptance:
    def test_entry_004_and_exit_006_unchanged(self):
        t = synth()
        assert t.entry(1)["total"] == 0.04 and t.exit(1, sale_principal=540.0)["total"] == 0.06

    def test_the_exact_control_reaches_TRADE_through_the_real_session_path(self):
        s = FeeSchedule(**{**RB.__dict__, "authorization": auth(RB)})
        assert s.usable
        d = pathlib.Path(tempfile.mkdtemp())
        h = SyntheticHarness(d / "l.jsonl", session_id="R3", t0=T0, risk="certified", fee_schedule=s)
        out = S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        assert out["decision"] == "TRADE"
        assert len([r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_fill"]) == 1

    def test_an_unauthorized_schedule_requests_no_quote(self):
        asked = []

        class CountingQuotes:
            def __call__(self, *a, **k):
                asked.append(1)
                raise AssertionError("a quote was requested")

        with pytest.raises(FeeAuthorizationRefused):
            d = pathlib.Path(tempfile.mkdtemp())
            h = SyntheticHarness(d / "l.jsonl", session_id="R3Q", t0=T0, risk="certified", fee_schedule=RB)
            h.quotes = CountingQuotes()
            S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        assert asked == []

    def test_an_unverifiable_computation_module_is_unauthorizable(self, monkeypatch):
        monkeypatch.setattr(FC.inspect, "getsource", lambda *a, **k: (_ for _ in ()).throw(OSError("no source")))
        assert FC.module_digest().startswith("UNVERIFIABLE_IMPLEMENTATION")
        with pytest.raises(FeeAuthorizationRefused, match="DIGEST_MALFORMED"):
            auth(RB, implementation_digest=FC.module_digest())
        st = FeeSchedule(**{**RB.__dict__}).authorization_state()
        assert st["basis"] == "IMPLEMENTATION_UNVERIFIABLE"

    def test_the_shipped_candidate_is_still_unauthorized(self):
        assert RB.authorization is None and RB.usable is False
