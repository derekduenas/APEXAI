"""ORCHESTRATOR-OOM-001: assemble the read-only diagnostic evidence."""
import json, subprocess, os

def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout.strip()

LEDGER = "/apex-data/runtime/results/ops/orchestrator.jsonl"
doc = {
 "kind": "orchestrator_oom_001_diagnosis",
 "version": "ORCHESTRATOR_OOM_001_V1",
 "utc": sh("date", "-u", "+%Y-%m-%dT%H:%M:%SZ"),
 "authorization": "bounded read-only diagnosis; no service behaviour changed, "
                  "nothing restarted or stopped, no limit raised, nothing deployed",

 # ---------------------------------------------------------------- 1
 "deployed_release": {
   "current_symlink": sh("readlink", "-f", "/opt/apex/current"),
   "deployed_utc": "2026-08-30T15:16:26Z",
   "commit": "5eff1cf5e00f21b02c537f25bcd74b1c1d317546",
   "unchanged_since_deploy": True,
   "entry_point": "/opt/apex/current/scripts/apex_orchestrator.py",
   "entry_point_sha256": sh("sha256sum", "/opt/apex/current/scripts/apex_orchestrator.py").split()[0],
   "entry_point_matches_canonical_repo": True,
   "chain_ledger_sha256": sh("sha256sum", "/opt/apex/current/apex/governance/chain_ledger.py").split()[0],
   "ops_orchestrator_sha256": sh("sha256sum", "/opt/apex/current/apex/ops/orchestrator.py").split()[0]},
 "unit": {
   "fragment": "/etc/systemd/system/apex-orchestrator.service",
   "drop_ins": ["/etc/systemd/system/apex-orchestrator.service.d/runtime.conf",
                "/etc/systemd/system/apex-orchestrator.service.d/slice.conf"],
   "slice": "apex-market.slice", "MemoryMax": "512M (536870912 bytes)",
   "Restart": "always", "RestartSec": "30s", "Type": "simple",
   "WorkingDirectory": "/apex-data/runtime"},

 # ---------------------------------------------------------------- 2
 "current_oom_loop": {
   "occurring_now": True,
   "evidence": "Result=oom-kill, ExecMainStatus=9/KILL, sampled repeatedly",
   "cumulative_restart_counter": 1860,
   "counter_is_cumulative_not_a_rate": True,
   "first_timestamped_oom_event": "2026-09-06T04:51:05Z",
   "latest_timestamped_oom_event_at_capture": "2026-09-06T21:05:15Z",
   "observed_cycle_s": 31,
   "cycle_derivation": "process is SIGKILLed 1-2 s after start; RestartSec=30",
   "observed_rate_per_hour": 116,
   "journal_retention": {
     "orchestrator_entries_retained_from": "2026-08-26T00:37:42Z",
     "retained_days": 11,
     "disk_usage": sh("sudo", "-n", "journalctl", "--disk-usage"),
     "oom_events_before_2026_09_06": 0,
     "entries_per_day": {"2026-08-26": 42, "2026-08-27": 28, "2026-08-28": 9,
                         "2026-08-29": 5, "2026-08-30": 5, "2026-08-31": 12,
                         "2026-09-01": 9, "2026-09-02": 13, "2026-09-03": 30,
                         "2026-09-04": 30, "2026-09-06": 11037}},
   "correction_of_the_earlier_report":
     "the loop is ~16 h old, not 7+ days. The journal retains 11 days of this "
     "unit and contains ZERO oom-kill events before 2026-09-06T04:51:05Z, so "
     "the shorter duration is a measurement, not a retention limit. The earlier "
     "'~114 kills/hour' rate is confirmed (116 observed); the 'for 7+ days' "
     "duration is not.",
   "loop_is_not_consuming_disk": {
     "ledger_mtime": "2026-09-06T04:50:03Z", "frozen": True,
     "reason": "the process dies BEFORE its append completes",
     "filesystem": sh("df", "-h", "/apex-data").splitlines()[-1]}},

 # ---------------------------------------------------------------- 3/4
 "root_cause": {
   "summary": "an unbounded per-tick list inflated one ledger record past the "
              "chain primitive's fixed 256 KiB tail window, which forces that "
              "primitive onto a whole-file read of a 438 MB ledger, which "
              "exceeds the 512 MiB unit cap on every start",
   "stage_1_generator": {
     "file": "scripts/apex_orchestrator.py", "function": "tick", "lines": "145-158",
     "defect": "MAX_RECOVERY_ATTEMPTS guards only the FIRST branch. The elif "
               "branch for externally supervised services appends one "
               "DEFERRED_TO_SUPERVISOR entry per tick with no cap.",
     "state_reset": "state['attempts'] is cleared only when the PHASE changes; "
                    "the phase stayed IDLE across the weekend",
     "measured": {"incident": "missed_start / btc-paper / phase IDLE",
                  "recovery_attempts_entries": 1907,
                  "distinct_timestamps": 1907,
                  "distinct_outcomes": ["DEFERRED_TO_SUPERVISOR"],
                  "bytes_per_attempt": 135,
                  "first_attempt_utc": "2026-09-04T21:00:18.825962+00:00",
                  "last_attempt_utc": "2026-09-06T04:50:03.040697+00:00",
                  "span_hours": 31.83,
                  "ticks_expected_in_span": 1910,
                  "one_entry_per_60s_tick": True},
     "amplification": "the whole incident, including its entire attempt "
                      "history, is re-serialised into EVERY tick record"},
   "stage_2_amplifier": {
     "file": "apex/governance/chain_ledger.py",
     "function": "_chain_append_locked",
     "fast_path": "seek(size-262144) and parse the last entry_hash -- O(1)",
     "defect": "when no entry_hash is found in that fixed window it falls back "
               "to log_path.read_text() over the ENTIRE file",
     "why_the_window_now_always_fails": {
       "ledger_size_bytes": 438867453,
       "final_record_bytes": 262275,
       "tail_window_bytes": 262144,
       "record_exceeds_window_by": 131,
       "consequence": "the window can never contain a complete record; the "
                      "single partial line is then discarded by the "
                      "'lines = lines[1:]' cut-guard, leaving zero candidates"},
     "measured_contained_read_only_reproduction": {
       "method": "the prev-hash lookup alone, run in its own transient unit; "
                 "read-only, appends nothing, starts no service",
       "at_512M_cap": {"result": "oom-kill", "status": "9/KILL",
                       "MemoryPeak_bytes": 536870912,
                       "rss_before_the_full_read_mib": 14.0,
                       "matches_production_signature": True},
       "at_2G_cap": {"result": "success",
                     "rss_after_read_text_mib": 847.8,
                     "rss_after_splitlines_mib": 1267.0,
                     "lines": 11804, "chars": 438867453},
       "requirement_vs_cap": "1267 MiB needed against a 512 MiB cap (2.5x over)"},
     "memory_attributed_to": "the orchestrator's own cgroup, in the read call; "
                             "not startup imports (14 MiB at that point), not a "
                             "child process, and not overlapping work"},
   "why_it_started_at_04_51": "the last successful append was 04:50:03; that "
                              "record was the first to exceed the tail window, "
                              "so the next tick took the fallback and died",
   "self_sustaining": "the loop no longer depends on in-memory state, which is "
                      "empty after each restart. The oversized final record in "
                      "the FILE is enough to reproduce it on every start."},

 # ---------------------------------------------------------------- 5
 "useful_work_health": {
   "systemd_reports": "activating / auto-restart (sampled 8 times over 32 s; "
                      "one sample showed deactivating). It never showed "
                      "'active' during observation.",
   "masking_risk": "'systemctl is-active' returns activating, whose exit status "
                   "is nonzero, so a status-code check is NOT fooled. A check "
                   "that substring-matches 'active' in the text IS fooled, "
                   "because 'activating' and 'deactivating' both contain it.",
   "honest_signal": "the heartbeat, which records WORK rather than presence",
   "heartbeat": {"path": "/apex-data/core/heartbeats/orchestrator.json",
                 "last_work_utc": "2026-09-06T04:50:03.179979+00:00",
                 "last_work_item": "tick IDLE", "work_completed": 5661,
                 "stale_for_at_capture": "16:21:16",
                 "pid_recorded": 737247,
                 "process_started_utc": "2026-09-02T06:19:36Z",
                 "last_error": None,
                 "note": "the heartbeat is never updated because beat.work() "
                         "runs only AFTER tick() returns, and tick() dies "
                         "inside chain_append"},
   "evidence_of_successful_work": "5661 completed ticks up to 04:50:03Z; none since",
   "gap": "no orchestrator work has completed for over 16 hours"},

 # ---------------------------------------------------------------- 3 (deps)
 "commissioning_impact": {
   "what_the_service_does": "every 60 s it classifies the session phase, "
                            "reconciles the expected roster against observed "
                            "processes, starts what it owns, verifies FIRST "
                            "WORK rather than liveness, and escalates "
                            "SESSION_MISSED_START",
   "reads": ["the exchange calendar via apex.ops.orchestrator.phase_at",
             "process liveness via pgrep",
             "per-service first-work evidence",
             "the tail of its own hash-chained ledger"],
   "writes": ["results/ops/orchestrator.jsonl (hash-chained)",
              "/apex-data/core/heartbeats/orchestrator.json"],
   "launches": "services it supervises directly (equity-fabric, options-paper); "
               "btc-paper and edgeforge-observatory are systemd-supervised and "
               "it only NOTICES those",
   "dependents_found_in_repo": ["scripts/pulse007_incident.py",
                                "docs/ORGANISM_AUDIT_2026-08-29.md"],
   "parallax_commissioning": "imports only session_bounds, a pure calendar "
                             "function; unaffected by the daemon being down",
   "capital_risk": "none. decision_power is NONE_OPERATIONAL; the service "
                   "never places an order and touches no trading rule",
   "sessions_missed_so_far": 0,
   "calendar": {"2026-09-04": "trading day (loop had not started)",
                "2026-09-05": "not a trading day",
                "2026-09-06": "not a trading day",
                "2026-09-07": "not a trading day",
                "2026-09-08": "TRADING DAY -- the operational deadline"},
   "consequence_if_unrepaired": "from 2026-09-08 no missed session start would "
                                "be noticed or escalated, and the services the "
                                "orchestrator itself starts would not be started",
   "other_services": "unaffected; only apex-orchestrator.service reports "
                     "Result=oom-kill. Several heartbeats are current."},

 "adjacent_observations_not_in_scope": [
   {"id": "ORCH-DUP-DEFS",
    "detail": "apex/ops/orchestrator.py defines session_bounds, phase_at, "
              "ArmCheck, evaluate_arm, StartAttempt, missed_start_verdict and "
              "reconcile_expected TWICE (first near lines 100-279, again near "
              "326-487). Python keeps the later definition, so the earlier ones "
              "are dead code. Not the cause of this loop; a latent hazard.",
    "action": "reported only"},
   {"id": "GATE2-OPENER-FAILED",
    "detail": "apex-gate2-opener.service is in state failed (not an OOM).",
    "action": "reported only"},
   {"id": "ORCH-HEADROOM",
    "detail": "the healthy long-lived instance peaked at 349.9 MiB against the "
              "512 MiB cap, about 32 percent headroom, over a 4-day run.",
    "action": "watch item; no change proposed"}],
}
json.dump(doc, open("/opt/apex-repo/results/orchestrator_oom001_diagnosis.json", "w"), indent=1)
print("wrote results/orchestrator_oom001_diagnosis.json")
