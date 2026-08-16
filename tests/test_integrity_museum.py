"""THE MUSEUM OF RESEARCH-SYSTEM LIES — permanent negative controls.

Each aborted campaign attempt is a fixture of a known corruption class.
The integrity gate must refuse them FOREVER; if a future refactor makes
any museum piece pass, the integrity system has regressed.

  ATTEMPT_0 -> LAB-01 (empty-symbol tick kill): ledger not preserved;
               only the tombstone remains (guard lives in unit tests).
  ATTEMPT_1 -> LAB-02 (silent quota starvation -> hollow sessions)
  ATTEMPT_2 -> LAB-04 (cached empty contexts -> blindfolded universe)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from hunter_replay_analysis import compute_integrity  # noqa: E402

MUSEUM = {
    "ATTEMPT_1_LAB02_hollow": Path(
        "results/hunter/replay_campaign_v1_ATTEMPT1/replay_ledger.jsonl"),
    "ATTEMPT_2_LAB04_blindfold": Path(
        "results/hunter/replay_campaign_v1_ATTEMPT2/replay_ledger.jsonl"),
}


def _load(path):
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    by = {}
    for r in rows:
        by.setdefault(r.get("kind"), []).append(r)
    sessions = sorted({r.get("session_date") for r in rows
                       if r.get("session_date")})
    return rows, by, sessions


@pytest.mark.parametrize("name", list(MUSEUM))
def test_museum_piece_is_refused_forever(name):
    path = MUSEUM[name]
    if not path.exists():
        pytest.skip(f"{name} fixture absent on this machine")
    rows, by, sessions = _load(path)
    verdict = compute_integrity(rows, by, sessions)["VERDICT"]
    assert "NOT CLEAN" in verdict, (
        f"INTEGRITY REGRESSION: museum piece {name} passed the gate")


def test_museum_pieces_fail_for_their_OWN_disease():
    """Each exhibit must be refused for its documented failure class,
    not accidentally for some unrelated reason."""
    p1 = MUSEUM["ATTEMPT_1_LAB02_hollow"]
    if p1.exists():
        integ = compute_integrity(*_load(p1))
        assert integ["hollow_sessions"] > 0            # LAB-02 signature
    p2 = MUSEUM["ATTEMPT_2_LAB04_blindfold"]
    if p2.exists():
        integ = compute_integrity(*_load(p2))
        assert integ["context_starved_sessions"] > 0   # LAB-04 signature
        assert integ["hollow_sessions"] == 0           # NOT hollow: subtler
