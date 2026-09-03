"""RESEARCH_BOARD_V2 -- the invariants that stop the board splitting again.

The 2026-09-03 split was not a race and not corruption. chain_append()
was called with the RELATIVE path `results/edgeforge/research_board.jsonl`
and resolved against the process working directory: services run from
/apex-data/runtime (results/ -> the data volume), session tooling from
/opt/apex-repo (results/ is a real directory on the root disk). The same
call, with the same string, wrote to two filesystems for four days.

These tests exist so that specific mistake cannot be made again, and so
the legacy histories cannot be quietly edited after V2 committed to them.
"""
import json
import subprocess
from pathlib import Path

import pytest

from apex.governance.research_board import (CANONICAL_BOARD,
                                            LEGACY_BOARDS,
                                            RECONCILIATION_RECORD_ID,
                                            ResearchBoardViolation,
                                            board_append,
                                            legacy_commitment,
                                            legacy_manifest,
                                            legacy_reconciliation_root,
                                            verify_chain)


# ------------------------------------------------ the path invariant
def test_canonical_board_is_absolute():
    assert CANONICAL_BOARD.is_absolute(), (
        "a relative canonical board is the exact defect V2 closes")


def test_board_append_refuses_a_relative_path():
    with pytest.raises(ResearchBoardViolation, match="ABSOLUTE"):
        board_append({"kind": "probe"},
                     board=Path("results/edgeforge/research_board.jsonl"))


def test_board_append_refuses_every_legacy_board():
    for ident, path in LEGACY_BOARDS.items():
        with pytest.raises(ResearchBoardViolation, match="FROZEN"):
            board_append({"kind": "probe"}, board=path)


def test_no_authoritative_writer_selects_its_board_by_cwd():
    """Mechanical: no module may hand chain_append a relative
    results/... path. Grep, not trust."""
    r = subprocess.run(
        ["grep", "-rn", "--include=*.py", "-e",
         r"chain_append(\s*[\"']results/", "apex", "scripts"],
        capture_output=True, text=True)
    hits = [x for x in r.stdout.split("\n") if x.strip()]
    assert not hits, "relative-path board writers: %s" % hits[:5]


# --------------------------------------- the cryptographic commitment
def test_reconciliation_root_is_deterministic_and_order_independent():
    ms = [legacy_manifest(k, v) for k, v in LEGACY_BOARDS.items()]
    a = legacy_reconciliation_root(ms)
    b = legacy_reconciliation_root(list(reversed(ms)))
    assert a == b, "the root must not depend on discovery order"
    assert a == legacy_reconciliation_root(ms)


def test_reconciliation_root_changes_if_a_legacy_board_changes(tmp_path):
    """The whole point: editing a legacy file after the fact must break
    the commitment."""
    src = next(iter(LEGACY_BOARDS.values()))
    a = tmp_path / "a.jsonl"
    a.write_bytes(src.read_bytes())
    m1 = legacy_manifest("X", a)
    root1 = legacy_reconciliation_root([m1])
    a.write_bytes(src.read_bytes() + b'{"tampered":1}\n')
    m2 = legacy_manifest("X", a)
    assert legacy_commitment(m1) != legacy_commitment(m2)
    assert legacy_reconciliation_root([m2]) != root1


def test_swapping_two_legacy_boards_changes_the_root(tmp_path):
    """leaf_digest binds identity to content, so two boards trading
    places is not invisible."""
    paths = list(LEGACY_BOARDS.values())
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_bytes(paths[0].read_bytes())
    b.write_bytes(paths[1].read_bytes())
    straight = legacy_reconciliation_root(
        [legacy_manifest("A", a), legacy_manifest("B", b)])
    swapped = legacy_reconciliation_root(
        [legacy_manifest("A", b), legacy_manifest("B", a)])
    assert straight != swapped


# ------------------------------------------------- the live board
@pytest.mark.skipif(not CANONICAL_BOARD.exists(),
                    reason="V2 board not present in this environment")
def test_v2_opens_with_the_reconciliation_record_and_verifies():
    v = verify_chain(CANONICAL_BOARD)
    assert v["intact"], "V2 chain broken at %s" % v["broken_at"]
    first = json.loads(
        CANONICAL_BOARD.read_text().split("\n")[0])
    assert first["id"] == RECONCILIATION_RECORD_ID
    assert first["prev_hash"] == "GENESIS"
    assert first["legacy_reconciliation_root"]
    # it must commit to BOTH legacy boards
    assert set(first["legacy_commitments"]) == set(LEGACY_BOARDS)


@pytest.mark.skipif(not CANONICAL_BOARD.exists(),
                    reason="V2 board not present in this environment")
def test_legacy_boards_still_match_what_v2_committed_to():
    first = json.loads(CANONICAL_BOARD.read_text().split("\n")[0])
    for ident, path in LEGACY_BOARDS.items():
        now = legacy_commitment(legacy_manifest(ident, path))
        assert now == first["legacy_commitments"][ident], (
            "%s has been altered since reconciliation" % ident)


@pytest.mark.skipif(not all(p.exists() for p in LEGACY_BOARDS.values()),
                    reason="legacy boards not present in this environment")
def test_legacy_boards_are_frozen_read_only():
    for ident, path in LEGACY_BOARDS.items():
        assert not (path.stat().st_mode & 0o222), (
            "%s is writable; V2 is the sole future authority" % ident)


@pytest.mark.skipif(not all(p.exists() for p in LEGACY_BOARDS.values()),
                    reason="legacy boards not present in this environment")
def test_each_legacy_board_is_independently_intact():
    """They are preserved AS THEY ARE -- two real histories, each valid
    from its own GENESIS. No merge, no renumbering."""
    for ident, path in LEGACY_BOARDS.items():
        v = verify_chain(path)
        assert v["intact"], "%s broken at %s" % (ident, v["broken_at"])


def test_reconciliation_claims_no_false_common_history():
    """The record must not assert the two legacy chains were ever one
    linear history -- they share no records and no genesis."""
    if not CANONICAL_BOARD.exists():
        pytest.skip("V2 board not present")
    first = json.loads(CANONICAL_BOARD.read_text().split("\n")[0])
    assert "EXPLICITLY_NOT_CLAIMED" in first
    ids = []
    for path in LEGACY_BOARDS.values():
        ids.append({json.loads(x).get("id")
                    for x in path.read_text().split("\n") if x.strip()}
                   - {None})
    assert not (ids[0] & ids[1]), (
        "the legacy boards share record ids; the 'independent chains' "
        "claim in the reconciliation record would be wrong")


def test_audit_script_passes():
    r = subprocess.run(
        ["/opt/apex/shared/venv/bin/python", "scripts/research_board_audit.py"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]
