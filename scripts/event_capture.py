#!/usr/bin/env python
"""Event-world clock: one EDGAR 8-K capture cycle (launchd every 15 min).

    python scripts/event_capture.py

Archive only — no decision wiring; the Catalyst seat stays dormant.
"""
from __future__ import annotations

import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

from apex.data.edgar import EdgarClient  # noqa: E402
from apex.events.capture import capture_once  # noqa: E402


def main() -> int:
    try:
        st = capture_once(EdgarClient())
        print(f"edgar events: {st['feed_entries']} in feed, "
              f"{st['new']} new @ {st['captured_at']}")
    except Exception as e:                                  # noqa: BLE001
        print(f"event capture failed (archive-only, no impact): "
              f"{type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
