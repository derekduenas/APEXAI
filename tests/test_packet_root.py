"""Tamper battery for PULSE_CYCLE_PACKET_ROOT_V1.

Each test is a way PULSE_V0's count-only binding could have been
defeated without breaking its chain.
"""
from __future__ import annotations

import copy

import pytest

from apex.pulse.packet_root import (PacketRootViolation, compute,
                                    cycle_commitment, merkle_root,
                                    verify)


def _packets(n=308):
    return [{"state_id": f"{i:032x}", "packet_hash": f"{i:064x}"}
            for i in range(n)]


def _commit(pkts):
    return cycle_commitment(cycle_id="c1",
                            scheduled_time="2026-09-01T08:00:00+00:00",
                            packets=pkts, prev_cycle_hash="GENESIS")


def test_honest_set_verifies():
    p = _packets()
    assert verify(_commit(p), p)["VALID"]


def test_packet_payload_altered_breaks_root():
    p = _packets()
    c = _commit(p)
    t = copy.deepcopy(p)
    t[100]["packet_hash"] = "f" * 64          # recomputed after tamper
    r = verify(c, t)
    assert not r["VALID"]
    assert not r["packet_root_matches"]


def test_packet_removed_breaks_root():
    p = _packets()
    c = _commit(p)
    t = [x for x in p if x["state_id"] != p[7]["state_id"]]
    r = verify(c, t)
    assert not r["VALID"]
    assert not r["packet_count_matches"]


def test_packet_inserted_breaks_root():
    p = _packets()
    c = _commit(p)
    t = p + [{"state_id": "f" * 32, "packet_hash": "e" * 64}]
    assert not verify(c, t)["VALID"]


def test_reordering_does_not_change_root():
    """Canonical ordering: write order must not matter."""
    p = _packets(64)
    c = _commit(p)
    assert verify(c, list(reversed(p)))["VALID"]


def test_swapping_contents_between_two_packets_breaks_root():
    """Both hashes still present, but bound to the wrong identities."""
    p = _packets(64)
    c = _commit(p)
    t = copy.deepcopy(p)
    t[3]["packet_hash"], t[9]["packet_hash"] = (
        t[9]["packet_hash"], t[3]["packet_hash"])
    assert not verify(c, t)["VALID"]


def test_count_preserved_but_substituted_breaks_root():
    """The exact attack count-only binding could not see."""
    p = _packets(32)
    c = _commit(p)
    t = copy.deepcopy(p)
    t[0] = {"state_id": "a" * 32, "packet_hash": "b" * 64}
    r = verify(c, t)
    assert r["packet_count_matches"]      # count still 32
    assert not r["VALID"]                 # but the root moved


def test_duplicate_state_id_refused():
    p = _packets(4)
    p.append(dict(p[0]))
    with pytest.raises(PacketRootViolation):
        compute(p)


def test_missing_fields_refused():
    with pytest.raises(PacketRootViolation):
        compute([{"state_id": "a"}])


def test_odd_leaf_promotion_not_duplication():
    """Guards CVE-2012-2459-style duplicate-leaf ambiguity."""
    a, b, c = ("1" * 64, "2" * 64, "3" * 64)
    assert merkle_root([a, b, c]) != merkle_root([a, b, c, c])


def test_empty_set_has_a_defined_root():
    assert compute([])["packet_root"] == merkle_root([])


def test_commitment_carries_root_into_the_chained_body():
    """Because packet_root sits inside the body chain_append hashes,
    the existing ledger primitive needs no modification."""
    c = _commit(_packets(8))
    assert "packet_root" in c
    assert c["prev_cycle_hash"] == "GENESIS"
    assert c["packet_count"] == 8


def test_pulse_v0_scale():
    p = _packets(308)
    c = _commit(p)
    assert c["packet_count"] == 308
    assert verify(c, p)["VALID"]
