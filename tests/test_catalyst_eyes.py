"""T1 item 6 — the Event Eyes must answer WHY IS IT MOVING honestly.

The three-state distinction is everything: a MEASURED absence of news
(NO_KNOWN_CATALYST) and an UNANSWERABLE question (EVENT_UNCERTAIN) must
never collapse into each other — that collapse is LAB-04 wearing a news
feed.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.events.catalyst import (EVENT_UNCERTAIN, KNOWN_CATALYST,
                                  NO_KNOWN_CATALYST, catalyst_state)

NOW = pd.Timestamp("2026-08-17T14:00:00Z")


def _ev(cik="1045810", event="2026-08-17T11:00:00+00:00",
        known="2026-08-17T11:05:00+00:00", form="8-K"):
    return {"kind": "edgar_event", "form_type": form,
            "company_raw": f"NVIDIA CORP ({cik.zfill(10)}) (Filer)",
            "event_time_utc": event, "known_from_utc": known,
            "source": "SEC_EDGAR_CURRENT_ATOM", "accession": "a1",
            "url": "https://sec.gov/x"}


def test_a_matching_filing_is_a_known_catalyst():
    st = catalyst_state("NVDA.US", NOW, cik="1045810", events=[_ev()])
    assert st.status == KNOWN_CATALYST
    assert st.events[0]["form_type"] == "8-K"
    assert st.decision_power == "NONE_OBSERVATIONAL_EPOCH1"


def test_pit_law_an_event_is_invisible_before_its_known_from():
    """Filed at 11:00, captured at 15:00. At 14:00 APEX did NOT know."""
    late = _ev(known="2026-08-17T15:00:00+00:00")
    fresh = _ev(cik="9999999", known="2026-08-17T13:59:00+00:00")
    st = catalyst_state("NVDA.US", NOW, cik="1045810",
                        events=[late, fresh])
    assert st.status != KNOWN_CATALYST, (
        "an event was attributed before APEX captured it — hindsight "
        "catalyst knowledge")


def test_measured_absence_is_not_uncertainty():
    other = _ev(cik="9999999", known="2026-08-17T13:30:00+00:00")
    st = catalyst_state("NVDA.US", NOW, cik="1045810", events=[other])
    assert st.status == NO_KNOWN_CATALYST
    assert "MEASURED" in st.reason


def test_no_identity_bridge_is_uncertain_never_guessed():
    st = catalyst_state("NVDA.US", NOW, cik=None,
                        events=[_ev(known="2026-08-17T13:30:00+00:00")])
    assert st.status == EVENT_UNCERTAIN
    assert "fuzzy" in st.reason


def test_a_stale_archive_is_uncertain_not_quiet():
    """Silence from a dead feed must not read as a quiet issuer."""
    old = _ev(known="2026-08-16T20:00:00+00:00")     # 18h before as_of
    st = catalyst_state("NVDA.US", NOW, cik="1045810", events=[old])
    assert st.status == EVENT_UNCERTAIN
    assert "dead feed" in st.reason


def test_an_empty_archive_is_uncertain():
    st = catalyst_state("NVDA.US", NOW, cik="1045810", events=[])
    assert st.status == EVENT_UNCERTAIN


def test_as_of_must_be_tz_aware():
    with pytest.raises(ValueError):
        catalyst_state("NVDA.US", "2026-08-17 14:00", cik="1")


def test_the_frozen_pipeline_does_not_consume_catalyst_state():
    """Prose-vs-code, the repo's signature trap (and this test's first
    draft fell into it: HUNTER-002's invalidation text legitimately SAYS
    'catalyst arriving mid-trade'). Scan for CONSUMPTION — imports and
    calls — not vocabulary."""
    from pathlib import Path
    for f in ("apex/hunter/playbooks_v1.py", "apex/hunter/capital.py",
              "apex/hunter/scanner.py", "scripts/hunter_forward_clock.py"):
        src = Path(f).read_text()
        for token in ("from apex.events.catalyst", "import catalyst",
                      "catalyst_state("):
            assert token not in src, (
                f"{f} consumes the catalyst channel — Epoch 1 is frozen")


def test_captain_eyes_refuses_replay_imagery():
    """Rule 17 in the wiring: the script must contain a hard refusal for
    non-forward evidence, so historical charts can never reach the model."""
    src = open("scripts/captain_eyes.py").read()
    assert "RULE 17" in src
    seg = src.split("RULE 17", 2)[-1][:400]
    assert "raise" in src.split('evidence_class") != "EODHD_FORWARD_OBSERVATION"', 1)[1][:200]


def test_captain_eyes_with_no_decisions_reports_nothing_to_see():
    # sys.executable, not a hardcoded .venv path: the suite runs
    # on both the Mac dev host and the cloud canonical host.
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "scripts/captain_eyes.py",
                        "--latest"], capture_output=True, text=True,
                       timeout=300)
    if "no playbook decisions" in r.stdout:
        assert r.returncode == 2      # honest empty, distinct from success
