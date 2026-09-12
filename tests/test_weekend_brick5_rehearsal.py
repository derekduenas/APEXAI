"""Weekend commissioning, Brick 5: operational rehearsal through the actual entry point (run_pilot) and harness engine.
Restart with an open position, a stale event feed, a quote timeout, duplicate delivery, a changed release, a clock
jump, and an unavailable exit. Refusing new entries never strands an existing position."""
from __future__ import annotations

import json

import pytest

from apex.catalyst import twin_snapshot as TS
from apex.options_pilot import entrypoint as PEP, ledger as L, session as S
from apex.options_pilot.synthetic_harness import SyntheticHarness, T0
from apex.pulse_options.providers import ProviderUnavailable

T = 1_789_000_020.0


def _prov(h, policy="PILOT_RULE_V2"):
    return PEP._HarnessProvider(h, selection_policy=policy)


def _run(led, tmp_path, h, sid, release="rel-A", cycles=1):
    return PEP.run_pilot(ledger=led, out=tmp_path / ("%s.json" % sid), symbols=["SPY"], provider=_prov(h), session_id=sid, release=release, cycles=cycles)


class TestRehearsal:
    def test_restart_with_an_open_position_resumes_and_discharges_it(self, tmp_path):
        led = tmp_path / "led.jsonl"
        h = SyntheticHarness(led, session_id="RS", t0=T)
        S.open_session(h.bd, symbols=["SPY"])
        src = h.sources(); src.pop("exit_quote_fn")
        d = S.scan(h.bd, symbol="SPY", seq=1, **src)                          # the process dies here: filled, no exit attempted
        assert d["decision"] == "TRADE" and h.bd.book().positions
        h2 = SyntheticHarness(led, session_id="RS", t0=h.now() + 1000.0)     # a NEW process, same ledger, same release
        rep2 = _run(led, tmp_path, h2, "RS", release=h.release)              # a DIFFERENT release would be refused: INTENT_FROM_OTHER_RELEASE
        assert rep2["recovered_positions"] and rep2["recovered_positions"][0]["intent_id"] == d["intent_id"]
        assert rep2["outcomes"], "the recovered position must be discharged through its exit obligation"
        book = h2.bd.book()
        assert not book.positions and book.closed and book.summary()["integrity_problems"] == []
        L.verify_chain(led)

    def test_stale_event_feed_is_recorded_and_under_shadow_does_not_block_and_under_active_blocks_only_entries(self, tmp_path):
        led = tmp_path / "led.jsonl"
        h = SyntheticHarness(led, session_id="EV", t0=T)
        cal = tmp_path / "cal"; cal.mkdir()
        ev = tmp_path / "events.jsonl"; ev.write_text(""); cy = tmp_path / "cycles.jsonl"; cy.write_text("")   # a ledger with no successful cycle

        def snap(symbol, as_of):
            return TS.event_snapshot(symbol=symbol, as_of=as_of, calendar_dir=cal, event_ledger=ev, cycle_ledger=cy)
        shadow = lambda s, t: {**snap(s, t), "gate": TS.evaluate_gate(snap(s, t), authority="SHADOW")}
        src = h.sources(); src["event_context_fn"] = shadow

        class P(PEP._HarnessProvider):
            def sources(self):
                return src
        rep = PEP.run_pilot(ledger=led, out=tmp_path / "o.json", symbols=["SPY"], provider=P(h), session_id="EV", release="rel-A")
        dec = next(r for r in L.read_all(led) if r["kind"] == "pilot_decision")
        ec = dec["funnel_trace"]["situation_regime"]["event_context"]
        assert ec["unscheduled_status"] == "STALE" and ec["gate"]["would_veto_new_entry"] and rep["decisions"][0]["decision"] == "TRADE"

    def test_quote_timeout_is_a_named_refusal_and_the_intent_expires_cleanly(self, tmp_path):
        led = tmp_path / "led.jsonl"
        h = SyntheticHarness(led, session_id="QT", t0=T)
        h.quotes.fail_with = ProviderUnavailable("HTTP_POLICY_V1: x/quote after 3 attempt(s): TIMEOUT")
        rep = _run(led, tmp_path, h, "QT")
        d = rep["decisions"][0]
        assert d["decision"] == "REFUSE" and "QUOTE_PROVIDER_FAILED" in d["why"] and "TIMEOUT" in d["why"]
        kinds = [r["kind"] for r in L.read_all(led)]
        assert "pilot_fill" in kinds and "pilot_outcome" not in kinds and not h.bd.book().positions

    def test_duplicate_delivery_of_a_scan_is_reconciled_not_re_executed(self, tmp_path):
        led = tmp_path / "led.jsonl"
        h = SyntheticHarness(led, session_id="DD", t0=T)
        src = h.sources(); src.pop("exit_quote_fn")
        d1 = S.scan(h.bd, symbol="SPY", seq=1, **src)
        d2 = S.scan(h.bd, symbol="SPY", seq=1, **src)                       # same scan id delivered twice
        assert d1["decision"] == "TRADE" and d2["decision"] == "TRADE" and d2.get("reconciled") is True
        assert [r["kind"] for r in L.read_all(led)].count("pilot_fill") == 1

    def test_changed_release_strands_the_previous_release_s_open_position_FINDING(self, tmp_path):
        """FINDING (weekend rehearsal, 2026-09-12), recorded as observed and carried as a blocker: a process started under
        rel-B refuses to recover the FILLED position opened under rel-A (INTENT_FROM_OTHER_RELEASE), opens its OWN
        position, discharges only its own, and closes the session with the rel-A position still open. The obligation is
        STRANDED. This test pins the observed behaviour so the finding cannot drift; the repair (exits of FILLED positions
        must be honoured across releases while intent recovery for FILL stays refused) is a separate reviewed change."""
        led = tmp_path / "led.jsonl"
        h = SyntheticHarness(led, session_id="REL", t0=T, release="rel-A")
        S.open_session(h.bd, symbols=["SPY"])
        src = h.sources(); src.pop("exit_quote_fn")
        d = S.scan(h.bd, symbol="SPY", seq=1, **src)
        assert d["decision"] == "TRADE" and len(h.bd.book().positions) == 1
        h2 = SyntheticHarness(led, session_id="REL", t0=h.now() + 1000.0, release="rel-B")
        rep2 = _run(led, tmp_path, h2, "REL", release="rel-B")
        rows = L.read_all(led)
        assert rep2["recovered_positions"] == []                                   # rel-A's position was NOT recovered
        assert rep2["outcomes"] and rep2["outcomes"][0]["fill_seq"] != d["receipts"]["fill"]["seq"]   # only rel-B's own fill exited
        book = h2.bd.book()
        assert len(book.positions) == 1 and book.positions[0]["intent_id"] == d["intent_id"], "the rel-A position is stranded"
        assert any(r["kind"] == "pilot_session_close" for r in rows), "and the session closed with it open"
        assert book.summary()["integrity_problems"] == []                          # the Book itself is consistent; the policy is the defect

    def test_clock_jump_backwards_makes_quotes_from_the_future_a_refusal(self, tmp_path):
        led = tmp_path / "led.jsonl"
        h = SyntheticHarness(led, session_id="CJ", t0=T)
        h.quotes.age = -30.0                                                   # provider clock ahead of ours by 30 s
        rep = _run(led, tmp_path, h, "CJ")
        d = rep["decisions"][0]
        assert d["decision"] == "REFUSE" and "QUOTE_FROM_THE_FUTURE" in d["why"]

    def test_unavailable_exit_keeps_the_obligation_open_and_visible(self, tmp_path):
        led = tmp_path / "led.jsonl"
        h = SyntheticHarness(led, session_id="UX", t0=T)
        S.open_session(h.bd, symbols=["SPY"])
        src = h.sources(); src.pop("exit_quote_fn")
        d = S.scan(h.bd, symbol="SPY", seq=1, **src)
        assert d["decision"] == "TRADE"
        h.exit_quotes.fail_with = ProviderUnavailable("exit venue down")
        h.advance(1000.0)
        res = S.attempt_exits(h.bd, exit_quote_fn=h.exit_quotes, sleep_fn=h.advance, wait_for_due=False)
        assert res and all(r.get("final") != "DISCHARGED" for r in res), res
        rows = L.read_all(led)
        assert any(r["kind"] in ("pilot_outcome", "pilot_exit_exhausted", "pilot_refusal") and "exit venue down" in json.dumps(r) for r in rows)
        book = h.bd.book()
        assert book.positions, "the position must remain an open obligation, never silently closed"
        assert book.summary()["integrity_problems"] == []
