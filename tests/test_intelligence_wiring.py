"""Every intelligence layer is ASKED, and an absence is MEASURED rather than assumed.

THE DEFECT. `forward_pass.decision_pass` called `assemble_bundle(d, analog_result=analog, swarm=swarm)` --
no ml_prediction, no simulation. The bundle then recorded assemble_bundle's own defaults, and the resulting
record was indistinguishable from one where the model had been consulted and had nothing to say. Ten of ten
capital decisions ever written carry `forecast = NOT_YET_AVAILABLE`, and from the record alone nobody could tell
whether the forecast layer was starved, broken, or never called.

These tests hold the distinction: NOT_REQUESTED is not UNTRAINED, and a refusal must carry its number.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.hunter import intelligence_wiring as W
from apex.hunter.evidence import EvidenceClass
from apex.hunter.forecast import assemble_bundle

EC = EvidenceClass.EODHD_FORWARD_OBSERVATION


def synth_bars(n=400, s0=100.0, seed=0, end="2026-09-14 18:00"):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.0008, n)
    close = s0 * np.exp(np.cumsum(r))
    t = pd.date_range(end=pd.Timestamp(end, tz="UTC"), periods=n, freq="min")
    return pd.DataFrame({"provider_symbol": "SPY.US", "event_time_utc": t,
                         "open": close, "high": close, "low": close,
                         "close": close, "volume": 1000})


CUTOFF = pd.Timestamp("2026-09-14 18:01", tz="UTC").timestamp()


# ======================================================= the semantic change
class TestAnUnaskedQuestionIsNotAnAnswer:
    def test_the_bundle_default_is_NOT_REQUESTED_not_UNTRAINED(self):
        """UNTRAINED is a model LIFECYCLE state. Asserting it on behalf of a model nobody consulted is how an
        unwired layer came to look like a starved one for a month."""
        b = assemble_bundle({"decision_id": "x", "direction": "LONG"}).as_record()
        assert b["ml_view"]["status"] == "NOT_REQUESTED"
        assert "UNTRAINED" != b["ml_view"]["status"]

    def test_an_unsupplied_simulation_is_recorded_as_NOT_REQUESTED_not_None(self):
        b = assemble_bundle({"decision_id": "x", "direction": "LONG"}).as_record()
        assert b["simulation_view"] is not None
        assert b["simulation_view"]["status"] == "NOT_REQUESTED"

    def test_a_supplied_refusal_carries_its_reasons_into_the_bundle(self):
        sv = W.SimulationView("REFUSED", "NO_BARS", 0, {}, ("NO_BARS_FOR_SYMBOL",), {"wiring": W.SCHEMA})
        b = assemble_bundle({"decision_id": "x", "direction": "LONG"}, simulation=sv).as_record()
        assert b["simulation_view"]["status"] == "REFUSED"
        assert b["simulation_view"]["reasons"] == ["NO_BARS_FOR_SYMBOL"], \
            "a refusal without its reason reads exactly like a layer that was never wired"


# ======================================================= the ML layer
class TestTheMLLayerIsAsked:
    def test_it_is_always_marked_as_asked(self):
        assert W.ml_view({"decision_id": "x"}, [], evidence_class=EC)["asked"] is True

    def test_an_empty_ledger_produces_a_refusal_WITH_NUMBERS(self):
        v = W.ml_view({"decision_id": "x"}, [], evidence_class=EC)
        assert v["p_positive"] is None
        assert v.get("min_effective_to_train") == 40
        assert v.get("n_effective") == 0
        assert any("INSUFFICIENT_FORWARD_DATA" in r for r in v["reasons"])
        assert any("< 40" in r for r in v["reasons"]), \
            "a refusal that does not say how far short it fell is not actionable"

    def test_the_provenance_contract_is_mirrored_not_defaulted(self):
        """Omitting evidence_class must fail at the CALL SITE, not become a record that reads like a refusal."""
        with pytest.raises(TypeError):
            W.ml_view({"decision_id": "x"}, [])

    def test_a_layer_that_raises_is_distinguished_from_one_with_nothing_to_say(self):
        v = W.ml_view({"decision_id": "x"}, "not-a-list", evidence_class=EC)
        assert v["status"] == "REFUSED_ERROR" and v["asked"] is True


# ======================================================= the variance + multiverse layer
class TestTheSimulationLayerIsAsked:
    def test_it_never_returns_None(self):
        assert W.simulation_view({"symbol": "X"}, None, as_of_epoch=CUTOFF) is not None

    def test_no_bars_is_a_named_refusal(self):
        v = W.simulation_view({"symbol": "X"}, None, as_of_epoch=CUTOFF)
        assert v.calibration_status == "REFUSED" and "NO_BARS_FOR_SYMBOL" in v.reasons

    def test_real_bars_produce_a_real_simulation(self):
        v = W.simulation_view({"symbol": "SPY.US"}, synth_bars(), as_of_epoch=CUTOFF, n_paths=500)
        assert v.calibration_status == "SIMULATED_UNCALIBRATED", v.reasons
        assert v.n_paths == 500
        assert "MULTIVERSE_CONDITIONAL" in v.source
        freqs = {k: x for k, x in v.branch_scenario_frequencies.items() if k != "note"}
        assert abs(sum(freqs.values()) - 1.0) < 1e-9, freqs
        assert v.provenance["next_bar_variance"] > 0

    def test_the_variance_handoff_convention_is_asserted_not_assumed(self):
        """The simulator's first-bar variance must EQUAL the variance model's next-bar forecast. A silent
        mismatch would make every branch frequency a fiction, so a mismatch is a refusal."""
        v = W.simulation_view({"symbol": "SPY.US"}, synth_bars(), as_of_epoch=CUTOFF, n_paths=200)
        assert v.calibration_status == "SIMULATED_UNCALIBRATED"
        assert "VARIANCE_HANDOFF_MISMATCH" not in v.reasons

    def test_whether_GARCH_was_asked_is_always_on_the_record(self):
        v = W.simulation_view({"symbol": "SPY.US"}, synth_bars(), as_of_epoch=CUTOFF, n_paths=200)
        p = v.provenance
        assert ("garch_refused" in p or "garch_error" in p or "garch_not_attempted" in p
                or p.get("variance_model", "").startswith("GARCH")), \
            "the record must say whether GARCH ran, refused, or was never attempted: %s" % p

    def test_a_short_sample_records_that_GARCH_was_not_attempted(self):
        v = W.simulation_view({"symbol": "SPY.US"}, synth_bars(n=40), as_of_epoch=CUTOFF, n_paths=100)
        assert "garch_not_attempted" in v.provenance
        assert "have 39" in v.provenance["garch_not_attempted"]


# ======================================================= the point-in-time firewall
class TestNoLookahead:
    def test_every_return_row_carries_when_it_became_knowable(self):
        rows = W._return_rows(synth_bars(n=50), cutoff_epoch=CUTOFF)
        assert rows and all("event_time" in r and "available" in r for r in rows)

    def test_a_return_is_knowable_at_the_CLOSING_bar_not_the_opening_one(self):
        bars = synth_bars(n=3)
        rows = W._return_rows(bars, cutoff_epoch=CUTOFF)
        assert rows[0]["event_time"] == float(bars["event_time_utc"].iloc[1].timestamp()) + 60

    def test_rows_after_the_cutoff_are_excluded(self):
        bars = synth_bars(n=100)
        early = float(bars["event_time_utc"].iloc[50].timestamp())
        rows = W._return_rows(bars, cutoff_epoch=early)
        assert rows and max(r["event_time"] for r in rows) <= early

    def test_the_simulation_refuses_rather_than_peeking(self):
        """The variance model's own firewall rejects any row available after the cutoff. Asked with a cutoff
        before the bars exist, the layer must refuse -- not quietly use them."""
        bars = synth_bars(n=300)
        before = float(bars["event_time_utc"].iloc[0].timestamp()) - 3600
        v = W.simulation_view({"symbol": "SPY.US"}, bars, as_of_epoch=before, n_paths=100)
        assert v.calibration_status == "REFUSED", v
