"""Verify a hash-chained APEX ledger from genesis to tail.

Recomputes every entry_hash and checks that each row's prev_hash equals
the previous row's entry_hash. A ledger that cannot be verified is not
evidence, whatever it says inside.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def verify(path: Path) -> dict:
    prev = "GENESIS"
    n, bad_link, bad_hash, torn = 0, [], [], 0
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            torn += 1
            continue
        n += 1
        if row.get("prev_hash") != prev:
            bad_link.append(i)
        body = {k: v for k, v in row.items() if k != "entry_hash"}
        want = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()).hexdigest()
        if want != row.get("entry_hash"):
            bad_hash.append(i)
        prev = row.get("entry_hash")
    return {"path": str(path), "rows": n, "unparseable_lines": torn,
            "broken_links": bad_link, "bad_hashes": bad_hash,
            "verdict": ("CHAIN_INTACT" if not (bad_link or bad_hash or torn)
                        else "CHAIN_BROKEN"),
            "head": prev}


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(verify(Path(p)), indent=1))
