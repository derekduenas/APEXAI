"""VERSIONED FEE AND EXECUTION POLICIES for OPTIONS-PILOT-001 (M1).

An unknown cost is not zero. A fee schedule is an object with an id, a
version, a provenance and a verification record. The production route may
only trade under a schedule whose provenance is PROVIDER_VERIFIED; the
synthetic harness uses a schedule whose provenance says SYNTHETIC_FIXTURE
and whose numbers are visibly invented. Fees are charged exactly once per
side: the entry fee lives on the fill record, the exit fee on the
discharging outcome record; the Book recomputes both from the schedule
named on the record.

The execution policy is also versioned: simulated latency, the re-quote
rule, the displayed-size rule and the fill-quantity domain {0, 1}. Every
simulated fill says it is simulated."""
from __future__ import annotations

import math
import ast
import inspect
import textwrap
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from dataclasses import dataclass, field

from .clock import is_real
from .records import canonical_hash

FEE_PROVENANCE = ("SYNTHETIC_FIXTURE", "PROVIDER_VERIFIED", "UNVERIFIED")


class FeePolicyRefused(ValueError):
    pass


ROUND_MODES = {"UP": ROUND_CEILING, "NEAREST": ROUND_HALF_UP, "DOWN": ROUND_FLOOR}


@dataclass(frozen=True)
class FeeComputationPolicy:
    """HOW the rates are applied -- declared once, and EXECUTED FROM.

    The first version of `computation_digest` hashed a hand-written description of the arithmetic while `_side()`
    carried its own parallel hard-coded rules. That made the digest a CLAIM about the implementation rather than a
    binding to it: changing ROUND_CEILING to ROUND_FLOOR in `_side()` changed the charged amount from 0.06 to 0.05
    and left the digest byte-identical, so an authorization bound to it still matched.

    This object is the single source of the rounding and basis decisions. `_side()` reads its modes from here, so
    the description and the behaviour cannot drift apart -- and the digest over it is a digest over rules that are
    actually in force."""
    sec_basis: str                      # SALE_PRINCIPAL_RATE_PER_MILLION | PER_CONTRACT_CONSTANT
    sec_rounding: str                   # UP | NEAREST | DOWN
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
            if getattr(self, f) not in ROUND_MODES:
                raise FeePolicyRefused("ROUNDING_MODE_UNKNOWN: %s=%r" % (f, getattr(self, f)))

    def mode(self, which: str):
        return ROUND_MODES[getattr(self, which)]

    def describe(self) -> dict:
        return {"sec_basis": self.sec_basis, "sec_rounding": self.sec_rounding, "cat_rounding": self.cat_rounding,
                "cat_sub_cent_to_zero": self.cat_sub_cent_to_zero, "taf_rounding": self.taf_rounding,
                "commission_rounding": self.commission_rounding, "exchange_rounding": self.exchange_rounding,
                "regulatory_sum": self.regulatory_sum, "arithmetic": self.arithmetic,
                "component_order": list(self.component_order)}

    @property
    def digest(self) -> str:
        return canonical_hash(self.describe())


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


# ---------------------------------------------------------------- the EXECUTABLE implementation digest
FEE_IMPLEMENTATION_FUNCTIONS = ("_side", "entry", "exit")


class SourceUnavailable(RuntimeError):
    pass


def _canonical_ast(fn) -> str:
    """A structural digest of a function's SOURCE, with docstrings and line numbers removed.

    Reformatting, comments and moving code do not change it. Changing arithmetic, dispatch, component ordering or
    rounding does. It carries no authorization payload data -- only the code that computes a fee."""
    try:
        src = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError) as e:
        # THE CODE CANNOT BE READ, so it cannot be verified. This must not raise into the fee path and must not
        # quietly match: it becomes a sentinel that no authorization can equal, so the schedule fails closed.
        raise SourceUnavailable("SOURCE_UNAVAILABLE for %r: %s" % (getattr(fn, "__qualname__", fn), e))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body.pop(0)
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def implementation_digest_of(cls) -> str:
    """Digest of the fee-calculation code ACTUALLY BOUND to `cls`, so a subclass that overrides the arithmetic
    produces a different digest than the class it inherits from.

    If the source cannot be read -- a frozen build, a zipimport, a class defined in an interactive session -- this
    returns a NAMED sentinel rather than raising or guessing. The sentinel can never equal an authorization's
    digest, so an unverifiable implementation is refused instead of trusted."""
    try:
        return canonical_hash({name: _canonical_ast(getattr(cls, name)) for name in FEE_IMPLEMENTATION_FUNCTIONS})
    except SourceUnavailable as e:
        return "UNVERIFIABLE_IMPLEMENTATION: %s" % str(e)[:120]


class FeeAuthorizationRefused(FeePolicyRefused):
    """A cost model no person has authorized. Named, never silent, and never a number."""


AUTHORIZED = "AUTHORIZED"
NOT_AUTHORIZED = "NOT_AUTHORIZED"
AUTHORIZATION_SUPERSEDED = "AUTHORIZATION_SUPERSEDED"
AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
AUTHORIZATION_STATES = (AUTHORIZED, NOT_AUTHORIZED, AUTHORIZATION_SUPERSEDED, AUTHORIZATION_MISMATCH)


@dataclass(frozen=True)
class FeeAuthorization:
    """A PERSON AUTHORIZED THIS EXACT ARITHMETIC. Immutable, and matched field by field.

    WHY THIS TYPE EXISTS. `provenance` used to carry two different facts at once: that the SOURCE DOCUMENT had
    been verified, and that the cost model was cleared for use. `known` was derived from provenance alone, so a
    schedule transcribed from a published PDF became usable the moment it was transcribed -- no person had to
    agree to the arithmetic. Verifying a document and authorizing a computation are different acts by different
    parties, and conflating them meant an operator authorization for one computation silently carried over to a
    different one.

    Each field is matched EXACTLY against the schedule it claims to authorize. An authorization for another
    schedule, another version, another source document, other terms, or another COMPUTATION does not apply."""
    schedule_id: str
    version: str
    source_document_sha256: str
    terms_digest: str                    # the RATES
    computation_policy_digest: str       # HOW the rates are applied -- the policy _side() executes from
    implementation_digest: str           # the fee-calculation CODE itself, so a recipe cannot drift from behaviour
    effective_date: str
    status: str                       # AUTHORIZED | NOT_AUTHORIZED | AUTHORIZATION_SUPERSEDED
    authorized_by: str
    authorized_utc: str
    scope: str

    def __post_init__(self):
        if self.status not in AUTHORIZATION_STATES:
            raise FeeAuthorizationRefused("AUTHORIZATION_STATE_UNKNOWN: %r" % (self.status,))
        for f in ("schedule_id", "version", "source_document_sha256", "terms_digest",
                  "computation_policy_digest", "implementation_digest",
                  "effective_date", "authorized_by", "authorized_utc", "scope"):
            if not isinstance(getattr(self, f), str) or not getattr(self, f).strip():
                raise FeeAuthorizationRefused("AUTHORIZATION_FIELD_MISSING: %s" % f)

    def describe(self) -> dict:
        return {"schedule_id": self.schedule_id, "version": self.version,
                "source_document_sha256": self.source_document_sha256, "terms_digest": self.terms_digest,
                "computation_policy_digest": self.computation_policy_digest,
                "implementation_digest": self.implementation_digest, "effective_date": self.effective_date,
                "status": self.status, "authorized_by": self.authorized_by,
                "authorized_utc": self.authorized_utc, "scope": self.scope}

    @property
    def digest(self) -> str:
        return canonical_hash(self.describe())


@dataclass(frozen=True)
class FeeSchedule:
    schedule_id: str
    version: str
    provenance: str                       # SYNTHETIC_FIXTURE | PROVIDER_VERIFIED | UNVERIFIED
    commission_per_contract: float | None
    exchange_fee_per_contract: float | None
    regulatory_fee_per_contract_buy: float | None
    regulatory_fee_per_contract_sell: float | None
    verified_against: dict | None = None  # {"provider", "document", "date"} for PROVIDER_VERIFIED
    note: str = ""
    sale_principal_rate_per_million: float | None = None   # e.g. SEC $20.60 per $1,000,000 of SALE principal
    sell_per_contract_components: float = 0.0              # the sell-side components that ARE per contract (CAT + FINRA TAF)
    effective_date: str = "UNDECLARED"                     # the date the published terms take effect
    cat_per_contract: float | None = None                  # CAT, both sides, rounded to the cent with sub-cent -> 0
    taf_per_contract_sell: float | None = None             # FINRA TAF, sells, rounded to the NEAREST cent
    source_document_sha256: str = ""                       # VERIFIED SOURCE: which document these terms came from
    authorization: "FeeAuthorization | None" = None        # OPERATOR ACT: who cleared this exact computation
    computation_policy: "FeeComputationPolicy | None" = None   # HOW the rates are applied; _side() executes from it

    def __post_init__(self):
        if self.provenance not in FEE_PROVENANCE:
            raise FeePolicyRefused("FEE_PROVENANCE_UNKNOWN: %r" % (self.provenance,))
        if self.provenance == "PROVIDER_VERIFIED" and not (isinstance(self.verified_against, dict)
                                                          and {"provider", "document", "date"} <= set(self.verified_against)):
            raise FeePolicyRefused("FEE_SCHEDULE_VERIFICATION_RECORD_MISSING")
        if self.provenance != "UNVERIFIED":
            for k in ("commission_per_contract", "exchange_fee_per_contract",
                      "regulatory_fee_per_contract_buy", "regulatory_fee_per_contract_sell"):
                v = getattr(self, k)
                if not is_real(v) or v < 0:
                    raise FeePolicyRefused("FEE_COMPONENT_INVALID: %s=%r" % (k, v))

    @property
    def known(self) -> bool:
        return self.provenance != "UNVERIFIED"

    @property
    def schedule_hash(self) -> str:
        return canonical_hash(self.describe())

    # ---------------------------------------------------------------- COMPLETE CANONICAL FEE IDENTITY
    # The binding commits to ALL of this, not to schedule_id alone: an altered hash, provenance, known status,
    # effective date or term changes the identity and therefore the binding, and a persisted approval stops verifying.
    IDENTITY_FIELDS = ("schedule_id", "schedule_hash", "provenance", "known", "version", "effective_date",
                       "terms_digest", "computation_policy_digest", "implementation_digest",
                       "source_document_sha256", "authorization_status", "authorization_digest")

    @property
    def terms_digest(self) -> str:
        """A digest of the CANONICAL FEE TERMS alone (no ids, no provenance): two schedules with the same id but
        different arithmetic have different terms digests."""
        return canonical_hash({"commission_per_contract": self.commission_per_contract,
                               "exchange_fee_per_contract": self.exchange_fee_per_contract,
                               "regulatory_fee_per_contract_buy": self.regulatory_fee_per_contract_buy,
                               "regulatory_fee_per_contract_sell": self.regulatory_fee_per_contract_sell,
                               "sale_principal_rate_per_million": self.sale_principal_rate_per_million,
                               "sell_per_contract_components": self.sell_per_contract_components,
                               "cat_per_contract": self.cat_per_contract,
                               "taf_per_contract_sell": self.taf_per_contract_sell})

    @property
    def policy(self) -> "FeeComputationPolicy":
        """The computation policy in force. A schedule that declares none falls back to the form implied by its
        own terms, so existing schedules keep working and nothing is silently defaulted to the wrong arithmetic."""
        if self.computation_policy is not None:
            return self.computation_policy
        return (SALE_PRINCIPAL_POLICY_V1 if self.sale_principal_rate_per_million is not None
                else PER_CONTRACT_POLICY_V1)

    @property
    def computation_digest(self) -> str:
        """A digest over the policy the arithmetic EXECUTES FROM -- not a hand-written description of it.

        This distinguishes v2026-09-12 from v2026-09-12b: the RATES are identical, and only the SEC basis and
        rounding changed. Paired with `implementation_digest`, which binds the code itself, a change to the rules
        OR to the code that applies them invalidates an authorization."""
        return self.policy.digest

    @property
    def implementation_digest(self) -> str:
        """A digest over the EXECUTABLE fee-calculation code bound to this schedule's class.

        The policy digest says what the rules are; this says what the code does. Changing arithmetic, dispatch,
        component ordering or rounding inside _side/entry/exit changes it -- including in a subclass that
        overrides them -- so a declared recipe can no longer drift away from the behaviour it claims."""
        return implementation_digest_of(type(self))

    # ------------------------------------------------------------------ SOURCE VERIFIED vs OPERATOR AUTHORIZED
    @property
    def source_verified(self) -> bool:
        """Did a document back these terms? This is what `provenance` has always meant, and ALL it means."""
        return self.provenance == "PROVIDER_VERIFIED"

    @property
    def requires_authorization(self) -> bool:
        """A real broker schedule is a claim about real money and needs a person. The SYNTHETIC fixture is
        exempt: it is labelled synthetic, can never be a live cost claim, and authorizing it would be theatre."""
        return self.provenance == "PROVIDER_VERIFIED"

    def authorization_state(self) -> dict:
        """Is this exact computation authorized? Each field matched exactly; a near miss is a refusal."""
        if not self.requires_authorization:
            return {"status": AUTHORIZED, "why": None,
                    "basis": "NOT_REQUIRED: %s is not a broker schedule" % self.provenance}
        a = self.authorization
        if a is None:
            return {"status": NOT_AUTHORIZED,
                    "why": ("NO_AUTHORIZATION: %s v%s carries no operator authorization. A verified source document "
                            "is not an authorized cost model." % (self.schedule_id, self.version)),
                    "basis": "ABSENT"}
        if a.status != AUTHORIZED:
            return {"status": (AUTHORIZATION_SUPERSEDED if a.status == AUTHORIZATION_SUPERSEDED else NOT_AUTHORIZED),
                    "why": "AUTHORIZATION_NOT_ACTIVE: status is %s" % a.status, "basis": "STATUS"}
        for field, mine, theirs in (("schedule_id", self.schedule_id, a.schedule_id),
                                    ("version", self.version, a.version),
                                    ("effective_date", self.effective_date, a.effective_date),
                                    ("source_document_sha256", self.source_document_sha256, a.source_document_sha256),
                                    ("terms_digest", self.terms_digest, a.terms_digest),
                                    ("computation_policy_digest", self.computation_digest, a.computation_policy_digest),
                                    ("implementation_digest", self.implementation_digest, a.implementation_digest)):
            if mine != theirs:
                return {"status": AUTHORIZATION_MISMATCH,
                        "why": ("AUTHORIZATION_DOES_NOT_MATCH: %s is %r on the schedule and %r on the "
                                "authorization. An authorization applies to exactly what was authorized."
                                % (field, str(mine)[:24], str(theirs)[:24])),
                        "basis": field}
        return {"status": AUTHORIZED, "why": None, "basis": "EXACT_MATCH", "authorization_digest": a.digest}

    @property
    def authorized(self) -> bool:
        return self.authorization_state()["status"] == AUTHORIZED

    @property
    def usable(self) -> bool:
        """The ONLY property a trading gate should consult: the terms are known AND a person authorized them."""
        return self.known and self.authorized

    def assert_usable(self, *, what: str = "operation") -> None:
        if not self.known:
            raise FeeAuthorizationRefused("FEE_SCHEDULE_UNKNOWN: %s is %s; an unknown cost is not zero (%s)"
                                          % (self.schedule_id, self.provenance, what))
        st = self.authorization_state()
        if st["status"] != AUTHORIZED:
            raise FeeAuthorizationRefused("FEE_SCHEDULE_NOT_AUTHORIZED: %s -- %s (%s)"
                                          % (st["status"], st["why"], what))

    def identity(self) -> dict:
        """The complete canonical fee identity. Every field is compared exactly, everywhere."""
        st = self.authorization_state()
        return {"schedule_id": self.schedule_id, "schedule_hash": self.schedule_hash, "provenance": self.provenance,
                "known": self.known, "version": self.version, "effective_date": self.effective_date,
                "terms_digest": self.terms_digest,
                # BOUND INTO THE IDENTITY, so a persisted approval stops verifying the moment the authorization
                # changes, is removed, or is superseded.
                "computation_policy_digest": self.computation_digest,
                "implementation_digest": self.implementation_digest,
                "source_document_sha256": self.source_document_sha256,
                "authorization_status": st["status"],
                "authorization_digest": (self.authorization.digest if self.authorization is not None else None)}

    @property
    def identity_hash(self) -> str:
        return canonical_hash(self.identity())

    def describe(self) -> dict:
        return {"schedule_id": self.schedule_id, "version": self.version, "provenance": self.provenance,
                "sale_principal_rate_per_million": self.sale_principal_rate_per_million,
                "sell_per_contract_components": self.sell_per_contract_components,
                "commission_per_contract": self.commission_per_contract,
                "exchange_fee_per_contract": self.exchange_fee_per_contract,
                "regulatory_fee_per_contract_buy": self.regulatory_fee_per_contract_buy,
                "regulatory_fee_per_contract_sell": self.regulatory_fee_per_contract_sell,
                "verified_against": self.verified_against, "note": self.note}

    # C: SALE-PRINCIPAL COMPONENTS. A component whose rate is denominated in sale principal (the SEC regulatory fee)
    # is computed from the ACTUAL principal, under its own declared rounding rule, before totalling. The per-contract
    # constant it replaces was declared, bounded at $0.01 and conservative, but an approximation is not an exactness.
    PRINCIPAL_COMPONENTS = ("sec_regulatory_fee",)

    def _side(self, contracts: int, side: str, *, sale_principal: float | None = None) -> dict:
        """DECIMAL-CENT arithmetic. Every component is computed in Decimal and rounded under ITS OWN published rule
        BEFORE the total is taken, so line-item rounding is what is charged and the aggregate is their sum:
            commission, ORF/OCC   per contract, exact
            CAT                   per contract, rounded to the cent, and a sub-cent charge rounds DOWN TO ZERO
            FINRA TAF (sells)     per contract, rounded to the NEAREST cent
            SEC (sells)           on ACTUAL sale principal, rounded UP to the cent
        The rounding decision for each component is persisted so the total is reconstructable."""
        if type(contracts) is not int or contracts < 0:
            raise FeePolicyRefused("CONTRACTS_INVALID: %r" % (contracts,))
        _auth = self.authorization_state()
        if self.known and _auth["status"] != AUTHORIZED:
            # SOURCE VERIFIED IS NOT AUTHORIZED. A cost nobody cleared is not a cost we may charge.
            return {"total": None, "status": "NOT_AUTHORIZED", "why": _auth["why"],
                    "authorization_status": _auth["status"], "schedule_id": self.schedule_id,
                    "schedule_hash": self.schedule_hash, "fee_identity": self.identity(), "side": side}
        if not self.known:
            return {"total": None, "status": "UNKNOWN", "why": "fee schedule %s is UNVERIFIED; an unknown cost is not zero"
                    % self.schedule_id, "schedule_id": self.schedule_id, "schedule_hash": self.schedule_hash, "side": side,
                    "fee_identity": self.identity()}
        n = Decimal(contracts)
        cent = Decimal("0.01")
        pol = self.policy                      # EVERY rounding decision below comes from here, never a literal
        comps, rounding = {}, {}

        def _cent(x, rule, name, *, sub_cent_to_zero=False):
            v = Decimal(x).quantize(cent, rounding=rule)
            if sub_cent_to_zero and Decimal(x) < cent:
                v = Decimal("0.00")
                rounding[name] = "sub-cent charge rounds DOWN to zero (published rule)"
            else:
                rounding[name] = ("rounded UP to the cent" if rule is ROUND_CEILING else
                                  "rounded DOWN to the cent" if rule is ROUND_FLOOR else
                                  "rounded to the NEAREST cent")
            return v

        comms = (Decimal(str(self.commission_per_contract)) * n).quantize(cent, rounding=pol.mode("commission_rounding"))
        comps["commission"] = comms; rounding["commission"] = "exact per contract, to the cent"
        exch = (Decimal(str(self.exchange_fee_per_contract)) * n).quantize(cent, rounding=pol.mode("exchange_rounding"))
        comps["exchange"] = exch; rounding["exchange"] = "ORF + OCC per contract, to the cent"
        basis = {}
        if side == "BUY":
            _buy_cat = self.cat_per_contract if self.cat_per_contract is not None else self.regulatory_fee_per_contract_buy   # UNKNOWN_TO_ZERO_EXEMPT: not a zero default; falls back to the schedule's declared buy-side regulatory rate, which is validated non-None for a known schedule
            raw_cat = Decimal(str(_buy_cat)) * n
            comps["regulatory"] = _cent(raw_cat, pol.mode("cat_rounding"), "regulatory_cat", sub_cent_to_zero=pol.cat_sub_cent_to_zero)
            basis["regulatory"] = "CAT per contract (%s x %d = %s)" % (_buy_cat, contracts, raw_cat)
        elif self.sale_principal_rate_per_million is None:
            comps["regulatory"] = (Decimal(str(self.regulatory_fee_per_contract_sell)) * n).quantize(cent, rounding=pol.mode("sec_rounding"))
            rounding["regulatory"] = "per contract (schedule declares no sale-principal rate), to the cent"
        else:
            if sale_principal is None:
                return {"total": None, "status": "NOT_ESTIMABLE", "side": side, "contracts": contracts,
                        "schedule_id": self.schedule_id, "schedule_hash": self.schedule_hash, "fee_identity": self.identity(),
                        "why": ("SALE_PRINCIPAL_REQUIRED: %s prices its regulatory fee at %.2f per $1,000,000 of sale principal; "
                                "an unknown principal is not zero" % (self.schedule_id, self.sale_principal_rate_per_million))}
            if isinstance(sale_principal, bool) or not isinstance(sale_principal, (int, float)) or not math.isfinite(sale_principal) or sale_principal < 0:
                return {"total": None, "status": "REFUSED", "side": side, "contracts": contracts,
                        "schedule_id": self.schedule_id, "schedule_hash": self.schedule_hash, "fee_identity": self.identity(),
                        "why": "SALE_PRINCIPAL_INVALID: %r" % (sale_principal,)}
            # a schedule that prices on sale principal must DECLARE its per-contract sell components; an undeclared
            # component is unknown, and an unknown cost is not zero
            if self.cat_per_contract is None or self.taf_per_contract_sell is None:
                return {"total": None, "status": "NOT_ESTIMABLE", "side": side, "contracts": contracts,
                        "schedule_id": self.schedule_id, "schedule_hash": self.schedule_hash, "fee_identity": self.identity(),
                        "why": ("SELL_COMPONENTS_UNDECLARED: %s prices on sale principal but does not declare cat_per_contract=%r "
                                "and taf_per_contract_sell=%r" % (self.schedule_id, self.cat_per_contract, self.taf_per_contract_sell))}
            raw_cat = Decimal(str(self.cat_per_contract)) * n
            cat = _cent(raw_cat, pol.mode("cat_rounding"), "regulatory_cat", sub_cent_to_zero=pol.cat_sub_cent_to_zero)
            raw_taf = Decimal(str(self.taf_per_contract_sell)) * n
            taf = raw_taf.quantize(cent, rounding=pol.mode("taf_rounding")); rounding["regulatory_taf"] = "FINRA TAF, %s" % pol.taf_rounding
            raw_sec = Decimal(str(sale_principal)) * Decimal(str(self.sale_principal_rate_per_million)) / Decimal("1000000")
            sec = raw_sec.quantize(cent, rounding=pol.mode("sec_rounding")); rounding["regulatory_sec"] = "SEC, %s" % pol.sec_rounding
            comps["regulatory"] = cat + taf + sec
            basis.update({"sale_principal": float(sale_principal), "cat_raw": str(raw_cat), "cat": float(cat),
                          "taf_raw": str(raw_taf), "taf": float(taf), "sec_raw": str(raw_sec), "sec_component": float(sec),
                          "regulatory_is": "CAT + TAF + SEC, each rounded under its own rule BEFORE the sum"})
        total = sum((comps[k] for k in pol.component_order if k in comps), Decimal("0.00")).quantize(cent, rounding=ROUND_HALF_UP)
        return {"total": float(total), "components": {k: float(v) for k, v in comps.items()},
                "component_basis": basis, "rounding_rules": rounding, "arithmetic": pol.arithmetic,
                "computation_policy": pol.describe(),
                "status": "CHARGED" if contracts else "NONE", "sale_principal": sale_principal,
                "schedule_id": self.schedule_id, "schedule_hash": self.schedule_hash, "fee_identity": self.identity(),
                "side": side, "contracts": contracts}

    def entry(self, contracts: int) -> dict:
        return self._side(contracts, "BUY")

    def exit(self, contracts: int, *, sale_principal: float | None = None) -> dict:
        """`sale_principal` = exit premium x multiplier x contracts. Required when the schedule prices a component
        on sale principal; an unknown principal returns NOT_ESTIMABLE, never a default."""
        return self._side(contracts, "SELL", sale_principal=sale_principal)


SYNTHETIC_FEES = FeeSchedule(
    schedule_id="SYNTHETIC_FEES_V1", version="1", provenance="SYNTHETIC_FIXTURE",
    commission_per_contract=0.65, exchange_fee_per_contract=0.30,
    regulatory_fee_per_contract_buy=0.02, regulatory_fee_per_contract_sell=0.05,
    note="INVENTED numbers for orchestration tests; not any provider's schedule")

UNVERIFIED_FEES = FeeSchedule(
    schedule_id="UNVERIFIED", version="0", provenance="UNVERIFIED",
    commission_per_contract=None, exchange_fee_per_contract=None,
    regulatory_fee_per_contract_buy=None, regulatory_fee_per_contract_sell=None,
    note="no provider fee schedule has been verified for the pilot path; trading under it is refused")


def identity_problem(mine: dict, theirs, *, what: str) -> str | None:
    """THE canonical fee-identity comparison. Every consumer calls THIS; nobody writes a field list again.

    WHY IT EXISTS. `accepts()` and `fee_identity_problem()` each carried their own hand-written tuple of seven
    fields. When the identity grew, both kept comparing the old seven -- so an approval issued under one operator
    authorization was honoured by an authority running a DIFFERENT one, and an intent sealed under one passed the
    gate on another. The schema had grown; the joins had not. Comparing against IDENTITY_FIELDS itself makes that
    failure mode unreachable: adding a field automatically tightens every consumer at once.

    EXACT KEY EQUALITY, both directions. A MISSING field refuses, so an older record cannot be quietly accepted by
    a newer authority. An EXTRA field refuses too, because an identity carrying something nobody declared is not
    an identity this code understands."""
    if not isinstance(theirs, dict):
        return ("FEE_IDENTITY_MISSING: %s carries no fee identity (got %s); only a complete identity is honoured"
                % (what, type(theirs).__name__))
    expected = set(FeeSchedule.IDENTITY_FIELDS)
    missing = sorted(expected - set(theirs))
    if missing:
        return "FEE_IDENTITY_INCOMPLETE: %s lacks %s" % (what, ", ".join(repr(m) for m in missing))
    extra = sorted(set(theirs) - expected)
    if extra:
        return ("FEE_IDENTITY_UNDECLARED_FIELDS: %s carries %s, which this code does not declare; an identity is "
                "compared in full or not at all" % (what, ", ".join(repr(e) for e in extra)))
    for k in FeeSchedule.IDENTITY_FIELDS:
        if theirs[k] != mine[k]:
            return ("FEE_IDENTITY_MISMATCH: %s has %s=%r while the active authority runs %r"
                    % (what, k, str(theirs[k])[:48], str(mine[k])[:48]))
    return None


def recompute_fees(record_fee_block: dict, schedule: FeeSchedule, *, contracts: int, side: str) -> list:
    """Independent recomputation for the Book: disagreements are named."""
    problems = []
    if not isinstance(record_fee_block, dict):
        return ["FEE_BLOCK_MISSING"]
    if record_fee_block.get("schedule_id") != schedule.schedule_id or record_fee_block.get("schedule_hash") != schedule.schedule_hash:
        problems.append("FEE_SCHEDULE_IDENTITY_DISAGREES: record %r/%r vs %r/%r" % (
            record_fee_block.get("schedule_id"), str(record_fee_block.get("schedule_hash"))[:12],
            schedule.schedule_id, schedule.schedule_hash[:12]))
    fresh = schedule._side(contracts, side, sale_principal=record_fee_block.get("sale_principal"))
    if fresh.get("total") != record_fee_block.get("total"):
        problems.append("FEE_TOTAL_DISAGREES: record %r vs recomputed %r" % (record_fee_block.get("total"), fresh.get("total")))
    return problems


# ---------------------------------------------------------------- execution policy

@dataclass(frozen=True)
class ExecutionPolicy:
    policy_id: str = "EXECUTION_POLICY_V1"
    simulated_latency_s: float = 0.25            # receipt -> simulated execution instant
    max_fill_attempts: int = 3                    # first quote + 2 re-quotes, within the intent TTL
    fill_quantity_domain: tuple = (0, 1)          # one contract: filled or not; no fractions
    displayed_size_rule: str = ("displayed ask size >= requested quantity is REQUIRED for a simulated fill; it is a "
                                "constraint, not a guarantee of queue position or of real execution")
    fill_label: str = "SIMULATED: no order was sent; the fill is the quoted ASK at the simulated execution instant"
    horizon_note: str = "exit policy is a separate versioned object (exit_policy.EXIT_POLICY_V1)"
    fields: tuple = field(default=("policy_id", "simulated_latency_s", "max_fill_attempts", "fill_quantity_domain",
                                   "displayed_size_rule", "fill_label"))

    def describe(self) -> dict:
        return {k: getattr(self, k) for k in self.fields}

    @property
    def policy_hash(self) -> str:
        return canonical_hash(self.describe())


EXECUTION_POLICY_V1 = ExecutionPolicy()


# ---------------------------------------------------------------------------------------------------------------
# BROKER SCHEDULE CANDIDATE (Brick 3, 2026-09-12). The paper simulation represents a Robinhood Financial
# self-directed cash/margin account (non-Gold, non-"Professional") trading U.S. listed ETF options (SPY/QQQ/IWM).
# Every number below is copied from the broker's published "Standard Pricing Fee Schedule" PDF; nothing is assumed.
# It is NOT the live default: the live boundary keeps UNVERIFIED_FEES until the operator authorizes this document,
# and it is selected only through an explicit LiveWiring(fee_schedule=...) choice.
ROBINHOOD_RHF_2026_SOURCE = {
    "provider": "Robinhood Financial LLC (execution broker of the account the paper simulation represents; Alpaca and ThetaData are DATA vendors, not the broker)",
    "document": "RHF Standard Pricing Fee Schedule (PDF), https://cdn.robinhood.com/assets/robinhood/legal/RHF%20Fee%20Schedule.pdf",
    "document_sha256": "7f9c86bf297d078ce27505cbc53eecc068cf975fbfca5aada37b9af865d7e14a",
    "date": "retrieved 2026-09-12; per-item effective dates below",
    "items": {
        "commission": "$0 commissions for self-directed cash/margin accounts trading U.S. listed securities (including ETFs) and their options via the app or website",
        "orf_and_occ_clearing": "$0.04 per options contract (buys and sells) — the schedule states a blended ORF that may differ from the exchange fee actually paid",
        "cat_fee": "$0.0003 per options contract",
        "finra_taf": "$0.00329 per contract (options sells), rounded to the nearest penny, no greater than $9.79; effective January 1, 2026",
        "sec_regulatory_fee": "$20.60 per $1,000,000 of total principal amount of SALE, rounded up to the nearest penny; effective April 4, 2026 (the schedule notes it can be waived under certain criteria)",
    },
    "not_applicable_or_unsupported": {
        "index_options_contract_fee": "$0.50 (non-Gold) / $0.35 (Gold) per contract applies to INDEX options only; SPY/QQQ/IWM are ETF options: NOT APPLIED",
        "professional_orders": "$0.50 per contract effective October 15, 2026 for 'Professional' customers (>390 listed-options orders/day): NOT APPLIED; not supported if the account ever qualifies",
        "exercise_assignment": "NOT FOUND in the document: no exercise or assignment fee is recorded; the pilot's exit policy never carries a position to exercise",
        "sec_fee_principal_dependence": "the SEC fee depends on SALE PRINCIPAL, not a per-contract constant; the per-contract figure below assumes a $5.00 premium (the pilot's cap) and OVERSTATES it for cheaper sells by at most $0.01 after rounding",
    },
    "assumptions": ["non-Gold account tier", "non-Professional", "ETF options, not index options", "one contract", "no exercise/assignment path",
                    "SEC fee computed at the $5.00 per-share cap: 500 x 20.60 / 1,000,000 = $0.0103, rounded UP to $0.02 per the document's rounding rule"],
}

ROBINHOOD_RHF_2026_AUTHORIZATION = {
    "authorized_by": "operator", "date": "2026-09-12",
    "text": ("Operator authorization granted for the Robinhood schedule transcribed from the published PDF, digest 7f9c86bf, "
             "including SEC $20.60/million of sale principal effective 2026-04-04. Promote it from candidate to PROVIDER_VERIFIED "
             "with its provenance record and digest sealed."),
    "document_sha256": "7f9c86bf297d078ce27505cbc53eecc068cf975fbfca5aada37b9af865d7e14a",
    "scope": "the paper simulation's cost model for a Robinhood self-directed non-Gold non-Professional account trading ETF options; "
             "not an order authorization; not paper capital",
}

# v2026-09-12b: the SEC component is now computed from the ACTUAL sale principal under its own rounding rule instead
# of a fixed per-contract constant taken at the $5.00 cap. THE COMPUTATION CHANGED, so this schedule RETURNS TO
# CANDIDATE and needs operator review before it is authorized again (its v2026-09-12 authorization covered the
# transcription, not this arithmetic).
ROBINHOOD_RHF_2026 = FeeSchedule(
    schedule_id="ROBINHOOD_RHF_2026", version="2026-09-12b", provenance="PROVIDER_VERIFIED",
    commission_per_contract=0.0,
    exchange_fee_per_contract=0.04,                      # ORF + OCC clearing, buys and sells
    regulatory_fee_per_contract_buy=0.0003,              # CAT fee
    regulatory_fee_per_contract_sell=round(0.0003 + 0.00329 + 0.02, 5),   # SUPERSEDED by the sale-principal computation; kept for schedules that declare no rate
    sale_principal_rate_per_million=20.60,               # SEC regulatory fee, effective 2026-04-04, on SALE principal
    sell_per_contract_components=round(0.0003 + 0.00329, 5),   # CAT + FINRA TAF, per contract, sells (superseded by the components below)
    cat_per_contract=0.0003,                             # CAT, both sides; sub-cent rounds to zero
    taf_per_contract_sell=0.00329,                       # FINRA TAF, sells, nearest cent, effective 2026-01-01
    effective_date="2026-04-04",                         # the latest published effective date among the components
    source_document_sha256=ROBINHOOD_RHF_2026_SOURCE["document_sha256"],
    # SOURCE VERIFICATION ONLY. `verified_against` records WHICH DOCUMENT backs these terms and nothing else.
    # The superseded 2026-09-12 operator authorization is NO LONGER CARRIED HERE: it authorized a different
    # computation, and leaving it inside the schedule is what let it travel to arithmetic nobody had reviewed.
    # It is retained, unaltered, as history in ROBINHOOD_RHF_2026_SUPERSEDED_AUTHORIZATION below.
    verified_against={"provider": ROBINHOOD_RHF_2026_SOURCE["provider"], "document": ROBINHOOD_RHF_2026_SOURCE["document"],
                      "date": ROBINHOOD_RHF_2026_SOURCE["date"], "document_sha256": ROBINHOOD_RHF_2026_SOURCE["document_sha256"]},
    authorization=None,          # NOT AUTHORIZED. No operator has cleared the v2026-09-12b computation.
    note=("CANDIDATE, NOT AUTHORIZED. Broker schedule transcribed from the published PDF (source document "
          "verified, digest 7f9c86bf). The v2026-09-12b SEC computation -- exact sale principal rather than a "
          "per-contract constant -- has NOT been authorized by an operator, so this schedule is not usable and is "
          "not the live default. Per-contract round trip ~ $0.06 vs the SYNTHETIC fixture's 1.02."))

# THE COMPUTATION CHANGED (sale-principal SEC component), so the schedule is a CANDIDATE again and the live default
# reverts to UNVERIFIED until the operator reviews the new arithmetic. An unknown cost is not zero, and a changed
# cost model is not an authorized one.
# HISTORY, NOT AUTHORITY. The 2026-09-12 authorization is kept verbatim as a record of what was authorized and
# when. It is deliberately NOT attached to any schedule: it authorized the v2026-09-12 computation, and the
# arithmetic has since changed. Mutating its status in place -- which is what this module used to do -- left an
# object that read AUTHORIZED to everything that did not happen to inspect one nested key.
ROBINHOOD_RHF_2026_SUPERSEDED_AUTHORIZATION = dict(ROBINHOOD_RHF_2026_AUTHORIZATION)
ROBINHOOD_RHF_2026_SUPERSEDED_AUTHORIZATION["status"] = (
    "SUPERSEDED_BY_COMPUTATION_CHANGE: authorized the v2026-09-12 transcription; v2026-09-12b changes the SEC "
    "component from a fixed per-contract constant to the exact sale-principal computation. It does not apply.")
ROBINHOOD_RHF_2026_SUPERSEDED_AUTHORIZATION["applies_to_current_schedule"] = False

# THE DEFAULT IS NOT THE CONTROL. LIVE_DEFAULT_FEES being UNVERIFIED only governs a caller that asks for no
# schedule; a caller could always pass the candidate explicitly and be charged. The control is
# FeeSchedule.usable / assert_usable(), enforced at the boundary and the risk authority, which refuses a
# PROVIDER_VERIFIED schedule carrying no matching operator authorization however it was supplied.
LIVE_DEFAULT_FEES = UNVERIFIED_FEES          # reverted 2026-09-12 pending authorization of v2026-09-12b
