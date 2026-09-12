"""ECONOMIC RISK SEMANTICS — a label is not a risk bound, and an
upstream aggregate is not a primary fact.

THE THREE QUANTITIES, PERMANENTLY DISTINCT:
  planned_risk_amount   what the sleeve intended to lose. Sizing.
  certified_max_loss    what the structure makes economically possible
                        in the worst case, DERIVED FROM PRIMARY FACTS.
  realized_pnl          what the market did. Measured after.

RISK-003 was `declared_risk` treated as a bound. The first repair moved
the trust to `net_debit` -- better, but still one upstream scalar that
both the certificate producer and Risk consumed. A wrong `net_debit`
produced a perfectly self-consistent certificate. So the bound is now
DERIVED FROM THE LEG ECONOMICS and the upstream aggregate is treated as
a CLAIM TO BE CHECKED, never as an input to trust.

CERTIFIED-RISK AUTHORITY (operator decision):
  DEFINED_MAX_LOSS  eligible for certified risk and PRIME V0.
  STOP_DEFINED      research / paper only. No certified authority.
  UNBOUNDED         research / paper only. No certified authority.
  NOT_ESTIMABLE     refused.
An unbounded position is not made bounded by a smaller label, and no
notional cap converts one into the other.

WHY A DEBIT VERTICAL IS NOT CERTIFIABLE HERE. A debit vertical's loss
is bounded by its debit ONLY AT EXPIRY. Every card in this system
carries a pre-expiry exit rule (the options pilot's EXIT_AT_HORIZON_15M_V1
exits 15 minutes after fill at quoted sides; the legacy protocol closed at
session close), so the short leg must be BOUGHT BACK: the close realises
(long bid - short ask), which can be negative, and the loss then
exceeds the debit by an amount set by two bid/ask spreads that are not
knowable at decision time. A long SINGLE option has no such exposure --
it is sold at a bid that cannot go below zero, so the debit remains a
true ceiling under any exit rule. That asymmetry is the whole reason
one is certifiable and the other is not.

decision_power: MEASUREMENT_ONLY.
"""
from __future__ import annotations

import hashlib
import json

from apex.organism.numeric_integrity import (POSITIVE, is_real_number,
                                             why_invalid)

CERTIFICATE_VERSION = "RISK_CERTIFICATE_V0"
SEMANTICS_VERSION = "ECONOMIC_RISK_SEMANTICS_V1"

DEFINED_MAX_LOSS = "DEFINED_MAX_LOSS"
STOP_DEFINED = "STOP_DEFINED"
UNBOUNDED = "UNBOUNDED"
NOT_ESTIMABLE = "NOT_ESTIMABLE"

CERTIFIED_RISK_AUTHORITY = {DEFINED_MAX_LOSS: True, STOP_DEFINED: False,
                            UNBOUNDED: False, NOT_ESTIMABLE: False}
RESEARCH_OBSERVATION_ONLY = (STOP_DEFINED, UNBOUNDED)

LONG_OPTION = ("LONG_CALL", "LONG_PUT")
VERTICAL = ("CALL_VERTICAL", "PUT_VERTICAL")
SUPPORTED = LONG_OPTION + VERTICAL + ("STOCK",)

EQUITY_MULTIPLIER = 1.0
OPTION_MULTIPLIER = 100.0

# `contracts` is recorded NOWHERE in the options ledger. It is not
# invented here: the protocol default is declared, and the debit
# derived under it is cross-checked against the independently recorded
# aggregate. A card whose true size differs will FAIL that check and
# refuse rather than be silently mis-sized.
PROTOCOL_DEFAULT_CONTRACTS = 1
CONTRACTS_BASIS_DEFAULT = ("PROTOCOL_DEFAULT_UNRECORDED_1 -- contracts "
                           "is not a recorded field; the derived debit "
                           "is cross-checked against the independently "
                           "sealed aggregate, so a mis-sized card "
                           "fails closed")

# No commission or regulatory-fee schedule exists anywhere in this
# repository for options. Nothing is invented; the omission is named.
FEE_TREATMENT = {
    "entry_fees": "NOT_RECORDED_IN_ANY_APEX_ARTIFACT",
    "exit_fees": "NOT_RECORDED_IN_ANY_APEX_ARTIFACT",
    "exercise_assignment_fees": "NOT_APPLICABLE -- the pre-declared "
                                "exit rule closes BEFORE expiry (15 min "
                                "after fill in the pilot; session close "
                                "in the legacy protocol), so no position "
                                "is carried to exercise",
    "fees_on_the_max_loss_path": "AN EXIT TRADE OCCURS on the max-loss "
                                 "path under any close-before-expiry "
                                 "exit rule, so entry AND exit fees "
                                 "both necessarily occur",
    "consequence": "certified_max_loss is PRE-FEE. It is a bound on "
                   "the option payoff loss, NOT total economic max "
                   "loss. No fee buffer is invented.",
}
CERTIFICATION_COMPLETENESS = "PRE_FEE"

GAP_REPORT_POINTS = (0.005, 0.01, 0.02, 0.05)

KNOWN_UNBOUNDABLE = {
    "BTC_PERP":
        "no contract specification (multiplier / point value) is "
        "recorded anywhere in this repository for PBTCUCZ50, so no "
        "dollar bound can be derived; apex/organism/"
        "path_intelligence.py already holds the standing rule that a "
        "multiplier is never guessed. REMEDY: the BTC sleeve must "
        "record its contract specification.",
}

LONG_OPTION_BASIS = (
    "a long single option's maximum loss is the net debit paid. The "
    "holder owns a right, carries no assignment obligation, and an "
    "early close sells at a bid that cannot be negative -- so no "
    "market path and no exit rule takes more than the premium.")

VERTICAL_NOT_CERTIFIABLE = (
    "a debit vertical is bounded by its debit ONLY AT EXPIRY. The "
    "pre-declared exit rule closes BEFORE EXPIRY at quoted sides (the pilot "
    "exits 15 minutes after fill; the legacy protocol at session close), "
    "which requires BUYING BACK the short leg: the close realises "
    "(long bid - short ask), which can be negative, and the loss then "
    "exceeds the debit by two bid/ask spreads that are NOT KNOWABLE "
    "from state available at decision time. Under a hold-to-expiry "
    "exit rule this same structure WOULD be DEFINED_MAX_LOSS.")

STOCK_LONG_BASIS = (
    "a long equity position's structural maximum loss is its full "
    "notional, reached if the security goes to zero. The protective "
    "stop reduces the EXPECTED loss but guarantees no fill price.")

STOCK_SHORT_BASIS = (
    "a short equity position has NO structural maximum loss: the "
    "repurchase price has no upper bound, and the stop is an order "
    "requiring a willing counterparty, not a guarantee.")


def certificate_hash(cert: dict) -> str:
    material = {k: cert.get(k) for k in
                ("certificate_version", "semantics_version",
                 "expression", "direction", "risk_class",
                 "certified_max_loss", "planned_risk_amount",
                 "gross_notional", "certified_risk_authority",
                 "prime_v0_eligible", "certification_completeness",
                 "inputs", "derivation")}
    return hashlib.sha256(
        json.dumps(material, sort_keys=True,
                   default=str).encode()).hexdigest()


def _seal(cert: dict) -> dict:
    cert["certificate_hash"] = certificate_hash(cert)
    return cert


def _collect(declared_risk, payload) -> dict:
    """Every raw fact a bound may be derived from, echoed verbatim."""
    legs = payload.get("legs")
    return {"declared_risk": declared_risk,
            "legs": ([list(x) for x in legs]
                     if isinstance(legs, (list, tuple)) else legs),
            "expiration": payload.get("expiration"),
            "contracts": payload.get("contracts"),
            "multiplier": payload.get("multiplier"),
            "net_debit_claimed": payload.get("net_debit"),
            "entry_fill": payload.get("entry_fill"),
            "stop": payload.get("stop"),
            "quantity": payload.get("quantity"),
            "entry_cost_per_share": payload.get("entry_cost_per_share"),
            "stop_exit_cost_per_share":
                payload.get("stop_exit_cost_per_share")}


def _base(expression, direction, inputs, risk_class) -> dict:
    authority = CERTIFIED_RISK_AUTHORITY[risk_class]
    return {"kind": "risk_certificate",
            "certificate_version": CERTIFICATE_VERSION,
            "semantics_version": SEMANTICS_VERSION,
            "expression": expression, "direction": direction,
            "risk_class": risk_class,
            "certified_risk_authority": authority,
            "prime_v0_eligible": authority,
            "research_observation_only":
                risk_class in RESEARCH_OBSERVATION_ONLY,
            "certification_completeness":
                CERTIFICATION_COMPLETENESS if authority else "NONE",
            "fee_treatment": FEE_TREATMENT,
            "inputs": inputs,
            "decision_power": "MEASUREMENT_ONLY"}


def _fail(expression, direction, refusals, inputs) -> dict:
    c = _base(expression, direction, inputs, NOT_ESTIMABLE)
    c.update({"certified_max_loss": None,
              "certified_basis": "no bound could be derived",
              "structural_worst_case": None,
              "planned_risk_amount": inputs.get("declared_risk"),
              "planned_risk_basis": "UNVERIFIED_UPSTREAM_LABEL",
              "planned_risk_components": None,
              "upstream_declared_risk": inputs.get("declared_risk"),
              "derivation": None,
              "label_equals_bound": None, "gross_notional": None,
              "gap_exposed": None, "gap_loss": None,
              "refusals": refusals,
              "law": "a position has no recognized risk budget until "
                     "its actual expression produces a deterministic, "
                     "auditable economic-risk certificate derived "
                     "from primary facts"})
    return _seal(c)


# ------------------------------------------- PRIMARY-FACT DERIVATION

def derive_from_legs(legs, *, multiplier, contracts) -> dict:
    """Net debit/credit from the leg economics themselves.

    A leg is (action, right, strike, price). BUY pays, SELL receives.
    This is the PRIMARY fact; any upstream aggregate is a claim to be
    checked against it."""
    problems, per_contract = [], 0.0
    if not isinstance(legs, (list, tuple)) or not legs:
        return {"ok": False,
                "problems": ["LEGS_ABSENT: no leg economics were "
                             "supplied, so no bound can be derived "
                             "from primary facts"]}
    for i, leg in enumerate(legs):
        if not isinstance(leg, (list, tuple)) or len(leg) < 4:
            problems.append(f"LEG_MALFORMED[{i}]: {leg!r} is not "
                            f"(action, right, strike, price)")
            continue
        action, right, strike, price = leg[0], leg[1], leg[2], leg[3]
        if action not in ("BUY", "SELL"):
            problems.append(f"LEG_SIDE_INVALID[{i}]: {action!r}")
        for name, v in (("strike", strike), ("price", price)):
            bad = why_invalid(f"leg[{i}].{name}", v, POSITIVE)
            if bad:
                problems.append(bad)
        if not problems:
            per_contract += price if action == "BUY" else -price
    if problems:
        return {"ok": False, "problems": problems}
    return {"ok": True,
            "per_contract_net": round(per_contract, 6),
            "derived_net_debit": round(
                per_contract * multiplier * contracts, 2),
            "multiplier": multiplier, "contracts": contracts,
            "leg_count": len(legs),
            "formula": "sum(+price if BUY else -price) x multiplier "
                       "x contracts"}


def certify(*, expression, direction, declared_risk,
            sleeve_payload: dict | None = None) -> dict:
    """Issue the economic-risk certificate for one position."""
    payload = sleeve_payload if isinstance(sleeve_payload, dict) else {}
    inputs = _collect(declared_risk, payload)

    if expression in KNOWN_UNBOUNDABLE:
        return _fail(expression, direction,
                     [f"UNBOUNDABLE_{expression}: "
                      + KNOWN_UNBOUNDABLE[expression]], inputs)
    if expression not in SUPPORTED:
        return _fail(expression, direction,
                     [f"expression {expression!r} has no bound formula "
                      f"in {CERTIFICATE_VERSION}; supported: "
                      f"{', '.join(SUPPORTED)}"], inputs)
    if expression in LONG_OPTION + VERTICAL:
        return _certify_option(expression, direction, declared_risk,
                               payload, inputs)
    return _certify_stock(expression, direction, declared_risk,
                          payload, inputs)


def _certify_option(expression, direction, declared_risk, payload,
                    inputs) -> dict:
    mult = payload.get("multiplier")
    if mult is None:
        mult = OPTION_MULTIPLIER
    elif not is_real_number(mult) or float(mult) != OPTION_MULTIPLIER:
        return _fail(expression, direction,
                     [f"MULTIPLIER_DISAGREEMENT: payload declares "
                      f"{mult!r} but a listed option contract is "
                      f"{OPTION_MULTIPLIER}"], inputs)
    contracts = payload.get("contracts")
    contracts_basis = "RECORDED"
    if contracts is None:
        contracts, contracts_basis = (PROTOCOL_DEFAULT_CONTRACTS,
                                      CONTRACTS_BASIS_DEFAULT)
    elif not is_real_number(contracts) or contracts <= 0:
        return _fail(expression, direction,
                     [f"CONTRACTS_INVALID: {contracts!r} is not a "
                      f"positive number"], inputs)

    d = derive_from_legs(payload.get("legs"), multiplier=float(mult),
                         contracts=float(contracts))
    if not d["ok"]:
        return _fail(expression, direction, d["problems"], inputs)
    d["contracts_basis"] = contracts_basis

    derived = d["derived_net_debit"]
    if derived <= 0:
        return _fail(expression, direction,
                     [f"NOT_A_DEBIT: leg economics net to "
                      f"{derived:.2f}; only a DEBIT structure has its "
                      f"loss bounded by what was paid"], inputs)

    # THE UPSTREAM AGGREGATE IS A CLAIM, NOT AN INPUT. If it disagrees
    # with the primary facts, no bound is issued -- this is the check
    # that a wrong net_debit could previously walk straight through.
    claimed = payload.get("net_debit")
    if claimed is not None:
        if not is_real_number(claimed):
            return _fail(expression, direction,
                         [f"NET_DEBIT_CLAIM_MALFORMED: {claimed!r}"],
                         inputs)
        if round(float(claimed), 2) != derived:
            return _fail(expression, direction,
                         [f"PRIMARY_FACT_DISAGREEMENT: upstream claims "
                          f"net_debit {float(claimed):.2f} but the leg "
                          f"economics derive {derived:.2f} "
                          f"({d['formula']}). The aggregate is not "
                          f"trusted over the legs."], inputs)

    if expression in VERTICAL:
        c = _fail(expression, direction,
                  [f"NOT_CERTIFIABLE_UNDER_THIS_EXIT_RULE: "
                   + VERTICAL_NOT_CERTIFIABLE], inputs)
        c["derivation"] = d
        c["bound_at_expiry_only"] = derived
        return _seal(c)

    cert = _base(expression, direction, inputs, DEFINED_MAX_LOSS)
    cert.update({
        "certified_max_loss": derived,
        "certified_basis": LONG_OPTION_BASIS,
        "structural_worst_case": derived,
        "derivation": d,
        "planned_risk_amount": derived,
        "planned_risk_basis":
            "for a long option the planned loss and the structural "
            "bound are the same number: the debit derived from legs",
        "planned_risk_components": {
            "derived_net_debit": derived,
            "per_contract_net": d["per_contract_net"],
            "multiplier": d["multiplier"], "contracts": d["contracts"],
            "contracts_basis": contracts_basis,
            "fees": FEE_TREATMENT},
        "upstream_declared_risk": declared_risk,
        "label_equals_bound": (is_real_number(declared_risk)
                               and round(float(declared_risk), 2)
                               == derived),
        "gross_notional": derived,
        "gap_exposed": False, "gap_loss": None, "refusals": [],
        "law": "the bound is derived from the contract's own legs, "
               "never accepted from an upstream total"})
    return _seal(cert)


def canonical_planned_risk(*, entry_fill, stop, quantity,
                           exit_cost_per_share=None,
                           entry_cost_per_share=None,
                           multiplier=EQUITY_MULTIPLIER) -> dict:
    """RISK-005. The canonical planned loss at the structural stop.

    DO NOT COUNT ENTRY SLIPPAGE TWICE: `entry_fill` is an EXECUTABLE
    fill that already crossed the spread, so the distance from it to
    the stop already contains the entry crossing. Only the EXIT
    crossing may be added."""
    stop_distance = abs(entry_fill - stop)
    # UNKNOWN IS NEVER ZERO (risk path): an unknown exit friction previously read as FRICTIONLESS and UNDERSTATED the
    # planned loss at the stop. An unknown friction now returns NOT_ESTIMABLE; a declared zero must be passed as 0.0.
    if exit_cost_per_share is None:
        return {"planned_risk_amount": None, "status": "NOT_ESTIMABLE",
                "why": ("EXIT_FRICTION_UNKNOWN: the planned loss at the stop includes the exit crossing; an unknown exit "
                        "cost is not a zero exit cost. Pass 0.0 explicitly to declare a frictionless exit."),
                "stop_distance": stop_distance, "quantity": quantity, "multiplier": multiplier}
    exit_friction = float(exit_cost_per_share)
    per_share = stop_distance + exit_friction
    entry_slip = (None if entry_cost_per_share is None
                  else round(entry_cost_per_share * quantity
                             * multiplier, 2))
    return {
        "planned_risk_amount": round(per_share * quantity * multiplier,
                                     2),
        "components": {
            "stop_distance_per_share": round(stop_distance, 6),
            "exit_friction_per_share": round(exit_friction, 6),
            "quantity": quantity, "multiplier": multiplier,
            "entry_slippage_already_inside_entry_fill": entry_slip,
            "entry_fees": "NOT_MODELLED_IN_THIS_MONEY_PATH",
            "exit_fees": "NOT_MODELLED_IN_THIS_MONEY_PATH"},
        "basis": "CANONICAL_V1: |executable_entry - stop| * quantity * "
                 "multiplier + modelled EXIT friction only; the entry "
                 "crossing is already embedded in the executable fill "
                 "and is never added again"}


def _certify_stock(expression, direction, declared_risk, payload,
                   inputs) -> dict:
    refusals = []
    for field in ("entry_fill", "quantity"):
        reason = why_invalid(field, payload.get(field), POSITIVE)
        if reason:
            refusals.append(reason)
    if refusals:
        return _fail(expression, direction, refusals, inputs)
    up = str(direction).upper()
    if up not in ("LONG", "SHORT"):
        return _fail(expression, direction,
                     [f"direction {direction!r} is neither LONG nor "
                      f"SHORT, so no bound can be assigned"], inputs)

    notional = float(payload["entry_fill"]) * float(payload["quantity"])
    risk_class = UNBOUNDED if up == "SHORT" else STOP_DEFINED
    cert = _base(expression, direction, inputs, risk_class)

    planned = None
    if is_real_number(payload.get("stop")):
        planned = canonical_planned_risk(
            entry_fill=float(payload["entry_fill"]),
            stop=float(payload["stop"]),
            quantity=float(payload["quantity"]),
            exit_cost_per_share=payload.get("stop_exit_cost_per_share"),
            entry_cost_per_share=payload.get("entry_cost_per_share"))

    cert.update({
        "certified_max_loss": None,
        "certified_basis": (STOCK_SHORT_BASIS if up == "SHORT"
                            else STOCK_LONG_BASIS)
        + " NO CERTIFIED MAX-LOSS AUTHORITY: research / paper "
          "observation only until STOP_DEFINED_RISK_MODEL_V1 is "
          "separately promoted on real gap and slippage evidence.",
        "structural_worst_case": (None if up == "SHORT"
                                  else round(notional, 2)),
        "derivation": None,
        "planned_risk_amount": (declared_risk if planned is None
                                else planned["planned_risk_amount"]),
        "planned_risk_basis": ("UNVERIFIED_UPSTREAM_LABEL"
                               if planned is None else planned["basis"]),
        "planned_risk_components": (None if planned is None
                                    else planned["components"]),
        "upstream_declared_risk": declared_risk,
        "label_equals_bound": False,
        "gross_notional": round(notional, 2),
        "gap_exposed": True,
        "gap_loss": {f"{int(g * 1000) / 10}%": round(notional * g, 2)
                     for g in GAP_REPORT_POINTS},
        "refusals": [],
        "law": "a stop yields an INTENDED maximum loss, never a "
               "GUARANTEED one"})
    return _seal(cert)


# ------------------------------------------------ INDEPENDENT VERIFY

def verify(certificate, *, expression, direction, declared_risk,
           sleeve_payload) -> list:
    """Recompute from PRIMARY FACTS and report every disagreement.
    Upstream certificate generation is NOT authority."""
    if not isinstance(certificate, dict):
        return [f"certificate is {type(certificate).__name__}, "
                f"not a certificate"]
    if certificate.get("certificate_version") != CERTIFICATE_VERSION:
        return [f"certificate_version "
                f"{certificate.get('certificate_version')!r} is not "
                f"{CERTIFICATE_VERSION}"]

    problems = []
    if certificate.get("certificate_hash") != \
            certificate_hash(certificate):
        problems.append(
            "CERTIFICATE_HASH_MISMATCH: a load-bearing field was "
            "altered after the certificate was sealed")

    fresh = certify(expression=expression, direction=direction,
                    declared_risk=declared_risk,
                    sleeve_payload=sleeve_payload)
    for field in ("expression", "direction", "risk_class",
                  "certified_max_loss", "planned_risk_amount",
                  "gross_notional", "certified_risk_authority",
                  "prime_v0_eligible", "certification_completeness",
                  "derivation"):
        if certificate.get(field) != fresh.get(field):
            problems.append(
                f"RECOMPUTATION_DISAGREEMENT on {field}: certificate "
                f"says {certificate.get(field)!r}, independent "
                f"recomputation from primary facts says "
                f"{fresh.get(field)!r}")

    echoed = certificate.get("inputs")
    actual = _collect(declared_risk,
                      sleeve_payload if isinstance(sleeve_payload, dict)
                      else {})
    if echoed != actual:
        differing = sorted(k for k in actual
                           if (echoed or {}).get(k) != actual[k])
        problems.append(
            f"CERTIFICATE_IS_FOR_A_DIFFERENT_POSITION: echoed inputs "
            f"disagree with the facts handed to Risk on {differing}")
    return problems
