"""GOVERNANCE-TOOL-001 regression tests.

Each encodes the specific way the planner could be fooled.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apex.ops.resource_profile import (EvidenceQuality,
                                       LimitDerivationRefused,
                                       ResourceProfile, assess,
                                       derive_limits)

UTC = timezone.utc
MiB = 1024 * 1024
GiB = 1024 * MiB


def _p(**kw):
    base = dict(
        service="x.service",
        observation_start=(datetime(2026, 8, 24, tzinfo=UTC)).isoformat(),
        observation_end=(datetime(2026, 9, 2, tzinfo=UTC)).isoformat(),
        historical_peak_bytes=None, current_peak_bytes=None)
    base.update(kw)
    return ResourceProfile(**base)


# ---- THE THETA TRAP -------------------------------------------------
def test_post_restart_peak_alone_is_refused():
    """The exact GOVERNANCE-TOOL-001 scenario.

    Long-lived service, 1.11 GiB real working set, restarted minutes
    ago, live peak now 410 MB. The planner must REFUSE, not propose
    615 MB.
    """
    p = _p(service="apex-thetaterminal.service",
           historical_peak_bytes=None,
           current_peak_bytes=410 * MiB,
           last_restart=datetime(2026, 9, 2, 2, 5,
                                 tzinfo=UTC).isoformat())
    assert assess(p) is EvidenceQuality.POST_RESTART_ONLY
    with pytest.raises(LimitDerivationRefused) as e:
        derive_limits(p)
    assert "INSUFFICIENT_EVIDENCE_FOR_LIMIT_DERIVATION" in str(e.value)


def test_historical_peak_survives_a_restart():
    """Restart must not erase older evidence."""
    p = _p(service="apex-thetaterminal.service",
           historical_peak_bytes=1164416 * 1024,     # 1.11 GiB, 9 days
           current_peak_bytes=410 * MiB,             # post-restart
           lifecycle_boundaries=3,
           last_restart=datetime(2026, 9, 2, 2, 5,
                                 tzinfo=UTC).isoformat())
    assert assess(p) is EvidenceQuality.SUFFICIENT
    d = derive_limits(p)
    assert d["MemoryHigh"] == 1164416 * 1024
    assert d["MemoryMax"] == int(1164416 * 1024 * 1.5)
    assert d["derived_from"] == "historical_peak_bytes"
    # emphatically NOT the 615 MB the old planner produced
    assert d["MemoryMax"] > 1 * GiB


def test_current_peak_never_becomes_the_basis():
    p = _p(historical_peak_bytes=2 * GiB, current_peak_bytes=50 * MiB)
    d = derive_limits(p)
    assert d["MemoryHigh"] == 2 * GiB


# ---- other insufficiency modes --------------------------------------
def test_new_service_with_no_history_is_refused():
    p = _p(historical_peak_bytes=None, current_peak_bytes=None)
    assert assess(p) is EvidenceQuality.INSUFFICIENT_NO_HISTORY
    with pytest.raises(LimitDerivationRefused):
        derive_limits(p)


def test_short_observation_window_is_refused():
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    p = _p(observation_start=(now - timedelta(minutes=5)).isoformat(),
           observation_end=now.isoformat(),
           historical_peak_bytes=400 * MiB)
    assert assess(p) is EvidenceQuality.INSUFFICIENT_WINDOW
    with pytest.raises(LimitDerivationRefused):
        derive_limits(p)


def test_market_facing_service_needs_a_full_day():
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    p = _p(observation_start=(now - timedelta(hours=8)).isoformat(),
           observation_end=now.isoformat(),
           historical_peak_bytes=900 * MiB)
    assert assess(p) is EvidenceQuality.SUFFICIENT            # 8h > 6h
    assert assess(p, market_facing=True) is \
        EvidenceQuality.INSUFFICIENT_WINDOW                   # 8h < 24h
    with pytest.raises(LimitDerivationRefused):
        derive_limits(p, market_facing=True)


def test_stale_version_profile_is_refused():
    """A peak observed under different code is not authoritative."""
    p = _p(historical_peak_bytes=2 * GiB,
           observed_under_release="5eff1cf5")
    assert assess(p, current_release="5eff1cf5") is \
        EvidenceQuality.SUFFICIENT
    assert assess(p, current_release="72b58c8c") is \
        EvidenceQuality.STALE_VERSION
    with pytest.raises(LimitDerivationRefused):
        derive_limits(p, current_release="72b58c8c")


def test_peak_from_a_defective_regime_is_refused():
    """btc_paper peaked at 1 GB because it re-read 350 MB every 30s.

    That peak is a symptom, not a capacity requirement, and must never
    become the repaired successor's budget.
    """
    p = _p(service="apex-btc-paper.service",
           historical_peak_bytes=1 * GiB,
           evidence_quality=EvidenceQuality.DEFECTIVE_REGIME.value)
    assert assess(p) is EvidenceQuality.DEFECTIVE_REGIME
    with pytest.raises(LimitDerivationRefused):
        derive_limits(p)


# ---- provenance -----------------------------------------------------
def test_profile_carries_provenance_and_hash():
    p = _p(historical_peak_bytes=1 * GiB,
           observed_under_release="72b58c8c",
           market_context="RTH",
           sources=["journalctl -u x.service"],
           method="systemd post-run accounting")
    d = p.to_dict()
    for k in ("profile_version", "observation_span_hours",
              "profile_hash", "sources", "method",
              "observed_under_release", "lifecycle_boundaries",
              "market_context", "evidence_quality"):
        assert k in d, k
    assert d["profile_version"] == "RESOURCE_PROFILE_V1"


def test_profile_hash_changes_with_evidence():
    a = _p(historical_peak_bytes=1 * GiB)
    b = _p(historical_peak_bytes=2 * GiB)
    assert a.profile_hash() != b.profile_hash()


def test_refusal_message_names_the_reason():
    p = _p(historical_peak_bytes=None, current_peak_bytes=1 * MiB,
           last_restart=datetime(2026, 9, 2, tzinfo=UTC).isoformat())
    with pytest.raises(LimitDerivationRefused) as e:
        derive_limits(p)
    assert "POST_RESTART_ONLY" in str(e.value)
