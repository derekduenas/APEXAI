"""EdgeGenome — F11: the schema for eventually learning which organs
actually contribute economic value, built now, populated by nobody yet.

THE LAW: no domain may carry a real attribution status (SUPPORTED,
LIKELY, UNCERTAIN) without a real, named `basis` string -- the
placeholder basis SCHEMA_ONLY_NO_ATTRIBUTION_METHODOLOGY_YET is
mechanically incompatible with anything but UNATTRIBUTED (enforced at
construction, not by convention). There is no numeric field anywhere in
this module -- no percentage, no weight, no economic_attribution_frac --
because "no forced numeric attribution" and "economic attribution must
remain absent until real economic cohorts exist" both mean the same
thing: this is a vocabulary, not a calculation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/edge_genome_ledger.jsonl")

DOMAINS = ("selection", "curvature", "relative_strength", "regime",
          "participant_pressure", "propagation", "timing", "entry",
          "execution", "event_context", "expression", "risk", "unattributed")

ATTRIBUTION_STATUSES = ("SUPPORTED", "LIKELY", "UNCERTAIN", "UNATTRIBUTED")

SCHEMA_ONLY_BASIS = "SCHEMA_ONLY_NO_ATTRIBUTION_METHODOLOGY_YET"


class EdgeGenomeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DomainAttribution:
    domain: str
    status: str = "UNATTRIBUTED"
    basis: str = SCHEMA_ONLY_BASIS
    known_from: str | None = None

    def __post_init__(self):
        if self.domain not in DOMAINS:
            raise EdgeGenomeError(f"unknown domain {self.domain!r}")
        if self.status not in ATTRIBUTION_STATUSES:
            raise EdgeGenomeError(f"unknown status {self.status!r}")
        if self.status != "UNATTRIBUTED" and self.basis == SCHEMA_ONLY_BASIS:
            raise EdgeGenomeError(
                f"domain {self.domain!r} claims status {self.status!r} "
                f"but carries the schema-only placeholder basis -- a "
                f"real attribution needs a real, named basis")

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EdgeGenome:
    candidate_id: str
    domains: dict
    known_from: str
    as_of: str
    decision_power: str = FRONTIER2_POWER

    def as_record(self) -> dict:
        return {"kind": "edge_genome", "candidate_id": self.candidate_id,
               "domains": dict(self.domains), "known_from": self.known_from,
               "as_of": self.as_of, "decision_power": self.decision_power}

    def fully_unattributed(self) -> bool:
        return all(d["status"] == "UNATTRIBUTED" for d in self.domains.values())


def new_genome(candidate_id: str, *, known_from, now) -> EdgeGenome:
    import pandas as pd
    now = pd.Timestamp(now)
    domains = {d: DomainAttribution(domain=d, known_from=str(pd.Timestamp(known_from))
                                    ).as_record() for d in DOMAINS}
    return EdgeGenome(candidate_id=candidate_id, domains=domains,
                      known_from=str(pd.Timestamp(known_from)), as_of=str(now))


def set_domain_attribution(genome: EdgeGenome, domain: str, status: str, *,
                           basis: str, known_from, now) -> EdgeGenome:
    """Returns a NEW EdgeGenome -- append-only, same discipline as F10.
    Refuses (via DomainAttribution.__post_init__) a real status without
    a real basis."""
    import pandas as pd
    if domain not in genome.domains:
        raise EdgeGenomeError(f"domain {domain!r} not in this genome")
    da = DomainAttribution(domain=domain, status=status, basis=basis,
                           known_from=str(pd.Timestamp(known_from)))
    new_domains = dict(genome.domains)
    new_domains[domain] = da.as_record()
    return EdgeGenome(candidate_id=genome.candidate_id, domains=new_domains,
                      known_from=genome.known_from, as_of=str(pd.Timestamp(now)))


def persist(genome: EdgeGenome) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, genome.as_record())
