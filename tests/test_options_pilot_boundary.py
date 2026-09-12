"""OPTIONS-PILOT-001 recording boundary (repaired), proven through the SESSION
orchestration on the EXPLICIT synthetic harness. No feed, no broker, no capital.

What these establish: event order by ledger sequence; receipts re-read from
disk with the referenced HISTORY chain-verified; a causal clock contract on
every recorded instant (parsed, one timeline, freshness measured after quote
receipt); finite values and strict serialization; risk approval bound to the
intent (self-attestation refused); atomic session-scoped idempotency under
concurrent workers and crash/restart; a resume policy that retires stale
intents instead of executing them forever; every record labelled prospective
paper with explicit SYNTHETIC provenance. They do not establish edge, feed
behaviour or risk certification."""
import json
import math
import os
import threading
from pathlib import Path

import pytest

from apex.options_pilot import boundary as B, ledger as L, records as R, risk_gate as RG, session as S
from apex.options_pilot import clock as C
from apex.options_pilot.expression_rule import DTE_MIN_DAYS, RULE_ID, RULE_ID_V2
from apex.options_pilot.synthetic_harness import SYNTHETIC_PARAMS, SyntheticHarness, T0, forecast_from_params

SYM = "SPY"
T_MINUTE = 1_789_000_020.0          # a minute boundary: the harness forecast's input cutoff equals its creation instant,
                                    # so the intent TTL (120 s) rather than forecast freshness (120 s from cutoff) binds


def _h(tmp_path, **kw) -> SyntheticHarness:
    return SyntheticHarness(tmp_path / "pilot.jsonl", **kw)


def _scan(h: SyntheticHarness, seq=None, **over):
    src = h.sources(); src.pop("exit_quote_fn"); src.update(over)
    seq = S.next_seq(h.ledger, session_id=h.session_id) if seq is None else seq
    return S.scan(h.bd, symbol=SYM, seq=seq, **src)


def _rows(h):
    return L.read_all(h.ledger)


def _kinds(h):
    return [r.get("kind") for r in _rows(h)]


def _rec(h, receipt):
    return _rows(h)[receipt["seq"] - 1]


def _exit(h, fill_receipt, exit_quote_fn=None, **kw):
    """Advance the controlled clock to the frozen exit policy's due instant (if not already past) and value."""
    rec = _rec(h, fill_receipt)
    if rec.get("status") == "FILLED":
        h.t = max(h.t, rec["exit_schedule"]["exit_due_epoch"])
    return S.resolve(h.bd, fill_receipt=fill_receipt, exit_quote_fn=exit_quote_fn or h.exit_quotes, **kw)


# ================================================================== reproduced failures (the old boundary)

def test_reproduced_old_defects_are_now_refused(tmp_path):
    """Each of these passed the 2eaab8f6 boundary (reproduced against that
    code before the repair; see the brick record). They are refused now."""
    # (a) a NaN provider TIMESTAMP passed `_quote_ok`: age = now - nan = nan, and both `nan < 0` and
    #     `nan > 15` are False, so a NaN-stamped quote FILLED.
    nan_age = T0 - float("nan")
    assert not (nan_age < 0) and not (nan_age > 15.0)
    contract = {"symbol": SYM, "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"}
    q = {**contract, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12, "timestamp_epoch": float("nan")}
    with pytest.raises(R.RecordRefused, match="timestamp_epoch: must be a finite real"):
        R.validate_quote(q, contract=contract)
    # (b) `risk={"approved": True}` supplied by the caller was authorization.
    with pytest.raises(RG.RiskRefused, match="self-attestation"):
        RG.verify_approval({"intent_id": "x"}, {"approved": True})
    # (c) time was checked with `endswith("Z")`: a naive or malformed instant with a Z pasted on passed.
    assert "2026-09-10 25:99:00Z".endswith("Z")
    with pytest.raises(C.ClockRefused, match="unparseable"):
        C.parse_utc("2026-09-10 25:99:00Z", field="t")
    with pytest.raises(C.ClockRefused, match="naive"):
        C.parse_utc("2026-09-10T14:00:00", field="t")
    # (d) freshness used a clock reading taken BEFORE quote_fn ran: a provider that stamped its quote at request
    #     time and then took 20 s to deliver looked 1 s old. Now the reading is taken AFTER receipt: 21 s -> WAIT.
    h = _h(tmp_path)
    def slow_then_stale(c):
        q = {**c, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12, "timestamp_epoch": h.now() - 1.0}
        h.advance(20.0)
        return q
    h.quotes.override = slow_then_stale
    d = _scan(h)
    assert d["decision"] == "WAIT" and d["why"].startswith("STALE_SELECTED_CONTRACT: ASK side 21.000s")
    fill = _rec(h, d["receipts"]["fill"])
    assert fill["quote_receipt_epoch"] - fill["quote_request_epoch"] == pytest.approx(20.0)
    assert fill["provider_latency_s"] == pytest.approx(20.0) and fill["quote_age_at_receipt_s"] == pytest.approx(21.0)


# ================================================================== order, receipts, labels, ids

def test_order_is_proven_by_ledger_sequence_and_history_is_chain_verified(tmp_path):
    h = _h(tmp_path)
    S.open_session(h.bd, symbols=[SYM])
    d = _scan(h)
    assert d["decision"] == "TRADE" and d["scan_id"] == "SYN-SESSION-1:0001:SPY"
    f, i, fl = d["receipts"]["forecast"], d["receipts"]["intent"], d["receipts"]["fill"]
    assert f["seq"] < i["seq"] < fl["seq"]
    assert _kinds(h) == ["pilot_session_open", "pilot_forecast", "pilot_intent", "pilot_fill", "pilot_decision"]
    for rc, kind in ((f, "pilot_forecast"), (i, "pilot_intent"), (fl, "pilot_fill")):
        rec = L.verify_receipt(h.ledger, rc, expected_kind=kind)
        assert rec["entry_hash"] == rc["entry_hash"] and L.recompute_entry_hash(rec) == rec["entry_hash"]
        assert "link to predecessor verified" in rc["receipt"]
    L.verify_chain(h.ledger)
    intent, fill = _rec(h, i), _rec(h, fl)
    assert intent["forecast_ref"] == {"seq": f["seq"], "entry_hash": f["entry_hash"], "forecast_hash": f["forecast_hash"],
                                      "forecast_id": f["forecast_id"]}
    assert fill["intent_ref"]["seq"] == i["seq"] and fill["intent_ref"]["intent_id"] == intent["intent_id"]
    assert fill["status"] == "FILLED" and fill["decision"] == "TRADE" and fill["side_crossed"] == "ASK"
    assert fill["price"] == 2.50 and fill["net_debit"] == 250.0
    # PILOT_RULE_V2: spot 646.3, LONG -> the nearest strike on the CALL side (K >= spot) whose indicative ask fits the cap
    assert intent["expression"] == "LONG_CALL" and intent["contract"] == {"symbol": SYM, "expiration": "2026-10-09", "strike": 650.0, "right": "CALL"}
    assert intent["expression_rule"] == RULE_ID_V2 and intent["no_best_option_claim"] is True
    assert intent["strike_selection"]["rule"] == "PILOT_RULE_V2" and intent["strike_selection"]["cap_consulted"] is True
    assert intent["strike_selection"]["census"]["feasible"] >= 1 and "what_v1_could_not_express" in intent["strike_selection"]
    assert intent["signal_used"] == "LONG" and intent["risk"]["risk_provenance"] == "SYNTHETIC_FIXTURE"
    # stable ids: recomputable from content, and the decision record carries them
    assert intent["intent_id"] == R.canonical_hash({"forecast_id": f["forecast_id"], "contract_id": intent["contract_id"],
                                                    "signal_used": "LONG", "session_id": h.session_id})[:24]
    dec = _rec(h, d["decision_receipt"])
    assert (dec["forecast_id"], dec["intent_id"], dec["fill_id"]) == (f["forecast_id"], i["intent_id"], fl["fill_id"])
    # resolve at a later clock with a fresh exit quote
    h.advance(60.0)
    o = _exit(h, fl, h.exit_quotes)
    assert o["status"] == "RESOLVED" and o["seq"] > fl["seq"]
    outc = _rec(h, o)
    assert outc["exit_side"] == "BID" and outc["gross_pnl"] == 20.0
    assert fill["fees_entry"]["total"] == 0.97 and outc["fees_exit"]["total"] == 1.0 and outc["pnl"] == 18.03   # fees once per side
    assert outc["pnl_status"] == "NET_OF_FEES" and fill["cashflow_entry"] == -250.97 and outc["cashflow_exit"] == 269.0
    assert fill["simulated"] is True and fill["exit_schedule"]["policy_id"] == "EXIT_AT_HORIZON_15M_V1"
    close = S.close_session(h.bd)
    assert _rec(h, close)["unfinished_intent_seqs_at_close"] == []


def test_every_record_is_prospective_paper_synthetic_and_never_replay(tmp_path):
    h = _h(tmp_path)
    d = _scan(h)
    _exit(h, d["receipts"]["fill"], h.exit_quotes)
    h.forecast_override = lambda s, t: {**h.base_forecast(s, t), "horizon_minutes": 30}
    d2 = _scan(h)
    assert d2["decision"] == "REFUSE" and d2["refusal_persisted"] is True
    rows = _rows(h)
    assert len(rows) >= 6
    for r in rows:
        assert r["evidence_class"] == "PROSPECTIVE_PAPER" and r["decision_power"] == "NONE_PAPER"
        assert r["live_capital"] == "LOCKED" and r["live_promotion_eligible"] is False
        assert r["data_provenance"] == "SYNTHETIC_FIXTURE" and r["synthetic"] is True
        assert r["execution_mode"] == "PROSPECTIVE_ORCHESTRATION"
        assert not any(bad in json.dumps(r) for bad in R.FORBIDDEN_CLASSES)
    with pytest.raises(R.RecordRefused, match="REPLAY_LABEL"):
        R.assert_prospective({**R.LABELS, "data_provenance": "SYNTHETIC_FIXTURE", "law": "HISTORICAL_DEVELOPMENT_REPLAY"})
    with pytest.raises(R.RecordRefused, match="PROVENANCE_MISSING"):
        R.assert_prospective({**R.LABELS})


def test_forecast_meaning_is_explicit_and_does_not_drive_selection(tmp_path):
    h = _h(tmp_path)
    d = _scan(h)
    f = _rec(h, d["receipts"]["forecast"])
    for k in R.FORECAST_REQUIRED + ("nu", "forecast_hash", "forecast_id", "forecast_meaning", "direction_signal_meaning",
                                    "horizon_relationship", "epoch", "persisted_epoch"):
        assert k in f, k
    assert f["drives_expression_selection"] is False
    assert "NOT a hold-to-close forecast" in f["forecast_meaning"] and "DIFFERENT horizons" in f["horizon_relationship"]
    assert f["direction_signal"] == "LONG" and "HEURISTIC" in f["direction_signal_meaning"]
    assert f["artifact_digest"].startswith("SYNTHETIC:") and f["model_id"] == "SYNTHETIC_FIXTURE_MODEL"
    loc, scale = forecast_from_params(SYNTHETIC_PARAMS, **h.inputs)
    assert f["location"] == loc and f["scale"] == scale and f["inputs"] == h.inputs
    # the signal ACTUALLY used by the rule is persisted on the intent, and must agree with the forecast's label
    i = _rec(h, d["receipts"]["intent"])
    assert i["signal_used"] == "LONG"
    h.signal = "SHORT"
    h.forecast_override = lambda s, t: {**h.base_forecast(s, t), "direction_signal": "LONG"}
    d2 = _scan(h)
    assert d2["decision"] == "REFUSE" and "SIGNAL_DISAGREES_WITH_FORECAST_RECORD" in d2["why"]


def test_hold_horizon_extrapolation_is_refused(tmp_path):
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id="SYN-SESSION-1:0001:SPY")
    prop = {"expression": "LONG_CALL", "action": "BUY", "quantity": 1, "expression_rule": RULE_ID,
            "contract": {"symbol": SYM, "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"},
            "use_forecast_as_hold_expectation": True}
    with pytest.raises(B.BoundaryRefused, match="HORIZON_EXTRAPOLATION_REFUSED"):
        h.bd.record_intent(forecast_receipt=fr, intent=prop, signal_used="LONG", scan_id="SYN-SESSION-1:0001:SPY")


# ================================================================== causal clock contract

@pytest.mark.parametrize("bad, reason", [
    (dict(horizon_minutes=30), "FORECAST_HORIZON_INCOMPATIBLE"),
    (dict(horizon_minutes=15.0), "FORECAST_HORIZON_INCOMPATIBLE"),
    (dict(target="expected move to close"), "FORECAST_TARGET_INCOMPATIBLE"),
    (dict(family="LOGNORMAL"), "FORECAST_FAMILY_UNKNOWN"),
    (dict(scale=0.0), "scale: must be > 0"),
    (dict(scale=True), "scale: must be a finite real"),
    (dict(location=float("nan")), "location: must be a finite real"),
    (dict(location=float("inf")), "location: must be a finite real"),
    (dict(nu=1.5), "FORECAST_NU_INVALID"),
    (dict(nu=float("nan")), "FORECAST_NU_INVALID"),
    (dict(params_hash="short"), "FORECAST_PARAMS_HASH_INVALID"),
    (dict(direction_signal="UP"), "DIRECTION_SIGNAL_INVALID"),
    (dict(created_utc="2026-09-10T00:25:00Z"), "FORECAST_CREATED_BEFORE_INPUT_CUTOFF"),
    (dict(input_cutoff_utc="2026-09-10 00:25:00"), "input_cutoff_utc: naive timestamp"),
    (dict(input_cutoff_utc="not a time"), "input_cutoff_utc: unparseable"),
    (dict(created_utc=1789000000.0), "created_utc: not a timestamp string"),
    (dict(target_end_utc="2026-09-10T00:41:00Z"), "FORECAST_TARGET_END_INCOMPATIBLE"),
    (dict(input_event_time_utc="2026-09-10T00:26:00Z"), "FORECAST_INPUT_AFTER_REFERENCE"),
    (dict(input_available_utc="2026-09-10T00:24:00Z"), "FORECAST_AVAILABLE_BEFORE_EVENT"),
    (dict(input_cutoff_utc="2026-09-10T00:24:30Z"), "FORECAST_INPUT_NOT_AVAILABLE_BY_CUTOFF"),
    (dict(created_utc="2026-09-10T00:27:00Z"), "FORECAST_FROM_THE_FUTURE"),
])
def test_missing_or_incompatible_forecasts_are_recorded_refusals(tmp_path, bad, reason):
    h = _h(tmp_path)
    base = h.forecast_fn(SYM, h.now())
    # reference 00:25:00Z, available/cutoff 00:26:00Z, created 00:26:40Z on the one synthetic timeline (T0 = 2026-09-10T00:26:40Z)
    assert base["reference_time_utc"].startswith("2026-09-10T00:25:00") and base["created_utc"].startswith("2026-09-10T00:26:40")
    h.forecast_override = {**base, **bad}
    d = _scan(h)
    assert d["decision"] == "REFUSE" and reason in d["why"], d["why"]
    rows = _rows(h)
    ref = [r for r in rows if r["kind"] == "pilot_refusal"]
    assert ref and ref[-1]["stage"] == "forecast" and reason in ref[-1]["reason"]
    assert not any(r["kind"] in ("pilot_intent", "pilot_fill") for r in rows)


def test_the_fixture_clock_and_the_forecast_share_one_timeline(tmp_path):
    h = _h(tmp_path)
    assert C.parse_utc(C.to_utc_string(T0), field="t0") == T0
    f = h.forecast_fn(SYM, h.now())
    body = R.validate_forecast(f, now_epoch=h.now(), provenance="SYNTHETIC_FIXTURE", session_id="s", scan_id="s:0001:SPY")
    e = body["epoch"]
    assert e["reference"] <= e["input_event"] <= e["input_available"] <= e["input_cutoff"] <= e["created"] <= h.now()
    assert e["target_end"] - e["reference"] == 900.0
    assert C.parse_utc(body["created_utc"], field="c") == e["created"]


def test_clock_readings_and_timestamps_reject_bool_nan_inf(tmp_path):
    for bad in (True, float("nan"), float("inf"), "1789000000", None):
        with pytest.raises(C.ClockRefused):
            C.check_reading(bad)
    with pytest.raises(C.ClockRefused):
        C.Clock(lambda: float("nan")).now()
    with pytest.raises(C.ClockRefused):
        C.to_utc_string(True)
    assert C.is_exact_int(1) and not C.is_exact_int(True) and not C.is_exact_int(1.0)
    assert C.is_real(1) and C.is_real(1.5) and not C.is_real(True) and not C.is_real(float("nan"))


def test_quote_timestamp_semantics_are_declared_and_request_order_is_not_generation_order(tmp_path):
    h = _h(tmp_path)
    d = _scan(h)
    fill = _rec(h, d["receipts"]["fill"])
    assert fill["quote_observed"]["timestamp_meaning"].startswith("PROVIDER_SNAPSHOT")
    assert "does NOT prove the provider generated the quote after the intent" in fill["order_proof"]
    assert fill["eligibility_policy"].startswith("QUOTE_ELIGIBILITY_V2")
    assert fill["quote_request_epoch"] <= fill["quote_receipt_epoch"]
    intent = _rec(h, d["receipts"]["intent"])
    assert intent["persisted_epoch"] <= fill["quote_request_epoch"]
    assert fill["quote_ts_minus_intent_persisted_s"] == pytest.approx(-1.0)
    # a provider timestamp 20 s BEFORE the intent was persisted cannot be 'fresh': receipt >= persisted, so age >= 20
    h.quotes.override = lambda c: {**c, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12,
                                   "timestamp_epoch": h.now() - 20.0}
    d2 = _scan(h)
    fill2 = _rec(h, d2["receipts"]["fill"])
    assert d2["decision"] == "WAIT" and fill2["quote_ts_minus_intent_persisted_s"] <= -20.0


# ================================================================== finite values, strict serialization, quote contract

@pytest.mark.parametrize("over, reason", [
    (dict(ask=float("nan")), "ask: must be a finite real"),
    (dict(ask=float("inf")), "ask: must be a finite real"),
    (dict(bid=float("-inf")), "bid: must be a finite real"),
    (dict(ask=True), "ask: must be a finite real"),
    (dict(ask=None), "ask: must be a finite real"),
    (dict(ask=0.0), "ask: must be > 0"),
    (dict(bid=2.6), "QUOTE_CROSSED"),
    (dict(ask_size=12.0), "ask_size: must be an exact int"),
    (dict(ask_size=True), "ask_size: must be an exact int"),
    (dict(ask_size=-1), "ask_size: must be >= 0"),
    (dict(timestamp_epoch="1789000000"), "timestamp_epoch: must be a finite real"),
    (dict(timestamp_epoch=float("nan")), "timestamp_epoch: must be a finite real"),
    (dict(right="C"), "QUOTE_CONTRACT_RIGHT_INVALID"),
    (dict(expiration="2026-13-40"), "QUOTE_CONTRACT_EXPIRATION_INVALID"),
])
def test_malformed_provider_quotes_refuse_through_the_session_path(tmp_path, over, reason):
    h = _h(tmp_path)
    h.quotes.override = lambda c: {**c, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12,
                                   "timestamp_epoch": h.now() - 1.0, **over}
    d = _scan(h)
    assert d["decision"] == "REFUSE" and reason in d["why"], d["why"]
    fill = _rec(h, d["receipts"]["fill"])
    assert fill["status"] == "UNFILLED" and fill["quantity_filled"] == 0 and fill["net_debit"] == 0.0
    for line in h.ledger.read_text().splitlines():                       # no NaN/Infinity TOKENS reached disk
        json.loads(line, parse_constant=lambda c: pytest.fail("non-finite token on disk: %s" % c))


def test_non_dict_and_failing_providers_fail_closed(tmp_path):
    h = _h(tmp_path)
    h.quotes.override = lambda c: [1, 2, 3]
    d = _scan(h)
    assert d["decision"] == "REFUSE" and "QUOTE_NOT_A_RECORD: 'list'" in d["why"]
    h.quotes.override = None
    h.quotes.fail_with = ConnectionError("provider down")
    d2 = _scan(h)
    assert d2["decision"] == "REFUSE" and "QUOTE_PROVIDER_FAILED: ConnectionError: provider down" in d2["why"]
    h.quotes.fail_with = None
    h.forecast_override = lambda s, t: (_ for _ in ()).throw(TimeoutError("forecast provider hung"))
    d3 = _scan(h)
    assert d3["decision"] == "REFUSE" and "FORECAST_PROVIDER_FAILED: TimeoutError" in d3["why"] and d3["refusal_persisted"]
    h.forecast_override = None
    h.chain = None
    d4 = _scan(h)
    assert d4["decision"] == "REFUSE" and "INPUT_PROVIDER_FAILED" in d4["why"]
    assert _kinds(h).count("pilot_fill") == 2 and not any(r.get("status") == "FILLED" for r in _rows(h))


def test_strict_serialization_refuses_nan_before_anything_lands(tmp_path):
    h = _h(tmp_path)
    with pytest.raises(L.LedgerRefused, match="NOT_STRICT_JSON"):
        L.append_with_receipt(h.ledger, {"kind": "x", "v": float("nan")})
    with pytest.raises(L.LedgerRefused, match="NOT_STRICT_JSON"):
        L.append_with_receipt(h.ledger, {"kind": "x", "v": float("inf")})
    with pytest.raises(L.LedgerRefused, match="ENTRY_CARRIES_CHAIN_FIELDS"):
        L.append_with_receipt(h.ledger, {"kind": "x", "entry_hash": "a" * 64})
    assert not h.ledger.exists()
    assert R.canonical_json({"b": 1, "a": [1.5, "x"]}) == '{"a":[1.5,"x"],"b":1}'


def test_boolean_quote_size_is_not_a_size(tmp_path):
    """`True < 1` is False in Python: the old `size < 1` check would have FILLED on size=True."""
    assert not (True < 1)
    h = _h(tmp_path)
    h.quotes.ask_size = True
    d = _scan(h)
    assert d["decision"] == "REFUSE" and "ask_size: must be an exact int" in d["why"]


# ================================================================== references, history, canonicalization, threat boundary

def _proposal(**over):
    p = {"expression": "LONG_CALL", "action": "BUY", "quantity": 1, "expression_rule": RULE_ID,
         "contract": {"symbol": SYM, "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"}}
    p.update(over)
    return p


SID = "SYN-SESSION-1:0001:SPY"


def test_a_hash_shaped_string_is_not_a_receipt(tmp_path):
    h = _h(tmp_path)
    h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    fake = {"path": str(h.ledger), "seq": 1, "entry_hash": "a" * 64, "forecast_hash": "b" * 64}
    with pytest.raises(B.BoundaryRefused, match="RECORD_HASH_MISMATCH"):
        h.bd.record_intent(forecast_receipt=fake, intent=_proposal(), signal_used="LONG", scan_id=SID)
    with pytest.raises(B.BoundaryRefused, match="RECEIPT_SEQ_UNKNOWN"):
        h.bd.record_intent(forecast_receipt={**fake, "seq": 99}, intent=_proposal(), signal_used="LONG", scan_id=SID)
    with pytest.raises(B.BoundaryRefused, match="RECEIPT_SEQ_UNKNOWN"):
        h.bd.record_intent(forecast_receipt={**fake, "seq": True}, intent=_proposal(), signal_used="LONG", scan_id=SID)
    with pytest.raises(B.BoundaryRefused, match="RECEIPT_MALFORMED"):
        h.bd.record_intent(forecast_receipt={"entry_hash": "a" * 64}, intent=_proposal(), signal_used="LONG", scan_id=SID)
    with pytest.raises(B.BoundaryRefused, match="RECEIPT_FOREIGN_LEDGER"):
        h.bd.record_intent(forecast_receipt={**fake, "path": str(tmp_path / "other.jsonl")}, intent=_proposal(),
                           signal_used="LONG", scan_id=SID)
    assert _kinds(h)[1:] == ["pilot_refusal"] * 5


def test_an_altered_predecessor_breaks_the_chain_not_just_the_record(tmp_path):
    """verify_receipt on record N verifies 1..N: tampering with an EARLIER record refuses N."""
    h = _h(tmp_path)
    S.open_session(h.bd, symbols=[SYM])
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    lines = h.ledger.read_text().splitlines()
    rec = json.loads(lines[0]); rec["symbols"] = ["QQQ"]                                # tamper seq 1, keep its hash
    lines[0] = json.dumps(rec, sort_keys=True); h.ledger.write_text("\n".join(lines) + "\n")
    with pytest.raises(B.BoundaryRefused, match="CHAIN_RECORD_ALTERED at seq 1"):
        h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=SID)
    # re-hash the tampered record consistently: the record verifies alone, but the LINK from seq 2 breaks
    rec["entry_hash"] = L.recompute_entry_hash(rec)
    lines = h.ledger.read_text().splitlines(); lines[0] = json.dumps(rec, sort_keys=True)
    h.ledger.write_text("\n".join(lines) + "\n")
    assert L.recompute_entry_hash(json.loads(lines[0])) == rec["entry_hash"]
    with pytest.raises(L.ChainBroken, match="CHAIN_LINK_BROKEN at seq 2"):
        L.verify_chain(h.ledger)
    with pytest.raises(L.LedgerRefused):
        L.verify_receipt(h.ledger, fr, expected_kind="pilot_forecast")
    assert L.verify_receipt(h.ledger, fr, expected_kind="pilot_forecast", chain=False)["kind"] == "pilot_forecast"


def test_state_canonicalization_recipe_is_the_documented_one(tmp_path):
    h = _h(tmp_path)
    rc = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    raw = h.ledger.read_text().splitlines()[0]
    rec = json.loads(raw)
    body = {k: v for k, v in rec.items() if k != "entry_hash"}
    import hashlib
    assert hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() == rec["entry_hash"] == rc["entry_hash"]
    assert rec["prev_hash"] == "GENESIS" and "default separators" in L.ENTRY_HASH_RECIPE
    # the recipe hashes the canonical re-serialization, NOT the raw line: re-serializing with other whitespace
    # yields a different line but the same entry_hash
    assert json.dumps(rec, sort_keys=True, indent=1) != raw and L.recompute_entry_hash(rec) == rec["entry_hash"]


def test_threat_boundary_a_consistent_rewrite_is_not_detected(tmp_path):
    """HONEST LIMIT: a writer with the file and the recipe can rewrite the chain consistently."""
    h = _h(tmp_path)
    _scan(h)
    rows = _rows(h)
    rows[1]["scale"] = 9.9e-4                                            # alter the forecast...
    prev, out = "GENESIS", []
    for r in rows:                                                       # ...and re-chain everything after it
        body = {k: v for k, v in r.items() if k not in ("entry_hash", "prev_hash")}
        body["prev_hash"] = prev
        body["entry_hash"] = L.recompute_entry_hash(body)
        prev = body["entry_hash"]
        out.append(json.dumps(body, sort_keys=True))
    h.ledger.write_text("\n".join(out) + "\n")
    L.verify_chain(h.ledger)                                             # verifies: the hashes detect INCONSISTENCY only
    assert "NOT tamper-proof" in L.__doc__


def test_intent_history_is_reverified_at_execution(tmp_path):
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    ir = h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=SID)
    lines = h.ledger.read_text().splitlines()
    rec = json.loads(lines[fr["seq"] - 1]); rec["symbol"] = "QQQ"; rec["entry_hash"] = L.recompute_entry_hash(rec)
    lines[fr["seq"] - 1] = json.dumps(rec, sort_keys=True); h.ledger.write_text("\n".join(lines) + "\n")
    with pytest.raises(B.BoundaryRefused, match="CHAIN_LINK_BROKEN"):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    assert not h.quotes.calls                                            # no quote was requested


def test_forecast_hash_mismatch_wrong_kind_and_other_session_refuse(tmp_path):
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    with pytest.raises(B.BoundaryRefused, match="FORECAST_HASH_MISMATCH"):
        h.bd.record_intent(forecast_receipt={**fr, "forecast_hash": "f" * 64}, intent=_proposal(), signal_used="LONG", scan_id=SID)
    ir = h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=SID)
    with pytest.raises(B.BoundaryRefused, match="RECORD_KIND_MISMATCH"):
        h.bd.record_intent(forecast_receipt={**ir, "forecast_hash": fr["forecast_hash"]}, intent=_proposal(), signal_used="LONG", scan_id=SID)
    other = SyntheticHarness(h.ledger, session_id="SYN-SESSION-2")
    with pytest.raises(B.BoundaryRefused, match="FORECAST_FROM_OTHER_SESSION"):
        other.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id="SYN-SESSION-2:0001:SPY")
    with pytest.raises(B.BoundaryRefused, match="INTENT_FROM_OTHER_SESSION"):
        other.bd.execute_intent(intent_receipt=ir, quote_fn=other.quotes)
    wrong_release = SyntheticHarness(h.ledger, session_id=h.session_id, release="other-release")
    with pytest.raises(B.BoundaryRefused, match="INTENT_FROM_OTHER_RELEASE"):
        wrong_release.bd.execute_intent(intent_receipt=ir, quote_fn=wrong_release.quotes)


def test_intent_content_refusals(tmp_path):
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    k = dict(forecast_receipt=fr, signal_used="LONG", scan_id=SID)
    with pytest.raises(B.BoundaryRefused, match="INTENT_SYMBOL_MISMATCH"):
        h.bd.record_intent(intent=_proposal(contract={"symbol": "QQQ", "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"}), **k)
    with pytest.raises(B.BoundaryRefused, match="INTENT_QUANTITY_NOT_ONE"):
        h.bd.record_intent(intent=_proposal(quantity=2), **k)
    with pytest.raises(B.BoundaryRefused, match="INTENT_QUANTITY_NOT_ONE"):
        h.bd.record_intent(intent=_proposal(quantity=True), **k)
    with pytest.raises(B.BoundaryRefused, match="INTENT_EXPRESSION_NOT_IN_PILOT_RULE"):
        h.bd.record_intent(intent=_proposal(expression="CALL_VERTICAL"), **k)
    with pytest.raises(B.BoundaryRefused, match="INTENT_SIGNAL_CONTRACT_DISAGREE"):
        h.bd.record_intent(intent=_proposal(), forecast_receipt=fr, signal_used="SHORT", scan_id=SID)
    with pytest.raises(B.BoundaryRefused, match="INTENT_SESSION_MISMATCH"):
        h.bd.record_intent(intent=_proposal(), forecast_receipt=fr, signal_used="LONG", scan_id="SYN-SESSION-1:0002:SPY")


# ================================================================== risk: self-attestation is not authorization

def test_risk_self_attestation_is_refused_and_production_authority_refuses(tmp_path):
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    # (1) a caller-supplied risk dict on the proposal is ignored; approval comes from the authority only
    prod = SyntheticHarness(tmp_path / "prod.jsonl")
    prod.bd.risk = RG.ProductionRiskAuthority()
    pfr = prod.bd.record_forecast(prod.forecast_fn(SYM, prod.now()), scan_id=SID)
    with pytest.raises(B.BoundaryRefused, match="RISK_INTEGRATION_MISSING"):
        prod.bd.record_intent(forecast_receipt=pfr, intent=_proposal(risk={"approved": True}), signal_used="LONG", scan_id=SID)
    assert not any(r["kind"] == "pilot_intent" for r in _rows(prod))
    assert "next brick" in _rows(prod)[-1]["reason"]
    # (2) the synthetic authority can refuse, and its refusal is a persisted intent-stage refusal
    h.risk.refuse_with = "SYNTHETIC_LIMIT"
    with pytest.raises(B.BoundaryRefused, match="RISK_NOT_APPROVED: 'SYNTHETIC_LIMIT'"):
        h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=SID)
    h.risk.refuse_with = None
    # (3) an approval copied from another intent does not bind
    ir = h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=SID)
    it = _rec(h, ir)
    foreign = {**it, "contract_id": "SPY|2026-10-09|650.0|CALL"}
    with pytest.raises(RG.RiskRefused, match="NOT_BOUND_TO_THIS_INTENT"):
        RG.verify_approval(foreign, it["risk"])
    with pytest.raises(RG.RiskRefused, match="RISK_PROVENANCE_UNKNOWN"):
        RG.verify_approval(it, {**it["risk"], "risk_provenance": "I_SAID_SO"})
    with pytest.raises(RG.RiskRefused, match="RISK_MAX_LOSS_INVALID"):
        RG.verify_approval(it, {**it["risk"], "certified_max_loss": float("nan")})
    # (4) the synthetic authority cannot be constructed outside the explicit harness
    with pytest.raises(RG.RiskRefused, match="OUTSIDE_HARNESS"):
        RG.SyntheticRiskAuthority(harness_token="production")
    # (5) an intent whose on-disk approval was edited refuses at execution
    lines = h.ledger.read_text().splitlines()
    rec = json.loads(lines[ir["seq"] - 1]); rec["risk"]["binding_hash"] = "0" * 64
    rec["entry_hash"] = L.recompute_entry_hash(rec); lines[ir["seq"] - 1] = json.dumps(rec, sort_keys=True)
    h.ledger.write_text("\n".join(lines) + "\n")
    with pytest.raises(B.BoundaryRefused, match="INTENT_RISK_ON_DISK_RISK_APPROVAL_NOT_BOUND"):
        h.bd.execute_intent(intent_receipt={**ir, "entry_hash": rec["entry_hash"]}, quote_fn=h.quotes)


# ================================================================== fill: wrong contract, staleness, size, expiry

def test_wrong_contract_at_execution_is_unfilled_and_recorded(tmp_path):
    h = _h(tmp_path)
    base = lambda c: {**c, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12, "timestamp_epoch": h.now() - 1.0}
    h.quotes.override = lambda c: base({**c, "strike": 655.0})           # the V2 intent is K=650; 655 is the wrong contract
    d = _scan(h)
    fill = _rec(h, d["receipts"]["fill"])
    assert d["decision"] == "REFUSE" and fill["status"] == "UNFILLED" and fill["why"].startswith("CONTRACT_MISMATCH")
    h.quotes.override = lambda c: base({**c, "expiration": "2026-11-20"})
    d2 = _scan(h)
    assert d2["why"].startswith("CONTRACT_MISMATCH")


def test_freshness_is_measured_after_receipt_for_the_selected_side(tmp_path):
    h = _h(tmp_path)
    h.quotes.age = 16.0
    d = _scan(h)
    assert d["decision"] == "WAIT" and d["why"].startswith("STALE_SELECTED_CONTRACT: ASK side 16.000s")
    h.quotes.age = 14.7                                   # 14.95 s at the simulated execution instant (0.25 s latency)
    d2 = _scan(h)
    assert d2["decision"] == "TRADE"
    h.quotes.age = 14.9                                   # fresh at receipt, 15.15 s at simulated execution -> WAIT
    assert _scan(h)["decision"] == "WAIT"
    h.quotes.age = -2.0
    d3 = _scan(h)
    assert d3["decision"] == "REFUSE" and d3["why"].startswith("QUOTE_FROM_THE_FUTURE")


def test_no_size_is_wait_and_resolves_to_no_position(tmp_path):
    h = _h(tmp_path)
    h.quotes.ask_size = 0
    d = _scan(h)
    fill = _rec(h, d["receipts"]["fill"])
    assert d["decision"] == "WAIT" and fill["why"] == "NO_SIZE_AT_ASK" and fill["net_debit"] == 0.0
    o = _exit(h, d["receipts"]["fill"], h.exit_quotes)
    assert o["status"] == "NO_POSITION"


def test_intent_expiry_is_enforced_before_and_during_the_quote(tmp_path):
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    ir = h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=SID)
    assert _rec(h, ir)["expiry_epoch"] == _rec(h, ir)["created_epoch"] + R.INTENT_TTL_S
    h.advance(R.INTENT_TTL_S + 1)
    with pytest.raises(B.BoundaryRefused, match="INTENT_EXPIRED: clock"):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    assert not h.quotes.calls and _kinds(h)[-2:] == ["pilot_intent_expired", "pilot_refusal"]
    with pytest.raises(B.BoundaryRefused, match="INTENT_TERMINAL: pilot_intent_expired"):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    # expiry crossed while the provider was slow: terminal record + refusal, never a fill
    h2 = _h(tmp_path / "s", t0=T_MINUTE)
    fr2 = h2.bd.record_forecast(h2.forecast_fn(SYM, h2.now()), scan_id=SID)
    ir2 = h2.bd.record_intent(forecast_receipt=fr2, intent=_proposal(), signal_used="LONG", scan_id=SID)
    h2.advance(R.INTENT_TTL_S - 1)
    h2.quotes.slow_s = 5.0
    with pytest.raises(B.BoundaryRefused, match="INTENT_EXPIRED_DURING_QUOTE"):
        h2.bd.execute_intent(intent_receipt=ir2, quote_fn=h2.quotes)
    assert _kinds(h2)[-2:] == ["pilot_intent_expired", "pilot_refusal"] and _kinds(h2).count("pilot_fill") == 0


def test_stale_and_missing_exit_quotes_are_not_estimable_never_imputed(tmp_path):
    h = _h(tmp_path)
    d = _scan(h)
    h.advance(60.0)
    h.exit_quotes.age = 61.0
    o = _exit(h, d["receipts"]["fill"], h.exit_quotes)
    rec = _rec(h, o)
    assert rec["status"] == "NOT_ESTIMABLE" and rec["why"].startswith("STALE_SELECTED_CONTRACT: BID side 61.000s")
    d2 = _scan(h)
    o2 = _exit(h, d2["receipts"]["fill"], lambda c: None)
    rec2 = _rec(h, o2)
    assert rec2["status"] == "NOT_ESTIMABLE" and rec2["pnl"] is None and "never imputed" in rec2["exit_law"]
    assert rec2["discharges_position"] is False and rec2["attempt"] == 1
    h.exit_quotes.age = 1.0
    later = _exit(h, d2["receipts"]["fill"], h.exit_quotes)   # a later attempt discharges
    assert later["status"] == "RESOLVED" and later["attempt"] == 2 and later["reconciled"] is False
    again = _exit(h, d2["receipts"]["fill"], h.exit_quotes)   # after discharge: reconciled
    assert again["reconciled"] is True and again["seq"] == later["seq"]
    assert len(B.Boundary.valuation_attempts(_rows(h), d2["receipts"]["fill"]["seq"])) == 2
    d3 = _scan(h)
    h.exit_quotes.age = 1.0; h.exit_quotes.fail_with = OSError("feed gone")
    o3 = _exit(h, d3["receipts"]["fill"], h.exit_quotes)
    assert _rec(h, o3)["why"].startswith("EXIT_QUOTE_PROVIDER_FAILED: OSError")


# ================================================================== persistence failure and refusal persistence

def test_failed_persistence_prevents_entry_and_is_reported_honestly(tmp_path, monkeypatch):
    h = _h(tmp_path)
    _scan(h)
    n_before = len(_rows(h))
    real = L.chain_append
    calls = {"n": 0}
    def dying(path, entry):
        calls["n"] += 1
        raise OSError("disk full")
    monkeypatch.setattr(L, "chain_append", dying)
    d = _scan(h)
    monkeypatch.setattr(L, "chain_append", real)
    assert d["decision"] == "REFUSE" and "PERSISTENCE_FAILED" in d["why"]
    assert d["refusal_persisted"] is False and "REFUSAL_NOT_PERSISTED" in d["why"]
    assert d["decision_persisted"] is False and "PERSISTENCE_FAILED" in d["decision_persist_error"]
    assert len(_rows(h)) == n_before and calls["n"] >= 1
    ro = tmp_path / "ro"; ro.mkdir(); os.chmod(ro, 0o500)
    try:
        h2 = SyntheticHarness(ro / "p.jsonl")
        d2 = _scan(h2)
        assert d2["decision"] == "REFUSE" and d2["refusal_persisted"] is False
        assert not (ro / "p.jsonl").exists()
    finally:
        os.chmod(ro, 0o700)


def test_persistence_is_proven_by_reread_not_by_return_value(tmp_path, monkeypatch):
    h = _h(tmp_path)
    real = L.chain_append
    def lying(path, entry):
        body = real(path, entry)
        Path(path).write_text("")
        return body
    monkeypatch.setattr(L, "chain_append", lying)
    with pytest.raises(B.BoundaryRefused, match="PERSISTENCE_UNPROVEN"):
        h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)


# ================================================================== atomic, session-scoped idempotency

def test_duplicate_delivery_and_duplicate_scan_are_refused(tmp_path):
    h = _h(tmp_path)
    d = _scan(h)
    n_quotes = len(h.quotes.calls)
    again = h.bd.execute_intent(intent_receipt=d["receipts"]["intent"], quote_fn=h.quotes)
    assert again["reconciled"] is True and again["seq"] == d["receipts"]["fill"]["seq"] and again["status"] == "FILLED"
    assert _kinds(h).count("pilot_fill") == 1 and len(h.quotes.calls) == n_quotes     # no second quote, no second fill
    d2 = _scan(h, seq=1)                                   # duplicate scan: the PERSISTED decision comes back
    assert d2["decision"] == "TRADE" and d2["duplicate_delivery"] is True and d2["reconciled"] is True
    assert d2["fill_id"] == d["fill_id"] and d2["decision_receipt"]["seq"] == d["decision_receipt"]["seq"]
    assert _kinds(h).count("pilot_forecast") == 1 and _kinds(h).count("pilot_decision") == 1
    assert _kinds(h)[-1] == "pilot_duplicate_delivery"


def test_a_forecast_cannot_back_two_intents(tmp_path):
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    ir = h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=SID)
    same = h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=SID)   # identical: reconciled
    assert same["seq"] == ir["seq"] and "RECONCILED" in same["receipt"]
    other = _proposal(contract={"symbol": SYM, "expiration": "2026-10-09", "strike": 650.0, "right": "CALL"})
    with pytest.raises(B.BoundaryRefused, match="FORECAST_ALREADY_CONSUMED"):
        h.bd.record_intent(forecast_receipt=fr, intent=other, signal_used="LONG", scan_id=SID)
    assert _kinds(h).count("pilot_intent") == 1


def test_concurrent_workers_cannot_fill_the_same_intent_twice(tmp_path):
    """Deterministic: N workers block on a barrier INSIDE the quote provider, so all have passed
    the pre-quote duplicate check before any can commit. Exactly one fill lands."""
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    ir = h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=SID)
    n = 6
    barrier = threading.Barrier(n)
    results, errors = [], []
    def quote_fn(c):
        barrier.wait(timeout=10)
        return {**c, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12, "timestamp_epoch": h.now() - 1.0}
    def worker():
        try:
            results.append(h.bd.execute_intent(intent_receipt=ir, quote_fn=quote_fn))
        except B.BoundaryRefused as e:
            errors.append(str(e))
    ts = [threading.Thread(target=worker) for _ in range(n)]
    [t.start() for t in ts]; [t.join(timeout=30) for t in ts]
    assert len(results) == n and errors == []
    assert len({r["seq"] for r in results}) == 1 and sum(1 for r in results if r.get("reconciled")) == n - 1
    assert _kinds(h).count("pilot_fill") == 1 and _kinds(h).count("pilot_refusal") == 0
    L.verify_chain(h.ledger)


def test_concurrent_intents_cannot_consume_one_forecast_twice(tmp_path):
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    n = 5
    barrier = threading.Barrier(n)
    ok, bad = [], []
    class GatedRisk(RG.SyntheticRiskAuthority):
        def approve(self, intent, *, book=None):
            barrier.wait(timeout=10)
            return super().approve(intent, book=book)
    h.bd.risk = GatedRisk(harness_token="I_AM_A_SYNTHETIC_HARNESS")
    def worker(i):
        prop = _proposal(contract={"symbol": SYM, "expiration": "2026-10-09", "strike": 640.0 + 5.0 * i, "right": "CALL"})
        try:
            ok.append(h.bd.record_intent(forecast_receipt=fr, intent=prop, signal_used="LONG", scan_id=SID))
        except B.BoundaryRefused as e:
            bad.append(str(e))
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in ts]; [t.join(timeout=30) for t in ts]
    assert len(ok) == 1 and len(bad) == n - 1 and all("FORECAST_ALREADY_CONSUMED" in e for e in bad)
    L.verify_chain(h.ledger)


def test_crash_before_durable_commit_leaves_no_fill_and_resume_fills_once(tmp_path):
    h = _h(tmp_path)
    h.quotes.fail_with = KeyboardInterrupt()          # process dies inside the provider, before any commit
    with pytest.raises(KeyboardInterrupt):
        _scan(h)
    assert _kinds(h) == ["pilot_forecast", "pilot_intent"]
    assert len(S.unfilled_intents(h.ledger)) == 1
    h.quotes.fail_with = None
    h.advance(5.0)
    acts = S.resume(h.bd, quote_fn=h.quotes)
    assert len(acts) == 1 and acts[0]["action"] == "EXECUTED" and acts[0]["status"] == "FILLED" and not acts[0]["reconciled"]
    assert S.unfilled_intents(h.ledger) == []
    assert S.resume(h.bd, quote_fn=h.quotes) == []
    assert _kinds(h).count("pilot_fill") == 1


def test_crash_after_durable_commit_reconciles_the_lost_ack(tmp_path, monkeypatch):
    """The fill was appended and fsync'd but the process died before it stored the receipt."""
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    ir = h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=SID)
    real = L.append_with_receipt
    def crash_after_write(path, entry):
        r = real(path, entry)
        if entry.get("kind") == "pilot_fill":
            raise KeyboardInterrupt("died after fsync, before ack")
        return r
    monkeypatch.setattr(L, "append_with_receipt", crash_after_write)
    with pytest.raises(KeyboardInterrupt):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    monkeypatch.setattr(L, "append_with_receipt", real)
    assert _kinds(h).count("pilot_fill") == 1
    r = h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)     # redelivery with the same txn_id
    assert r["reconciled"] is True and r["status"] == "FILLED" and "RECONCILED" in r["receipt"]
    assert _kinds(h).count("pilot_fill") == 1 and len(h.quotes.calls) == 1   # no second quote, no second fill
    acts = S.resume(h.bd, quote_fn=h.quotes)
    assert acts == []


def test_resume_policy_retires_stale_intents_instead_of_executing_forever(tmp_path):
    led = tmp_path / "p.jsonl"
    # A: this session, unexpired -> executed once
    a = SyntheticHarness(led, session_id="S-A", release="r1")
    fa = a.bd.record_forecast(a.forecast_fn(SYM, a.now()), scan_id="S-A:0001:SPY")
    a.bd.record_intent(forecast_receipt=fa, intent=_proposal(), signal_used="LONG", scan_id="S-A:0001:SPY")
    # B: a closed session's unfinished intent
    b = SyntheticHarness(led, session_id="S-B", release="r1")
    fb = b.bd.record_forecast(b.forecast_fn(SYM, b.now()), scan_id="S-B:0001:SPY")
    b.bd.record_intent(forecast_receipt=fb, intent=_proposal(), signal_used="LONG", scan_id="S-B:0001:SPY")
    S.close_session(b.bd)
    # C: another release
    c = SyntheticHarness(led, session_id="S-A", release="r0")
    fc = c.bd.record_forecast(c.forecast_fn(SYM, c.now()), scan_id="S-A:0002:SPY")
    c.bd.record_intent(forecast_receipt=fc, intent=_proposal(), signal_used="LONG", scan_id="S-A:0002:SPY")
    # D: another (open) session
    d = SyntheticHarness(led, session_id="S-D", release="r1")
    fd = d.bd.record_forecast(d.forecast_fn(SYM, d.now()), scan_id="S-D:0001:SPY")
    d.bd.record_intent(forecast_receipt=fd, intent=_proposal(), signal_used="LONG", scan_id="S-D:0001:SPY")
    # E: this session, created on the same timeline 200 s earlier, so its TTL (120 s) has lapsed
    e = SyntheticHarness(led, session_id="S-A", release="r1", t0=T0 - 200.0)
    fe = e.bd.record_forecast(e.forecast_fn(SYM, e.now()), scan_id="S-A:0003:SPY")
    e.bd.record_intent(forecast_receipt=fe, intent=_proposal(), signal_used="LONG", scan_id="S-A:0003:SPY")
    # B's close CANCELLED its own unfilled intent (SESSION_CLOSE); four remain unfinished
    assert len(S.unfilled_intents(led)) == 4
    b_cancel = [r for r in L.read_all(led) if r["kind"] == "pilot_intent_cancelled" and r["session_id"] == "S-B"]
    assert len(b_cancel) == 1 and b_cancel[0]["why"].startswith("SESSION_CLOSE")
    a.t = T0 + 10.0                                  # restart A ten seconds after its intent was persisted
    acts = S.resume(a.bd, quote_fn=a.quotes)
    by = {x["intent_id"]: x for x in acts}
    kinds = {r["scan_id"]: r for r in L.read_all(led) if r["kind"] == "pilot_intent"}
    assert by[kinds["S-A:0001:SPY"]["intent_id"]]["action"] == "EXECUTED"
    assert by[kinds["S-A:0002:SPY"]["intent_id"]]["action"] == "CANCELLED" and "WRONG_RELEASE" in by[kinds["S-A:0002:SPY"]["intent_id"]]["why"]
    assert by[kinds["S-D:0001:SPY"]["intent_id"]]["action"] == "CANCELLED" and "STALE_AUTHORIZATION" in by[kinds["S-D:0001:SPY"]["intent_id"]]["why"]
    assert by[kinds["S-A:0003:SPY"]["intent_id"]]["action"] == "EXPIRED"
    assert S.unfilled_intents(led) == []
    assert S.resume(a.bd, quote_fn=a.quotes) == []                       # terminal: nothing re-executes
    assert len(a.quotes.calls) == 1
    L.verify_chain(led)


def test_quote_is_requested_only_after_the_intent_is_on_disk(tmp_path):
    h = _h(tmp_path)
    seen = {}
    def quote_fn(c):
        rows = L.read_all(h.ledger)
        seen["intent_present"] = any(r.get("kind") == "pilot_intent" for r in rows)
        seen["records_before_quote"] = len(rows)
        return {**c, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12, "timestamp_epoch": h.now() - 1.0}
    d = _scan(h, quote_fn=quote_fn)
    assert seen["intent_present"] is True and seen["records_before_quote"] == d["receipts"]["intent"]["seq"]


def test_fsync_durability_is_retained(tmp_path, monkeypatch):
    import apex.governance.chain_ledger as CL
    calls = []
    real = os.fsync
    monkeypatch.setattr(CL.os, "fsync", lambda fd: (calls.append(fd), real(fd)))
    h = _h(tmp_path)
    _scan(h)
    assert len(calls) == len(_rows(h))


# ================================================================== rule refusals through the session

def test_rule_refusals_are_recorded_after_the_forecast(tmp_path):
    h = _h(tmp_path)
    h.signal = None
    d = _scan(h)
    assert d["decision"] == "REFUSE" and "NO_DIRECTION_SIGNAL" in d["why"]
    assert _kinds(h) == ["pilot_forecast", "pilot_refusal", "pilot_decision"]
    h.signal = "LONG"; h.chain = [{"expiration": "2026-09-18", "strike": 645.0, "right": "CALL"}]
    d2 = _scan(h)
    assert "NO_ELIGIBLE_EXPIRY" in d2["why"] and DTE_MIN_DAYS == 21


def test_next_seq_survives_restart(tmp_path):
    h = _h(tmp_path)
    assert S.next_seq(h.ledger, session_id=h.session_id) == 1
    _scan(h); _scan(h)
    assert S.next_seq(h.ledger, session_id=h.session_id) == 3
    h2 = SyntheticHarness(h.ledger)                    # same session id, new process
    assert S.next_seq(h2.ledger, session_id=h2.session_id) == 3
    assert S.next_seq(h2.ledger, session_id="OTHER") == 1


# ================================================================== r3: the six reproduced findings

def _pending_intent(h, scan_id=SID):
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=scan_id)
    ir = h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=scan_id)
    return fr, ir


def test_f1_production_authority_and_provenance_are_checked_on_execution_and_resume(tmp_path):
    """A synthetic pending intent must never fill through a production boundary."""
    h = _h(tmp_path)
    _fr, ir = _pending_intent(h)
    prod = B.Boundary(h.ledger, clock=h.clock, provenance="LIVE_FEED", risk_authority=RG.ProductionRiskAuthority(),
                      session_id=h.session_id, release=h.release)
    calls = []
    def quote_fn(c):
        calls.append(c); return h.quotes(c)
    with pytest.raises(B.BoundaryRefused, match="PROVENANCE_INCOMPATIBLE: intent 'SYNTHETIC_FIXTURE' vs boundary 'LIVE_FEED'"):
        prod.execute_intent(intent_receipt=ir, quote_fn=quote_fn)
    acts = S.resume(prod, quote_fn=quote_fn)
    assert len(acts) == 1 and acts[0]["action"] == "CANCELLED" and "STALE_AUTHORIZATION" in acts[0]["why"]
    assert "PROVENANCE_INCOMPATIBLE" in acts[0]["why"] and calls == []
    # provenance matches but the ACTIVE authority is production: the stored synthetic approval is not authorization
    h2 = _h(tmp_path / "b")
    _fr2, ir2 = _pending_intent(h2)
    prod2 = B.Boundary(h2.ledger, clock=h2.clock, provenance="SYNTHETIC_FIXTURE", risk_authority=RG.ProductionRiskAuthority(),
                       session_id=h2.session_id, release=h2.release)
    with pytest.raises(B.BoundaryRefused, match="RISK_AUTHORITY_INCOMPATIBLE: the production authority honours no stored approval"):
        prod2.execute_intent(intent_receipt=ir2, quote_fn=quote_fn)
    acts2 = S.resume(prod2, quote_fn=quote_fn)
    assert acts2[0]["action"] == "CANCELLED" and "RISK_AUTHORITY_INCOMPATIBLE" in acts2[0]["why"] and calls == []
    for led in (h.ledger, h2.ledger):
        rows = L.read_all(led)
        assert not any(r["kind"] == "pilot_fill" for r in rows)
        assert not any(r.get("data_provenance") == "LIVE_FEED" and r["kind"] == "pilot_fill" for r in rows)
    # a synthetic boundary likewise refuses a LIVE_FEED-labelled intent
    h3 = _h(tmp_path / "c")
    _fr3, ir3 = _pending_intent(h3)
    lines = h3.ledger.read_text().splitlines()
    recs = [json.loads(x) for x in lines]; recs[ir3["seq"] - 1]["data_provenance"] = "LIVE_FEED"
    prev, out = "GENESIS", []
    for r in recs:
        body = {k: v for k, v in r.items() if k not in ("entry_hash", "prev_hash")}
        body["prev_hash"] = prev; body["entry_hash"] = L.recompute_entry_hash(body); prev = body["entry_hash"]; out.append(json.dumps(body, sort_keys=True))
    h3.ledger.write_text("\n".join(out) + "\n")
    ir3 = {**ir3, "entry_hash": recs[ir3["seq"] - 1]["entry_hash"]}
    with pytest.raises(B.BoundaryRefused, match="PROVENANCE_INCOMPATIBLE"):
        h3.bd.execute_intent(intent_receipt={**ir3, "entry_hash": json.loads(out[ir3["seq"] - 1])["entry_hash"]}, quote_fn=quote_fn)


def test_f2_cancellation_inside_the_quote_window_wins_and_no_fill_follows(tmp_path):
    h = _h(tmp_path)
    _fr, ir = _pending_intent(h)
    it = _rec(h, ir)
    def cancelling_quote(c):
        h.bd.expire_intent(ir, it, why="OPERATOR_CANCEL during quote", kind="pilot_intent_cancelled")
        return h.quotes(c)
    with pytest.raises(B.BoundaryRefused, match="INTENT_TERMINAL_AT_COMMIT: pilot_intent_cancelled"):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=cancelling_quote)
    kinds = _kinds(h)
    assert kinds == ["pilot_forecast", "pilot_intent", "pilot_intent_cancelled", "pilot_refusal"]
    assert not any(k == "pilot_fill" for k in kinds)
    # and the reverse exclusion: a filled intent cannot be cancelled or expired afterwards
    h2 = _h(tmp_path / "b")
    _fr2, ir2 = _pending_intent(h2)
    r = h2.bd.execute_intent(intent_receipt=ir2, quote_fn=h2.quotes)
    assert r["status"] == "FILLED"
    with pytest.raises(B.BoundaryRefused, match="FILL_EXISTS"):
        h2.bd.expire_intent(ir2, _rec(h2, ir2), why="late cancel", kind="pilot_intent_cancelled")
    assert _kinds(h2).count("pilot_intent_cancelled") == 0
    # session closure during the quote window is caught at commit too
    h3 = _h(tmp_path / "c")
    _fr3, ir3 = _pending_intent(h3)
    def closing_quote(c):
        S.close_session(h3.bd); return h3.quotes(c)
    # the close cancels the open intent (terminal record) so the commit sees the cancellation; either exclusion holds
    with pytest.raises(B.BoundaryRefused, match="INTENT_TERMINAL_AT_COMMIT: pilot_intent_cancelled|SESSION_CLOSED_AT_COMMIT"):
        h3.bd.execute_intent(intent_receipt=ir3, quote_fn=closing_quote)
    assert _kinds(h3).count("pilot_fill") == 0
    assert [r for r in _rows(h3) if r["kind"] == "pilot_intent_cancelled"][0]["why"].startswith("SESSION_CLOSE")
    # intent expiry crossed between receipt and commit: see test_r4_expiry_between_receipt_and_commit_persists_terminal


def test_f2_concurrent_cancel_and_execute_are_mutually_exclusive(tmp_path):
    """Deterministic release: both workers pass a barrier; whichever commits first wins, the other refuses.
    Repeated with both orderings forced by a second barrier stage."""
    for first in ("cancel", "execute"):
        h = _h(tmp_path / first)
        _fr, ir = _pending_intent(h)
        it = _rec(h, ir)
        gate = threading.Barrier(2)
        order = threading.Event()
        results = {}
        def quote_fn(c):
            gate.wait(timeout=10)
            if first == "cancel":
                order.wait(timeout=10)                       # let the cancel commit first
            return h.quotes(c)
        def executor():
            try:
                results["execute"] = h.bd.execute_intent(intent_receipt=ir, quote_fn=quote_fn)["status"]
            except B.BoundaryRefused as e:
                results["execute"] = "REFUSED: " + str(e)
        def canceller():
            gate.wait(timeout=10)
            if first == "execute":
                # wait until a fill is on disk, then try to cancel
                for _ in range(200):
                    if any(r["kind"] == "pilot_fill" for r in _rows(h)):
                        break
                    threading.Event().wait(0.01)
            try:
                h.bd.expire_intent(ir, it, why="race cancel", kind="pilot_intent_cancelled")
                results["cancel"] = "CANCELLED"
            except B.BoundaryRefused as e:
                results["cancel"] = "REFUSED: " + str(e)
            order.set()
        ts = [threading.Thread(target=executor), threading.Thread(target=canceller)]
        [t.start() for t in ts]; [t.join(timeout=30) for t in ts]
        kinds = _kinds(h)
        n_fill, n_cancel = kinds.count("pilot_fill"), kinds.count("pilot_intent_cancelled")
        assert (n_fill, n_cancel) in ((1, 0), (0, 1)), (first, kinds, results)
        if first == "cancel":
            assert results["cancel"] == "CANCELLED" and "INTENT_TERMINAL_AT_COMMIT" in results["execute"]
        else:
            assert results["execute"] == "FILLED" and "FILL_EXISTS" in results["cancel"]
        L.verify_chain(h.ledger)


def test_f3_reconciliation_verifies_the_existing_fill_and_its_chain(tmp_path):
    h = _h(tmp_path)
    _fr, ir = _pending_intent(h)
    r = h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    assert r["status"] == "FILLED"
    lines = h.ledger.read_text().splitlines()
    rec = json.loads(lines[r["seq"] - 1]); rec["net_debit"] = 1.0                     # altered, hash untouched
    lines[r["seq"] - 1] = json.dumps(rec, sort_keys=True); h.ledger.write_text("\n".join(lines) + "\n")
    n_quotes = len(h.quotes.calls)
    with pytest.raises(B.BoundaryRefused, match="RECONCILE_ALTERED: existing fill seq %d" % r["seq"]):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    assert len(h.quotes.calls) == n_quotes
    with pytest.raises(L.LedgerRefused, match="RECONCILE_ALTERED"):
        L.commit_once(h.ledger, txn_id=rec["txn_id"], build=lambda rows: {}, kind="pilot_fill")
    acts = S.resume(h.bd, quote_fn=h.quotes)                                              # resume cannot launder it either
    assert acts == [] or all(a["action"] != "EXECUTED" for a in acts)
    # a consistently re-hashed alteration breaks the link from the next record and is caught the same way
    h2 = _h(tmp_path / "b")
    _fr2, ir2 = _pending_intent(h2)
    r2 = h2.bd.execute_intent(intent_receipt=ir2, quote_fn=h2.quotes)
    _exit(h2, r2, h2.exit_quotes)                     # a successor exists
    lines = h2.ledger.read_text().splitlines()
    rec = json.loads(lines[r2["seq"] - 1]); rec["net_debit"] = 1.0; rec["entry_hash"] = L.recompute_entry_hash(rec)
    lines[r2["seq"] - 1] = json.dumps(rec, sort_keys=True); h2.ledger.write_text("\n".join(lines) + "\n")
    with pytest.raises(B.BoundaryRefused, match="RECONCILE_ALTERED"):
        h2.bd.execute_intent(intent_receipt=ir2, quote_fn=h2.quotes)


def test_f4_duplicate_scan_returns_the_persisted_decision_not_a_new_story(tmp_path):
    h = _h(tmp_path)
    d1 = _scan(h)
    assert d1["decision"] == "TRADE"
    d2 = _scan(h, seq=1)
    for k in ("decision", "why", "forecast_id", "intent_id", "fill_id"):
        assert d2[k] == d1[k], k
    assert d2["duplicate_delivery"] is True and d2["reconciled"] is True
    dec_seq = d1["decision_receipt"]["seq"]
    assert d2["decision_receipt"]["seq"] == dec_seq and _rec(h, d2["decision_receipt"])["decision"] == "TRADE"
    rows = _rows(h)
    assert [r["kind"] for r in rows].count("pilot_decision") == 1
    diag = [r for r in rows if r["kind"] == "pilot_duplicate_delivery"]
    assert len(diag) == 1 and diag[0]["decision_ref"]["seq"] == dec_seq and diag[0]["scan_id"] == d1["scan_id"]
    # an interrupted scan (records but no decision) is refused as INCOMPLETE_SCAN, and that refusal IS its first decision
    h2 = _h(tmp_path / "b")
    h2.quotes.fail_with = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        _scan(h2)
    h2.quotes.fail_with = None
    d = _scan(h2, seq=1)
    assert d["decision"] == "REFUSE" and "INCOMPLETE_SCAN" in d["why"] and d["refusal_persisted"] is True
    assert _kinds(h2).count("pilot_decision") == 1 and _kinds(h2).count("pilot_fill") == 0
    d_again = _scan(h2, seq=1)
    assert d_again["decision"] == "REFUSE" and d_again["duplicate_delivery"] is True and "INCOMPLETE_SCAN" in d_again["why"]


def test_f5_a_forecast_about_a_completed_target_is_not_prospective_evidence(tmp_path):
    h = _h(tmp_path)
    stale_by_an_hour = h.base_forecast(SYM, h.now() - 3600.0)                     # target ended 23:40, clock 00:26:40
    assert stale_by_an_hour["target_end_utc"].startswith("2026-09-09T23:40:00")
    h.forecast_override = stale_by_an_hour
    d = _scan(h)
    assert d["decision"] == "REFUSE" and "FORECAST_TARGET_ALREADY_ENDED" in d["why"]
    assert _kinds(h).count("pilot_intent") == 0
    # stale inputs (cutoff 160 s before the clock) refuse even though the target is still in the future
    h.forecast_override = h.base_forecast(SYM, h.now() - 130.0)
    d2 = _scan(h)
    assert d2["decision"] == "REFUSE" and "FORECAST_STALE" in d2["why"]
    # re-checked at intent creation: a forecast persisted in time cannot back an intent after its target ended
    h.forecast_override = None
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id="SYN-SESSION-1:0009:SPY")
    h.advance(900.0)
    with pytest.raises(B.BoundaryRefused, match="FORECAST_TARGET_ENDED_BEFORE_INTENT"):
        h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id="SYN-SESSION-1:0009:SPY")
    f = _rec(h, fr)
    assert f["eligibility_policy"].startswith("FORECAST_ELIGIBILITY_V1")


def test_f6_unresolved_positions_are_recovered_reported_and_block_clean_completion(tmp_path):
    h = _h(tmp_path)
    _fr, ir = _pending_intent(h)
    h.quotes.fail_with = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    h.quotes.fail_with = None
    acts = S.resume(h.bd, quote_fn=h.quotes)
    assert acts[0]["action"] == "EXECUTED" and acts[0]["status"] == "FILLED"
    rec = S.recover_positions(h.bd)
    assert len(rec["own"]) == 1 and rec["own"][0]["seq"] == acts[0]["receipt"]["seq"] and rec["foreign"] == []
    close = S.close_session(h.bd)
    c = _rec(h, close)
    assert c["unfinished_intent_seqs_at_close"] == [] and c["unresolved_fill_seqs_at_close"] == [rec["own"][0]["seq"]]
    assert c["outstanding_obligations"] == 1 and c["completion"] == "CLOSED_WITH_OUTSTANDING_OBLIGATIONS"
    # another session sees it as foreign: reported, not resolved
    other = SyntheticHarness(h.ledger, session_id="SYN-SESSION-2")
    rec2 = S.recover_positions(other.bd)
    assert rec2["own"] == [] and len(rec2["foreign"]) == 1 and rec2["foreign"][0]["session_id"] == h.session_id
    # the owning session discharges it; a second close is a NEW record that says so
    o = _exit(h, rec["own"][0], h.exit_quotes)
    assert o["status"] == "RESOLVED"
    close2 = S.close_session(h.bd)
    c2 = _rec(h, close2)
    assert close2["seq"] > close["seq"] and c2["close_number"] == 2 and c2["completion"] == "CLOSED_CLEAN"
    assert S.recover_positions(h.bd) == {"own": [], "foreign": []}


# ================================================================== r4: the four remaining cases against 0c23f702

def _advance_before_commit(monkeypatch, h, seconds: float, *, kind="pilot_fill"):
    """Model 'the clock moves between quote receipt and the commit transaction' deterministically:
    advance the controlled clock immediately before the fill's commit_once."""
    real = L.commit_once
    def late(path, *, txn_id, build, kind=None):
        if kind == "pilot_fill":
            h.advance(seconds)
        return real(path, txn_id=txn_id, build=build, kind=kind)
    monkeypatch.setattr(B.L, "commit_once", late)


def test_r4_expiry_between_receipt_and_commit_persists_terminal(tmp_path, monkeypatch):
    h = _h(tmp_path, t0=T_MINUTE)
    _fr, ir = _pending_intent(h)
    h.advance(R.INTENT_TTL_S - 1)                       # still alive at request and at receipt
    _advance_before_commit(monkeypatch, h, 5.0)         # dead by the time the commit transaction runs
    with pytest.raises(B.BoundaryRefused, match="INELIGIBLE_AT_COMMIT: INTENT_EXPIRED"):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    kinds = _kinds(h)
    assert kinds[-2:] == ["pilot_intent_expired", "pilot_refusal"] and kinds.count("pilot_fill") == 0
    assert len(h.quotes.calls) == 1
    exp = [r for r in _rows(h) if r["kind"] == "pilot_intent_expired"][0]
    assert exp["intent_id"] == ir["intent_id"] and "INTENT_EXPIRED" in exp["why"]
    assert S.unfilled_intents(h.ledger) == []            # the intent is finished, not left dangling
    monkeypatch.undo()
    assert S.resume(h.bd, quote_fn=h.quotes) == []
    with pytest.raises(B.BoundaryRefused, match="INTENT_TERMINAL: pilot_intent_expired"):
        h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    L.verify_chain(h.ledger)


def test_r4_missing_or_stale_exit_keeps_the_position_outstanding(tmp_path):
    h = _h(tmp_path)
    d = _scan(h)
    assert d["decision"] == "TRADE", d
    fill = d["receipts"]["fill"]
    # the ORDINARY missing-exit path: provider returns None
    o1 = _exit(h, fill, lambda c: None)
    assert o1["status"] == "NOT_ESTIMABLE" and o1["discharges_position"] is False and o1["attempt"] == 1
    assert [seq for seq, _ in S.unresolved_fills(h.ledger)] == [fill["seq"]]
    rec = S.recover_positions(h.bd)
    assert len(rec["own"]) == 1 and rec["own"][0]["valuation_attempts"] == 1 and rec["own"][0]["last_attempt_why"] == "EXIT_QUOTE_MISSING"
    c1 = _rec(h, S.close_session(h.bd))
    assert c1["completion"] == "CLOSED_WITH_OUTSTANDING_OBLIGATIONS" and c1["unresolved_fill_seqs_at_close"] == [fill["seq"]]
    # a STALE exit is likewise an attempt, not a discharge
    h.advance(60.0); h.exit_quotes.age = 61.0
    o2 = _exit(h, fill, h.exit_quotes)
    assert o2["status"] == "NOT_ESTIMABLE" and o2["attempt"] == 2 and len(S.unresolved_fills(h.ledger)) == 1
    # restart recovers it from disk
    h2 = SyntheticHarness(h.ledger, t0=h.now() + 5.0)
    rec2 = S.recover_positions(h2.bd)
    assert [r["seq"] for r in rec2["own"]] == [fill["seq"]] and rec2["own"][0]["valuation_attempts"] == 2
    # a valid exit discharges it; the close then says clean
    o3 = _exit(h2, rec2["own"][0], h2.exit_quotes)
    assert o3["status"] == "RESOLVED" and o3["discharges_position"] is True and o3["attempt"] == 3
    assert S.unresolved_fills(h.ledger) == []
    c2 = _rec(h, S.close_session(h2.bd))
    assert c2["completion"] == "CLOSED_CLEAN" and c2["close_number"] == 2
    # provider failure is an attempt too (a NEW session: the closed one correctly refuses new scans)
    h3 = SyntheticHarness(h.ledger, session_id="SYN-SESSION-3", t0=h2.now() + 5.0)
    d2 = _scan(h3)
    assert d2["decision"] == "TRADE", d2
    h3.exit_quotes.fail_with = OSError("feed gone")
    o4 = _exit(h3, d2["receipts"]["fill"], h3.exit_quotes)
    assert o4["status"] == "NOT_ESTIMABLE" and o4["discharges_position"] is False and len(S.unresolved_fills(h.ledger)) == 1
    assert S.recover_positions(h3.bd)["own"][0]["last_attempt_why"].startswith("EXIT_QUOTE_PROVIDER_FAILED: OSError")
    L.verify_chain(h.ledger)


def test_r4_late_duplicate_delivery_reconciles_after_the_forecast_target_ended(tmp_path):
    h = _h(tmp_path)
    _fr, ir = _pending_intent(h)
    first = h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    assert first["status"] == "FILLED"
    n = len(_rows(h))
    h.advance(1000.0)                                   # forecast target ended, intent TTL long past
    again = h.bd.execute_intent(intent_receipt=ir, quote_fn=h.quotes)
    assert again["reconciled"] is True and again["seq"] == first["seq"] and again["status"] == "FILLED"
    assert len(h.quotes.calls) == 1 and len(_rows(h)) == n          # no quote, no refusal, no new record
    # ...but a NEW fill for a different, still-pending intent is refused and cancelled on the same clock
    _fr2, ir2 = _pending_intent(h, scan_id="SYN-SESSION-1:0002:SPY")
    h.advance(1000.0)
    with pytest.raises(B.BoundaryRefused, match="INTENT_EXPIRED"):
        h.bd.execute_intent(intent_receipt=ir2, quote_fn=h.quotes)
    assert _kinds(h)[-2:] == ["pilot_intent_expired", "pilot_refusal"]


def test_r4_forecast_freshness_is_rechecked_at_intent_and_at_commit(tmp_path, monkeypatch):
    # (a) at intent creation: forecast persisted fresh, cutoff 130 s old by the time the intent is proposed
    h = _h(tmp_path)
    fr = h.bd.record_forecast(h.forecast_fn(SYM, h.now()), scan_id=SID)
    cutoff = _rec(h, fr)["epoch"]["input_cutoff"]
    h.advance(130.0 - (h.now() - cutoff))
    assert h.now() - cutoff == pytest.approx(130.0)
    with pytest.raises(B.BoundaryRefused, match="FORECAST_STALE_BEFORE_INTENT: input cutoff 130.0s"):
        h.bd.record_intent(forecast_receipt=fr, intent=_proposal(), signal_used="LONG", scan_id=SID)
    # (b) before the quote: intent unexpired (TTL 120) but the forecast cutoff is 130 s old -> cancelled, no quote
    h2 = _h(tmp_path / "b")
    _fr2, ir2 = _pending_intent(h2)
    cutoff2 = _rec(h2, _fr2)["epoch"]["input_cutoff"]
    h2.advance(130.0 - (h2.now() - cutoff2))
    assert h2.now() <= _rec(h2, ir2)["expiry_epoch"]
    with pytest.raises(B.BoundaryRefused, match="FORECAST_STALE_BEFORE_EXECUTION"):
        h2.bd.execute_intent(intent_receipt=ir2, quote_fn=h2.quotes)
    assert h2.quotes.calls == [] and _kinds(h2)[-2:] == ["pilot_intent_cancelled", "pilot_refusal"]
    assert S.unfilled_intents(h2.ledger) == []
    # (c) between receipt and commit: fresh at the quote, 130 s old at the commit transaction -> cancelled, no fill
    h3 = _h(tmp_path / "c")
    _fr3, ir3 = _pending_intent(h3)
    cutoff3 = _rec(h3, _fr3)["epoch"]["input_cutoff"]
    h3.advance(110.0 - (h3.now() - cutoff3))
    _advance_before_commit(monkeypatch, h3, 20.0)
    with pytest.raises(B.BoundaryRefused, match="INELIGIBLE_AT_COMMIT: FORECAST_STALE_BEFORE_EXECUTION"):
        h3.bd.execute_intent(intent_receipt=ir3, quote_fn=h3.quotes)
    assert len(h3.quotes.calls) == 1 and _kinds(h3)[-2:] == ["pilot_intent_cancelled", "pilot_refusal"]
    assert _kinds(h3).count("pilot_fill") == 0 and S.unfilled_intents(h3.ledger) == []
    monkeypatch.undo()
    assert S.resume(h3.bd, quote_fn=h3.quotes) == []
    L.verify_chain(h3.ledger)
