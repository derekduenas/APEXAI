"""PREMARKET-SEQUENTIAL-AUDIT-001-R4 — the staged production producer.

R3 established that the production runner had never been staged: only the audit harness had. R4 replaces the
producer itself. These tests hold the properties that replacement is supposed to have, and several of them exist
because the failure flights caught the first version of this code getting them wrong.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import pathlib
import subprocess

import pytest

from apex.audit import call_graph as CG
from apex.frontier import premarket_journal as PJ
from apex.frontier import premarket_runtime as RT
from apex.frontier import premarket_stages as PS
from apex.frontier import run_record as RR

REPO = pathlib.Path(__file__).resolve().parents[1]
OPS = REPO / "ops/premarket_repair"
STAGED_CLI = "scripts/premarket_stage.py"
LEGACY = "scripts/premarket_run.py"

# The three sleep sites reachable by IMPORT from the staged entry point. Every one is a provider rate-limit or
# retry backoff bounded by a request interval or a retry budget; none is parameterised by a stage target. This is
# a CLOSURE, not a list someone eyeballed: a new sleep anywhere in the reachable set breaks this test.
PERMITTED_SLEEPS = {("apex/data/sharadar_api.py", "time.sleep"),
                    ("apex/intraday/eodhd.py", "time.sleep")}

# Captured from the live host at the start of R4, before anything in this brick ran.
INSTALLED_AT_R4_START = {
    "plist": "6a22ee77ee8e4af2994889826c13bf42a850c1f3db944f94de3a35461a05a0f2",
    "shell": "3508fe93467f7eb96c459389e94604912f71775a2764b5406d6691da3821f2b7",
}


# ======================================================= 2. ONE authoritative implementation
class TestOneImplementation:
    def test_the_legacy_runner_calls_the_library_absorb_and_defines_no_second_one(self):
        src = (REPO / LEGACY).read_text()
        tree = ast.parse(src)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "absorb")
        calls = {ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}
        assert "PS.absorb" in calls, "the legacy runner must delegate, not reimplement"
        assert not any("assemble" in c for c in calls), \
            "a second call site for assemble() is a second implementation waiting to drift"

    def test_assemble_is_reached_from_exactly_one_place_in_the_premarket_path(self):
        sites = []
        for f in (LEGACY, STAGED_CLI, "apex/frontier/premarket_stages.py"):
            tree = ast.parse((REPO / f).read_text())
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "assemble":
                    sites.append((f, n.lineno))
        assert len(sites) == 1 and sites[0][0] == "apex/frontier/premarket_stages.py", sites

    def test_the_schedule_has_one_definition(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pmstage", REPO / STAGED_CLI)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        assert m.STAGES is PS.STAGES
        legacy = (REPO / LEGACY).read_text()
        assert "schedule = list(PS.ABSORB_STAGES)" in legacy
        assert '("0815_ET_initial", 8, 15)' not in legacy, "the schedule was restated in a second place"

    def test_the_brief_firewall_and_prompt_have_one_definition(self):
        import importlib.util
        src = (REPO / LEGACY).read_text()
        assert "FORBIDDEN_IN_BRIEF = PS.FORBIDDEN_IN_BRIEF" in src
        assert "BRIEF_PROMPT = PS.BRIEF_PROMPT" in src
        assert '"buy "' not in src, "the forbidden-term list was restated"


# ======================================================= 3/4. durable state and transitions
class TestDurableState:
    @pytest.fixture()
    def j(self, tmp_path):
        return PJ.open_journal("2026-08-26", root=tmp_path)

    def test_the_log_is_hash_chained_and_verifies(self, j):
        j.append(stage="a", state="STARTED")
        j.append(stage="a", state="CAPTURED")
        assert j.verify()["verdict"] == "CHAIN_INTACT"
        assert j.events()[1]["prev"] == j.events()[0]["digest"]

    def test_an_altered_event_is_detected(self, j):
        j.append(stage="a", state="STARTED", note="original")
        evs = j.events(); evs[0]["payload"]["note"] = "tampered"
        j.events_path.write_text(json.dumps(evs[0], default=str) + "\n")
        with pytest.raises(PJ.ChainBroken, match="EVENT_DIGEST_MISMATCH"):
            j.verify()

    def test_an_altered_blob_that_kept_its_digest_is_detected(self, j):
        sha = j.put_blob({"rows": [1, 2, 3]})
        j.append(stage="a", state="CAPTURED", capture_blob=sha)
        (j.blobs / ("%s.json" % sha)).write_text('{"rows":[9]}')
        with pytest.raises(PJ.ChainBroken, match="BLOB_DIGEST_MISMATCH"):
            j.verify()

    def test_blobs_are_content_addressed_and_write_once(self, j):
        a = j.put_blob({"x": 1}); b = j.put_blob({"x": 1})
        assert a == b and len(list(j.blobs.glob("*.json"))) == 1

    def test_no_pickle_anywhere_in_the_durable_path(self):
        """Asserted over the IMPORT closure, not the text -- the module's own docstring says the word."""
        rep = CG.report(STAGED_CLI, repo=str(REPO))
        for f in rep["modules"]:
            mods = CG._imports(ast.parse((REPO / f).read_text()))
            assert not any(m.split(".")[0] in ("pickle", "marshal", "shelve") for m in mods), f

    def test_sequence_numbers_are_dense_and_unique_under_concurrency(self, tmp_path):
        code = ("import sys;sys.path.insert(0,%r)\n"
                "from apex.frontier import premarket_journal as PJ\n"
                "j = PJ.open_journal('2026-08-26', root=%r)\n"
                "[j.append(stage='s', state='STARTED', i=i) for i in range(20)]\n"
                % (str(REPO), str(tmp_path)))
        ps = [subprocess.Popen([os.sys.executable, "-c", code], cwd=str(REPO)) for _ in range(4)]
        for p in ps:
            p.wait()
        j = PJ.open_journal("2026-08-26", root=tmp_path)
        seqs = [e["seq"] for e in j.events()]
        assert seqs == list(range(80)), "sequence allocation is not transactional"
        assert j.verify()["verdict"] == "CHAIN_INTACT"

    def test_the_state_vocabulary_covers_the_declared_transitions(self):
        assert PJ.PROGRESS == ("PENDING", "STARTED", "CAPTURED", "NORMALIZED", "ABSORBED", "COMPLETED")
        for t in ("TOO_EARLY", "MISSED_WINDOW", "SOURCE_UNAVAILABLE", "REFUSED_INPUT", "FAILED",
                  "RECONCILED_DUPLICATE"):
            assert t in PJ.TERMINAL
        assert "LATE_START" in PJ.DISPOSITIONS and "LATE_START" not in PJ.TERMINAL, \
            "LATE_START is a start disposition; a stage that starts late still absorbs (declared narrowing)"

    def test_reconstruction_reads_evidence_and_never_a_caller_supplied_flag(self, j):
        sha = j.put_blob({"kind": "premarket_context_packet", "market_date": "2026-08-26"})
        j.append(stage="0815_ET_initial", state="COMPLETED", packet_blob=sha)
        r = j.reconstruct()
        assert r["status"] == "RECONSTRUCTED" and r["from_stage"] == "0815_ET_initial"
        src = (REPO / "apex/frontier/premarket_journal.py").read_text()
        assert "self.verify()" in src.split("def reconstruct")[1][:400], \
            "reconstruct must verify the chain before trusting it"

    def test_nothing_to_reconstruct_is_named_not_guessed(self, j):
        assert j.reconstruct()["status"] == "NO_COMPLETED_ABSORPTION"


class TestExactlyOnceClaim:
    @pytest.fixture()
    def j(self, tmp_path):
        return PJ.open_journal("2026-08-26", root=tmp_path)

    def test_a_live_holder_is_never_displaced(self, j):
        assert j.claim("s", holder="a")["status"] == "GRANTED"
        assert j.claim("s", holder="b")["status"] == "HELD"

    def test_a_dead_holder_on_a_non_terminal_stage_is_taken_over_and_recorded(self, j):
        j.claim("s", holder="a")
        p = j.claims / "s.claim"
        p.write_text(json.dumps({"stage": "s", "holder": "a", "pid": 2 ** 22, "at": 0}))
        out = j.claim("s", holder="b")
        assert out["status"] == "TAKEOVER" and out["holder"]["pid"] == 2 ** 22
        assert json.loads(p.read_text())["took_over_from"]["pid"] == 2 ** 22, "the dead holder must be recorded"

    def test_a_dead_holder_on_a_TERMINAL_stage_is_a_duplicate_not_a_recovery(self, j):
        j.claim("s", holder="a")
        (j.claims / "s.claim").write_text(json.dumps({"pid": 2 ** 22, "at": 0}))
        j.append(stage="s", state="COMPLETED")
        assert j.claim("s", holder="b")["status"] == "HELD"

    def test_an_unreadable_claim_is_treated_as_held(self, j):
        j.claim("s", holder="a")
        (j.claims / "s.claim").write_text("{not json")
        assert j.claim("s", holder="b")["status"] == "HELD"


class TestRunLockLiveness:
    @pytest.fixture(autouse=True)
    def isolate(self, tmp_path, monkeypatch):
        monkeypatch.setattr(RR, "RUNS", tmp_path / "runs")

    def test_a_live_holder_is_refused_at_any_age(self):
        RR.RunLock(now=lambda: 0.0).acquire("first")
        with pytest.raises(RR.LockHeld):
            RR.RunLock(now=lambda: 10 ** 9).acquire("second")

    def test_a_dead_holder_is_taken_over_and_the_dead_holder_is_named(self):
        lk = RR.RunLock()
        lk.acquire("first")
        lk.path.write_text(json.dumps({"run_id": "first", "pid": 2 ** 22, "at": 0}))
        body = RR.RunLock().acquire("second")
        assert body["took_over_from"]["pid"] == 2 ** 22

    def test_the_strict_R3_behaviour_is_still_available(self):
        lk = RR.RunLock(); lk.acquire("first")
        lk.path.write_text(json.dumps({"run_id": "first", "pid": 2 ** 22, "at": 0}))
        with pytest.raises(RR.LockHeld):
            RR.RunLock(takeover_dead=False).acquire("second")

    def test_a_run_record_is_per_invocation_not_per_stage(self):
        a = RR.next_run_id("2026-08-26", "0815_ET_initial")
        RR.RunRecord(run_id=a)
        b = RR.next_run_id("2026-08-26", "0815_ET_initial")
        assert a != b, ("conflating per-invocation accounting with exactly-once enforcement made a crashed "
                        "stage permanently unresumable; the failure flights caught it")


# ======================================================= window logic
class TestTheWindow:
    @pytest.mark.parametrize("hh,mm,expect", [(3, 0, "TOO_EARLY"), (8, 15, "ON_TIME"), (8, 22, "LATE_START"),
                                              (8, 40, "MISSED_WINDOW"), (8, 14, "ON_TIME")])
    def test_an_out_of_window_invocation_is_refused_not_mislabelled(self, hh, mm, expect):
        import pandas as pd
        now = pd.Timestamp("2026-08-26 %02d:%02d" % (hh, mm), tz="America/New_York")
        assert PS.disposition("0815_ET_initial", now)[0] == expect


# ======================================================= 9. the prepared production call graph
class TestPreparedProductionPath:
    def test_every_prepared_plist_invokes_the_shell_with_an_explicit_stage(self):
        stages = {s for s, _h, _m in PS.STAGE_SCHEDULE} | {"reconcile"}
        found = set()
        for p in OPS.glob("com.apex.premarket.*.plist.NEW"):
            body = p.read_text()
            stage = p.name[len("com.apex.premarket."):-len(".plist.NEW")]
            found.add(stage)
            assert "ops/premarket.sh</string><string>%s</string>" % stage in body, p.name
            assert "StandardErrorPath" in body, "a failure before the script's log redirect must be visible"
        assert found == stages, "a stage without a trigger, or a trigger without a stage: %s" % (found ^ stages)

    def test_no_prepared_artifact_reaches_the_long_sleeping_runner(self):
        for p in list(OPS.glob("*.NEW")) + [OPS / "install.sh", OPS / "once.sh", OPS / "status.sh"]:
            assert "premarket_run.py" not in p.read_text(), p.name

    def test_the_prepared_shell_invokes_the_staged_cli(self):
        assert "scripts/premarket_stage.py --stage" in (OPS / "premarket.sh.NEW").read_text()

    def test_the_prepared_shell_exports_no_runtime_substitution(self):
        body = (OPS / "premarket.sh.NEW").read_text()
        for name in RT.ENV_NAMES:
            assert "export %s" % name not in body and "%s=" % name not in body, name

    def test_the_prepared_artifacts_are_generated_from_the_schedule_and_have_not_drifted(self):
        r = subprocess.run([os.sys.executable, "ops/premarket_repair/generate.py", "--check"],
                           cwd=str(REPO), capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_the_staged_entry_point_cannot_reach_the_legacy_runner(self):
        rep = CG.report(STAGED_CLI, repo=str(REPO))
        assert rep["reaches_legacy_runner"] is False
        assert rep["module_count"] > 15, "the closure looks too small to be real: %d" % rep["module_count"]

    def test_the_only_sleeps_reachable_from_production_are_the_declared_provider_backoffs(self):
        rep = CG.report(STAGED_CLI, repo=str(REPO))
        got = {(s["module"], s["call"]) for s in rep["sleep_sites"]}
        assert got == PERMITTED_SLEEPS, "a sleep appeared in the production closure: %s" % (got ^ PERMITTED_SLEEPS)

    def test_the_legacy_runner_still_has_its_two_scheduling_sleeps_because_it_is_the_oracle(self):
        rep = CG.report(LEGACY, repo=str(REPO))
        mine = [s for s in rep["sleep_sites"] if s["module"] == LEGACY]
        assert len(mine) == 2, "the parity oracle must keep the defect it is the oracle for"


# ======================================================= the runtime seam
class TestTheRuntimeSeam:
    def test_a_clean_environment_is_fully_real(self, monkeypatch):
        for n in RT.ENV_NAMES:
            monkeypatch.delenv(n, raising=False)
        assert RT.substitutions() == {} and RT.realism() == "FULLY_REAL"

    def test_every_substitution_is_reported(self, monkeypatch):
        monkeypatch.setenv(RT.ENV_TRANSPORT, "m:f")
        assert RT.substitutions() == {RT.ENV_TRANSPORT: "m:f"} and RT.realism() == "SUBSTITUTED"

    def test_the_crash_injector_is_a_declared_name(self):
        assert RT.ENV_CRASH in RT.ENV_NAMES, "a hook that is not in ENV_NAMES would not appear in any record"


# ======================================================= the Captain path
class TestTheCaptainPath:
    def test_the_firewall_still_refuses_the_forbidden_terms(self):
        from apex.audit import premarket_fixture as FX
        v = PS.brief_verdict(FX.HOSTILE_BRIEF)
        assert v["verdict"] == "REFUSED_BY_FIREWALL" and v["firewall_hits"]

    def test_an_invalid_schema_is_named_separately_from_the_firewall(self):
        from apex.audit import premarket_fixture as FX
        assert PS.brief_verdict(FX.INVALID_BRIEF)["verdict"] == "CAPTAIN_SCHEMA_INVALID"
        assert PS.brief_verdict(FX.RECORDED_BRIEF)["verdict"] == "ACCEPTED"

    def test_the_captain_prompt_does_not_depend_on_which_producer_serialized_the_packet(self):
        """The R4 parity run found this: the staged path round-trips the packet through a canonical sorted-key
        blob and the legacy path did not, so the Captain saw different BYTES for identical FACTS."""
        a = {"market_date": "d", "indices": {"b": 1, "a": 2}, "gap_map": [], "watch_map": {},
             "source_coverage": {}, "blind_spots": []}
        b = dict(a, indices={"a": 2, "b": 1})
        assert PS.brief_facts(a) == PS.brief_facts(b)


# ======================================================= nothing was activated
class TestNothingWasActivated:
    def test_the_installed_production_files_are_byte_for_byte_unchanged(self):
        plist = pathlib.Path.home() / "Library/LaunchAgents/com.apex.premarket.plist"
        shell = pathlib.Path.home() / "apex-equities/ops/premarket.sh"
        assert hashlib.sha256(plist.read_bytes()).hexdigest() == INSTALLED_AT_R4_START["plist"]
        assert hashlib.sha256(shell.read_bytes()).hexdigest() == INSTALLED_AT_R4_START["shell"]

    def test_no_per_stage_agent_was_installed(self):
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
        for stage, _h, _m in PS.STAGE_SCHEDULE:
            assert "com.apex.premarket.%s" % stage not in out, stage

    def test_no_disposable_launchagent_was_left_behind(self):
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
        assert "com.apex.audit" not in out
