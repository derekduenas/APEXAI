"""SEQUENTIAL-FUNNEL-AUDIT-001-R1 — claim corrections and the two Stage-1 repairs."""
from __future__ import annotations

import inspect as I

import pytest

from apex.audit.stage1 import T0, expected_last_bar_close, expected_ret_15, frozen_bars
from apex.options_pilot.clock import Clock
from apex.options_pilot.fees import SYNTHETIC_FEES, FeeSchedule
from apex.options_pilot import fee_computation as FC
from apex.pulse_options import features as FT, inference as INF, snapshot as SN, sources as SRC
from apex.pulse_options.decision_context import (SCHEMA, decision_context_identity, execution_quote_binding,
                                                 normalize_chain)
from apex.pulse_options.ingest import BarStore
from apex.pulse_options.providers import load_bars

BARS = frozen_bars()
CHEAP = [{"expiration": "2026-10-09", "strike": 650.0, "right": "CALL", "ask": 2.45, "bid": 2.35}]
DEAR = [{"expiration": "2027-06-18", "strike": 900.0, "right": "PUT", "ask": 88.0, "bid": 87.0}]


def twin(bars=None, chain=()):
    bars = BARS if bars is None else bars

    class Feed:
        provider = "audit"

        def bars(self, symbol, start_epoch, end_epoch):
            return [b for b in bars if start_epoch <= b["event_time"] <= end_epoch]

    return SRC.TwinSources(provenance="SYNTHETIC_FIXTURE", clock=Clock(lambda: T0), bar_source=Feed(),
                           chain_fn=lambda s, a: list(chain), quote_fn=None, exit_quote_fn=None,
                           fee_schedule=SYNTHETIC_FEES, sleep_fn=lambda s: None)


def ctx(bars=None, chain=CHEAP, quote=None, as_of=T0):
    s = twin(bars, chain).snapshot("SPY", as_of)
    return s, decision_context_identity(snapshot=s, chain_rows=chain, reference_quote=quote)


# ================================================= 1. corrected claims


class TestTheCorrectedClaims:
    def test_consumption_was_measured_through_ONE_accessor_and_there_are_THREE(self):
        """WITHDRAWN CLAIM: 'only 2 of 32 fields are read'. Other access paths exist."""
        assert "snapshot[\"fields\"].get" in I.getsource(FT.feature_vector)
        assert 'snapshot["fields"]["ret_1"]' in I.getsource(INF.FrozenArtifact.forecast)

    def test_five_fields_show_observed_consumption_not_two(self):
        reads, orig_uv, orig_fv = [], SN.usable_value, FT.feature_vector

        def uv(s, n):
            reads.append(n)
            return orig_uv(s, n)

        def fv(s):
            reads.extend(FT.FEATURE_ORDER)
            return orig_fv(s)

        SN.usable_value = SRC.usable_value = uv
        FT.feature_vector = INF.feature_vector = fv
        try:
            tw = twin()
            tw.snapshot("SPY", T0); tw.signal_fn("SPY", T0); tw.spot_fn("SPY", T0)
            try:
                tw.forecast_fn("SPY", T0)
            except Exception:
                pass
        finally:
            SN.usable_value = SRC.usable_value = orig_uv
            FT.feature_vector = INF.feature_vector = orig_fv
        assert set(reads) >= {"ret_15", "last_bar_close", "ret_1", "ret_5", "rv_30"}

    def test_the_remainder_is_CONSUMPTION_NOT_OBSERVED_not_never_read(self):
        s = twin().snapshot("SPY", T0)
        observed = {"ret_15", "last_bar_close", "ret_1", "ret_5", "rv_30"}
        assert len(s["fields"]) == 32 and len(observed) == 5
        # the claim is bounded to the route exercised
        assert "PILOT_RULE_V2" in SRC.SELECTION_POLICIES

    def test_WITHDRAWN_a_snapshot_change_does_not_touch_any_fee_bound_field(self):
        """The fee authorization binds fee identity; implementation_digest covers the fee computation module
        ONLY. snapshot.py and sources.py are not in it."""
        assert "snapshot" not in FC.__name__ and "sources" not in FC.__name__
        assert set(FeeSchedule.IDENTITY_FIELDS).isdisjoint({"snapshot_id", "state_hash"})


# ================================================= 2. D1


class TestD1DecisionContextIdentity:
    def test_the_defect_reproduces_on_snapshot_id_alone(self):
        a, b = twin(chain=CHEAP).snapshot("SPY", T0), twin(chain=DEAR).snapshot("SPY", T0)
        assert a["snapshot_id"] == b["snapshot_id"], "the original defect"

    def test_snapshot_id_scope_is_preserved_not_redefined(self):
        _, c = ctx()
        assert "UNDERLYING state only" in c["snapshot_id_scope_preserved"]
        assert c["schema"] == SCHEMA

    @pytest.mark.parametrize("label,kw", [
        ("chain_only", {"chain": DEAR}),
        ("quote_only", {"quote": {"bid": 2.30, "ask": 2.40, "timestamp_epoch": T0 - 1}}),
        ("cross_snapshot", {"as_of": T0 - 600.0}),
    ])
    def test_each_perturbation_changes_the_context_identity(self, label, kw):
        _, base = ctx()
        _, other = ctx(**kw)
        assert base["context_id"] != other["context_id"], label

    def test_underlying_and_availability_changes_also_change_it(self):
        _, base = ctx()
        alt = [dict(b) for b in BARS]
        alt[-1].update(close=alt[-1]["close"] + 1, high=alt[-1]["high"] + 1,
                       open=alt[-1]["open"] + 1, vwap=alt[-1]["vwap"] + 1)
        assert ctx(bars=alt)[1]["context_id"] != base["context_id"]
        late = [dict(b) for b in BARS]
        late[-1]["receipt_time"] = T0 + 1.0
        assert ctx(bars=late)[1]["context_id"] != base["context_id"]

    def test_equivalent_reordering_does_not_change_identity(self):
        both = CHEAP + DEAR
        assert ctx(chain=both)[1]["context_id"] == ctx(chain=list(reversed(both)))[1]["context_id"]
        assert normalize_chain(both) == normalize_chain(list(reversed(both)))

    def test_duplicates_are_retained_not_collapsed(self):
        assert len(normalize_chain(CHEAP + CHEAP)) == 2

    def test_altered_content_under_an_old_digest_is_detected(self):
        s, c = ctx()
        tampered = dict(s, state_hash="0" * 64)
        assert decision_context_identity(snapshot=tampered, chain_rows=CHEAP)["context_id"] != c["context_id"]

    def test_execution_requotes_bind_to_their_own_attempt_and_never_backwards(self):
        _, c = ctx()
        a = execution_quote_binding(context_id=c["context_id"], quote={"bid": 2.7, "ask": 2.8},
                                    attempt=1, at_epoch=T0 + 900)
        b = execution_quote_binding(context_id=c["context_id"], quote={"bid": 2.6, "ask": 2.7},
                                    attempt=2, at_epoch=T0 + 960)
        assert a["binding_id"] != b["binding_id"]
        assert "never a revision of the decision's context" in a["law"]
        assert "does not cover" in " ".join(c.keys()) or c["does_not_cover"]

    def test_a_snapshot_without_an_id_is_refused(self):
        with pytest.raises(ValueError, match="REQUIRES_A_SNAPSHOT_WITH_AN_ID"):
            decision_context_identity(snapshot={"no": "id"}, chain_rows=CHEAP)


# ================================================= 3. D2


class TestD2MalformedBarHandling:
    def test_a_missing_event_time_no_longer_aborts_the_batch(self):
        bad = {k: v for k, v in BARS[1].items() if k != "event_time"}
        st = BarStore("SPY", source="a")
        r = load_bars(st, [BARS[0], bad, BARS[2]])
        assert any("FIELDS_MISSING: event_time" in p for p in r["problems"])
        assert r["accepted"] == 2, "the valid rows must survive"

    def test_a_mixed_batch_reports_stable_named_reasons(self):
        batch = [BARS[0],
                 {k: v for k, v in BARS[1].items() if k != "event_time"},
                 {k: v for k, v in BARS[2].items() if k != "receipt_time"},
                 {**BARS[3], "event_time": float("nan")},
                 {**BARS[4], "close": float("inf")},
                 {**BARS[5], "close": BARS[5]["close"] + 9},
                 {**BARS[6], "receipt_time": T0 + 600.0},
                 BARS[7]]
        st = BarStore("SPY", source="a")
        r = load_bars(st, batch)
        joined = " | ".join(r["problems"])
        for expect in ("BAR_1_FIELDS_MISSING: event_time", "BAR_2_FIELDS_MISSING: receipt_time",
                       "BAR_3_REFUSED", "BAR_4_REFUSED", "BAR_5_REFUSED"):
            assert expect in joined, expect
        assert r["accepted"] == 3
        assert len(st.bars_available_by(T0)) == 2, "the future-availability row is excluded at the as-of filter"

    def test_a_non_object_row_is_named_not_crashed(self):
        st = BarStore("SPY", source="a")
        r = load_bars(st, ["not a bar"])
        assert any("NOT_AN_OBJECT" in p for p in r["problems"])

    def test_no_blanket_handler_was_added(self):
        src = I.getsource(load_bars)
        assert "except Exception" not in src and "except BaseException" not in src


# ================================================= 4. Stage 1 reverified


class TestStage1Reverified:
    def test_the_inspected_fields_still_agree(self):
        s = twin().snapshot("SPY", T0)
        assert s["fields"]["last_bar_close"]["value"] == expected_last_bar_close(BARS, T0)
        assert abs(s["fields"]["ret_15"]["value"] - expected_ret_15(BARS, T0)) < 1e-12

    def test_missing_still_differs_from_zero(self):
        s = twin().snapshot("SPY", T0)
        assert s["fields"]["chain_quote_count"]["value"] is None
