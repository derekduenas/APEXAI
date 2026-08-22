"""FrontierComputeRouter — F15. Proves tier selection is a deterministic
lookup over named ordinals, high uncertainty escalates but never past
what seriousness already earned, and nothing here can be read as trade
or risk authority.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2.compute_router2 import (TIERS, ComputeRoute,
                                             ComputeRouter2Error, route)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def test_ignore_no_change_is_tier_0():
    rt = route("AAPL", known_from=T0, now=T0)
    assert rt.tier == 0


def test_material_change_with_no_seriousness_is_tier_1():
    rt = route("AAPL", material_change=True, known_from=T0, now=T0)
    assert rt.tier == 1


def test_watch_is_tier_1():
    rt = route("AAPL", opportunity_seriousness="WATCH", known_from=T0, now=T0)
    assert rt.tier == 1


def test_serious_is_tier_4():
    rt = route("AAPL", opportunity_seriousness="SERIOUS", known_from=T0, now=T0)
    assert rt.tier == 4


def test_wait_for_entry_is_tier_4():
    rt = route("AAPL", opportunity_seriousness="WAIT_FOR_ENTRY", known_from=T0, now=T0)
    assert rt.tier == 4


def test_wait_for_confirmation_is_tier_3():
    rt = route("AAPL", opportunity_seriousness="WAIT_FOR_CONFIRMATION",
              known_from=T0, now=T0)
    assert rt.tier == 3


def test_develop_low_info_value_is_tier_2():
    rt = route("AAPL", opportunity_seriousness="DEVELOP",
              information_value="LOW", known_from=T0, now=T0)
    assert rt.tier == 2


def test_develop_high_info_value_is_tier_3():
    rt = route("AAPL", opportunity_seriousness="DEVELOP",
              information_value="HIGH", known_from=T0, now=T0)
    assert rt.tier == 3


def test_degrading_thesis_still_gets_a_real_check_not_zero():
    rt = route("AAPL", opportunity_seriousness="DEGRADE", known_from=T0, now=T0)
    assert rt.tier == 2
    rt2 = route("AAPL", opportunity_seriousness="INVALIDATE", known_from=T0, now=T0)
    assert rt2.tier == 2


def test_high_uncertainty_escalates_a_low_tier():
    rt = route("AAPL", uncertainty="HIGH", known_from=T0, now=T0)
    assert rt.tier == 2                     # 0 -> escalated to 2


def test_high_uncertainty_never_downgrades_an_already_higher_tier():
    rt = route("AAPL", opportunity_seriousness="SERIOUS", uncertainty="HIGH",
              known_from=T0, now=T0)
    assert rt.tier == 4                     # unaffected, already above 2


def test_unknown_seriousness_refused():
    with pytest.raises(ComputeRouter2Error):
        route("AAPL", opportunity_seriousness="BUY", known_from=T0, now=T0)


def test_unknown_uncertainty_refused():
    with pytest.raises(ComputeRouter2Error):
        route("AAPL", uncertainty="EXTREME", known_from=T0, now=T0)


def test_bad_tier_refused_at_construction():
    with pytest.raises(ComputeRouter2Error):
        ComputeRoute(subject="X", tier=99, tier_description="x",
                    material_change=False, opportunity_seriousness="IGNORE",
                    uncertainty="LOW", information_value="LOW", reasoning=(),
                    known_from=str(T0), as_of=str(T0))


def test_no_trade_or_risk_authority_fields():
    fields = set(ComputeRoute.__dataclass_fields__)
    assert not (fields & {"size", "risk_authority", "trade_authority"})
    rt = route("AAPL", opportunity_seriousness="SERIOUS", known_from=T0, now=T0)
    assert "never implies trade or risk authority" in rt.as_record()["note"]


def test_all_five_tiers_documented():
    assert set(TIERS.keys()) == {0, 1, 2, 3, 4}


def test_determinism_same_inputs_twice_byte_identical():
    a = route("AAPL", opportunity_seriousness="DEVELOP", known_from=T0, now=T0)
    b = route("AAPL", opportunity_seriousness="DEVELOP", known_from=T0, now=T0)
    assert a.as_record() == b.as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.compute_router2 as cr
    monkeypatch.setattr(cr, "LEDGER", tmp_path / "cr.jsonl")
    rt = route("AAPL", known_from=T0, now=T0)
    rec1 = cr.persist(rt)
    rec2 = cr.persist(rt)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
