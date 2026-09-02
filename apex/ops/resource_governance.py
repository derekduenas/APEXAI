"""APEX_RESOURCE_GOVERNANCE_V1 -- intentional resource placement.

THE LAW THIS ENCODES
--------------------
CREDIBLE CONCURRENT WORKING SET + SYSTEM RESERVE + REQUIRED HEADROOM
MUST FIT PHYSICAL RESOURCES UNDER THE WORST SUPPORTED OPERATING REGIME.

Aggregate MemoryMax MAY exceed physical RAM, but ONLY where workload
non-concurrency is explicitly PROVEN and recorded. Never on average
utilisation, and never on hope.

WHY THIS MODULE EXISTS
----------------------
On 2026-09-01 apex-pulse.service ran in system.slice with
MemoryMax=infinity. It reached 2.5-4.1 GB, the 8 GB host exhausted, and
the kernel's GLOBAL OOM killer chose which APEX organ died -- 77 times.
146 of the 148 global OOM events in retained history came from services
that were in system.slice with no bound. Containment was not merely
weak; it was absent, and the kernel became the arbiter of which part of
the trading organism survived.

Every number here is MEASURED, not chosen for roundness. Limits are
derived by headroom_plan() from observed peaks with an explicit
multiplier, and the whole plan is refused if it does not fit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

GOVERNANCE_VERSION = "APEX_RESOURCE_GOVERNANCE_V1"
MiB = 1024 * 1024


class Criticality(Enum):
    """Ordered by what must survive when the host is under pressure.

    Lower ordinal == protect harder. Research and background must yield
    BEFORE factual input, evidence writers and risk/execution.
    """
    CRITICAL_FACTUAL_INPUT = 0      # live market sensing
    CRITICAL_EVIDENCE_WRITER = 1    # append-only canonical truth
    RISK_EXECUTION_CRITICAL = 2     # capital protection / authorisation
    DECISION_INFERENCE = 3          # future World Model / PRIME runtime
    RESEARCH = 4                    # expendable compute
    BACKGROUND = 5                  # maintenance, acquisition

    @property
    def yields_under_pressure(self) -> bool:
        return self in (Criticality.RESEARCH, Criticality.BACKGROUND)


class Lifecycle(Enum):
    ACTIVE_REQUIRED = "ACTIVE_REQUIRED"
    INACTIVE_FUTURE = "INACTIVE_FUTURE"
    DECOMMISSIONED = "DECOMMISSIONED"
    LEGACY = "LEGACY"


@dataclass(frozen=True)
class ServiceSpec:
    unit: str
    criticality: Criticality
    lifecycle: Lifecycle
    slice_name: str
    observed_peak_bytes: int | None      # MEASURED, None if never run
    memory_high: int | None              # throttle threshold
    memory_max: int | None               # hard containment
    concurrent: bool = True              # runs alongside the others?
    canonical_writer: bool = False
    note: str = ""

    def __post_init__(self):
        if self.lifecycle is Lifecycle.ACTIVE_REQUIRED:
            if self.memory_max is None:
                raise GovernanceViolation(
                    f"{self.unit}: ACTIVE_REQUIRED with no MemoryMax -- "
                    "this is precisely the apex-pulse defect")
            if not self.slice_name.startswith("apex"):
                raise GovernanceViolation(
                    f"{self.unit}: ACTIVE_REQUIRED outside the governed "
                    f"apex.slice hierarchy (slice={self.slice_name})")
        if (self.memory_high is not None and self.memory_max is not None
                and self.memory_high > self.memory_max):
            raise GovernanceViolation(
                f"{self.unit}: MemoryHigh > MemoryMax is incoherent")


class GovernanceViolation(Exception):
    """Raised when a plan would permit what the law forbids."""


@dataclass
class HostBudget:
    """Measured host facts. Nothing here is assumed."""
    ram_bytes: int
    swap_bytes: int
    non_apex_baseline_bytes: int         # measured, not guessed
    kernel_cache_reserve_bytes: int      # explicit, derived
    note: str = ""

    @property
    def allocatable_bytes(self) -> int:
        return (self.ram_bytes - self.non_apex_baseline_bytes
                - self.kernel_cache_reserve_bytes)

    @property
    def has_swap_buffer(self) -> bool:
        """Zero swap means pressure goes straight to SIGKILL with no
        degraded intermediate state. That is why PULSE was killed
        rather than slowed."""
        return self.swap_bytes > 0


@dataclass
class Plan:
    host: HostBudget
    services: list[ServiceSpec] = field(default_factory=list)
    proven_exclusive: set[frozenset] = field(default_factory=set)

    # -- the arithmetic that actually matters -------------------------
    def concurrent_services(self) -> list[ServiceSpec]:
        return [s for s in self.services
                if s.lifecycle is Lifecycle.ACTIVE_REQUIRED
                and s.concurrent]

    def credible_concurrent_working_set(self) -> int:
        """Sum of MEASURED peaks for services that genuinely run
        together. This -- not the sum of caps -- is the quantity that
        must fit."""
        return sum(s.observed_peak_bytes or 0
                   for s in self.concurrent_services())

    def worst_case_containment(self) -> int:
        """Sum of hard maxima for concurrent services: the most the
        cgroups would ever ALLOW simultaneously."""
        return sum(s.memory_max or 0 for s in self.concurrent_services())

    def is_exclusive(self, a: str, b: str) -> bool:
        return frozenset((a, b)) in self.proven_exclusive

    def validate(self) -> dict:
        """Refuse any plan under which a plausible concurrency state
        could produce global OOM."""
        findings, fatal = [], []

        for s in self.services:
            if (s.lifecycle is not Lifecycle.DECOMMISSIONED
                    and s.memory_max is None
                    and not s.slice_name.startswith("apex")):
                fatal.append(
                    f"{s.unit}: ungoverned ({s.slice_name}, no "
                    f"MemoryMax) -- a future global-OOM landmine even "
                    f"if it is not running today")
            if (s.observed_peak_bytes and s.memory_max
                    and s.observed_peak_bytes >= s.memory_max):
                findings.append(
                    f"{s.unit}: observed peak {s.observed_peak_bytes} "
                    f">= MemoryMax {s.memory_max} -- the service has "
                    f"REACHED its containment boundary. A MemoryMax is "
                    f"a boundary, not a lifecycle mechanism.")

        working = self.credible_concurrent_working_set()
        allocatable = self.host.allocatable_bytes
        if working > allocatable:
            fatal.append(
                f"credible concurrent working set {working} exceeds "
                f"allocatable {allocatable}")

        worst = self.worst_case_containment()
        if worst > allocatable:
            findings.append(
                f"aggregate MemoryMax {worst} exceeds allocatable "
                f"{allocatable}. Permitted ONLY where non-concurrency "
                f"is proven; {len(self.proven_exclusive)} exclusivity "
                f"pair(s) recorded.")
            if not self.proven_exclusive:
                fatal.append(
                    "aggregate MemoryMax exceeds allocatable with NO "
                    "proven exclusivity -- a plausible concurrency "
                    "state could cause global OOM")

        if not self.host.has_swap_buffer:
            findings.append(
                "host has ZERO swap: memory pressure produces SIGKILL "
                "with no degraded intermediate state. Swap is an "
                "airbag, never permission to exceed bounds.")

        return {
            "version": GOVERNANCE_VERSION,
            "ram_bytes": self.host.ram_bytes,
            "non_apex_baseline_bytes": self.host.non_apex_baseline_bytes,
            "kernel_cache_reserve_bytes":
                self.host.kernel_cache_reserve_bytes,
            "allocatable_bytes": allocatable,
            "credible_concurrent_working_set": working,
            "worst_case_containment": worst,
            "headroom_bytes": allocatable - working,
            "GLOBAL_OOM_STRUCTURALLY_CONTAINED": not fatal,
            "fatal": fatal,
            "findings": findings,
        }

    def enforce(self) -> None:
        r = self.validate()
        if r["fatal"]:
            raise GovernanceViolation("; ".join(r["fatal"]))

    def ungoverned(self) -> list[ServiceSpec]:
        return [s for s in self.services
                if not s.slice_name.startswith("apex")
                and s.lifecycle is not Lifecycle.DECOMMISSIONED]

    def active_ungoverned_critical(self) -> list[ServiceSpec]:
        return [s for s in self.ungoverned()
                if s.lifecycle is Lifecycle.ACTIVE_REQUIRED
                and s.criticality.value <= 2]

    def yields_before(self, a: str, b: str) -> bool:
        """Does `a` yield to `b` under memory pressure?"""
        sa = self.get(a)
        sb = self.get(b)
        return sa.criticality.value > sb.criticality.value

    def get(self, unit: str) -> ServiceSpec:
        for s in self.services:
            if s.unit == unit:
                return s
        raise KeyError(unit)


def headroom_plan(observed_peak: int, *, multiplier: float = 1.5,
                  floor: int = 128 * MiB) -> tuple[int, int]:
    """Derive (MemoryHigh, MemoryMax) from a MEASURED peak.

    MemoryHigh = throttle threshold, set AT the observed peak so the
    kernel begins reclaiming before containment.
    MemoryMax  = hard boundary, observed peak x multiplier.

    Deliberately NOT a round number: the input is evidence.
    """
    if observed_peak <= 0:
        raise ValueError("headroom_plan requires a measured peak")
    high = max(observed_peak, floor)
    hard = max(int(observed_peak * multiplier), floor)
    return high, hard
