"""FEE-AUTHORIZATION-002-R3.1 — the PUBLIC execution surface, closed.

R3 digested `fee_computation.py` and left the public path outside it:

    FeeSchedule.entry / FeeSchedule.exit -> FeeSchedule._side -> fee_computation

A wrapper needs no arithmetic to change a fee. It can change which side, quantity, principal, policy or component
set the arithmetic is asked for. Reproduced with five ordinary source edits, and decisively:

    baseline                                      auth=AUTHORIZED usable=True exit=0.06
    after forcing the exit down the entry branch  auth=AUTHORIZED usable=True exit=0.04

An authorization computed BEFORE the edit still reported AUTHORIZED. (The R3 test suite did fail on those
mutations, but only because it asserts fee VALUES -- a value assertion is not a closure, and tests do not run in
production.)

THE CLOSURE. `FeeRuntime` -- policy selection, term validation, the gate, `_side`, `entry`, `exit` -- now lives
inside the digested module and `FeeSchedule` inherits it, holding only data, identity and authorization.
`fee_surface_problems()` proves no fee-producing member resolves anywhere else.

Reproductions: R31_FINDING_REPRODUCTION_before_repair.txt and R31_AFTER_REPAIR.txt."""
from __future__ import annotations

import ast
import hashlib
import pathlib
import tempfile

import pytest

from apex.options_pilot import fee_computation as FC
from apex.options_pilot import ledger as L
from apex.options_pilot import session as S
from apex.options_pilot.fees import (AUTHORIZED, FeeAuthorization, FeeAuthorizationRefused, FeePolicyRefused,
                                     FeeSchedule, ROBINHOOD_RHF_2026)
from apex.options_pilot.synthetic_harness import SyntheticHarness, T0

RB = ROBINHOOD_RHF_2026
FC_PY = pathlib.Path(FC.__file__)


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
    tree = ast.parse(src)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body.pop(0)
    return hashlib.sha256(ast.dump(tree, annotate_fields=True, include_attributes=False).encode()).hexdigest()


# ===================================================== the five wrapper mutations


MUTATIONS = {
    "1_force_exit_down_the_entry_branch": (
        '        return self._side(contracts, "SELL", sale_principal=sale_principal)',
        '        return self._side(contracts, "BUY")'),
    "2_swap_the_delegated_operation": (
        '        return self._side(contracts, "BUY")',
        '        return self._side(contracts, "SELL", sale_principal=540.0)'),
    "3_different_sale_principal": (
        '        return self._side(contracts, "SELL", sale_principal=sale_principal)',
        '        return self._side(contracts, "SELL", sale_principal=1.0)'),
    "4_replace_a_returned_component": (
        '        out["schedule_id"] = self.schedule_id',
        '        out["components"]["exchange"] = out["components"]["commission"]\n'
        '        out["schedule_id"] = self.schedule_id'),
    "5_exit_calls_the_wrong_operation": (
        '    def exit(self, contracts: int, *, sale_principal=None) -> dict:',
        '    def exit(self, contracts: int, *, sale_principal=None) -> dict:\n'
        '        return self.entry(contracts)'),
}


class TestEveryWrapperMutationChangesTheDigest:
    """Each mutation is digested WITHOUT writing to the repository: the same canonicalization applied to mutated
    source text. Under R3 every one of these left the digest byte-identical."""

    @pytest.mark.parametrize("name", sorted(MUTATIONS))
    def test_mutation_changes_the_implementation_digest(self, name):
        old, new = MUTATIONS[name]
        src = FC_PY.read_text()
        assert old in src, "anchor missing for %s" % name
        mutated = src.replace(old, new, 1)
        assert mutated != src
        assert digest_of_source(mutated) != digest_of_source(src) == FC.module_digest()

    def test_the_whole_public_surface_is_inside_the_digested_module(self):
        assert FC.fee_surface_problems(FeeSchedule) == []
        for name in FC.FEE_PRODUCING_METHODS:
            member = getattr(FeeSchedule, name)
            fn = getattr(member, "fget", member)
            assert fn.__module__ == FC.__name__, name

    def test_NEGATIVE_an_undigested_public_fee_path_fails_the_build(self):
        """The structural guard itself must catch a path added outside the digested module."""
        class Rogue(FeeSchedule):
            def entry(self, contracts):                       # defined HERE, not in the digested module
                return {"total": 0.0}

        problems = FC.fee_surface_problems(Rogue)
        assert problems and "Rogue.entry" in problems[0] and "outside the digested computation module" in problems[0]

    def test_NEGATIVE_a_missing_surface_member_also_fails(self):
        class Hollow:
            pass
        assert len(FC.fee_surface_problems(Hollow)) == len(FC.FEE_PRODUCING_METHODS)

    def test_the_gate_and_the_validation_are_inside_the_digest_too(self):
        src = FC_PY.read_text()
        assert "def validate_terms_and_policy" in src
        assert "authorization_state()" in src, "the gate call belongs to the digested surface"


# ===================================================== the digest boundary


class TestTheDigestBoundary:
    def test_authorization_metadata_does_not_change_the_implementation_digest(self):
        a = synth(authorization=auth(RB)).implementation_digest
        b = synth(authorization=auth(RB, authorized_by="SOMEONE_ELSE", scope="WIDER",
                                     authorized_utc="1999-01-01T00:00:00Z")).implementation_digest
        assert a == b == FC.module_digest()

    def test_the_module_carries_no_authorization_payload(self):
        """Non-circular: the module calls the gate, it never contains an authorization's fields."""
        src = FC_PY.read_text()
        for forbidden in ("class FeeAuthorization", "authorized_by", "authorized_utc", "source_document_sha256"):
            assert forbidden not in src, forbidden

    def test_comments_and_docstrings_do_not_change_the_digest(self):
        src = FC_PY.read_text()
        same = src.replace('"""HOW the rates are applied -- declared once, and EXECUTED FROM.',
                           '"""ENTIRELY DIFFERENT PROSE.') + "\n# trailing comment\n\n"
        assert digest_of_source(same) == digest_of_source(src)

    def test_the_dependency_set_is_still_closed(self):
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
        nested = set()
        for outer in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            for sub in ast.walk(outer):
                if isinstance(sub, ast.FunctionDef) and sub is not outer:
                    nested.add(id(sub))
        unresolved = set()
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and id(n) not in nested):
            local = set()
            for sub in ast.walk(fn):
                if isinstance(sub, (ast.FunctionDef, ast.Lambda)):
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
        assert unresolved == set(), sorted(unresolved)


# ===================================================== R1-R3 reproducers remain closed


class TestEarlierReproducersRemainClosed:
    def test_R2_policy_subclass_still_refused(self):
        class P(FC.FeeComputationPolicy):
            pass
        with pytest.raises(FC.FeeComputationRefused, match="POLICY_NOT_CANONICAL"):
            synth(computation_policy=P(**FC.SALE_PRINCIPAL_POLICY_V1.__dict__)).exit(1, sale_principal=540.0)

    def test_R3_schedule_subclass_still_unverifiable(self):
        class Sub(FeeSchedule):
            pass
        assert Sub(**{**RB.__dict__}).implementation_digest.startswith("UNVERIFIABLE_IMPLEMENTATION")

    def test_R2_inconsistent_basis_still_refused(self):
        lying = FC.FeeComputationPolicy(**{**FC.SALE_PRINCIPAL_POLICY_V1.__dict__,
                                           "sec_basis": "PER_CONTRACT_CONSTANT"})
        with pytest.raises(FeePolicyRefused, match="SEC_BASIS_INCONSISTENT"):
            synth(computation_policy=lying)

    def test_R2_malformed_digest_still_refused(self):
        with pytest.raises(FeeAuthorizationRefused, match="DIGEST_MALFORMED"):
            auth(RB, implementation_digest="UNVERIFIABLE_IMPLEMENTATION: x")

    def test_source_unavailable_remains_unauthorizable(self, monkeypatch):
        monkeypatch.setattr(FC.inspect, "getsource", lambda *a, **k: (_ for _ in ()).throw(OSError("no source")))
        assert FC.module_digest().startswith("UNVERIFIABLE_IMPLEMENTATION")
        assert FeeSchedule(**{**RB.__dict__}).authorization_state()["basis"] == "IMPLEMENTATION_UNVERIFIABLE"


# ===================================================== acceptance


class TestAcceptance:
    def test_entry_004_and_exit_006(self):
        t = synth()
        assert t.entry(1)["total"] == 0.04 and t.exit(1, sale_principal=540.0)["total"] == 0.06

    def test_the_exact_control_reaches_TRADE(self):
        s = FeeSchedule(**{**RB.__dict__, "authorization": auth(RB)})
        assert s.usable
        d = pathlib.Path(tempfile.mkdtemp())
        h = SyntheticHarness(d / "l.jsonl", session_id="R31", t0=T0, risk="certified", fee_schedule=s)
        out = S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        assert out["decision"] == "TRADE"
        assert len([r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_fill"]) == 1

    @pytest.mark.parametrize("kind", ["missing", "stale", "mismatched"])
    def test_a_bad_authorization_refuses_before_any_quote(self, kind):
        asked = []

        class CountingQuotes:
            def __call__(self, *a, **k):
                asked.append(1)
                raise AssertionError("a quote was requested")

        fees = {"missing": FeeSchedule(**{**RB.__dict__}),
                "stale": FeeSchedule(**{**RB.__dict__, "authorization": auth(RB, version="2026-09-12")}),
                "mismatched": FeeSchedule(**{**RB.__dict__,
                                             "authorization": auth(RB, terms_digest="0" * 64)})}[kind]
        with pytest.raises(FeeAuthorizationRefused):
            d = pathlib.Path(tempfile.mkdtemp())
            h = SyntheticHarness(d / "l.jsonl", session_id="R31Q", t0=T0, risk="certified", fee_schedule=fees)
            h.quotes = CountingQuotes()
            S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        assert asked == []

    def test_the_shipped_candidate_is_still_unauthorized(self):
        assert RB.authorization is None and RB.usable is False
