"""RECORDED-OBSERVATION WIRING — the recorded route's observation feed for the shared V2 lifecycle runner.

WHAT WAS MISSING. `EXIT_POLICY_V2` services a due exit the moment a NEW observation for its contract becomes
available. The runner learns that from `observation_feed`, a list of `(available_epoch, {observation_id,
contract_id})` pairs. Production gets those from the live feed. The recorded route had no way to produce them at
all, so a recorded run under V2 behaved exactly like V1 -- arrival triggering was built and unreachable. This
module closes that gap and nothing else: it turns recorded chain snapshots into the two things the runner needs,
a feed of arrival notifications and an exit-quote source, from the SAME recording, so the notification and the
quote can never disagree about what was available when.

THE ONE GATE, UNCHANGED. Visibility is decided by `replay.most_recent_available`, on the RECORDED RECEIPT. A
snapshot that reached the collector at 13:46 is invisible at 13:45:30 however early its quotes claim to have been
true. This module adds no second path to the data and never reaches past `now` to pick an advantageous instant.

IDENTITY IS DERIVED FROM THE RECORD, NOT INVENTED. `observation_id` is a digest over the contract, the snapshot's
availability instant and the quote fields actually recorded. Two observations of one contract at one instant with
identical quotes are the same observation and get the same id; anything that differs gets a different id. Because
the digest is a pure function of persisted values, a reviewer can recompute an id from the ledger and confirm which
recorded observation an attempt valued -- which is the whole point of carrying an identity at all.

WHAT THIS MODULE DOES NOT DO. It does not read files, name a collection, authorize a replay or construct a
boundary; `replay.ReplayAuthorization` and the driver own all of that. It does not normalise vendor rows -- it
takes rows already normalised by the caller's own adapter (`pulse_options.sources.live_chain_rows` in the recorded
driver) so there is exactly one normalisation in the system. And it is not on any exit path's critical route: it
supplies data, and when it has none it raises the ordinary provider-unavailable signal the boundary already turns
into a named, non-discharging attempt."""
from __future__ import annotations

import hashlib
import json

from . import instant as I
from . import replay as RP
from .records import contract_id as contract_id_of

FEED_SCHEMA = "RECORDED_OBSERVATION_FEED_V1"

IDENTITY_FIELDS = ("bid", "ask", "bid_size", "ask_size", "timestamp_epoch")

AVAILABILITY_LAW = (
    "RECORDED_OBSERVATION_AVAILABILITY_V1: an observation becomes visible at the instant the RECORDING says it "
    "reached this system, never at the instant its quote claims to describe. The notification feed and the quote "
    "source are built from the same snapshots, so a notification can never announce an observation the quote "
    "source would not serve, and neither can see past the clock.")

IDENTITY_LAW = (
    "RECORDED_OBSERVATION_IDENTITY_V1: observation_id = sha256 over the contract id, the canonical availability "
    "instant and the recorded quote fields. It is a pure function of persisted values, so it can be recomputed "
    "from the ledger and matched back to the recording. It is NOT a provider-issued sequence number and does not "
    "claim to be one.")


class RecordedFeedRefused(RuntimeError):
    """A recorded feed that cannot be stated honestly. Named, never silent."""


def observation_id(*, contract_id: str, available_epoch, quote: dict) -> str:
    body = {"contract_id": contract_id,
            "available_us": I.canonical_micros(available_epoch, field="available"),
            "quote": {k: quote.get(k) for k in IDENTITY_FIELDS}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:32]


def _contract_of(row: dict) -> dict:
    for k in ("symbol", "expiration", "strike", "right"):
        if row.get(k) is None:
            raise RecordedFeedRefused("RECORDED_ROW_MISSING_CONTRACT_FIELD: %r in %r" % (k, sorted(row)))
    return {"symbol": row["symbol"], "expiration": row["expiration"],
            "strike": float(row["strike"]), "right": row["right"]}


class RecordedQuoteSource:
    """Exit quotes and arrival notifications from ONE set of recorded chain snapshots.

    `snapshots` is `[(available_epoch, rows)]`, where `available_epoch` is the recording's own receipt instant for
    that snapshot and `rows` are contract rows already normalised by the caller's adapter (each carrying symbol,
    expiration, strike, right, bid, ask, bid_size, ask_size and timestamp_epoch). `now_fn` reads the run's clock;
    this module never advances it."""

    def __init__(self, snapshots, *, now_fn):
        if not callable(now_fn):
            raise RecordedFeedRefused("NOW_FN_REQUIRED: the feed reads the run's clock, it does not keep its own")
        self.now = now_fn
        self.pairs, self._index, self.excluded = [], {}, []
        for n, (available, rows) in enumerate(snapshots):
            av_us = I.canonical_micros(available, field="available")
            keep = {}
            for row in (rows or []):
                c = _contract_of(row)
                ts = row.get("timestamp_epoch")
                if not isinstance(ts, (int, float)) or isinstance(ts, bool):
                    raise RecordedFeedRefused("RECORDED_ROW_MISSING_TIMESTAMP: snapshot %d, contract %r"
                                              % (n, contract_id_of(c)))
                if I.canonical_micros(ts, field="timestamp") > av_us:
                    # the recording says this quote was received BEFORE it existed. It is excluded, named, and not
                    # repaired: a receipt that precedes its own event is a defect in the recording, not a datum.
                    self.excluded.append({"snapshot": n, "contract_id": contract_id_of(c),
                                          "why": "RECORDED_QUOTE_AFTER_ITS_OWN_RECEIPT",
                                          "timestamp_utc": I.canonical_utc(ts),
                                          "available_utc": I.canonical_utc(available)})
                    continue
                cid = contract_id_of(c)
                keep[cid] = dict(row)
                self._index[(av_us, cid)] = dict(row)
            self.pairs.append((I.from_micros(av_us), keep))
        self.pairs.sort(key=lambda p: I.canonical_micros(p[0]))
        self.served: list = []

    # ------------------------------------------------------------------ visibility

    def visible_snapshot(self):
        """THE gate, reused: the most recent snapshot whose recorded availability is at or before the clock."""
        return RP.most_recent_available(self.pairs, self.now())

    # ------------------------------------------------------------------ the two things the runner needs

    def observation_feed(self, contract_ids=None) -> list:
        """One notification per (snapshot, contract). The runner coalesces these by (instant, contract) itself."""
        want = set(contract_ids) if contract_ids is not None else None
        out = []
        for available, rows in self.pairs:
            for cid, row in sorted(rows.items()):
                if want is not None and cid not in want:
                    continue
                out.append((available, {"observation_id": observation_id(contract_id=cid, available_epoch=available,
                                                                         quote=row),
                                        "contract_id": cid}))
        return out

    def exit_quote_fn(self, contract: dict):
        """The exit-quote source. Serves ONLY from the currently visible snapshot, and stamps the observation
        identity and availability instant the 003 adapter contract carries."""
        from apex.pulse_options.providers import ProviderUnavailable
        now = self.now()
        got = self.visible_snapshot()
        if got is None:
            self.served.append({"asked_at": now, "outcome": "NO_VISIBLE_SNAPSHOT"})
            raise ProviderUnavailable("NO_RECORDED_SNAPSHOT_AVAILABLE_YET")
        available, rows = got
        cid = contract_id_of(_contract_of({**contract, "strike": float(contract["strike"])}))
        row = rows.get(cid)
        if row is None:
            self.served.append({"asked_at": now, "available": available, "contract_id": cid,
                                "outcome": "CONTRACT_NOT_IN_SNAPSHOT"})
            raise ProviderUnavailable("CONTRACT_NOT_IN_RECORDED_SNAPSHOT: %s at %s" % (cid, I.canonical_utc(now)))
        oid = observation_id(contract_id=cid, available_epoch=available, quote=row)
        self.served.append({"asked_at": now, "available": available, "contract_id": cid,
                            "observation_id": oid, "outcome": "SERVED"})
        return {**{k: row[k] for k in ("symbol", "expiration", "strike", "right", "bid", "ask", "bid_size",
                                       "ask_size", "timestamp_epoch")},
                "observation_id": oid, "available_epoch": available}

    # ------------------------------------------------------------------ evidence

    def describe(self) -> dict:
        return {"schema": FEED_SCHEMA, "n_snapshots": len(self.pairs),
                "n_observations": sum(len(r) for _a, r in self.pairs),
                "n_excluded_rows": len(self.excluded), "excluded": self.excluded[:20],
                "first_available_utc": (I.canonical_utc(self.pairs[0][0]) if self.pairs else None),
                "last_available_utc": (I.canonical_utc(self.pairs[-1][0]) if self.pairs else None),
                "availability_law": AVAILABILITY_LAW, "identity_law": IDENTITY_LAW,
                "feed_digest": self.feed_digest()}

    def feed_digest(self) -> str:
        """One digest over every notification this feed can emit, so a run's inputs are named by content."""
        body = [[I.canonical_micros(a), p["contract_id"], p["observation_id"]] for a, p in self.observation_feed()]
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
