"""The Monday loop, end to end, without a market.

Rehearsal against a closed market can reach WAIT_FOR_ENTRY but never
ATTACK_READY, so the attack-and-resolve path would otherwise go into
its first live session untested. These drive the real loop functions
against a constructed-but-realistic observation.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from apex.predators.options.live_world import LiveObservation
from apex.predators.options.replay import FrozenState
from apex.predators.options.scoreboard import SessionScoreboard
from scripts import options_paper_session as sess

SESSION = "2026-08-24"


def _observation(*, trend_up=True, spread=0.05, spot=100.0,
                 quality="GOOD"):
    """A live observation shaped exactly like the real adapter's."""
    t0 = pd.Timestamp(f"{SESSION}T09:30:00")
    n = 240
    # The commissioned equity faculty rates entry GOOD only when the
    # trend is real AND price is not extended from session VWAP. Those
    # pull against each other: a 30-bar trend strong enough to register
    # is usually far from VWAP, which trips chase risk. The shape that
    # satisfies both is a CONSOLIDATION (letting VWAP catch up)
    # followed by a modest advance -- which is what a pullback entry
    # actually looks like. Parameters below were measured against the
    # real faculty, not guessed: they yield UP / GOOD / MODERATE.
    bars = []
    flat_n, rise, rng = 200, 0.9, 0.30
    sign = 1.0 if trend_up else -1.0
    for i in range(n):
        if i < flat_n:
            c = spot + 0.05 * math.sin(i / 7.0)
        else:
            c = spot + sign * rise * ((i - flat_n) / (n - flat_n))
        bars.append({"t": str(t0 + pd.Timedelta(minutes=i)),
                     "o": c, "h": c + rng, "l": c - rng, "c": c,
                     "v": 100000 + (i % 7) * 900,
                     "session": "REGULAR"})
    last = bars[-1]["c"]
    T = str(t0 + pd.Timedelta(minutes=n))

    quotes = []
    for k in [round(last + d, 1) for d in
              (-6, -4, -2, -1, 0, 1, 2, 4, 6)]:
        for right in ("CALL", "PUT"):
            intrinsic = (max(last - k, 0) if right == "CALL"
                         else max(k - last, 0))
            mid = intrinsic + 2.2
            quotes.append({
                "symbol": "TEST", "expiration": "2026-09-18",
                "strike": f"{k:.3f}", "right": right,
                "timestamp": T,
                "bid": f"{mid - spread / 2:.2f}",
                "ask": f"{mid + spread / 2:.2f}",
                "bid_size": "40", "ask_size": "40",
                "moneyness_status": "CAUSAL"})

    frozen = FrozenState(
        symbol="TEST", session=SESSION, T=T,
        underlying_bars=tuple(bars), option_quotes=tuple(quotes),
        oi_rows=(), spot_ref=last, spot_ref_source_label=str(t0),
        spot_ref_age_s=60.0)
    return LiveObservation(frozen=frozen, stock_bid=last - 0.01,
                           stock_ask=last + 0.01, quote_age_s=30.0,
                           bar_age_s=45.0, feed_quality=quality)


@pytest.fixture
def patched(monkeypatch):
    def _install(obs):
        monkeypatch.setattr(sess, "observe", lambda sym, now=None: obs)
    return _install


def _run(obs, tmp_path):
    sb = SessionScoreboard(session=SESSION)
    ledger = Path(tmp_path) / "live.jsonl"
    opens = []
    rec = sess._scan_symbol("TEST", sb, ledger, opens)
    return sb, ledger, opens, rec


# ------------------------------------------------ the attack path

def test_a_clean_setup_reaches_paper_attack_and_seals_first(
        patched, tmp_path):
    obs = _observation()
    patched(obs)
    sb, ledger, opens, rec = _run(obs, tmp_path)
    # asserted, not skipped: this fixture is measured to reach
    # ATTACK_READY, so a decline here is a regression in the funnel,
    # not a legitimate refusal, and must fail loudly.
    assert rec["status"] == "PAPER_ATTACKED", (
        f"the measured attackable fixture was declined as "
        f"{rec['status']} -- the funnel regressed")
    assert len(opens) == 1
    assert rec["card_hash"] and len(rec["card_hash"]) == 64
    assert sb.report()["pipeline"]["PAPER_ATTACKED"] == 1
    # the BEFORE card must be in the chain, and before the attack row
    rows = [l for l in ledger.read_text().splitlines() if l.strip()]
    kinds = [__import__("json").loads(r)["kind"] for r in rows]
    assert kinds.index("options_live_card") < \
        kinds.index("options_live_attack")


def test_an_attack_resolves_with_friction_attribution(
        patched, tmp_path):
    obs = _observation()
    patched(obs)
    sb, ledger, opens, rec = _run(obs, tmp_path)
    assert rec["status"] == "PAPER_ATTACKED"
    out = sess.resolve_open(opens, sb, ledger)
    assert len(out) == 1
    r = sb.report()
    assert r["attacks_raw"] == 1
    assert r["attacks_effective_lower_bound"] == 1
    assert out[0]["class"] in (
        "THESIS_WRONG", "THESIS_RIGHT_OPTION_LOST",
        "THESIS_RIGHT_FRICTION_KILLED", "EXECUTION_FAILURE",
        "THESIS_RIGHT_FRICTION_SURVIVED")


# ------------------------------------------------ the refusal paths

def test_a_degraded_feed_is_refused_not_silently_skipped(
        patched, tmp_path):
    patched(_observation(quality="STALE_QUOTES"))
    sb, _l, opens, rec = _run(None, tmp_path)
    assert rec["status"] == "FEED_DEGRADED"
    assert not opens
    assert sb.report()["stops"]["DATA_QUALITY"] == 1


def test_a_feed_failure_is_recorded_as_a_refusal(monkeypatch, tmp_path):
    def _boom(sym, now=None):
        raise sess.FeedUnavailable("no bars")
    monkeypatch.setattr(sess, "observe", _boom)
    sb = SessionScoreboard(session=SESSION)
    rec = sess._scan_symbol("TEST", sb, Path(tmp_path) / "l.jsonl", [])
    assert rec["status"] == "FEED_UNAVAILABLE"
    assert sb.report()["stops"]["DATA_QUALITY"] == 1


def test_no_position_is_opened_without_a_sealed_card(patched, tmp_path):
    """simulate_entry must refuse an unsealed decision, always."""
    from apex.predators.options.expression import build_candidates
    from apex.predators.options.paper_execution import (
        ExecutionRefused, simulate_entry)
    obs = _observation()
    c = next(c for c in build_candidates(obs.frozen, "LONG", iv=0.25)
             if c.expression != "STOCK")
    with pytest.raises(ExecutionRefused):
        simulate_entry(c, T=obs.frozen.T, sealed_card_hash=None)


def test_the_stock_comparator_uses_the_real_equity_spread(patched):
    from apex.predators.options.expression import build_candidates
    obs = _observation()
    cands = build_candidates(obs.frozen, "LONG", iv=0.25,
                             stock_bid=obs.stock_bid,
                             stock_ask=obs.stock_ask)
    st = next(c for c in cands if c.expression == "STOCK")
    assert st.execution_pedigree == "OBSERVED_QUOTE"
    assert st.round_trip_friction == pytest.approx(2.0, abs=0.01)


def test_protocol_is_preregistered_with_no_trade_quota():
    p = sess.PROTOCOL
    assert p["authority"] == "PAPER_EXPLORATORY"
    assert p["decision_power"] == "NONE_PAPER"
    assert p["live_capital"] == "LOCKED"
    assert "no quota" in p["no_trade_rule"]
    assert p["risk_basis"] == "FULL_PREMIUM"
