"""PULSE_CYCLE_PACKET_ROOT_V1 -- bind packets to the chained cycle.

THE GAP THIS CLOSES
-------------------
PULSE_V0 chain-appended only cycle_log.jsonl. market_twin.jsonl was a
plain append whose packets carried a self-covering packet_hash but were
bound to the chained cycle record by COUNT ALONE
(packets_sealed / packets_written). So 2.1 GB of factual evidence could
have had a packet altered, removed or inserted -- with packet_hash
recomputed -- and nothing in the chain would break.

Here each cycle commits to its authoritative packet SET via a Merkle
root over canonically ordered packet hashes. Altering, inserting,
removing or REORDERING a packet changes the root, which changes the
cycle's entry_hash, which breaks the chain from that cycle onward.

Canonical ordering is by state_id, so the root is independent of the
order packets happened to be written in, but NOT independent of which
packets are present.
"""
from __future__ import annotations

import hashlib
import json

PACKET_ROOT_VERSION = "PULSE_CYCLE_PACKET_ROOT_V1"
_LEAF = b"\x00"
_NODE = b"\x01"


class PacketRootViolation(Exception):
    pass


def _h(*parts: bytes) -> str:
    d = hashlib.sha256()
    for p in parts:
        d.update(p)
    return d.hexdigest()


def leaf_digest(state_id: str, packet_hash: str) -> str:
    """Domain-separated leaf: binds identity to content.

    The state_id is included so that swapping two packets' CONTENTS
    while keeping both hashes present still changes the tree.
    """
    return _h(_LEAF, state_id.encode(), b"|", packet_hash.encode())


def merkle_root(leaves: list[str]) -> str:
    """Standard binary Merkle root with domain separation.

    An odd node is promoted rather than duplicated, avoiding the
    CVE-2012-2459 duplicate-leaf ambiguity where two different leaf
    sets can produce the same root.
    """
    if not leaves:
        return _h(_LEAF, b"EMPTY")
    level = list(leaves)
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(_h(_NODE, level[i].encode(), level[i + 1].encode()))
        if len(level) % 2:
            nxt.append(level[-1])          # promote, never duplicate
        level = nxt
    return level[0]


def compute(packets: list[dict]) -> dict:
    """Build the cycle's packet commitment.

    `packets` need only carry state_id and packet_hash.
    """
    rows = []
    seen = set()
    for p in packets:
        sid = p.get("state_id")
        ph = p.get("packet_hash")
        if not sid or not ph:
            raise PacketRootViolation(
                "every packet must carry state_id and packet_hash")
        if sid in seen:
            raise PacketRootViolation(f"duplicate state_id {sid}")
        seen.add(sid)
        rows.append((sid, ph))
    rows.sort(key=lambda r: r[0])          # canonical order
    leaves = [leaf_digest(sid, ph) for sid, ph in rows]
    return {
        "version": PACKET_ROOT_VERSION,
        "packet_count": len(rows),
        "ordering": "ascending state_id",
        "packet_root": merkle_root(leaves),
        "first_state_id": rows[0][0] if rows else None,
        "last_state_id": rows[-1][0] if rows else None,
    }


def cycle_commitment(*, cycle_id: str, scheduled_time: str,
                     packets: list[dict], prev_cycle_hash: str) -> dict:
    """The object the cycle log chain-appends.

    Because packet_root is INSIDE this body, the existing chain_append
    (which hashes the whole body) automatically extends its guarantee
    over the packet set -- no change to the ledger primitive needed.
    """
    root = compute(packets)
    return {
        "commitment_version": PACKET_ROOT_VERSION,
        "cycle_id": cycle_id,
        "scheduled_time": scheduled_time,
        "packet_count": root["packet_count"],
        "packet_root": root["packet_root"],
        "packet_ordering": root["ordering"],
        "prev_cycle_hash": prev_cycle_hash,
        "LAW": "altering, inserting, removing or reordering any packet "
               "changes packet_root, which changes this record's "
               "entry_hash, which breaks the chain onward",
    }


def verify(commitment: dict, packets: list[dict]) -> dict:
    """Re-derive the root from the packets actually on disk."""
    recomputed = compute(packets)
    ok_root = recomputed["packet_root"] == commitment.get("packet_root")
    ok_count = recomputed["packet_count"] == commitment.get("packet_count")
    return {
        "packet_root_matches": ok_root,
        "packet_count_matches": ok_count,
        "VALID": ok_root and ok_count,
        "expected_root": commitment.get("packet_root"),
        "actual_root": recomputed["packet_root"],
        "expected_count": commitment.get("packet_count"),
        "actual_count": recomputed["packet_count"],
    }
