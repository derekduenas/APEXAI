"""PREMARKET-SEQUENTIAL-AUDIT-001-R2 — corrected root cause, and the simulated morning."""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from apex.audit.fake_morning import (FIXTURES, RECORDED_MODEL_RESPONSE, TRADING_DATE, ET_STAGES,
                                     et_epoch, firewall_verdict)
from apex.frontier import run_record as RR
from apex.frontier.premarket_time import packet_times, source_observation


class TestTheCorrectedRootCauseRecord:
    def test_runs_zero_is_explained_by_the_boot_time_and_proves_nothing_about_the_gap(self):
        """WITHDRAWN CLAIM. R1 called the root cause conclusive. The machine booted Fri 2026-09-11 16:09 --
        AFTER that Friday's 05:14 -- and Sat/Sun are not weekdays, so NO scheduled fire has been due since boot.
        runs=0 is fully self-explaining and is not evidence about 2026-08-26..09-11."""
        import datetime as dt
        boot = dt.datetime(2026, 9, 11, 16, 9, 42)
        now = dt.datetime(2026, 9, 13, 17, 20)
        d, fires = boot.date(), []
        while d <= now.date():
            if d.weekday() < 5:
                t = dt.datetime.combine(d, dt.time(5, 14))
                if boot < t <= now:
                    fires.append(t)
            d += dt.timedelta(days=1)
        assert fires == [], "no weekday 05:14 has occurred since boot"

    def test_missed_calendar_runs_while_loaded_and_asleep_are_COALESCED_not_lost(self):
        """WITHDRAWN CLAIM. I said a missed run was 'permanently lost'. The host's own manual says otherwise."""
        import subprocess
        man = subprocess.run(["man", "5", "launchd.plist"], capture_output=True, text=True).stdout
        man = re.sub(r".\x08", "", man)
        assert "launchd will start the job the next time the computer wakes up" in man
        assert "coalesced into one event upon wake from sleep" in man


class TestTheLongSleepDesign:
    def test_one_process_sleeps_through_every_stage(self):
        src = pathlib.Path("scripts/premarket_run.py").read_text()
        assert src.count("time.sleep(") >= 2
        assert "min(wait, 3600)" in src, "the sleep is capped at an hour"

    def test_the_capped_sleep_can_run_a_stage_EARLY(self):
        """A real defect in the current design: if a stage target is more than 3600s away, the capped sleep
        returns early and absorb() runs at the wrong time, with no re-check."""
        src = pathlib.Path("scripts/premarket_run.py").read_text()
        i = src.index("time.sleep(min(wait, 3600))")
        after = src[i:i + 220]
        assert "while" not in after.split("absorb")[0], "no loop re-checks the target after the capped sleep"


class TestTheSimulatedMorning:
    def test_every_declared_disposition_is_one_of_the_named_outcomes(self):
        named = {"ACCEPTED", "CLUSTERED_AS_SYNDICATION", "APPLIED_AS_ADDITIVE_REVISION", "MARKED_UNAVAILABLE",
                 "EXCLUDED_AS_STALE", "REFUSED_AS_FUTURE", "RETAINED_AS_DATA_NO_AUTHORITY"}
        assert {v["disposition"] for v in FIXTURES.values()} <= named
        assert len(FIXTURES) == 10

    def test_the_recorded_brief_passes_the_real_firewall(self):
        assert firewall_verdict(RECORDED_MODEL_RESPONSE.format(date=TRADING_DATE))["verdict"] == "PASSES_FIREWALL"

    def test_the_hostile_headline_would_be_refused_if_it_reached_the_brief(self):
        v = firewall_verdict(FIXTURES["hostile_headline"]["text"])
        assert v["verdict"] == "REFUSED_BY_FIREWALL" and "buy " in v["hits"]

    def test_the_model_response_is_labelled_recorded_not_generated(self):
        import apex.audit.fake_morning as FM
        assert "RECORDED_MODEL_RESPONSE" in dir(FM)
        assert "not model GENERATION" in FM.__doc__ or "model GENERATION" in FM.__doc__

    def test_the_time_fields_satisfy_the_laws(self):
        cutoff = et_epoch(TRADING_DATE, 9, 20)
        obs = [source_observation(receipt_time=cutoff - 120)]
        t = packet_times(collection_started_at=et_epoch(TRADING_DATE, 8, 15), observations=obs,
                         created_at=et_epoch(TRADING_DATE, 9, 25) - 10,
                         sealed_at=et_epoch(TRADING_DATE, 9, 25))
        assert t["packet_known_from"] >= t["packet_sealed_at"]
        assert t["packet_data_cutoff"] < t["packet_sealed_at"]

    def test_the_stages_are_separate_bounded_invocations(self):
        assert len(ET_STAGES) == 4
        assert [s[0] for s in ET_STAGES] == ["0815_ET_initial", "0832_ET_post_macro",
                                             "0905_ET_refresh", "0920_ET_final"]


class TestFailureFlights:
    @pytest.fixture(autouse=True)
    def isolate(self, tmp_path, monkeypatch):
        monkeypatch.setattr(RR, "RUNS", tmp_path / "runs")

    def test_a_late_stage_records_its_ACTUAL_time_and_is_not_backdated(self):
        r = RR.RunRecord(run_id="late", scheduled_epoch=et_epoch(TRADING_DATE, 8, 15),
                         now=lambda: et_epoch(TRADING_DATE, 8, 41))
        r.stage("SOURCES", "LATE_START", scheduled="08:15 ET", actual="08:41 ET")
        b = json.loads(r.path.read_text())
        assert b["stages"]["SOURCES"]["status"] == "LATE_START"
        assert b["started_epoch"] > b["scheduled_epoch"], "the actual time is recorded, not the scheduled one"

    def test_a_missed_window_is_recorded_without_fetching_retrospective_data(self):
        r = RR.RunRecord(run_id="missed", scheduled_epoch=et_epoch(TRADING_DATE, 8, 15),
                         now=lambda: et_epoch(TRADING_DATE, 10, 0))
        r.stage("SOURCES", "MISSED_WINDOW")
        r.finish(exit_status="MISSED_WINDOW")
        assert json.loads(r.path.read_text())["exit_status"] == "MISSED_WINDOW"

    def test_an_interrupted_run_leaves_an_incomplete_record_not_silence(self):
        r = RR.RunRecord(run_id="cut", now=lambda: 1.0)
        r.stage("SOURCES", "OK")
        b = json.loads(r.path.read_text())
        assert b["finished_epoch"] is None and b["stage"] == "SOURCES"


class TestNothingWasActivated:
    def test_the_corrected_plist_is_still_not_installed(self):
        installed = pathlib.Path.home().joinpath("Library/LaunchAgents/com.apex.premarket.plist").read_text()
        assert "StandardErrorPath" not in installed

    def test_no_disposable_launchagent_was_left_behind(self):
        import subprocess
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
        assert "com.apex.audit" not in out


# ======================================================= R3: the production runner


class TestTheProductionRunnerWasNotStagedUntilR3:
    def test_the_prepared_plist_invokes_the_long_sleeping_runner(self):
        """THE AMBIGUITY IN MY R2 REPORT, RESOLVED AGAINST ME. Only the audit harness was staged. The prepared
        production plist -> ops/premarket.sh -> scripts/premarket_run.py, which still sleeps."""
        import ast
        plist = pathlib.Path("ops/premarket_repair/com.apex.premarket.plist.NEW").read_text()
        sh = pathlib.Path("ops/premarket_repair/premarket.sh.NEW").read_text()
        assert "ops/premarket.sh" in plist and "scripts/premarket_run.py" in sh
        t = ast.parse(pathlib.Path("scripts/premarket_run.py").read_text())
        sleeps = [n for n in ast.walk(t) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "sleep"]
        assert len(sleeps) == 2, "the production runner still long-sleeps"

    def test_the_staged_entry_point_has_no_executable_sleep(self):
        import ast
        t = ast.parse(pathlib.Path("scripts/premarket_stage.py").read_text())
        sleeps = [n for n in ast.walk(t) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "sleep"]
        assert sleeps == []

    @pytest.mark.parametrize("hh,mm,expect", [(3, 0, "TOO_EARLY"), (8, 15, "ON_TIME"),
                                              (8, 22, "LATE_START"), (10, 0, "MISSED_WINDOW")])
    def test_an_out_of_window_invocation_is_refused_not_mislabelled(self, hh, mm, expect):
        import sys as _s
        _s.path.insert(0, "scripts")
        import pandas as pd, premarket_stage as PS
        now = pd.Timestamp("2026-08-26", tz="America/New_York").normalize() + pd.Timedelta(hours=hh, minutes=mm)
        assert PS.disposition("0815_ET_initial", now)[0] == expect

    def test_the_old_loop_fires_every_stage_early_from_a_coalesced_wake(self):
        """The defect the simulation found, re-enacted: a 02:00 ET start runs 08:15 at 03:00."""
        stages = [(8, 15), (8, 32), (9, 5), (9, 20)]
        t = 2 * 3600
        fired = []
        for h, m in stages:
            target = h * 3600 + m * 60
            wait = target - t
            if wait > 0:
                t += min(wait, 3600)
            fired.append((target, t))
        assert all(actual < target for target, actual in fired), "every stage fires early"
        assert fired[0][1] == 3 * 3600, "the 08:15 stage absorbs at 03:00 ET"
