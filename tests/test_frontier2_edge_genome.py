"""EdgeGenome — F11. Proves every domain starts UNATTRIBUTED, a real
status is mechanically impossible without a real basis, and no numeric
attribution field exists anywhere in the schema.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2.edge_genome import (DOMAINS, SCHEMA_ONLY_BASIS,
                                        DomainAttribution, EdgeGenomeError,
                                        new_genome, set_domain_attribution)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def test_new_genome_has_all_thirteen_domains_unattributed():
    g = new_genome("C1", known_from=T0, now=T0)
    assert set(g.domains.keys()) == set(DOMAINS)
    assert g.fully_unattributed() is True
    for d in g.domains.values():
        assert d["status"] == "UNATTRIBUTED"
        assert d["basis"] == SCHEMA_ONLY_BASIS


def test_real_status_without_real_basis_refused():
    with pytest.raises(EdgeGenomeError):
        DomainAttribution(domain="curvature", status="SUPPORTED")


def test_real_status_with_real_basis_is_allowed():
    da = DomainAttribution(domain="curvature", status="LIKELY",
                           basis="post-resolution residual analysis (methodology TBD)")
    assert da.status == "LIKELY"


def test_unknown_domain_refused():
    with pytest.raises(EdgeGenomeError):
        DomainAttribution(domain="NOT_A_REAL_DOMAIN")


def test_unknown_status_refused():
    with pytest.raises(EdgeGenomeError):
        DomainAttribution(domain="curvature", status="DEFINITELY", basis="x")


def test_set_domain_attribution_is_append_only_new_object():
    g0 = new_genome("C1", known_from=T0, now=T0)
    g1 = set_domain_attribution(g0, "curvature", "UNCERTAIN",
                                basis="some real basis text",
                                known_from=T0, now=T0)
    assert g0.domains["curvature"]["status"] == "UNATTRIBUTED"   # unchanged
    assert g1.domains["curvature"]["status"] == "UNCERTAIN"
    assert g1.fully_unattributed() is False


def test_set_domain_attribution_unknown_domain_refused():
    g = new_genome("C1", known_from=T0, now=T0)
    with pytest.raises(EdgeGenomeError):
        set_domain_attribution(g, "NOT_A_DOMAIN", "LIKELY", basis="x",
                              known_from=T0, now=T0)


def test_no_numeric_attribution_field_anywhere():
    forbidden = {"weight", "pct", "fraction", "economic_attribution_frac",
                "score", "contribution"}
    assert not (set(DomainAttribution.__dataclass_fields__) & forbidden)
    g = new_genome("C1", known_from=T0, now=T0)
    from apex.frontier2.edge_genome import EdgeGenome
    assert not (set(EdgeGenome.__dataclass_fields__) & forbidden)


def test_determinism_same_build_twice_byte_identical():
    a = new_genome("C1", known_from=T0, now=T0)
    b = new_genome("C1", known_from=T0, now=T0)
    assert a.as_record() == b.as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.edge_genome as eg
    monkeypatch.setattr(eg, "LEDGER", tmp_path / "eg.jsonl")
    g = new_genome("C1", known_from=T0, now=T0)
    rec1 = eg.persist(g)
    rec2 = eg.persist(g)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
