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

from dataclasses import dataclass, field

from .clock import is_real
from .records import canonical_hash

FEE_PROVENANCE = ("SYNTHETIC_FIXTURE", "PROVIDER_VERIFIED", "UNVERIFIED")


class FeePolicyRefused(ValueError):
    pass


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

    def describe(self) -> dict:
        return {"schedule_id": self.schedule_id, "version": self.version, "provenance": self.provenance,
                "commission_per_contract": self.commission_per_contract,
                "exchange_fee_per_contract": self.exchange_fee_per_contract,
                "regulatory_fee_per_contract_buy": self.regulatory_fee_per_contract_buy,
                "regulatory_fee_per_contract_sell": self.regulatory_fee_per_contract_sell,
                "verified_against": self.verified_against, "note": self.note}

    def _side(self, contracts: int, side: str) -> dict:
        if type(contracts) is not int or contracts < 0:
            raise FeePolicyRefused("CONTRACTS_INVALID: %r" % (contracts,))
        if not self.known:
            return {"total": None, "status": "UNKNOWN", "why": "fee schedule %s is UNVERIFIED; an unknown cost is not zero"
                    % self.schedule_id, "schedule_id": self.schedule_id, "schedule_hash": self.schedule_hash, "side": side}
        reg = self.regulatory_fee_per_contract_buy if side == "BUY" else self.regulatory_fee_per_contract_sell
        comps = {"commission": round(self.commission_per_contract * contracts, 4),
                 "exchange": round(self.exchange_fee_per_contract * contracts, 4),
                 "regulatory": round(reg * contracts, 4)}
        return {"total": round(sum(comps.values()), 2), "components": comps, "status": "CHARGED" if contracts else "NONE",
                "schedule_id": self.schedule_id, "schedule_hash": self.schedule_hash, "side": side, "contracts": contracts}

    def entry(self, contracts: int) -> dict:
        return self._side(contracts, "BUY")

    def exit(self, contracts: int) -> dict:
        return self._side(contracts, "SELL")


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


def recompute_fees(record_fee_block: dict, schedule: FeeSchedule, *, contracts: int, side: str) -> list:
    """Independent recomputation for the Book: disagreements are named."""
    problems = []
    if not isinstance(record_fee_block, dict):
        return ["FEE_BLOCK_MISSING"]
    if record_fee_block.get("schedule_id") != schedule.schedule_id or record_fee_block.get("schedule_hash") != schedule.schedule_hash:
        problems.append("FEE_SCHEDULE_IDENTITY_DISAGREES: record %r/%r vs %r/%r" % (
            record_fee_block.get("schedule_id"), str(record_fee_block.get("schedule_hash"))[:12],
            schedule.schedule_id, schedule.schedule_hash[:12]))
    fresh = schedule._side(contracts, side)
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
