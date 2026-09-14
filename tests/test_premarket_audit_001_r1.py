"""PREMARKET-SEQUENTIAL-AUDIT-001-R1 — checkpoint 1A: producer reliability and time semantics."""
from __future__ import annotations

import json
import pathlib
import time

import pytest

from apex.frontier import run_record as RR
from apex.frontier.premarket_time import (LAWS, SCHEMA, UNAVAILABLE, PremarketTimeRefused, data_cutoff,
                                          freshness_s, packet_times, refuse_future_source, source_observation)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(RR, "RUNS", tmp_path / "runs")


class TestTheTimeModel:
    def test_seal_time_availability_is_CONSERVATIVE_not_unsafe(self):
        """CORRECTION RECORDED. The audit first called seal-time known_from unsafe. It is conservative: a sealed
        packet genuinely cannot be known before it is sealed. The defect was that ONE field also implied source
        freshness."""
        o = source_observation(event_time=100.0, receipt_time=120.0)
        t = packet_times(collection_started_at=110.0, observations=[o], created_at=150.0, sealed_at=160.0)
        assert t["packet_known_from"] == t["packet_sealed_at"] == 160.0
        assert t["packet_data_cutoff"] == 120.0, "the cutoff derives from sources, not the seal clock"
        assert freshness_s(o, t["packet_data_cutoff"]) == 0.0

    def test_source_freshness_is_measured_from_the_cutoff_not_the_seal(self):
        a = source_observation(receipt_time=100.0)
        b = source_observation(receipt_time=140.0)
        t = packet_times(collection_started_at=90.0, observations=[a, b], created_at=150.0, sealed_at=160.0)
        assert t["packet_data_cutoff"] == 140.0
        assert freshness_s(a, t["packet_data_cutoff"]) == 40.0
        assert freshness_s(b, t["packet_data_cutoff"]) == 0.0

    def test_known_from_before_the_seal_is_refused(self):
        with pytest.raises(PremarketTimeRefused, match="PACKET_KNOWN_FROM_BEFORE_SEAL"):
            packet_times(collection_started_at=1.0, observations=[], created_at=2.0,
                         sealed_at=160.0, known_from=100.0)

    def test_a_cutoff_after_the_seal_is_refused(self):
        late = source_observation(receipt_time=200.0)
        with pytest.raises(PremarketTimeRefused, match="DATA_CUTOFF_AFTER_SEAL"):
            packet_times(collection_started_at=1.0, observations=[late], created_at=2.0, sealed_at=160.0)

    def test_a_source_known_after_the_cutoff_is_refused_not_clipped(self):
        with pytest.raises(PremarketTimeRefused, match="SOURCE_KNOWN_AFTER_CUTOFF"):
            refuse_future_source(source_observation(receipt_time=300.0), 200.0)

    def test_unavailable_timestamps_stay_unavailable(self):
        """R5 narrowed this from 'every field' to 'every TIMESTAMP field'. A source observation now also carries
        its availability basis, its normalization verdict and whether it carries content -- which are facts about
        the observation, not instants. The property under test is unchanged: no absent time is ever defaulted to
        a clock reading."""
        o = source_observation()
        times = [k for k in o if k.endswith("_time") or k == "source_known_from"]
        assert times, "the timestamp fields must still exist"
        assert all(o[k] == UNAVAILABLE for k in times), {k: o[k] for k in times}
        assert data_cutoff([o]) == UNAVAILABLE
        assert freshness_s(o, 100.0) == UNAVAILABLE

    def test_known_from_defaults_to_receipt_never_to_the_event_time(self):
        o = source_observation(event_time=100.0, receipt_time=120.0)
        assert o["source_known_from"] == 120.0

    def test_legacy_packets_are_labelled_not_reinterpreted(self):
        t = packet_times(collection_started_at=1.0, observations=[], created_at=2.0, sealed_at=3.0)
        assert "SOURCE FRESHNESS is NOT" in t["legacy_note"]
        assert t["schema"] == SCHEMA and len(LAWS) == 7


class TestRunAccounting:
    def test_a_run_that_fails_before_the_packet_still_leaves_a_record(self):
        r = RR.RunRecord(run_id="r1", scheduled_epoch=10.0)
        r.stage("SOURCES", "FAILED", why="provider timeout")
        r.fail("SOURCES", "provider timeout")
        body = json.loads((RR.RUNS / "r1.json").read_text())
        assert body["exit_status"] == "FAILED" and body["failure_stage"] == "SOURCES"
        assert body["started_epoch"] and body["finished_epoch"]

    def test_a_run_record_is_never_overwritten(self):
        RR.RunRecord(run_id="dup")
        with pytest.raises(FileExistsError, match="never overwritten"):
            RR.RunRecord(run_id="dup")

    def test_a_successful_run_records_every_stage_and_the_output_identity(self):
        r = RR.RunRecord(run_id="ok")
        for s in ("SOURCES", "AI", "PACKET", "SEALED"):
            r.stage(s, "OK")
        r.finish(output_identity="sha:abc")
        b = json.loads((RR.RUNS / "ok.json").read_text())
        assert set(b["stages"]) == {"SOURCES", "AI", "PACKET", "SEALED"}
        assert b["exit_status"] == "OK" and b["output_identity"] == "sha:abc"

    def test_a_second_invocation_is_locked_out_not_allowed_to_overwrite(self):
        lock = RR.RunLock(now=lambda: 1000.0)
        lock.acquire("first")
        with pytest.raises(RR.LockHeld, match="ACTIVE"):
            RR.RunLock(now=lambda: 1000.0).acquire("second")
        lock.release()
        RR.RunLock(now=lambda: 1000.0).acquire("third")

    def test_a_stale_lock_is_DIAGNOSED_not_silently_stolen(self):
        RR.RunLock(now=lambda: 1000.0).acquire("old")
        with pytest.raises(RR.LockHeld, match="STALE"):
            RR.RunLock(max_age_s=60.0, now=lambda: 99999.0).acquire("new")


class TestTheSchedulerArtifacts:
    D = pathlib.Path("ops/premarket_repair")

    def test_the_prior_state_is_preserved_byte_exact_for_rollback(self):
        prior = (self.D / "com.apex.premarket.plist.PRIOR").read_bytes()
        installed = pathlib.Path.home().joinpath("Library/LaunchAgents/com.apex.premarket.plist").read_bytes()
        assert prior == installed, "rollback must restore exactly what is installed today"

    def test_the_corrected_plist_adds_the_missing_failure_surface(self):
        """R4 replaced the single prepared plist with one per stage. The property under test is unchanged --
        a failure before the script's own log redirect must be visible -- and now has to hold for every one."""
        old = (self.D / "com.apex.premarket.plist.PRIOR").read_text()
        assert "StandardErrorPath" not in old and "StandardOutPath" not in old
        news = sorted(self.D.glob("com.apex.premarket.*.plist.NEW"))
        assert len(news) == 6, [p.name for p in news]
        for p in news:
            body = p.read_text()
            assert "StandardErrorPath" in body and "StandardOutPath" in body, p.name

    def test_the_corrected_script_redirects_BEFORE_reading_the_secret(self):
        new = (self.D / "premarket.sh.NEW").read_text().splitlines()
        redirect = next(i for i, l in enumerate(new) if l.startswith("exec >>"))
        secret = next(i for i, l in enumerate(new) if "find-generic-password" in l)
        assert redirect < secret, "the log must be open before anything can fail"

    def test_the_prior_script_had_it_the_other_way_round(self):
        old = (self.D / "premarket.sh.PRIOR").read_text().splitlines()
        redirect = next(i for i, l in enumerate(old) if l.startswith("exec >>"))
        secret = next(i for i, l in enumerate(old) if "find-generic-password" in l)
        assert secret < redirect, "the defect: a secret failure exited with no log line"

    def test_install_and_rollback_both_exist_and_are_executable(self):
        import os
        for n in ("install.sh", "rollback.sh", "status.sh", "once.sh"):
            assert os.access(self.D / n, os.X_OK), n

    def test_the_audit_did_not_activate_anything(self):
        """The installed plist must still be the PRIOR one."""
        installed = pathlib.Path.home().joinpath("Library/LaunchAgents/com.apex.premarket.plist").read_text()
        assert "StandardErrorPath" not in installed, "the corrected plist must NOT be installed by this brick"
