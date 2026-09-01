"""NUMERIC INTEGRITY — the money path's arithmetic must be real.

Two contracts live here, both fail-closed:

  BOOK_NUMERIC_INTEGRITY_V2  every number the Book writes must be a
                             real number in its declared domain, so a
                             malformed value can never be sealed into
                             an append-only ledger.
  RISK_INPUT_INTEGRITY_V2    every number the Risk Kernel compares
                             against a limit must be independently
                             validated by the kernel, because the
                             kernel owns the survival veto and cannot
                             delegate the trustworthiness of the
                             quantities its comparisons depend on.

WHY THIS EXISTS. NaN is a float. It passes `isinstance(v, float)`, it
survives `round()`, it propagates silently through `sum()`, and it
defeats EVERY `>` and `<=` comparison by returning False. One NaN
`executable_pnl` therefore disabled the session drawdown halt AND the
available-capital check simultaneously, with no error and no log line
(defect BOOK-NAN-POISON / RISK-002). A negative size passes every
upper-bound comparison for the same structural reason.

The law: A MALFORMED NUMBER IS NOT A SMALL NUMBER. It is an absence of
information, and absence must refuse, never approve.

decision_power: VALIDATION_ONLY -- this module can only reject.
"""
from __future__ import annotations

import math

BOOK_CONTRACT = "BOOK_NUMERIC_INTEGRITY_V2"
RISK_CONTRACT = "RISK_INPUT_INTEGRITY_V2"

# The one legitimate non-numeric value in the money path. An execution
# failure is the ABSENCE OF A MARKET, not a zero, and collapsing it to
# 0.0 would silently claim a flat trade that never happened.
NOT_ESTIMABLE = "NOT_ESTIMABLE"

# domain kinds
POSITIVE = "finite, > 0"
NON_NEGATIVE = "finite, >= 0"
SIGNED = "finite, sign unrestricted"
UNIT_FRACTION = "finite, 0 < v <= 1"


class NumericIntegrityViolation(ValueError):
    """Raised at the write boundary. Never caught to substitute a
    default -- a default here would be a fabricated number."""


# ------------------------------------------------------------ domains
# Each domain is derived from what the quantity MEANS, not from what
# has happened to appear in the ledger so far.
BOOK_DOMAINS = {
    # a position risking zero or less is not a position
    "declared_risk": POSITIVE,
    "funded_risk": POSITIVE,
    # 1.0 == FUND, 0.5 == FUND_REDUCED; a fraction above 1 would fund
    # more than the candidate declared
    "funding_fraction": UNIT_FRACTION,
    # prices and sizes
    "entry_fill": POSITIVE,
    "stop": POSITIVE,
    "quantity": POSITIVE,
    "net_debit": POSITIVE,
    # a loss is negative and a win is positive: sign carries meaning,
    # so this one may NOT be constrained to non-negative
    "executable_pnl": SIGNED,
}

RISK_DOMAINS = {
    "declared_risk": POSITIVE,
    # sums over open positions; zero when the book is flat
    "open_risk": NON_NEGATIVE,
    "same_underlying_risk": NON_NEGATIVE,
    "same_family_risk": NON_NEGATIVE,
    # MUST allow negative -- a drawdown halt that cannot see a negative
    # number is not a drawdown halt
    "session_realized_pnl": SIGNED,
    # may legitimately go negative once realized losses exceed the
    # starting capital; that state must refuse, not be clamped
    "available_capital": SIGNED,
}


def is_real_number(value) -> bool:
    """True only for a genuine finite number. bool is excluded on
    purpose: True == 1 would otherwise pass as a dollar amount."""
    return (not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value))


def why_invalid(name: str, value, domain: str) -> str | None:
    """The named reason this value may not be used, or None if it is
    sound. Returns a reason string rather than a bare bool so every
    refusal can quote its own cause."""
    if isinstance(value, bool):
        return (f"{name}: {value!r} is a bool, not a monetary "
                f"quantity -- True would silently act as 1")
    if value is None:
        return f"{name}: None is an absence of information, not a value"
    if not isinstance(value, (int, float)):
        return (f"{name}: {value!r} is {type(value).__name__}, not a "
                f"number")
    if math.isnan(value):
        return (f"{name}: NaN defeats every comparison silently -- it "
                f"would DISABLE the limit rather than trip it")
    if math.isinf(value):
        return f"{name}: {value!r} is infinite, not a real quantity"
    if domain is POSITIVE and value <= 0:
        return f"{name}: {value!r} must be > 0 ({POSITIVE})"
    if domain is NON_NEGATIVE and value < 0:
        return f"{name}: {value!r} must be >= 0 ({NON_NEGATIVE})"
    if domain is UNIT_FRACTION and not 0 < value <= 1:
        return f"{name}: {value!r} must satisfy {UNIT_FRACTION}"
    return None


# ------------------------------------------- BOOK_NUMERIC_INTEGRITY_V2

def validate_book_numbers(record: dict, *,
                          allow_not_estimable: bool = False) -> list:
    """Every numeric field this record carries, checked against its
    domain. Returns the list of named violations; empty means sound.

    Nested sleeve_payload numbers are validated too: entry_fill, stop,
    quantity and net_debit are the inputs the risk certificate is
    computed from, so a malformed one produces a false economic bound
    rather than a visible error."""
    violations = []
    payload = record.get("sleeve_payload")
    scopes = [("", record)]
    if isinstance(payload, dict):
        scopes.append(("sleeve_payload.", payload))

    for prefix, scope in scopes:
        for field, domain in BOOK_DOMAINS.items():
            if field not in scope:
                continue
            value = scope[field]
            if (allow_not_estimable and field == "executable_pnl"
                    and value == NOT_ESTIMABLE):
                continue           # the named sentinel, not a number
            reason = why_invalid(prefix + field, value, domain)
            if reason:
                violations.append(reason)
    return violations


def require_book_numbers(record: dict, *,
                         allow_not_estimable: bool = False) -> None:
    """Write boundary. Raises rather than returning, because a caller
    that ignored a return value is exactly how the first NaN got
    sealed into the chain."""
    violations = validate_book_numbers(
        record, allow_not_estimable=allow_not_estimable)
    if violations:
        raise NumericIntegrityViolation(
            f"{BOOK_CONTRACT} refused the write: "
            + "; ".join(violations))


def scan_ledger_integrity(rows: list) -> dict:
    """Read boundary. Historical rows sealed before this contract
    existed cannot be rewritten -- corrections append, history is never
    edited -- so state() reports contamination instead of hiding it."""
    contaminated = []
    for r in rows:
        violations = validate_book_numbers(r, allow_not_estimable=True)
        if violations:
            contaminated.append({"kind": r.get("kind"),
                                 "candidate_id": r.get("candidate_id"),
                                 "violations": violations})
    return {"contract": BOOK_CONTRACT,
            "integrity": "CLEAN" if not contaminated else "CONTAMINATED",
            "contaminated_records": contaminated}


# --------------------------------------------- RISK_INPUT_INTEGRITY_V2

def validate_risk_inputs(**inputs) -> list:
    """The kernel's own validation of every quantity it will compare
    against a limit. Independent by design: Arena's Candidate checks
    are ergonomics for the arena, not this contract."""
    violations = []
    for field, domain in RISK_DOMAINS.items():
        if field not in inputs:
            violations.append(
                f"{field}: absent -- the kernel may not compare a "
                f"limit against a missing quantity")
            continue
        reason = why_invalid(field, inputs[field], domain)
        if reason:
            violations.append(reason)
    return violations
