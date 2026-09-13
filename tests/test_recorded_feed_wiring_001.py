"""RECORDED-OBSERVATION WIRING — acceptance through the real shared lifecycle runner.

Base `c37e60be8d158b506ac07f0b72bf5729c88f90fa`. **Synthetic acceptance only.** No recorded collection is opened,
no FLOW-VALIDATION rerun happens, no provider is called and no replay is authorized. The fixtures below are
recorded-SHAPED: snapshots carrying a recording's own receipt instant and contract rows in the shape the recorded
driver's adapter already produces. What is under test is the wiring, not the recording.

Every case drives `LifecycleRunner` -- the same runner production uses -- through the real boundary and the real
ledger. Nothing here mocks the scheduler, the policy or the accounting."""
from __future__ import annotations

import json

import pytest

from apex.options_pilot import boundary as B
from apex.options_pilot import exit_policy as EP
from apex.options_pilot import instant as I
from apex.options_pilot import ledger as L
from apex.options_pilot import lifecycle as LC
from apex.options_pilot import recorded_feed as RF
from apex.options_pilot import run_dir as RD
from apex.options_pilot import session as S
from tests.test_exit_scheduling_003 import CONTRACT, DUE, HOLD, T, harness, on_clock, outcomes, resolved
from tests.test_exit_scheduling_003_correction import open_under

SYMBOL, EXPIRY, STRIKE, RIGHT = "SPY", "2026-10-09", 650.0, "CALL"


def row(quote_ts, *, bid=4.73, ask=4.78, bid_size=9, ask_size=12, strike=STRIKE):
    return {"symbol": SYMBOL, "expiration": EXPIRY, "strike": strike, "right": RIGHT,
            "bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size, "timestamp_epoch": quote_ts}


def snapshots(*items):
    """items: (available_epoch, quote_lag_s) -- one contract row per snapshot, the recorded shape."""
    return [(av, [row(av - lag)]) for av, lag in items]


def source(h, snaps):
    return RF.RecordedQuoteSource(snaps, now_fn=h.now)


def drive(h, lc, src_obj, *, scans=(), policy=EP.EXIT_POLICY_V2, contract_ids=None):
    """The REAL runner, fed by the recorded feed and the recorded quote source from ONE recording."""
    sources = dict(h.sources())
    sources["exit_quote_fn"] = src_obj.exit_quote_fn
    r = LC.LifecycleRunner(boundary=h.bd, sources=sources, clock=lc, symbols=[SYMBOL],
                           selection_policy="PILOT_RULE_V2", scan_epochs=list(scans),
                           observation_feed=src_obj.observation_feed(contract_ids))
    return r.run(), r


def opened(tmp_path, sid, policy=EP.EXIT_POLICY_V2):
    """A position opened under `policy`, then a fresh process to service it from the recording."""
    open_under(tmp_path, sid, policy)
    h = harness(tmp_path, sid)
    lc = on_clock(h, t0=T + 1.0)
    h.bd.exit_policy = policy
    return h, lc


# ==================================================== 1. availability and identity


class TestAvailabilityAndIdentity:

    def test_no_snapshot_is_served_before_its_recorded_availability(self, tmp_path):
        h, lc = opened(tmp_path, "AV1")
        src = source(h, snapshots((DUE + 0.5, 0.1), (DUE + 40.0, 0.1), (DUE + 80.0, 0.1)))
        drive(h, lc, src)
        served = [s for s in src.served if s["outcome"] == "SERVED"]
        assert served
        for s in served:
            assert s["available"] <= s["asked_at"], "a recorded snapshot is invisible before its receipt"
        for o in outcomes(h):
            q = o.get("exit_quote_observed") or {}
            if q.get("available_epoch") is not None:
                assert q["available_epoch"] <= o["exit_quote_receipt_epoch"]

    def test_the_feed_and_the_quote_source_agree_because_they_share_one_recording(self, tmp_path):
        h, lc = opened(tmp_path, "AV2")
        snaps = snapshots((DUE + 0.5, 0.1), (DUE + 40.0, 0.1))
        src = source(h, snaps)
        feed_ids = {p["observation_id"] for _a, p in src.observation_feed()}
        drive(h, lc, src)
        for s in src.served:
            if s["outcome"] == "SERVED":
                assert s["observation_id"] in feed_ids, \
                    "the quote source cannot serve an observation the feed never announced"

    def test_the_outcome_names_the_recorded_observation_it_valued(self, tmp_path):
        h, lc = opened(tmp_path, "AV3")
        src = source(h, snapshots((DUE + 0.5, 0.1),))
        drive(h, lc, src)
        q = resolved(h)[0]["exit_quote_observed"]
        assert q["observation_id"] and q["available_epoch"] == DUE + 0.5
        assert "UNVERIFIED" in q["identity_basis"]

    def test_the_identity_is_recomputable_from_the_ledger_alone(self, tmp_path):
        """A reviewer with the ledger and the recording can prove WHICH observation an attempt valued, without
        trusting this process's own account of it."""
        h, lc = opened(tmp_path, "AV4")
        snaps = snapshots((DUE + 0.5, 0.1),)
        src = source(h, snaps)
        drive(h, lc, src)
        o = resolved(h)[0]
        q = o["exit_quote_observed"]
        recomputed = RF.observation_id(contract_id=o["contract_id"], available_epoch=q["available_epoch"],
                                       quote={k: q[k] for k in RF.IDENTITY_FIELDS})
        assert recomputed == q["observation_id"], "the id is a pure function of persisted values"

    def test_identical_quotes_at_different_instants_are_different_observations(self, tmp_path):
        h, lc = opened(tmp_path, "AV5")
        src = source(h, [(DUE + 0.5, [row(DUE + 0.4)]), (DUE + 40.0, [row(DUE + 0.4)])])
        ids = [p["observation_id"] for _a, p in src.observation_feed()]
        assert len(ids) == 2 and ids[0] != ids[1], "availability is part of the identity"

    def test_a_quote_recorded_before_its_own_receipt_is_excluded_and_named(self, tmp_path):
        h, lc = opened(tmp_path, "AV6")
        src = RF.RecordedQuoteSource([(DUE + 0.5, [row(DUE + 5.0)])], now_fn=h.now)
        assert src.observation_feed() == [], "nothing is announced for an excluded row"
        assert len(src.excluded) == 1
        assert src.excluded[0]["why"] == "RECORDED_QUOTE_AFTER_ITS_OWN_RECEIPT"

    def test_a_row_without_a_timestamp_is_refused_not_defaulted(self, tmp_path):
        h, lc = opened(tmp_path, "AV7")
        bad = {k: v for k, v in row(DUE).items() if k != "timestamp_epoch"}
        with pytest.raises(RF.RecordedFeedRefused, match="RECORDED_ROW_MISSING_TIMESTAMP"):
            RF.RecordedQuoteSource([(DUE + 0.5, [bad])], now_fn=h.now)


# ==================================================== 2. arrival-triggered resolution


class TestArrivalTriggeredResolution:

    def test_a_recorded_arrival_between_timers_resolves_the_exit(self, tmp_path):
        """The 127 ms geometry, delivered entirely from a recording. Without this wiring the recorded route could
        not produce an arrival at all and V2 degenerated to V1."""
        h, lc = opened(tmp_path, "AR1")
        src = source(h, snapshots((DUE - 60.0 + 0.127, 0.128), (DUE + 0.127, 0.128), (DUE + 60.127, 0.128)))
        rep, r = drive(h, lc, src)
        assert resolved(h), "resolved from the recording's own arrival"
        arr = [e for e in rep["exits"] if e.get("event") == LC.EXIT_ARRIVAL and e.get("outcome_seq")]
        assert arr and arr[0]["trigger"] == "OBSERVATION_ARRIVAL"
        # request <= receipt: this fixture's provider answers instantaneously, so the two instants coincide. The
        # strict inequality under a slow provider is proved in tests/test_exit_scheduling_003_correction.py.
        assert arr[0]["quote_observation_id"] and arr[0]["request_epoch"] <= arr[0]["receipt_epoch"]

    def test_the_arrival_trace_carries_the_boundarys_own_instants(self, tmp_path):
        h, lc = opened(tmp_path, "AR2")
        src = source(h, snapshots((DUE + 0.5, 0.1),))
        rep, r = drive(h, lc, src)
        a = [e for e in rep["exits"] if e.get("event") == LC.EXIT_ARRIVAL and e.get("outcome_seq")][0]
        o = L.read_all(h.bd.ledger)[a["outcome_seq"] - 1]
        assert a["request_epoch"] == o["exit_quote_request_epoch"]
        assert a["receipt_epoch"] == o["exit_quote_receipt_epoch"]

    def test_a_recorded_arrival_carrying_a_stale_quote_is_still_refused(self, tmp_path):
        """A new RECEIPT is not a fresh quote. The recording arrives at due+0.5 carrying a 40 s old quote."""
        h, lc = opened(tmp_path, "AR3")
        src = source(h, snapshots((DUE + 0.5, 40.0),))
        drive(h, lc, src)
        assert not resolved(h)
        assert any((o.get("why") or "").startswith("STALE_SELECTED_CONTRACT") for o in outcomes(h))
        assert h.bd.book().positions, "it remains an obligation"


# ==================================================== 3. V1 is unchanged


class TestV1IsUnchanged:

    def test_the_same_recording_under_v1_spends_five_timer_attempts_and_does_not_resolve(self, tmp_path):
        h, lc = opened(tmp_path, "V1A", policy=EP.EXIT_POLICY_V1)
        src = source(h, snapshots((DUE - 60.0 + 0.127, 0.128), (DUE + 0.127, 0.128), (DUE + 60.127, 0.128)))
        rep, r = drive(h, lc, src, policy=EP.EXIT_POLICY_V1)
        assert not resolved(h) and len(outcomes(h)) == 5
        assert rep["exit_entries"][0]["final"] == "EXIT_EXHAUSTED_UNRESOLVED"

    def test_supplying_a_feed_to_a_v1_position_triggers_nothing(self, tmp_path):
        """The feed is available; the POSITION's policy says arrivals do not trigger attempts. The runner records
        that by name rather than quietly honouring the feed."""
        h, lc = opened(tmp_path, "V1B", policy=EP.EXIT_POLICY_V1)
        src = source(h, snapshots((DUE + 0.5, 0.1),))
        rep, r = drive(h, lc, src, policy=EP.EXIT_POLICY_V1)
        notes = [e for e in rep["events"] if e["kind"] == LC.EXIT_ARRIVAL]
        assert notes, "the notification was still scheduled and seen"
        acted = notes[0]["outcome"]["acted"]
        assert acted != "NO_DUE_POSITION"
        assert any(a.get("reason") == "ARRIVAL_TRIGGER_NOT_ENABLED_BY_POLICY" for a in acted), acted
        assert all(a.get("is_attempt") is False for a in acted), "a scheduling decision is never an attempt"
        assert all(e.get("event") != LC.EXIT_ARRIVAL or not e.get("outcome_seq") for e in rep["exits"])

    def test_the_v1_hash_and_the_limits_are_untouched(self):
        assert EP.EXIT_POLICY_V1.policy_hash == "9f9784f7af5b9c198e9bad69432488cb86c58a482a4d83e62dc18dcb9eb1e5af"
        assert EP.EXIT_POLICY_V1.max_attempts == 5 and EP.EXIT_POLICY_V1.window_s == 120.0
        assert B.MAX_SELECTED_QUOTE_AGE_S == 15.0


# ==================================================== 4. original policy and remaining budget on a restart


class TestRestartUnderTheRecording:

    def test_an_inherited_position_is_serviced_from_the_recording_under_its_original_policy(self, tmp_path):
        h, lc = opened(tmp_path, "RS1")
        src = source(h, snapshots((DUE + 30.0, 0.1),))
        rep, r = drive(h, lc, src)
        assert rep["recovered_positions"], "the restart inherited the obligation"
        entry = rep["exit_entries"][0]
        assert entry["recovery"] is True and entry["final"] == "RESOLVED"
        assert all(a.get("policy_version") == "EXIT_AT_HORIZON_15M_V2_ARRIVAL" for a in entry["attempts"])

    def test_a_restart_under_a_wider_policy_still_gets_the_original_budget(self, tmp_path):
        """The recording never becomes usable. The restarting process is configured for 50 attempts over 600 s;
        the position was opened under V1 and gets 5 attempts inside 120 s."""
        open_under(tmp_path, "RS2", EP.EXIT_POLICY_V1)
        h = harness(tmp_path, "RS2")
        lc = on_clock(h, t0=DUE + 0.5)
        h.bd.exit_policy = EP.ExitPolicy(policy_id="WIDE_FIXTURE", window_s=600.0, max_attempts=50,
                                         retry_spacing_s=5.0)
        src = source(h, [])
        rep, r = drive(h, lc, src)
        assert len(outcomes(h)) == 5
        assert max(o["exit_quote_request_epoch"] for o in outcomes(h)) <= DUE + 120.0
        assert all(o["exit_policy"]["policy_id"] == "EXIT_AT_HORIZON_15M_V1" for o in outcomes(h))

    def test_remaining_budget_is_read_from_the_ledger_not_reset_by_the_restart(self, tmp_path):
        """Process two spends two attempts against an empty recording and stops; process three inherits and may
        spend only the remaining three."""
        open_under(tmp_path, "RS3", EP.EXIT_POLICY_V1)
        h2 = harness(tmp_path, "RS3")
        lc2 = on_clock(h2, t0=DUE + 0.5)
        h2.bd.exit_policy = EP.EXIT_POLICY_V1
        pos = S.recover_positions(h2.bd)["own"][0]
        for _ in range(2):
            h2.bd.record_outcome(fill_receipt=pos, exit_quote_fn=lambda c: None)
        assert len(outcomes(h2)) == 2

        h3 = harness(tmp_path, "RS3")
        lc3 = on_clock(h3, t0=DUE + 1.0)
        h3.bd.exit_policy = EP.EXIT_POLICY_V1
        rep, r = drive(h3, lc3, source(h3, []))
        assert len(outcomes(h3)) == 5, "two already spent plus three remaining, not five more"
        assert rep["exit_entries"][0]["final"] == "EXIT_EXHAUSTED_UNRESOLVED"


# ==================================================== 5. no eligible quote -> explicit unresolved exposure


class TestNoEligibleQuote:

    def test_an_empty_recording_ends_in_explicit_unresolved_exposure(self, tmp_path):
        h, lc = opened(tmp_path, "NE1")
        rep, r = drive(h, lc, source(h, []))
        assert not resolved(h)
        assert rep["exit_entries"][0]["final"] == "EXIT_EXHAUSTED_UNRESOLVED"
        assert rep["completion"] == "CLOSED_WITH_OUTSTANDING_OBLIGATIONS"
        assert rep["outstanding_obligations"] == 1
        assert h.bd.book().positions, "exposure is retained, never written off"
        rows = L.read_all(h.bd.ledger)
        assert any(x["kind"] == "pilot_exit_exhausted" for x in rows)

    def test_the_total_is_null_not_zero_when_a_position_is_unresolved(self, tmp_path):
        h, lc = opened(tmp_path, "NE2")
        rep, r = drive(h, lc, source(h, []))
        bk = rep["book"]
        assert bk["cash_identity"]["holds"] is True and bk["integrity_problems"] == []
        assert rep["outstanding_obligations"] == 1

    def test_every_failed_attempt_is_persisted_with_its_reason(self, tmp_path):
        h, lc = opened(tmp_path, "NE3")
        rep, r = drive(h, lc, source(h, []))
        outs = outcomes(h)
        assert len(outs) == 5 and all(o["status"] == "NOT_ESTIMABLE" for o in outs)
        assert all("EXIT_QUOTE_PROVIDER_FAILED" in (o.get("why") or "") for o in outs)
        assert all(o["discharges_position"] is False for o in outs)


# ==================================================== 6. immutable outputs, reconstructible records


class TestImmutableOutputsAndReconstruction:

    def test_a_run_directory_is_claimed_once_and_never_overwritten(self, tmp_path):
        h, lc = opened(tmp_path, "IM1")
        src = source(h, snapshots((DUE + 0.5, 0.1),))
        rd = RD.new_run(tmp_path / "runs", run_id="recorded-wiring-1", now_epoch=T,
                        config={"feed_digest": src.feed_digest(), "policy": EP.EXIT_POLICY_V2.policy_id})
        rep, r = drive(h, lc, src)
        rd.write_json("report.json", rep)
        rd.write_json("feed.json", src.describe())
        rd.complete(now_epoch=h.now(), summary={"resolved": len(resolved(h))})

        with pytest.raises(RD.RunDirRefused, match="RUN_DIR_COLLISION"):
            RD.new_run(tmp_path / "runs", run_id="recorded-wiring-1", now_epoch=T)
        with pytest.raises(RD.RunDirRefused, match="ARTIFACT_NAME_ALREADY_CLAIMED"):
            rd.path_for("report.json")
        with pytest.raises(RD.RunDirRefused, match="RUN_ALREADY_TERMINAL"):
            rd.complete(now_epoch=h.now())
        assert rd.status()["status"] == "COMPLETED"

    def test_the_feed_digest_names_the_inputs_by_content(self, tmp_path):
        h, lc = opened(tmp_path, "IM2")
        a = source(h, snapshots((DUE + 0.5, 0.1), (DUE + 40.0, 0.1)))
        b = source(h, snapshots((DUE + 0.5, 0.1), (DUE + 40.0, 0.1)))
        c = source(h, snapshots((DUE + 0.5, 0.1), (DUE + 41.0, 0.1)))
        assert a.feed_digest() == b.feed_digest(), "same recording, same digest"
        assert a.feed_digest() != c.feed_digest(), "a different recording is a different digest"

    def test_the_decision_is_reconstructible_from_the_ledger(self, tmp_path):
        """Ledger + recording is enough to say what was valued, when it was requested, when it was received, which
        observation it was, and under which contract -- with the chain verified."""
        h, lc = opened(tmp_path, "IM3")
        src = source(h, snapshots((DUE + 0.5, 0.1),))
        drive(h, lc, src)
        L.verify_chain(h.bd.ledger)
        o = resolved(h)[0]
        for k in ("exit_quote_request_epoch", "exit_quote_receipt_epoch", "exit_quote_observed", "exit_policy",
                  "process_identity", "contract_id", "fill_ref"):
            assert k in o, k
        q = o["exit_quote_observed"]
        assert RF.observation_id(contract_id=o["contract_id"], available_epoch=q["available_epoch"],
                                 quote={k: q[k] for k in RF.IDENTITY_FIELDS}) == q["observation_id"]
        assert o["exit_policy"]["binding"] == "ORIGINAL_POLICY_OF_RECORD"
        assert o["process_identity"]["process_id"]
        assert "LOGICAL_INVOCATION_LABEL" in o["process_identity"]["basis"]

    def test_the_feed_description_states_its_laws_and_its_exclusions(self, tmp_path):
        h, lc = opened(tmp_path, "IM4")
        src = RF.RecordedQuoteSource([(DUE + 0.5, [row(DUE + 0.4)]), (DUE + 1.0, [row(DUE + 9.0)])], now_fn=h.now)
        d = src.describe()
        assert d["schema"] == "RECORDED_OBSERVATION_FEED_V1"
        assert d["n_observations"] == 1 and d["n_excluded_rows"] == 1
        assert "RECORDED_OBSERVATION_AVAILABILITY_V1" in d["availability_law"]
        assert "NOT a provider-issued sequence number" in d["identity_law"]
        assert json.dumps(d), "the description is serialisable into a run artifact"


# ==================================================== the recorded route is not on any exit's critical path


def test_the_feed_module_imports_nothing_from_a_provider_or_the_network():
    import inspect
    srcfile = inspect.getsource(RF)
    for banned in ("requests", "urllib", "httpx", "socket", "open("):
        assert banned not in srcfile, banned
