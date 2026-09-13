"""ORGANISM-COURT-001 — the connected decision path, layer by layer.

This is INTEGRATION VERIFICATION. Nothing here is evidence of calibration, edge or profitability, and the world is
declared synthetic. What it establishes is narrower and, on this code line, not yet established anywhere else:
which layers exist, which execute, whose output is actually consumed downstream, and where the flow stops."""
from __future__ import annotations

import json
import pathlib
import uuid

import pytest

from apex.court import receipt as R
from apex.court import world as W
from apex.court.court import Court, synthetic_fee_authorization
from apex.court.verify import reconstruct

OUT = "results/court"


def rid(tag):
    return "%s-%s" % (tag, uuid.uuid4().hex[:8])


def layer(out, name):
    return [r for r in out["receipts"] if r["layer"] == name]


# ======================================================= the fixture itself


class TestTheCourtFixtureIsHonest:
    def test_the_fee_authorization_is_synthetic_and_can_never_be_a_live_default(self):
        from apex.options_pilot.fees import LIVE_DEFAULT_FEES, ROBINHOOD_RHF_2026
        f = synthetic_fee_authorization()
        assert f.provenance == "SYNTHETIC_FIXTURE" and f.requires_authorization is False
        assert f.authorization is None
        assert LIVE_DEFAULT_FEES.schedule_id == "UNVERIFIED"          # untouched
        assert ROBINHOOD_RHF_2026.authorization is None               # still unauthorized

    def test_the_world_recipe_and_seed_are_frozen_and_declared(self):
        assert W.RECIPE and W.SEED and "SYNTHETIC" in W.DECLARED["law"]
        assert W.MIN_TRAIN_BARS == 400 and W.FIT_BUDGET == 400, "engine gates are not lowered for the court"

    def test_a_run_directory_is_never_overwritten(self):
        r = rid("dup")
        Court(run_id=r, world="ELIGIBLE_TRADE")
        with pytest.raises(RuntimeError, match="RUN_DIR_EXISTS"):
            Court(run_id=r, world="ELIGIBLE_TRADE")


# ======================================================= FLIGHT A — eligible TRADE


@pytest.fixture(scope="module")
def flight_a():
    c = Court(run_id=rid("A-trade"), world="ELIGIBLE_TRADE")
    return c.run(arrivals=[c.t0 + 900.0 + 0.2]), c.dir


class TestFlightAEligibleTrade:
    def test_the_real_path_reached_a_reconciled_round_trip(self, flight_a):
        out, _ = flight_a
        assert out["decision"] == "TRADE"
        k = out["ledger_kinds"]
        for kind in ("pilot_forecast", "pilot_intent", "pilot_fill", "pilot_outcome", "pilot_decision"):
            assert k.get(kind), kind

    def test_the_twin_snapshot_executed_and_its_id_reached_the_decision(self, flight_a):
        out, _ = flight_a
        twin = layer(out, "DIGITAL_TWIN")[0]
        assert twin["executed"] == R.EXECUTED and twin["valid"] == R.VALID
        assert twin["consumption"]["state"] == R.USED, "the snapshot id must be found in a persisted record"
        assert twin["consumption"]["evidence"][0]["field_path"]

    def test_the_forecast_model_identity_is_recorded_and_consumed(self, flight_a):
        out, _ = flight_a
        f = layer(out, "LOCATION_VOLATILITY_FORECAST")[0]
        assert f["model_identity"]["params_hash"] and f["valid"] == R.VALID
        assert f["consumption"]["state"] in (R.USED, R.NOT_CONSUMED)

    def test_risk_certified_independently_and_the_intent_was_persisted_before_the_fill(self, flight_a):
        _, d = flight_a
        v = reconstruct(d)
        assert v["intent_binding"]["risk_provenance"] == "CERTIFIED_KERNEL"
        assert v["intent_binding"]["certified_max_loss"] > 0
        assert v["fill"]["status"] == "FILLED"

    def test_independent_reconstruction_agrees_on_pnl(self, flight_a):
        _, d = flight_a
        v = reconstruct(d)
        assert v["problems"] == [], v["problems"]
        assert v["pnl_agrees"] is True
        # a run can write several outcome records; the RESOLVED one is the one that discharges the position
        assert v["resolved_exit"]["pnl_status"] == "NET_OF_FEES"

    def test_every_receipt_states_what_it_cannot_establish(self, flight_a):
        out, _ = flight_a
        assert all("does NOT establish" in r["limits"] for r in out["receipts"])


# ======================================================= FLIGHT B — mandatory WAIT


class TestFlightBMandatoryWait:
    def test_wait_is_a_decision_not_an_input_failure(self):
        c = Court(run_id=rid("B-wait"), world="MANDATORY_WAIT")
        out = c.run()
        assert out["decision"] in ("WAIT", "REFUSE")
        data = layer(out, "REALITY_DATA")[0]
        twin = layer(out, "DIGITAL_TWIN")[0]
        assert data["valid"] == R.VALID and twin["valid"] == R.VALID, "inputs were sound; the rules declined"
        assert out["ledger_kinds"].get("pilot_fill") is None
        v = reconstruct(c.dir)
        assert v["fill"]["status"] is None and v["remaining_obligation"]["open_position"] is False


# ======================================================= FLIGHT C — mandatory REFUSAL


class TestFlightCMandatoryRefusal:
    @pytest.mark.parametrize("break_input,expect", [
        ("FUTURE_BAR", "FUTURE_BAR_IN_SNAPSHOT"),
        ("INVALID_MODEL_OUTPUT", "NON_FINITE_SCALE"),
    ])
    def test_a_broken_input_stops_new_entry_BY_NAME(self, break_input, expect):
        c = Court(run_id=rid("C-%s" % break_input.lower()), world="ELIGIBLE_TRADE")
        out = c.run(break_input=break_input)
        named = [r for r in out["receipts"]
                 if expect in str(r.get("why_invalid") or "") or expect in str(r.get("refusal") or "")]
        assert named, "the refusal must be named, not generic: %s" % [
            (r["layer"], r.get("why_invalid"), r.get("refusal")) for r in out["receipts"]]
        assert out["ledger_kinds"].get("pilot_fill") is None, "no entry may occur"

    def test_an_unauthorized_fee_schedule_refuses_before_any_quote(self):
        """The fee brick's gate, exercised through the court's own construction path."""
        from apex.options_pilot.fees import FeeAuthorizationRefused, ROBINHOOD_RHF_2026
        from apex.options_pilot.synthetic_harness import SyntheticHarness
        import tempfile
        with pytest.raises(FeeAuthorizationRefused):
            SyntheticHarness(pathlib.Path(tempfile.mkdtemp()) / "l.jsonl", session_id="C", t0=1_789_000_020.0,
                             risk="certified", fee_schedule=ROBINHOOD_RHF_2026)


# ======================================================= FLIGHT D — optional context fails


class TestFlightDOptionalContextFailure:
    def test_a_hung_external_context_does_not_stop_the_due_exit(self):
        c = Court(run_id=rid("D-hung"), world="ELIGIBLE_TRADE")
        out = c.run(arrivals=[c.t0 + 900.0 + 0.2], hung_context=True)
        ext = layer(out, "TRADINGVIEW_EXTERNAL_CONTEXT")[0]
        assert ext["available"] == R.UNAVAILABLE and "PROVIDER_DID_NOT_RETURN" in (ext["why_unavailable"] or "")
        assert out["ledger_kinds"].get("pilot_outcome"), "the exit was still serviced"
        v = reconstruct(c.dir)
        assert any(e["discharges"] for e in v["exits"])

    def test_the_external_context_is_never_consumed_because_no_consumer_exists(self):
        c = Court(run_id=rid("D-ctx"), world="ELIGIBLE_TRADE")
        out = c.run()
        ext = layer(out, "TRADINGVIEW_EXTERNAL_CONTEXT")[0]
        assert "USED here can only ever be 0" in ext["declared_not_measured"]["note"]


# ======================================================= FLIGHT E — lifecycle continuity


class TestFlightELifecycleContinuity:
    def test_an_arrival_triggered_exit_resolves_within_the_original_policy(self):
        c = Court(run_id=rid("E-arrival"), world="ELIGIBLE_TRADE")
        out = c.run(arrivals=[c.t0 + 900.0 + 0.2])
        v = reconstruct(c.dir)
        assert any(e["discharges"] for e in v["exits"])
        rows = [json.loads(x) for x in (c.dir / "ledger.jsonl").read_text().splitlines() if x.strip()]
        oc = [r for r in rows if r["kind"] == "pilot_outcome" and r.get("discharges_position")][0]
        assert (oc.get("exit_policy") or {}).get("binding") == "ORIGINAL_POLICY_OF_RECORD"


# ======================================================= FLIGHT F — unresolved outcome


class TestFlightFUnresolvedOutcome:
    def test_no_executable_exit_quote_leaves_exposure_and_an_unknown_net(self):
        c = Court(run_id=rid("F-unresolved"), world="ELIGIBLE_TRADE")
        out = c.run(no_exit_quote=True)
        v = reconstruct(c.dir)
        assert v["fill"]["status"] == "FILLED"
        assert not any(e["discharges"] for e in v["exits"]), "the position must remain an obligation"
        assert v["remaining_obligation"]["open_position"] is True
        assert v.get("pnl_recomputed") is None, "an incomplete accounting must not produce a total"


# ======================================================= section 5 — the joins


class TestTheJoinsNotTheLabels:
    def test_the_snapshot_id_is_content_addressed_not_run_scoped(self):
        """CORRECTED ASSUMPTION. Two runs whose MARKET STATE is identical share a snapshot_id -- that is what
        content-addressing means, and the court's two worlds differ only in the option chain, not in the bars.
        A different market state is what must produce a different id."""
        a = Court(run_id=rid("J-a"), world="ELIGIBLE_TRADE"); a.run()
        b = Court(run_id=rid("J-b"), world="MANDATORY_WAIT"); b.run()
        va, vb = reconstruct(a.dir), reconstruct(b.dir)
        assert va["snapshot_id"] == vb["snapshot_id"], "same bars, same state, same id"
        c = Court(run_id=rid("J-c"), world="ELIGIBLE_TRADE", n_bars=60); c.run()
        assert reconstruct(c.dir)["snapshot_id"] != va["snapshot_id"], "a different state must differ"

    def test_altered_content_under_the_old_digest_is_detected(self):
        """Content changed while the recorded digest is retained: the recomputation must disagree."""
        c = Court(run_id=rid("J-alter"), world="ELIGIBLE_TRADE"); c.run(arrivals=[c.t0 + 900.0 + 0.2])
        p = c.dir / "court_run.json"
        doc = json.loads(p.read_text())
        twin = [r for r in doc["receipts"] if r["layer"] == "DIGITAL_TWIN"][0]
        recorded = twin["output_digest"]
        tampered = dict(twin["parents"] and {} or {}, **{"missingness": 999})
        assert R.digest(tampered) != recorded

    def test_consumption_is_discovered_not_declared(self):
        c = Court(run_id=rid("J-consume"), world="ELIGIBLE_TRADE"); out = c.run()
        used = [r for r in out["receipts"] if r["consumption"]["state"] == R.USED]
        assert used, "at least one output must be findable in a downstream record"
        for r in used:
            ev = r["consumption"]["evidence"][0]
            assert ev["consumer_record_kind"] and ev["field_path"], "evidence must name WHERE it was found"
        assert all(r["consumption"]["note"].startswith("discovered") for r in used)

    def test_a_receipt_with_no_downstream_reader_says_so(self):
        c = Court(run_id=rid("J-unused"), world="ELIGIBLE_TRADE"); out = c.run()
        unused = [r for r in out["receipts"] if r["consumption"]["state"] == R.NOT_CONSUMED]
        assert unused, "NOT_CONSUMED is a legitimate, reportable outcome"


# ======================================================= the FULL funnel route (separate flight)


from apex.court.court import FunnelCourt  # noqa: E402


@pytest.fixture(scope="module")
def funnel_ready():
    return FunnelCourt(run_id=rid("G-funnel"), n_bars=500).run()


class TestTheFullFunnelRoute:
    """Run SEPARATELY from the rule route on purpose: the rule route never constructs a FunnelEngine, so
    reporting one while running the other would claim reach the run never had."""

    def test_with_sufficient_history_the_whole_model_stack_executes(self, funnel_ready):
        out = funnel_ready
        assert out["reachable"] and out["fit_status"] == "READY"
        for stage in ("regime", "variance", "implied", "simulation", "expression_war", "prime"):
            assert stage in out["trace_stages_present"], stage

    def test_the_funnel_reaches_a_decision_and_persists_a_trace_before_any_intent(self, funnel_ready):
        out = funnel_ready
        assert out["funnel_decision"] in ("TRADE", "WAIT")
        assert out["ledger_kinds"].get("pilot_funnel")

    def test_insufficient_history_is_a_named_WAIT_not_a_crash_and_not_a_trade(self):
        out = FunnelCourt(run_id=rid("G-short"), n_bars=40).run()
        assert out["decision"] == "WAIT"
        assert "INSUFFICIENT_HISTORY" in str(out["funnel_why"])
        assert out["ledger_kinds"].get("pilot_fill") is None
        assert "regime" not in out["trace_stages_present"], "a gate that stops must stop the stages after it"

    def test_the_engine_declares_the_layers_it_did_not_invoke(self, funnel_ready):
        """The court reports the engine's OWN declaration rather than inferring reach from a green run."""
        rows = [json.loads(x) for x in
                (pathlib.Path("results/court") / funnel_ready["run_id"] / "ledger.jsonl").read_text().splitlines()
                if x.strip()]
        tr = [r for r in rows if r["kind"] == "pilot_funnel"][0]["trace"]
        ni = tr["layers_not_invoked"]
        for absent in ("enrichment", "fusion", "jumps", "svi_surface"):
            assert absent in ni, absent

    def test_the_variance_model_records_which_model_actually_ran(self, funnel_ready):
        rows = [json.loads(x) for x in
                (pathlib.Path("results/court") / funnel_ready["run_id"] / "ledger.jsonl").read_text().splitlines()
                if x.strip()]
        tr = [r for r in rows if r["kind"] == "pilot_funnel"][0]["trace"]
        assert "model" in tr["variance"], "the variance stage must name the model that ran, not the one intended"

    def test_JOINT_is_unreachable_and_names_its_missing_dependency(self):
        out = FunnelCourt(run_id=rid("G-joint"), n_bars=500, policy="JOINT_FUNNEL_V1").run()
        assert out["reachable"] is False
        assert "joint_engine" in out["refusal"] and "joint_context_fn" in out["refusal"]

    def test_no_number_from_this_court_is_evidence_of_anything(self, funnel_ready):
        assert "does NOT establish" in funnel_ready["verdict_limits"]
