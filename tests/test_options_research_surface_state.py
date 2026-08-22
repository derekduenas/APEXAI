"""OptionSurfaceState — every feature honestly typed, no single scalar
represents the whole surface, absence is NO_SUPPORT not a fabricated 0.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.options_research.surface_state import (SURFACE_FEATURES,
                                                  SurfaceStateError,
                                                  build_surface)

T0 = pd.Timestamp("2026-08-18T14:40:00Z")


def test_all_features_present_even_when_unsupplied():
    s = build_surface("AAPL", "2026-08-19", known_from=T0, now=T0)
    assert set(s.features.keys()) == set(SURFACE_FEATURES)
    for f in s.features.values():
        assert f["status"] == "NO_SUPPORT"
        assert f["value"] is None


def test_supplied_feature_is_supported():
    s = build_surface("AAPL", "2026-08-19", known_from=T0, now=T0,
                      values={"atm_iv": 0.35})
    assert s.feature("atm_iv")["status"] == "SUPPORTED"
    assert s.feature("atm_iv")["value"] == 0.35
    assert s.feature("skew")["status"] == "NO_SUPPORT"


def test_no_single_iv_rank_field_exists():
    """Structural proof: nothing named iv_rank collapses the surface."""
    fields = set(__import__("apex.options_research.surface_state",
                           fromlist=["OptionSurfaceState"]
                           ).OptionSurfaceState.__dataclass_fields__)
    assert "iv_rank" not in fields


def test_unknown_feature_name_refused():
    from apex.options_research.surface_state import SurfaceFeature
    with pytest.raises(SurfaceStateError):
        SurfaceFeature(name="not_a_real_feature", value=1.0, status="SUPPORTED",
                       support=1, freshness_s=None, known_from=str(T0))


def test_decision_power_stamped():
    s = build_surface("AAPL", "2026-08-19", known_from=T0, now=T0)
    assert s.decision_power == "NONE_OPTIONS_RESEARCH"


def test_determinism():
    a = build_surface("AAPL", "2026-08-19", known_from=T0, now=T0, values={"atm_iv": 0.3})
    b = build_surface("AAPL", "2026-08-19", known_from=T0, now=T0, values={"atm_iv": 0.3})
    assert a.as_record() == b.as_record()
