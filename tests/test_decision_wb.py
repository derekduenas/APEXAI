"""M5 — fusion, PRIME-late supervision, experience/attribution, enrichment schema. Synthetic only."""
import numpy as np
import pytest

from apex.decision_wb import enrichment as EN, experience as EX, fusion as FU, supervision as SV
from apex.multiverse_wb import expression_war as EW, pricing as PR, simulator as SIM
from apex.options_pilot import ledger as L, session as S
from apex.options_pilot.synthetic_harness import SyntheticHarness
from apex.worldmodel_wb.contracts import ForecastObject

T0 = 1_789_000_000.0


def _fo(mid, mu, sig, cutoff=T0, horizon=15, family="GAUSSIAN"):
    return ForecastObject(model_id=mid, artifact_digest="d-" + mid, horizon_minutes=horizon, input_cutoff_epoch=cutoff, created_epoch=cutoff + 1,
                          supplies=("mean", "variance", "density"), mean=mu, variance=sig ** 2,
                          density={"family": family, "location": mu, "variance": sig ** 2, "scale": sig, "nu": 6.0})


# ================================================================== fusion

def test_fusion_weights_are_estimated_out_of_fold_frozen_and_compared_to_the_strongest_single():
    rng = np.random.default_rng(3)
    n = 600
    truth_mu = rng.normal(0, 3e-4, n); y = truth_mu + rng.normal(0, 2e-4, n)
    good = [(m + rng.normal(0, 1e-4), 2.2e-4) for m in truth_mu]                # informative, roughly calibrated
    flat = [(0.0, 3.6e-4) for _ in range(n)]                                   # unconditional
    noise = [(rng.normal(0, 5e-4), 2e-4) for _ in range(n)]                     # uninformative and overconfident
    oof = [{"y": y[i], "components": [good[i], flat[i], noise[i]]} for i in range(n)]
    w = FU.estimate_weights(oof)
    assert w["frozen"] and abs(sum(w["weights"]) - 1) < 1e-9 and w["weights"][0] > 0.6 and w["weights"][2] < 0.15
    assert w["strongest_single"] == 0 and w["improvement_over_strongest_single"] >= -1e-9
    assert set(w["loo_ablation_log_score"]) == {"0", "1", "2"} and w["loo_contribution"]["0"] > w["loo_contribution"]["2"]
    fused = FU.fuse([_fo("good", 2e-4, 2.2e-4), _fo("flat", 0.0, 3.6e-4), _fo("noise", -4e-4, 2e-4)], w, created_epoch=T0 + 2)
    assert fused.density()["family"] == "GAUSSIAN_MIXTURE" and 0 < fused.meta["p_return_gt_zero"] < 1
    assert fused.meta["p_meaning"].startswith("P(target return > 0)") and fused.meta["lineage"][0] == ("good", "d-good")
    with pytest.raises(FU.FusionRefused, match="WEIGHTS_DIGEST_DISAGREES"):
        FU.fuse([_fo("a", 0, 1e-4), _fo("b", 0, 1e-4), _fo("c", 0, 1e-4)], {**w, "weights": [0.5, 0.3, 0.2]}, created_epoch=T0 + 2)
    with pytest.raises(FU.FusionRefused, match="HORIZON_MISMATCH"):
        FU.check_compatible([_fo("a", 0, 1e-4), _fo("b", 0, 1e-4, horizon=30)])
    with pytest.raises(FU.FusionRefused, match="CUTOFF_MISMATCH"):
        FU.check_compatible([_fo("a", 0, 1e-4), _fo("b", 0, 1e-4, cutoff=T0 + 60)])
    mean_only = ForecastObject(model_id="m", artifact_digest="d", horizon_minutes=15, input_cutoff_epoch=T0, created_epoch=T0, supplies=("mean",), mean=0.0)
    with pytest.raises(FU.FusionRefused, match="SUPPLIES_NO_DENSITY"):
        FU.check_compatible([_fo("a", 0, 1e-4), mean_only])


# ================================================================== supervision

def _comparison(established=True, spread_rel=0.04, exp_pnl=5.0):
    return {"candidates": [{"label": "WAIT", "status": "ELIGIBLE", "expected_net_pnl": 0.0},
                           {"label": "ATM_CALL", "status": "ELIGIBLE", "expected_net_pnl": exp_pnl, "entry_spread_rel": spread_rel,
                            "expected_value_established": established}],
            "expected_value_note": "IV fixed" if not established else "declared IV process"}


def test_supervision_abstains_for_each_named_reason_and_acts_only_when_all_prerequisites_hold():
    f = FU.fuse([_fo("a", 1e-4, 2e-4), _fo("b", 1.2e-4, 2e-4)], {"weights": [0.5, 0.5], "frozen": True,
                                                                  "weights_digest": FU.digest({"w": [0.5, 0.5]})}, created_epoch=T0 + 1)
    snap = {"fields": {"last_bar_age_s": {"value": 30.0}}}
    risk_ok = {"approved": True}; book_ok = {"integrity_problems": []}
    act = SV.supervise(forecast=f, snapshot=snap, comparison=_comparison(), risk_decision=risk_ok, book_summary=book_ok, candidate_label="ATM_CALL")
    assert act["decision"] == "ACT" and act["confidence"]["meaning"].startswith("P(target return > 0)") and act["authority"].startswith("NONE")
    cases = [
        (dict(snapshot={"fields": {"last_bar_age_s": {"value": 500.0}}}), "STALE_DATA"),
        (dict(regime={"abstain": True, "abstain_why": "HIGH_ENTROPY"}), "UNSUPPORTED_STATE"),
        (dict(comparison=_comparison(spread_rel=0.4)), "QUOTE_UNCERTAINTY"),
        (dict(comparison=_comparison(established=False)), "VALUE_UNESTABLISHED"),
        (dict(comparison=_comparison(exp_pnl=-1.0)), "INSUFFICIENT_MARGIN"),
        (dict(risk_decision={"approved": False, "refusals": ["aggregate"]}), "RISK_LIMIT"),
        (dict(book_summary={"integrity_problems": ["FILL_DEBIT_DISAGREES"]}), "PREREQUISITE_MISSING"),
        (dict(comparison=None), "PREREQUISITE_MISSING"),
        (dict(candidate_label="NOPE"), "PREREQUISITE_MISSING"),
    ]
    for over, reason in cases:
        kw = dict(forecast=f, snapshot=snap, comparison=_comparison(), risk_decision=risk_ok, book_summary=book_ok, candidate_label="ATM_CALL")
        kw.update(over)
        r = SV.supervise(**kw)
        assert r["decision"] == "ABSTAIN" and any(x.startswith(reason) for x in r["reasons"]), (reason, r["reasons"])
    # disagreement: two components far apart relative to scale
    fd = FU.fuse([_fo("a", 8e-4, 2e-4), _fo("b", -8e-4, 2e-4)], {"weights": [0.5, 0.5], "frozen": True, "weights_digest": FU.digest({"w": [0.5, 0.5]})}, created_epoch=T0 + 1)
    r = SV.supervise(forecast=fd, snapshot=snap, comparison=_comparison(), risk_decision=risk_ok, book_summary=book_ok, candidate_label="ATM_CALL")
    assert any(x.startswith("MODEL_DISAGREEMENT") for x in r["reasons"])
    assert "confidence" in act and "policy_digest" in act["policy"]


# ================================================================== experience

def test_experience_join_is_immutable_and_attributes_or_stays_ambiguous(tmp_path):
    h = SyntheticHarness(tmp_path / "p.jsonl", risk="certified")
    src = h.sources(); src.pop("exit_quote_fn")
    d = S.scan(h.bd, symbol="SPY", seq=1, **src)
    fill = d["receipts"]["fill"]
    rec = L.read_all(h.ledger)[fill["seq"] - 1]
    h.t = rec["exit_schedule"]["exit_due_epoch"]
    h.exit_quotes.bid, h.exit_quotes.ask = 2.51, 2.6                                   # gross +1, net negative after fees
    S.resolve(h.bd, fill_receipt=fill, exit_quote_fn=h.exit_quotes)
    rows = L.read_all(h.ledger)
    before = h.ledger.read_text()
    fc = [r for r in rows if r["kind"] == "pilot_forecast"][0]
    j = EX.join_scan(rows, scan_id=d["scan_id"], realized_return=fc["location"] + 0.2 * fc["scale"], entry_iv=0.18, exit_iv=0.18)
    assert j["attribution"]["primary"] == "SPREAD_LATENCY_FEES" and j["attribution"]["evidence"]["gross_pnl"] == 1.0
    assert 0.5 < j["attribution"]["evidence"]["pit"] < 0.75 and j["immutable"] and h.ledger.read_text() == before
    # a tail realization with falling IV and costs: more than one class -> AMBIGUOUS, not forced
    j2 = EX.join_scan(rows, scan_id=d["scan_id"], realized_return=fc["location"] - 8 * fc["scale"], entry_iv=0.20, exit_iv=0.15)
    assert j2["attribution"]["primary"] == "AMBIGUOUS" and {"FORECAST_TAIL_ERROR", "IV_SCENARIO_ERROR", "SPREAD_LATENCY_FEES"} <= set(j2["attribution"]["all"])
    # a refused scan attributes to DATA availability; a proposal registers nothing
    h2 = SyntheticHarness(tmp_path / "q.jsonl")
    h2.quotes.fail_with = ConnectionError("provider down")
    src2 = h2.sources(); src2.pop("exit_quote_fn")
    d2 = S.scan(h2.bd, symbol="SPY", seq=1, **src2)
    j3 = EX.join_scan(L.read_all(h2.ledger), scan_id=d2["scan_id"])
    assert j3["attribution"]["primary"] == "SOFTWARE_FAILURE"
    prop = EX.propose_challenger(from_join=j, hypothesis="cost model underestimates exit spread", family="COST_MODEL", features=["spread_rel"])
    assert prop["status"] == "PROPOSED_NOT_REGISTERED" and prop["authority"].startswith("NONE") and len(prop["proposal_digest"]) == 16


# ================================================================== enrichment

def test_enrichment_records_are_source_linked_clocked_deduped_and_time_gated():
    kw = dict(kind="RELEASE", source_url="https://example.invalid/cpi", source_id="cpi-2026-09", event_time_utc="2026-09-10T12:30:00Z",
              publication_time_utc="2026-09-10T12:30:05Z", receipt_time_utc="2026-09-10T12:30:07Z", text_digest="abc",
              extraction={"uncertainty": 0.2, "fields": {"surprise_bps": 10}}, prompt_version="p1", model_version="m1")
    r = EN.event_record(**kw)
    assert r["dedup_key"] and r["authority"].startswith("NONE") and r["known_from_epoch"] == EN.parse_utc("2026-09-10T12:30:05Z", field="x")
    assert EN.usable_as_covariate(r, as_of_epoch=EN.parse_utc("2026-09-10T12:00:00Z", field="x"))["usable"] is False
    assert EN.usable_as_covariate(r, as_of_epoch=EN.parse_utc("2026-09-10T12:31:00Z", field="x"))["usable"] is True
    sched = EN.event_record(**{**kw, "kind": "SCHEDULED_EVENT", "source_id": "cal", "scheduled_time_utc": "2026-09-17T18:00:00Z",
                              "event_time_utc": "2026-09-01T00:00:00Z", "publication_time_utc": "2026-09-01T00:00:00Z", "receipt_time_utc": "2026-09-01T00:00:01Z"})
    assert EN.usable_as_covariate(sched, as_of_epoch=EN.parse_utc("2026-09-10T12:00:00Z", field="x"))["as"].startswith("known covariate")
    assert EN.dedupe([r, r, sched])["dropped_duplicates"] == 1
    for bad, why in (({**kw, "source_url": ""}, "SOURCE_LINK"), ({**kw, "publication_time_utc": "2026-09-10T12:29:00Z"}, "CLOCKS_OUT_OF_ORDER"),
                     ({**kw, "extraction": {}}, "EXTRACTION_UNCERTAINTY"), ({**kw, "event_time_utc": "2026-09-10 12:30"}, "naive|unparseable"),
                     ({**kw, "kind": "SCHEDULED_EVENT"}, "SCHEDULED_TIME_REQUIRED")):
        with pytest.raises(EN.EnrichmentRefused, match=why):
            EN.event_record(**bad)
    with pytest.raises(EN.EnrichmentRefused, match="NO_LLM_CLIENT"):
        EN.NoLLMClient().extract("text")
