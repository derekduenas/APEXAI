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
    # SNAPSHOT RECONCILIATION (operator mandate 2026-08-22: "in-flight
    # timing is an explanation, not yet proof"). Each periodic venue
    # snapshot is quantitatively reconciled against our reconstruction
    # BEFORE replacing it. Classification law:
    #   * a mismatch that is GONE at the next reconciliation was a
    #     transient in-flight race -> RECONCILIATION_RACE_CONFIRMED
    #   * the SAME level mismatched at two consecutive reconciliations
    #     -> BOOK_RECONSTRUCTION_DIVERGENCE (L2 stays provisional)
    snapshot_divergence_events: int = 0
    last_divergence: dict | None = None
    reconciliations_total: int = 0
    reconciliations_perfect: int = 0
    races_confirmed: int = 0
    persistent_divergences: int = 0
    last_reconciliation: dict | None = None
    _pending_mismatch_keys: tuple = ()
    _levels_since_snapshot: int = 0
    _last_level_arrival: float | None = None

    def _invalidate(self, reason: str) -> None:
        if self.quality != BOOK_INVALID:
            self.invalidations += 1
        self.quality = BOOK_INVALID
        self.invalid_reason = reason

    def apply_snapshot(self, msg: dict, arrival: float | None = None
                       ) -> None:
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
            self._reconcile(ack, msg, bids, asks, arrival)
        self.bids, self.asks = bids, asks
        self._levels_since_snapshot = 0
        self.snapshot_ack = ack
        self.last_applied_ack = ack
        self.snapshots += 1
        self.quality = BOOK_VALID
        self.invalid_reason = None
        if was_invalid:
            self.resyncs += 1
        self._check_crossed()

    def apply_level(self, msg: dict, arrival: float | None = None
                    ) -> None:
        ack = int(msg["ack_id"])
        if arrival is not None:
            self._last_level_arrival = arrival
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
        self._levels_since_snapshot += 1
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
                      ) -> tuple:
        """Mismatched top-N levels between our reconstruction and a
        fresh venue snapshot -- the reconstruction-correctness probe.
        Returns (mismatches, levels_compared, qty_mm, price_mm)."""
        out, compared, qty_mm, price_mm = [], 0, 0, 0
        for name, ours, theirs in (("bid", self.bids, bids),
                                   ("ask", self.asks, asks)):
            keys = sorted(set(ours) | set(theirs),
                          reverse=(name == "bid"))[:top_n]
            compared += len(keys)
            for p in keys:
                if ours.get(p) != theirs.get(p):
                    if p in ours and p in theirs:
                        qty_mm += 1
                    else:
                        price_mm += 1
                    out.append({"side": name, "price": p,
                                "ours": ours.get(p),
                                "snapshot": theirs.get(p)})
        return out, compared, qty_mm, price_mm

    def _reconcile(self, ack: int, msg: dict, bids: dict, asks: dict,
                   arrival: float | None) -> None:
        """Quantitative snapshot reconciliation + race-vs-divergence
        classification (see class docstring for the law)."""
        diff, compared, qty_mm, price_mm = self._diff_against(bids, asks)
        self.reconciliations_total += 1
        our_bb, our_ba = self.best_bid(), self.best_ask()
        snap_bb = max(bids) if bids else None
        snap_ba = min(asks) if asks else None
        rec = {"snapshot_ack": ack,
               "snapshot_event_time": msg.get("timestamp"),
               "local_last_applied_ack": self.last_applied_ack,
               "time_delta_ms": round(
                   (arrival - self._last_level_arrival) * 1000.0, 1)
               if arrival is not None and
               self._last_level_arrival is not None else None,
               "levels_compared": compared,
               "levels_matching": compared - len(diff),
               "quantity_mismatch": qty_mm,
               "price_mismatch": price_mm,
               "top_of_book_match": (our_bb == snap_bb and
                                     our_ba == snap_ba),
               "events_between_local_capture_and_snapshot":
                   self._levels_since_snapshot,
               "mismatched_levels": diff[:10]}
        # classify LAST reconciliation's pending mismatches
        if self._pending_mismatch_keys:
            now_keys = {(d["side"], d["price"]) for d in diff}
            repeated = [k for k in self._pending_mismatch_keys
                        if k in now_keys]
            if repeated:
                self.persistent_divergences += 1
                rec["classification"] = "BOOK_RECONSTRUCTION_DIVERGENCE"
                rec["repeated_levels"] = repeated
            else:
                self.races_confirmed += 1
                rec["prior_divergence_classification"] = \
                    "RECONCILIATION_RACE_CONFIRMED"
        if diff:
            self.snapshot_divergence_events += 1
            self.last_divergence = rec
        else:
            self.reconciliations_perfect += 1
        self._pending_mismatch_keys = tuple(
            (d["side"], d["price"]) for d in diff)
        self.last_reconciliation = rec

    def continuity(self) -> dict:
        return {"snapshots": self.snapshots,
                "levels_applied": self.levels_applied,
                "levels_stale_skipped": self.levels_stale_skipped,
                "same_ack_repeats": self.same_ack_repeats,
                "snapshot_divergence_events":
                    self.snapshot_divergence_events,
                "reconciliations_total": self.reconciliations_total,
                "reconciliations_perfect": self.reconciliations_perfect,
                "races_confirmed": self.races_confirmed,
                "persistent_divergences": self.persistent_divergences,
                "out_of_order": self.out_of_order,
                "crossed_events": self.crossed_events,
                "negative_size_events": self.negative_size_events,
                "invalidations": self.invalidations,
                "resyncs": self.resyncs,
                "sequence_contiguity": "NOT_PROVIDED_BY_VENUE"}
