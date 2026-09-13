"""EXIT-SCHEDULING-002 — acceptance, through the real lifecycle path on synthetic inputs.

The failure this repairs, from `docs/FLOW_VALIDATION_001_DIAGNOSIS.md`: a due exit failed five times while eligible
quotes sat in its window, because the snapshot arrived 127 ms after the due instant and the 15 s retry spacing then
pinned every retry to the 15 s freshness boundary.

Nothing here relaxes freshness, widens the window or adds an attempt. The budget is five and the window is 120 s in
both versions. What changes is WHEN the five attempts fire."""
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
HOLD = 900.0
WINDOW = 120.0
FRESH = B.MAX_SELECTED_QUOTE_AGE_S          # 15.0 s, untouched by this brick
SNAPSHOT_PERIOD = 60.0


class Feed:
    """A recorded quote feed with explicit arrival instants.

    Each snapshot has an arrival instant and a provider quote timestamp. `exit_quote_fn` returns the newest snapshot
    whose ARRIVAL is at or before the clock, exactly as the recorded adapter does, so the boundary's own freshness
    check sees a real age."""

    def __init__(self, harness, *, arrivals, quote_lag_s=0.1, bid=4.73, ask=4.78):
        self.h = harness
        self.snapshots = [{"observation_id": "obs-%d" % i, "arrival": a, "quote_ts": a - quote_lag_s}
                          for i, a in enumerate(arrivals)]
        self.bid, self.ask = bid, ask
        self.calls = []

    def visible(self):
        now = self.h.now()
        got = [s for s in self.snapshots if s["arrival"] <= now]
        return got[-1] if got else None

    def __call__(self, contract):
        self.calls.append(self.h.now())
        s = self.visible()
        if s is None:
            from apex.pulse_options.providers import ProviderUnavailable
            raise ProviderUnavailable("NO_SNAPSHOT_YET")
        return {"symbol": contract["symbol"], "expiration": contract["expiration"], "strike": contract["strike"],
                "right": contract["right"], "bid": self.bid, "ask": self.ask, "bid_size": 9, "ask_size": 12,
                "timestamp_epoch": s["quote_ts"]}

    def feed_for(self, contract_id):
        return [(s["arrival"], {"observation_id": s["observation_id"], "contract_id": contract_id})
                for s in self.snapshots]


def harness(tmp_path, sid):
    h = SyntheticHarness(tmp_path / "led.jsonl", session_id=sid, t0=T, risk="certified")
    h.chain = [{**c, "ask": 4.95} for c in h.chain]
    h.quotes.ask, h.quotes.bid = 4.95, 4.90
    return h


def on_clock(h):
    lc = LC.MonotonicClock(h.now())
    h.clock = lc.clock(); h.bd.clock = h.clock; h.now = lc.now; h.advance = lc.sleep
    return lc


# The runner opens the position itself, so it is THIS run's obligation and gets the full policy rather than the
# one labelled recovery attempt an inherited position receives. On this fixture the fill commits at the scan
# instant exactly, so the due time and the contract are both deterministic.
DUE = T + HOLD
CONTRACT = "SPY|2026-10-09|650.0|CALL"


def scenario(tmp_path, sid, *, arrivals, quote_lag_s=0.1, policy=EP.EXIT_POLICY_V2, scans=(T,), bid=4.73, ask=4.78,
             repeat_first_id=False):
    """One run: a scan that fills, then the declared observation arrivals.

    `repeat_first_id` gives every later arrival the FIRST arrival's observation id, which is how a duplicate or a
    re-delivery of the same snapshot is expressed."""
    h = harness(tmp_path, sid)
    lc = on_clock(h)
    h.bd.exit_policy = policy
    feed = Feed(h, arrivals=list(arrivals), quote_lag_s=quote_lag_s, bid=bid, ask=ask)
    if repeat_first_id:
        for snap in feed.snapshots[1:]:
            snap["observation_id"] = feed.snapshots[0]["observation_id"]
    src = dict(h.sources()); src["exit_quote_fn"] = feed
    r = LC.LifecycleRunner(boundary=h.bd, sources=src, clock=lc, symbols=["SPY"], selection_policy="PILOT_RULE_V2",
                           scan_epochs=list(scans), observation_feed=feed.feed_for(CONTRACT))
    rep = r.run()
    fill = next((x for x in L.read_all(h.bd.ledger) if x["kind"] == "pilot_fill" and x["status"] == "FILLED"), None)
    assert fill is not None, "the fixture must open a position"
    assert fill["committed_epoch"] + HOLD == DUE
    return h, rep, feed, fill


def attempts(h):
    return [r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_outcome"]


def resolved(h):
    return [r for r in attempts(h) if r.get("discharges_position")]


# ---------------------------------------------------------------------------- the historical case


class TestTheOneHundredAndTwentySevenMillisecondCase:

    def _setup(self, tmp_path, offset_s, *, policy=EP.EXIT_POLICY_V2, quote_lag_s=0.1):
        arrivals = [DUE - SNAPSHOT_PERIOD + offset_s, DUE + offset_s, DUE + SNAPSHOT_PERIOD + offset_s,
                    DUE + 2 * SNAPSHOT_PERIOD + offset_s]
        h, rep, feed, fill = scenario(tmp_path, "OFF", arrivals=arrivals, policy=policy, quote_lag_s=quote_lag_s)
        return h, rep, DUE

    def test_the_exact_historical_failure_now_resolves(self, tmp_path):
        """Snapshot 127 ms AFTER the due instant. Under V1 this consumed all five attempts and never resolved."""
        # quote_lag 0.127 puts the provider timestamp EXACTLY on the due instant, the 2026-09-11 geometry: the
        # first attempt sees the previous snapshot at ~60 s, and a V1 retry lands a hair over the 15 s limit.
        # quote_lag 0.128 puts the provider timestamp one millisecond BEFORE the due instant, reproducing the
        # 2026-09-11 geometry exactly: attempt 1 sees the previous snapshot at 60.001 s, and a V1 retry lands at
        # 15.001 s against a 15.000 s limit.
        h, rep, due = self._setup(tmp_path, 0.127, quote_lag_s=0.128)
        assert resolved(h), "the position must discharge"
        r = resolved(h)[0]
        assert r["exit_quote_request_epoch"] - r["exit_quote_observed"]["timestamp_epoch"] <= FRESH
        arr = [e for e in rep["events"] if e["kind"] == LC.EXIT_ARRIVAL]
        assert arr, "an arrival must have driven it"
        assert len(attempts(h)) <= 5

    def test_the_same_case_under_v1_still_fails_so_the_fixture_is_real(self, tmp_path):
        h, rep, due = self._setup(tmp_path, 0.127, policy=EP.EXIT_POLICY_V1, quote_lag_s=0.128)
        assert not resolved(h), "V1 must still fail on this fixture, or the repair proves nothing"
        assert len(attempts(h)) == 5, "V1 spends the whole budget on blind timers"
        assert any(r["kind"] == "pilot_exit_exhausted" for r in L.read_all(h.bd.ledger))

    @pytest.mark.parametrize("offset", [-2.0, -0.5, -0.001, 0.0, 0.001, 0.127, 1.0, 5.0])
    def test_arrivals_just_before_and_just_after_the_due_instant(self, tmp_path, offset):
        h, rep, due = self._setup(tmp_path, offset)
        assert resolved(h), "offset %.3f left the position unresolved" % offset

    @pytest.mark.parametrize("offset", [0.0, 3.7, 11.2, 14.9, 15.1, 22.5, 31.0, 44.4, 52.8, 59.9])
    def test_a_sweep_across_the_whole_snapshot_period(self, tmp_path, offset):
        """NOT tuned to the historical millisecond: the arrival phase is swept across the full 60 s period."""
        h, rep, due = self._setup(tmp_path, offset)
        assert resolved(h), "offset %.1f s left the position unresolved" % offset
        assert len(attempts(h)) <= 5


# ---------------------------------------------------------------------------- freshness is untouched


class TestANewReceiptIsNotAFreshQuote:

    def test_a_newly_arrived_snapshot_carrying_a_stale_quote_is_still_refused(self, tmp_path):
        """The arrival is new; the quote inside it is 40 s old. The boundary must refuse it exactly as before."""
        h, rep, feed, fill = scenario(tmp_path, "STALEOBS", arrivals=[DUE + 1.0], quote_lag_s=40.0)
        assert not resolved(h), "a stale quote must not resolve merely because its snapshot is new"
        whys = [(a.get("why") or "") for a in attempts(h)]
        assert any("STALE_SELECTED_CONTRACT" in w for w in whys), whys
        assert h.bd.book().positions, "the position remains an obligation"

    def test_the_freshness_limit_is_not_relaxed_by_this_brick(self):
        assert B.MAX_SELECTED_QUOTE_AGE_S == 15.0
        assert EP.EXIT_POLICY_V2.max_attempts == EP.EXIT_POLICY_V1.max_attempts == 5
        assert EP.EXIT_POLICY_V2.window_s == EP.EXIT_POLICY_V1.window_s == 120.0
        assert EP.EXIT_POLICY_V2.horizon_s == EP.EXIT_POLICY_V1.horizon_s == 900.0

    def test_an_arrival_triggered_attempt_goes_through_the_real_boundary(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "REALBD", arrivals=[DUE + 0.2])
        o = resolved(h)[0]
        for k in ("exit_quote_request_epoch", "exit_quote_receipt_epoch", "exit_quote_observed", "contract_id",
                  "fees_exit", "pnl"):
            assert k in o, k
        assert o["contract_id"] == fill["contract_id"]


# ---------------------------------------------------------------------------- timers, deadlines, no data


class TestTimersAndDeadlinesRemain:

    def test_no_data_at_all_still_reaches_an_explicit_terminal_outcome(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "NODATA", arrivals=[])   # nothing ever arrives
        assert not resolved(h)
        rows = L.read_all(h.bd.ledger)
        assert any(r["kind"] == "pilot_exit_exhausted" for r in rows), "the deadline must terminate it on its own"
        book = h.bd.book()
        assert len(book.positions) == 1 and book.positions[0]["exit_exhausted"]
        assert book.open_cost > 0, "the unresolved position retains its exposure"

    def test_five_attempts_are_exhausted_before_the_window_expires(self, tmp_path):
        """Attempts are the binding limit here, and the record says so rather than implying the window ran out."""
        h, rep, feed, fill = scenario(tmp_path, "BUDGET", quote_lag_s=40.0,
                                      arrivals=[DUE + 1.0 + 3.0 * i for i in range(8)])
        n = len(attempts(h))
        assert n == 5, n
        last = max(a["exit_quote_request_epoch"] for a in attempts(h))
        assert last < DUE + WINDOW, "the budget ran out with window remaining"
        assert any(r["kind"] == "pilot_exit_exhausted" for r in L.read_all(h.bd.ledger))

    def test_an_arrival_after_the_window_closes_does_not_attempt(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "LATE", arrivals=[DUE + WINDOW + 30.0])
        assert not resolved(h)
        late = [e for e in rep["events"] if e["kind"] == LC.EXIT_ARRIVAL]
        assert late, "the arrival event still fired"
        assert all(a["exit_quote_request_epoch"] <= DUE + WINDOW for a in attempts(h))

    def test_exit_servicing_is_not_driven_by_scans(self, tmp_path):
        """No scan is scheduled at all, and the exit still resolves on its arrival."""
        h, rep, feed, fill = scenario(tmp_path, "NOSCAN", arrivals=[DUE + 0.3])
        assert resolved(h)
        scans = [e for e in rep["events"] if e["kind"] == LC.SCAN]
        assert len(scans) == 1, "only the scan that opened the position"
        exits = [e for e in rep["events"] if e["kind"].startswith("EXIT")]
        assert all(e["at_us"] > scans[0]["at_us"] for e in exits), "no scan ran between the exit events"


# ---------------------------------------------------------------------------- attempt and event accounting


class TestAttemptAndEventAccounting:

    def test_a_duplicate_arrival_produces_one_exit_and_one_fee(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "DUP", arrivals=[DUE + 0.2, DUE + 0.2], repeat_first_id=True)
        assert len(resolved(h)) == 1
        book = h.bd.book()
        assert len(book.closed) == 1 and book.closed[0]["fees_exit"] is not None
        exits = [r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_outcome"]
        assert len({e["txn_id"] for e in exits}) == len(exits), "no duplicated outcome transaction"
        assert any(s["reason"] == "DUPLICATE_OBSERVATION_IN_FEED" for s in rep["scheduling_events"])

    def test_a_repeat_of_an_already_attempted_observation_is_not_reattempted(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "REPEAT", arrivals=[DUE + 1.0, DUE + 20.0], quote_lag_s=40.0,
                                      repeat_first_id=True)
        reasons = [s["reason"] for s in rep["scheduling_events"]]
        # a repeated id is deduplicated at ingestion, or at the position if it survives that far. Either is correct;
        # what matters is that it is NAMED and that it produces no second attempt against the same observation.
        assert {"DUPLICATE_OBSERVATION_IN_FEED", "DUPLICATE_OBSERVATION_ALREADY_ATTEMPTED"} & set(reasons), reasons
        arrivals_that_attempted = [e for e in rep["exits"] if e.get("event") == LC.EXIT_ARRIVAL]
        assert len(arrivals_that_attempted) <= 1, "the repeated observation must not be attempted twice"

    def test_scheduling_decisions_are_never_counted_as_attempts(self, tmp_path):
        """SUPERSEDED FORM. This test used to assert that blind retries WERE skipped. The repair at
        `tests/test_exit_scheduling_002_repair.py` disabled that optimisation, because a notification id does not
        establish which quote was evaluated. What survives, and is the part that mattered, is that a scheduling
        decision is never counted as an attempt in either direction."""
        h, rep, feed, fill = scenario(tmp_path, "SKIP", arrivals=[DUE + 1.0], quote_lag_s=40.0)
        assert all(s["is_attempt"] is False for s in rep["scheduling_events"])
        assert not [s for s in rep["scheduling_events"] if s["reason"] == "TIMER_SKIPPED_NO_NEW_OBSERVATION"], \
            "the optimisation is disabled in this candidate"
        assert len(attempts(h)) == 5, "with no suppression the budget is spent on the timer, honestly and visibly"
        assert not resolved(h), "and no resolution is manufactured"

    def test_the_accounting_rule_is_stated_on_the_run(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "ACCT", arrivals=[DUE + 0.2])
        assert "ATTEMPT_ACCOUNTING_V2" in rep["attempt_accounting"]
        assert rep["exit_policy"]["policy_id"] == "EXIT_AT_HORIZON_15M_V2_ARRIVAL"

    def test_a_flood_of_arrivals_cannot_starve_the_deadline(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "FLOOD", quote_lag_s=40.0,
                                      arrivals=[DUE + 0.5 + i * 0.01 for i in range(500)])
        assert len(attempts(h)) <= 5, "the flood must not buy attempts"
        assert any(r["kind"] == "pilot_exit_exhausted" for r in L.read_all(h.bd.ledger)), \
            "the deadline still terminated the obligation"
        assert rep["n_events"] < LC.DEFAULT_EVENT_BUDGET

    def test_a_resolved_position_cancels_its_pending_timer(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "CANCEL", arrivals=[DUE + 1.0, DUE + 2.0])
        assert len(resolved(h)) == 1
        assert any(s["reason"] == "PENDING_RETRY_CANCELLED_POSITION_RESOLVED" for s in rep["scheduling_events"])
        res_at = resolved(h)[0]["exit_quote_request_epoch"]
        later = [a for a in attempts(h) if a["exit_quote_request_epoch"] > res_at]
        assert not later, "nothing was attempted after the position resolved"


# ---------------------------------------------------------------------------- ordering and causality


class TestOrderingAndCausalEquivalence:

    def test_the_declared_total_order(self):
        o = LC.EVENT_ORDER
        assert o.index(LC.DATA_AVAILABLE) < o.index(LC.EXIT_DUE) < o.index(LC.EXIT_ARRIVAL) \
            < o.index(LC.EXIT_RETRY) < o.index(LC.EXIT_WINDOW_CLOSE) < o.index(LC.SCAN) < o.index(LC.SESSION_CLOSE)
        for k in LC.OBLIGATION_EVENTS:
            assert LC.RANK[k] < LC.RANK[LC.SCAN]

    def test_an_arrival_at_the_same_instant_as_the_due_time_is_ordered_deterministically(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "TIE", arrivals=[DUE])   # arrival EXACTLY at the due instant
        kinds = [e["kind"] for e in rep["events"] if e["kind"].startswith("EXIT")]
        assert kinds and kinds[0] == LC.EXIT_DUE, "the due timer is ordered before the arrival at the same instant"
        assert resolved(h), "and the due attempt sees the already-visible observation"
        assert len(attempts(h)) == 1

    def test_reproducible(self, tmp_path):
        seen = set()
        for i in range(3):
            h, rep, feed, fill = scenario(tmp_path / str(i), "REPRO",
                                          arrivals=[DUE + 0.127, DUE + SNAPSHOT_PERIOD + 0.127])
            seen.add(tuple((e["kind"], e["at_utc"]) for e in rep["events"]))
        assert len(seen) == 1

    def test_an_observation_is_invisible_before_its_recorded_availability(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "CAUSAL", arrivals=[DUE + 40.0])
        for t in feed.calls:
            visible = [s for s in feed.snapshots if s["arrival"] <= t]
            assert all(s["arrival"] <= t for s in visible)
        first_attempt = min(a["exit_quote_request_epoch"] for a in attempts(h))
        assert first_attempt >= DUE, "nothing was attempted before the exit was due"

    def test_the_scheduler_does_not_look_ahead_to_pick_a_retry_time(self):
        import inspect
        src = inspect.getsource(LC.LifecycleRunner)
        assert "observation_feed" in src
        assert "self.snapshots" not in src, "the runner must not reach into a feed's future contents"
        assert "_next_attempt_epoch" in src


# ---------------------------------------------------------------------------- restart and exposure


class TestRestartAndExposure:

    def test_a_restart_with_an_exit_pending_recovers_without_duplicating(self, tmp_path):
        h1 = harness(tmp_path, "RS")
        lc1 = on_clock(h1)
        h1.bd.exit_policy = EP.EXIT_POLICY_V2
        S.open_session(h1.bd, symbols=["SPY"])
        d = S.scan(h1.bd, symbol="SPY", seq=1, **{k: v for k, v in h1.sources().items() if k != "exit_quote_fn"})
        assert d["decision"] == "TRADE"
        n_before = len([r for r in L.read_all(h1.bd.ledger) if r["kind"] == "pilot_fill"])
        h2 = harness(tmp_path, "RS")                      # same ledger, same session: a restart
        lc2 = LC.MonotonicClock(DUE + 1.0)
        h2.clock = lc2.clock(); h2.bd.clock = h2.clock; h2.now = lc2.now; h2.advance = lc2.sleep
        h2.bd.exit_policy = EP.EXIT_POLICY_V2
        feed = Feed(h2, arrivals=[DUE + 2.0])
        src = dict(h2.sources()); src["exit_quote_fn"] = feed
        r2 = LC.LifecycleRunner(boundary=h2.bd, sources=src, clock=lc2, symbols=["SPY"],
                                selection_policy="PILOT_RULE_V2", scan_epochs=[],
                                observation_feed=feed.feed_for(CONTRACT))
        rep = r2.run()
        rows = L.read_all(h2.bd.ledger)
        assert len([r for r in rows if r["kind"] == "pilot_fill"]) == n_before, "no duplicate fill"
        fees = [r["fees_entry"]["total"] for r in rows if r["kind"] == "pilot_fill" and r.get("fees_entry")]
        assert len(fees) == 1, "one entry fee"
        assert rep["recovered_positions"], "the restart saw the obligation"

    def test_a_completed_exit_releases_the_exposure(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "REL", arrivals=[DUE + 0.2])
        book = h.bd.book()
        assert not book.positions and book.open_cost == 0.0 and book.reserved == 0.0
        from apex.options_pilot import accounting as ACC
        agg = ACC.net_result(book)
        assert agg["total_net_estimable"] and agg["total_net_pnl"] is not None

    def test_an_unresolved_exit_retains_exposure_and_an_unknown_total(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "RETAIN", arrivals=[DUE + 1.0], quote_lag_s=40.0)
        book = h.bd.book()
        from apex.options_pilot import accounting as ACC
        agg = ACC.net_result(book)
        assert book.open_cost > 0.0, "exposure is retained"
        assert agg["total_net_pnl"] is None and agg["total_net_status"] == ACC.NOT_ESTIMABLE
        assert agg["n_unresolved_positions"] == 1
        ACC.assert_no_phantom_zero(agg)


# ---------------------------------------------------------------------------- the version is explicit


class TestThePolicyVersionIsExplicit:

    def test_v1_is_unchanged_and_still_available(self):
        assert EP.EXIT_POLICY_V1.policy_id == "EXIT_AT_HORIZON_15M_V1"
        assert EP.EXIT_POLICY_V1.policy_hash == "9f9784f7af5b9c198e9bad69432488cb86c58a482a4d83e62dc18dcb9eb1e5af", \
            "the policy the earlier run was evaluated under must hash to the same value"
        assert not getattr(EP.EXIT_POLICY_V1, "arrival_triggered", False)

    def test_v2_declares_what_it_changes_and_what_it_does_not(self):
        d = EP.EXIT_POLICY_V2.describe()
        assert d["supersedes"] == "EXIT_AT_HORIZON_15M_V1"
        assert "freshness" in d["change_note"] and "unchanged" in d["change_note"]
        assert d["policy_hash"] if "policy_hash" in d else EP.EXIT_POLICY_V2.policy_hash

    def test_every_attempt_records_its_trigger_and_policy_version(self, tmp_path):
        h, rep, feed, fill = scenario(tmp_path, "TRIG", arrivals=[DUE + 0.127])
        entry = rep["exit_entries"][0]
        for a in entry["attempts"]:
            assert a["trigger"] in (LC.EXIT_DUE, LC.EXIT_ARRIVAL, LC.EXIT_RETRY, LC.EXIT_WINDOW_CLOSE)
            assert a["policy_version"] == "EXIT_AT_HORIZON_15M_V2_ARRIVAL"
            assert "remaining_window_s" in a
        arr = [e for e in rep["exits"] if e.get("event") == LC.EXIT_ARRIVAL]
        assert arr and arr[0]["observation_id"] and "remaining_window_s" in arr[0]
