"""PERMANENT ADVERSARIAL LEDGER CONCURRENCY TESTS (Defect B, 2026-08-23).

The natural failure: watchdog and reader threads both read parent hash
X and appended children XA, XB -- two post-fix chain breaks in the g1
book ledger. Reproduced deterministically with a barrier before repair;
these tests keep the repaired primitive honest forever.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.governance.chain_ledger import chain_append  # noqa: E402


def _verify(lp: Path, expected_rows: int) -> None:
    rows = [json.loads(x) for x in lp.read_text().splitlines()
            if x.strip()]
    assert len(rows) == expected_rows, \
        f"lost/duplicated appends: {len(rows)} != {expected_rows}"
    breaks = sum(1 for i in range(1, len(rows))
                 if rows[i]["prev_hash"] != rows[i - 1]["entry_hash"])
    assert breaks == 0, f"{breaks} hash breaks"
    assert len({r["entry_hash"] for r in rows}) == len(rows), \
        "duplicate entry hashes"


def test_barrier_race_no_longer_breaks_the_chain(tmp_path):
    """The exact Defect B scenario: two threads released simultaneously
    onto the same ledger."""
    lp = tmp_path / "race.jsonl"
    chain_append(lp, {"kind": "genesis"})
    barrier = threading.Barrier(2)

    def worker(tag):
        barrier.wait()
        chain_append(lp, {"kind": "racer", "tag": tag})
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    _verify(lp, 3)


def test_thread_hammer(tmp_path):
    """4 threads x 300 appends -- volume that exposed the old race in
    a single run."""
    lp = tmp_path / "hammer.jsonl"

    def hammer(tag):
        for i in range(300):
            chain_append(lp, {"kind": "h", "tag": tag, "i": i})
    ts = [threading.Thread(target=hammer, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    _verify(lp, 1200)
    # reopen/restart semantics: a fresh append still chains correctly
    chain_append(lp, {"kind": "after_restart"})
    _verify(lp, 1201)


def test_multiprocess_hammer(tmp_path):
    """Accidental second WRITER PROCESS -- the flock layer's job."""
    import subprocess
    lp = tmp_path / "mp.jsonl"
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from apex.governance.chain_ledger import chain_append\n"
        "for i in range(150):\n"
        "    chain_append(%r, {'kind': 'mp', 'tag': sys.argv[1], 'i': i})\n"
    ) % (str(Path(__file__).resolve().parent.parent), str(lp))
    procs = [subprocess.Popen(
        [sys.executable, "-c", code, str(t)]) for t in range(3)]
    assert all(p.wait() == 0 for p in procs)
    _verify(lp, 450)


def test_malformed_rows_zero_after_hammer(tmp_path):
    lp = tmp_path / "wf.jsonl"

    def hammer(tag):
        for i in range(100):
            chain_append(lp, {"kind": "w", "tag": tag, "i": i})
    ts = [threading.Thread(target=hammer, args=(i,)) for i in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    for line in lp.read_text().splitlines():
        rec = json.loads(line)                 # raises if malformed
        assert "entry_hash" in rec and "prev_hash" in rec
