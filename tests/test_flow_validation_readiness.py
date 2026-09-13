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


def run_driver(coll: Path, out_base: Path, run_id: str, *, manifest: Path | None = None, prior: Path | None = None,
               no_manifest: bool = False):
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

    def test_a_formulaic_receipt_is_reported_as_not_measured(self, ok_run_manifested):
        """The prior-bar artifact's receipt is a constant offset from event time across every row, which is a
        computed value from a bulk pull, not a recorded receipt. It must be labelled, not used silently."""
        rep = result(ok_run_manifested["out"], ok_run_manifested["run_id"])["input_report"]
        av = rep["prior_bars_availability"]
        assert av["status"] == "FORMULAIC_NOT_MEASURED" and av["assumption_required"] is True
        assert "not a recorded receipt" in av["why"]

    def test_a_measured_receipt_is_reported_as_measured(self):
        from scripts import preserve_inputs  # noqa: F401  (import guard only)
        import importlib.util
        spec = importlib.util.spec_from_file_location("drv_helpers", DRIVER)
        # availability_class is defined before argv parsing fails, so read it out of the source instead
        ns = {}
        src = DRIVER.read_text()
        start = src.index("def availability_class")
        end = src.index("D, PRIOR, BASE")
        exec(compile(src[start:end], "drv", "exec"), ns)
        measured = [{"event_time": 10.0 * i, "receipt_time": 10.0 * i + 3.0 + (i % 4)} for i in range(50)]
        assert ns["availability_class"](measured)["status"] == "MEASURED"
        assert ns["availability_class"]([{"event_time": 1.0}])["status"] == "ABSENT"


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
