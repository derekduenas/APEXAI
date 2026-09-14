"""PREMARKET-SEQUENTIAL-AUDIT-001-R5 — production time truth and timezone safety.

Two production defects R4 left standing:
  * PREMARKET_TIME_V1 existed only in tests, and the packet still collapsed data freshness, information cutoff
    and downstream availability into one `as_of_time`;
  * the generated launchd schedule assumed the host tracks US Eastern, verified the assumption at two probe
    instants, and wrote the conclusion in a comment.
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import subprocess

import pandas as pd
import pytest

from apex.audit import call_graph as CG
from apex.frontier import market_time as MT
from apex.frontier import premarket as PM
from apex.frontier import premarket_stages as PS
from apex.frontier import premarket_time as T

REPO = pathlib.Path(__file__).resolve().parents[1]
OPS = REPO / "ops/premarket_repair"
STAGED_CLI = "scripts/premarket_stage.py"

SPRING_FORWARD = "2026-03-08"      # Sunday; the first EDT trading day is the 9th
FALL_BACK = "2026-11-01"           # Sunday; the first EST trading day is the 2nd
HOLIDAY = "2026-11-26"             # Thanksgiving
WEEKEND = "2026-08-29"             # Saturday


def et(date, h, m):
    return pd.Timestamp("%s %02d:%02d" % (date, h, m), tz=MT.MARKET_TZ)


# ======================================================= 5. market time is authoritative
class TestMarketTimeIsAuthoritative:
    def test_the_host_timezone_comes_from_operating_system_evidence(self):
        h = MT.host_timezone()
        assert h["resolved"], h
        assert h["source"] in ("TZ", "/etc/localtime")
        assert "/" in h["name"], "an IANA zone, not an abbreviation: %r" % h["name"]
        assert h["evidence"]

    def test_an_abbreviation_is_reported_unresolved_rather_than_guessed(self, monkeypatch):
        monkeypatch.delenv("TZ", raising=False)
        monkeypatch.setattr(MT.pathlib.Path, "is_symlink", lambda self: False)
        h = MT.host_timezone()
        assert not h["resolved"] and h["name"].startswith("UNRESOLVED_ABBREVIATION")

    @pytest.mark.parametrize("tz,expect_local", [("America/New_York", "08:15"),
                                                 ("America/Los_Angeles", "05:15"),
                                                 ("UTC", "12:15")])
    def test_a_market_target_converts_to_each_host_zone(self, tz, expect_local):
        assert MT.market_instant("2026-08-26", 8, 15).tz_convert(tz).strftime("%H:%M") == expect_local

    @pytest.mark.parametrize("tz,n", [("America/New_York", 1), ("America/Los_Angeles", 1), ("UTC", 2),
                                      ("Asia/Tokyo", 2)])
    def test_a_host_that_does_not_track_the_market_needs_two_triggers(self, tz, n):
        assert len(MT.local_triggers(8, 15, tz, 2026)) == n
        assert MT.offset_is_stable(tz, 2026) == (n == 1)

    def test_the_stage_decision_uses_the_market_instant_not_the_local_hour(self):
        """The load-bearing property. A UTC host's 08:15 ET trigger fires at local 12:15 in summer. Reading the
        LOCAL hour as if it were a market hour gives MISSED_WINDOW; reading the market instant gives ON_TIME."""
        inst = MT.market_instant("2026-08-26", 8, 15)             # the real moment the stage should run
        local = inst.tz_convert("UTC")
        assert local.strftime("%H:%M") == "12:15"
        assert PS.disposition("0815_ET_initial", inst)[0] == "ON_TIME"
        naive_as_if_local_were_market = et("2026-08-26", local.hour, local.minute)
        assert PS.disposition("0815_ET_initial", naive_as_if_local_were_market)[0] == "MISSED_WINDOW", \
            "this is the answer the system would give if it trusted the displayed local hour"

    @pytest.mark.parametrize("date", [SPRING_FORWARD, "2026-03-09", FALL_BACK, "2026-11-02"])
    def test_across_both_daylight_transitions_the_target_stays_0815_market_time(self, date):
        inst = MT.market_instant(date, 8, 15)
        assert inst.strftime("%H:%M") == "08:15"
        assert PS.disposition("0815_ET_initial", inst)[0] == "ON_TIME"

    def test_a_la_host_needs_the_same_local_trigger_on_both_sides_of_a_transition(self):
        before = MT.market_instant("2026-03-06", 8, 15).tz_convert("America/Los_Angeles").strftime("%H:%M")
        after = MT.market_instant("2026-03-09", 8, 15).tz_convert("America/Los_Angeles").strftime("%H:%M")
        assert before == after == "05:15"

    def test_a_utc_host_needs_a_DIFFERENT_local_trigger_on_each_side(self):
        before = MT.market_instant("2026-03-06", 8, 15).tz_convert("UTC").strftime("%H:%M")
        after = MT.market_instant("2026-03-09", 8, 15).tz_convert("UTC").strftime("%H:%M")
        assert (before, after) == ("13:15", "12:15")
        assert set(MT.local_triggers(8, 15, "UTC", 2026)) == {(13, 15), (12, 15)}

    def test_a_holiday_and_a_weekend_are_not_market_sessions(self):
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        from nightly_pull import is_trading_day
        assert not is_trading_day(HOLIDAY) and not is_trading_day(WEEKEND)
        assert MT.next_market_session(WEEKEND) == "2026-08-31"
        assert MT.next_market_session(HOLIDAY) == "2026-11-27"


class TestTheTimezoneBinding:
    def test_a_matching_host_is_bound(self):
        h = MT.host_timezone()
        b = MT.binding_body(h["name"], PS.STAGE_SCHEDULE, generated_for_year=2026)
        assert MT.verify_binding(b, h)["status"] == "BOUND"

    def test_a_host_moved_after_generation_is_REFUSED_by_name(self):
        h = MT.host_timezone()
        b = MT.binding_body("Asia/Tokyo", PS.STAGE_SCHEDULE, generated_for_year=2026)
        with pytest.raises(MT.TimezoneConfigurationMismatch, match="TIMEZONE_CONFIGURATION_MISMATCH"):
            MT.verify_binding(b, h)

    def test_an_unresolvable_host_is_refused_rather_than_assumed_to_match(self):
        b = MT.binding_body("America/Los_Angeles", PS.STAGE_SCHEDULE, generated_for_year=2026)
        with pytest.raises(MT.TimezoneConfigurationMismatch):
            MT.verify_binding(b, {"name": "UNRESOLVED_ABBREVIATION:PDT", "resolved": False, "evidence": "x"})

    def test_no_binding_is_UNBOUND_and_says_why_that_is_still_safe(self):
        out = MT.verify_binding(None, MT.host_timezone())
        assert out["status"] == "UNBOUND" and "market time" in out["note"]

    def test_the_generated_binding_matches_the_host_and_the_schedule(self):
        b = json.loads((OPS / MT.BINDING_NAME).read_text())
        assert b["host_tz"] == MT.host_timezone()["name"]
        assert set(b["triggers"]) == {s for s, _h, _m in PS.STAGE_SCHEDULE} | {"reconcile"}

    def test_the_cli_refuses_a_mismatched_binding(self, tmp_path):
        import os
        bad = tmp_path / "binding.json"
        bad.write_text(json.dumps(MT.binding_body("Asia/Tokyo", PS.STAGE_SCHEDULE, generated_for_year=2026)))
        env = dict(os.environ, APEX_PREMARKET_ROOT=str(tmp_path / "root"),
                   APEX_PREMARKET_TZ_BINDING=str(bad), PYTHONPATH=str(REPO))
        r = subprocess.run([os.sys.executable, STAGED_CLI, "--stage", "0815_ET_initial"],
                           cwd=str(REPO), env=env, capture_output=True, text=True, timeout=300)
        assert r.returncode == 5, r.stdout + r.stderr
        assert "TIMEZONE_CONFIGURATION_MISMATCH" in r.stdout


# ======================================================= dispositions, in market time
class TestWindowDecisionsUnderCoalescingAndLateness:
    @pytest.mark.parametrize("hh,mm,expect", [(2, 0, "TOO_EARLY"), (7, 15, "TOO_EARLY"), (8, 15, "ON_TIME"),
                                              (8, 20, "LATE_START"), (8, 25, "LATE_START"),
                                              (8, 26, "MISSED_WINDOW"), (9, 30, "MISSED_WINDOW")])
    def test_every_arrival_gets_the_market_time_answer(self, hh, mm, expect):
        assert PS.disposition("0815_ET_initial", et("2026-08-26", hh, mm))[0] == expect

    def test_a_coalesced_older_event_arriving_hours_late_is_MISSED_not_absorbed(self):
        d, delta = PS.disposition("0815_ET_initial", et("2026-08-26", 11, 0))
        assert d == "MISSED_WINDOW" and delta > 9000

    def test_a_coalesced_event_arriving_hours_early_is_TOO_EARLY_not_absorbed(self):
        d, delta = PS.disposition("0815_ET_initial", et("2026-08-26", 2, 0))
        assert d == "TOO_EARLY" and delta < -22000


# ======================================================= 3. the production time model
class TestTheProductionTimeModel:
    def test_the_packet_schema_is_versioned_and_legacy_bytes_keep_their_meaning(self):
        legacy = {"as_of_time": "2026-08-26 13:25:00+00:00"}
        assert PM.packet_schema(legacy) == PM.PACKET_SCHEMA_V1
        i = PM.interpret(legacy)
        assert i["source_freshness"] == "UNRECONSTRUCTIBLE"
        assert i["information_cutoff"] == "UNRECONSTRUCTIBLE"
        assert i["packet_known_from"] == legacy["as_of_time"], "V1 availability IS reconstructible"

    def test_as_of_time_carries_a_machine_readable_definition_in_v2(self):
        s = PM.AS_OF_TIME_SEMANTICS_V2
        assert s["means"] == "PACKET_SEALED_AT" and s["equals"] == "time.packet_sealed_at"
        assert "SOURCE_FRESHNESS" in s["does_not_mean"] and "INFORMATION_CUTOFF" in s["does_not_mean"]
        assert s["information_cutoff_field"] != s["availability_field"]

    def test_known_from_defaults_to_receipt_and_records_that_basis(self):
        o = T.source_observation(receipt_time=10.0)
        assert o["source_known_from"] == 10.0 and o["availability_basis"] == T.BASIS_RECEIPT

    def test_an_explicit_availability_is_recorded_as_provider_stated(self):
        o = T.source_observation(receipt_time=10.0, known_from=4.0)
        assert o["source_known_from"] == 4.0 and o["availability_basis"] == T.BASIS_EXPLICIT

    def test_freshness_comes_only_from_source_times_and_never_from_the_seal(self):
        obs = [T.source_observation(source_kind="S", receipt_time=100.0)]
        early = T.packet_times(collection_started_at=0.0, observations=obs, created_at=100.0, sealed_at=200.0)
        late = T.packet_times(collection_started_at=0.0, observations=obs, created_at=100.0, sealed_at=9000.0)
        assert early["per_source_freshness_s"] == late["per_source_freshness_s"]
        assert early["packet_data_cutoff"] == late["packet_data_cutoff"] == 100.0

    def test_sealing_later_does_not_make_a_source_fresher(self):
        obs = [T.source_observation(source_kind="S", receipt_time=100.0)]
        a = T.packet_times(collection_started_at=0.0, observations=obs, created_at=100.0, sealed_at=200.0,
                           declared_cutoff=150.0)
        assert a["per_source_freshness_s"]["S"] == 50.0

    def test_packet_known_from_is_never_before_the_seal(self):
        with pytest.raises(T.PremarketTimeRefused, match="PACKET_KNOWN_FROM_BEFORE_SEAL"):
            T.packet_times(collection_started_at=0.0, observations=[], created_at=1.0, sealed_at=200.0,
                           known_from=100.0)

    def test_an_accepted_input_after_the_declared_cutoff_refuses(self):
        obs = [T.source_observation(source_kind="S", receipt_time=500.0)]
        with pytest.raises(T.PremarketTimeRefused, match="ACCEPTED_INPUT_AFTER_DECLARED_CUTOFF"):
            T.packet_times(collection_started_at=0.0, observations=obs, created_at=1.0, sealed_at=600.0,
                           declared_cutoff=100.0)

    def test_a_provider_declared_future_availability_is_recognised_as_future(self):
        future = T.source_observation(source_kind="S", receipt_time=10.0, known_from=900.0)
        latency = T.source_observation(source_kind="S", request_time=10.0, receipt_time=13.0)
        assert T.provider_declared_future(future, as_of=100.0) is True
        assert T.provider_declared_future(latency, as_of=10.0) is False, \
            "a receipt three seconds after the stage started is latency, not a claim about the future"

    def test_unavailable_times_stay_unavailable(self):
        o = T.source_observation(source_kind="S")
        assert o["source_known_from"] == T.UNAVAILABLE and o["availability_basis"] == T.BASIS_UNAVAILABLE
        t = T.packet_times(collection_started_at=T.UNAVAILABLE, observations=[o], created_at=1.0, sealed_at=2.0)
        assert t["packet_data_cutoff"] == T.UNAVAILABLE

    def test_a_probe_cannot_make_a_silent_source_look_fresh(self):
        """A measured absence is information, but it is not NEWS. Counting probes as content makes every source
        perfectly fresh forever, which is a freshness number that can never indicate staleness."""
        obs = [T.source_observation(source_kind="SEC", known_from=100.0, carries_content=True),
               T.source_observation(source_kind="SEC", receipt_time=1000.0, carries_content=False)]
        t = T.packet_times(collection_started_at=0.0, observations=obs, created_at=1000.0, sealed_at=1100.0,
                           declared_cutoff=1000.0)
        assert t["per_source_known_from"]["SEC"] == 100.0
        assert t["per_source_last_probe"]["SEC"] == 1000.0
        assert t["per_source_freshness_s"]["SEC"] == 900.0

    def test_a_source_with_no_content_at_all_reports_no_freshness_rather_than_zero(self):
        obs = [T.source_observation(source_kind="DEAD", receipt_time=1000.0, carries_content=False)]
        t = T.packet_times(collection_started_at=0.0, observations=obs, created_at=1000.0, sealed_at=1100.0,
                           declared_cutoff=1000.0)
        assert t["per_source_freshness_s"]["DEAD"] == T.UNAVAILABLE_NO_CONTENT

    def test_the_seal_binds_the_time_block(self, tmp_path, monkeypatch):
        monkeypatch.setattr(PM, "PACKETS", tmp_path)
        base = {"schema": PM.PACKET_SCHEMA_V2, "market_date": "2026-08-26",
                "as_of_time": "2026-08-26 13:25:00+00:00", "source_observations": [],
                "time": T.collection_times(collection_started_at=1.0, observations=[], declared_cutoff=2.0,
                                           created_at=3.0)}
        a = PM.seal(dict(base))
        b = dict(base); b["time"] = dict(base["time"], packet_collection_started_at=999.0)
        assert PM.seal(b)["packet_sha256"] != a["packet_sha256"], \
            "a change inside the time block must change the digest"

    def test_the_stage_time_block_names_every_declared_instant(self):
        required = {"market_date", "stage", "target_instant", "window_opens", "window_closes",
                    "process_started_at", "capture_started_at", "capture_finished_at",
                    "normalization_finished_at", "absorption_finished_at", "disposition", "lateness_s",
                    "code_identity", "config_identity"}
        got = PS.stage_time_block(stage="0815_ET_initial", now_et=et("2026-08-26", 8, 15), disposition_="ON_TIME",
                                  delta=0.0, process_started_at=1.0, capture_started_at=2.0,
                                  capture_finished_at=3.0, normalization_finished_at=4.0,
                                  absorption_finished_at=5.0)
        assert required <= set(got), required - set(got)
        assert got["config_identity"]["config_digest"]


class TestARacerCannotPoisonTheWinner:
    """R5 concurrency defect. RECONCILED_DUPLICATE was counted as a terminal outcome, so a LOSING racer's own
    marker made the WINNER conclude the stage was already done and abandon it. Five concurrent processes produced
    ZERO absorptions -- the stage was lost, which is the exact failure this whole audit exists to prevent. R4's
    version of this test passed, but on TIMING: the winner happened to finish before the losers wrote."""

    @pytest.fixture()
    def j(self, tmp_path):
        from apex.frontier import premarket_journal as PJ
        return PJ.open_journal("2026-08-26", root=tmp_path)

    def test_a_duplicate_marker_is_not_an_outcome(self, j):
        j.append(stage="s", state="RECONCILED_DUPLICATE")
        assert j.stage_state("s") == "RECONCILED_DUPLICATE"
        assert j.stage_outcome("s") == "PENDING", "a note about a race is not an outcome for the stage"

    def test_a_duplicate_marker_after_completion_does_not_un_complete_a_stage(self, j):
        j.append(stage="s", state="COMPLETED", packet_blob="x")
        j.append(stage="s", state="RECONCILED_DUPLICATE")
        assert j.stage_outcome("s") == "COMPLETED", "reading the LAST state would re-run a finished stage"

    @pytest.mark.parametrize("state", ["COMPLETED", "TOO_EARLY", "MISSED_WINDOW", "SOURCE_UNAVAILABLE",
                                       "REFUSED_INPUT", "FAILED"])
    def test_every_real_outcome_is_decisive(self, j, state):
        j.append(stage="s", state=state)
        assert j.stage_outcome("s") == state

    def test_a_claim_is_not_handed_over_because_a_racer_left_a_marker(self, j):
        from apex.frontier import premarket_journal as PJ
        j.claim("s", holder="winner")
        (j.claims / "s.claim").write_text(json.dumps({"pid": 2 ** 22, "at": 0}))
        j.append(stage="s", state="RECONCILED_DUPLICATE")
        assert j.claim("s", holder="recovery")["status"] == "TAKEOVER", \
            "a dead holder plus a racer's marker must still be recoverable"
        assert PJ.DECISIVE == ("COMPLETED", "TOO_EARLY", "MISSED_WINDOW", "SOURCE_UNAVAILABLE",
                               "REFUSED_INPUT", "FAILED")


class TestARehearsalIsNotAnOutcome:
    def test_a_dry_run_state_exists_and_is_not_decisive(self):
        from apex.frontier import premarket_journal as PJ
        assert PJ.DRY_RUN in PJ.STATES
        assert PJ.DRY_RUN not in PJ.DECISIVE and PJ.DRY_RUN not in PJ.TERMINAL

    def test_a_dry_run_does_not_make_the_real_stage_look_like_a_duplicate(self, tmp_path):
        """A `--dry-run` at 08:15 that recorded a decisive state would make the real 08:15 stage a duplicate and
        the morning would lose the stage -- the racer-poisoning defect from a different direction."""
        from apex.frontier import premarket_journal as PJ
        j = PJ.open_journal("2026-08-26", root=tmp_path)
        j.append(stage="0815_ET_initial", state=PJ.DRY_RUN, dry_run=True)
        assert j.stage_outcome("0815_ET_initial") == "PENDING"

    def test_verify_works_on_a_host_that_would_be_refused(self, tmp_path):
        """Refusing to REPORT on a misconfigured host is how a misconfiguration stays invisible."""
        import os
        bad = tmp_path / "binding.json"
        bad.write_text(json.dumps(MT.binding_body("Asia/Tokyo", PS.STAGE_SCHEDULE, generated_for_year=2026)))
        env = dict(os.environ, APEX_PREMARKET_ROOT=str(tmp_path / "root"),
                   APEX_PREMARKET_TZ_BINDING=str(bad), PYTHONPATH=str(REPO))
        r = subprocess.run([os.sys.executable, STAGED_CLI, "--stage", "verify"], cwd=str(REPO), env=env,
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "CHAIN_INTACT" in r.stdout


# ======================================================= 8. the prepared production call graph
class TestPreparedProductionPath:
    def test_no_prepared_path_reaches_the_legacy_runner_the_harness_or_a_stage_sleep(self):
        rep = CG.report(STAGED_CLI, repo=str(REPO))
        assert rep["reaches_legacy_runner"] is False
        for banned in ("apex/audit/fake_morning.py", "apex/audit/premarket_fixture.py",
                       "apex/audit/legacy_oracle.py", "scripts/premarket_synthetic_morning.py",
                       "scripts/premarket_failure_flights.py"):
            assert banned not in rep["modules"], "production reaches the audit harness: %s" % banned
        assert {(s["module"], s["call"]) for s in rep["sleep_sites"]} == {
            ("apex/data/sharadar_api.py", "time.sleep"), ("apex/intraday/eodhd.py", "time.sleep")}

    def test_no_production_premarket_module_builds_a_wall_clock_time_by_adding_elapsed_time(self):
        """`x.normalize() + Timedelta(hours=h)` is elapsed time from local midnight, which is NOT a wall-clock
        hour on a 23- or 25-hour day. Asserted over the premarket production modules as a closure, so the two
        instances found in R5 cannot come back and a third cannot be added.

        The same construction still exists at nine other sites in the repo (shadow_paper, mission_control,
        closing_run, arm_session_anchor_evidence, and the retained legacy runner). Those are outside Checkpoint
        1A and are named here rather than silently fixed or silently ignored."""
        production = ["apex/frontier/premarket_stages.py", "apex/frontier/premarket.py",
                      "apex/frontier/premarket_journal.py", "apex/frontier/premarket_runtime.py",
                      "apex/frontier/premarket_time.py", "apex/frontier/market_time.py", STAGED_CLI]
        offenders = []
        for f in production:
            for n in ast.walk(ast.parse((REPO / f).read_text())):
                if (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add)
                        and isinstance(n.left, ast.Call)
                        and getattr(n.left.func, "attr", None) == "normalize"
                        and isinstance(n.right, ast.Call)
                        and getattr(n.right.func, "attr", None) == "Timedelta"):
                    offenders.append("%s:%d" % (f, n.lineno))
        assert offenders == [], offenders

    def test_the_legacy_oracle_still_carries_the_defect_it_is_the_oracle_for(self):
        src = (REPO / "scripts/premarket_run.py").read_text()
        assert "normalize() + pd.Timedelta(hours=h, minutes=m)" in src, \
            "the oracle must keep the legacy construction, including its latent DST defect"

    def test_production_reaches_the_versioned_time_schema(self):
        rep = CG.report(STAGED_CLI, repo=str(REPO))
        for required in ("apex/frontier/premarket_time.py", "apex/frontier/market_time.py",
                         "apex/frontier/premarket_journal.py", "apex/frontier/premarket.py"):
            assert required in rep["modules"], required

    def test_every_prepared_plist_carries_every_local_trigger_the_host_needs(self):
        tz = MT.host_timezone()["name"]
        stages = list(PS.STAGE_SCHEDULE) + [("reconcile", 9, 40)]
        for stage, h, m in stages:
            body = (OPS / ("com.apex.premarket.%s.plist.NEW" % stage)).read_text()
            for lh, lm in MT.local_triggers(h, m, tz, 2026):
                assert ("<key>Hour</key><integer>%d</integer><key>Minute</key><integer>%d</integer>"
                        % (lh, lm)) in body, (stage, lh, lm)
            assert "America/New_York" in body, "the plist must say which market target it implements"

    def test_the_prepared_artifacts_have_not_drifted_from_schedule_or_host_timezone(self):
        import os
        r = subprocess.run([os.sys.executable, "ops/premarket_repair/generate.py", "--check"],
                           cwd=str(REPO), capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_install_places_the_binding_and_rollback_removes_it(self):
        assert "timezone_binding.json" in (OPS / "install.sh").read_text()
        assert "rm -f \"$HOME/apex-equities/ops/timezone_binding.json\"" in (OPS / "rollback.sh").read_text()


# ======================================================= nothing was activated
class TestNothingWasActivated:
    INSTALLED = {"plist": "6a22ee77ee8e4af2994889826c13bf42a850c1f3db944f94de3a35461a05a0f2",
                 "shell": "3508fe93467f7eb96c459389e94604912f71775a2764b5406d6691da3821f2b7"}

    def test_the_installed_production_files_are_byte_for_byte_unchanged(self):
        plist = pathlib.Path.home() / "Library/LaunchAgents/com.apex.premarket.plist"
        shell = pathlib.Path.home() / "apex-equities/ops/premarket.sh"
        assert hashlib.sha256(plist.read_bytes()).hexdigest() == self.INSTALLED["plist"]
        assert hashlib.sha256(shell.read_bytes()).hexdigest() == self.INSTALLED["shell"]

    def test_no_binding_was_installed_into_the_live_repo(self):
        assert not (pathlib.Path.home() / "apex-equities/ops/timezone_binding.json").exists()

    def test_no_per_stage_or_disposable_agent_is_loaded(self):
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
        assert "com.apex.audit" not in out
        for stage, _h, _m in PS.STAGE_SCHEDULE:
            assert "com.apex.premarket.%s" % stage not in out
