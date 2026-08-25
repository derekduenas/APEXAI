"""MARKET STATE GENOME — everything causally knowable at one instant.

One lineage-preserving research object per decision timestamp. The
genome is what makes discovery scientifically possible: an analog
engine, a hypothesis tournament and an edge surface can only be honest
if the state they reason over carries its own provenance.

GENOME LAW
    Every field preserves value, event_time, known_from, source,
    pedigree, quality and authority. UNKNOWN remains UNKNOWN. No
    forward-filling across causal boundaries without explicit
    authorization. No field may appear more precise than its source.
    Only the current correction lineage is EDGEFORGE_ELIGIBLE --
    known-corrupted labels are forbidden as inputs, full stop.

The genome does not interpret. A field named `trend_state` holds what
the commissioned faculty said, stamped with which faculty said it. The
genome flattening provenance away would quietly launder every upstream
uncertainty into false confidence, which is the exact failure the V2
uncertainty work exists to prevent.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"
UNKNOWN = "UNKNOWN"

DOMAINS = ("TIME", "UNDERLYING", "VOLATILITY", "OPTIONS", "BTC",
           "EXECUTION", "CROSS_MARKET", "EVENT", "PREDATOR_OUTPUT")

QUALITY_LEVELS = ("FULL", "LIMITED", UNKNOWN)


class GenomeViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class GenomeField:
    name: str
    value: object
    event_time: str | None
    known_from: str
    source: str
    pedigree: str
    quality: str = "FULL"
    authority: str = "NONE"
    forward_filled: bool = False

    def __post_init__(self):
        if self.quality not in QUALITY_LEVELS:
            raise GenomeViolation(
                f"{self.name}: quality {self.quality!r} is not declared")
        if self.forward_filled:
            raise GenomeViolation(
                f"{self.name}: forward-filling across causal boundaries "
                f"requires explicit authorization, which does not exist")

    def as_record(self) -> dict:
        return asdict(self)


@dataclass
class MarketStateGenome:
    subject: str
    T: str                            # the causal boundary, ET-naive str
    session: str
    source_lineage: str               # e.g. DAY1_CORRECTED, LIVE_SEALED
    fields: dict = field(default_factory=dict)   # domain -> name -> GenomeField
    eligibility: str = "EDGEFORGE_ELIGIBLE"
    law: str = ("UNKNOWN remains UNKNOWN; no field appears more precise "
                "than its source; superseded labels are forbidden")
    decision_power: str = "NONE_RESEARCH"

    def __post_init__(self):
        # THE ELIGIBILITY GATE. A genome built from a superseded or
        # defective resolution is refused at construction -- the first
        # dataset EdgeForge ever sees must not contain labels we know
        # are wrong.
        bad = ("SUPERSEDED", "DEFECTIVE", "CORRUPTED", "MISLABELLED")
        if any(b in self.source_lineage.upper() for b in bad):
            raise GenomeViolation(
                f"source lineage {self.source_lineage!r} is not "
                f"EDGEFORGE_ELIGIBLE: known-corrupted labels are "
                f"forbidden as research inputs")

    # ------------------------------------------------------------ build
    def add(self, domain: str, name: str, value, *, known_from: str,
            source: str, pedigree: str, event_time: str | None = None,
            quality: str = "FULL", authority: str = "NONE") -> None:
        if domain not in DOMAINS:
            raise GenomeViolation(f"unknown genome domain {domain!r}")
        gf = GenomeField(name=name, value=value, event_time=event_time,
                         known_from=known_from, source=source,
                         pedigree=pedigree, quality=quality,
                         authority=authority)
        self.fields.setdefault(domain, {})[name] = gf

    def get(self, domain: str, name: str) -> GenomeField | None:
        return self.fields.get(domain, {}).get(name)

    # ---------------------------------------------------------- consume
    def vector(self, wanted: list) -> dict:
        """Numeric research view of selected (domain, name) fields.

        UNKNOWN and non-numeric values are EXCLUDED and REPORTED, never
        imputed -- missingness is data, and an analog engine that
        silently zero-fills a missing funding rate has invented a
        market that never existed."""
        values, missing, excluded = {}, [], []
        for dom, name in wanted:
            gf = self.get(dom, name)
            key = f"{dom}.{name}"
            if gf is None:
                missing.append(key)
                continue
            if gf.value in (UNKNOWN, NOT_ESTIMABLE, None) or \
                    not isinstance(gf.value, (int, float, bool)):
                excluded.append({"field": key, "value": str(gf.value),
                                 "quality": gf.quality})
                continue
            values[key] = float(gf.value)
        n_wanted = len(wanted)
        return {"values": values,
                "coverage": round(len(values) / n_wanted, 4)
                if n_wanted else 0.0,
                "missing": missing, "excluded_non_numeric": excluded,
                "law": "missingness is data; nothing was imputed"}

    def state_hash(self) -> str:
        body = {d: {n: f.as_record() for n, f in fs.items()}
                for d, fs in sorted(self.fields.items())}
        return hashlib.sha256(json.dumps(
            {"subject": self.subject, "T": self.T, "fields": body},
            sort_keys=True, default=str).encode()).hexdigest()

    def as_record(self) -> dict:
        return {"kind": "market_state_genome", "subject": self.subject,
                "T": self.T, "session": self.session,
                "source_lineage": self.source_lineage,
                "state_hash": self.state_hash(),
                "n_fields": sum(len(f) for f in self.fields.values()),
                "domains": {d: sorted(fs) for d, fs in
                            self.fields.items()},
                "fields": {d: {n: f.as_record() for n, f in fs.items()}
                           for d, fs in self.fields.items()},
                "eligibility": self.eligibility, "law": self.law,
                "decision_power": self.decision_power}
