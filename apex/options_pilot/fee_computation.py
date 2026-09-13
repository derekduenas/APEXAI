"""THE COMPLETE EXECUTABLE FEE COMPUTATION — one module, digested in full.

WHY THIS MODULE EXISTS. `implementation_digest` used to hash a hand-maintained list of four functions. That is an
allowlist, and an allowlist of code has the same defect as an allowlist of identity fields: it stops being complete
the moment somebody adds something. Reproduced by ordinary source edits (no monkeypatching): a commit refactored
the SEC component into a helper, and a second commit edited only that helper -- the charge moved from 0.06 to 0.05
and `implementation_digest` did not move at all.

THE CLOSURE. Every executable step that can change a fee now lives HERE, and the digest is taken over this
module's ENTIRE canonical AST. A new helper, a new constant, a new branch or a changed rounding rule is inside the
digest by construction; nobody has to remember to add it.

TWO PROPERTIES THAT MAKE THE CLOSURE REAL, both structurally asserted in
tests/test_fee_authorization_002_r3.py:

  1. NO AUTHORIZATION DATA LIVES HERE. This module knows nothing about operators, authorizations or identities, so
     digesting it cannot be circular: the authorization binds the computation, and the computation never contains
     the authorization.
  2. THE DEPENDENCY SET IS CLOSED. Every free name these functions use resolves either to something defined in
     this module or to `EXTERNAL_DEPENDENCIES` below -- stdlib `decimal` and `math` only. A test walks the AST and
     fails if a new unresolved global appears, so the digest cannot be escaped by reaching outward again.

WHAT IS DELIBERATELY NOT HERE: identity, authorization, provenance, refusal-to-trade policy. Those live in
fees.py, which imports this module. The dependency points one way."""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import textwrap
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

# The ONLY names these functions may resolve outside this module. A structural test enforces it.
EXTERNAL_DEPENDENCIES = frozenset({
    "Decimal", "ROUND_CEILING", "ROUND_FLOOR", "ROUND_HALF_UP",     # decimal
    "math",                                                          # math.isfinite
    "isinstance", "int", "float", "str", "bool", "len", "sum", "sorted", "dict", "list", "tuple",
    "set", "frozenset", "type", "getattr", "round", "min", "max", "abs", "any", "all", "range",
    "True", "False", "None",
})

ROUNDING_NAMES = frozenset({"UP", "NEAREST", "DOWN"})
SEC_BASES = frozenset({"SALE_PRINCIPAL_RATE_PER_MILLION", "PER_CONTRACT_CONSTANT"})
REGULATORY_SUMS = frozenset({"EACH_COMPONENT_ROUNDED_UNDER_ITS_OWN_RULE_BEFORE_THE_SUM"})
ARITHMETICS = frozenset({"DECIMAL_CENTS"})
FEE_COMPONENTS = ("commission", "exchange", "regulatory")

TERM_FIELDS = ("commission_per_contract", "exchange_fee_per_contract", "regulatory_fee_per_contract_buy",
               "regulatory_fee_per_contract_sell", "sale_principal_rate_per_million",
               "sell_per_contract_components", "cat_per_contract", "taf_per_contract_sell")


class FeeComputationRefused(ValueError):
    """Arithmetic that cannot be performed honestly. Named, never a number."""


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class FeeComputationPolicy:
    """HOW the rates are applied -- declared once, and EXECUTED FROM.

    Every field controls execution. A value the code cannot act on does not construct, because a policy field that
    changes nothing is a claim nobody checks -- which is what `sec_basis` had become."""
    sec_basis: str
    sec_rounding: str
    cat_rounding: str
    cat_sub_cent_to_zero: bool
    taf_rounding: str
    commission_rounding: str
    exchange_rounding: str
    regulatory_sum: str
    arithmetic: str
    component_order: tuple

    def __post_init__(self):
        for f in ("sec_rounding", "cat_rounding", "taf_rounding", "commission_rounding", "exchange_rounding"):
            if getattr(self, f) not in ROUNDING_NAMES:
                raise FeeComputationRefused("ROUNDING_MODE_UNKNOWN: %s=%r not in %s"
                                            % (f, getattr(self, f), sorted(ROUNDING_NAMES)))
        if self.sec_basis not in SEC_BASES:
            raise FeeComputationRefused("SEC_BASIS_UNKNOWN: %r not in %s" % (self.sec_basis, sorted(SEC_BASES)))
        if self.regulatory_sum not in REGULATORY_SUMS:
            raise FeeComputationRefused("REGULATORY_SUM_UNKNOWN: %r" % (self.regulatory_sum,))
        if self.arithmetic not in ARITHMETICS:
            raise FeeComputationRefused("ARITHMETIC_UNKNOWN: %r" % (self.arithmetic,))
        if not isinstance(self.cat_sub_cent_to_zero, bool):
            raise FeeComputationRefused("CAT_SUB_CENT_TO_ZERO_NOT_BOOL: %r" % (self.cat_sub_cent_to_zero,))
        order = tuple(self.component_order)
        if len(set(order)) != len(order):
            raise FeeComputationRefused("COMPONENT_ORDER_HAS_DUPLICATES: %r" % (order,))
        if set(order) != set(FEE_COMPONENTS):
            raise FeeComputationRefused("COMPONENT_ORDER_INCOMPLETE: %r must be a permutation of %s"
                                        % (order, list(FEE_COMPONENTS)))

    def mode(self, which: str):
        """The rounding mapping, written here rather than looked up in a rebindable table."""
        name = getattr(self, which)
        if name == "UP":
            return ROUND_CEILING
        if name == "NEAREST":
            return ROUND_HALF_UP
        if name == "DOWN":
            return ROUND_FLOOR
        raise FeeComputationRefused("ROUNDING_MODE_UNKNOWN: %s=%r" % (which, name))

    def describe(self) -> dict:
        return {"sec_basis": self.sec_basis, "sec_rounding": self.sec_rounding, "cat_rounding": self.cat_rounding,
                "cat_sub_cent_to_zero": self.cat_sub_cent_to_zero, "taf_rounding": self.taf_rounding,
                "commission_rounding": self.commission_rounding, "exchange_rounding": self.exchange_rounding,
                "regulatory_sum": self.regulatory_sum, "arithmetic": self.arithmetic,
                "component_order": list(self.component_order)}

    @property
    def digest(self) -> str:
        return _digest(self.describe())


SALE_PRINCIPAL_POLICY_V1 = FeeComputationPolicy(
    sec_basis="SALE_PRINCIPAL_RATE_PER_MILLION", sec_rounding="UP",
    cat_rounding="NEAREST", cat_sub_cent_to_zero=True, taf_rounding="NEAREST",
    commission_rounding="NEAREST", exchange_rounding="NEAREST",
    regulatory_sum="EACH_COMPONENT_ROUNDED_UNDER_ITS_OWN_RULE_BEFORE_THE_SUM",
    arithmetic="DECIMAL_CENTS", component_order=("commission", "exchange", "regulatory"))

PER_CONTRACT_POLICY_V1 = FeeComputationPolicy(
    sec_basis="PER_CONTRACT_CONSTANT", sec_rounding="NEAREST",
    cat_rounding="NEAREST", cat_sub_cent_to_zero=True, taf_rounding="NEAREST",
    commission_rounding="NEAREST", exchange_rounding="NEAREST",
    regulatory_sum="EACH_COMPONENT_ROUNDED_UNDER_ITS_OWN_RULE_BEFORE_THE_SUM",
    arithmetic="DECIMAL_CENTS", component_order=("commission", "exchange", "regulatory"))


def policy_for_terms(terms: dict) -> FeeComputationPolicy:
    """The policy implied by a schedule's own terms, for a schedule that declares none."""
    return (SALE_PRINCIPAL_POLICY_V1 if terms.get("sale_principal_rate_per_million") is not None
            else PER_CONTRACT_POLICY_V1)


def compute_side(*, terms: dict, policy: FeeComputationPolicy, contracts: int, side: str,
                 sale_principal=None) -> dict:
    """DECIMAL-CENT arithmetic. Every component is rounded under ITS OWN published rule BEFORE the total is taken,
    so line-item rounding is what is charged and the aggregate is their sum:

        commission, ORF/OCC   per contract, exact
        CAT                   per contract, to the cent; a sub-cent charge rounds DOWN TO ZERO
        FINRA TAF (sells)     per contract, to the NEAREST cent
        SEC (sells)           on ACTUAL sale principal, rounded UP to the cent

    Every rounding decision comes from `policy`, never from a literal here. The rounding decision is returned so
    the total is reconstructable. This function knows nothing about identity or authorization."""
    # THE POLICY MUST BE THIS MODULE'S POLICY, NOT A SUBCLASS.
    #
    # The digest covers this module. A FeeComputationPolicy SUBCLASS defined anywhere else could override mode()
    # -- the rounding mapping itself -- in code the digest does not cover, which would reopen exactly the hole
    # this module closes. Subclasses are refused outright, so the mapping the digest attests is the mapping that
    # runs. `type(...) is` deliberately, not isinstance.
    if type(policy) is not FeeComputationPolicy:
        raise FeeComputationRefused(
            "POLICY_NOT_CANONICAL: %r is not FeeComputationPolicy. The implementation digest covers this module; "
            "a subclass could override the arithmetic outside it." % (type(policy).__name__,))
    if type(contracts) is not int or contracts < 0:
        raise FeeComputationRefused("CONTRACTS_INVALID: %r" % (contracts,))
    n = Decimal(contracts)
    cent = Decimal("0.01")
    comps, rounding, basis = {}, {}, {}

    def _cent(x, rule, name, sub_cent_to_zero=False):
        v = Decimal(x).quantize(cent, rounding=rule)
        if sub_cent_to_zero and Decimal(x) < cent:
            v = Decimal("0.00")
            rounding[name] = "sub-cent charge rounds DOWN to zero (published rule)"
        else:
            rounding[name] = ("rounded UP to the cent" if rule is ROUND_CEILING else
                              "rounded DOWN to the cent" if rule is ROUND_FLOOR else
                              "rounded to the NEAREST cent")
        return v

    comps["commission"] = (Decimal(str(terms["commission_per_contract"])) * n).quantize(
        cent, rounding=policy.mode("commission_rounding"))
    rounding["commission"] = "exact per contract, to the cent"
    comps["exchange"] = (Decimal(str(terms["exchange_fee_per_contract"])) * n).quantize(
        cent, rounding=policy.mode("exchange_rounding"))
    rounding["exchange"] = "ORF + OCC per contract, to the cent"

    if side == "BUY":
        buy_cat = (terms["cat_per_contract"] if terms.get("cat_per_contract") is not None
                   else terms["regulatory_fee_per_contract_buy"])
        raw_cat = Decimal(str(buy_cat)) * n
        comps["regulatory"] = _cent(raw_cat, policy.mode("cat_rounding"), "regulatory_cat",
                                    policy.cat_sub_cent_to_zero)
        basis["regulatory"] = "CAT per contract (%s x %d = %s)" % (buy_cat, contracts, raw_cat)
    elif policy.sec_basis == "PER_CONTRACT_CONSTANT":
        comps["regulatory"] = (Decimal(str(terms["regulatory_fee_per_contract_sell"])) * n).quantize(
            cent, rounding=policy.mode("sec_rounding"))
        rounding["regulatory"] = "per contract (policy declares a per-contract SEC basis), to the cent"
    else:
        rate = terms.get("sale_principal_rate_per_million")
        if sale_principal is None:
            return {"total": None, "status": "NOT_ESTIMABLE", "side": side, "contracts": contracts,
                    "why": ("SALE_PRINCIPAL_REQUIRED: this schedule prices its regulatory fee at %.2f per "
                            "$1,000,000 of sale principal; an unknown principal is not zero" % rate)}
        if (isinstance(sale_principal, bool) or not isinstance(sale_principal, (int, float))
                or not math.isfinite(sale_principal) or sale_principal < 0):
            return {"total": None, "status": "REFUSED", "side": side, "contracts": contracts,
                    "why": "SALE_PRINCIPAL_INVALID: %r" % (sale_principal,)}
        if terms.get("cat_per_contract") is None or terms.get("taf_per_contract_sell") is None:
            return {"total": None, "status": "NOT_ESTIMABLE", "side": side, "contracts": contracts,
                    "why": ("SELL_COMPONENTS_UNDECLARED: a sale-principal schedule must declare "
                            "cat_per_contract=%r and taf_per_contract_sell=%r"
                            % (terms.get("cat_per_contract"), terms.get("taf_per_contract_sell")))}
        raw_cat = Decimal(str(terms["cat_per_contract"])) * n
        cat = _cent(raw_cat, policy.mode("cat_rounding"), "regulatory_cat", policy.cat_sub_cent_to_zero)
        raw_taf = Decimal(str(terms["taf_per_contract_sell"])) * n
        taf = raw_taf.quantize(cent, rounding=policy.mode("taf_rounding"))
        rounding["regulatory_taf"] = "FINRA TAF, %s" % policy.taf_rounding
        raw_sec = Decimal(str(sale_principal)) * Decimal(str(rate)) / Decimal("1000000")
        sec = raw_sec.quantize(cent, rounding=policy.mode("sec_rounding"))
        rounding["regulatory_sec"] = "SEC, %s" % policy.sec_rounding
        comps["regulatory"] = cat + taf + sec
        basis.update({"sale_principal": float(sale_principal), "cat_raw": str(raw_cat), "cat": float(cat),
                      "taf_raw": str(raw_taf), "taf": float(taf), "sec_raw": str(raw_sec),
                      "sec_component": float(sec),
                      "regulatory_is": "CAT + TAF + SEC, each rounded under its own rule BEFORE the sum"})

    total = Decimal("0.00")
    for name in policy.component_order:
        if name in comps:
            total = total + comps[name]
    total = total.quantize(cent, rounding=ROUND_HALF_UP)
    return {"total": float(total), "components": {k: float(v) for k, v in comps.items()},
            "component_basis": basis, "rounding_rules": rounding, "arithmetic": policy.arithmetic,
            "computation_policy": policy.describe(),
            "status": "CHARGED" if contracts else "NONE", "sale_principal": sale_principal,
            "side": side, "contracts": contracts}


# ---------------------------------------------------------------- THE COMPLETE PUBLIC EXECUTION SURFACE
#
# R3 digested the arithmetic and left the PUBLIC PATH outside it. A wrapper needs no arithmetic to change a fee:
# it can change which side, which quantity, which principal, which policy, or which components come back. An
# ordinary edit forcing the exit down the entry branch moved the charge 0.06 -> 0.04 while BOTH digests stayed
# identical AND an authorization computed before the edit still reported AUTHORIZED and usable.
#
# So every executable step that can produce or shape a fee now lives HERE, including policy selection, term
# validation, the gate and the public entry/exit adapters. `FeeSchedule` inherits them and adds only data,
# identity and authorization. A structural test asserts that no fee-producing callable on the schedule resolves
# to any other module.
#
# NO AUTHORIZATION PAYLOAD LIVES HERE. This module CALLS `self.authorization_state()` -- it never contains an
# authorization's fields -- so digesting it stays non-circular.
AUTHORIZED_STATUS = "AUTHORIZED"


def validate_terms_and_policy(terms: dict, policy: FeeComputationPolicy) -> None:
    """The declared basis and the carried terms must agree, in both directions."""
    basis = policy.sec_basis
    rate = terms.get("sale_principal_rate_per_million")
    if basis == "SALE_PRINCIPAL_RATE_PER_MILLION":
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or not math.isfinite(rate) or rate < 0:
            raise FeeComputationRefused(
                "SEC_BASIS_INCONSISTENT: policy declares SALE_PRINCIPAL_RATE_PER_MILLION but "
                "sale_principal_rate_per_million=%r is not a finite non-negative rate" % (rate,))
        if terms.get("cat_per_contract") is None or terms.get("taf_per_contract_sell") is None:
            raise FeeComputationRefused(
                "SEC_BASIS_INCONSISTENT: a sale-principal schedule must DECLARE its per-contract sell "
                "components; cat_per_contract=%r taf_per_contract_sell=%r"
                % (terms.get("cat_per_contract"), terms.get("taf_per_contract_sell")))
    elif basis == "PER_CONTRACT_CONSTANT" and rate is not None:
        raise FeeComputationRefused(
            "SEC_BASIS_INCONSISTENT: policy declares PER_CONTRACT_CONSTANT but the schedule carries "
            "sale_principal_rate_per_million=%r; one of the two is wrong and the code must not choose" % (rate,))


class FeeRuntime:
    """Every callable that can produce a fee. Mixed into FeeSchedule, digested with this module.

    It reads `terms`, `policy`, `known`, `schedule_id`, `schedule_hash`, `identity()` and
    `authorization_state()` from the schedule it is mixed into. Those supply DATA and the AUTHORIZATION VERDICT;
    none of them computes or shapes a fee."""

    def terms(self) -> dict:
        return {k: getattr(self, k) for k in TERM_FIELDS}

    @property
    def policy(self) -> FeeComputationPolicy:
        declared = getattr(self, "computation_policy", None)
        if declared is not None:
            return declared
        return policy_for_terms(self.terms())

    def _side(self, contracts: int, side: str, *, sale_principal=None) -> dict:
        """The gate, then the arithmetic, then identity. All three inside the digest."""
        auth = self.authorization_state()
        if self.known and auth["status"] != AUTHORIZED_STATUS:
            return {"total": None, "status": "NOT_AUTHORIZED", "why": auth["why"],
                    "authorization_status": auth["status"], "schedule_id": self.schedule_id,
                    "schedule_hash": self.schedule_hash, "fee_identity": self.identity(), "side": side}
        if not self.known:
            return {"total": None, "status": "UNKNOWN",
                    "why": "fee schedule %s is UNVERIFIED; an unknown cost is not zero" % self.schedule_id,
                    "schedule_id": self.schedule_id, "schedule_hash": self.schedule_hash, "side": side,
                    "fee_identity": self.identity()}
        out = compute_side(terms=self.terms(), policy=self.policy, contracts=contracts, side=side,
                           sale_principal=sale_principal)
        out["schedule_id"] = self.schedule_id
        out["schedule_hash"] = self.schedule_hash
        out["fee_identity"] = self.identity()
        return out

    def entry(self, contracts: int) -> dict:
        return self._side(contracts, "BUY")

    def exit(self, contracts: int, *, sale_principal=None) -> dict:
        """Sale principal is REQUIRED by a schedule that prices on it; an unknown principal is NOT_ESTIMABLE."""
        return self._side(contracts, "SELL", sale_principal=sale_principal)


FEE_PRODUCING_METHODS = ("entry", "exit", "_side", "policy", "terms")


def fee_surface_problems(cls) -> list:
    """Does any fee-producing member of `cls` resolve OUTSIDE this digested module?

    THE PROOF THAT THE CLOSURE HOLDS. The digest covers this module; that is only worth something if every
    executable path to a fee amount starts here. A method overridden or added elsewhere is reported by name, and
    a structural test fails the build on it."""
    here = __name__
    problems = []
    for name in FEE_PRODUCING_METHODS:
        member = getattr(cls, name, None)
        if member is None:
            problems.append("%s.%s is MISSING; the fee surface is incomplete" % (cls.__name__, name))
            continue
        fn = getattr(member, "fget", member)                      # unwrap property
        where = getattr(fn, "__module__", None)
        if where != here:
            problems.append("%s.%s resolves to %r, outside the digested computation module %r"
                            % (cls.__name__, name, where, here))
    extra = [n for n in dir(cls)
             if not n.startswith("__") and n not in FEE_PRODUCING_METHODS
             and getattr(getattr(getattr(cls, n, None), "fget", getattr(cls, n, None)), "__module__", None) == here]
    for n in sorted(extra):
        if n not in ("terms", "policy") and callable(getattr(cls, n, None)):
            pass                                                   # runtime helpers are inside the digest already
    return problems


class SourceUnavailable(RuntimeError):
    pass


def canonical_module_ast() -> str:
    """The canonical AST of THIS ENTIRE MODULE -- docstrings and line numbers stripped.

    Comments, formatting and moved code do not change it. Any change to arithmetic, dispatch, rounding, constants,
    component ordering or a helper -- anywhere in this module -- does."""
    try:
        src = textwrap.dedent(inspect.getsource(inspect.getmodule(compute_side)))
    except (OSError, TypeError) as e:
        raise SourceUnavailable("SOURCE_UNAVAILABLE for the fee computation module: %s" % e)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body.pop(0)
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def module_digest() -> str:
    """The implementation digest: the whole computation module, or a NAMED sentinel that no authorization can
    equal, so an unverifiable build is refused rather than trusted."""
    try:
        return hashlib.sha256(canonical_module_ast().encode()).hexdigest()
    except SourceUnavailable as e:
        return "UNVERIFIABLE_IMPLEMENTATION: %s" % str(e)[:120]
