"""EXIT-SCHEDULING-003 bounded correction — three review findings, reproducers first.

Base `b5b91f285a64be30bdbf17d03736fce9f20695e1`. Synthetic only. The recorded driver is neither wired nor run.

1. ORIGINAL-POLICY BINDING. `_service_exit` and `record_outcome` took `pol = bd.exit_policy`: the fill instant and
   the prior attempt count came from the ledger, but the horizon, window, maximum attempts and retry behaviour came
   from the RESTARTING process. Restarting under a wider policy therefore extended the original contract. The
   position's policy must be resolved from the persisted fill/intent and hash-verified before anything is scheduled
   or any quote is requested; a policy that cannot be resolved is an explicit unresolved obligation, named.
2. REQUEST-TIME ACCURACY. The arrival trace recorded `request_epoch=self.clock.now()` AFTER `_service_exit`
   returned -- after the provider call and after persistence. The boundary already persists the true
   `exit_quote_request_epoch` and `exit_quote_receipt_epoch`; the trace must carry those.
3. AVAILABILITY ENFORCEMENT. `validate_quote` refused availability BEFORE the quote's own timestamp, and nothing
   refused availability AFTER receipt, so a fresh provider timestamp with an availability instant in the future
   could discharge a position. A live request may legitimately be served a quote that became available DURING the
   request, so the law is availability <= receipt, never availability <= request. Recorded as-of lookup is a
   separate gate with its own semantics.
"""
from __future__ import annotations

import pytest

from apex.options_pilot import boundary as B
from apex.options_pilot import exit_policy as EP
from apex.options_pilot import instant as I
from apex.options_pilot import ledger as L
from apex.options_pilot import lifecycle as LC
from apex.options_pilot import replay as RP
from apex.options_pilot import session as S
from tests.test_exit_scheduling_003 import (CONTRACT, DUE, Feed, HOLD, T, harness, on_clock, outcomes, resolved,
                                            run, snaps)

# A policy this build has never frozen: wider window, far more attempts, faster retries. Restarting under it must
# not enlarge a contract opened under something else.
WIDE = EP.ExitPolicy(policy_id="EXIT_WIDE_FIXTURE", window_s=600.0, max_attempts=50, retry_spacing_s=5.0)


def fills(h):
    return [r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_fill" and r.get("status") == "FILLED"]


def open_under(tmp_path, sid, policy):
    """Process one opens a position under `policy` and stops."""
    h1 = harness(tmp_path, sid)
    on_clock(h1)
    h1.bd.exit_policy = policy
    S.open_session(h1.bd, symbols=["SPY"])
    d = S.scan(h1.bd, symbol="SPY", seq=1, **{k: v for k, v in h1.sources().items() if k != "exit_quote_fn"})
    assert d["decision"] == "TRADE", d.get("why")
    f = fills(h1)[0]
    assert f["committed_epoch"] + HOLD == DUE
    return f


def restart_under(tmp_path, sid, policy, *, start, snapshots=(), fail_until=None):
    h2 = harness(tmp_path, sid)
    lc2 = on_clock(h2, t0=start)
    h2.bd.exit_policy = policy
    feed = Feed(h2, snapshots=list(snapshots), fail_until=fail_until)
    rep, r = run(h2, lc2, feed)
    return h2, rep, feed, r


# ==================================================== 1. the original policy binds


class TestOriginalPolicyBinding:

    def test_a_restart_under_a_wider_policy_cannot_extend_window_or_budget(self, tmp_path):
        """REPRODUCER. Opened under V1 (5 attempts / 120 s), restarted under a 50-attempt / 600 s policy. At
        b5b91f2 the restarting process's numbers governed and the position was attempted far past its contract."""
        open_under(tmp_path, "OB", EP.EXIT_POLICY_V1)
        h2, rep, feed, r = restart_under(tmp_path, "OB", WIDE, start=DUE + 0.5)
        outs = outcomes(h2)
        assert len(outs) == EP.EXIT_POLICY_V1.max_attempts == 5, "the ORIGINAL budget, not the restart's 50"
        last = max(o["exit_quote_request_epoch"] for o in outs)
        assert last <= DUE + EP.EXIT_POLICY_V1.window_s, "no attempt outside the ORIGINAL 120 s window"
        entry = rep["exit_entries"][0]
        assert entry["final"] == "EXIT_EXHAUSTED_UNRESOLVED"
        assert all(a.get("policy_version") == "EXIT_AT_HORIZON_15M_V1" for a in entry["attempts"])

    def test_the_original_policy_governs_arrival_triggering_not_the_restarting_process(self, tmp_path):
        """The 127 ms geometry: only an arrival-triggered attempt can resolve it. Opened under V2, restarted under
        V1. The ORIGINAL policy allows arrival triggering, so it resolves even though the restarting process is
        configured for timers only."""
        open_under(tmp_path, "OA", EP.EXIT_POLICY_V2)
        h2, rep, feed, r = restart_under(tmp_path, "OA", EP.EXIT_POLICY_V1, start=T + 1.0,
                                         snapshots=snaps(("p", DUE - 60.0 + 0.127, 0.128),
                                                         ("q", DUE + 0.127, 0.128),
                                                         ("r", DUE + 60.127, 0.128)))
        assert resolved(h2), "the position's own policy permits the arrival-triggered attempt"
        assert rep["exit_entries"][0]["final"] == "RESOLVED"

    def test_the_reverse_holds_a_v1_position_is_not_upgraded_by_a_v2_process(self, tmp_path):
        """Same geometry, opened under V1 and restarted under V2. The original policy has no arrival trigger, so
        the five timer attempts all fail on staleness exactly as V1 always did."""
        open_under(tmp_path, "OR", EP.EXIT_POLICY_V1)
        h2, rep, feed, r = restart_under(tmp_path, "OR", EP.EXIT_POLICY_V2, start=T + 1.0,
                                         snapshots=snaps(("p", DUE - 60.0 + 0.127, 0.128),
                                                         ("q", DUE + 0.127, 0.128),
                                                         ("r", DUE + 60.127, 0.128)))
        assert not resolved(h2) and len(outcomes(h2)) == 5
        assert rep["exit_entries"][0]["final"] == "EXIT_EXHAUSTED_UNRESOLVED"

    def test_an_unresolvable_original_policy_refuses_by_name_before_any_quote_is_requested(self, tmp_path):
        """Opened under a policy this build does not carry, restarted under V1. The original contract cannot be
        reconstructed, so it is not guessed: nothing is scheduled, nothing is asked, and the position stays an
        explicit obligation naming what is missing."""
        open_under(tmp_path, "OU", WIDE)
        h2, rep, feed, r = restart_under(tmp_path, "OU", EP.EXIT_POLICY_V1, start=DUE + 0.5,
                                         snapshots=snaps(("good", DUE + 1.0, 0.1)))
        assert outcomes(h2) == [], "no valuation attempt was made"
        assert [s for s in feed.served if s["outcome"] == "SERVED"] == [], "the provider was never asked"
        entry = rep["exit_entries"][0]
        assert entry["final"] == "UNSERVICEABLE_EXIT_POLICY_UNRESOLVED"
        assert "EXIT_POLICY_UNKNOWN_HASH" in entry["policy_problem"]
        assert h2.bd.book().positions, "it remains an obligation with retained exposure"
        assert rep["outstanding_obligations"] >= 1
        assert not any(x["kind"] == "pilot_exit_exhausted" for x in L.read_all(h2.bd.ledger)), \
            "unserviceable is NOT exhausted: the budget was never spent"

    def test_every_attempt_records_the_resolved_original_policy_and_how_it_was_resolved(self, tmp_path):
        open_under(tmp_path, "OP", EP.EXIT_POLICY_V1)
        h2, rep, feed, r = restart_under(tmp_path, "OP", WIDE, start=DUE + 0.5)
        for o in outcomes(h2):
            ep = o["exit_policy"]
            assert ep["policy_id"] == "EXIT_AT_HORIZON_15M_V1"
            assert ep["policy_hash"] == EP.EXIT_POLICY_V1.policy_hash
            assert ep["binding"] == "ORIGINAL_POLICY_OF_RECORD"
            assert ep["resolved_from"] in ("FROZEN_POLICY_REGISTRY", "PROCESS_CONFIGURED_POLICY")
            assert ep["process_policy_id"] == "EXIT_WIDE_FIXTURE", "the record says the process differed"
            assert ep["process_policy_matches_original"] is False

    # ---- the resolver itself, on record shapes an end-to-end fixture cannot legitimately produce

    def _fill(self, **over):
        fl = {"kind": "pilot_fill", "status": "FILLED", "committed_epoch": T, "intent_id": "i-1",
              "exit_schedule": EP.EXIT_POLICY_V1.schedule(T)}
        fl.update(over)
        return fl

    def test_the_resolver_accepts_a_hash_it_can_verify(self):
        pol, problem = EP.resolve_for_fill(self._fill(), process_policy=EP.EXIT_POLICY_V2)
        assert problem is None and pol is EP.EXIT_POLICY_V1

    def test_the_resolver_names_missing_policy_evidence(self):
        pol, problem = EP.resolve_for_fill(self._fill(exit_schedule={}), process_policy=EP.EXIT_POLICY_V1)
        assert pol is None and problem.startswith("EXIT_POLICY_EVIDENCE_MISSING")
        assert "exit_schedule.policy_hash" in problem and "pins.exit_policy_hash" in problem

    def test_the_resolver_falls_back_to_the_intent_pin_when_the_fill_predates_the_schedule(self):
        intent = {"pins": {"exit_policy_id": "EXIT_AT_HORIZON_15M_V1",
                           "exit_policy_hash": EP.EXIT_POLICY_V1.policy_hash}}
        pol, problem = EP.resolve_for_fill(self._fill(exit_schedule={}), intent_row=intent,
                                           process_policy=EP.EXIT_POLICY_V2)
        assert problem is None and pol is EP.EXIT_POLICY_V1

    def test_the_resolver_refuses_when_the_fill_and_the_intent_disagree(self):
        intent = {"pins": {"exit_policy_id": "EXIT_AT_HORIZON_15M_V2_ARRIVAL",
                           "exit_policy_hash": EP.EXIT_POLICY_V2.policy_hash}}
        pol, problem = EP.resolve_for_fill(self._fill(), intent_row=intent, process_policy=EP.EXIT_POLICY_V1)
        assert pol is None and problem.startswith("EXIT_POLICY_EVIDENCE_CONFLICT")

    def test_the_resolver_refuses_an_id_hash_disagreement(self):
        sch = dict(EP.EXIT_POLICY_V1.schedule(T)); sch["policy_id"] = "EXIT_AT_HORIZON_15M_V2_ARRIVAL"
        pol, problem = EP.resolve_for_fill(self._fill(exit_schedule=sch), process_policy=EP.EXIT_POLICY_V1)
        assert pol is None and problem.startswith("EXIT_POLICY_ID_HASH_DISAGREE")

    def test_the_resolver_refuses_a_schedule_the_resolved_policy_does_not_reproduce(self):
        """A persisted deadline that the resolved policy does not recompute is tampering or corruption, not a
        rounding difference, and it is refused rather than silently preferred either way."""
        sch = dict(EP.EXIT_POLICY_V1.schedule(T)); sch["window_close_epoch"] += 480.0
        pol, problem = EP.resolve_for_fill(self._fill(exit_schedule=sch), process_policy=EP.EXIT_POLICY_V1)
        assert pol is None and problem.startswith("EXIT_POLICY_SCHEDULE_INCOHERENT")

    def test_a_policy_the_process_still_carries_resolves_even_if_unregistered(self):
        """The restarting process's OWN policy is a valid evidence source when its hash matches the persisted one:
        that is a verification, not a substitution."""
        fl = self._fill(exit_schedule=WIDE.schedule(T))
        pol, problem = EP.resolve_for_fill(fl, process_policy=WIDE)
        assert problem is None and pol is WIDE
        pol2, problem2 = EP.resolve_for_fill(fl, process_policy=EP.EXIT_POLICY_V1)
        assert pol2 is None and problem2.startswith("EXIT_POLICY_UNKNOWN_HASH")


# ==================================================== 2. request-time accuracy


class SlowFeed(Feed):
    """A provider that takes real time to answer. The clock at return is NOT the clock at request, which is the
    whole point: a trace that reads the clock afterwards records a time the request never happened at."""

    def __init__(self, *a, latency_s=0.25, available_offset=None, **kw):
        super().__init__(*a, **kw)
        self.latency_s, self.available_offset = latency_s, available_offset
        self.requested_at: list = []

    def __call__(self, contract):
        req = self.h.now()
        self.requested_at.append(req)
        self.h.advance(self.latency_s)
        s = self.visible()
        if s is None:
            from apex.pulse_options.providers import ProviderUnavailable
            self.served.append({"asked_at": req, "observation_id": None, "outcome": "NO_SNAPSHOT"})
            raise ProviderUnavailable("NO_SNAPSHOT_YET")
        self.served.append({"asked_at": req, "observation_id": s["observation_id"], "quote_ts": s["quote_ts"],
                            "arrival": s["arrival"], "outcome": "SERVED"})
        avail = s["arrival"] if self.available_offset is None else req + self.available_offset
        return {"symbol": contract["symbol"], "expiration": contract["expiration"], "strike": contract["strike"],
                "right": contract["right"], "bid": self.bid, "ask": self.ask, "bid_size": 9, "ask_size": 12,
                "timestamp_epoch": s["quote_ts"], "observation_id": s["observation_id"], "available_epoch": avail}


def slow_run(tmp_path, sid, **feed_kw):
    h = harness(tmp_path, sid)
    lc = on_clock(h)
    h.bd.exit_policy = EP.EXIT_POLICY_V2
    # the snapshot arrives AFTER the due timer's own receipt, so the timer genuinely fails and the resolving
    # attempt is the arrival-triggered one -- which is the path whose request instant is under test
    feed = SlowFeed(h, snapshots=snaps(("s", DUE + 5.0, 0.1)), **feed_kw)
    rep, r = run(h, lc, feed, scans=[T])
    return h, rep, feed


class TestRequestTimeAccuracy:

    def test_the_arrival_trace_carries_the_boundarys_persisted_request_and_receipt(self, tmp_path):
        """REPRODUCER. At b5b91f2 the trace read the clock after `_service_exit` returned, so with a provider that
        takes 250 ms the recorded 'request' instant was later than the receipt it was meant to precede."""
        h, rep, feed = slow_run(tmp_path, "RT")
        arr = [e for e in rep["exits"] if e.get("event") == LC.EXIT_ARRIVAL and e.get("outcome_seq")]
        assert arr, "an arrival-triggered attempt happened"
        a = arr[0]
        row = L.read_all(h.bd.ledger)[a["outcome_seq"] - 1]
        assert a["request_epoch"] == row["exit_quote_request_epoch"]
        assert a["receipt_epoch"] == row["exit_quote_receipt_epoch"]
        assert a["request_epoch"] == pytest.approx(feed.requested_at[-1])
        assert a["request_epoch"] < a["receipt_epoch"], "a request precedes its own receipt"
        assert a["receipt_epoch"] - a["request_epoch"] == pytest.approx(feed.latency_s, abs=1e-6)

    def test_the_recorded_request_is_not_the_clock_after_the_attempt_returned(self, tmp_path):
        h, rep, feed = slow_run(tmp_path, "RN", latency_s=2.0)
        a = [e for e in rep["exits"] if e.get("event") == LC.EXIT_ARRIVAL and e.get("outcome_seq")][0]
        assert a["request_epoch"] <= a["receipt_epoch"] - 1.9
        assert a["request_epoch"] < h.now() - 1.9, "the clock has moved well past the request since"

    def test_the_remaining_window_is_measured_at_the_request_it_describes(self, tmp_path):
        h, rep, feed = slow_run(tmp_path, "RW", latency_s=2.0)
        a = [e for e in rep["exits"] if e.get("event") == LC.EXIT_ARRIVAL and e.get("outcome_seq")][0]
        assert a["remaining_window_s"] == pytest.approx(round(DUE + 120.0 - a["request_epoch"], 3))


# ==================================================== 3. availability enforcement


class TestAvailabilityEnforcement:

    def test_availability_after_receipt_does_not_discharge_the_position(self, tmp_path):
        """REPRODUCER. A fresh provider timestamp with an availability instant AFTER the receipt is a claim the
        system could not have acted on. At b5b91f2 it discharged the position."""
        h, rep, feed = slow_run(tmp_path, "AV", latency_s=0.25, available_offset=5.0)
        assert not resolved(h), "a quote that became available after it was received cannot resolve anything"
        whys = {o.get("why") for o in outcomes(h)}
        assert any(w and w.startswith("EXIT_QUOTE_AVAILABLE_AFTER_RECEIPT") for w in whys), whys
        assert h.bd.book().positions, "the position remains an obligation"

    def test_availability_between_request_and_receipt_is_permitted_for_a_live_response(self, tmp_path):
        """The opposite error would be as bad: a live request can legitimately be served a quote that became
        available WHILE the request was in flight. That must resolve."""
        h, rep, feed = slow_run(tmp_path, "AB", latency_s=0.25, available_offset=0.1)
        assert resolved(h), "availability inside the request is not a violation"
        q = resolved(h)[0]["exit_quote_observed"]
        row = resolved(h)[0]
        assert row["exit_quote_request_epoch"] < q["available_epoch"] < row["exit_quote_receipt_epoch"]

    def test_availability_exactly_at_receipt_is_permitted(self, tmp_path):
        h, rep, feed = slow_run(tmp_path, "AE", latency_s=0.25, available_offset=0.25)
        assert resolved(h)

    def test_missing_availability_stays_unknown_and_is_never_manufactured(self, tmp_path):
        h = harness(tmp_path, "AN")
        lc = on_clock(h)
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        feed = Feed(h, snapshots=snaps(("legacy", DUE + 0.2, 0.1)))
        base = Feed.__call__
        feed.__class__ = type("LegacyFeed", (Feed,), {
            "__call__": lambda self, c: {k: v for k, v in base(self, c).items() if k != "available_epoch"}})
        run(h, lc, feed, scans=[T])
        assert resolved(h), "an adapter that declares no availability is not thereby refused"
        q = resolved(h)[0]["exit_quote_observed"]
        assert q["available_epoch"] is None and "NOT_SUPPLIED" not in (q["identity_basis"] or "")[:0]
        assert q["observation_id"] == "legacy"
        assert "UNVERIFIED" in q["identity_basis"]

    def test_the_quote_contract_still_refuses_availability_before_the_quotes_own_timestamp(self):
        from apex.options_pilot.records import RecordRefused, validate_quote
        c = {"symbol": "SPY", "expiration": "2026-10-09", "strike": 650.0, "right": "CALL"}
        raw = {**c, "bid": 4.7, "ask": 4.8, "bid_size": 9, "ask_size": 12, "timestamp_epoch": T,
               "observation_id": "x", "available_epoch": T - 5.0}
        with pytest.raises(RecordRefused, match="QUOTE_AVAILABLE_BEFORE_ITS_OWN_TIMESTAMP"):
            validate_quote(raw, contract=c)

    def test_the_quote_contract_does_not_impose_a_request_instant_it_cannot_see(self):
        """`validate_quote` has no request instant, so it must NOT invent an availability-before-request rule.
        Receipt-side enforcement is the boundary's, and the boundary is the only place that knows both."""
        from apex.options_pilot.records import validate_quote
        c = {"symbol": "SPY", "expiration": "2026-10-09", "strike": 650.0, "right": "CALL"}
        raw = {**c, "bid": 4.7, "ask": 4.8, "bid_size": 9, "ask_size": 12, "timestamp_epoch": T,
               "observation_id": "x", "available_epoch": T + 3600.0}
        q = validate_quote(raw, contract=c)
        assert q["available_epoch"] == T + 3600.0, "carried, for the boundary to judge against receipt"

    def test_recorded_as_of_lookup_is_a_separate_gate_with_its_own_semantics(self):
        """Recorded replay does not use the live receipt law. It enforces the DECLARED lookup instant, and it
        refuses a datum with no recorded availability instead of assuming one."""
        pairs = [(T, "early"), (T + 10.0, "late")]
        assert RP.most_recent_available(pairs, T + 5.0) == (T, "early")
        assert RP.most_recent_available(pairs, T + 10.0) == (T + 10.0, "late")
        assert RP.most_recent_available(pairs, T - 1.0) is None
        with pytest.raises(RP.ReplayRefused, match="AVAILABILITY_UNKNOWN"):
            RP.most_recent_available([(None, "x")], T)


# ==================================================== process identity is a label


class TestProcessIdentityIsALabel:

    def test_the_record_states_what_the_process_id_is_and_is_not(self, tmp_path):
        h = harness(tmp_path, "PI")
        lc = on_clock(h)
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        feed = Feed(h, snapshots=snaps(("s", DUE + 0.2, 0.1)))
        run(h, lc, feed, scans=[T])
        pi = outcomes(h)[0]["process_identity"]
        assert pi["process_id"] and pi["started_utc"]
        assert "LOGICAL_INVOCATION_LABEL" in pi["basis"]
        assert "NOT" in pi["basis"] and "operating-system" in pi["basis"]
        assert "does not prevent" in pi["basis"] or "no exclusivity" in pi["basis"]
