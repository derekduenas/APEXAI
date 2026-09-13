"""SEQUENTIAL-FUNNEL-AUDIT-001 STAGE 1 — data intake -> PULSE -> Twin.

Every expectation here is computed independently of the system from a fixture frozen before execution. Two
production defects and two audit errors were found; all four are pinned."""
from __future__ import annotations

import math

import pytest

from apex.audit.stage1 import T0, adversarial, expected_last_bar_close, expected_ret_15, frozen_bars
from apex.audit.reader_probe import ReaderProbe
from apex.court import receipt as R
from apex.options_pilot.clock import Clock
from apex.options_pilot.fees import SYNTHETIC_FEES
from apex.options_pilot.records import canonical_hash
from apex.pulse_options.ingest import BarStore
from apex.pulse_options.providers import load_bars
from apex.pulse_options.sources import TwinSources

BARS = frozen_bars()


def twin(bars=None, chain=()):
    bars = BARS if bars is None else bars

    class Feed:
        provider = "audit"

        def bars(self, symbol, start_epoch, end_epoch):
            return [b for b in bars if start_epoch <= b["event_time"] <= end_epoch]

    return TwinSources(provenance="SYNTHETIC_FIXTURE", clock=Clock(lambda: T0), bar_source=Feed(),
                       chain_fn=lambda s, a: list(chain), quote_fn=None, exit_quote_fn=None,
                       fee_schedule=SYNTHETIC_FEES, sleep_fn=lambda s: None)


# ===================================================== 1. corrected evidence semantics


class TestEvidenceSemanticsAreThreeDifferentClaims:
    def test_finding_an_id_in_a_record_is_only_a_reference(self):
        log = R.ReceiptLog(run_id="t")
        log.emit(layer="X", operation="o", output={"a": 1}, output_id="o1")
        res = log.discover_consumption([{"kind": "downstream", "txn_id": "d", "ref": "o1"}])
        assert log.receipts[0]["consumption"]["state"] == R.REFERENCED_IN_RECORD
        assert "not that any calculation read it" in log.receipts[0]["consumption"]["note"]
        assert "REFERENCE ONLY" in res["claim"]

    def test_the_three_claims_are_distinct_names(self):
        assert len({R.REFERENCED_IN_RECORD, R.CONSUMED, R.BEHAVIORAL_EFFECT}) == 3


# ===================================================== 2-3. the real ingestion path


class TestRealIngestionGuards:
    def test_the_clean_frozen_fixture_is_accepted_whole(self):
        st = BarStore("SPY", source="audit")
        r = load_bars(st, BARS)
        assert r["problems"] == [] and len(st.bars_available_by(T0)) == len(BARS)

    @pytest.mark.parametrize("case,expect", [("MALFORMED_PRICE", "not a finite real"),
                                             ("NEGATIVE_PRICE", "BAR_INCONSISTENT"),
                                             ("DUPLICATE_CONFLICTING", "BAR_INCONSISTENT")])
    def test_a_bad_bar_is_named_not_dropped(self, case, expect):
        bad = next(b for n, b, _ in adversarial(BARS) if n == case)
        st = BarStore("SPY", source="audit")
        load_bars(st, BARS)
        r = load_bars(st, [bad])
        assert r["problems"] and expect in r["problems"][0]

    def test_D2_a_bar_missing_its_timestamp_is_NAMED_not_crashed(self):
        """SUPERSEDED BY R1, WHICH REPAIRED IT. The defect as found: providers.load_bars documented that
        malformed bars are 'counted and named, never dropped silently' and caught IngestRefused, but a missing
        key raised KeyError straight out of the loop, so ONE malformed bar aborted the whole batch and every
        valid row after it was lost. The repair checks required keys explicitly and reports through the same
        named mechanism -- no blanket handler. This test now asserts the repaired behaviour, and the defect it
        replaces is recorded above."""
        bad = next(b for n, b, _ in adversarial(BARS) if n == "MISSING_TIMESTAMP")
        st = BarStore("SPY", source="audit")
        r = load_bars(st, [BARS[0], bad, BARS[1]])
        assert any("FIELDS_MISSING: event_time" in p for p in r["problems"])
        assert r["accepted"] == 2, "valid rows either side of the malformed one must survive"

    def test_receipt_time_is_the_field_that_governs_availability(self):
        """AUDIT ERROR, recorded: the first late-input proof set `available` and saw no change, because
        load_bars keys availability off `receipt_time`."""
        late = [dict(b) for b in BARS]
        late[-1]["available"] = T0 + 1.0                      # NOT the governing field
        assert twin(late).snapshot("SPY", T0)["n_bars_available"] == len(BARS)
        late[-1]["receipt_time"] = T0 + 1.0                   # the governing field
        s = twin(late).snapshot("SPY", T0)
        assert s["n_bars_available"] == len(BARS) - 1
        assert abs(s["fields"]["last_bar_close"]["value"] - 603.80) < 1e-9


# ===================================================== 4. PULSE / Twin values


class TestTwinFieldsAgreeWithIndependentComputation:
    def test_last_bar_close(self):
        s = twin().snapshot("SPY", T0)
        assert s["fields"]["last_bar_close"]["value"] == expected_last_bar_close(BARS, T0) == 603.90

    def test_ret_15_is_a_LOG_return(self):
        """AUDIT ERROR, recorded: the first expectation used a SIMPLE return and disagreed at the 6th decimal.
        The Twin was right."""
        s = twin().snapshot("SPY", T0)
        assert abs(s["fields"]["ret_15"]["value"] - expected_ret_15(BARS, T0)) < 1e-12
        assert abs(s["fields"]["ret_15"]["value"] - math.log(603.90 / 602.40)) < 1e-12
        assert abs(s["fields"]["ret_15"]["value"] - (603.90 / 602.40 - 1.0)) > 1e-9, "it is NOT a simple return"

    def test_missing_stays_distinguishable_from_a_measured_zero(self):
        s = twin().snapshot("SPY", T0)
        for f in ("chain_quote_count", "chain_expirations", "next_scheduled_event_type"):
            assert s["fields"][f]["value"] is None and s["fields"][f]["quality"] == "NOT_AVAILABLE"


class TestConsumptionAtTheRealReader:
    def test_only_two_of_thirty_two_twin_fields_are_read_by_this_route(self):
        probe = ReaderProbe()
        with probe.instrument():
            tw = twin(); snap = tw.snapshot("SPY", T0); tw.signal_fn("SPY", T0); tw.spot_fn("SPY", T0)
        consumed = probe.consumed_fields(snap["snapshot_id"])
        assert set(consumed) == {"last_bar_close", "ret_15"}
        assert len(snap["fields"]) == 32
        assert consumed["ret_15"] == ["apex.pulse_options.sources.signal_fn"]
        assert consumed["last_bar_close"] == ["apex.pulse_options.sources.spot_fn"]

    def test_a_perturbation_produces_the_independently_expected_value(self):
        alt = [dict(b) for b in BARS]
        alt[-1].update(close=alt[-1]["close"] + 1.0, high=alt[-1]["high"] + 1.0,
                       open=alt[-1]["open"] + 1.0, vwap=alt[-1]["vwap"] + 1.0)
        s = twin(alt).snapshot("SPY", T0)
        assert abs(s["fields"]["ret_15"]["value"] - expected_ret_15(alt, T0)) < 1e-12
        assert s["snapshot_id"] != twin().snapshot("SPY", T0)["snapshot_id"]


# ===================================================== 5. snapshot identity


class TestSnapshotIdentityCoverage:
    def test_DEFECT_snapshot_id_does_not_cover_the_option_chain(self):
        """PRODUCTION DEFECT. TwinSources.snapshot() never passes chain_meta to compose(), although compose()
        accepts it. Two scans on completely different chains are indistinguishable by the identifier the decision
        record uses to name 'the market state this decision was made on'."""
        cheap = [{"expiration": "2026-10-09", "strike": 650.0, "right": "CALL", "ask": 2.45, "bid": 2.35}]
        dear = [{"expiration": "2027-06-18", "strike": 900.0, "right": "PUT", "ask": 88.0, "bid": 87.0}]
        a, b = twin(chain=cheap).snapshot("SPY", T0), twin(chain=dear).snapshot("SPY", T0)
        assert a["snapshot_id"] == b["snapshot_id"], "the defect: identical id, different chain"
        assert a["fields"]["chain_quote_count"]["quality"] == "NOT_AVAILABLE"

    def test_the_ids_own_stated_basis_is_accurate_about_what_it_hashes(self):
        """The basis string is not the defect. The gap between it and the id's downstream ROLE is."""
        s = twin().snapshot("SPY", T0)
        assert "the field values and the bar count" in s["snapshot_id_basis"]
        assert "chain" not in s["snapshot_id_basis"]

    def test_the_underlying_state_IS_covered(self):
        a = twin().snapshot("SPY", T0)
        alt = [dict(x) for x in BARS]
        alt[-1].update(close=alt[-1]["close"] + 1.0, high=alt[-1]["high"] + 1.0,
                       open=alt[-1]["open"] + 1.0, vwap=alt[-1]["vwap"] + 1.0)
        assert twin(alt).snapshot("SPY", T0)["snapshot_id"] != a["snapshot_id"]


class TestConnectionProofs:
    def test_another_scans_snapshot_has_a_different_identity(self):
        assert twin().snapshot("SPY", T0 - 600.0)["snapshot_id"] != twin().snapshot("SPY", T0)["snapshot_id"]

    def test_altered_content_under_a_retained_digest_is_detected_by_recomputation(self):
        s = twin().snapshot("SPY", T0)
        t = dict(s, fields=dict(s["fields"]))
        t["fields"]["last_bar_close"] = dict(s["fields"]["last_bar_close"], value=999.0)
        recomputed = canonical_hash({k: t[k] for k in ("schema_version", "symbol", "as_of_epoch",
                                                       "fields", "n_bars_available")})
        assert recomputed != s["state_hash"]
