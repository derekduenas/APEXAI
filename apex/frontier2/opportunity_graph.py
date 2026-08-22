"""OpportunityIntelligenceGraph — F10: every candidate can answer WHY
DID I ENTER, WHAT KEPT ME HERE, WHAT WEAKENED ME, WHAT KILLED ME -- by
walking a provenance DAG, not by re-reading a mutable narrative.

Directly targets the Day-1 lesson named in the operator's directive: a
watchlist name entering because of a corrupted GAP signal while
legitimate RS told a different story is now a STRUCTURAL question the
graph can answer (which node CAUSED_ATTENTION, and does a later node
CONTRADICT it), not something that has to be reconstructed from logs
after the fact.

APPEND-ONLY, IMMUTABLE: `add_node`/`add_edge` are pure functions that
return a NEW graph (frozen dataclasses -- there is no `.append()` to
call). Nodes reference `artifact_hash` -- the `entry_hash` a source
ledger record already carries -- rather than copying that record's
content into the graph, so nothing here can drift out of sync with the
ledger it points at.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/opportunity_graph_ledger.jsonl")

NODE_TYPES = ("RAW_OBSERVATION", "VALID_FEATURE", "SCOUT_ABNORMALITY",
             "HUNTER_MECHANISM", "CURVE", "EXPECTATION_VIOLATION",
             "PARTICIPANT_PRESSURE", "PROPAGATION", "LEADING_EDGE",
             "WORLD_LAB", "MODEL_MARKET", "ASSASSIN2", "CAPTAIN_SHADOW")

EDGE_TYPES = ("CAUSED_ATTENTION", "SUPPORTED", "CONTRADICTED", "INVALIDATED",
             "SUPERSEDED", "TRIGGERED_REVIEW")


class ProvenanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProvenanceNode:
    node_id: str
    node_type: str
    artifact_hash: str | None
    summary: str
    as_of: str

    def __post_init__(self):
        if self.node_type not in NODE_TYPES:
            raise ProvenanceError(f"unknown node_type {self.node_type!r}")

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProvenanceEdge:
    edge_type: str
    source_node_id: str
    target_node_id: str
    reason: str
    known_from: str

    def __post_init__(self):
        if self.edge_type not in EDGE_TYPES:
            raise ProvenanceError(f"unknown edge_type {self.edge_type!r}")

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OpportunityIntelligenceGraph:
    opportunity_id: str
    subject: str
    nodes: tuple
    edges: tuple
    known_from: str
    as_of: str
    decision_power: str = FRONTIER2_POWER

    def as_record(self) -> dict:
        return {"kind": "opportunity_intelligence_graph",
               "opportunity_id": self.opportunity_id, "subject": self.subject,
               "nodes": [n for n in self.nodes], "edges": [e for e in self.edges],
               "known_from": self.known_from, "as_of": self.as_of,
               "decision_power": self.decision_power}

    def _sources_of(self, edge_type: str) -> tuple:
        return tuple(e["source_node_id"] for e in self.edges
                    if e["edge_type"] == edge_type)

    def why_did_i_enter(self) -> tuple:
        return self._sources_of("CAUSED_ATTENTION")

    def why_did_i_persist(self) -> tuple:
        return self._sources_of("SUPPORTED")

    def what_hurt_the_thesis(self) -> tuple:
        return self._sources_of("CONTRADICTED")

    def why_did_i_die(self) -> tuple:
        return self._sources_of("INVALIDATED")


def new_graph(opportunity_id: str, subject: str, *, known_from, now
             ) -> OpportunityIntelligenceGraph:
    import pandas as pd
    now = pd.Timestamp(now)
    return OpportunityIntelligenceGraph(
        opportunity_id=opportunity_id, subject=subject, nodes=(), edges=(),
        known_from=str(pd.Timestamp(known_from)), as_of=str(now))


def add_node(graph: OpportunityIntelligenceGraph, node_id: str, node_type: str,
            *, artifact_hash: str | None, summary: str, now
            ) -> OpportunityIntelligenceGraph:
    import pandas as pd
    if any(n["node_id"] == node_id for n in graph.nodes):
        raise ProvenanceError(f"node_id {node_id!r} already exists -- "
                              f"nodes are append-only and never overwritten")
    n = ProvenanceNode(node_id=node_id, node_type=node_type,
                      artifact_hash=artifact_hash, summary=summary,
                      as_of=str(pd.Timestamp(now)))
    return OpportunityIntelligenceGraph(
        opportunity_id=graph.opportunity_id, subject=graph.subject,
        nodes=graph.nodes + (n.as_record(),), edges=graph.edges,
        known_from=graph.known_from, as_of=str(pd.Timestamp(now)))


def add_edge(graph: OpportunityIntelligenceGraph, edge_type: str,
            source_node_id: str, target_node_id: str, *, reason: str, now
            ) -> OpportunityIntelligenceGraph:
    import pandas as pd
    ids = {n["node_id"] for n in graph.nodes}
    missing = {source_node_id, target_node_id} - ids
    if missing:
        raise ProvenanceError(
            f"edge references node(s) not in the graph: {missing} -- "
            f"add_node() first, an edge cannot forward-reference")
    e = ProvenanceEdge(edge_type=edge_type, source_node_id=source_node_id,
                       target_node_id=target_node_id, reason=reason,
                       known_from=str(pd.Timestamp(now)))
    return OpportunityIntelligenceGraph(
        opportunity_id=graph.opportunity_id, subject=graph.subject,
        nodes=graph.nodes, edges=graph.edges + (e.as_record(),),
        known_from=graph.known_from, as_of=str(pd.Timestamp(now)))


def persist(graph: OpportunityIntelligenceGraph) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, graph.as_record())
