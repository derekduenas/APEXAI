"""OPERATING-LOOP-001 — the twelve synthetic acceptance proofs, through the REAL lifecycle path.

Every proof drives the real boundary, the real session functions, the real risk kernel, the real exit policy and the
real Book. Inputs are synthetic; no provider is contacted, nothing is fitted, no limit is changed and no fixture is
chosen for its profitability. The trading fixture is the one the loop demonstration ran into: a contract whose debit
is large enough that two of them exceed the $600 same-underlying cap, so capacity genuinely binds."""
from __future__ import annotations

import json

import pytest

from apex.options_pilot import accounting as ACC
from apex.options_pilot import instant as I
from apex.options_pilot import ledger as L
from apex.options_pilot import lifecycle as LC
from apex.options_pilot import records as R
from apex.options_pilot import replay as RP
from apex.options_pilot import run_dir as RD
from apex.options_pilot import session as S
from apex.options_pilot.book import Book
from apex.options_pilot.clock import to_utc_string
from apex.options_pilot.synthetic_harness import SyntheticHarness

T = 1_789_000_020.0
HOLD = 900.0            # EXIT_AT_HORIZON_15M_V1 horizon
WINDOW = 120.0          # and its window


# ---------------------------------------------------------------------------- fixtures


def harness(tmp_path, sid, *, ask=4.95, exit_bid=4.73):
    """The demonstration's condition: 495 + 500 > the $600 same-underlying cap, so one open position blocks the next
    entry until it is discharged. Nothing here is tuned for profit; the exit is a LOSS at these quotes."""
    h = SyntheticHarness(tmp_path / "led.jsonl", session_id=sid, t0=T, risk="certified")
    h.chain = [{**c, "ask": ask} for c in h.chain]
    h.quotes.ask, h.quotes.bid = ask, round(ask - 0.05, 2)
    h.exit_quotes.ask, h.exit_quotes.bid = round(exit_bid + 0.05, 2), exit_bid
    return h


def on_lifecycle_clock(h):
    """Give the harness the lifecycle's monotonic clock. The harness's own `advance` becomes a guarded sleep, so a
    fixture cannot rewind time either."""
    lc = LC.MonotonicClock(h.now())
    h.clock = lc.clock()
    h.bd.clock = h.clock
    h.now = lc.now
    h.advance = lc.sleep
    return lc


def run(h, lc, *, scans, close_at=None, budget=LC.DEFAULT_EVENT_BUDGET):
    src = h.sources()
    runner = LC.LifecycleRunner(boundary=h.bd, sources=src, clock=lc, symbols=["SPY"],
                                selection_policy="PILOT_RULE_V2", scan_epochs=scans, close_at=close_at,
                                event_budget=budget)
    return runner.run(), runner


def kinds(report):
    return [e["kind"] for e in report["events"]]


def decisions(report):
    return [d["decision"] for d in report["decisions"]]


# ---------------------------------------------------------------------------- 1-3: deadlines, exposure, capacity


class TestExitDeadlinesAreServicedOnTheirOwnSchedule:

    def test_1_an_exit_due_between_scans_is_serviced_inside_its_window(self, tmp_path):
        """THE DEFECT THIS BRICK EXISTS FOR. The demonstration scanned twelve times and only then looked at its one
        position. Here the second scan is 1800 s away and the exit is due at 900 s: it must be serviced at 900 s."""
        h = harness(tmp_path, "L1")
        lc = on_lifecycle_clock(h)
        rep, _ = run(h, lc, scans=[T, T + 1800.0])
        assert decisions(rep)[0] == "TRADE"
        ex = [e for e in rep["events"] if e["kind"] == LC.EXIT_DUE]
        assert ex and ex[0]["outcome"]["state"] == "RESOLVED"
        fill = next(r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_fill" and r["status"] == "FILLED")
        due = fill["committed_epoch"] + HOLD
        serviced = I.canonical_micros(ex[0]["at_utc"])
        assert I.canonical_micros(due) <= serviced <= I.canonical_micros(due + WINDOW), \
            "the exit must be valued at or after its deadline and before its window closes"
        first_exit = rep["events"].index(ex[0])
        scan_ix = [i for i, e in enumerate(rep["events"]) if e["kind"] == LC.SCAN]
        assert scan_ix[0] < first_exit < scan_ix[1], "serviced BETWEEN the two scans, not after both"
        assert not h.bd.book().positions

    def test_2_a_scan_just_before_the_exit_is_due_still_carries_the_open_exposure(self, tmp_path):
        """One second before the deadline the position is genuinely open. The refusal is CORRECT and must stand: the
        loop must not discharge an obligation early to make room for a scan."""
        h = harness(tmp_path, "L2")
        lc = on_lifecycle_clock(h)
        rep, _ = run(h, lc, scans=[T, T + HOLD - 1.0])
        d = decisions(rep)
        assert d[0] == "TRADE" and d[1] == "REFUSE"
        assert "KERNEL_REFUSED" in (rep["decisions"][1]["why"] or "")
        early = [e for e in rep["events"] if e["kind"] == LC.SCAN][1]
        exits_before = [e for e in rep["events"][:rep["events"].index(early)] if e["kind"].startswith("EXIT")]
        assert not any(x["outcome"].get("state") == "RESOLVED" for x in exits_before), \
            "nothing may be resolved before it is due"

    def test_3_a_completed_exit_releases_capacity_and_the_next_scan_can_trade(self, tmp_path):
        h = harness(tmp_path, "L3")
        lc = on_lifecycle_clock(h)
        rep, _ = run(h, lc, scans=[T, T + HOLD + 30.0])
        assert decisions(rep) == ["TRADE", "TRADE"], rep["decisions"]
        order = kinds(rep)
        assert order.index(LC.EXIT_DUE) < order.index(LC.SCAN, order.index(LC.SCAN) + 1), \
            "the exit that released the capacity must precede the scan that used it"
        book = h.bd.book()
        assert len(book.closed) == 2 and not book.positions

    def test_exit_servicing_does_not_wait_for_a_scan_at_all(self, tmp_path):
        """One scan, then nothing. The obligation must still be discharged: exit servicing is not a side effect of
        scanning."""
        h = harness(tmp_path, "L3b")
        lc = on_lifecycle_clock(h)
        rep, _ = run(h, lc, scans=[T])
        assert len([e for e in rep["events"] if e["kind"] == LC.SCAN]) == 1
        assert any(e["kind"] == LC.EXIT_DUE and e["outcome"]["state"] == "RESOLVED" for e in rep["events"])
        assert rep["completion"] == "CLOSED_CLEAN"


# ---------------------------------------------------------------------------- 4-5: retries and exhaustion


class TestUnavailableQuotesRetryAndThenExhaust:

    @staticmethod
    def _broken(tmp_path, sid):
        from apex.pulse_options.providers import ProviderUnavailable
        h = harness(tmp_path, sid)
        h.exit_quotes.fail_with = ProviderUnavailable("EXIT_QUOTE_UNAVAILABLE_FIXTURE")
        return h

    def test_4_unavailable_quotes_schedule_retries_and_never_rewind_the_clock(self, tmp_path):
        h = self._broken(tmp_path, "L4")
        lc = on_lifecycle_clock(h)
        rep, _ = run(h, lc, scans=[T])
        attempts = [e for e in rep["events"] if e["kind"] in (LC.EXIT_DUE, LC.EXIT_RETRY, LC.EXIT_WINDOW_CLOSE)]
        assert len(attempts) >= 2, "an unavailable quote must be RETRIED, on a schedule"
        stamps = [I.canonical_micros(e["at_utc"]) for e in rep["events"]]
        assert stamps == sorted(stamps), "the event stream must be chronological"
        assert all(a["delta_s"] >= 0 for a in rep["clock_advances"]), "the clock never rewinds"
        assert all(a["at_us"] >= b["at_us"] for a, b in zip(attempts[1:], attempts[:-1]))

    def test_5_an_exhausted_exit_is_an_explicit_unresolved_obligation(self, tmp_path):
        h = self._broken(tmp_path, "L5")
        lc = on_lifecycle_clock(h)
        rep, _ = run(h, lc, scans=[T])
        rows = L.read_all(h.bd.ledger)
        assert any(r["kind"] == "pilot_exit_exhausted" for r in rows), "exhaustion must be PERSISTED, not implied"
        book = h.bd.book()
        assert len(book.positions) == 1 and book.positions[0]["exit_exhausted"]
        assert rep["completion"] == "CLOSED_WITH_OUTSTANDING_OBLIGATIONS"
        agg = ACC.net_result(book)
        assert agg["total_net_pnl"] is None and agg["total_net_status"] == ACC.NOT_ESTIMABLE
        assert any("EXIT_EXHAUSTED_POSITIONS" in w for w in agg["why_not_estimable"])
        assert agg["n_unresolved_positions"] == 1
        ACC.assert_no_phantom_zero(agg)

    def test_the_valuation_attempts_stay_inside_the_frozen_policy(self, tmp_path):
        h = self._broken(tmp_path, "L5b")
        lc = on_lifecycle_clock(h)
        run(h, lc, scans=[T])
        rows = L.read_all(h.bd.ledger)
        att = [r for r in rows if r["kind"] == "pilot_outcome"]
        assert 1 <= len(att) <= h.bd.exit_policy.max_attempts
        fill = next(r for r in rows if r["kind"] == "pilot_fill" and r["status"] == "FILLED")
        close = fill["committed_epoch"] + HOLD + WINDOW
        for a in att:
            assert I.canonical_micros(a["resolved_utc"]) <= I.canonical_micros(close) + 1


# ---------------------------------------------------------------------------- 6: restart


class TestRestartRecoversWithoutDuplicating:

    def test_6_a_restart_recovers_the_obligation_without_a_duplicate_fill_or_fee(self, tmp_path):
        """Process one dies immediately after the fill. Process two, same ledger and session, must finish the job and
        must not re-execute the intent."""
        h1 = harness(tmp_path, "L6")
        lc1 = on_lifecycle_clock(h1)
        src = h1.sources()
        S.open_session(h1.bd, symbols=["SPY"])
        d = S.scan(h1.bd, symbol="SPY", seq=1, **{k: v for k, v in src.items() if k != "exit_quote_fn"})
        assert d["decision"] == "TRADE"
        rows_before = L.read_all(h1.bd.ledger)
        n_fills_before = sum(1 for r in rows_before if r["kind"] == "pilot_fill")
        entry_fee = next(r for r in rows_before if r["kind"] == "pilot_fill")["fees_entry"]["total"]

        h2 = harness(tmp_path, "L6")                      # same ledger path, same session id: a restart
        lc2 = LC.MonotonicClock(lc1.now() + HOLD + 5.0)   # the process restarts after the exit came due
        h2.clock = lc2.clock(); h2.bd.clock = h2.clock; h2.now = lc2.now; h2.advance = lc2.sleep
        rep2, _ = run(h2, lc2, scans=[])
        rows_after = L.read_all(h2.bd.ledger)
        assert sum(1 for r in rows_after if r["kind"] == "pilot_fill") == n_fills_before, "no duplicate fill"
        fees = [r["fees_entry"]["total"] for r in rows_after if r["kind"] == "pilot_fill" and r.get("fees_entry")]
        assert fees == [entry_fee], "the entry fee is charged once and only once"
        assert rep2["recovered_positions"], "the restart must SEE the obligation"
        book = h2.bd.book()
        assert len(book.closed) == 1 and not book.positions
        rec = ACC.reconcile(book, rows_after, fee_schedules={h2.fee_schedule.schedule_id: h2.fee_schedule})
        assert rec["agrees"], rec["problems"]


# ---------------------------------------------------------------------------- 7: deterministic simultaneity


class TestSimultaneousEventsAreDeterministic:

    def test_7_an_exit_and_a_scan_at_the_same_instant_order_the_exit_first(self, tmp_path):
        h = harness(tmp_path, "L7")
        lc = on_lifecycle_clock(h)
        S.open_session(h.bd, symbols=["SPY"])
        d = S.scan(h.bd, symbol="SPY", seq=1, **{k: v for k, v in h.sources().items() if k != "exit_quote_fn"})
        assert d["decision"] == "TRADE"
        fill = next(r for r in L.read_all(h.bd.ledger) if r["kind"] == "pilot_fill" and r["status"] == "FILLED")
        due = fill["committed_epoch"] + HOLD
        rep, _ = run(h, lc, scans=[due])                  # a scan at EXACTLY the exit deadline
        order = kinds(rep)
        assert order.index(LC.EXIT_DUE) < order.index(LC.SCAN), "the due obligation is processed before new risk"
        assert decisions(rep) == ["TRADE"], "and the capacity it released is what let the scan through"

    def test_the_ordering_is_reproducible(self, tmp_path):
        seen = set()
        for i in range(3):
            h = harness(tmp_path / str(i), "L7R")
            lc = on_lifecycle_clock(h)
            rep, _ = run(h, lc, scans=[T, T + HOLD, T + 2 * HOLD])
            seen.add(tuple((e["kind"], e["at_utc"]) for e in rep["events"]))
        assert len(seen) == 1, "the same inputs must produce the same event order, every time"

    def test_the_total_order_is_by_instant_then_rank_then_scheduling_ordinal(self):
        lc = LC.MonotonicClock(T)
        sch = LC.Scheduler(lc)
        sch.at(T + 10, LC.SCAN, key="scan")
        sch.at(T + 10, LC.EXIT_DUE, key="exit")
        sch.at(T + 10, LC.EXIT_DUE, key="exit2")
        sch.at(T + 5, LC.SESSION_CLOSE, key="early-close")
        lc.advance_to(T + 10)
        got = [(e["kind"], e["key"]) for e in sch.pop_due()]
        assert got == [("SESSION_CLOSE", "early-close"), ("EXIT_DUE", "exit"), ("EXIT_DUE", "exit2"), ("SCAN", "scan")]


class TestTheClockNeverRewinds:

    def test_advancing_backwards_is_refused(self):
        lc = LC.MonotonicClock(T)
        lc.advance_to(T + 10.0)
        with pytest.raises(LC.LifecycleRefused, match="CLOCK_REWIND_REFUSED"):
            lc.advance_to(T + 9.999999)
        with pytest.raises(LC.LifecycleRefused, match="CLOCK_REWIND_REFUSED"):
            lc.sleep(-1.0)
        assert lc.now() == T + 10.0

    def test_scheduling_into_the_past_is_refused_unless_declared_overdue(self):
        lc = LC.MonotonicClock(T)
        sch = LC.Scheduler(lc)
        lc.advance_to(T + 100.0)
        with pytest.raises(LC.LifecycleRefused, match="EVENT_IN_THE_PAST"):
            sch.at(T + 1.0, LC.EXIT_DUE, key=1)
        ev = sch.at(T + 1.0, LC.EXIT_DUE, key=1, allow_past=True)
        assert ev["at_us"] == lc.now_us(), "an overdue obligation is due NOW, never at an instant already gone"

    def test_the_demonstration_driver_defect_is_now_structurally_impossible(self, tmp_path):
        """The driver set `rec.t = t0 + HOLD_S`, moving the clock from 16:15Z back to 13:45Z. Through the lifecycle
        clock that assignment is a refusal."""
        h = harness(tmp_path, "L7D")
        lc = on_lifecycle_clock(h)
        lc.advance_to(T + 9900.0)
        with pytest.raises(LC.LifecycleRefused, match="CLOCK_REWIND_REFUSED"):
            lc.advance_to(T + HOLD)


# ---------------------------------------------------------------------------- 8: recorded-data visibility


class TestRecordedInputVisibility:

    @staticmethod
    def _inputs():
        return RP.RecordedInputs([
            {"event_time": T, "available_time": T + 60.0, "close": 1.0},
            {"event_time": T + 60.0, "available_time": T + 120.0, "close": 2.0},
            {"event_time": T + 120.0, "available_time": T + 180.0, "close": 3.0}])

    def test_8_a_recorded_input_is_invisible_before_its_recorded_availability(self):
        ri = self._inputs()
        assert ri.visible(T) == []
        assert ri.visible(T + 59.999999) == []
        assert len(ri.visible(T + 60.0)) == 1, "visible exactly at its availability instant"
        assert len(ri.visible(T + 179.999999)) == 2
        assert len(ri.visible(T + 180.0)) == 3
        assert len(ri.hidden(T + 60.0)) == 2

    def test_event_time_and_availability_are_preserved_separately(self):
        ri = self._inputs()
        assert ri.items[0]["source_timestamps"] == {"event_time": T, "available_time": T + 60.0}
        assert ri.items[0]["event_us"] != ri.items[0]["available_us"]

    def test_availability_before_the_event_is_refused(self):
        with pytest.raises(RP.ReplayRefused, match="RECORDED_AVAILABLE_BEFORE_EVENT"):
            RP.RecordedInputs([{"event_time": T + 10.0, "available_time": T}])

    def test_the_availability_instants_are_the_data_events_the_loop_schedules(self, tmp_path):
        ri = self._inputs()
        assert ri.availability_epochs() == [T + 60.0, T + 120.0, T + 180.0]
        h = harness(tmp_path, "L8")
        lc = on_lifecycle_clock(h)
        runner = LC.LifecycleRunner(boundary=h.bd, sources=h.sources(), clock=lc, symbols=["SPY"],
                                    selection_policy="PILOT_RULE_V2", scan_epochs=[T + 200.0],
                                    data_available_epochs=ri.availability_epochs())
        rep = runner.run()
        got = [e["at_utc"] for e in rep["events"] if e["kind"] == LC.DATA_AVAILABLE]
        assert got == [I.canonical_utc(t) for t in ri.availability_epochs()]
        assert kinds(rep).index(LC.SCAN) > kinds(rep).index(LC.DATA_AVAILABLE)


# ---------------------------------------------------------------------------- 9: canonical instants


class TestCanonicalInstants:

    def test_9_the_next_representable_future_instant_is_refused(self, tmp_path):
        h = SyntheticHarness(tmp_path / "l.jsonl", t0=T)
        f = h.base_forecast("SPY", h.now())
        R.validate_forecast({**f, "created_utc": to_utc_string(h.now())}, now_epoch=h.now(),
                            provenance="SYNTHETIC_FIXTURE", session_id="S", scan_id="X")
        nxt = I.from_micros(I.canonical_micros(h.now()) + 1)
        with pytest.raises(R.RecordRefused, match="FORECAST_FROM_THE_FUTURE"):
            R.validate_forecast({**f, "created_utc": to_utc_string(nxt)}, now_epoch=h.now(),
                                provenance="SYNTHETIC_FIXTURE", session_id="S", scan_id="X")

    def test_there_is_no_epsilon_in_the_comparison(self):
        assert I.is_after(I.from_micros(I.canonical_micros(T) + 1), T)
        assert not I.is_after(T, T)
        assert I.compare(T, T) == 0

    def test_the_round_trip_is_the_identity_at_the_declared_precision(self):
        for t in (T, 1_789_134_322.3894567, 1_789_134_322.9999996, 0.5, 1e9 + 0.0000005):
            assert I.round_trips(t), t

    def test_the_upward_round_trip_that_broke_the_demonstration_is_equal_now(self):
        from apex.options_pilot.clock import parse_utc
        t = 1_789_134_322.3894567
        assert parse_utc(to_utc_string(t), field="x") > t, "fixture must exhibit the upward round trip"
        assert I.same_instant(parse_utc(to_utc_string(t), field="x"), t), "canonically they are ONE instant"

    def test_invalid_instants_are_refused(self):
        from apex.options_pilot.clock import ClockRefused
        for bad in (None, True, float("nan"), float("inf"), "", "not-a-time", "2026-09-11T13:30:23.096973"):
            with pytest.raises(ClockRefused):
                I.canonical_micros(bad)

    def test_the_conversion_and_rounding_rule_is_documented_on_the_record(self):
        assert "no epsilon" in I.CONVERSION_RULE
        assert R.TIMESTAMP_CONVERSION_RULE == I.CONVERSION_RULE
        st = I.stamp(T, source="2026-09-11T13:30:23.096973Z", source_field="provider_ts")
        assert st["canonical_us"] == I.canonical_micros(T) and st["source"]["value"].endswith("Z")


# ---------------------------------------------------------------------------- 10: run directories


class TestRunDirectories:

    def test_10_a_collision_is_refused_and_nothing_is_overwritten(self, tmp_path):
        rd = RD.new_run(tmp_path, run_id="R1", now_epoch=T, config={"policy": "PILOT_RULE_V2"})
        rd.write("report.json", json.dumps({"a": 1}))
        with pytest.raises(RD.RunDirRefused, match="RUN_DIR_COLLISION"):
            RD.new_run(tmp_path, run_id="R1", now_epoch=T)
        with pytest.raises(RD.RunDirRefused, match="ARTIFACT_NAME_ALREADY_CLAIMED"):
            rd.path_for("report.json")
        rd2 = RD.new_run(tmp_path, run_id="R2", now_epoch=T)
        with pytest.raises(RD.RunDirRefused, match="ARTIFACT_EXISTS"):
            (rd2.path / "x.json").write_text("{}")
            rd2.path_for("x.json")
        assert json.loads((rd.path / "report.json").read_text()) == {"a": 1}, "the first run's artifact is intact"

    def test_a_failed_run_keeps_its_partial_artifacts_and_says_it_failed(self, tmp_path):
        rd = RD.new_run(tmp_path, run_id="F1", now_epoch=T)
        rd.write("partial_ledger.jsonl", '{"kind":"pilot_forecast"}\n')
        rd.failed(now_epoch=T + 5.0, error=RuntimeError("provider died"))
        st = rd.status()
        assert st["status"] == "FAILED" and "partial_ledger.jsonl" in st["artifacts"]
        body = json.loads((rd.path / RD.FAILED_FILE).read_text())
        assert "provider died" in body["error"] and body["artifacts_preserved"]
        assert (rd.path / "partial_ledger.jsonl").read_text().strip()

    def test_start_identity_records_inputs_configuration_and_the_code_pin(self, tmp_path):
        src = tmp_path / "in.json"
        src.write_text('{"bars": 3}')
        rd = RD.new_run(tmp_path / "runs", run_id="R3", now_epoch=T, inputs={"bars": src},
                        config={"policy": "WAIT", "limits": "unchanged"})
        body = json.loads((rd.path / RD.START_FILE).read_text())
        assert body["inputs"]["bars"]["sha256"] and body["config_digest"]
        assert body["code_pin"]["status"] in ("PINNED", "UNAVAILABLE")
        assert body["started_canonical_us"] == I.canonical_micros(T)
        rd.complete(now_epoch=T + 1.0, summary={"trades": 0})
        assert rd.status()["status"] == "COMPLETED"
        with pytest.raises(RD.RunDirRefused, match="RUN_ALREADY_TERMINAL"):
            rd.complete(now_epoch=T + 2.0)

    def test_nothing_in_the_output_path_removes_a_previous_artifact(self):
        """STRUCTURAL BAN, in the spirit of B7: the run-directory module never unlinks or removes."""
        import pathlib
        src = pathlib.Path("apex/options_pilot/run_dir.py").read_text()
        for banned in ("unlink(", "rmtree", "shutil.rm", ".truncate("):
            assert banned not in src, banned


# ---------------------------------------------------------------------------- 11: unknown accounting


class TestUnknownCostsCannotBecomeACompleteResult:

    @staticmethod
    def _closed_rows(tmp_path):
        h = harness(tmp_path, "L11")
        lc = on_lifecycle_clock(h)
        run(h, lc, scans=[T])
        return h, L.read_all(h.bd.ledger)

    def test_11_an_unknown_exit_fee_makes_the_aggregate_not_estimable(self, tmp_path):
        h, rows = self._closed_rows(tmp_path)
        good = ACC.net_result(h.bd.book())
        assert good["total_net_estimable"] and good["total_net_pnl"] is not None
        blinded = [dict(r) for r in rows]
        for r in blinded:
            if r["kind"] == "pilot_outcome" and r.get("status") == "RESOLVED":
                r["fees_exit"] = {**(r.get("fees_exit") or {}), "total": None, "why": "FIXTURE: exit fee unknown"}
                r.pop("pnl", None)
        book = Book(blinded, session_id=h.session_id, fee_schedules={})
        agg = ACC.net_result(book)
        assert agg["total_net_pnl"] is None and agg["total_net_status"] == ACC.NOT_ESTIMABLE
        assert agg["n_closed_net_not_estimable"] == 1
        assert any("CLOSED_POSITIONS_WITHOUT_A_NET" in w for w in agg["why_not_estimable"])
        ACC.assert_no_phantom_zero(agg)

    def test_an_unresolved_position_cannot_vanish_from_the_total(self, tmp_path):
        from apex.pulse_options.providers import ProviderUnavailable
        h = harness(tmp_path, "L11b")
        h.exit_quotes.fail_with = ProviderUnavailable("NO_EXIT_FIXTURE")
        lc = on_lifecycle_clock(h)
        run(h, lc, scans=[T])
        agg = ACC.net_result(h.bd.book())
        assert agg["total_net_pnl"] is None
        assert agg["n_unresolved_positions"] == 1 and agg["unresolved_fill_seqs"]
        assert agg["valuation_status"], "the unresolved position's valuation state must be reported, not dropped"

    def test_zero_is_a_result_only_for_a_policy_that_actually_traded_nothing(self, tmp_path):
        h = harness(tmp_path, "L11c")
        lc = on_lifecycle_clock(h)
        runner = LC.LifecycleRunner(boundary=h.bd, sources=h.sources(), clock=lc, symbols=["SPY"],
                                    selection_policy="PILOT_RULE_V2", scan_epochs=[])
        runner.run()
        agg = ACC.net_result(h.bd.book())
        assert agg["total_net_pnl"] == 0.0 and agg["zero_basis"] == ACC.ZERO_NO_TRADE
        ACC.assert_no_phantom_zero(agg)

    def test_a_net_may_never_be_reported_while_the_aggregate_is_not_estimable(self):
        with pytest.raises(ValueError, match="NET_REPORTED_WHILE_NOT_ESTIMABLE"):
            ACC.assert_no_phantom_zero({"total_net_pnl": -22.09, "total_net_estimable": False,
                                        "why_not_estimable": ["UNRESOLVED_POSITIONS: 1"]})
        with pytest.raises(ValueError, match="PHANTOM_ZERO_NET"):
            ACC.assert_no_phantom_zero({"total_net_pnl": 0.0, "total_net_estimable": True, "zero_basis": None,
                                        "n_closed_with_net": 0, "why_not_estimable": []})


class TestIndependentArithmetic:
    """Cash, fees, reservations and P&L recomputed from the PRIMARY ledger fields, without the Book's aggregates."""

    def test_the_independent_recomputation_agrees_with_the_book_on_a_closed_trade(self, tmp_path):
        h = harness(tmp_path, "A1")
        lc = on_lifecycle_clock(h)
        run(h, lc, scans=[T, T + HOLD + 30.0])
        rows = L.read_all(h.bd.ledger)
        rec = ACC.reconcile(h.bd.book(), rows, fee_schedules={h.fee_schedule.schedule_id: h.fee_schedule})
        assert rec["agrees"], rec["problems"]
        assert not rec["book_integrity_problems"]
        assert {l["line"] for l in rec["lines"]} == {"cash", "reserved", "open_position_cost", "realized_pnl"}

    def test_the_arithmetic_is_checked_against_hand_computed_values(self, tmp_path):
        h = harness(tmp_path, "A2", ask=4.95, exit_bid=4.73)
        lc = on_lifecycle_clock(h)
        run(h, lc, scans=[T])
        rows = L.read_all(h.bd.ledger)
        fill = next(r for r in rows if r["kind"] == "pilot_fill" and r["status"] == "FILLED")
        out = next(r for r in rows if r["kind"] == "pilot_outcome" and r.get("status") == "RESOLVED")
        debit = fill["price"] * 100.0 * fill["quantity_filled"]
        credit = out["exit_price"] * 100.0 * fill["quantity_filled"]
        fe, fx = fill["fees_entry"]["total"], out["fees_exit"]["total"]
        assert abs(debit - 495.0) < 1e-9 and abs(credit - 473.0) < 1e-9
        book = h.bd.book()
        p = book.closed[0]
        assert abs(p["gross_pnl"] - (credit - debit)) < 1e-9
        assert abs(p["realized_pnl"] - (credit - debit - fe - fx)) < 1e-9
        ind = ACC.independent_check(rows, fee_schedules={})
        assert abs(ind["realized_pnl_closed"] - (credit - debit - fe - fx)) < 0.005
        assert abs(ind["cash"] - book.cash) < 0.005
        assert book.cash_identity()["holds"]

    def test_reserved_capital_is_released_when_the_intent_finishes(self, tmp_path):
        h = harness(tmp_path, "A3")
        lc = on_lifecycle_clock(h)
        run(h, lc, scans=[T])
        book = h.bd.book()
        assert book.reserved == 0.0 and not book.reserved_unknown
        ind = ACC.independent_check(L.read_all(h.bd.ledger), fee_schedules={})
        assert ind["reserved"] == 0.0


# ---------------------------------------------------------------------------- 12: WAIT is a decision


class TestWaitIsPersistedAsADecision:

    def test_12_a_wait_is_a_persisted_decision_record(self, tmp_path):
        """The executable ask exceeds the risk envelope, so the fill attempt is a WAIT. A WAIT is a DECISION -- it is
        recorded on disk with its reason, not dropped as a non-event."""
        h = harness(tmp_path, "L12")
        h.quotes.ask, h.quotes.bid = 9.95, 9.90          # above the envelope's max entry price
        lc = on_lifecycle_clock(h)
        rep, _ = run(h, lc, scans=[T])
        assert decisions(rep) == ["WAIT"], rep["decisions"]
        rows = L.read_all(h.bd.ledger)
        dec = [r for r in rows if r["kind"] == "pilot_decision"]
        assert len(dec) == 1 and dec[0]["decision"] == "WAIT" and dec[0]["why"]
        assert rep["decisions"][0]["decision_persisted"] is True
        agg = ACC.net_result(h.bd.book())
        assert agg["total_net_pnl"] == 0.0 and agg["zero_basis"] == ACC.ZERO_NO_TRADE

    def test_every_scan_ends_in_exactly_one_persisted_decision(self, tmp_path):
        h = harness(tmp_path, "L12b")
        lc = on_lifecycle_clock(h)
        rep, _ = run(h, lc, scans=[T, T + HOLD - 1.0, T + HOLD + 30.0])
        rows = L.read_all(h.bd.ledger)
        dec = [r for r in rows if r["kind"] == "pilot_decision"]
        assert len(dec) == 3 == len(rep["decisions"])
        assert all(r["decision"] in ("TRADE", "WAIT", "REFUSE") for r in dec)
        assert all(r.get("why") is not None or r["decision"] == "TRADE" for r in dec)


# ---------------------------------------------------------------------------- honest evidence classes


class TestHonestEvidenceClasses:

    @staticmethod
    def _auth():
        return RP.ReplayAuthorization(reason="OPERATING-LOOP-001 acceptance", recorded_window_utc=("a", "b"),
                                      input_digests={"bars": "e" * 64})

    def test_the_replay_route_must_be_selected_explicitly_and_named_by_digest(self):
        with pytest.raises(RP.ReplayRefused, match="REPLAY_INPUT_DIGESTS_REQUIRED"):
            RP.ReplayAuthorization(reason="x", input_digests={}, recorded_window_utc=("a", "b"))
        with pytest.raises(RP.ReplayRefused, match="REPLAY_REASON_REQUIRED"):
            RP.ReplayAuthorization(reason="", input_digests={"b": "e" * 64}, recorded_window_utc=("a", "b"))

    def test_a_replay_boundary_writes_replay_labels_and_cannot_claim_prospective_evidence(self, tmp_path):
        h = SyntheticHarness(tmp_path / "syn.jsonl", t0=T)
        # require_verified_inputs=False: this test exercises the LABELS, not the input binding, which has its own
        # tests in tests/test_flow_validation_readiness.py. Naming the waiver keeps the two controls distinct.
        bd = RP.replay_boundary(tmp_path / "replay.jsonl", clock=h.clock, risk_authority=h.risk,
                                session_id="RPL", release="r", authorization=self._auth(),
                                fee_schedule=h.fee_schedule, require_verified_inputs=False)
        assert bd.replay and bd.labels["evidence_class"] == R.REPLAY_EVIDENCE_CLASS
        assert bd.labels["prospective_results_eligible"] is False
        assert bd.labels["live_promotion_eligible"] is False
        assert bd.labels["live_authorization_eligible"] is False
        with pytest.raises(R.RecordRefused, match="REPLAY_LABEL_ON_PROSPECTIVE_RECORD|LABELS_NOT_PROSPECTIVE"):
            R.assert_prospective({**bd.labels, "kind": "pilot_decision"})
        R.assert_record_labels({**bd.labels, "kind": "pilot_decision"})

    def test_a_replay_record_is_excluded_from_live_authorization_and_promotion(self):
        rl = R.labels_for("RECORDED_REPLAY")
        with pytest.raises(R.RecordRefused, match="REPLAY_NOT_LIVE_AUTHORIZABLE"):
            R.assert_live_authorizable(rl, what="promotion")
        R.assert_live_authorizable(R.labels_for("LIVE_FEED"), what="promotion")

    def test_replay_rows_are_excluded_from_a_prospective_results_aggregate(self):
        rows = [{**R.labels_for("LIVE_FEED"), "kind": "pilot_outcome", "pnl": 1.0},
                {**R.labels_for("RECORDED_REPLAY"), "kind": "pilot_outcome", "pnl": 999.0},
                {"kind": "pilot_outcome", "data_provenance": "RECORDED_REPLAY", "pnl": 5.0}]
        kept = R.prospective_only(rows)
        assert len(kept) == 1 and kept[0]["pnl"] == 1.0
        summary = RP.assert_excluded_from_prospective_results(rows)
        assert summary["n_replay_excluded"] == 2 and summary["n_prospective"] == 1

    def test_the_two_classes_never_share_a_ledger(self, tmp_path):
        h = SyntheticHarness(tmp_path / "led.jsonl", t0=T)
        S.open_session(h.bd, symbols=["SPY"])
        with pytest.raises(R.RecordRefused, match="EVIDENCE_ROUTE_MIXED"):
            RP.replay_boundary(tmp_path / "led.jsonl", clock=h.clock, risk_authority=h.risk, session_id="RPL",
                               release="r", authorization=self._auth(), fee_schedule=h.fee_schedule,
                               require_verified_inputs=False)

    def test_the_prospective_route_is_not_weakened(self):
        """assert_prospective still refuses every replay marker, and a record claiming neither class is refused."""
        good = {**R.labels_for("SYNTHETIC_FIXTURE"), "kind": "pilot_decision"}
        R.assert_prospective(good)
        for bad in ({**good, "evidence_class": "HISTORICAL_DEVELOPMENT_REPLAY"},
                    {**good, "decision_power": "NONE_REPLAY"},
                    {**good, "data_provenance": "RECORDED_REPLAY"}):
            with pytest.raises(R.RecordRefused):
                R.assert_prospective(bad)
        with pytest.raises(R.RecordRefused, match="EVIDENCE_CLASS_UNKNOWN"):
            R.assert_record_labels({**good, "evidence_class": "SOMETHING_ELSE"})

    def test_a_replay_record_missing_an_exclusion_flag_is_refused(self):
        rl = {**R.labels_for("RECORDED_REPLAY"), "kind": "pilot_decision"}
        for k in ("live_promotion_eligible", "prospective_results_eligible", "live_authorization_eligible"):
            with pytest.raises(R.RecordRefused, match="REPLAY_EXCLUSION_NOT_SEALED"):
                R.assert_record_labels({**rl, k: True})
        with pytest.raises(R.RecordRefused, match="REPLAY_FLAG_NOT_SEALED"):
            R.assert_record_labels({**rl, "replay": False})


class TestTheRepairedDemonstrationDriver:
    """`scripts/loop_demonstration.py` is the driver whose three defects this brick removes. It is REPAIRED BUT NOT
    RE-RUN (recorded evaluation is outside this brick's scope), so what is checked here is that the defects are gone
    from the source and that it now uses the tested library paths."""

    @staticmethod
    def _src():
        """The driver's CODE, with the module docstring and comment lines removed: the header and the comments
        describe the defects on purpose, so grepping them would find what the code no longer does."""
        import ast
        import pathlib
        text = pathlib.Path("scripts/loop_demonstration.py").read_text()
        tree = ast.parse(text)
        lines = text.splitlines()
        first = tree.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            lines = lines[first.end_lineno:]
        return "\n".join(l for l in lines if not l.strip().startswith("#"))

    def test_it_no_longer_unlinks_or_writes_to_a_fixed_directory(self):
        s = self._src()
        assert "unlink(" not in s and "rmtree" not in s
        assert "RD.new_run(" in s and "rd.path_for(" in s and "RUN.write_json(" in s

    def test_it_no_longer_assigns_to_the_recorded_clock(self):
        s = self._src()
        assert "rec.t = chains[" not in s and "rec.t = t0" not in s
        assert "LC.MonotonicClock(" in s and "LC.LifecycleRunner(" in s

    def test_it_takes_the_recorded_replay_route_not_the_live_one(self):
        s = self._src()
        assert "RP.replay_boundary(" in s and "ReplayAuthorization(" in s
        assert 'B.Boundary(led, clock=clock, provenance="LIVE_FEED"' not in s

    def test_it_no_longer_sums_unknowns_as_zero(self):
        s = self._src()
        assert 'p.get("realized_pnl") or 0.0' not in s and 'p.get("gross_pnl") or 0.0' not in s
        assert "ACC.net_result(" in s and "ACC.assert_no_phantom_zero(" in s

    def test_the_module_still_parses(self):
        import ast
        ast.parse(self._src())


# ---------------------------------------------------------------------------- the full event trace


class TestTheWholeLoopTrace:

    def test_forecast_to_decision_to_fill_to_exit_to_released_capital_to_next_decision(self, tmp_path):
        """The trace the brick asks for, end to end, on one synthetic timeline."""
        h = harness(tmp_path, "TRACE")
        lc = on_lifecycle_clock(h)
        rep, _ = run(h, lc, scans=[T, T + HOLD + 30.0])
        rows = L.read_all(h.bd.ledger)
        seen = [r["kind"] for r in rows]
        for k in ("pilot_session_open", "pilot_forecast", "pilot_intent", "pilot_fill", "pilot_decision",
                  "pilot_outcome", "pilot_session_close"):
            assert k in seen, k
        assert decisions(rep) == ["TRADE", "TRADE"]
        book = h.bd.book()
        assert len(book.closed) == 2 and not book.positions and not book.problems
        agg = ACC.net_result(book)
        assert agg["total_net_estimable"] and agg["n_closed_with_net"] == 2
        rec = ACC.reconcile(book, rows, fee_schedules={h.fee_schedule.schedule_id: h.fee_schedule})
        assert rec["agrees"], rec["problems"]
        assert L.verify_chain(h.bd.ledger)
