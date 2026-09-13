"""EXIT-SCHEDULING-003 — recovery continuity and arrival provenance. Reproducers first.

Three cases against `16513b0`, each reproduced before any product code changed:

1. RESTART CONTINUITY. A process opens a position; the next process starts after the exit is due; its recovery
   attempt fails; a fresh usable observation arrives inside the remaining 120-second window. Current behaviour:
   the inherited position received ONE labelled attempt and was then excluded from further servicing, arrivals
   included, so a closable position was stranded.
2. ARRIVAL-TO-QUOTE PROVENANCE. Two distinct observations share a quote timestamp. Matching the outcome to an
   arrival by timestamp cannot say which one the boundary used, because `validate_quote` dropped every field it did
   not name and the outcome record whitelisted the same five. Nothing durable tied the arrival that woke the
   scheduler to the quote that was valued.
3. DETERMINISTIC COALESCING. Notifications sharing an instant and a contract were represented by the LAST id in
   input order and truncated after eight. Two equivalent feeds in different orders produced different traces.

Synthetic only. The recorded driver is neither wired nor run."""
from __future__ import annotations

import json

import pytest

from apex.options_pilot import boundary as B
from apex.options_pilot import exit_policy as EP
from apex.options_pilot import ledger as L
from apex.options_pilot import lifecycle as LC
from apex.options_pilot import session as S
from apex.options_pilot.synthetic_harness import SyntheticHarness

T = 1_789_000_020.0
HOLD, WINDOW = 900.0, 120.0
DUE = T + HOLD
CONTRACT = "SPY|2026-10-09|650.0|CALL"


class Feed:
    """A quote feed whose quotes carry a durable observation identity and their availability instant, and which
    records exactly what it served on every request."""

    def __init__(self, harness, *, snapshots, bid=4.73, ask=4.78, fail_until=None):
        # snapshots: list of {"observation_id", "arrival", "quote_ts"}; may share quote_ts deliberately
        self.h = harness
        # deterministic: two snapshots at one instant tie-break on identity, never on input order, so the FIXTURE
        # cannot be the source of a difference the scheduler is being tested for
        self.snapshots = sorted(snapshots, key=lambda s: (s["arrival"], s["quote_ts"], s["observation_id"]))
        self.bid, self.ask, self.fail_until = bid, ask, fail_until
        self.served: list = []

    def visible(self):
        got = [s for s in self.snapshots if s["arrival"] <= self.h.now()]
        return got[-1] if got else None

    def __call__(self, contract):
        now = self.h.now()
        from apex.pulse_options.providers import ProviderUnavailable
        if self.fail_until is not None and now <= self.fail_until:
            self.served.append({"asked_at": now, "observation_id": None, "outcome": "PROVIDER_FAILED"})
            raise ProviderUnavailable("TRANSIENT_PROVIDER_FAILURE_FIXTURE")
        s = self.visible()
        if s is None:
            self.served.append({"asked_at": now, "observation_id": None, "outcome": "NO_SNAPSHOT"})
            raise ProviderUnavailable("NO_SNAPSHOT_YET")
        self.served.append({"asked_at": now, "observation_id": s["observation_id"], "quote_ts": s["quote_ts"],
                            "arrival": s["arrival"], "outcome": "SERVED"})
        return {"symbol": contract["symbol"], "expiration": contract["expiration"], "strike": contract["strike"],
                "right": contract["right"], "bid": self.bid, "ask": self.ask, "bid_size": 9, "ask_size": 12,
                "timestamp_epoch": s["quote_ts"],
                # the durable identity and availability the adapter contract now carries
                "observation_id": s["observation_id"], "available_epoch": s["arrival"]}

    def feed_for(self, contract_id=CONTRACT):
        return [(s["arrival"], {"observation_id": s["observation_id"], "contract_id": contract_id})
                for s in self.snapshots]


def snaps(*items):
    """items: (observation_id, arrival, quote_lag_s)"""
    return [{"observation_id": oid, "arrival": a, "quote_ts": a - lag} for oid, a, lag in items]


def harness(tmp_path, sid, *, t0=T):
    h = SyntheticHarness(tmp_path / "led.jsonl", session_id=sid, t0=t0, risk="certified")
    h.chain = [{**c, "ask": 4.95} for c in h.chain]
    h.quotes.ask, h.quotes.bid = 4.95, 4.90
    return h


def on_clock(h, t0=None):
    lc = LC.MonotonicClock(h.now() if t0 is None else t0)
    h.clock = lc.clock(); h.bd.clock = h.clock; h.now = lc.now; h.advance = lc.sleep
    return lc


def run(h, lc, feed, *, scans=(), pairs=None, **kw):
    src = dict(h.sources()); src["exit_quote_fn"] = feed
    r = LC.LifecycleRunner(boundary=h.bd, sources=src, clock=lc, symbols=["SPY"], selection_policy="PILOT_RULE_V2",
                           scan_epochs=list(scans), observation_feed=(pairs if pairs is not None else feed.feed_for()),
                           **kw)
    return r.run(), r


def outcomes(h):
    return [r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_outcome"]


def resolved(h):
    return [r for r in outcomes(h) if r.get("discharges_position")]


def fills(h):
    return [r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_fill" and r.get("status") == "FILLED"]


def open_in_process_one(tmp_path, sid):
    """Process one: open the position and stop. Returns the ledger path and the fill."""
    h1 = harness(tmp_path, sid)
    on_clock(h1)
    h1.bd.exit_policy = EP.EXIT_POLICY_V2
    S.open_session(h1.bd, symbols=["SPY"])
    d = S.scan(h1.bd, symbol="SPY", seq=1, **{k: v for k, v in h1.sources().items() if k != "exit_quote_fn"})
    assert d["decision"] == "TRADE", d.get("why")
    f = fills(h1)[0]
    assert f["committed_epoch"] + HOLD == DUE
    return f


def process_two(tmp_path, sid, *, start, snapshots, fail_until=None, policy=EP.EXIT_POLICY_V2):
    """Process two: a restart on the same ledger and session, beginning at `start`."""
    h2 = harness(tmp_path, sid)
    lc2 = on_clock(h2, t0=start)
    h2.bd.exit_policy = policy
    feed = Feed(h2, snapshots=snapshots, fail_until=fail_until)
    rep, r = run(h2, lc2, feed)
    return h2, rep, feed, r


# ============================================================ 1. restart continuity


class TestRestartContinuity:

    def _stranding_case(self, tmp_path):
        """The exact sequence the brick names. Process two starts at due+1; its first attempt fails because the
        provider is down until due+5; a fresh usable observation arrives at due+30, ninety seconds of window left."""
        open_in_process_one(tmp_path, "RC")
        return process_two(tmp_path, "RC", start=DUE + 1.0,
                           snapshots=snaps(("late-good", DUE + 30.0, 0.1)), fail_until=DUE + 5.0)

    def test_a_recovery_run_resolves_on_a_later_fresh_arrival(self, tmp_path):
        """REPRODUCER. At 16513b0 the inherited position got one attempt and was then excluded from arrivals, so
        the usable quote at due+30 was never used and the position was stranded."""
        h2, rep, feed, r = self._stranding_case(tmp_path)
        assert rep["recovered_positions"], "the restart saw the inherited obligation"
        assert resolved(h2), "the fresh quote inside the window must resolve the inherited position"
        assert not h2.bd.book().positions
        assert rep["completion"] == "CLOSED_CLEAN"

    def test_recovery_runs_under_the_original_remaining_window(self, tmp_path):
        open_in_process_one(tmp_path, "RW")
        # the good observation arrives AFTER the original window closes: recovery must NOT extend the window
        h2, rep, feed, r = process_two(tmp_path, "RW", start=DUE + 1.0,
                                       snapshots=snaps(("too-late", DUE + WINDOW + 5.0, 0.1)))
        assert not resolved(h2), "recovery cannot extend the original 120-second window"
        assert all(o["exit_quote_request_epoch"] <= DUE + WINDOW for o in outcomes(h2))
        assert h2.bd.book().positions, "still an explicit obligation"

    def test_recovery_runs_under_the_original_remaining_attempt_budget(self, tmp_path):
        """Process one spends three attempts on stale quotes before dying; process two may use at most two."""
        f = open_in_process_one(tmp_path, "RB")
        h1 = harness(tmp_path, "RB")
        lc1 = on_clock(h1, t0=DUE)
        h1.bd.exit_policy = EP.EXIT_POLICY_V2
        feed1 = Feed(h1, snapshots=snaps(("stale-a", DUE + 0.5, 40.0)))
        pos = S.recover_positions(h1.bd)["own"]
        for _ in range(3):
            h1.bd.record_outcome(fill_receipt=pos[0], exit_quote_fn=feed1)   # three stale attempts, as process one
            lc1.sleep(1.0)
        assert len(outcomes(h1)) == 3
        h2, rep, feed, r = process_two(tmp_path, "RB", start=DUE + 10.0,
                                       snapshots=snaps(("stale-b", DUE + 11.0, 40.0), ("stale-c", DUE + 12.0, 40.0),
                                                       ("stale-d", DUE + 13.0, 40.0), ("stale-e", DUE + 14.0, 40.0)))
        assert len(outcomes(h2)) == 5, "five in total across both processes, never more"
        assert any(x["kind"] == "pilot_exit_exhausted" for x in L.read_all(h2.bd.ledger))

    def test_recovery_cannot_create_a_second_fill_fee_outcome_or_discharge(self, tmp_path):
        open_in_process_one(tmp_path, "RD")
        h2, rep, feed, r = process_two(tmp_path, "RD", start=DUE + 1.0,
                                       snapshots=snaps(("good", DUE + 2.0, 0.1), ("good-2", DUE + 3.0, 0.1)))
        rows = L.read_all(h2.bd.ledger)
        assert len(fills(h2)) == 1
        assert len([x for x in rows if x["kind"] == "pilot_fill" and x.get("fees_entry")]) == 1, "one entry fee"
        assert len(resolved(h2)) == 1, "one discharge"
        assert len({x["txn_id"] for x in outcomes(h2)}) == len(outcomes(h2)), "no duplicated outcome txn"
        assert len([x for x in resolved(h2) if x.get("fees_exit")]) == 1, "one exit fee"
        book = h2.bd.book()
        assert not book.problems and book.cash_identity()["holds"]

    def test_recovery_still_refuses_a_stale_or_malformed_quote(self, tmp_path):
        open_in_process_one(tmp_path, "RS")
        h2, rep, feed, r = process_two(tmp_path, "RS", start=DUE + 1.0,
                                       snapshots=snaps(("stale", DUE + 2.0, 40.0)))
        assert not resolved(h2)
        assert any("STALE_SELECTED_CONTRACT" in (o.get("why") or "") for o in outcomes(h2))
        # malformed: a quote missing its bid
        open_in_process_one(tmp_path / "m", "RM")
        h3 = harness(tmp_path / "m", "RM")
        lc3 = on_clock(h3, t0=DUE + 1.0)
        h3.bd.exit_policy = EP.EXIT_POLICY_V2
        feed3 = Feed(h3, snapshots=snaps(("bad", DUE + 2.0, 0.1)))
        good_call = feed3.__call__
        feed3.__class__ = type("BadFeed", (Feed,), {"__call__": lambda self, c: {k: v for k, v in good_call(c).items() if k != "bid"}})
        rep3, _ = run(h3, lc3, feed3)
        assert not resolved(h3), "a malformed quote must not discharge a position, recovery or not"

    def test_the_ledger_states_which_process_performed_each_attempt(self, tmp_path):
        open_in_process_one(tmp_path, "RP")
        h2, rep, feed, r = process_two(tmp_path, "RP", start=DUE + 1.0,
                                       snapshots=snaps(("good", DUE + 30.0, 0.1)), fail_until=DUE + 5.0)
        atts = outcomes(h2)
        assert atts, "process two made attempts"
        for o in atts:
            pi = o.get("process_identity")
            assert isinstance(pi, dict) and pi.get("process_id"), "every attempt names the process that made it"
            assert pi.get("inherited_position") is True, "and says the position was inherited"
        ids = {o["process_identity"]["process_id"] for o in atts}
        assert len(ids) == 1, "all of process two's attempts carry the same process id"


# ============================================================ 2. arrival-to-quote provenance


class TestArrivalToQuoteProvenance:

    def test_two_observations_with_the_same_timestamp_cannot_be_told_apart_by_timestamp(self, tmp_path):
        """REPRODUCER. Two distinct observations, same quote timestamp. Timestamp matching returns both."""
        h = harness(tmp_path, "PV")
        lc = on_clock(h)
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        same_ts = DUE + 0.3
        feed = Feed(h, snapshots=[{"observation_id": "A", "arrival": DUE + 0.4, "quote_ts": same_ts},
                                  {"observation_id": "B", "arrival": DUE + 0.5, "quote_ts": same_ts}])
        rep, r = run(h, lc, feed, scans=[T])
        o = resolved(h)[0]
        used_ts = o["exit_quote_observed"]["timestamp_epoch"]
        by_ts = [s for s in feed.snapshots if abs(s["quote_ts"] - used_ts) < 1e-9]
        assert len(by_ts) == 2, "timestamp matching is ambiguous here, by construction"
        # THE DURABLE IDENTITY resolves it
        assert o["exit_quote_observed"].get("observation_id") in ("A", "B")
        served = [s for s in feed.served if s["outcome"] == "SERVED"]
        assert o["exit_quote_observed"]["observation_id"] == served[-1]["observation_id"], \
            "the outcome names the observation the feed actually served"

    def test_the_quote_adapter_contract_carries_identity_and_availability(self, tmp_path):
        h = harness(tmp_path, "PC")
        lc = on_clock(h)
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        feed = Feed(h, snapshots=snaps(("X", DUE + 0.2, 0.1)))
        rep, r = run(h, lc, feed, scans=[T])
        q = resolved(h)[0]["exit_quote_observed"]
        assert q["observation_id"] == "X"
        assert q["available_epoch"] == DUE + 0.2
        assert q["identity_basis"], "the record says where the identity came from and that the boundary did not verify it"

    def test_an_arrival_triggered_exit_records_both_identities_and_whether_they_match(self, tmp_path):
        h = harness(tmp_path, "PM")
        lc = on_clock(h)
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        # the arrival that wakes the scheduler is "wake"; by the time the boundary asks, "newer" has also arrived
        # at the same instant, so the quote served is NOT the waking observation. The record must say so.
        # ids chosen so the canonical (minimum) representative is the waking one and the feed serves the other
        feed = Feed(h, snapshots=[{"observation_id": "a-wake", "arrival": DUE + 0.2, "quote_ts": DUE + 0.1},
                                  {"observation_id": "b-newer", "arrival": DUE + 0.2, "quote_ts": DUE + 0.15}])
        rep, r = run(h, lc, feed, scans=[T])
        arr = [e for e in rep["exits"] if e.get("event") == LC.EXIT_ARRIVAL]
        assert arr
        a = arr[0]
        for k in ("arrival_observation_id", "quote_observation_id", "request_epoch", "quote_available_epoch",
                  "same_observation"):
            assert k in a, k
        assert a["arrival_observation_id"] == "a-wake"
        assert a["quote_observation_id"] == "b-newer"
        assert a["same_observation"] is False, "an arrival only wakes the scheduler; it need not be the quote used"

    def test_a_matching_case_is_recorded_as_matching(self, tmp_path):
        h = harness(tmp_path, "PS")
        lc = on_clock(h)
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        feed = Feed(h, snapshots=snaps(("only", DUE + 0.2, 0.1)))
        rep, r = run(h, lc, feed, scans=[T])
        a = [e for e in rep["exits"] if e.get("event") == LC.EXIT_ARRIVAL][0]
        assert a["arrival_observation_id"] == a["quote_observation_id"] == "only"
        assert a["same_observation"] is True

    def test_a_quote_without_identity_is_recorded_as_unidentified_not_faked(self, tmp_path):
        h = harness(tmp_path, "PN")
        lc = on_clock(h)
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        feed = Feed(h, snapshots=snaps(("legacy", DUE + 0.2, 0.1)))
        base_call = Feed.__call__
        feed.__class__ = type("LegacyFeed", (Feed,), {"__call__": lambda self, c: {k: v for k, v in base_call(self, c).items()
                                                                                    if k not in ("observation_id", "available_epoch")}})
        rep, r = run(h, lc, feed, scans=[T])
        q = resolved(h)[0]["exit_quote_observed"]
        assert q["observation_id"] is None and q["available_epoch"] is None
        assert "NOT_SUPPLIED" in q["identity_basis"]


# ============================================================ 3. deterministic coalescing


class TestDeterministicCoalescing:

    def _pairs(self, ids):
        return [(DUE + 1.0, {"observation_id": i, "contract_id": CONTRACT}) for i in ids]

    def _trace(self, tmp_path, ids):
        h = harness(tmp_path, "CO")
        lc = on_clock(h)
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        feed = Feed(h, snapshots=[{"observation_id": i, "arrival": DUE + 1.0, "quote_ts": DUE + 0.9} for i in ids])
        rep, r = run(h, lc, feed, scans=[T], pairs=self._pairs(ids))
        arr = [e for e in rep["events"] if e["kind"] == LC.EXIT_ARRIVAL]
        assert len(arr) == 1
        out = dict(arr[0]["outcome"])
        return out, rep

    def test_permuted_input_order_yields_the_same_representative_and_digest(self, tmp_path):
        """REPRODUCER. At 16513b0 the representative was the LAST id in input order, so permuting the feed changed
        the trace."""
        ids = ["m", "c", "x", "a", "k"]
        o1, _ = self._trace(tmp_path / "1", ids)
        o2, _ = self._trace(tmp_path / "2", list(reversed(ids)))
        o3, _ = self._trace(tmp_path / "3", sorted(ids, key=lambda s: -ord(s[0])))
        for o in (o1, o2, o3):
            assert o["observation_id"] == "a", "the canonical representative is order-independent"
            assert o["n_coalesced"] == 5
            assert o["coalesced_ids_digest"] == o1["coalesced_ids_digest"]
        assert o1["observation_id"] == o2["observation_id"] == o3["observation_id"]

    def test_the_complete_id_set_is_not_truncated(self, tmp_path):
        ids = ["id-%03d" % i for i in range(40)]
        o, _ = self._trace(tmp_path, ids)
        assert o["n_coalesced"] == 40
        assert sorted(o["coalesced_ids"]) == sorted(ids), "all forty are carried; nothing is elided"
        assert "..." not in o["coalesced_ids"]

    def test_lifecycle_records_are_byte_identical_apart_from_declared_ordering_metadata(self, tmp_path):
        ids = ["m", "c", "x", "a", "k"]
        _, rep1 = self._trace(tmp_path / "1", ids)
        _, rep2 = self._trace(tmp_path / "2", list(reversed(ids)))

        def strip(rep):
            evs = []
            for e in rep["events"]:
                e = json.loads(json.dumps(e))
                if e["kind"] == LC.EXIT_ARRIVAL:
                    e["outcome"].pop("input_order", None)      # the ONE declared ordering field
                evs.append(e)
            return json.dumps(evs, sort_keys=True)
        assert strip(rep1) == strip(rep2)

    def test_the_digest_is_over_the_sorted_set(self, tmp_path):
        import hashlib
        ids = ["m", "c", "x"]
        o, _ = self._trace(tmp_path, ids)
        expected = hashlib.sha256(json.dumps(sorted(ids), separators=(",", ":")).encode()).hexdigest()
        assert o["coalesced_ids_digest"] == expected


# ============================================================ acceptance carried forward


class TestCarriedForwardAcceptance:

    def test_the_127ms_fixture_still_separates_v1_from_v2(self, tmp_path):
        def one(policy, sub):
            h = harness(tmp_path / sub, "H")
            lc = on_clock(h)
            h.bd.exit_policy = policy
            feed = Feed(h, snapshots=snaps(("p", DUE - 60.0 + 0.127, 0.128), ("q", DUE + 0.127, 0.128),
                                           ("r", DUE + 60.127, 0.128)))
            run(h, lc, feed, scans=[T])
            return h
        assert resolved(one(EP.EXIT_POLICY_V2, "v2"))
        h1 = one(EP.EXIT_POLICY_V1, "v1")
        assert not resolved(h1) and len(outcomes(h1)) == 5

    @pytest.mark.parametrize("offset", [0.0, 3.7, 11.2, 14.9, 15.1, 22.5, 31.0, 44.4, 52.8, 59.9])
    def test_the_phase_sweep_still_passes(self, tmp_path, offset):
        h = harness(tmp_path, "SW")
        lc = on_clock(h)
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        feed = Feed(h, snapshots=snaps(("a", DUE - 60.0 + offset, 0.1), ("b", DUE + offset, 0.1),
                                       ("c", DUE + 60.0 + offset, 0.1), ("d", DUE + 120.0 + offset, 0.1)))
        run(h, lc, feed, scans=[T])
        assert resolved(h), offset

    def test_no_future_observation_is_ever_served(self, tmp_path):
        h = harness(tmp_path, "FUT")
        lc = on_clock(h)
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        feed = Feed(h, snapshots=snaps(("a", DUE + 0.5, 0.1), ("b", DUE + 40.0, 0.1), ("c", DUE + 80.0, 0.1)))
        run(h, lc, feed, scans=[T])
        for s in feed.served:
            if s["outcome"] == "SERVED":
                assert s["arrival"] <= s["asked_at"]
        for o in outcomes(h):
            q = o.get("exit_quote_observed") or {}
            if q.get("available_epoch") is not None:
                # THE LAW IS AVAILABILITY <= RECEIPT. A live request may legitimately be served a quote that became
                # available while the request was in flight, so availability <= REQUEST is NOT required and this
                # assertion deliberately does not demand it (EXIT-SCHEDULING-003 correction).
                assert q["available_epoch"] <= o["exit_quote_receipt_epoch"], "availability never postdates receipt"

    def test_limits_hash_and_suppression_are_unchanged(self):
        assert B.MAX_SELECTED_QUOTE_AGE_S == 15.0
        assert EP.EXIT_POLICY_V2.max_attempts == 5 and EP.EXIT_POLICY_V2.window_s == 120.0
        assert EP.EXIT_POLICY_V2.skip_timer_when_no_new_observation is False
        assert EP.EXIT_POLICY_V1.policy_hash == "9f9784f7af5b9c198e9bad69432488cb86c58a482a4d83e62dc18dcb9eb1e5af"
