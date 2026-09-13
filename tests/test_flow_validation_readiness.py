"""FLOW-VALIDATION-001 — the pre-execution audit, as tests.

Synthetic inputs only. No recorded market data is read by anything here. Every driver scenario runs the ACTUAL CLI
in a subprocess, because the point is to exercise the command that the recorded run will use, not a re-implementation
of it.

This module exists because the audit's fifth item found a crash: the repaired driver stripped `exit_quote_fn` from
its sources, a line the old driver needed and the scheduler does not, so the FIRST exit of the recorded run would
have died with a KeyError. Nothing short of running the real command would have caught it."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from apex.options_pilot import replay as RP
from tests.synthetic_collection import SESSION_OPEN, write

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "scripts" / "loop_demonstration.py"
PRESERVE = REPO / "scripts" / "preserve_inputs.py"
CADENCE_S = 15 * 60.0
HOLD_S = 900.0


def preserve(coll: Path, dest: Path, *, prior: Path | None = None):
    """Run the real preservation CLI, which is how a manifest is produced."""
    return subprocess.run([sys.executable, str(PRESERVE), str(coll), str(prior or (coll / "prior_bars.json")),
                           str(dest)], cwd=REPO, capture_output=True, text=True)


def synthetic_authorization(dest: Path, *, manifest: Path | None = None, assumption_id: str = "BULK_PULL_AVAILABILITY_V1",
                            text: str | None = None, **override) -> Path:
    """A SYNTHETIC operator authorization, for tests only.

    Nothing in the repository may author the real one: an acceptance written by the process that needs it is not an
    acceptance. This exists so the acceptance GATE can be exercised, and it says so in its own contents."""
    import hashlib
    from apex.options_pilot import provenance as PROV
    from apex.options_pilot import run_dir as RD
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = {"accepted_by": "SYNTHETIC_TEST_FIXTURE - not an operator acceptance",
           "accepted_utc": "2026-09-12T00:00:00Z",
           "evaluation_id": "FLOW-VALIDATION-001",
           "input_manifest_sha256": (hashlib.sha256(manifest.read_bytes()).hexdigest()
                                     if manifest is not None and manifest.is_file() else "0" * 64),
           "code_pin": RD.code_pin().get("commit"),
           "scope": "synthetic exercise of the acceptance gate",
           "accepted_assumptions": [{"id": assumption_id,
                                     "text": text if text is not None else PROV.assumption_text(assumption_id)}]}
    doc.update(override)
    dest.write_text(json.dumps(doc, indent=1))
    return dest


def run_driver(coll: Path, out_base: Path, run_id: str, *, manifest: Path | None = None, prior: Path | None = None,
               no_manifest: bool = False, authz: Path | None = None, no_authz: bool = False):
    """The driver REQUIRES a manifest, so unless a test is specifically about that requirement, one is produced from
    the collection first. The preserved layout keeps prior_bars.json OUTSIDE the collection directory on purpose: it
    is a different dataset with a different authorization, and the command names the two separately."""
    prior = prior or (coll / "prior_bars.json")
    if manifest is None and not no_manifest:
        dest = coll.parent / (coll.name + "__preserved")
        if not dest.exists():
            r = preserve(coll, dest, prior=prior)
            assert r.returncode == 0, r.stderr[-1500:]
        coll, prior = dest / "collection", dest / "prior_bars.json"
        manifest = dest / "INPUTS_MANIFEST.json"
    argv = [sys.executable, str(DRIVER), str(coll), str(prior), str(out_base), run_id]
    if manifest is not None:
        argv.append(str(manifest))
        if not no_authz:
            argv.append(str(authz or synthetic_authorization(out_base.parent / "authz.json", manifest=manifest)))
    return subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=900)


def result(out_base: Path, run_id: str) -> dict:
    return json.loads((out_base / run_id / "loop_demonstration.json").read_text())


def ledger(out_base: Path, run_id: str, policy: str) -> list:
    p = out_base / run_id / ("REPLAY_QUARANTINED_%s.jsonl" % policy)
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


@pytest.fixture(scope="module")
def ok_run(tmp_path_factory):
    """One healthy synthetic run, reused by the read-only assertions below."""
    base = tmp_path_factory.mktemp("ok")
    coll = base / "coll"
    write(coll, minutes=180)
    r = run_driver(coll, base / "runs", "ok")
    assert r.returncode == 0, r.stderr[-3000:]
    return {"base": base, "coll": coll, "out": base / "runs", "run_id": "ok"}


# ---------------------------------------------------------------------------- item 5: the driver and its CLI


class TestTheActualDriverAndCLI:

    def test_a_full_lifecycle_completes_through_the_real_command(self, ok_run):
        res = result(ok_run["out"], ok_run["run_id"])
        summ = res["summary"]
        assert set(summ) == {"WAIT", "PILOT_RULE_V2", "FULL_FUNNEL_V1"}
        assert summ["PILOT_RULE_V2"]["trades"] >= 1, "the rule path must reach a trade on this fixture"
        rows = ledger(ok_run["out"], ok_run["run_id"], "PILOT_RULE_V2")
        kinds = {r["kind"] for r in rows}
        for k in ("pilot_session_open", "pilot_forecast", "pilot_intent", "pilot_fill", "pilot_decision",
                  "pilot_outcome", "pilot_session_close"):
            assert k in kinds, k

    def test_the_exit_quote_source_is_required_at_construction(self):
        """The crash this audit found, turned into a refusal that fires immediately instead of mid-run."""
        from apex.options_pilot import lifecycle as LC
        from apex.options_pilot.synthetic_harness import SyntheticHarness
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            h = SyntheticHarness(Path(td) / "l.jsonl")
            lc = LC.MonotonicClock(h.now())
            h.clock = lc.clock(); h.bd.clock = h.clock; h.now = lc.now; h.advance = lc.sleep
            src = h.sources(); src.pop("exit_quote_fn")
            with pytest.raises(LC.LifecycleRefused, match="SOURCES_INCOMPLETE"):
                LC.LifecycleRunner(boundary=h.bd, sources=src, clock=lc, symbols=["SPY"],
                                   selection_policy="PILOT_RULE_V2", scan_epochs=[])

    def test_the_driver_no_longer_strips_the_exit_quote_source(self):
        src = DRIVER.read_text()
        assert 'src.pop("exit_quote_fn"' not in src

    def test_wait_is_persisted_as_a_decision_when_nothing_is_affordable(self, tmp_path):
        """Every contract priced far above the per-trade cap. The run must WAIT and RECORD each WAIT."""
        coll = tmp_path / "coll"
        write(coll, minutes=180, ask=4.95, expensive_after=0, expensive_ask=40.0)
        r = run_driver(coll, tmp_path / "runs", "wait")
        assert r.returncode == 0, r.stderr[-2000:]
        res = result(tmp_path / "runs", "wait")
        assert res["summary"]["PILOT_RULE_V2"]["trades"] == 0
        rows = ledger(tmp_path / "runs", "wait", "PILOT_RULE_V2")
        decisions = [x for x in rows if x["kind"] == "pilot_decision"]
        assert decisions and all(d["decision"] in ("WAIT", "REFUSE") for d in decisions)
        assert all(d.get("why") for d in decisions), "a WAIT without a reason is not a decision"
        agg = res["policies"]["PILOT_RULE_V2"]["net_result"]
        assert agg["total_net_pnl"] == 0.0 and agg["zero_basis"] == "ACTUAL_NO_TRADE_POLICY"

    def test_an_output_collision_is_refused_and_the_first_run_survives(self, ok_run):
        before = sorted(p.name for p in (ok_run["out"] / ok_run["run_id"]).iterdir())
        r = run_driver(ok_run["coll"], ok_run["out"], ok_run["run_id"])
        assert r.returncode != 0 and "RUN_DIR_COLLISION" in (r.stderr + r.stdout)
        after = sorted(p.name for p in (ok_run["out"] / ok_run["run_id"]).iterdir())
        assert before == after, "the refused second run must not touch the first run's artifacts"

    def test_a_failing_run_preserves_its_partial_artifacts(self, tmp_path):
        """A collection whose bars file is unreadable fails partway. Whatever it produced must survive."""
        coll = tmp_path / "coll"
        write(coll, minutes=180)
        (coll / "bars_SPY.jsonl").write_text("{not json\n")
        r = run_driver(coll, tmp_path / "runs", "boom")
        assert r.returncode != 0
        d = tmp_path / "runs" / "boom"
        if d.exists():                       # it fails before the run dir when parsing happens first; both are fine
            assert (d / "RUN_START.json").exists()
            if (d / "RUN_FAILED.json").exists():
                body = json.loads((d / "RUN_FAILED.json").read_text())
                assert body["status"] == "FAILED" and body["error"]

    def test_driver_level_restart_is_not_applicable_and_says_so(self, ok_run):
        """Each run claims a FRESH directory and therefore a fresh ledger, so the driver has no restart path. The
        restart contract is proven where it lives, at the library level, over one ledger across two processes."""
        res = result(ok_run["out"], ok_run["run_id"])
        assert res["policies"]["PILOT_RULE_V2"]["ledger"].endswith("REPLAY_QUARANTINED_PILOT_RULE_V2.jsonl")
        import tests.test_operating_loop_001 as T
        assert hasattr(T.TestRestartRecoversWithoutDuplicating,
                       "test_6_a_restart_recovers_the_obligation_without_a_duplicate_fill_or_fee")


# ---------------------------------------------------------------------------- item 2: quote visibility


class TestQuoteVisibilityUsesRecordedAvailability:

    def test_no_quote_used_is_later_than_the_instant_that_asked_for_it(self, ok_run):
        """THE GENERAL INVARIANT, over every fill and every outcome of a whole run: the provider's own timestamp on
        the quote that was used is at or before the instant the request was made. No future quote selection."""
        checked = 0
        for policy in ("PILOT_RULE_V2", "FULL_FUNNEL_V1"):
            for r in ledger(ok_run["out"], ok_run["run_id"], policy):
                if r["kind"] == "pilot_fill" and r.get("quote_observed"):
                    assert r["quote_observed"]["timestamp_epoch"] <= r["quote_request_epoch"], r["fill_id"]
                    checked += 1
                if r["kind"] == "pilot_outcome" and r.get("exit_quote_observed"):
                    assert r["exit_quote_observed"]["timestamp_epoch"] <= r["exit_quote_request_epoch"], r["intent_id"]
                    checked += 1
        assert checked >= 5, "the invariant must actually have been exercised, not vacuously true"

    def test_an_older_available_snapshot_beats_a_closer_future_one(self, tmp_path):
        """NEAREST-IN-TIME WOULD PICK THE FUTURE ONE. Availability must pick the past one.

        The chain snapshot immediately AFTER each scan instant is made wildly cheaper. A nearest-time lookup would
        often select it, because it can sit closer to the instant than the previous snapshot does. Every price the
        run actually used must come from a snapshot at or before its instant, so the cheap future asks must never
        appear as a fill price."""
        coll = tmp_path / "coll"
        write(coll, minutes=180)
        # rewrite: every snapshot whose index is 1 past a scan boundary becomes cheap and slightly LATER
        lines = (coll / "chain_SPY.jsonl").read_text().splitlines()
        out, cheap = [], 0.55
        for i, line in enumerate(lines):
            r = json.loads(line)
            if i % 15 == 1:                                   # the snapshot just after each scan instant
                for q in r["payload"]["quotes"]:
                    q["ask"], q["bid"] = "%.2f" % cheap, "%.2f" % (cheap - 0.05)
            out.append(json.dumps(r))
        (coll / "chain_SPY.jsonl").write_text("\n".join(out) + "\n")
        r = run_driver(coll, tmp_path / "runs", "future")
        assert r.returncode == 0, r.stderr[-2000:]
        prices = [x["price"] for x in ledger(tmp_path / "runs", "future", "PILOT_RULE_V2")
                  if x["kind"] == "pilot_fill" and x.get("price") is not None]
        assert prices, "the fixture must produce fills for this to mean anything"
        assert all(abs(p - cheap) > 1e-9 for p in prices), \
            "a price from a snapshot that had not arrived yet was used: %r" % (prices,)

    def test_no_eligible_quote_in_the_exit_window_leaves_it_unresolved(self, tmp_path):
        """A chain gap spanning an exit window. The position must stay an explicit unresolved obligation, and no
        fill may be fabricated from a quote outside the window."""
        coll = tmp_path / "coll"
        # first scan at snapshot 0 fills; its exit is due 15 min later, so omit snapshots 14..22
        write(coll, minutes=180, chain_gap=(14, 23))
        r = run_driver(coll, tmp_path / "runs", "gap")
        assert r.returncode == 0, r.stderr[-2000:]
        rows = ledger(tmp_path / "runs", "gap", "PILOT_RULE_V2")
        res = result(tmp_path / "runs", "gap")
        agg = res["policies"]["PILOT_RULE_V2"]["net_result"]
        exhausted = [x for x in rows if x["kind"] == "pilot_exit_exhausted"]
        assert exhausted or agg["n_unresolved_positions"] >= 1, \
            "a missing exit quote must leave an explicit obligation"
        assert agg["total_net_pnl"] is None and agg["total_net_status"] == "NOT_ESTIMABLE"
        assert any("UNRESOLVED" in w or "EXHAUSTED" in w for w in agg["why_not_estimable"])
        # and nothing resolved against a quote from outside its own window
        for o in rows:
            if o["kind"] == "pilot_outcome" and o.get("status") == "RESOLVED":
                assert o["exit_quote_observed"]["timestamp_epoch"] <= o["exit_quote_request_epoch"]


# ---------------------------------------------------------------------------- item 3: the replay's own controls


class TestTheReplayRoutesOwnDataControls:

    def _auth(self, digests):
        return RP.ReplayAuthorization(reason="audit", input_digests=digests, recorded_window_utc=("a", "b"))

    def test_a_boundary_is_refused_until_the_inputs_are_verified(self, tmp_path):
        a = self._auth({"bars": "e" * 64})
        with pytest.raises(RP.ReplayRefused, match="REPLAY_INPUTS_NOT_VERIFIED"):
            RP.replay_boundary(tmp_path / "l.jsonl", clock=None, risk_authority=None, session_id="S",
                               release="r", authorization=a)

    def test_a_digest_mismatch_refuses(self, tmp_path):
        p = tmp_path / "bars.json"
        p.write_text("[]")
        a = self._auth({"bars": "e" * 64})
        with pytest.raises(RP.ReplayRefused, match="REPLAY_INPUT_DIGEST_MISMATCH"):
            a.verify_inputs({"bars": p})
        assert a.verified_inputs is None

    def test_an_undeclared_or_missing_input_refuses(self, tmp_path):
        p = tmp_path / "bars.json"
        p.write_text("[]")
        import hashlib
        good = hashlib.sha256(p.read_bytes()).hexdigest()
        a = self._auth({"bars": good})
        with pytest.raises(RP.ReplayRefused, match="REPLAY_INPUT_SET_MISMATCH"):
            a.verify_inputs({"bars": p, "extra": p})
        b = self._auth({"bars": good, "nbbo": good})
        with pytest.raises(RP.ReplayRefused, match="REPLAY_INPUT_SET_MISMATCH"):
            b.verify_inputs({"bars": p})
        c = self._auth({"bars": good})
        with pytest.raises(RP.ReplayRefused, match="REPLAY_INPUT_MISSING"):
            c.verify_inputs({"bars": tmp_path / "gone.json"})

    def test_a_matching_digest_binds_and_the_description_says_so(self, tmp_path):
        import hashlib
        p = tmp_path / "bars.json"
        p.write_text("[1,2,3]")
        a = self._auth({"bars": hashlib.sha256(p.read_bytes()).hexdigest()})
        a.verify_inputs({"bars": p})
        d = a.describe()
        assert d["inputs_verified"]["bars"]["sha256"] and d["authorization_digest"]
        assert "NOT_VERIFIED" not in json.dumps(d["inputs_verified"])

    def test_the_run_records_where_its_declared_digests_came_from(self, ok_run):
        """A self-declared digest and an independently declared one are not the same evidence, and the run says
        which it had."""
        res = result(ok_run["out"], ok_run["run_id"])
        assert res["declaration_source"].startswith("INDEPENDENT_MANIFEST"), \
            "the driver now REQUIRES a manifest, so every run declares independently"

    def test_an_independent_manifest_upgrades_the_declaration(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=180)
        out = preserve(coll, tmp_path / "durable")
        assert out.returncode == 0, out.stderr[-2000:]
        man = tmp_path / "durable" / "INPUTS_MANIFEST.json"
        r = run_driver(tmp_path / "durable" / "collection", tmp_path / "runs", "manifested", manifest=man,
                       prior=tmp_path / "durable" / "prior_bars.json")
        assert r.returncode == 0, r.stderr[-2000:]
        res = result(tmp_path / "runs", "manifested")
        assert res["declaration_source"].startswith("INDEPENDENT_MANIFEST")

    def test_every_persisted_record_carries_the_replay_class(self, ok_run):
        from apex.options_pilot import records as R
        rows = ledger(ok_run["out"], ok_run["run_id"], "PILOT_RULE_V2")
        assert rows and all(r["evidence_class"] == R.REPLAY_EVIDENCE_CLASS for r in rows)
        assert all(r["prospective_results_eligible"] is False for r in rows)
        assert R.prospective_only(rows) == []


# ---------------------------------------------------------------------------- item 6: preservation


class TestInputPreservation:

    def test_copies_are_verified_and_manifested(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=30)
        out = subprocess.run([sys.executable, str(PRESERVE), str(coll), str(coll / "prior_bars.json"),
                              str(tmp_path / "dest")], cwd=REPO, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr[-2000:]
        man = json.loads((tmp_path / "dest" / "INPUTS_MANIFEST.json").read_text())
        assert sorted(man["inputs"]) == ["bars", "chain", "nbbo", "prior_bars"]
        import hashlib
        for label, v in man["inputs"].items():
            assert hashlib.sha256(Path(v["path"]).read_bytes()).hexdigest() == v["sha256"]

    def test_it_never_overwrites_a_preserved_set(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=30)
        args = [sys.executable, str(PRESERVE), str(coll), str(coll / "prior_bars.json"), str(tmp_path / "dest")]
        assert subprocess.run(args, cwd=REPO, capture_output=True, text=True).returncode == 0
        second = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
        assert second.returncode != 0 and "DESTINATION_EXISTS" in second.stderr

    def test_the_acquisition_history_survives_the_copy(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=30)
        subprocess.run([sys.executable, str(PRESERVE), str(coll), str(coll / "prior_bars.json"),
                        str(tmp_path / "dest")], cwd=REPO, capture_output=True, text=True)
        man = json.loads((tmp_path / "dest" / "INPUTS_MANIFEST.json").read_text())
        pb = man["acquisition_history"]["prior_bars"]
        assert pb["authorization"] == "NONE AT ACQUISITION TIME"
        assert "SCOPE_DEVIATION_001" in pb["recorded_in"]
        assert "does not authorize how it was obtained" in pb["note"]


# ---------------------------------------------------------------------------- item 1: the invocation map


class TestTheInvocationMapComesFromTheRecords:

    def test_every_stage_reports_a_value_or_a_named_absence(self, ok_run):
        """The map is read off the persisted funnel trace, not off the source. A stage that did not run must say so
        by name; none may be silently missing."""
        from apex.options_pilot.session import FUNNEL_STAGES
        rows = ledger(ok_run["out"], ok_run["run_id"], "FULL_FUNNEL_V1")
        traces = [r["funnel_trace"] for r in rows if r["kind"] == "pilot_decision"]
        assert traces
        for t in traces:
            for stage in FUNNEL_STAGES:
                assert stage in t, stage
                v = t[stage]
                assert v, "stage %s is empty rather than absent-with-a-reason" % stage
                if isinstance(v, dict) and "missing" in v:
                    assert isinstance(v["missing"], str) and v["missing"], stage

    def test_the_unavailable_layers_are_named_not_implied(self, ok_run):
        res = result(ok_run["out"], ok_run["run_id"])
        ident = res["policies"]["PILOT_RULE_V2"]["model_identity"]
        assert ident["joint_engine"]["status"] == "UNAVAILABLE" and ident["joint_engine"]["why"]
        for stage in ("variance", "regime", "simulation"):
            assert ident[stage]["status"] == "UNAVAILABLE" and ident[stage]["why"], stage
        assert ident["signal"]["status"].startswith("PLACEHOLDER_NOT_A_SIGNAL")

    def test_the_funnel_records_its_own_fit_status(self, ok_run):
        rows = ledger(ok_run["out"], ok_run["run_id"], "FULL_FUNNEL_V1")
        funnels = [r for r in rows if r["kind"] == "pilot_funnel"]
        assert funnels
        for f in funnels:
            assert f["engine"]["fit"]["status"], "the engine must state its fit status on every scan"


# ---------------------------------------------------------------------------- f87113a findings: bytes and timing


class TestVerificationHappensBeforeParsing:
    """Finding 1 at f87113a: the driver parsed the inputs near the top and verified them near the bottom, so the
    digest described one read and the decisions came from another."""

    def test_the_manifest_is_required(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=30)
        r = run_driver(coll, tmp_path / "runs", "nomanifest", no_manifest=True)
        assert r.returncode != 0 and "MANIFEST_REQUIRED" in (r.stdout + r.stderr)

    def test_the_bytes_hashed_are_the_bytes_parsed(self):
        """STRUCTURAL. The inputs are read once into RAW, RAW is verified, and only RAW is parsed. A second read
        would reopen the window this finding is about, so no file is opened again after verification."""
        src = DRIVER.read_text()
        i_read = src.index("RAW = {label: p.read_bytes()")
        i_verify = src.index("AUTHORIZATION.verify_bytes(RAW)")
        i_parse = src.index('for line in RAW["chain"].decode()')
        assert i_read < i_verify < i_parse, "read, then verify, then parse"
        after = src[i_verify:]
        assert ".read_text()" not in after.split("def run_policy")[0], "no re-read after verification"
        assert "json.loads(PRIOR.read_text())" not in src

    def test_a_digest_mismatch_refuses_before_any_model_and_leaves_evidence(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=30)
        out = subprocess.run([sys.executable, str(PRESERVE), str(coll), str(coll / "prior_bars.json"),
                              str(tmp_path / "durable")], cwd=REPO, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr[-1500:]
        # replace a preserved file with different bytes: the manifest now names something that is not on disk
        (tmp_path / "durable" / "collection" / "nbbo_SPY.jsonl").write_text('{"kind":"pilot_collection_nbbo"}\n')
        r = run_driver(tmp_path / "durable" / "collection", tmp_path / "runs", "tampered",
                       manifest=tmp_path / "durable" / "INPUTS_MANIFEST.json",
                       prior=tmp_path / "durable" / "prior_bars.json")
        assert r.returncode != 0 and "REPLAY_INPUT_DIGEST_MISMATCH" in (r.stdout + r.stderr)
        d = tmp_path / "runs" / "tampered"
        assert (d / "RUN_START.json").exists(), "the run directory is claimed before reading, so a refusal is recorded"
        body = json.loads((d / "RUN_FAILED.json").read_text())
        assert body["status"] == "FAILED" and "DIGEST_MISMATCH" in body["error"]
        assert body["summary"]["stage"] == "INPUT_VALIDATION"

    def test_verify_bytes_refuses_a_path_instead_of_bytes(self, tmp_path):
        import hashlib
        a = RP.ReplayAuthorization(reason="x", input_digests={"k": hashlib.sha256(b"x").hexdigest()},
                                   recorded_window_utc=("a", "b"))
        with pytest.raises(RP.ReplayRefused, match="REPLAY_INPUT_NOT_BYTES"):
            a.verify_bytes({"k": str(tmp_path / "f")})


class TestAvailabilityAppliesToEveryInputFamily:
    """Finding 2 at f87113a: chain used the recorded receipt, but NBBO used the quote's own `as_of` and bars fell
    back to `event_time + 60`. Neither establishes when APEX received the observation."""

    def test_the_gate_takes_the_most_recent_available_not_the_nearest(self):
        pairs = [(100.0, "old"), (140.0, "late")]      # 140 is closer to 130 than 100 is, and it has not arrived
        assert RP.most_recent_available(pairs, 130.0)[1] == "old"
        assert RP.most_recent_available(pairs, 140.0)[1] == "late"
        assert RP.most_recent_available(pairs, 99.0) is None

    def test_an_old_quote_received_after_the_scan_is_invisible(self):
        """The exact case the correction names: the observation is OLD, its arrival is LATE. Event time would admit
        it; availability must not."""
        scan = 1000.0
        pairs = [(900.0, {"as_of": 890.0, "tag": "arrived_before"}),
                 (1001.0, {"as_of": 500.0, "tag": "old_event_late_arrival"})]
        got = RP.most_recent_available(pairs, scan)
        assert got[1]["tag"] == "arrived_before"
        assert got[1]["as_of"] < scan and pairs[1][1]["as_of"] < scan, \
            "both quotes PREDATE the scan by event time; only availability separates them"

    def test_a_datum_with_no_recorded_availability_is_refused_not_backdated(self):
        with pytest.raises(RP.ReplayRefused, match="AVAILABILITY_UNKNOWN"):
            RP.most_recent_available([(None, {"x": 1})], 10.0)

    def test_the_driver_gates_nbbo_on_the_record_receipt(self):
        src = DRIVER.read_text()
        assert 'nbbo.append((r["receipt_epoch"]' in src
        assert 'nbbo.append((r["payload"]["as_of"]' not in src
        assert "RP.most_recent_available(nbbo, self.t)" in src

    def test_the_driver_invents_no_bar_receipt(self):
        src = DRIVER.read_text()
        assert 'b.get("receipt_time", b["event_time"] + 60.0)' not in src
        assert "bars_excluded_no_recorded_receipt" in src

    def test_bars_without_a_recorded_receipt_are_excluded_and_counted(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=60)
        lines = (coll / "bars_SPY.jsonl").read_text().splitlines()
        stripped = 0
        out = []
        for i, line in enumerate(lines):
            r = json.loads(line)
            if i % 5 == 0:
                for b in r["payload"]:
                    b.pop("receipt_time", None)
                    stripped += 1
            out.append(json.dumps(r))
        (coll / "bars_SPY.jsonl").write_text("\n".join(out) + "\n")
        subprocess.run([sys.executable, str(PRESERVE), str(coll), str(coll / "prior_bars.json"),
                        str(tmp_path / "d")], cwd=REPO, capture_output=True, text=True)
        r = run_driver(tmp_path / "d" / "collection", tmp_path / "runs", "nobarreceipt",
                       manifest=tmp_path / "d" / "INPUTS_MANIFEST.json", prior=tmp_path / "d" / "prior_bars.json")
        assert r.returncode == 0, r.stderr[-2000:]
        rep = result(tmp_path / "runs", "nobarreceipt")["input_report"]
        assert rep["bars_excluded_no_recorded_receipt"] == stripped > 0

    def test_the_prior_bar_artifact_claims_no_measurement(self, ok_run_manifested):
        """Its availability is DERIVED by the accepted formula, its attribution is UNVERIFIED, and its constant
        offset is a diagnostic rather than a verdict."""
        rep = result(ok_run_manifested["out"], ok_run_manifested["run_id"])["input_report"]
        prov = rep["prior_bars_provenance"]
        assert prov["availability_basis"] == "DERIVED_BY_FORMULA"
        assert prov["artifact_execution_attribution"]["status"] == "UNVERIFIED"
        assert prov["diagnostics"]["constant_offset_s"] is not None
        assert "DIAGNOSTIC ONLY" in prov["diagnostics"]["note"]
        assert rep["accepted_assumption"]["assumption_id"] == "BULK_PULL_AVAILABILITY_V1"


@pytest.fixture(scope="module")
def ok_run_manifested(tmp_path_factory):
    base = tmp_path_factory.mktemp("okm")
    coll = base / "coll"
    write(coll, minutes=180)
    subprocess.run([sys.executable, str(PRESERVE), str(coll), str(coll / "prior_bars.json"), str(base / "d")],
                   cwd=REPO, capture_output=True, text=True)
    r = run_driver(base / "d" / "collection", base / "runs", "okm",
                   manifest=base / "d" / "INPUTS_MANIFEST.json", prior=base / "d" / "prior_bars.json")
    assert r.returncode == 0, r.stderr[-3000:]
    return {"out": base / "runs", "run_id": "okm"}


class TestTheFitBudgetIsTheRunsBudget:

    def test_the_driver_pins_three_not_the_constructor_default(self):
        """Checked on the CODE. The comment explains why 400 is wrong for this run, so a prose scan would trip on
        the explanation itself."""
        import ast
        tree = ast.parse(DRIVER.read_text())
        assigns = {t.id: n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                   for t in n.targets if isinstance(t, ast.Name)}
        assert isinstance(assigns.get("FIT_BUDGET"), ast.Constant) and assigns["FIT_BUDGET"].value == 3
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "FunnelEngine"]
        assert calls and all(any(k.arg == "fit_budget" for k in c.keywords) for c in calls), \
            "every FunnelEngine in the driver must be given this run's budget explicitly"

    def test_three_is_the_exact_maximum_one_fit_call_can_consume(self):
        """GARCH, then the regime model, then the conditional EWMA fallback. Nothing else consumes the counter."""
        from apex.decision_wb.engine import FunnelEngine
        import inspect
        src = inspect.getsource(FunnelEngine.fit)
        assert src.count("self.fits += 1") == 2, "one per model in the loop, plus the fallback below"
        assert '("garch", lambda: GARCH()), ("regime", lambda: MarkovSwitching2' in src
        e = FunnelEngine(fit_budget=3)
        assert e.fit_budget == 3 and e.fits == 0

    def test_the_budget_is_reported_on_the_run(self, ok_run_manifested):
        assert result(ok_run_manifested["out"], ok_run_manifested["run_id"])["fit_budget"] == 3

    def test_the_engine_fitted_within_the_budget(self, ok_run_manifested):
        rows = ledger(ok_run_manifested["out"], ok_run_manifested["run_id"], "FULL_FUNNEL_V1")
        funnels = [r for r in rows if r["kind"] == "pilot_funnel"]
        assert funnels
        assert all(f["engine"]["fits"] <= 3 for f in funnels), [f["engine"]["fits"] for f in funnels]
        assert all(f["engine"]["fit_budget"] == 3 for f in funnels)


# ---------------------------------------------------------------------------- f4d2d20 findings


class TestProvenanceIsNotInferredFromTimestampShape:
    """Offsets are diagnostics. This class pins that; the attribution question is pinned by
    TestAssignmentPathIsNotArtifactAttribution below."""

    from apex.options_pilot import provenance as P

    def test_varied_offsets_alone_establish_nothing(self):
        varied = [{"event_time": 10.0 * i, "receipt_time": 10.0 * i + 3.0 + (i % 7) * 0.31} for i in range(60)]
        got = self.P.classify("fabricated_but_varied", varied, assignment_key=None)
        assert got["assignment_path_evidence"]["status"] == self.P.PATH_NOT_CLAIMED
        assert got["artifact_execution_attribution"]["status"] == self.P.UNVERIFIED
        assert got["diagnostics"]["n_distinct_offsets"] > 1, "the fixture really does vary"
        assert "DIAGNOSTIC ONLY" in got["diagnostics"]["note"]

    def test_constant_offsets_alone_veto_nothing(self):
        constant = [{"event_time": 10.0 * i, "receipt_time": 10.0 * i + 60.0} for i in range(60)]
        got = self.P.classify("constant_but_named", constant, assignment_key="alpaca_bar_receipt")
        assert got["assignment_path_evidence"]["status"] == self.P.MARKER_PRESENT, \
            "a constant offset must not veto what the source actually says"
        assert got["diagnostics"]["constant_offset_s"] == 60.0

    def test_the_source_claim_comes_from_the_named_path(self):
        got = self.P.classify("session_bars", [{"event_time": 1.0, "receipt_time": 2.0}],
                              assignment_key="alpaca_bar_receipt")
        assert got["assignment_path_evidence"]["file"].endswith("providers.py")
        assert got["assignment_path_evidence"]["marker"] in \
            (REPO / got["assignment_path_evidence"]["file"]).read_text()

    def test_a_claim_dies_when_its_marker_leaves_the_code(self, monkeypatch):
        spec = dict(self.P.ASSIGNMENT_PATHS["alpaca_bar_receipt"])
        monkeypatch.setitem(self.P.ASSIGNMENT_PATHS, "alpaca_bar_receipt",
                            {**spec, "marker": "this text is not in the file"})
        got = self.P.classify("x", [{"event_time": 1.0, "receipt_time": 2.0}], assignment_key="alpaca_bar_receipt")
        assert got["assignment_path_evidence"]["status"] == self.P.MARKER_ABSENT
        assert got["timestamp_semantics"]["status"] == "UNKNOWN"

    def test_an_absent_receipt_is_reported_as_absent(self):
        got = self.P.classify("x", [{"event_time": 1.0}], assignment_key="alpaca_bar_receipt")
        assert got["availability_basis"] == self.P.ABSENT

    def test_the_run_reports_the_two_artifacts_differently(self, ok_run_manifested):
        rep = result(ok_run_manifested["out"], ok_run_manifested["run_id"])["input_report"]
        assert rep["session_bars_provenance"]["availability_basis"] == "PER_RECORD_RECORDED"
        assert rep["prior_bars_provenance"]["availability_basis"] == "DERIVED_BY_FORMULA"
        assert rep["prior_bars_provenance"]["diagnostics"]["n_distinct_offsets"] == 1


class TestTheAssumptionMustBeAcceptedNotMerelyRequired:
    """Finding 1b: `assumption_required: true` reported a requirement and then used the rows anyway."""

    from apex.options_pilot import provenance as P

    def test_no_authorization_refuses_before_any_model(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=60)
        r = run_driver(coll, tmp_path / "runs", "noauth", no_authz=True)
        assert r.returncode != 0
        assert "ACCEPTANCE_MISSING" in (r.stdout + r.stderr)
        body = json.loads((tmp_path / "runs" / "noauth" / "RUN_FAILED.json").read_text())
        assert body["summary"]["stage"] == "INPUT_VALIDATION"

    def test_a_different_assumption_id_refuses(self, tmp_path):
        with pytest.raises(self.P.ProvenanceRefused, match="ASSUMPTION_NOT_ACCEPTED"):
            self.P.require_accepted("BULK_PULL_AVAILABILITY_V1",
                                    {"accepted_assumptions": [{"id": "SOMETHING_ELSE", "text": "x"}]})

    def test_different_words_refuse(self, tmp_path):
        with pytest.raises(self.P.ProvenanceRefused, match="ASSUMPTION_TEXT_MISMATCH"):
            self.P.require_accepted("BULK_PULL_AVAILABILITY_V1",
                                    {"accepted_assumptions": [{"id": "BULK_PULL_AVAILABILITY_V1",
                                                               "text": "close enough"}]})

    def test_whitespace_differences_are_tolerated_but_wording_is_not(self):
        text = self.P.assumption_text("BULK_PULL_AVAILABILITY_V1")
        got = self.P.require_accepted("BULK_PULL_AVAILABILITY_V1",
                                      {"accepted_assumptions": [{"id": "BULK_PULL_AVAILABILITY_V1",
                                                                 "text": "  " + text.replace(" ", "  ") + "\n"}]})
        assert got["accepted"] is True

    def test_an_unknown_assumption_id_refuses(self):
        with pytest.raises(self.P.ProvenanceRefused, match="ASSUMPTION_UNKNOWN"):
            self.P.assumption_text("NOT_DECLARED_ANYWHERE")

    def test_the_accepted_text_is_bound_into_the_run(self, ok_run_manifested):
        res = result(ok_run_manifested["out"], ok_run_manifested["run_id"])
        acc = res["accepted_assumptions"]
        assert len(acc) == 1 and acc[0]["assumption_id"] == "BULK_PULL_AVAILABILITY_V1"
        assert acc[0]["text"] == self.P.assumption_text("BULK_PULL_AVAILABILITY_V1")
        assert acc[0]["accepted_by"].startswith("SYNTHETIC_TEST_FIXTURE")

    def test_the_repository_authors_no_operator_acceptance(self):
        """Reading an acceptance and REPORTING it is fine; CONSTRUCTING one is not. The check is for a literal
        acceptance being built in shipped code, not for the words appearing anywhere."""
        import pathlib
        for p in list(pathlib.Path("apex").rglob("*.py")) + list(pathlib.Path("scripts").rglob("*.py")):
            txt = p.read_text()
            assert '"accepted_assumptions": [{' not in txt, "%s constructs an acceptance literal" % p
            if p.name != "provenance.py":
                assert self.P.ASSUMPTIONS["BULK_PULL_AVAILABILITY_V1"][:40] not in txt, \
                    "%s restates the assumption text instead of referring to the one declaration" % p
        assert "Nothing in this repository may write it" in pathlib.Path("apex/options_pilot/provenance.py").read_text()
        # and the manifest the preservation tool writes carries no acceptance
        assert "accepted_assumptions" not in pathlib.Path("scripts/preserve_inputs.py").read_text()


class TestTheManifestIsCapturedOnceInsideTheBoundary:
    """Finding 2 at f4d2d20: the manifest was parsed before the run directory was claimed, and read twice."""

    def test_the_run_directory_is_claimed_before_the_manifest_is_opened(self):
        src = DRIVER.read_text()
        assert src.index("RUN = RD.new_run(") < src.index("MANIFEST_CAPTURE = _capture(MANIFEST)")

    def test_a_missing_manifest_still_leaves_a_failure_record(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=30)
        r = run_driver(coll, tmp_path / "runs", "nomani", manifest=tmp_path / "does_not_exist.json")
        assert r.returncode != 0
        d = tmp_path / "runs" / "nomani"
        assert (d / "RUN_START.json").exists() and (d / "RUN_FAILED.json").exists()
        assert "FileNotFoundError" in json.loads((d / "RUN_FAILED.json").read_text())["error"]

    def test_a_malformed_manifest_still_leaves_a_failure_record(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=30)
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        r = run_driver(coll, tmp_path / "runs", "badmani", manifest=bad)
        assert r.returncode != 0
        body = json.loads((tmp_path / "runs" / "badmani" / "RUN_FAILED.json").read_text())
        assert "JSONDecodeError" in body["error"] or "Expecting" in body["error"]

    def test_the_manifest_is_read_exactly_once(self):
        src = DRIVER.read_text()
        assert src.count("_capture(MANIFEST)") == 1
        assert "json.loads(MANIFEST.read_text())" not in src
        assert "SELF_DECLARED_FROM_THE_FILES_READ" not in src, "the obsolete reread block must be gone"

    def test_replacing_the_manifest_after_capture_changes_nothing(self, tmp_path):
        """The recorded declaration must be the captured one. Since the file is opened once and never reopened,
        a later replacement cannot reach the run; the digest on the record proves which bytes were used."""
        coll = tmp_path / "coll"
        write(coll, minutes=180)
        assert preserve(coll, tmp_path / "d").returncode == 0
        man = tmp_path / "d" / "INPUTS_MANIFEST.json"
        original = man.read_bytes()
        import hashlib
        expected = hashlib.sha256(original).hexdigest()
        r = run_driver(tmp_path / "d" / "collection", tmp_path / "runs", "cap", manifest=man,
                       prior=tmp_path / "d" / "prior_bars.json")
        assert r.returncode == 0, r.stderr[-2000:]
        man.write_text('{"inputs": {"chain": "%s"}}' % ("0" * 64))     # replace it AFTER the run
        rep = result(tmp_path / "runs", "cap")["input_report"]
        assert rep["manifest_capture"]["sha256"] == expected, "the run recorded the bytes it actually used"
        assert hashlib.sha256(man.read_bytes()).hexdigest() != expected, "the file on disk really did change"


# ---------------------------------------------------------------------------- 0fab0b6 findings


class TestAssignmentPathIsNotArtifactAttribution:
    """Finding 1 at 0fab0b6: a marker in today's source was being read as proof that particular records came from
    that code. It is not: a fabricated artifact handed over with the same key looks identical."""

    from apex.options_pilot import provenance as P

    def test_fabricated_rows_with_a_valid_key_do_not_gain_verified_attribution(self):
        fabricated = [{"event_time": 10.0 * i, "receipt_time": 10.0 * i + 3.0 + (i % 5) * 0.7} for i in range(40)]
        got = self.P.classify("fabricated", fabricated, assignment_key="alpaca_bar_receipt")
        assert got["assignment_path_evidence"]["status"] == self.P.MARKER_PRESENT
        assert got["artifact_execution_attribution"]["status"] == self.P.UNVERIFIED
        assert "fabricated artifact presented with the same assignment key" in \
            got["artifact_execution_attribution"]["why"]

    def test_the_two_fields_are_separate_and_neither_is_a_verdict_on_the_other(self):
        got = self.P.classify("x", [{"event_time": 1.0, "receipt_time": 2.0}], assignment_key="alpaca_bar_receipt")
        assert set(("assignment_path_evidence", "artifact_execution_attribution")) <= set(got)
        assert "MEASURED_BY_COLLECTOR" not in json.dumps(got), "the merged verdict is gone"
        assert got["assignment_path_evidence"]["scope"].startswith("this establishes only what the inspected source")

    def test_write_and_parse_time_are_not_network_receipt(self):
        for key, expect in (("pilot_collection_record", "WRITE_TIME"), ("alpaca_bar_receipt", "PARSE_TIME")):
            got = self.P.classify("x", [{"event_time": 1.0, "receipt_time": 2.0}], assignment_key=key)
            assert got["timestamp_semantics"]["measures"] == expect
            assert "network receipt" in got["timestamp_semantics"]["not"]

    def test_the_run_reports_both_fields_for_both_artifacts(self, ok_run_manifested):
        rep = result(ok_run_manifested["out"], ok_run_manifested["run_id"])["input_report"]
        for k in ("session_bars_provenance", "prior_bars_provenance"):
            assert rep[k]["artifact_execution_attribution"]["status"] == "UNVERIFIED", k
        assert rep["session_bars_provenance"]["assignment_path_evidence"]["status"] == "MARKER_PRESENT"
        assert rep["prior_bars_provenance"]["assignment_path_evidence"]["status"] == "NO_ASSIGNMENT_PATH_CLAIMED"
        assert rep["session_bars_provenance"]["availability_basis"] == "PER_RECORD_RECORDED"
        assert rep["prior_bars_provenance"]["availability_basis"] == "DERIVED_BY_FORMULA"


class TestTheAcceptedFormulaIsTheComputationUsed:
    """Finding 2 at 0fab0b6: the acceptance said event_time + 60 while the driver gated on each row's supplied
    receipt. Accepting one thing and computing another is not an accepted assumption."""

    from apex.options_pilot import provenance as P

    def test_the_derived_field_is_computed_and_the_source_is_preserved(self):
        got = self.P.apply_bulk_pull_availability([{"event_time": 100.0, "receipt_time": 160.0, "close": 1.0}])
        row = got["rows"][0]
        assert row[self.P.ASSUMED_FIELD] == 160.0 and row[self.P.SOURCE_FIELD] == 160.0
        assert row["availability_assumption"] == "BULK_PULL_AVAILABILITY_V1"
        assert row["close"] == 1.0, "the rest of the row is untouched"

    def test_a_row_inconsistent_with_the_formula_refuses(self):
        with pytest.raises(self.P.ProvenanceRefused, match="ASSUMED_AVAILABILITY_INCONSISTENT"):
            self.P.apply_bulk_pull_availability([{"event_time": 100.0, "receipt_time": 160.0},
                                                 {"event_time": 200.0, "receipt_time": 275.0}])

    def test_the_driver_refuses_a_collection_whose_prior_receipts_disagree(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=60, prior_receipt_lag=75.0)          # the artifact says +75, the acceptance says +60
        r = run_driver(coll, tmp_path / "runs", "lagmismatch")
        assert r.returncode != 0 and "ASSUMED_AVAILABILITY_INCONSISTENT" in (r.stdout + r.stderr)
        body = json.loads((tmp_path / "runs" / "lagmismatch" / "RUN_FAILED.json").read_text())
        assert body["summary"]["stage"] == "INPUT_VALIDATION"

    def test_a_missing_event_time_refuses_rather_than_guessing(self):
        with pytest.raises(self.P.ProvenanceRefused, match="ASSUMED_AVAILABILITY_NEEDS_EVENT_TIME"):
            self.P.apply_bulk_pull_availability([{"receipt_time": 1.0}])

    def test_the_run_gates_prior_bars_on_the_derived_value(self, ok_run_manifested):
        rep = result(ok_run_manifested["out"], ok_run_manifested["run_id"])["input_report"]
        a = rep["assumed_availability"]
        assert a["assumption_id"] == "BULK_PULL_AVAILABILITY_V1" and a["offset_s"] == 60.0
        assert a["derived_field"] == "assumed_available_time" and a["source_field_preserved"] == "source_receipt_time"
        assert "a disagreement would have refused the run" in a["checked"]

    def test_the_driver_gates_bars_on_available_time_not_a_raw_receipt(self):
        src = DRIVER.read_text()
        assert 'b["available_time"] <= self.t' in src
        assert 'b["receipt_time"] <= self.t' not in src


class TestTheAcceptanceDocumentIsBoundAndItsLimitsStated:
    """Finding 3 at 0fab0b6: the acceptance checked only the assumption text, and the schema bound to nothing."""

    from apex.options_pilot import provenance as P

    def _doc(self, **over):
        d = {"accepted_by": "x", "accepted_utc": "2026-09-12T00:00:00Z", "evaluation_id": "FLOW-VALIDATION-001",
             "input_manifest_sha256": "a" * 64, "code_pin": "b" * 40, "scope": "one diagnostic",
             "accepted_assumptions": [{"id": "BULK_PULL_AVAILABILITY_V1",
                                       "text": self.P.assumption_text("BULK_PULL_AVAILABILITY_V1")}]}
        d.update(over)
        return d

    def test_every_required_field_is_required(self):
        for field in self.P.ACCEPTANCE_REQUIRED_FIELDS:
            with pytest.raises(self.P.ProvenanceRefused, match="ACCEPTANCE_INCOMPLETE"):
                self.P.validate_acceptance(self._doc(**{field: None}), evaluation_id="FLOW-VALIDATION-001",
                                           manifest_sha256="a" * 64, code_pin="b" * 40)

    def test_it_binds_to_this_evaluation_manifest_and_pin(self):
        ok = dict(evaluation_id="FLOW-VALIDATION-001", manifest_sha256="a" * 64, code_pin="b" * 40)
        assert self.P.validate_acceptance(self._doc(), **ok)["code_pin"] == "b" * 40
        with pytest.raises(self.P.ProvenanceRefused, match="ACCEPTANCE_WRONG_EVALUATION"):
            self.P.validate_acceptance(self._doc(evaluation_id="SOMETHING-ELSE"), **ok)
        with pytest.raises(self.P.ProvenanceRefused, match="ACCEPTANCE_WRONG_MANIFEST"):
            self.P.validate_acceptance(self._doc(input_manifest_sha256="c" * 64), **ok)
        with pytest.raises(self.P.ProvenanceRefused, match="ACCEPTANCE_WRONG_CODE_PIN"):
            self.P.validate_acceptance(self._doc(code_pin="d" * 40), **ok)

    def test_authorship_is_described_as_procedural_not_authenticated(self):
        got = self.P.validate_acceptance(self._doc(), evaluation_id="FLOW-VALIDATION-001",
                                         manifest_sha256="a" * 64, code_pin="b" * 40)
        assert got["authorship"].startswith("PROCEDURAL_UNAUTHENTICATED")
        assert "Nothing here verifies who wrote it" in got["authorship"]
        assert got["accepted_by_claimed"] == "x", "recorded as a CLAIM, and named as one"

    def test_a_manifest_mismatch_refuses_the_real_run(self, tmp_path):
        coll = tmp_path / "coll"
        write(coll, minutes=60)
        assert preserve(coll, tmp_path / "d").returncode == 0
        bad = synthetic_authorization(tmp_path / "bad_authz.json", manifest=None)   # names a manifest digest of zeros
        r = run_driver(tmp_path / "d" / "collection", tmp_path / "runs", "badman",
                       manifest=tmp_path / "d" / "INPUTS_MANIFEST.json", prior=tmp_path / "d" / "prior_bars.json",
                       authz=bad)
        assert r.returncode != 0 and "ACCEPTANCE_WRONG_MANIFEST" in (r.stdout + r.stderr)

    def test_the_template_exists_and_is_not_filled_in(self):
        from pathlib import Path as P_
        t = json.loads(P_("docs/FLOW_VALIDATION_001_ACCEPTANCE_TEMPLATE.json").read_text())
        for field in ("accepted_by", "accepted_utc", "input_manifest_sha256", "code_pin", "scope"):
            assert str(t[field]).startswith("<FILL IN"), "%s is pre-filled; the template must stay unpopulated" % field
        assert t["accepted_assumptions"][0]["text"].startswith("<FILL IN")
        assert any("who wrote it" in line for line in t["_README"])

    def test_the_run_records_the_acceptance_and_its_boundary(self, ok_run_manifested):
        acc = result(ok_run_manifested["out"], ok_run_manifested["run_id"])["input_report"]["acceptance"]
        assert acc["evaluation_id"] == "FLOW-VALIDATION-001"
        assert acc["authorship"].startswith("PROCEDURAL_UNAUTHENTICATED")
        assert acc["accepted_by_claimed"].startswith("SYNTHETIC_TEST_FIXTURE")
