"""PREMARKET-1 — the desk wakes before the market, and cannot cheat.

The laws: sealed BEFORE the bell or not at all; coverage stated, never
assumed; unknown catalysts labeled as unidentified-within-sources; the
morning brief is a PRIOR the tape outranks; the learner is preregistered
at zero observations.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from apex.frontier.premarket import (PremarketViolation, SOURCES, seal)


def _pkt(as_of):
    return {"kind": "premarket_context_packet", "market_date": "2026-08-17",
            "prior_session": "2026-08-14", "as_of_time": str(as_of),
            "created_at": str(as_of), "source_coverage": dict(SOURCES),
            "indices": {}, "gap_map": [], "watch_map": {},
            "blind_spots": [], "decision_power": "NONE_FRONTIER_SHADOW"}


def test_sealing_after_the_bell_is_refused(tmp_path, monkeypatch):
    """A 'premarket' packet written at 09:47 ET is hindsight in a
    morning coat."""
    import apex.frontier.premarket as pm
    monkeypatch.setattr(pm, "PACKETS", tmp_path)
    with pytest.raises(PremarketViolation):
        seal(_pkt(pd.Timestamp("2026-08-17T13:47:00Z")))   # 09:47 ET
    ok = seal(_pkt(pd.Timestamp("2026-08-17T13:25:00Z")))  # 09:25 ET
    assert ok["sealed"] == "SEALED_BEFORE_OPEN"
    assert ok["packet_sha256"]


def test_coverage_is_stated_per_source_never_globally():
    assert SOURCES["COMPANY_NEWS"] == "NOT_CONNECTED"
    assert SOURCES["MACRO_CALENDAR"] == "NOT_CONNECTED"
    assert SOURCES["EODHD_PREMARKET"] == "CONNECTED"
    pkt = _pkt(pd.Timestamp("2026-08-17T13:00:00Z"))
    assert "GOOD" not in json.dumps(pkt["source_coverage"])


def test_unknown_catalyst_dislocation_is_precisely_labeled():
    """Big move + volume + no identified event = interesting, and labeled
    'not identified by active sources', never 'inexplicable'."""
    src = open("apex/frontier/premarket.py").read()
    assert "UNKNOWN_CATALYST_DISLOCATION" in src
    assert "NO_KNOWN_CATALYST" in src           # ties to the bounded state
    assert "not\n                    # identified BY OUR ACTIVE SOURCES" \
        in src or "identified BY OUR ACTIVE SOURCES" in src


def test_the_brief_firewall_refuses_trading_vocabulary():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path("scripts").resolve()))
    from premarket_run import FORBIDDEN_IN_BRIEF
    for bad in ("buy ", "sell ", "probability"):
        assert bad in FORBIDDEN_IN_BRIEF
    # R4: the firewall moved into apex.frontier.premarket_stages so the staged producer and the legacy runner
    # cannot hold two copies of it. The property is unchanged; only its address is.
    src = open("apex/frontier/premarket_stages.py").read()
    assert "BRIEF REFUSED BY FIREWALL" in src
    assert "tape gets the final vote" in src
    assert "BRIEF REFUSED BY FIREWALL" not in open("scripts/premarket_run.py").read(), \
        "a second copy of the firewall text is a second firewall waiting to drift"


def test_anti_anchoring_is_written_into_the_brief_itself():
    src = open("apex/frontier/premarket_stages.py").read()      # R4: moved with the rest of the Captain path
    assert "PRIORS, NOT TRUTH" in src
    assert "THE BRIEF LOSES" in src


def test_h_premarket_is_preregistered_and_not_estimable():
    from apex.frontier.learning import PREREGISTRATION, estimate
    h = PREREGISTRATION["hypotheses"]["H_PREMARKET"]
    assert set(h["groups"]) == {"ALIGNED", "CONTRADICTED", "NOT_RELEVANT",
                                "UNKNOWN"}
    r = estimate("H_PREMARKET")
    assert r["status"] == "NOT_YET_ESTIMABLE"
    # SEMANTIC RULING 2026-08-18 (Phase 1.1): `resolved_cards == 0` here
    # encoded a pre-live world, not a governance law -- the 2026-08-18
    # session produced APEX's first legitimate resolved card (HD). The
    # law that matters is the line above: a non-empty denominator must
    # still not make an under-powered hypothesis estimable. See
    # test_frontier1.test_synthetic_cards_never_enter_the_learning_denominator
    # for the full ruling and the retained synthetic-exclusion invariant.
    from apex.frontier.learning import _resolved_cards
    assert r["resolved_cards"] == len(_resolved_cards())


def test_cards_carry_the_premarket_hash_but_agreement_stays_unknown():
    """The field exists so H_PREMARKET can be tested later; computing
    alignment is a post-Day-1 act, not a bell-eve one."""
    src = open("scripts/frontier_loop.py").read()
    assert "premarket_context_hash" in src
    assert '"premarket_prior_agreement": "UNKNOWN"' in src
    from apex.frontier.decision_card import SECTIONS
    assert "premarket" in SECTIONS


def test_epoch1_does_not_read_the_premarket_packet():
    from pathlib import Path
    # Fifth occurrence of the vocabulary-collision trap in this weekend's
    # own tooling: the clock legitimately computes premarket price LEVELS
    # (frozen ChartState feature). Scan for CONSUMPTION of the packet —
    # imports and loads — never the word.
    for f in ("apex/hunter/forward_pass.py", "apex/hunter/capital.py",
              "scripts/hunter_forward_clock.py",
              "apex/hunter/playbooks_v1.py"):
        src = Path(f).read_text()
        for token in ("apex.frontier.premarket", "load_sealed(",
                      "PremarketContextPacket"):
            assert token not in src, (
                f"{f} consumes the premarket packet — Epoch-1 must stay "
                f"blind to it")
