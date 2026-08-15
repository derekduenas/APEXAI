#!/usr/bin/env python
"""Freeze P1B dependencies: hash each artifact and register its BIRTH.

Run once per version. A birth is append-only; re-running refuses names
already registered (a changed artifact is a new version under a new name).
From each birth forward — and only forward — that dependency's forecasts
can qualify as EODHD_FORWARD evidence.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

from nightly_pull import _chain_append  # noqa: E402

from apex.hunter.birth import REGISTRY, load_births  # noqa: E402

ARTIFACTS = {
    "HUNTER-FORWARD-PROTOCOL_v1": (
        "protocol", ("HUNTER-FORWARD-PROTOCOL.md",)),
    "hunter_feature_schema_v1": (
        "feature_schema", ("apex/hunter/chartstate.py",
                           "apex/hunter/relstrength.py")),
    "hunter_rule_model_v1": (
        "model", ("apex/hunter/scanner.py", "apex/hunter/playbooks_v1.py",
                  "apex/hunter/forward_pass.py")),
    # v1.1: forward_pass ledger readers fixed post-mint (chain entries are
    # flat, not wrapped) BEFORE any forecast existed; birth.py (the
    # eligibility law itself) now hashed too. Append-only: v1 stays.
    "hunter_rule_model_v1.1": (
        "model", ("apex/hunter/scanner.py", "apex/hunter/playbooks_v1.py",
                  "apex/hunter/forward_pass.py", "apex/hunter/birth.py")),
    "HUNTER-001_v1": (
        "playbook", ("docs/HUNTER-001-PLAYBOOK.md",
                     "apex/hunter/playbooks_v1.py")),
    "HUNTER-002_v1": (
        "playbook", ("docs/HUNTER-002-PLAYBOOK.md",
                     "apex/hunter/playbooks_v1.py")),
}


def main() -> int:
    existing = load_births()
    now = str(pd.Timestamp.now(tz="UTC"))
    for name, (kind, files) in ARTIFACTS.items():
        if name in existing:
            print(f"already born: {name} at "
                  f"{existing[name]['birth_time_utc']} (refusing re-birth)")
            continue
        h = hashlib.sha256()
        for f in files:
            h.update(Path(f).read_bytes())
        e = _chain_append(REGISTRY, {
            "kind": "birth", "name": name, "dependency_kind": kind,
            "artifact_hash": h.hexdigest()[:16],
            "artifact_files": list(files), "birth_time_utc": now})
        print(f"BORN {name} ({kind}) {h.hexdigest()[:16]} at {now} "
              f"[{e['entry_hash'][:12]}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
