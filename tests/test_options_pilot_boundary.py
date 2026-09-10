"""OPTIONS-PILOT-001 recording boundary, proven through the SESSION
orchestration on synthetic fixtures. No feed, no broker, no capital.

What these establish: event order by ledger sequence, receipts re-read from
disk, refusal on missing/incompatible forecasts, on unknown/altered/mismatched
references, on write failure, on the wrong contract, on a stale SELECTED
contract; restart and duplicate delivery cannot fill twice; every record is
labelled prospective paper. They do not establish edge or feed behaviour."""
import json
import os
from pathlib import Path

import pytest

from apex.options_pilot import boundary as B, ledger as L, records as R, session as S
from apex.options_pilot.expression_rule import DTE_MIN_DAYS, RULE_ID

SYM = "SPY"
AS_OF = "2026-09-10T14:00:00Z"
T0 = 1_789_000_000.0                                     # synthetic epoch for the clock


def _forecast(**over):
    f = {"symbol": SYM, "target": R.FORECAST_TARGET, "units": R.FORECAST_UNITS, "horizon_minutes": 15,
         "family": "STUDENT_T", "location": 1.2e-5, "scale": 3.1e-4, "nu": 6.384478029123821,
         "model_id": "EXP002_L", "model_hash": "9155024f51825d13487cdc035432d85b357d22e3",
         "params_hash": "ca04fc6e713e1a5c" * 2, "input_cutoff_utc": "2026-09-10T13:59:00Z",
         "created_utc": "2026-09-10T13:59:30Z", "direction_signal": "LONG",
         "validation_status": "NOT_VALIDATED: parameters from a NOT_SELECTED experiment; no edge claim"}
    f.update(over)
    return f


CHAIN = [{"expiration": "2026-10-09", "strike": k, "right": r} for k in (640.0, 645.0, 650.0, 655.0) for r in ("CALL", "PUT")] + \
        [{"expiration": "2026-09-18", "strike": 645.0, "right": "CALL"}]          # 8 DTE: ineligible


def _quote(contract, *, ask=2.50, bid=2.40, ask_size=12, bid_size=9, age=1.0, **over):
    q = {"symbol": contract["symbol"], "expiration": contract["expiration"], "strike": contract["strike"],
         "right": contract["right"], "bid": bid, "ask": ask, "bid_size": bid_size, "ask_size": ask_size,
         "timestamp_epoch": T0 - age}
    q.update(over)
    return q


def _sources(**over):
    src = {"forecast_fn": lambda s, t: _forecast(), "signal_fn": lambda s, t: "LONG",
           "chain_fn": lambda s, t: CHAIN, "spot_fn": lambda s, t: 646.3,
           "quote_fn": lambda c: _quote(c), "risk_fn": lambda p: {"approved": True, "certified_max_loss": 250.0},
           "clock_fn": lambda: T0}
    src.update(over)
    return src


def _kinds(ledger):
    return [r.get("kind") for r in L.read_all(ledger)]


# ------------------------------------------------------------------ order, receipts, labels

def test_order_is_proven_by_ledger_sequence_and_receipts_are_reread(tmp_path):
    led = tmp_path / "pilot.jsonl"
    S.open_session(led, session="S1", symbol=SYM, release="test")
    out = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources())
    f, i, fl = out["forecast_receipt"], out["intent_receipt"], out["fill_receipt"]
    assert f["seq"] < i["seq"] < fl["seq"]                                   # order by append, not by timestamps
    assert _kinds(led) == ["pilot_session_open", "pilot_forecast", "pilot_intent", "pilot_fill"]
    for rc, kind in ((f, "pilot_forecast"), (i, "pilot_intent"), (fl, "pilot_fill")):
        rec = L.verify_receipt(led, rc, expected_kind=kind)                 # re-read and hash-verified
        assert rec["entry_hash"] == rc["entry_hash"] and L.recompute_entry_hash(rec) == rec["entry_hash"]
        assert "RE-READ" in rc["receipt"]
    rows = L.read_all(led)
    intent, fill = rows[i["seq"] - 1], rows[fl["seq"] - 1]
    assert intent["forecast_ref"] == {"seq": f["seq"], "entry_hash": f["entry_hash"], "forecast_hash": f["forecast_hash"]}
    assert fill["intent_ref"] == {"seq": i["seq"], "entry_hash": i["entry_hash"]}
    assert fill["status"] == "FILLED" and fill["side_crossed"] == "ASK" and fill["price"] == 2.50 and fill["net_debit"] == 250.0
    assert intent["expression"] == "LONG_CALL" and intent["contract"] == {"symbol": SYM, "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"}
    assert intent["expression_rule"] == RULE_ID and intent["no_best_option_claim"] is True
    # the exit quote must itself be fresh at the resolve clock: stamp it there
    o = S.resolve(led, fill_receipt=fl, exit_quote_fn=lambda c: _quote(c, bid=2.70, ask=2.80, timestamp_epoch=T0 + 59),
                  clock_fn=lambda: T0 + 60)
    assert o["status"] == "RESOLVED" and o["seq"] > fl["seq"]
    outc = L.read_all(led)[o["seq"] - 1]
    assert outc["exit_side"] == "BID" and outc["pnl"] == 20.0 and outc["fees"] == "NOT_MODELLED_IN_THIS_BRICK"
    close = S.close_session(led, session="S1")
    assert L.read_all(led)[close["seq"] - 1]["unfilled_intents_at_close"] == 0


def test_every_record_is_prospective_paper_and_never_replay(tmp_path):
    led = tmp_path / "p.jsonl"
    out = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources())
    S.resolve(led, fill_receipt=out["fill_receipt"], exit_quote_fn=lambda c: _quote(c), clock_fn=lambda: T0 + 1)
    with pytest.raises(B.BoundaryRefused):                                    # a refusal record too
        S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(forecast_fn=lambda s, t: _forecast(horizon_minutes=30)))
    rows = L.read_all(led)
    assert len(rows) >= 5
    for r in rows:
        assert r["evidence_class"] == "PROSPECTIVE_PAPER" and r["decision_power"] == "NONE_PAPER"
        assert r["live_capital"] == "LOCKED" and r["live_promotion_eligible"] is False
        assert not any(bad in json.dumps(r) for bad in R.FORBIDDEN_CLASSES)
    with pytest.raises(R.RecordRefused, match="REPLAY_LABEL"):
        R.assert_prospective({**R.LABELS, "law": "HISTORICAL_DEVELOPMENT_REPLAY -- never prospective"})


def test_forecast_meaning_is_explicit_and_the_trend_label_is_only_a_signal(tmp_path):
    led = tmp_path / "p.jsonl"
    out = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources())
    f = L.read_all(led)[out["forecast_receipt"]["seq"] - 1]
    for k in R.FORECAST_REQUIRED + ("nu", "forecast_hash", "forecast_meaning", "direction_signal_meaning"):
        assert k in f, k
    assert f["horizon_minutes"] == 15 and f["family"] == "STUDENT_T" and f["nu"] > 2
    assert "NOT an expected directional move" in f["forecast_meaning"]
    assert f["direction_signal"] == "LONG" and "HEURISTIC" in f["direction_signal_meaning"]
    assert f["validation_status"].startswith("NOT_VALIDATED")


# ------------------------------------------------------------------ forecast refusals

@pytest.mark.parametrize("bad, reason", [
    (dict(horizon_minutes=30), "FORECAST_HORIZON_INCOMPATIBLE"),
    (dict(horizon_minutes=15.0001), "FORECAST_HORIZON_INCOMPATIBLE"),
    (dict(target="expected move to close"), "FORECAST_TARGET_INCOMPATIBLE"),
    (dict(family="LOGNORMAL"), "FORECAST_FAMILY_UNKNOWN"),
    (dict(scale=0.0), "FORECAST_PARAMETERS_INVALID"),
    (dict(location=float("nan")), "FORECAST_PARAMETERS_INVALID"),
    (dict(nu=1.5), "FORECAST_NU_INVALID"),
    (dict(params_hash="short"), "FORECAST_PARAMS_HASH_INVALID"),
    (dict(created_utc="2026-09-10T13:58:00Z"), "FORECAST_CREATED_BEFORE_INPUT_CUTOFF"),
    (dict(input_cutoff_utc="2026-09-10 13:59:00"), "FORECAST_INPUT_CUTOFF_UTC_NOT_UTC"),
    (dict(direction_signal="UP"), "DIRECTION_SIGNAL_INVALID"),
])
def test_missing_or_incompatible_forecasts_are_recorded_refusals(tmp_path, bad, reason):
    led = tmp_path / "p.jsonl"
    with pytest.raises(B.BoundaryRefused, match=reason):
        S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(forecast_fn=lambda s, t: _forecast(**bad)))
    rows = L.read_all(led)
    assert rows and rows[-1]["kind"] == "pilot_refusal" and rows[-1]["stage"] == "forecast" and reason in rows[-1]["reason"]
    assert not any(r["kind"] in ("pilot_intent", "pilot_fill") for r in rows)


def test_missing_forecast_fields_refuse(tmp_path):
    led = tmp_path / "p.jsonl"
    f = _forecast(); f.pop("params_hash"); f.pop("scale")
    with pytest.raises(B.BoundaryRefused, match="FORECAST_MISSING_FIELDS"):
        S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(forecast_fn=lambda s, t: f))
    assert _kinds(led) == ["pilot_refusal"]


# ------------------------------------------------------------------ persistence failure

def test_failed_persistence_prevents_entry(tmp_path, monkeypatch):
    led = tmp_path / "p.jsonl"
    f_ok = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources())["forecast_receipt"]      # a healthy ledger first
    n_before = len(L.read_all(led))
    real = L.chain_append
    calls = {"n": 0}
    def dying(path, entry):
        calls["n"] += 1
        raise OSError("disk full")
    monkeypatch.setattr(L, "chain_append", dying)
    with pytest.raises(B.BoundaryRefused, match="PERSISTENCE_FAILED"):
        S.scan(led, symbol=SYM, as_of=AS_OF, **_sources())
    monkeypatch.setattr(L, "chain_append", real)
    assert len(L.read_all(led)) == n_before                          # nothing landed, not even the refusal
    assert calls["n"] >= 1
    # an unwritable ledger directory refuses too, before any fill
    ro = tmp_path / "ro"; ro.mkdir(); os.chmod(ro, 0o500)
    try:
        with pytest.raises(B.BoundaryRefused):
            S.scan(ro / "p.jsonl", symbol=SYM, as_of=AS_OF, **_sources())
        assert not (ro / "p.jsonl").exists()
    finally:
        os.chmod(ro, 0o700)


def test_persistence_is_proven_by_reread_not_by_return_value(tmp_path, monkeypatch):
    """If the append reports success but the bytes are not on disk, refuse."""
    led = tmp_path / "p.jsonl"
    real = L.chain_append
    def lying(path, entry):
        body = real(path, entry)
        Path(path).write_text("")                                        # wipe what was written
        return body
    monkeypatch.setattr(L, "chain_append", lying)
    with pytest.raises(B.BoundaryRefused, match="PERSISTENCE_UNPROVEN"):
        B.record_forecast(led, _forecast())


# ------------------------------------------------------------------ references: unknown, altered, mismatched

def test_a_hash_shaped_string_is_not_a_receipt(tmp_path):
    led = tmp_path / "p.jsonl"
    B.record_forecast(led, _forecast())
    fake = {"path": str(led), "seq": 1, "entry_hash": "a" * 64, "forecast_hash": "b" * 64}
    with pytest.raises(B.BoundaryRefused, match="RECORD_HASH_MISMATCH"):
        B.record_intent(led, forecast_receipt=fake, intent=_proposal())
    with pytest.raises(B.BoundaryRefused, match="RECEIPT_SEQ_UNKNOWN"):
        B.record_intent(led, forecast_receipt={**fake, "seq": 99}, intent=_proposal())
    with pytest.raises(B.BoundaryRefused, match="RECEIPT_MALFORMED"):
        B.record_intent(led, forecast_receipt={"entry_hash": "a" * 64}, intent=_proposal())
    with pytest.raises(B.BoundaryRefused, match="RECEIPT_FOREIGN_LEDGER"):
        B.record_intent(led, forecast_receipt={**fake, "path": str(tmp_path / "other.jsonl")}, intent=_proposal())
    assert [r["kind"] for r in L.read_all(led)][1:] == ["pilot_refusal"] * 4


def _proposal(**over):
    p = {"expression": "LONG_CALL", "action": "BUY", "quantity": 1, "expression_rule": RULE_ID,
         "contract": {"symbol": SYM, "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"},
         "risk": {"approved": True}}
    p.update(over)
    return p


def test_an_altered_forecast_on_disk_refuses_the_intent(tmp_path):
    led = tmp_path / "p.jsonl"
    fr = B.record_forecast(led, _forecast())
    lines = led.read_text().splitlines()
    rec = json.loads(lines[fr["seq"] - 1]); rec["scale"] = 9.9e-4                  # tamper, keep the hash
    lines[fr["seq"] - 1] = json.dumps(rec, sort_keys=True); led.write_text("\n".join(lines) + "\n")
    with pytest.raises(B.BoundaryRefused, match="RECORD_ALTERED"):
        B.record_intent(led, forecast_receipt=fr, intent=_proposal())


def test_forecast_hash_mismatch_and_wrong_kind_refuse(tmp_path):
    led = tmp_path / "p.jsonl"
    fr = B.record_forecast(led, _forecast())
    with pytest.raises(B.BoundaryRefused, match="FORECAST_HASH_MISMATCH"):
        B.record_intent(led, forecast_receipt={**fr, "forecast_hash": "f" * 64}, intent=_proposal())
    ir = B.record_intent(led, forecast_receipt=fr, intent=_proposal())
    with pytest.raises(B.BoundaryRefused, match="RECORD_KIND_MISMATCH"):          # an intent receipt is not a forecast
        B.record_intent(led, forecast_receipt={**ir, "forecast_hash": fr["forecast_hash"]}, intent=_proposal())


def test_an_unapproved_or_wrong_symbol_intent_refuses(tmp_path):
    led = tmp_path / "p.jsonl"
    fr = B.record_forecast(led, _forecast())
    with pytest.raises(B.BoundaryRefused, match="INTENT_NOT_RISK_APPROVED"):
        B.record_intent(led, forecast_receipt=fr, intent=_proposal(risk={"approved": False, "why": "limit"}))
    with pytest.raises(B.BoundaryRefused, match="INTENT_NOT_RISK_APPROVED"):
        B.record_intent(led, forecast_receipt=fr, intent=_proposal(risk="yes"))
    with pytest.raises(B.BoundaryRefused, match="INTENT_SYMBOL_MISMATCH"):
        B.record_intent(led, forecast_receipt=fr, intent=_proposal(contract={"symbol": "QQQ", "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"}))
    with pytest.raises(B.BoundaryRefused, match="INTENT_QUANTITY_NOT_ONE"):
        B.record_intent(led, forecast_receipt=fr, intent=_proposal(quantity=2))
    with pytest.raises(B.BoundaryRefused, match="INTENT_EXPRESSION_NOT_IN_PILOT_RULE"):
        B.record_intent(led, forecast_receipt=fr, intent=_proposal(expression="CALL_VERTICAL"))


# ------------------------------------------------------------------ fill: wrong contract, staleness, size

def test_wrong_contract_at_execution_is_unfilled_and_recorded(tmp_path):
    led = tmp_path / "p.jsonl"
    wrong = lambda c: _quote({**c, "strike": 650.0})                   # quote for a neighbouring strike
    out = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(quote_fn=wrong))
    fill = L.read_all(led)[out["fill_receipt"]["seq"] - 1]
    assert fill["status"] == "UNFILLED" and fill["why"].startswith("CONTRACT_MISMATCH") and fill["quantity_filled"] == 0
    wrong_exp = lambda c: _quote({**c, "expiration": "2026-11-20"})
    out2 = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(quote_fn=wrong_exp))
    assert L.read_all(led)[out2["fill_receipt"]["seq"] - 1]["why"].startswith("CONTRACT_MISMATCH")


def test_freshness_is_checked_for_the_selected_contract_and_side(tmp_path):
    """A fresh quote elsewhere in the chain must not mask a stale selected contract."""
    led = tmp_path / "p.jsonl"
    stale_selected = lambda c: _quote(c, age=16.0)                     # 16 s > 15 s limit on the ASK side
    out = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(quote_fn=stale_selected))
    fill = L.read_all(led)[out["fill_receipt"]["seq"] - 1]
    assert fill["status"] == "UNFILLED" and fill["why"].startswith("STALE_SELECTED_CONTRACT: ASK side 16.0s")
    fresh_enough = lambda c: _quote(c, age=14.9)
    out2 = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(quote_fn=fresh_enough))
    assert L.read_all(led)[out2["fill_receipt"]["seq"] - 1]["status"] == "FILLED"
    future = lambda c: _quote(c, age=-2.0)
    out3 = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(quote_fn=future))
    assert L.read_all(led)[out3["fill_receipt"]["seq"] - 1]["why"].startswith("QUOTE_FROM_THE_FUTURE")


def test_one_contract_is_filled_or_unfilled_explicitly(tmp_path):
    led = tmp_path / "p.jsonl"
    out = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(quote_fn=lambda c: _quote(c, ask_size=0)))
    fill = L.read_all(led)[out["fill_receipt"]["seq"] - 1]
    assert fill["status"] == "UNFILLED" and fill["why"] == "NO_SIZE_AT_ASK" and fill["net_debit"] == 0.0
    o = S.resolve(led, fill_receipt=out["fill_receipt"], exit_quote_fn=lambda c: _quote(c), clock_fn=lambda: T0 + 1)
    assert o["status"] == "NO_POSITION"
    out2 = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(quote_fn=lambda c: _quote(c, ask=None)))
    assert L.read_all(led)[out2["fill_receipt"]["seq"] - 1]["why"].startswith("QUOTE_SIDE_MISSING")


def test_stale_exit_quote_is_not_estimable(tmp_path):
    """The exit side is freshness-checked too: a 61 s-old bid at resolve time is NOT_ESTIMABLE."""
    led = tmp_path / "p.jsonl"
    out = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources())
    o = S.resolve(led, fill_receipt=out["fill_receipt"], exit_quote_fn=lambda c: _quote(c, bid=2.70, ask=2.80),
                  clock_fn=lambda: T0 + 60)                                      # quote stamped T0-1 -> 61 s old
    rec = L.read_all(led)[o["seq"] - 1]
    assert rec["status"] == "NOT_ESTIMABLE" and rec["why"].startswith("STALE_SELECTED_CONTRACT: BID side 61.0s")


def test_missing_exit_quote_is_not_estimable_never_imputed(tmp_path):
    led = tmp_path / "p.jsonl"
    out = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources())
    o = S.resolve(led, fill_receipt=out["fill_receipt"], exit_quote_fn=lambda c: None, clock_fn=lambda: T0 + 1)
    rec = L.read_all(led)[o["seq"] - 1]
    assert rec["status"] == "NOT_ESTIMABLE" and rec["pnl"] is None and "never imputed" in rec["exit_law"]
    with pytest.raises(B.BoundaryRefused, match="DUPLICATE_OUTCOME"):
        S.resolve(led, fill_receipt=out["fill_receipt"], exit_quote_fn=lambda c: _quote(c), clock_fn=lambda: T0 + 2)


# ------------------------------------------------------------------ crash / restart / duplicate delivery

def test_crash_after_intent_then_restart_fills_exactly_once(tmp_path):
    led = tmp_path / "p.jsonl"
    boom = lambda c: (_ for _ in ()).throw(RuntimeError("process died before the quote"))
    with pytest.raises(RuntimeError):
        S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(quote_fn=boom))
    assert _kinds(led) == ["pilot_forecast", "pilot_intent"]                     # intent on disk, no fill
    assert len(S.unfilled_intents(led)) == 1
    done = S.resume(led, quote_fn=lambda c: _quote(c), clock_fn=lambda: T0 + 5)  # restart: rebuilt from disk
    assert len(done) == 1 and done[0]["status"] == "FILLED"
    assert S.unfilled_intents(led) == []
    again = S.resume(led, quote_fn=lambda c: _quote(c), clock_fn=lambda: T0 + 6)  # second restart: nothing to do
    assert again == []
    assert _kinds(led).count("pilot_fill") == 1


def test_duplicate_delivery_of_an_intent_cannot_fill_twice(tmp_path):
    led = tmp_path / "p.jsonl"
    out = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources())
    with pytest.raises(B.BoundaryRefused, match="DUPLICATE_DELIVERY"):
        B.execute_intent(led, intent_receipt=out["intent_receipt"], quote_fn=lambda c: _quote(c), now_epoch=T0 + 1)
    assert _kinds(led).count("pilot_fill") == 1 and _kinds(led)[-1] == "pilot_refusal"


def test_a_forecast_cannot_back_two_intents(tmp_path):
    led = tmp_path / "p.jsonl"
    fr = B.record_forecast(led, _forecast())
    B.record_intent(led, forecast_receipt=fr, intent=_proposal())
    with pytest.raises(B.BoundaryRefused, match="FORECAST_ALREADY_CONSUMED"):
        B.record_intent(led, forecast_receipt=fr, intent=_proposal())


def test_quote_is_requested_only_after_the_intent_is_on_disk(tmp_path):
    led = tmp_path / "p.jsonl"
    seen = {}
    def quote_fn(c):
        seen["intent_present"] = any(r.get("kind") == "pilot_intent" for r in L.read_all(led))
        seen["records_before_quote"] = len(L.read_all(led))
        return _quote(c)
    out = S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(quote_fn=quote_fn))
    assert seen["intent_present"] is True
    assert seen["records_before_quote"] == out["intent_receipt"]["seq"]         # quote came strictly after seq(intent)


# ------------------------------------------------------------------ rule refusals through the session

def test_rule_refusals_are_recorded_after_the_forecast(tmp_path):
    led = tmp_path / "p.jsonl"
    with pytest.raises(B.BoundaryRefused, match="NO_DIRECTION_SIGNAL"):
        S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(signal_fn=lambda s, t: None))
    assert _kinds(led) == ["pilot_forecast", "pilot_refusal"]
    short_chain = [{"expiration": "2026-09-18", "strike": 645.0, "right": "CALL"}]   # only 8 DTE
    with pytest.raises(B.BoundaryRefused, match="NO_ELIGIBLE_EXPIRY"):
        S.scan(led, symbol=SYM, as_of=AS_OF, **_sources(chain_fn=lambda s, t: short_chain))
    assert DTE_MIN_DAYS == 21
