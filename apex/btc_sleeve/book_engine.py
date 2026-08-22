"""BITNOMIAL BOOK ENGINE -- snapshot + delta reconstruction as law.

Venue protocol (docs 2026-08-21): a `book` snapshot carries ack_id,
asks/bids as (price, quantity) tuples best-first; `level` deltas apply
ONLY when level.ack_id > snapshot ack_id; quantity 0 clears a level;
book ack_id 0 means markets closed. The venue provides NO contiguous
sequence numbers (SEQUENCE_CONTIGUITY=NOT_PROVIDED_BY_VENUE), so
uncertainty detection is built from ack monotonicity plus book
invariants -- and the law is:

    AFTER ANY DETECTED SEQUENCE UNCERTAINTY: BOOK_QUALITY = INVALID
    until a clean snapshot resync. No silently continuing.

Prices stay in RAW venue units here (unit resolution is the stream
daemon's job); the engine never converts, only reconstructs.

decision_power: NONE -- a sensor organ.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BOOK_VALID = "VALID"
BOOK_INVALID = "INVALID"
BOOK_NO_SNAPSHOT = "NO_SNAPSHOT_YET"
BOOK_CLOSED = "MARKETS_CLOSED"


@dataclass
class BookState:
    quality: str = BOOK_NO_SNAPSHOT
    invalid_reason: str | None = None
    snapshot_ack: int | None = None
    last_applied_ack: int | None = None
    bids: dict = field(default_factory=dict)   # price -> qty (raw units)
    asks: dict = field(default_factory=dict)
    # continuity accounting
    snapshots: int = 0
    levels_applied: int = 0
    levels_stale_skipped: int = 0
    # MEASURED LIVE 2026-08-21 (~47% of level traffic): one matching
    # event updates several levels SHARING one ack_id -- same-ack
    # levels are atomic-event members, NOT duplicates. Levels are
    # absolute-quantity replacements (idempotent), so applying them is
    # safe; skipping them was the bug the first live soak caught.
    same_ack_repeats: int = 0
    out_of_order: int = 0
    crossed_events: int = 0
    negative_size_events: int = 0
    invalidations: int = 0
    resyncs: int = 0
    # the venue's periodic snapshots (~10s cadence measured) are ground
    # truth: each one is diffed against our reconstruction BEFORE it
    # replaces it. Persistent divergence = real delta loss; occasional
    # divergence can be in-flight timing, so it is telemetry, not an
    # automatic invalidation.
    snapshot_divergence_events: int = 0
    last_divergence: dict | None = None

    def _invalidate(self, reason: str) -> None:
        if self.quality != BOOK_INVALID:
            self.invalidations += 1
        self.quality = BOOK_INVALID
        self.invalid_reason = reason

    def apply_snapshot(self, msg: dict) -> None:
        ack = int(msg["ack_id"])
        if ack == 0:
            self.quality = BOOK_CLOSED
            self.invalid_reason = None
            self.bids, self.asks = {}, {}
            self.snapshot_ack = 0
            self.snapshots += 1
            return
        bids = {float(p): float(q) for p, q in msg.get("bids", [])}
        asks = {float(p): float(q) for p, q in msg.get("asks", [])}
        if any(q < 0 for q in list(bids.values()) + list(asks.values())):
            self.negative_size_events += 1
            self._invalidate("NEGATIVE_SIZE_IN_SNAPSHOT")
            return
        was_invalid = self.quality == BOOK_INVALID
        if self.quality == BOOK_VALID:
            diff = self._diff_against(bids, asks)
            if diff:
                self.snapshot_divergence_events += 1
                self.last_divergence = {"snapshot_ack": ack,
                                        "our_ack": self.last_applied_ack,
                                        "mismatched_levels": diff}
        self.bids, self.asks = bids, asks
        self.snapshot_ack = ack
        self.last_applied_ack = ack
        self.snapshots += 1
        self.quality = BOOK_VALID
        self.invalid_reason = None
        if was_invalid:
            self.resyncs += 1
        self._check_crossed()

    def apply_level(self, msg: dict) -> None:
        ack = int(msg["ack_id"])
        if self.snapshot_ack is None or self.quality == BOOK_CLOSED:
            # delta before any snapshot: cannot anchor -- uncertainty
            self._invalidate("LEVEL_BEFORE_SNAPSHOT")
            return
        if ack <= self.snapshot_ack:
            # venue law: pre-snapshot deltas are expected replay, skip
            self.levels_stale_skipped += 1
            return
        if self.last_applied_ack is not None:
            if ack == self.last_applied_ack:
                # atomic multi-level event member: APPLY (idempotent
                # absolute-qty replacement), count, never skip
                self.same_ack_repeats += 1
            elif ack < self.last_applied_ack:
                self.out_of_order += 1
                self._invalidate("ACK_REGRESSION")
                return
        if self.quality == BOOK_INVALID:
            # no silent recovery: deltas do not repair an invalid book
            return
        qty = float(msg["quantity"])
        if qty < 0:
            self.negative_size_events += 1
            self._invalidate("NEGATIVE_SIZE_DELTA")
            return
        price = float(msg["price"])
        side = self.bids if msg["side"].lower().startswith("b") else \
            self.asks
        if qty == 0:
            side.pop(price, None)
        else:
            side[price] = qty
        self.last_applied_ack = ack
        self.levels_applied += 1
        self._check_crossed()

    def on_disconnect(self) -> None:
        """Reconnect law: the old book is uncertain until resnapshot."""
        self._invalidate("DISCONNECTED_AWAITING_RESYNC")

    def _check_crossed(self) -> None:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is not None and ba is not None and bb >= ba:
            self.crossed_events += 1
            self._invalidate("CROSSED_OR_LOCKED_BOOK")

    def best_bid(self):
        return max(self.bids) if self.bids else None

    def best_ask(self):
        return min(self.asks) if self.asks else None

    def top(self) -> dict:
        """Top-of-book in RAW units. Refuses numbers unless VALID --
        an invalid book yields its reason, never a price."""
        if self.quality != BOOK_VALID:
            return {"book_quality": self.quality,
                    "invalid_reason": self.invalid_reason}
        bb, ba = self.best_bid(), self.best_ask()
        return {"book_quality": BOOK_VALID,
                "best_bid_raw": bb, "best_ask_raw": ba,
                "best_bid_qty": self.bids.get(bb),
                "best_ask_qty": self.asks.get(ba),
                "book_mid_raw": (bb + ba) / 2.0
                if bb is not None and ba is not None else None,
                "spread_raw": ba - bb
                if bb is not None and ba is not None else None,
                "depth_bid_levels": len(self.bids),
                "depth_ask_levels": len(self.asks),
                "last_applied_ack": self.last_applied_ack}

    def _diff_against(self, bids: dict, asks: dict, top_n: int = 5
                      ) -> list:
        """Mismatched top-N levels between our reconstruction and a
        fresh venue snapshot -- the reconstruction-correctness probe."""
        out = []
        for name, ours, theirs, best in (
                ("bid", self.bids, bids, max), ("ask", self.asks, asks,
                                                min)):
            keys = sorted(set(ours) | set(theirs),
                          reverse=(name == "bid"))[:top_n]
            for p in keys:
                if ours.get(p) != theirs.get(p):
                    out.append({"side": name, "price": p,
                                "ours": ours.get(p),
                                "snapshot": theirs.get(p)})
        return out

    def continuity(self) -> dict:
        return {"snapshots": self.snapshots,
                "levels_applied": self.levels_applied,
                "levels_stale_skipped": self.levels_stale_skipped,
                "same_ack_repeats": self.same_ack_repeats,
                "snapshot_divergence_events":
                    self.snapshot_divergence_events,
                "out_of_order": self.out_of_order,
                "crossed_events": self.crossed_events,
                "negative_size_events": self.negative_size_events,
                "invalidations": self.invalidations,
                "resyncs": self.resyncs,
                "sequence_contiguity": "NOT_PROVIDED_BY_VENUE"}
