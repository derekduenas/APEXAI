"""M1 — execution accounting and the operational paper loop, on the synthetic harness
with the CERTIFIED risk authority (the real risk_certificate + risk_kernel).

Establishes: certificate arithmetic is recomputed and bound to the intent + envelope;
atomic reservations (concurrent intents cannot jointly exceed the kernel limits);
fees charged exactly once and independently recomputed by the Book; restart before /
after durable entry and exit; the executable quote is rechecked against the reserved
envelope; re-quote and size rules; the frozen exit policy (not-due refusal, window,
retries, exhaustion); Book reconstruction with cash identities; and the real script seam.
It does not establish edge, live feed behaviour or operational authority."""
import json
import threading

import pytest

from apex.options_pilot import boundary as B, book as BK, ledger as L, risk_authority as RA, risk_gate as RG, session as S
from apex.options_pilot import entrypoint as E
from apex.options_pilot.exit_policy import EXIT_POLICY_V1
from apex.options_pilot.fees import EXECUTION_POLICY_V1, SYNTHETIC_FEES, UNVERIFIED_FEES, FeePolicyRefused, FeeSchedule
from apex.options_pilot.synthetic_harness import SyntheticHarness, T0
from apex.organism import risk_kernel as RK
from scripts import options_paper_session as sess

SYM = "SPY"
SID = "SYN-SESSION-1:0001:SPY"


def _h(tmp_path, **kw):
    kw.setdefault("risk", "certified")
    return SyntheticHarness(tmp_path / "pilot.jsonl", **kw)


def _scan(h, symbol=SYM, seq=None, **over):
    src = h.sources(); src.pop("exit_quote_fn"); src.update(over)
    seq = S.next_seq(h.ledger, session_id=h.session_id) if seq is None else seq
    return S.scan(h.bd, symbol=symbol, seq=seq, **src)


def _rows(h):
    return L.read_all(h.ledger)


def _rec(h, receipt):
    return _rows(h)[receipt["seq"] - 1]


def _proposal(**over):
    p = {"expression": "LONG_CALL", "action": "BUY", "quantity": 1, "reference_ask": 2.45,
         "contract": {"symbol": SYM, "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"}}
    p.update(over)
    return p


def _pending(h, scan_id=SID, **over):
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=scan_id)
    ir = h.bd.record_intent(forecast_receipt=fr, intent=_proposal(**over), signal_used="LONG", scan_id=scan_id)
    return fr, ir


def _exit(h, fill, fn=None, **kw):
    rec = _rec(h, fill)
    if rec.get("status") == "FILLED":
        h.t = max(h.t, rec["exit_schedule"]["exit_due_epoch"])
    return S.resolve(h.bd, fill_receipt=fill, exit_quote_fn=fn or h.exit_quotes, **kw)


# ================================================================== certificate + kernel wiring

def test_certified_approval_recomputes_the_certificate_and_binds_to_intent_and_envelope(tmp_path):
    h = _h(tmp_path)
    _fr, ir = _pending(h)
    it = _rec(h, ir)
    risk, env = it["risk"], it["risk_envelope"]
    assert env == {**env, "max_entry_price": 2.7, "envelope_debit": 270.0, "basis": "REFERENCE_ASK_PLUS_BUFFER", "reference_ask": 2.45}
    assert risk["risk_provenance"] == "CERTIFIED_KERNEL" and risk["authority_id"] == RA.AUTHORITY_ID
    cert = risk["certificate"]
    assert cert["certificate_version"] == "RISK_CERTIFICATE_V0" and cert["risk_class"] == "DEFINED_MAX_LOSS"
    assert cert["certified_max_loss"] == 270.0 == risk["certified_max_loss"]
    assert cert["inputs"]["legs"] == [["BUY", "CALL", 645.0, 2.7]] and cert["derivation"]["derived_net_debit"] == 270.0
    assert risk["kernel_check"]["approved"] is True and risk["kernel_check_at_commit"]["approved"] is True
    assert risk["kernel_check"]["threshold_set"] == "ORGANISM_PAPER_V1" and risk["limits"] == RK.LIMITS
    assert risk["book_state_hash_at_commit"] and risk["fee_schedule_id"] == "SYNTHETIC_FEES_V1"
    # the approval is bound to the envelope: a different envelope on the same intent does not verify
    with pytest.raises(RG.RiskRefused, match="NOT_BOUND_TO_THIS_ENVELOPE"):
        RG.verify_approval({**it, "risk_envelope": {**env, "max_entry_price": 5.0}}, risk)
    # a synthetic approval is not honoured by the certified authority, and vice versa
    assert "honours only CERTIFIED_KERNEL" in h.risk.accepts({"risk_provenance": "SYNTHETIC_FIXTURE", "authority_id": "SYNTHETIC_FIXTURE_AUTHORITY"})
    syn = RG.SyntheticRiskAuthority(harness_token="I_AM_A_SYNTHETIC_HARNESS")
    assert "honours only its own" in syn.accepts(risk)


def test_envelope_above_kernel_cap_is_refused_before_any_quote(tmp_path):
    """SPY ATM 21-DTE asks around $7-8 exceed the kernel's $500/trade cap: the pilot rule refuses at intent time."""
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    with pytest.raises(B.BoundaryRefused, match="RISK_ENVELOPE_INFEASIBLE: indicative ask 7.80 > kernel cap 5.00"):
        h.bd.record_intent(forecast_receipt=fr, intent=_proposal(reference_ask=7.80), signal_used="LONG", scan_id=SID)
    assert h.quotes.calls == [] and _rows(h)[-1]["kind"] == "pilot_refusal"
    env = RA.envelope_for(reference_ask=7.80)
    assert env["feasible"] is False and env["basis"] == "REFERENCE_ABOVE_CAP"
    # without a reference the envelope is the kernel cap itself ($500): allowed, and the executable ask is bounded by it
    h2 = _h(tmp_path / "b")
    fr2 = h2.bd.record_forecast(h2.forecast_fn(SYM, h2.now()), scan_id=SID)
    ir2 = h2.bd.record_intent(forecast_receipt=fr2, intent=_proposal(reference_ask=None), signal_used="LONG", scan_id=SID)
    env2 = _rec(h2, ir2)["risk_envelope"]
    assert env2["max_entry_price"] == 5.0 and env2["basis"] == "KERNEL_CAP_NO_REFERENCE" and h2.bd.book().reserved == 500.0
    h2.quotes.ask = 5.01
    assert h2.bd.execute_intent(intent_receipt=ir2, quote_fn=h2.quotes)["why"].startswith("ASK_ABOVE_ENVELOPE")


def test_unverified_fee_schedule_refuses_live_feed_intents(tmp_path):
    h = SyntheticHarness(tmp_path / "p.jsonl", risk="certified", fee_schedule=UNVERIFIED_FEES)
    live = B.Boundary(h.ledger, clock=h.clock, provenance="LIVE_FEED", session_id="L", release="r",
                      risk_authority=RA.CertifiedRiskAuthority(fee_schedule=UNVERIFIED_FEES, provenance="LIVE_FEED"),
                      fee_schedule=UNVERIFIED_FEES)
    f = h.forecast_fn(SYM, h.now())
    fr = live.record_forecast(f, scan_id="L:0001:SPY")
    with pytest.raises(B.BoundaryRefused, match="FEE_SCHEDULE_UNVERIFIED"):
        live.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id="L:0001:SPY")
    with pytest.raises(FeePolicyRefused, match="VERIFICATION_RECORD_MISSING"):
        FeeSchedule(schedule_id="X", version="1", provenance="PROVIDER_VERIFIED", commission_per_contract=0.65,
                    exchange_fee_per_contract=0.3, regulatory_fee_per_contract_buy=0.02, regulatory_fee_per_contract_sell=0.05)
    assert UNVERIFIED_FEES.entry(1)["status"] == "UNKNOWN" and UNVERIFIED_FEES.entry(1)["total"] is None


# ================================================================== atomic reservations

def test_concurrent_intents_cannot_jointly_exceed_the_same_underlying_limit(tmp_path):
    """Six SPY intents (envelope $270 each) released together; the kernel's same-underlying cap is $600, so exactly
    two may reserve. The re-check inside the intent commit transaction decides, not the pre-lock approval."""
    h = _h(tmp_path)
    n = 6
    forecasts = [h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id="SYN-SESSION-1:%04d:SPY" % (i + 1)) for i in range(n)]
    barrier = threading.Barrier(n)
    real_approve = h.risk.approve
    def gated(intent, *, book=None):
        out = real_approve(intent, book=book)
        barrier.wait(timeout=10)                       # everyone approved against the SAME empty book...
        return out
    h.risk.approve = gated
    ok, bad = [], []
    def worker(i):
        try:
            ok.append(h.bd.record_intent(forecast_receipt=forecasts[i], intent=_proposal(), signal_used="LONG",
                                         scan_id="SYN-SESSION-1:%04d:SPY" % (i + 1)))
        except B.BoundaryRefused as e:
            bad.append(str(e))
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in ts]; [t.join(timeout=30) for t in ts]
    assert len(ok) == 2 and len(bad) == 4, (len(ok), bad)          # ...but only two fit under the lock
    assert all("RISK_LIMIT_AT_COMMIT" in b and "SPY risk would reach" in b for b in bad)
    book = h.bd.book()
    assert book.reserved == 540.0 and len(book.reservations) == 2 and book.risk_inputs(symbol=SYM)["same_underlying_risk"] == 540.0
    L.verify_chain(h.ledger)


def test_reservation_is_consumed_or_released_exactly_once(tmp_path):
    h = _h(tmp_path)
    _fr, ir = _pending(h)
    assert h.bd.book().reserved == 270.0
    r = h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    assert r["status"] == "FILLED"
    b = h.bd.book()
    assert b.reserved == 0.0 and b.open_cost == 250.0 and len(b.positions) == 1        # reservation -> position at ACTUAL debit
    assert b.risk_inputs(symbol=SYM)["open_risk"] == 250.0
    # an unfilled (WAIT) attempt keeps the reservation; a terminal REFUSE or cancellation releases it
    h2 = _h(tmp_path / "b")
    _fr2, ir2 = _pending(h2)
    h2.quotes.ask_size = 0
    w = h2.bd.execute_intent(intent_receipt=ir2, quote_fn=h2.quotes)
    assert w["decision"] == "WAIT" and h2.bd.book().reserved == 270.0
    h2.bd.expire_intent(ir2, _rec(h2, ir2), why="operator cancel", kind="pilot_intent_cancelled")
    assert h2.bd.book().reserved == 0.0 and h2.bd.book().outstanding["unfinished_intents"] == []


# ================================================================== envelope, re-quote and size rules

def test_executable_ask_is_rechecked_against_the_envelope(tmp_path):
    h = _h(tmp_path)
    _fr, ir = _pending(h)                       # envelope max_entry_price 2.70
    h.quotes.ask = 2.75
    w = h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    assert w["decision"] == "WAIT" and w["why"].startswith("ASK_ABOVE_ENVELOPE: executable ask 2.75 > reserved max_entry_price 2.70")
    h.quotes.ask = 2.70
    f = h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    assert f["status"] == "FILLED" and f["attempt"] == 2 and _rec(h, f)["net_debit"] == 270.0


def test_requotes_are_bounded_and_exhaustion_cancels_the_intent(tmp_path):
    h = _h(tmp_path)
    _fr, ir = _pending(h)
    h.quotes.ask_size = 0
    for k in range(EXECUTION_POLICY_V1.max_fill_attempts):
        w = h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
        assert w["decision"] == "WAIT" and w["attempt"] == k + 1
    with pytest.raises(B.BoundaryRefused, match="REQUOTES_EXHAUSTED: 3 attempts"):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    rows = _rows(h)
    assert [r["kind"] for r in rows][-2:] == ["pilot_intent_cancelled", "pilot_refusal"]
    assert len(h.quotes.calls) == 3 and S.unfilled_intents(h.ledger) == []
    # a redelivery after exhaustion is terminal, never a fourth quote
    with pytest.raises(B.BoundaryRefused, match="INTENT_TERMINAL"):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    assert len(h.quotes.calls) == 3


def test_fill_quantity_is_zero_or_one_and_labelled_simulated(tmp_path):
    h = _h(tmp_path)
    d = _scan(h)
    f = _rec(h, d["receipts"]["fill"])
    assert f["quantity_filled"] == 1 and f["quantity_intended"] == 1 and f["simulated"] is True
    assert f["fill_label"].startswith("SIMULATED") and f["execution_policy"]["policy_id"] == "EXECUTION_POLICY_V1"
    assert EXECUTION_POLICY_V1.fill_quantity_domain == (0, 1)
    h.quotes.ask_size = 0
    d2 = _scan(h)
    assert _rec(h, d2["receipts"]["fill"])["quantity_filled"] == 0


# ================================================================== fees charged once; Book identities

def test_fees_are_charged_once_per_side_and_the_book_recomputes_them(tmp_path):
    h = _h(tmp_path)
    d = _scan(h)
    fill = d["receipts"]["fill"]
    o = _exit(h, fill)
    rows = _rows(h)
    f, oc = rows[fill["seq"] - 1], rows[o["seq"] - 1]
    assert f["fees_entry"] == {**f["fees_entry"], "total": 0.97, "side": "BUY", "schedule_id": "SYNTHETIC_FEES_V1"}
    assert oc["fees_exit"]["total"] == 1.0 and oc["fees_exit"]["side"] == "SELL"
    assert f["cashflow_entry"] == -250.97 and oc["cashflow_exit"] == 269.0 and oc["gross_pnl"] == 20.0 and oc["pnl"] == 18.03
    book = h.bd.book()
    assert book.problems == [] and book.cash == round(10_000.0 - 250.97 + 269.0, 2) == 10_018.03
    assert book.total_realized_pnl == 18.03 and book.cash_identity()["holds"] is True
    assert [c["kind"] for c in book.cashflows] == ["ENTRY", "EXIT"]
    # tamper the stored aggregate: the Book recomputes from primary fields and names the disagreement
    lines = h.ledger.read_text().splitlines()
    rec = json.loads(lines[fill["seq"] - 1]); rec["net_debit"] = 1.0; rec["fees_entry"]["total"] = 0.0
    lines[fill["seq"] - 1] = json.dumps(rec, sort_keys=True); h.ledger.write_text("\n".join(lines) + "\n")
    tampered = BK.load_book(h.ledger, session_id=h.session_id, fee_schedules={"SYNTHETIC_FEES_V1": SYNTHETIC_FEES})
    assert any(p.startswith("FILL_DEBIT_DISAGREES") for p in tampered.problems)
    assert any("FEE_TOTAL_DISAGREES" in p for p in tampered.problems)


def test_book_reconstructs_independently_from_records(tmp_path):
    h = _h(tmp_path)
    d1 = _scan(h)
    _exit(h, d1["receipts"]["fill"])                                # closed, +18.03
    d2 = _scan(h)                                                   # open position
    _fr, ir = _pending(h, scan_id="SYN-SESSION-1:0009:SPY")         # reservation (unfilled)
    rows = _rows(h)
    book = BK.Book(rows, session_id=h.session_id, fee_schedules={"SYNTHETIC_FEES_V1": SYNTHETIC_FEES})
    s = book.summary()
    assert s["n_closed"] == 1 and s["n_positions"] == 1 and s["n_reservations"] == 1
    assert s["open_cost"] == 250.0 and s["reserved"] == 270.0 and s["session_realized_pnl"] == 18.03
    assert s["cash"] == round(10_000 + 18.03 - 250.97, 2) and s["cash_identity"]["holds"] is True
    assert s["outstanding"] == {"unfinished_intents": [ir["seq"]], "unresolved_positions": [d2["receipts"]["fill"]["seq"]],
                                "exit_exhausted_positions": []}
    ri = book.risk_inputs(symbol=SYM)
    assert ri["open_risk"] == 520.0 and ri["same_underlying_risk"] == 520.0 and ri["beta_family"] == "US_EQUITY_INDEX"
    assert ri["available_capital"] == round(s["cash"] - 270.0, 2)
    # a fresh process reconstructs the same state
    assert BK.load_book(h.ledger, session_id=h.session_id, fee_schedules={"SYNTHETIC_FEES_V1": SYNTHETIC_FEES}).state_hash() == book.state_hash()


# ================================================================== exit policy

def test_exit_policy_refuses_early_valuation_and_governs_the_window(tmp_path):
    h = _h(tmp_path)
    d = _scan(h)
    fill = d["receipts"]["fill"]
    with pytest.raises(B.BoundaryRefused, match="EXIT_NOT_DUE"):
        S.resolve(h.bd, fill_receipt=fill, exit_quote_fn=h.exit_quotes)
    sched = _rec(h, fill)["exit_schedule"]
    assert sched["exit_due_epoch"] == _rec(h, fill)["committed_epoch"] + 900.0 and sched["policy_id"] == EXIT_POLICY_V1.policy_id
    h.t = sched["exit_due_epoch"]
    h.exit_quotes.override = lambda c: None
    for k in range(EXIT_POLICY_V1.max_attempts):
        o = S.resolve(h.bd, fill_receipt=fill, exit_quote_fn=h.exit_quotes)
        assert o["status"] == "NOT_ESTIMABLE" and o["attempt"] == k + 1
        h.advance(EXIT_POLICY_V1.retry_spacing_s)
    with pytest.raises(B.BoundaryRefused, match="EXIT_WINDOW_EXHAUSTED"):
        S.resolve(h.bd, fill_receipt=fill, exit_quote_fn=h.exit_quotes)
    ex = h.bd.record_exit_exhausted(fill)
    assert _rec(h, ex)["obligation"].startswith("POSITION REMAINS UNRESOLVED")
    assert h.bd.book().outstanding["exit_exhausted_positions"] == [fill["seq"]]
    # a labelled recovery attempt may still discharge it
    h.exit_quotes.override = None
    o = S.resolve(h.bd, fill_receipt=fill, exit_quote_fn=h.exit_quotes, recovery=True)
    assert o["status"] == "RESOLVED" and _rec(h, o)["exit_policy_status"] == "EXHAUSTED_RECOVERY_ATTEMPT"
    assert h.bd.book().outstanding["unresolved_positions"] == []


def test_attempt_exits_drives_the_policy_deterministically(tmp_path):
    h = _h(tmp_path)
    d = _scan(h)
    calls = []
    def flaky(c):
        calls.append(h.now())
        return None if len(calls) < 3 else h.exit_quotes(c)
    out = S.attempt_exits(h.bd, exit_quote_fn=flaky, sleep_fn=h.advance)
    assert len(out) == 1 and out[0]["final"] == "RESOLVED" and [a["status"] for a in out[0]["attempts"]] == ["NOT_ESTIMABLE"] * 2 + ["RESOLVED"]
    due = _rec(h, d["receipts"]["fill"])["exit_schedule"]["exit_due_epoch"]
    assert calls[0] == due and calls[1] == due + 15.0 and calls[2] == due + 30.0


# ================================================================== restart before / after durable entry and exit

def test_restart_before_and_after_durable_entry_and_exit(tmp_path, monkeypatch):
    # before durable entry: provider dies -> no fill; the reservation survives; resume fills once
    h = _h(tmp_path)
    _fr, ir = _pending(h)
    h.quotes.fail_with = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    assert h.bd.book().reserved == 270.0
    h.quotes.fail_with = None
    h2 = SyntheticHarness(h.ledger, risk="certified", t0=h.now() + 5.0)
    acts = S.resume(h2.bd, quote_fn=h2.quotes)
    assert acts[0]["action"] == "EXECUTED" and acts[0]["status"] == "FILLED"
    b = h2.bd.book()
    assert b.reserved == 0.0 and b.open_cost == 250.0
    # after durable entry, before ack: redelivery reconciles; the Book sees exactly one position
    real = L.append_with_receipt
    def crash_after_write(path, entry):
        r = real(path, entry)
        if entry.get("kind") == "pilot_outcome":
            raise KeyboardInterrupt("died after fsync, before ack")
        return r
    fill = acts[0]["receipt"]
    h2.t = _rec(h2, fill)["exit_schedule"]["exit_due_epoch"]
    monkeypatch.setattr(L, "append_with_receipt", crash_after_write)
    with pytest.raises(KeyboardInterrupt):
        S.resolve(h2.bd, fill_receipt=fill, exit_quote_fn=h2.exit_quotes)
    monkeypatch.setattr(L, "append_with_receipt", real)
    h3 = SyntheticHarness(h.ledger, risk="certified", t0=h2.now() + 1.0)
    b3 = h3.bd.book()
    assert b3.positions == [] and len(b3.closed) == 1 and b3.total_realized_pnl == 18.03     # the exit WAS durable
    again = S.resolve(h3.bd, fill_receipt=fill, exit_quote_fn=h3.exit_quotes)
    assert again["reconciled"] is True and [r["kind"] for r in _rows(h3)].count("pilot_outcome") == 1
    assert S.recover_positions(h3.bd) == {"own": [], "foreign": []}
    L.verify_chain(h.ledger)


# ================================================================== the real script seam with the certified authority

def test_real_entry_point_with_certified_authority_and_synthetic_fees(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LEGACY PATH")
    monkeypatch.setattr(sess, "_scan_symbol", boom)
    monkeypatch.setattr(sess.paper_execution, "simulate_entry", boom)
    led = tmp_path / "led.jsonl"
    h = SyntheticHarness(led, session_id="ACC-1", risk="certified")
    argv = ["--ledger", str(led), "--out", str(tmp_path / "out.json"), "--symbols", "SPY,QQQ", "--dry-run",
            "--pilot-boundary", "--pilot-session-id", "ACC-1", "--pilot-release", "synthetic-release"]
    assert sess.main(argv, pilot_sources=E._HarnessProvider(h)) == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["risk_authority"] == "CertifiedRiskAuthority" and rep["fee_schedule"]["schedule_id"] == "SYNTHETIC_FEES_V1"
    assert rep["exit_policy"]["policy_id"] == "EXIT_AT_HORIZON_15M_V1" and rep["execution_policy"]["policy_id"] == "EXECUTION_POLICY_V1"
    assert [d["decision"] for d in rep["decisions"]] == ["TRADE", "TRADE"]
    assert all(o["final"] == "RESOLVED" for o in rep["outcomes"]) and rep["completion"] == "CLOSED_CLEAN"
    book = rep["book"]
    assert book["n_closed"] == 2 and book["session_realized_pnl"] == 36.06 and book["cash_identity"]["holds"] is True
    assert book["integrity_problems"] == [] and book["fees_unknown"] is False
    rows = L.read_all(led)
    intents = [r for r in rows if r["kind"] == "pilot_intent"]
    assert all(r["risk"]["risk_provenance"] == "CERTIFIED_KERNEL" and r["risk"]["kernel_check_at_commit"]["approved"] for r in intents)
    # the second intent's kernel check saw the first position on the Book
    assert intents[1]["risk"]["book_summary_at_commit"]["n_positions"] == 1
    L.verify_chain(led)
