#!/usr/bin/env python
"""Crypto shadow arena: one tick (launchd every 5 minutes, 24/7).

    python scripts/crypto_arena.py

Zero capital by construction. Separate evidence class and ledger.
"""
from __future__ import annotations

import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))


def main() -> int:
    try:
        from apex.crypto.arena import tick
        st = tick()
        print(f"crypto tick: {st}")
    except Exception as e:                                  # noqa: BLE001
        print(f"crypto tick failed (shadow-only, no impact): "
              f"{type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
