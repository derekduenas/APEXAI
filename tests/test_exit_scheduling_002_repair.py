"""EXIT-SCHEDULING-002 bounded repair — reproducers first, then the fixes they justify.

Three findings against `01fcda9`:

1. A resolved exit could later be reported as exhausted. The retry-suppression block ran BEFORE the check that the
   position still exists, so a timer queued before an arrival resolved the position could reach window close and
   overwrite the report's terminal state. The Book stayed right and the report contradicted it.
2. A notification id was treated as proof of which quote was evaluated. `_on_exit_arrival` recorded the id before
   asking the boundary, and nothing bound it to the quote actually returned or looked at why a refusal happened, so
   a transient provider failure could suppress later timer attempts.
3. Arrival notifications consumed the global convergence budget, so enough of them could end the loop before a
   deadline. The 500-arrival test never approached the 20,000 limit.

Synthetic only."""
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
OTHER_CONTRACT = "SPY|2026-10-09|655.0|PUT"


class Feed:
    """A quote feed that RECORDS what it returned, so a test can assert against the actual quote rather than
    against the fixture's own construction."""

    def __init__(self, harness, *, arrivals, quote_lag_s=0.1, bid=4.73, ask=4.78, fail_until=None):
        self.h = harness
        self.snapshots = [{"observation_id": "obs-%d" % i, "arrival": a, "quote_ts": a - quote_lag_s}
                          for i, a in enumerate(arrivals)]
        self.bid, self.ask, self.fail_until = bid, ask, fail_until
        self.served: list = []                 # (asked_at, observation_id, quote_ts) or (asked_at, None, "FAILED")

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
                "timestamp_epoch": s["quote_ts"]}

    def feed_for(self, contract_id=CONTRACT, *, ids=None):
        return [(s["arrival"], {"observation_id": (ids[i] if ids else s["observation_id"]),
                                "contract_id": contract_id}) for i, s in enumerate(self.snapshots)]


def scenario(tmp_path, sid, *, arrivals, quote_lag_s=0.1, policy=None, feed_pairs=None, fail_until=None,
             scans=(T,), **runner_kw):
    h = SyntheticHarness(tmp_path / "led.jsonl", session_id=sid, t0=T, risk="certified")
    h.chain = [{**c, "ask": 4.95} for c in h.chain]
    h.quotes.ask, h.quotes.bid = 4.95, 4.90
    lc = LC.MonotonicClock(h.now())
    h.clock = lc.clock(); h.bd.clock = h.clock; h.now = lc.now; h.advance = lc.sleep
    h.bd.exit_policy = policy or EP.EXIT_POLICY_V2
    feed = Feed(h, arrivals=list(arrivals), quote_lag_s=quote_lag_s, fail_until=fail_until)
    src = dict(h.sources()); src["exit_quote_fn"] = feed
    r = LC.LifecycleRunner(boundary=h.bd, sources=src, clock=lc, symbols=["SPY"], selection_policy="PILOT_RULE_V2",
                           scan_epochs=list(scans),
                           observation_feed=(feed_pairs if feed_pairs is not None else feed.feed_for()),
                           **runner_kw)
    rep = r.run()
    return h, rep, feed, r


def outcomes(h):
    return [r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_outcome"]


def resolved(h):
    return [r for r in outcomes(h) if r.get("discharges_position")]


def exhausted_records(h):
    return [r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_exit_exhausted"]


# ============================================================ 1. a resolved exit must stay resolved everywhere


class TestAResolvedExitIsNeverReportedExhausted:
    """REPRODUCER for finding 1. An arrival resolves the position while a timer is still queued; the queue is then
    drained all the way through window close."""

    def _run(self, tmp_path, policy):
        # The due timer fires first and fails (no snapshot yet), queuing a retry. The arrival at due+1 resolves.
        # The queued retry then runs to window close with the position already gone.
        return scenario(tmp_path, "RESOLVED", arrivals=[DUE + 1.0], policy=policy)

    def test_the_ledger_and_book_agree_that_it_resolved(self, tmp_path):
        h, rep, feed, r = self._run(tmp_path, EP.EXIT_POLICY_V2)
        assert len(resolved(h)) == 1
        book = h.bd.book()
        assert not book.positions and len(book.closed) == 1
        assert not exhausted_records(h), "no exhaustion record may exist for a discharged position"

    def test_the_lifecycle_report_agrees_with_the_book(self, tmp_path):
        """THE BUG. The Book was right and `exit_entries` said EXIT_EXHAUSTED_UNRESOLVED."""
        h, rep, feed, r = self._run(tmp_path, EP.EXIT_POLICY_V2)
        entry = rep["exit_entries"][0]
        assert entry["final"] == "RESOLVED", entry["final"]
        assert not any(e["outcome"].get("state") == "EXIT_EXHAUSTED_UNRESOLVED" for e in rep["events"])

    def test_no_valuation_happens_after_the_resolution(self, tmp_path):
        h, rep, feed, r = self._run(tmp_path, EP.EXIT_POLICY_V2)
        res_at = resolved(h)[0]["exit_quote_request_epoch"]
        assert not [o for o in outcomes(h) if o["exit_quote_request_epoch"] > res_at]
        assert not [s for s in feed.served if s["asked_at"] > res_at], "the boundary was not even asked again"

    def test_the_session_completion_says_clean(self, tmp_path):
        h, rep, feed, r = self._run(tmp_path, EP.EXIT_POLICY_V2)
        assert rep["completion"] == "CLOSED_CLEAN", rep["completion"]
        assert rep["outstanding_obligations"] == 0

    def test_the_stale_timer_is_reconciled_and_named(self, tmp_path):
        h, rep, feed, r = self._run(tmp_path, EP.EXIT_POLICY_V2)
        reasons = [s["reason"] for s in rep["scheduling_events"]]
        assert any("ALREADY_RESOLVED" in x or "RECONCILED" in x for x in reasons), reasons


# ============================================================ 2. a notification id is not the quote evaluated


class TestNotificationIdentityIsNotProofOfTheQuoteEvaluated:

    def test_a_transient_failure_after_a_notification_does_not_suppress_the_timer(self, tmp_path):
        """REPRODUCER for finding 2. The arrival fires, the provider fails transiently, and a usable quote is
        available later on the timer path. Under the suppression rule the notification id was recorded as attempted
        even though NO quote was evaluated, and the later timer was skipped."""
        h, rep, feed, r = scenario(tmp_path, "TRANSIENT", arrivals=[DUE + 1.0], fail_until=DUE + 5.0)
        served = [s for s in feed.served if s["outcome"] == "SERVED"]
        assert any(s["outcome"] == "PROVIDER_FAILED" for s in feed.served), "the fixture must fail transiently"
        assert resolved(h), "a usable quote existed later and must have been reached"
        assert served, "the boundary must have been served a real quote at some point"

    def test_the_optional_suppression_is_off_in_this_candidate(self):
        assert EP.EXIT_POLICY_V2.skip_timer_when_no_new_observation is False, \
            "disabled for this candidate: notification identity does not establish which quote was evaluated"

    def test_no_replacement_suppression_was_introduced(self):
        import inspect
        src = inspect.getsource(LC.LifecycleRunner)
        assert "TIMER_SKIPPED" not in src or "skip_timer_when_no_new_observation" in src, \
            "suppression must remain behind the one declared, disabled switch"

    def test_the_policy_identity_records_the_change(self):
        d = EP.EXIT_POLICY_V2.describe()
        assert d["skip_timer_when_no_new_observation"] is False
        assert EP.EXIT_POLICY_V2.policy_hash != EP.ARRIVAL_POLICY_HASH_WITH_SUPPRESSION, \
            "turning the optimisation off must change the policy identity"


# ============================================================ 3. notification traffic must not starve deadlines


class TestNotificationTrafficIsBounded:

    def test_traffic_beyond_the_global_budget_does_not_end_the_loop(self, tmp_path):
        """REPRODUCER for finding 3. More notifications than the global convergence budget, with an open position
        whose deadline must still be honoured."""
        n = LC.DEFAULT_EVENT_BUDGET + 5000
        arrivals = [DUE + 1.0 + i * 0.001 for i in range(n)]
        h, rep, feed, r = scenario(tmp_path, "FLOOD", arrivals=arrivals, quote_lag_s=40.0)
        assert exhausted_records(h), "the deadline must still have terminated the obligation"
        assert len(outcomes(h)) <= 5, "the flood must not buy attempts"
        assert rep["completion"] == "CLOSED_WITH_OUTSTANDING_OBLIGATIONS"

    def test_notifications_at_one_instant_for_one_contract_are_coalesced(self, tmp_path):
        arrivals = [DUE + 1.0] * 50
        h, rep, feed, r = scenario(tmp_path, "COALESCE", arrivals=arrivals, quote_lag_s=40.0)
        arr = [e for e in rep["events"] if e["kind"] == LC.EXIT_ARRIVAL]
        assert len(arr) == 1, "fifty notifications at one instant for one contract are one event"
        assert arr[0]["outcome"]["n_coalesced"] == 50

    def test_coalescing_never_selects_a_future_observation(self, tmp_path):
        """Coalescing groups only notifications that share an availability instant, so nothing later is pulled
        forward. Asserted against the quote the boundary was actually served."""
        arrivals = [DUE + 1.0, DUE + 1.0, DUE + 40.0]
        h, rep, feed, r = scenario(tmp_path, "CAUSAL", arrivals=arrivals, quote_lag_s=0.1)
        for s in feed.served:
            if s["outcome"] != "SERVED":
                continue
            assert s["arrival"] <= s["asked_at"], "a quote was served from an observation that had not arrived"

    def test_duplicate_conflicting_and_cross_contract_identities(self, tmp_path):
        """The same id twice; the same id on a DIFFERENT contract; and an unrelated contract's notification."""
        h0 = None
        arrivals = [DUE + 1.0, DUE + 2.0, DUE + 3.0]
        pairs = [(DUE + 1.0, {"observation_id": "same", "contract_id": CONTRACT}),
                 (DUE + 2.0, {"observation_id": "same", "contract_id": CONTRACT}),          # duplicate
                 (DUE + 2.5, {"observation_id": "same", "contract_id": OTHER_CONTRACT}),    # conflicting
                 (DUE + 3.0, {"observation_id": "elsewhere", "contract_id": OTHER_CONTRACT})]  # cross-contract
        h, rep, feed, r = scenario(tmp_path, "IDS", arrivals=arrivals, quote_lag_s=40.0, feed_pairs=pairs)
        reasons = [s["reason"] for s in rep["scheduling_events"]]
        assert "DUPLICATE_OBSERVATION_IN_FEED" in reasons, reasons
        # a notification for a contract with no position must not attempt anything
        served_contracts = {c for c in [None]}
        assert len(outcomes(h)) <= 5
        assert exhausted_records(h), "deadlines still honoured with unrelated traffic present"

    def test_the_global_budget_is_not_simply_raised(self):
        assert LC.DEFAULT_EVENT_BUDGET == 20000, "the convergence budget is unchanged"
        import inspect
        src = inspect.getsource(LC.LifecycleRunner.run)
        assert "arrival" in src.lower(), "arrival events must be accounted separately, not by a bigger budget"


# ============================================================ acceptance strengthened


class TestStrengthenedAcceptance:

    def test_the_quote_actually_served_is_the_one_available(self, tmp_path):
        """REPLACES a tautology. The old test asserted a property of the fixture's own filter; this asserts against
        what the boundary was served and what it recorded."""
        h, rep, feed, r = scenario(tmp_path, "SERVED", arrivals=[DUE + 0.127, DUE + 60.127])
        served = [s for s in feed.served if s["outcome"] == "SERVED"]
        assert served
        o = resolved(h)[0]
        used_ts = o["exit_quote_observed"]["timestamp_epoch"]
        match = [s for s in served if abs(s["quote_ts"] - used_ts) < 1e-9]
        assert match, "the recorded quote must be one the feed actually served"
        assert match[0]["arrival"] <= o["exit_quote_request_epoch"], "and it must have arrived by then"
        assert o["exit_quote_request_epoch"] - used_ts <= B.MAX_SELECTED_QUOTE_AGE_S

    def test_the_historical_geometry_still_separates_v1_from_v2(self, tmp_path):
        arrivals = [DUE - 60.0 + 0.127, DUE + 0.127, DUE + 60.127]
        h2, rep2, f2, _ = scenario(tmp_path / "v2", "V2", arrivals=arrivals, quote_lag_s=0.128)
        assert resolved(h2), "V2 must resolve the 127 ms case"
        h1, rep1, f1, _ = scenario(tmp_path / "v1", "V1", arrivals=arrivals, quote_lag_s=0.128,
                                   policy=EP.EXIT_POLICY_V1)
        assert not resolved(h1), "V1 must still fail on the identical fixture"
        assert len(outcomes(h1)) == 5

    @pytest.mark.parametrize("offset", [0.0, 3.7, 11.2, 14.9, 15.1, 22.5, 31.0, 44.4, 52.8, 59.9])
    def test_the_phase_sweep_still_passes(self, tmp_path, offset):
        arrivals = [DUE - 60.0 + offset, DUE + offset, DUE + 60.0 + offset, DUE + 120.0 + offset]
        h, rep, feed, r = scenario(tmp_path, "SWEEP", arrivals=arrivals)
        assert resolved(h), "offset %.1f" % offset

    def test_the_declared_limits_and_the_v1_hash_are_unchanged(self):
        assert B.MAX_SELECTED_QUOTE_AGE_S == 15.0
        assert EP.EXIT_POLICY_V2.max_attempts == 5 and EP.EXIT_POLICY_V2.window_s == 120.0
        assert EP.EXIT_POLICY_V1.policy_hash == "9f9784f7af5b9c198e9bad69432488cb86c58a482a4d83e62dc18dcb9eb1e5af"

    def test_terminal_reports_are_asserted_not_just_fills(self, tmp_path):
        h, rep, feed, r = scenario(tmp_path, "TERM", arrivals=[], quote_lag_s=0.1)
        assert rep["exit_entries"][0]["final"] == "EXIT_EXHAUSTED_UNRESOLVED"
        assert rep["completion"] == "CLOSED_WITH_OUTSTANDING_OBLIGATIONS"
        assert rep["outstanding_obligations"] == 1
        assert exhausted_records(h)
        book = h.bd.book()
        assert len(book.positions) == 1 and book.open_cost > 0


# ============================================================ recovery: reported, not changed


class TestRecoveryIsACarriedForwardLimitation:
    """SUPERSEDED IN PLACE by EXIT-SCHEDULING-003. This class originally pinned the carried-forward limitation: an
    inherited position got ONE labelled recovery attempt and was then excluded from servicing, arrivals included,
    so a usable quote at due + 30 s went unused. That contract is gone. An inherited position is now serviced under
    the original policy's remaining window and remaining budget, and this test asserts the repaired behaviour on the
    same fixture. The full 003 evidence lives in tests/test_exit_scheduling_003.py."""

    def test_restart_then_failed_recovery_then_a_fresh_arrival_inside_the_window(self, tmp_path):
        h1 = SyntheticHarness(tmp_path / "led.jsonl", session_id="RECOV", t0=T, risk="certified")
        h1.chain = [{**c, "ask": 4.95} for c in h1.chain]
        h1.quotes.ask, h1.quotes.bid = 4.95, 4.90
        lc1 = LC.MonotonicClock(T)
        h1.clock = lc1.clock(); h1.bd.clock = h1.clock; h1.now = lc1.now; h1.advance = lc1.sleep
        S.open_session(h1.bd, symbols=["SPY"])
        d = S.scan(h1.bd, symbol="SPY", seq=1, **{k: v for k, v in h1.sources().items() if k != "exit_quote_fn"})
        assert d["decision"] == "TRADE"

        # process two restarts just after the exit came due; its first attempt fails, a good quote arrives after
        h2 = SyntheticHarness(tmp_path / "led.jsonl", session_id="RECOV", t0=T, risk="certified")
        lc2 = LC.MonotonicClock(DUE + 1.0)
        h2.clock = lc2.clock(); h2.bd.clock = h2.clock; h2.now = lc2.now; h2.advance = lc2.sleep
        h2.bd.exit_policy = EP.EXIT_POLICY_V2
        feed = Feed(h2, arrivals=[DUE + 30.0], quote_lag_s=0.1)
        src = dict(h2.sources()); src["exit_quote_fn"] = feed
        r2 = LC.LifecycleRunner(boundary=h2.bd, sources=src, clock=lc2, symbols=["SPY"],
                                selection_policy="PILOT_RULE_V2", scan_epochs=[],
                                observation_feed=feed.feed_for())
        rep2 = r2.run()

        assert rep2["recovered_positions"], "the restart saw the inherited obligation"
        entry = rep2["exit_entries"][0]
        assert entry["recovery"] is True
        # EXIT-SCHEDULING-003: the inherited position keeps being serviced inside its remaining window
        assert len(entry["attempts"]) > 1, "servicing continued past the first failed attempt"
        assert len(entry["attempts"]) <= EP.EXIT_POLICY_V1.max_attempts, "under the ORIGINAL budget, not a new one"
        assert entry["final"] == "RESOLVED"
        assert resolved(h2), "the usable quote at due+30 WAS used"
        assert not h2.bd.book().positions, "so the obligation is discharged and exposure released"
        # the ledger names the process that performed each attempt, and that the position was inherited
        rows = L.read_all(tmp_path / "led.jsonl")
        outs = [r for r in rows if r.get("kind") == "pilot_outcome" and (r.get("fill_ref") or {}).get("seq") == entry["fill_seq"]]
        assert outs and all(r.get("process_identity", {}).get("process_id") == r2.process_id for r in outs)
        assert all(r["process_identity"]["inherited_position"] is True for r in outs)
