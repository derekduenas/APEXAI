"""OpportunityIntelligenceGraph — F10. Proves the graph is append-only
and immutable, edges cannot forward-reference missing nodes, and the
four required questions (WHY DID I ENTER / PERSIST / WHAT HURT / WHY
DID I DIE) are answerable purely by walking typed edges.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2.opportunity_graph import (ProvenanceError, add_edge,
                                              add_node, new_graph)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def test_new_graph_starts_empty():
    g = new_graph("OPP-1", "NVDA", known_from=T0, now=T0)
    assert g.nodes == () and g.edges == ()
    assert g.why_did_i_enter() == ()


def test_add_node_returns_a_new_graph_original_unchanged():
    g0 = new_graph("OPP-1", "NVDA", known_from=T0, now=T0)
    g1 = add_node(g0, "scout:1", "SCOUT_ABNORMALITY", artifact_hash="abc123",
                 summary="gap flagged", now=T0)
    assert g0.nodes == ()                    # original untouched -- immutable
    assert len(g1.nodes) == 1


def test_duplicate_node_id_refused():
    g = new_graph("OPP-1", "NVDA", known_from=T0, now=T0)
    g = add_node(g, "n1", "CURVE", artifact_hash=None, summary="x", now=T0)
    with pytest.raises(ProvenanceError):
        add_node(g, "n1", "CURVE", artifact_hash=None, summary="y", now=T0)


def test_edge_cannot_forward_reference_a_missing_node():
    g = new_graph("OPP-1", "NVDA", known_from=T0, now=T0)
    g = add_node(g, "n1", "CURVE", artifact_hash=None, summary="x", now=T0)
    with pytest.raises(ProvenanceError):
        add_edge(g, "SUPPORTED", "n1", "n2_does_not_exist", reason="x", now=T0)


def test_unknown_node_type_refused():
    g = new_graph("OPP-1", "NVDA", known_from=T0, now=T0)
    with pytest.raises(ProvenanceError):
        add_node(g, "n1", "NOT_A_REAL_TYPE", artifact_hash=None, summary="x", now=T0)


def test_unknown_edge_type_refused():
    g = new_graph("OPP-1", "NVDA", known_from=T0, now=T0)
    g = add_node(g, "n1", "CURVE", artifact_hash=None, summary="x", now=T0)
    g = add_node(g, "n2", "CURVE", artifact_hash=None, summary="y", now=T0)
    with pytest.raises(ProvenanceError):
        add_edge(g, "NOT_A_REAL_EDGE", "n1", "n2", reason="x", now=T0)


def test_the_four_required_questions():
    g = new_graph("OPP-1", "NVDA", known_from=T0, now=T0)
    g = add_node(g, "scout:gap", "SCOUT_ABNORMALITY", artifact_hash="h1",
                summary="gap flagged (later shown corrupted)", now=T0)
    g = add_node(g, "rs:module", "HUNTER_MECHANISM", artifact_hash="h2",
                summary="RS told a different story", now=T0)
    g = add_node(g, "curve:t5", "CURVE", artifact_hash="h3",
                summary="NEGATIVE_TRANSITION", now=T0)
    g = add_node(g, "captain:t11", "CAPTAIN_SHADOW", artifact_hash="h4",
                summary="INVALIDATE", now=T0)
    g = add_node(g, "root", "CAPTAIN_SHADOW", artifact_hash=None,
                summary="opportunity entry", now=T0)

    g = add_edge(g, "CAUSED_ATTENTION", "scout:gap", "root",
                reason="the corrupted gap signal is what drew attention",
                now=T0)
    g = add_edge(g, "CONTRADICTED", "rs:module", "root",
                reason="RS disagreed with the gap-driven attention",
                now=T0 + pd.Timedelta(minutes=1))
    g = add_edge(g, "SUPPORTED", "curve:t5", "root",
                reason="curvature confirmed the negative transition",
                now=T0 + pd.Timedelta(minutes=5))
    g = add_edge(g, "INVALIDATED", "captain:t11", "root",
                reason="direction reversed at t11", now=T0 + pd.Timedelta(minutes=11))

    assert g.why_did_i_enter() == ("scout:gap",)
    assert g.what_hurt_the_thesis() == ("rs:module",)
    assert g.why_did_i_persist() == ("curve:t5",)
    assert g.why_did_i_die() == ("captain:t11",)


def test_a_never_invalidated_candidate_has_no_death_reason():
    g = new_graph("OPP-2", "AAPL", known_from=T0, now=T0)
    g = add_node(g, "n1", "CURVE", artifact_hash=None, summary="x", now=T0)
    assert g.why_did_i_die() == ()


def test_artifact_hash_is_a_reference_not_copied_content():
    """The node stores only the hash, never the full source record."""
    g = new_graph("OPP-1", "NVDA", known_from=T0, now=T0)
    g = add_node(g, "n1", "CURVE", artifact_hash="deadbeef1234",
                summary="short label only", now=T0)
    rec = g.nodes[0]
    assert rec["artifact_hash"] == "deadbeef1234"
    assert "dimensions" not in rec           # no copied Curve internals


def test_decision_power_always_stamped():
    g = new_graph("OPP-1", "NVDA", known_from=T0, now=T0)
    assert g.decision_power == "NONE_FRONTIER_SHADOW"


def test_determinism_same_build_sequence_twice_byte_identical():
    def build():
        g = new_graph("OPP-1", "NVDA", known_from=T0, now=T0)
        g = add_node(g, "n1", "CURVE", artifact_hash="h1", summary="x", now=T0)
        g = add_node(g, "n2", "CURVE", artifact_hash="h2", summary="y", now=T0)
        return add_edge(g, "SUPPORTED", "n1", "n2", reason="r", now=T0)
    assert build().as_record() == build().as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.opportunity_graph as og
    monkeypatch.setattr(og, "LEDGER", tmp_path / "og.jsonl")
    g = new_graph("OPP-1", "NVDA", known_from=T0, now=T0)
    rec1 = og.persist(g)
    rec2 = og.persist(g)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
