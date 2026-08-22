"""CONJUNCTION ENGINE -- simultaneous multi-mechanism configurations.

The Observatory's reason for existing: Curve says X, sector rotation says
Y, breadth is deteriorating, the options surface is repricing. Those are
not four trades. They may be one configuration.

WHAT THIS ENGINE MUST NOT DO. Conjunction is not evidence of edge. Any
five conditions co-occur sometimes; in a 164-symbol universe sampled
every cycle, rare co-occurrences are guaranteed by volume alone. This
engine REGISTERS and MEASURES conjunctions. Whether they contain
information is decided later by the outcome resolver against baselines,
and by then the conjunction must already have been recorded prospectively
or it does not count.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from apex.pattern_observatory import OBSERVATORY_POWER
from apex.pattern_observatory import independence as indep


@dataclass(frozen=True)
class Conjunction:
    pattern_id: str
    family_id: str | None
    subject: str
    market: str
    components: tuple
    component_values: dict
    first_seen: str
    last_seen: str
    duration_s: float
    quality_vector: dict
    independence: dict
    regime: str
    known_from: str
    observation_count: int = 1
    notes: tuple = ()

    def as_dict(self) -> dict:
        return {"kind": "pattern_conjunction", **self.__dict__,
                "components": list(self.components),
                "component_values": dict(self.component_values),
                "quality_vector": dict(self.quality_vector),
                "independence": dict(self.independence),
                "notes": list(self.notes),
                "conjunction_implies_edge": False,
                "decision_power": OBSERVATORY_POWER}


def pattern_id(subject: str, market: str, components: tuple) -> str:
    """CONJUNCTION identity -- content-addressed and ORDER-INDEPENDENT:
    the same set of components on the same subject is the same
    conjunction however the caller happened to order them.

    THIS IS NOT A FAMILY-SCOPED PATTERN IDENTITY. The 2026-08-20
    collision: the runtime matches MULTIPLE families against one
    conjunction (each family's required components are a subset of the
    active superset), and every family's PatternState inherited this
    conjunction-level hash verbatim -- so P004 and P006, with fully
    disjoint required components, shared one pattern_id 3 times in one
    session (92/246 rows). Family-scoped identity is family_pattern_id()
    below; PatternState uses THAT, and keeps this value separately as
    `conjunction_id` lineage."""
    payload = f"{market}|{subject}|" + "|".join(sorted(components))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


PATTERN_ID_SCHEMA_VERSION = 2


def family_pattern_id(*, family_id: str, subject: str, conjunction_id: str,
                      first_seen: str) -> str:
    """FAMILY-SCOPED pattern identity (schema v2, the collision fix).

    Semantic payload is canonical JSON with sorted keys and an explicit
    schema_version -- not concatenated strings, whose missing separators
    or field-order drift can silently alias two different identities.

    Two families born from the same conjunction at the same instant MUST
    get different ids (family_id is in the payload); the same family's
    same episode MUST get a stable id across every cycle of its life
    (first_seen never changes within an episode)."""
    import json
    payload = json.dumps({
        "schema_version": PATTERN_ID_SCHEMA_VERSION,
        "family_id": family_id,
        "subject": subject,
        "conjunction_id": conjunction_id,
        "first_seen": first_seen,
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class ConjunctionEngine:
    """Tracks live conjunctions across cycles.

    Statefulness is the point: a conjunction that has held for 40 minutes
    is a different observation from one seen once, and only a running
    engine can know the difference.
    """

    def __init__(self):
        self._live: dict = {}

    def observe(self, *, subject: str, market: str, active_components: dict,
                quality_vector: dict, regime: str, now, known_from,
                family_id: str | None = None,
                min_components: int = 2) -> Conjunction | None:
        """`active_components`: {name: value} for conditions TRUE right now."""
        import pandas as pd
        comps = tuple(sorted(active_components))
        if len(comps) < min_components:
            return None
        pid = pattern_id(subject, market, comps)
        ts = str(pd.Timestamp(now))

        prior = self._live.get(pid)
        if prior is None:
            c = Conjunction(
                pattern_id=pid, family_id=family_id, subject=subject,
                market=market, components=comps,
                component_values=dict(active_components), first_seen=ts,
                last_seen=ts, duration_s=0.0,
                quality_vector=dict(quality_vector),
                independence=indep.analyse(list(comps)), regime=regime,
                known_from=str(known_from), observation_count=1)
        else:
            dur = (pd.Timestamp(ts) - pd.Timestamp(prior.first_seen)).total_seconds()
            c = Conjunction(
                pattern_id=pid, family_id=prior.family_id or family_id,
                subject=subject, market=market, components=comps,
                component_values=dict(active_components),
                first_seen=prior.first_seen, last_seen=ts, duration_s=dur,
                quality_vector=dict(quality_vector),
                independence=indep.analyse(list(comps)), regime=regime,
                known_from=str(known_from),
                observation_count=prior.observation_count + 1)
        self._live[pid] = c
        return c

    def expire(self, *, now, max_idle_s: float = 900.0) -> list:
        """Conjunctions no longer observed. Returned so they can be
        recorded as ended -- a pattern that stops is information."""
        import pandas as pd
        gone = []
        for pid, c in list(self._live.items()):
            idle = (pd.Timestamp(now) - pd.Timestamp(c.last_seen)).total_seconds()
            if idle > max_idle_s:
                gone.append(self._live.pop(pid))
        return gone

    def live(self) -> list:
        return list(self._live.values())
