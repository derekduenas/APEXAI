"""A-009 machinery: hand-computed pricing, and every counterexample the
signed amendment demands (§7 items 2-6)."""

from __future__ import annotations

import numpy as np
import pytest

from apex.governance import holdout_capacity as H


# --- §7.2 pricing, hand-computed incl. boundary cases -----------------------

def test_n_eff_and_charge_hand_computed():
    assert H.n_eff(1, 0.6) == 1.0
    assert H.n_eff(2, 0.6) == pytest.approx(2 / 1.6)          # 1.25
    assert H.charge(2, 0.6) == pytest.approx(0.25)            # floor binds
    assert H.charge(2, 0.15) == pytest.approx(2 / 1.15 - 1)   # 0.7391
    assert H.charge(1, 0.9) == pytest.approx(1.0)             # first look is full
    assert H.n_eff(3, 1.0) == pytest.approx(1.0)              # perfect corr adds nothing
    assert H.charge(3, 1.0) == pytest.approx(0.25)            # ...but is never free


def test_class_floors_bind_and_default_penalises():
    assert H.governing_rho(0.10, "II") == 0.50, "engineered low corr cannot buy independence"
    assert H.governing_rho(0.60, "II") == 0.60, "a HIGHER measurement is kept"
    assert H.governing_rho(None, "III") == 0.7, "unmeasurable defaults to the penalising guess"
    with pytest.raises(H.CapacityError, match="unknown independence class"):
        H.governing_rho(0.5, "VI")


# --- §7.3 leak suppression --------------------------------------------------

def test_rho_measurement_emits_one_float_and_nothing_else(capsys):
    rng = np.random.default_rng(2)
    out = H.measure_rho(rng.normal(0.08, 0.01, 300),      # candidate has a HUGE mean
                        [rng.normal(0, 0.01, 300)])
    assert isinstance(out, float) and 0.0 <= out <= 1.0
    assert capsys.readouterr().out == "", "the pricing path printed something"


def test_the_pricing_path_is_scale_and_mean_invariant():
    """The proof no performance statistic flows through: shifting and scaling
    the candidate's returns (changing its ENTIRE economics) leaves the
    emitted number identical."""
    rng = np.random.default_rng(3)
    cand = rng.normal(0, 0.01, 300)
    other = [rng.normal(0, 0.01, 300)]
    assert H.measure_rho(cand, other) == pytest.approx(
        H.measure_rho(cand * 7 + 0.55, other))


# --- §7.4 automatic reversion ------------------------------------------------

def test_budget_is_8_while_pricing_is_operative():
    assert H.pricing_operative() and H.budget() == 8


def test_counterexample_breaking_pricing_reverts_the_budget_to_5(monkeypatch):
    monkeypatch.setattr(H, "CHARGE_FLOOR", 0.0)     # 'free' correlated re-tests
    assert not H.pricing_operative()
    assert H.budget() == 5, "the reversion clause must live in code, not prose"


# --- §7.5 irrevocable naming + programme-wide burn ---------------------------

def test_naming_is_irrevocable_and_burn_is_programme_wide(tmp_path):
    led = H.HoldoutCapacityLedger(tmp_path / "cap.jsonl")
    led.define_holdout("midcap-2022-2026", "u" * 16, "2022..2026", "II")
    led.define_holdout("microcap-2022-2026", "v" * 16, "2022..2026", "II")
    led.name_holdout("APEX-005", "midcap-2022-2026")
    with pytest.raises(H.CapacityError, match="never be\\s+renegotiated"):
        led.name_holdout("APEX-005", "microcap-2022-2026")
    led.burn("midcap-2022-2026")
    with pytest.raises(H.CapacityError, match="BURNED programme-wide"):
        led.name_holdout("APEX-006", "midcap-2022-2026")
    with pytest.raises(H.CapacityError, match="cannot be revised"):
        led.define_holdout("midcap-2022-2026", "u" * 16, "2022..2026", "III")


def test_a_charge_row_carries_every_mandatory_field(tmp_path):
    led = H.HoldoutCapacityLedger(tmp_path / "cap.jsonl")
    led.define_holdout("midcap", "u" * 16, "2022..2026", "II")
    row = led.record_charge(experiment="APEX-005", holdout_id="midcap",
                            klass="II", measured_rho=0.62,
                            rho_window="in-sample 2005-2017", k=2)
    for field in ("holdout_id", "universe_hash", "class", "measured_rho",
                  "governing_rho", "rho_estimation_window", "n_eff_before",
                  "n_eff_after", "charge", "cumulative_charges",
                  "remaining_budget"):
        assert field in row or field == "universe_hash"   # hash on the define row
    s = led.summary()
    assert "cumulative_charges_governs_budget" in s
    assert "n_eff_current_set_governs_multiplicity" in s, (
        "section 3.3: never one without the other")


# --- §7.6 verdict weight -----------------------------------------------------

def test_a_bare_verdict_is_refused_and_a_weighted_one_passes():
    w = H.weighted_verdict("SUCCESS", "II", 0.60, 0.25)
    assert w == "SUCCESS (Class II, ρ̄=0.60, +0.25 N_eff)"
    assert H.require_weighted(w) == w
    with pytest.raises(H.CapacityError, match="headline-hunting"):
        H.require_weighted("SUCCESS")
