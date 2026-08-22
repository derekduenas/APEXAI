"""LIVING-ORGANISM DIAGNOSTIC (2026-08-21) -- the severed-loop repairs.

The diagnostic found four organs built-and-tested but never connected:
outcomes.resolve() (zero callers -- the learning loop was severed),
probability.estimate() (imported, never called), information_lead
(zero callers), and the crypto facet (declared DARK while a live
healthy sensor ran). Plus: no forecast layer, no canonical-chain ->
Expression adapter, and a UTC date bug in the frontier2 runtime.

These tests pin every repair, including AST proofs that the runtimes
actually CALL the organs -- the defect class this repo keeps producing
is "proven in vitro, never connected to blood supply", and only a
caller-existence test prevents its recurrence.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.pattern_observatory import outcomes as ocmod  # noqa: E402
from apex.pattern_observatory import resolution as resmod  # noqa: E402

T0 = pd.Timestamp("2026-08-20 14:00:00", tz="UTC")


def _bars(n=120, start=None, base=100.0, step=0.0):
    start = start or T0
    rows = []
    p = base
    for i in range(n):
        p = base + step * i
        rows.append({"event_time_utc": start + pd.Timedelta(minutes=i),
                     "open": p, "high": p + 0.05, "low": p - 0.05,
                     "close": p, "volume": 1000})
    return pd.DataFrame(rows)


def _episode(pid="ep1", fs=None, subject="SPY", family="P006"):
    return {"pattern_id": pid, "first_seen": str(fs or T0),
            "subject": subject, "family_id": family,
            "birth_classification": "PROSPECTIVE_OBSERVATION",
            "regime": "UNKNOWN",
            "input_quality": {"combined_quality": "VALID"}}


# ------------------------------------------------- the resolution loop

def test_resolution_resolves_elapsed_horizons_and_only_those():
    bars = _bars(n=40)
    c = resmod.run_cycle(
        bars_by_subject={"SPY": bars},
        now=T0 + pd.Timedelta(minutes=40),
        pattern_rows=[_episode()], outcome_rows=[], persist=False)
    # 5/15/30 elapsed in bars; 60/90 have not -> PENDING, not persisted
    assert c["no_event"] + c["resolved"] == 3
    assert c["pending"] == 2


def test_resolution_is_idempotent_via_the_outcome_ledger():
    bars = _bars(n=40)
    done = [{"pattern_id": "ep1", "episode_first_seen": str(T0),
             "horizon_minutes": h} for h in (5, 15, 30)]
    c = resmod.run_cycle(
        bars_by_subject={"SPY": bars},
        now=T0 + pd.Timedelta(minutes=40),
        pattern_rows=[_episode()], outcome_rows=done, persist=False)
    assert c["checked"] == 2          # only the two pending horizons


def test_resolution_never_extrapolates_wall_clock_past_the_bars():
    """The no-lookahead guard through the loop. Same session (now a few
    hours later): uncovered horizons stay PENDING -- bars might still
    arrive. After a full overnight (NEVER_COVERABLE_AFTER_H), they
    become terminally UNRESOLVABLE -- never a fabricated return. This
    second rule was found by this very test before first deploy:
    without it, close-crossing horizons were re-checked every cycle
    forever."""
    bars = _bars(n=10)                # bars end at T0+9m
    same_day = resmod.run_cycle(
        bars_by_subject={"SPY": bars},
        now=T0 + pd.Timedelta(hours=6),
        pattern_rows=[_episode()], outcome_rows=[], persist=False)
    assert same_day["resolved"] + same_day["no_event"] >= 1
    assert same_day["pending"] >= 1               # honest: might still fill

    next_day = resmod.run_cycle(
        bars_by_subject={"SPY": bars},
        now=T0 + pd.Timedelta(hours=30),
        pattern_rows=[_episode()], outcome_rows=[], persist=False)
    assert next_day["pending"] == 0
    assert next_day["unresolvable"] >= 1          # terminal, persisted once


def test_outcome_corpus_is_known_from_filtered():
    rows = [
        {"family_id": "P006", "horizon_minutes": 30, "status": "NO_EVENT",
         "ret": 0.001, "mfe": 0.002, "mae": -0.001, "direction": "UP",
         "known_from": str(T0)},
        {"family_id": "P006", "horizon_minutes": 30, "status": "RESOLVED",
         "ret": 0.005, "mfe": 0.006, "mae": -0.002, "direction": "UP",
         "known_from": str(T0 + pd.Timedelta(hours=8))},   # future
    ]
    c = resmod.outcome_corpus(rows, family_id="P006", horizon_minutes=30,
                              as_of=T0 + pd.Timedelta(hours=1))
    assert c["n"] == 1
    assert c["returns"] == [0.001]


def test_newly_terminal_fires_once_per_episode_on_the_lead_horizon():
    bars = _bars(n=40)
    c = resmod.run_cycle(
        bars_by_subject={"SPY": bars},
        now=T0 + pd.Timedelta(minutes=40),
        pattern_rows=[_episode()], outcome_rows=[], persist=False)
    assert len(c["newly_terminal"]) == 1
    assert c["newly_terminal"][0]["pattern_id"] == "ep1"


def test_observatory_runtime_calls_the_learning_organs():
    """AST proof: run_cycle (resolution), estimate (probability) and
    measure (information lead) all have live call sites in the runtime.
    The defect class this pins: organ built, never connected."""
    src = Path("scripts/pattern_observatory_shadow_runtime.py").read_text()
    tree = ast.parse(src)
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)}
    for organ in ("run_cycle", "estimate", "measure"):
        assert organ in called, f"{organ}() lost its live caller"


# ----------------------------------------------------- forecast layer

def test_forecast_refuses_without_earned_support():
    from apex.forecast import FORECAST_NOT_ESTIMABLE
    from apex.forecast import forward_distribution as fdmod
    fd = fdmod.build(family_id="P006", subject="SPY", horizon_minutes=30,
                     corpus={"returns": [0.001] * 8},
                     support={"prospective_n": 8, "distinct_sessions": 1,
                              "distinct_symbols": 1, "distinct_regimes": 1},
                     as_of=T0, known_from=T0)
    assert fd.status == FORECAST_NOT_ESTIMABLE
    assert fd.q50 is None and fd.p_up is None
    assert fd.blockers                     # every refusal is named
    assert fd.as_record()["is_authorization_input"] is False


def test_forecast_with_earned_gates_is_estimable_but_uncalibrated():
    from apex.forecast import FORECAST_ESTIMABLE_UNCALIBRATED
    from apex.forecast import forward_distribution as fdmod
    rets = [0.001 * ((-1) ** i) + 0.0001 * i for i in range(40)]
    fd = fdmod.build(
        family_id="P006", subject="SPY", horizon_minutes=30,
        corpus={"returns": rets, "mfe": [0.01] * 40, "mae": [-0.008] * 40},
        support={"prospective_n": 40, "distinct_sessions": 12,
                 "distinct_symbols": 6, "distinct_regimes": 3},
        as_of=T0, known_from=T0)
    assert fd.status == FORECAST_ESTIMABLE_UNCALIBRATED
    assert fd.q05 is not None and fd.q95 is not None
    assert fd.q05 <= fd.q50 <= fd.q95
    assert abs(fd.p_up + fd.p_down - 1.0) < 1e-6
    # UNCALIBRATED means research output, never authorization input
    assert fd.as_record()["is_authorization_input"] is False


def test_only_a_calibrated_forecast_is_an_authorization_input():
    from apex.forecast import FORECAST_CALIBRATED
    from apex.forecast import forward_distribution as fdmod
    rets = [0.001] * 40
    fd = fdmod.build(
        family_id="P006", subject="SPY", horizon_minutes=30,
        corpus={"returns": rets, "mfe": [], "mae": []},
        support={"prospective_n": 40, "distinct_sessions": 12,
                 "distinct_symbols": 6, "distinct_regimes": 3},
        calibration={"status": "COMPUTED", "beats_base_rate": True},
        as_of=T0, known_from=T0)
    assert fd.status == FORECAST_CALIBRATED
    assert fd.as_record()["is_authorization_input"] is True


def test_funnel_slot_stays_empty_below_calibrated():
    """The authority guard in the runtime: any status other than
    FORECAST_CALIBRATED leaves Capital's ForecastSlot at its
    NOT_YET_AVAILABLE default -- proven at the source level."""
    src = Path("scripts/frontier2_shadow_runtime.py").read_text()
    assert "if fd.status == FORECAST_CALIBRATED" in src
    assert "slot = ForecastSlot()" in src


# ------------------------------------------------- chain -> expression

def _contract(strike, opt_type="call", iv=0.2, delta=0.55, bid=2.0,
              ask=2.1, expiry="2026-08-24", quality="HIGH",
              age=1.0, as_of=None):
    return {"symbol": f"SPY260824{'C' if opt_type == 'call' else 'P'}"
                      f"{int(strike * 1000):08d}",
            "strike": strike, "option_type": opt_type,
            "expiry_date": expiry, "spot": 100.0,
            "market_bid": bid, "market_ask": ask,
            "market_mid": (bid + ask) / 2,
            "iv": {"iv_mid": iv},
            "delta": {"greek_name": "delta", "bsm_value": delta},
            "gamma": {"greek_name": "gamma", "bsm_value": 0.01},
            "theta": {"greek_name": "theta", "bsm_value": -5.0},
            "vega": {"greek_name": "vega", "bsm_value": 10.0},
            "state_quality": quality,
            "live_quality": {"quote_age_s": age, "bid_size": 10,
                             "ask_size": 10},
            "as_of": str(as_of or T0)}


def test_adapter_builds_a_real_candidate_with_real_economics():
    from apex.options_research import chain_adapter as ca
    chain = [_contract(100, delta=0.55), _contract(105, delta=0.30),
             _contract(95, delta=0.80)]
    cand = ca.build_candidate("SPY", "UP", thesis_id="T1",
                              now=T0, known_from=T0, chain=chain)
    assert cand is not None
    assert cand.expression_type == "LONG_CALL"
    assert cand.strikes == (100.0,)            # nearest to target delta
    assert cand.max_loss == pytest.approx(2.05 * 100 + 0.65)
    assert cand.break_even == (pytest.approx(102.05),)
    assert cand.research_mechanism_ids == ("OPT-001-DIRECTIONAL-CONVEXITY",)


def test_adapter_refuses_negative_clock_and_stale_quotes(tmp_path):
    from apex.options_research import chain_adapter as ca
    rows = [_contract(100, age=-0.5), _contract(101, age=500.0),
            _contract(102, age=1.0)]
    p = tmp_path / "states.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    chain = ca.load_chain("SPY", now=T0 + pd.Timedelta(minutes=1), path=p)
    assert [c["strike"] for c in chain] == [102]


def test_adapter_refuses_zero_dte_and_thin_depth():
    from apex.options_research import chain_adapter as ca
    same_day = _contract(100, expiry=str(T0.date()))
    thin = _contract(100)
    thin["live_quality"]["bid_size"] = 1
    thin["live_quality"]["ask_size"] = 1
    assert ca.select_directional([same_day], "UP", now=T0) is None
    assert ca.select_directional([thin], "UP", now=T0) is None


def test_adapter_direction_down_builds_a_put():
    from apex.options_research import chain_adapter as ca
    chain = [_contract(100, opt_type="put", delta=-0.55)]
    cand = ca.build_candidate("SPY", "DOWN", thesis_id="T1",
                              now=T0, known_from=T0, chain=chain)
    assert cand is not None
    assert cand.expression_type == "LONG_PUT"
    assert cand.break_even == (pytest.approx(100 - 2.05),)


def test_adapter_candidate_survives_the_engine_gates(tmp_path,
                                                     monkeypatch):
    """End-to-end: a real adapter candidate + real surface passes into
    expression_engine.run() and either survives to `candidates` or is
    refused with a NAMED gate -- never silently dropped."""
    from apex.options_research import chain_adapter as ca
    from apex.options_research import expression_engine as ex
    chain = [_contract(100, delta=0.55), _contract(101, delta=0.45),
             _contract(99, delta=0.65)]
    cand = ca.build_candidate("SPY", "UP", thesis_id="T1",
                              now=T0, known_from=T0, chain=chain)
    pick = ca.select_directional(chain, "UP", now=T0)
    surf = ca.build_surface_for("SPY", pick, chain, now=T0, known_from=T0)
    dec = ex.run(subject="SPY", now=T0, known_from=T0,
                 hunter_present=False, frontier_present=True,
                 stock_entry_price=100.0, option_candidates=(cand,),
                 surface_state=surf, candidate_dte=4,
                 expected_realization_minutes=30.0,
                 timing_uncertainty_minutes=30.0)
    types_out = {c["expression_type"] for c in dec.candidates}
    refused_types = {r.get("candidate_expression_type")
                     for r in dec.refusals}
    assert ("LONG_CALL" in types_out) or ("LONG_CALL" in refused_types), (
        "the option candidate vanished without a verdict")
    assert "NO_TRADE" in types_out


def test_frontier2_runtime_uses_the_et_session_date():
    src = Path("scripts/frontier2_shadow_runtime.py").read_text()
    assert 'today = str(now.date())' not in src
    assert 'tz_convert("America/New_York").date()' in src


# --------------------------------------------------------- crypto facet

def test_crypto_sensor_dark_when_artifact_absent(tmp_path, monkeypatch):
    from apex.pattern_observatory import crypto_sensor as cs
    monkeypatch.setattr(cs, "HEALTH_PATH", tmp_path / "absent.json")
    r = cs.observe(now=T0)
    assert r["status"] == "DARK"
    assert "absent" in r["reason"]


def test_crypto_sensor_dark_when_heartbeat_stale(tmp_path, monkeypatch):
    from apex.pattern_observatory import crypto_sensor as cs
    p = tmp_path / "h.json"
    p.write_text(json.dumps(
        {"last_heartbeat": str(T0 - pd.Timedelta(hours=2)),
         "book_health": "OK", "fabric_health": {"connected": True}}))
    monkeypatch.setattr(cs, "HEALTH_PATH", p)
    r = cs.observe(now=T0)
    assert r["status"] == "DARK"
    assert "stale" in r["reason"]


def test_crypto_sensor_live_reports_observability_not_signal(tmp_path,
                                                             monkeypatch):
    from apex.pattern_observatory import crypto_sensor as cs
    p = tmp_path / "h.json"
    p.write_text(json.dumps(
        {"last_heartbeat": str(T0 - pd.Timedelta(seconds=10)),
         "book_health": "OK",
         "fabric_health": {"connected": True, "reconnects": 3}}))
    monkeypatch.setattr(cs, "HEALTH_PATH", p)
    monkeypatch.setattr(cs, "ARENA_LEDGER", tmp_path / "no_ledger.jsonl")
    monkeypatch.setattr(cs, "DERIVATIVES_HEALTH", tmp_path / "nd2.json")
    r = cs.observe(now=T0)
    assert r["status"] == "LIVE"
    st = r["state"]
    assert st["market_features"]["status"] == "NOT_DERIVED"
    assert st["decision_power"] == "NONE_PATTERN_OBSERVATORY"


def test_crypto_sensor_is_read_only_by_ast():
    """The adapter may never write anywhere -- proven over its AST: no
    open(..., mode with w/a), no Path.write_text, no mem.append."""
    tree = ast.parse(
        Path("apex/pattern_observatory/crypto_sensor.py").read_text())
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            fn = n.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else "")
            assert name not in ("write_text", "append", "unlink"), (
                f"crypto_sensor calls {name}() -- adapter must be "
                f"read-only")
            if name == "open":
                modes = [a for a in n.args[1:2]]
                for kw in n.keywords:
                    if kw.arg == "mode":
                        modes.append(kw.value)
                for m in modes:
                    if isinstance(m, ast.Constant):
                        assert "w" not in m.value and "a" not in m.value


# --------------------------- FORWARD_LEARNING_CAUSALITY (operator law)

def test_forward_learning_causality_the_operator_scenario():
    """THE LAW: a forecast at known_from=T may only consume outcomes
    whose resolution was KNOWABLE by T --
    outcome.known_from <= forecast.known_from, never mere existence in
    the ledger. The operator's exact scenario: episode at 10:00,
    outcome resolves 11:00; a forecast reconstructed at 10:30 MUST NOT
    see it; a forecast at 11:01 MAY. If this is ever wrong, APEX will
    produce beautifully calibrated historical predictions using
    information it learned later."""
    t_ep = pd.Timestamp("2026-08-20 10:00:00", tz="America/New_York")
    t_res = pd.Timestamp("2026-08-20 11:00:00", tz="America/New_York")
    rows = [{"family_id": "P006", "horizon_minutes": 30,
             "status": "RESOLVED", "ret": 0.004, "mfe": 0.005,
             "mae": -0.001, "direction": "UP",
             "episode_first_seen": str(t_ep),
             "known_from": str(t_res)}]           # knowable at 11:00

    at_1030 = resmod.outcome_corpus(
        rows, family_id="P006", horizon_minutes=30,
        as_of=t_ep + pd.Timedelta(minutes=30))
    assert at_1030["n"] == 0, (
        "FORWARD_LEARNING_CAUSALITY VIOLATED: a 10:30 forecast saw an "
        "outcome that resolved at 11:00")

    at_1101 = resmod.outcome_corpus(
        rows, family_id="P006", horizon_minutes=30,
        as_of=t_res + pd.Timedelta(minutes=1))
    assert at_1101["n"] == 1


def test_forward_learning_causality_end_to_end_through_the_forecast():
    """Same law proven through fdmod.build: identical support, identical
    ledger -- the only difference is the forecast's own known_from, and
    the corpus it may draw from changes accordingly."""
    from apex.forecast import forward_distribution as fdmod
    t_ep = pd.Timestamp("2026-08-20 10:00:00", tz="America/New_York")
    t_res = pd.Timestamp("2026-08-20 11:00:00", tz="America/New_York")
    rows = [{"family_id": "P006", "horizon_minutes": 30,
             "status": "RESOLVED", "ret": 0.004, "mfe": 0.005,
             "mae": -0.001, "direction": "UP",
             "episode_first_seen": str(t_ep),
             "known_from": str(t_res)}]
    support = {"prospective_n": 40, "distinct_sessions": 12,
               "distinct_symbols": 6, "distinct_regimes": 3}

    early = fdmod.build(
        family_id="P006", subject="SPY", horizon_minutes=30,
        corpus=resmod.outcome_corpus(rows, family_id="P006",
                                     horizon_minutes=30,
                                     as_of=t_ep + pd.Timedelta(minutes=30)),
        support=support, as_of=t_ep + pd.Timedelta(minutes=30),
        known_from=t_ep + pd.Timedelta(minutes=30))
    late = fdmod.build(
        family_id="P006", subject="SPY", horizon_minutes=30,
        corpus=resmod.outcome_corpus(rows, family_id="P006",
                                     horizon_minutes=30,
                                     as_of=t_res + pd.Timedelta(minutes=1)),
        support=support, as_of=t_res + pd.Timedelta(minutes=1),
        known_from=t_res + pd.Timedelta(minutes=1))
    assert early.corpus_n == 0        # the 10:30 forecast learned nothing
    assert late.corpus_n == 1         # the 11:01 forecast may


def test_resolution_known_from_is_resolution_time_never_event_time():
    """The field the law depends on: a persisted outcome's known_from is
    when the RESOLUTION was computed, never the episode's own time --
    verified against the real Thursday ledger."""
    from apex.pattern_observatory import memory as mem
    rows = mem.read(mem.OUTCOME_LEDGER)
    if not rows:
        pytest.skip("no outcome ledger in this environment")
    for r in rows:
        kf = pd.Timestamp(r["known_from"])
        t1 = (pd.Timestamp(r["episode_first_seen"])
              + pd.Timedelta(minutes=r["horizon_minutes"]))
        if kf.tz is None:
            kf = kf.tz_localize("UTC")
        if t1.tz is None:
            t1 = t1.tz_localize("UTC")
        assert kf >= t1, (
            f"outcome known_from {kf} precedes its own horizon end {t1} "
            f"-- a resolution cannot be knowable before it happened")


def test_crypto_terminology_context_live_perps_not_available(tmp_path,
                                                             monkeypatch):
    """Operator law: crypto CONTEXT is live; BTC-perps DERIVATIVES
    intelligence is not. The state must carry both statements
    explicitly so spot data can never masquerade as derivatives
    evidence in a later reading."""
    from apex.pattern_observatory import crypto_sensor as cs
    p = tmp_path / "h.json"
    p.write_text(json.dumps(
        {"last_heartbeat": str(T0 - pd.Timedelta(seconds=5)),
         "book_health": "OK", "fabric_health": {"connected": True}}))
    monkeypatch.setattr(cs, "HEALTH_PATH", p)
    monkeypatch.setattr(cs, "ARENA_LEDGER", tmp_path / "none.jsonl")
    monkeypatch.setattr(cs, "DERIVATIVES_HEALTH",
                        tmp_path / "no_deriv.json")   # poller absent
    st = cs.observe(now=T0)["state"]
    assert st["crypto_context"] == "LIVE"
    assert st["btc_perps_derivatives"] == "NOT_AVAILABLE"
    mf = st["market_features"]
    for k in ("funding", "open_interest", "liquidations", "perp_basis",
              "cross_exchange_positioning"):
        assert mf[k] == "NOT_AVAILABLE"
    # with a FRESH poller health, status may rise to PARTIAL -- never
    # LIVE while trades/book/liquidations are missing
    import pandas as pd_
    (tmp_path / "deriv.json").write_text(json.dumps(
        {"as_of": str(pd_.Timestamp.now(tz="UTC")), "polls": 5}))
    monkeypatch.setattr(cs, "DERIVATIVES_HEALTH", tmp_path / "deriv.json")
    st2 = cs.observe(now=T0)["state"]
    assert st2["btc_perps_derivatives"] == "PARTIAL"
    assert "NOT_AVAILABLE" in st2["market_features"]["liquidations"]


def test_corpus_carries_independence_accounting():
    """n_raw never implies independence: the corpus persists clustering
    and a conservative n_effective lower bound (distinct sessions)."""
    t1 = pd.Timestamp("2026-08-20 10:00:00", tz="UTC")
    t2 = pd.Timestamp("2026-08-20 14:00:00", tz="UTC")   # same session
    t3 = pd.Timestamp("2026-08-19 14:00:00", tz="UTC")   # prior session
    rows = [
        {"family_id": "P006", "horizon_minutes": 30, "status": "NO_EVENT",
         "ret": 0.001, "pattern_id": "a", "subject": "SPY",
         "episode_first_seen": str(t1), "known_from": str(t1)},
        {"family_id": "P006", "horizon_minutes": 30, "status": "NO_EVENT",
         "ret": 0.002, "pattern_id": "b", "subject": "SPY",
         "episode_first_seen": str(t2), "known_from": str(t2)},
        {"family_id": "P006", "horizon_minutes": 30, "status": "RESOLVED",
         "ret": 0.004, "pattern_id": "c", "subject": "SPY",
         "episode_first_seen": str(t3), "known_from": str(t3)},
    ]
    c = resmod.outcome_corpus(rows, family_id="P006", horizon_minutes=30,
                              as_of=t2 + pd.Timedelta(hours=1))
    assert c["n_raw"] == 3
    assert c["clustering"]["distinct_sessions"] == 2
    assert c["clustering"]["distinct_episodes"] == 3
    assert c["n_effective_lower_bound"] == 2   # 3 raw, 2 sessions


# --------------------- bad-print high/low fix (found by the audit above)

def _trades(specs, t0=None):
    t0 = (t0 or T0).timestamp()
    return [{"event_s": t0 + i, "price": p, "size": 100,
             "conditions": c} for i, (p, c) in enumerate(specs)]


def test_ineligible_condition_cannot_poison_the_low():
    """THE 14:02 REPRODUCTION: one derivative-priced print 4% below the
    tape must not become the bar's low. It still counts toward volume."""
    from apex.intraday.bar_builder import build_1m_bars
    tr = _trades([(766.6, ["@"]), (766.7, ["@"]), (736.5, ["4"]),
                  (766.1, ["@"])])
    bars = build_1m_bars(tr, [], now=T0 + pd.Timedelta(minutes=2),
                         symbol="SPY", transport="TEST")
    b = bars.iloc[0]
    assert b["low"] == 766.1, f"bad print became the low: {b['low']}"
    assert b["high"] == 766.7
    assert b["volume"] == 400            # ineligible still counts volume


def test_odd_lot_excluded_from_high_low():
    from apex.intraday.bar_builder import build_1m_bars
    tr = _trades([(100.0, ["@"]), (101.5, ["I"]), (100.2, [])])
    bars = build_1m_bars(tr, [], now=T0 + pd.Timedelta(minutes=2),
                         symbol="SPY", transport="TEST")
    assert bars.iloc[0]["high"] == 100.2


def test_all_ineligible_minute_falls_back_not_empty():
    from apex.intraday.bar_builder import build_1m_bars
    tr = _trades([(100.0, ["4"]), (100.5, ["4"])])
    bars = build_1m_bars(tr, [], now=T0 + pd.Timedelta(minutes=2),
                         symbol="SPY", transport="TEST")
    assert len(bars) == 1
    assert bars.iloc[0]["high"] == 100.5   # honest fallback, not NaN


def test_missing_conditions_key_is_regular_way():
    from apex.intraday.bar_builder import build_1m_bars
    t0 = T0.timestamp()
    tr = [{"event_s": t0 + i, "price": 100.0 + i, "size": 10}
          for i in range(3)]
    bars = build_1m_bars(tr, [], now=T0 + pd.Timedelta(minutes=2),
                         symbol="SPY", transport="TEST")
    assert bars.iloc[0]["high"] == 102.0


def test_quality_flags_excise_named_fields_only_append_only():
    """A flag row marks mae/mfe contaminated; the outcome's RETURNS
    still count. The original row is never rewritten."""
    t1 = pd.Timestamp("2026-08-20 10:00:00", tz="UTC")
    rows = [
        {"family_id": "P006", "horizon_minutes": 30, "status": "NO_EVENT",
         "ret": 0.001, "mfe": 0.002, "mae": -0.040,   # poisoned mae
         "pattern_id": "a", "subject": "SPY",
         "episode_first_seen": str(t1), "known_from": str(t1)},
        {"kind": "pattern_outcome_quality_flag", "pattern_id": "a",
         "episode_first_seen": str(t1), "horizon_minutes": 30,
         "contaminated_fields": ["mae", "mfe"],
         "known_from": str(t1)},
    ]
    c = resmod.outcome_corpus(rows, family_id="P006", horizon_minutes=30,
                              as_of=t1 + pd.Timedelta(hours=1))
    assert c["returns"] == [0.001]          # clean field retained
    assert c["mae"] == [] and c["mfe"] == []  # poisoned fields excised
