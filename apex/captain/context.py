"""CaptainMarketContextPacket — ONE STATE, MULTIPLE CONSUMERS.

EYES-1 WS3. The Captain's high-resolution sensory packet, and the single
object the Flight Deck renders, the chart snapshot is drawn from, and the
visual challenger indirectly sees.

THE LAW: this module ASSEMBLES, it does not COMPUTE. Every strategy
number here is copied from the canonical record that already produced it
(ChartState, RelativeStrengthState, world_state, assassin_review,
capital_decision). Recomputing a VWAP here would create a second source
of truth, and a cockpit that disagrees with the engine is worse than no
cockpit — it is a confident lie.

Everything sourced from the broker or added for perception carries
`decision_power = NONE_OBSERVATIONAL_EPOCH1`. Nothing in Epoch 1 consumes
those fields; they exist to be measured prospectively so a later epoch can
earn the right to use them.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

OBSERVATIONAL = "NONE_OBSERVATIONAL_EPOCH1"

HEALTHY, DEGRADED, PARTIAL, REFUSED = ("HEALTHY", "DEGRADED", "PARTIAL",
                                       "REFUSED")


@dataclass(frozen=True)
class Facet:
    """A single sensed quantity with the provenance the Twin contract
    requires. `value=None` means UNKNOWN — never zero, never neutral."""
    value: object
    source: str
    event_time: str | None = None
    known_from: str | None = None
    freshness_s: float | None = None
    quality: str = "UNKNOWN"
    coverage: str | None = None
    status: str = "OK"

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CaptainMarketContextPacket:
    # --- identity / time
    symbol: str
    decision_id: str
    as_of_time: str
    last_market_timestamp: str | None
    context_created_at: str
    data_age_seconds: float | None
    session_state: str
    evidence_class: str

    # --- canonical strategy state, COPIED not recomputed
    chart_state: dict = field(default_factory=dict)
    relative_strength: dict = field(default_factory=dict)
    world: dict = field(default_factory=dict)

    # --- oracle / adversary / money, as already decided upstream
    oracle: dict = field(default_factory=dict)
    assassin: dict = field(default_factory=dict)
    capital: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)

    # --- perception-only enrichment (broker microscope, L2, fundamentals)
    microscope: dict = field(default_factory=dict)

    # --- packet health: explicit, never a scalar confidence
    health: str = HEALTHY
    health_reasons: tuple = ()
    decision_power: str = OBSERVATIONAL

    def as_record(self) -> dict:
        rec = asdict(self)
        rec["packet_hash"] = self.packet_hash()
        return rec

    def packet_hash(self) -> str:
        body = {k: v for k, v in asdict(self).items()}
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _age(as_of, last) -> float | None:
    if not last:
        return None
    import pandas as pd
    try:
        return round((pd.Timestamp(as_of) - pd.Timestamp(last)).total_seconds(), 1)
    except Exception:                                       # noqa: BLE001
        return None


def assemble(*, decision: dict, world_record: dict | None = None,
             assassin_record: dict | None = None,
             capital_record: dict | None = None,
             bundle_record: dict | None = None,
             microscope: dict | None = None,
             session_state: str = "REGULAR",
             as_of: str | None = None) -> CaptainMarketContextPacket:
    """Build the packet from PERSISTED canonical records.

    Deliberately takes records, not live engines: the packet must be
    reproducible from the archive alone, which is what makes the Flight
    Deck and the challenger replayable and auditable after the fact.
    """
    import pandas as pd
    as_of = as_of or str(decision.get("t_utc") or pd.Timestamp.now(tz="UTC"))
    cs = decision.get("chart_state") or {}
    last_bar = cs.get("last_bar_time") or decision.get("last_market_timestamp")

    reasons: list = []
    health = HEALTHY
    if cs.get("data_quality"):
        health = DEGRADED
        reasons.append(f"chart data_quality: {list(cs['data_quality'])[:4]}")
    if not cs:
        health = REFUSED
        reasons.append("no ChartState: the packet has no market to describe")
    if world_record is None:
        health = PARTIAL if health == HEALTHY else health
        reasons.append("world state absent")
    if microscope and microscope.get("status") not in (None, "OK"):
        health = PARTIAL if health == HEALTHY else health
        reasons.append(f"microscope {microscope.get('status')}")

    return CaptainMarketContextPacket(
        symbol=decision.get("symbol", "UNKNOWN"),
        decision_id=decision.get("decision_id", "UNKNOWN"),
        as_of_time=as_of,
        last_market_timestamp=str(last_bar) if last_bar else None,
        context_created_at=str(pd.Timestamp.now(tz="UTC")),
        data_age_seconds=_age(as_of, last_bar),
        session_state=session_state,
        evidence_class=decision.get("evidence_class", "UNKNOWN"),
        chart_state=cs,
        relative_strength=decision.get("relative_strength") or {},
        world=world_record or {},
        oracle={k: (bundle_record or {}).get(k)
                for k in ("analog_view", "ml_view", "swarm_view",
                          "disagreement", "distribution_source_status")},
        assassin=assassin_record or {},
        capital=capital_record or {},
        options={},
        microscope=microscope or {"status": "NOT_REQUESTED"},
        health=health,
        health_reasons=tuple(reasons),
    )
