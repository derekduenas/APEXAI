"""Findings from closing the 12-scan demonstration: (A) the housekeeping omission that blocked eleven scans,
reproduced synthetically; (B) timestamp comparison at the declared precision, including genuinely future instants."""
from __future__ import annotations

import json

import pytest

from apex.options_pilot import ledger as L, records as R, session as S
from apex.options_pilot.clock import to_utc_string
from apex.options_pilot.synthetic_harness import SyntheticHarness

T = 1_789_000_020.0
HOLD = 900.0


# ================================================================ A. HOUSEKEEPING LIFECYCLE
class TestHousekeepingReleasesTheBlock:
    """The demonstration's eleven consecutive KERNEL_REFUSED were a DRIVER artifact: the driver ran every scan and
    only then attempted exits, so a position whose exit was already due was never valued and kept blocking. The real
    entry point runs S.resume + S.attempt_exits at the start of each cycle. These tests pin both behaviours."""

    @staticmethod
    def _harness(tmp_path, sid):
        """The demonstration's condition: a contract whose debit is large enough that TWO of them exceed the
        $600 same-underlying cap (495 + 500 = 995). The harness default (2.45 -> $245) does not reach it."""
        h = SyntheticHarness(tmp_path / "led.jsonl", session_id=sid, t0=T, risk="certified")
        h.chain = [{**c, "ask": 4.95} for c in h.chain]
        h.quotes.ask, h.quotes.bid = 4.95, 4.90
        h.exit_quotes.ask, h.exit_quotes.bid = 4.78, 4.73
        return h

    def _scan(self, h, seq):
        src = h.sources(); src.pop("exit_quote_fn")
        return S.scan(h.bd, symbol="SPY", seq=seq, **src)

    def test_without_housekeeping_a_due_position_blocks_the_next_scan(self, tmp_path):
        h = self._harness(tmp_path, "NOHK")
        S.open_session(h.bd, symbols=["SPY"])
        d1 = self._scan(h, 1)
        assert d1["decision"] == "TRADE"
        h.advance(HOLD + 60.0)                       # the exit is now DUE and its window has closed
        d2 = self._scan(h, 2)                        # no housekeeping in between: the position is still open
        assert d2["decision"] == "REFUSE" and "KERNEL_REFUSED" in d2["why"]
        assert len(h.bd.book().positions) == 1

    def test_with_housekeeping_the_exit_discharges_and_the_next_scan_is_admitted(self, tmp_path):
        h = self._harness(tmp_path, "HK")
        S.open_session(h.bd, symbols=["SPY"])
        d1 = self._scan(h, 1)
        assert d1["decision"] == "TRADE"
        h.advance(HOLD + 1.0)                        # exit due, inside the 120 s window
        S.resume(h.bd, quote_fn=h.quotes)            # exactly what run_pilot does at the start of a cycle
        ex = S.attempt_exits(h.bd, exit_quote_fn=h.exit_quotes, sleep_fn=h.advance, wait_for_due=False)
        assert ex and any(x.get("final") == "RESOLVED" for x in ex)
        book = h.bd.book()
        assert not book.positions and len(book.closed) == 1, "the position must be discharged before the next scan"
        d2 = self._scan(h, 2)
        assert d2["decision"] == "TRADE", d2.get("why")     # capacity released; the next opportunity is admitted

    def test_the_real_entry_point_runs_housekeeping_between_cycles(self):
        import inspect
        from apex.options_pilot import entrypoint as PEP
        src = inspect.getsource(PEP.run_pilot)
        assert "S.resume(" in src and "S.attempt_exits(" in src and "housekeeping" in src
        i_hk, i_scan = src.index("housekeeping"), src.index("S.scan(")
        assert i_hk < i_scan, "housekeeping must precede the cycle's scans"

    def test_a_scan_before_the_exit_is_due_is_correctly_refused(self, tmp_path):
        """Scan 2 of the demonstration fired 0.7 s BEFORE the exit was due. That refusal was correct and stands."""
        h = self._harness(tmp_path, "EARLY")
        S.open_session(h.bd, symbols=["SPY"])
        assert self._scan(h, 1)["decision"] == "TRADE"
        h.advance(HOLD - 1.0)                        # one second BEFORE due
        S.resume(h.bd, quote_fn=h.quotes)
        ex = S.attempt_exits(h.bd, exit_quote_fn=h.exit_quotes, sleep_fn=h.advance, wait_for_due=False)
        assert not any(x.get("final") == "RESOLVED" for x in ex), "an exit before its due time must not resolve"
        assert self._scan(h, 2)["decision"] == "REFUSE"


# ================================================================ B. TIMESTAMP PRECISION
class TestTimestampPrecisionAtTheDeclaredGranularity:
    """Records serialize epochs as MICROSECOND strings. Comparisons are made at that granularity
    (records.TIMESTAMP_GRANULARITY_S = 1e-6). A genuinely future forecast must still be refused."""

    def _fc(self, h, created_epoch):
        f = h.base_forecast("SPY", h.now())
        return {**f, "created_utc": to_utc_string(created_epoch)}

    def test_the_declared_precision_is_one_microsecond(self):
        assert R.TIMESTAMP_GRANULARITY_S == 1e-6

    def test_equal_instants_are_accepted(self, tmp_path):
        h = SyntheticHarness(tmp_path / "l.jsonl", t0=T)
        R.validate_forecast(self._fc(h, h.now()), now_epoch=h.now(), provenance="SYNTHETIC_FIXTURE", session_id="S", scan_id="X")

    def test_a_serialization_round_trip_that_rounds_upward_is_accepted(self, tmp_path):
        """The demonstration's failure mode: an epoch whose microsecond string parses back LARGER than itself."""
        from apex.options_pilot.clock import parse_utc
        t = 1_789_134_322.3894567
        assert parse_utc(to_utc_string(t), field="x") > t, "fixture must exhibit the upward round trip"
        h = SyntheticHarness(tmp_path / "l.jsonl", t0=t)
        R.validate_forecast(self._fc(h, t), now_epoch=t, provenance="SYNTHETIC_FIXTURE", session_id="S", scan_id="X")

    def test_the_immediately_preceding_representable_instant_is_accepted(self, tmp_path):
        """created one microsecond BEFORE the clock: unambiguously in the past, accepted. (created must still be at
        or after its own input cutoff, so the clock is advanced rather than the creation time moved back.)"""
        h = SyntheticHarness(tmp_path / "l.jsonl", t0=T)
        R.validate_forecast(self._fc(h, h.now()), now_epoch=h.now() + 1e-6, provenance="SYNTHETIC_FIXTURE", session_id="S", scan_id="X")

    @pytest.mark.parametrize("ahead", [1e-5, 1e-4, 0.001, 1.0, 60.0])
    def test_a_genuinely_future_forecast_is_still_refused(self, tmp_path, ahead):
        """The tolerance must not hide a real future timestamp. One microsecond is the granularity; ten is a future."""
        h = SyntheticHarness(tmp_path / "l.jsonl", t0=T)
        with pytest.raises(R.RecordRefused, match="FORECAST_FROM_THE_FUTURE"):
            R.validate_forecast(self._fc(h, h.now() + ahead), now_epoch=h.now(), provenance="SYNTHETIC_FIXTURE", session_id="S", scan_id="X")

    def test_the_tolerance_is_exactly_one_granularity_and_no_more(self, tmp_path):
        h = SyntheticHarness(tmp_path / "l.jsonl", t0=T)
        R.validate_forecast(self._fc(h, h.now() + 1e-6), now_epoch=h.now(), provenance="SYNTHETIC_FIXTURE", session_id="S", scan_id="X")
        with pytest.raises(R.RecordRefused, match="FORECAST_FROM_THE_FUTURE"):
            R.validate_forecast(self._fc(h, h.now() + 1e-5), now_epoch=h.now(), provenance="SYNTHETIC_FIXTURE", session_id="S", scan_id="X")

    def test_timezone_equivalent_instants_compare_equal(self, tmp_path):
        from apex.options_pilot.clock import parse_utc
        assert parse_utc("2026-09-11T13:30:23.096973Z", field="x") == parse_utc("2026-09-11T13:30:23.096973+00:00", field="x")

    def test_invalid_timestamps_are_refused_not_tolerated(self, tmp_path):
        h = SyntheticHarness(tmp_path / "l.jsonl", t0=T)
        for bad in ("", "not-a-time", None, "2026-13-45T99:99:99Z"):
            with pytest.raises(R.RecordRefused):
                R.validate_forecast(self._fc(h, h.now()) | {"created_utc": bad}, now_epoch=h.now(),
                                    provenance="SYNTHETIC_FIXTURE", session_id="S", scan_id="X")
