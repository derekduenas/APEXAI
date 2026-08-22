"""CURVE V2 PROPERTY TESTS -- the mathematics repair of 2026-08-20.

V1's defect, proven live on 17,322 states: curvature = OLS_acceleration /
std(raw levels) has units hour^-2, so its magnitude was set by the window
length (~1/T^2 ~ 100+ for the 6-minute live window), not by the data.
price fired "elevated" on 99.9% of a full session; a 2-microdollar wobble
scored |curvature| > 4.

V2 is a return-normalized second difference judged against a LONGER
trailing distribution: z = (r_n - r_{n-1}) / (std_ddof1(trailing) *
sqrt(2)), trailing = r_1..r_{n-1} capped at SIGMA_MAX_RETURNS, newest
return excluded. The exclusion is itself pinned by a property test here:
a first draft used a self-inclusive sigma and the single-break maximum
|z| was mathematically capped at sqrt(n/2) ~ 1.58 < ELEVATED_Z -- break
detection was structurally unreachable, the same defect class being
repaired.

Every test constructs its series from first principles. NO test reads
Thursday outcomes. NO test asserts a target firing percentage.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.frontier2 import curve  # noqa: E402
from apex.frontier2.curve import compute_dimension  # noqa: E402

T0 = pd.Timestamp("2026-08-20 14:00:00", tz="UTC")


def _pts(values, spacing_s=60):
    return [(T0 + pd.Timedelta(seconds=i * spacing_s), v)
            for i, v in enumerate(values)]


def _z(values):
    return compute_dimension(
        "price", _pts(values),
        now=T0 + pd.Timedelta(minutes=len(values)), known_from=T0)


# A realistic 12-bar noisy drift (hand-written once, never regenerated)
BASE = [770.0, 770.4, 770.2, 770.9, 771.1, 770.8, 771.5, 771.2, 771.9,
        772.1, 771.8, 772.4]


# ------------------------------------------------------------ invariance

def test_scale_invariance_x10():
    a = _z(BASE).curvature
    b = _z([v * 10 for v in BASE]).curvature
    assert a is not None
    assert a == pytest.approx(b, abs=1e-6)


def test_shift_invariance_plus_100000():
    a = _z(BASE).curvature
    b = _z([v + 100000 for v in BASE]).curvature
    # log mode is invariant to O((dp/p)^2); at these magnitudes that is
    # far below the 4-decimal rounding of the statistic
    assert a == pytest.approx(b, abs=0.05)


def test_split_adjustment_invariance():
    # a 10:1 split-adjusted trajectory is the same market path
    a = _z(BASE).curvature
    b = _z([v / 10 for v in BASE]).curvature
    assert a == pytest.approx(b, abs=1e-6)


# ----------------------------------------------------------- degeneracy

def test_exact_flat_is_neutral_zero():
    d = _z([770.0] * 12)
    assert d.curvature == 0.0
    assert not d.elevated()


def test_exact_linear_trend_is_neutral_in_diff_mode():
    # RS-style signed level series with a constant drift: second
    # difference is exactly zero, sigma is exactly zero -> 0.0 neutral
    d = _z([0.0 + 0.001 * i for i in range(12)])
    assert d.return_mode == "diff"
    assert d.curvature == 0.0
    assert not d.elevated()


def test_jump_out_of_perfect_flatness_is_refused_not_fabricated():
    # eleven perfectly flat bars then a jump: the trailing distribution
    # has sigma == 0 and the numerator != 0 -- there is no trailing
    # variability to judge the jump against, so z is undefined. REFUSE.
    d = _z([770.0] * 11 + [777.7])
    assert d.curvature is None
    assert not d.elevated()


def test_micro_noise_wobble_does_not_elevate():
    """THE 2026-08-20 reproduction pattern (2-microdollar wobble),
    extended to the V2 window. V1 scored the sextet |curvature| > 4 and
    the live analogue scored in the hundreds. V2 must see ordinary
    noise."""
    wob = [770.0, 770.000001, 770.000002, 770.000001, 770.000003,
           770.000001, 770.000002, 770.000000, 770.000002, 770.000001,
           770.000003, 770.000001]
    d = _z(wob)
    assert d.curvature is not None
    assert abs(d.curvature) < curve.ELEVATED_Z, (
        f"micro-noise scored z={d.curvature} -- the V1 pathology is back")


def test_dollar_linear_trend_is_near_zero():
    # constant $0.10/min climb in log mode: returns decline smoothly
    d = _z([770.0 + 0.1 * i for i in range(12)])
    assert d.curvature is not None
    assert abs(d.curvature) < curve.ELEVATED_Z


# ----------------------------------------------------- genuine structure

def test_abrupt_reversal_after_noisy_trend_is_detected():
    # a realistic noisy climb, then a hard one-bar reversal several
    # times the size of any trailing move
    ser = BASE + [768.0]
    d = _z(ser)
    assert d.curvature is not None
    assert d.curvature < 0
    assert abs(d.curvature) >= curve.ELEVATED_Z, (
        f"z={d.curvature}: a genuine trajectory break must register")


def test_single_break_elevation_is_not_mathematically_capped():
    """Pins the sigma-exclusion design decision. With self-inclusive
    sigma, one-bar breaks had max |z| = sqrt(n/2) < ELEVATED_Z: the
    statistic could NEVER elevate on the exact event class it exists
    for. Trailing-exclusive sigma must let a large break exceed the
    threshold by an arbitrary margin."""
    quiet = [770.0 + 0.05 * ((-1) ** i) for i in range(11)]
    d = _z(quiet + [760.0])                       # ~$10 one-bar break
    assert d.curvature is not None
    assert abs(d.curvature) > 10 * curve.ELEVATED_Z


def test_accelerating_trend_detects_bend_consistently():
    # returns growing linearly: z positive at every scale -- consistent
    # detection of the bend's direction (elevation is NOT required for a
    # smooth self-similar acceleration; abruptness is what elevates)
    ser1 = [770.0 + 0.01 * i * i for i in range(12)]
    ser2 = [500.0 + 0.0065 * i * i for i in range(12)]
    d1, d2 = _z(ser1), _z(ser2)
    assert d1.curvature is not None and d1.curvature > 0
    assert d2.curvature is not None and d2.curvature > 0


def test_single_spike_suppresses_subsequent_windows_not_permanently():
    # spike at bar k: once the spike's return joins the TRAILING sigma,
    # later ordinary moves are judged against the inflated distribution
    # and score LOWER than they would have without the spike
    calm = [770.0, 770.1, 770.05, 770.12, 770.08, 770.15, 770.1, 770.18,
            770.13, 770.2, 770.16]
    # the spike must sit >= 2 returns back: the second difference reads
    # r_n and r_{n-1}, so one bar after a spike the NUMERATOR itself
    # still contains the spike's aftermath -- that window legitimately
    # scores high. Two bars later both numerator returns are ordinary
    # and only the trailing sigma remembers the spike.
    with_spike = calm + [785.0, 770.2, 770.25, 770.32]
    without = calm + [770.22, 770.2, 770.25, 770.32]
    zs = _z(with_spike).curvature
    zn = _z(without).curvature
    assert zs is not None and zn is not None
    assert abs(zs) < abs(zn), "spike failed to dampen subsequent windows"


# --------------------------------------------------------------- refusal

def test_insufficient_history_refuses():
    d = _z([770.0 + 0.1 * i for i in range(6)])   # 6 < MIN_POINTS(10)
    assert d.status == curve.INSUFFICIENT_HISTORY
    assert d.curvature is None
    assert not d.elevated()


def test_empty_is_no_support():
    d = compute_dimension("price", [], now=T0, known_from=T0)
    assert d.status == curve.NO_SUPPORT
    assert not d.elevated()


# ------------------------------------------------------------ versioning

def test_formula_version_and_hash_are_stamped_on_every_record():
    d = _z(BASE)
    rec = d.as_record()
    assert rec["formula_version"] == curve.CURVE_FORMULA_VERSION
    assert rec["formula_hash"] == curve._formula_hash()
    assert rec["curvature_units"] == "Z_SCORE_DIMENSIONLESS"
    assert rec["return_mode"] in ("log", "diff")


def test_v1_threshold_is_retired_not_deleted():
    # archaeology on pre-V2 ledger rows needs the old constant's meaning
    assert curve.ELEVATED_CURVATURE_V1_RETIRED == 1.0
    assert not hasattr(curve, "ELEVATED_CURVATURE"), (
        "the retired V1 threshold must not survive under its old load-"
        "bearing name where stale code could silently keep reading it")


def test_elevated_uses_the_z_threshold():
    d = _z(BASE + [768.0])
    assert d.elevated() == (abs(d.curvature) >= curve.ELEVATED_Z)


def test_sigma_window_constants_are_the_preregistered_values():
    assert curve.SIGMA_MAX_RETURNS == 30
    assert curve.MIN_SIGMA_RETURNS == 8
    assert curve.MIN_POINTS_FOR_CURVATURE == 10
    assert curve.ELEVATED_Z == 2.0


# ------------------------------------------- non-degeneracy (descriptive)

def test_non_degeneracy_on_real_thursday_bars_descriptive_only():
    """Replays Thursday's ACTUAL bar files through V2 -- DESCRIPTIVE
    distribution diagnostics only, no outcomes, no threshold selection.
    Success = the statistic is not effectively constant, elevated is
    neither always-on nor never-on across a real session's windows.
    The bounds are deliberately loose sanity rails, not calibration
    targets."""
    import json
    bars_dir = Path("data/live/alpaca_fabric/bars")
    if not bars_dir.exists():
        pytest.skip("no live bar data in this environment")
    W = curve.SIGMA_MAX_RETURNS + 1
    zs = []
    for sym in ("SPY", "QQQ", "IWM", "XLK", "XLE", "NVDA", "TSLA", "KO"):
        f = bars_dir / f"{sym}_2026-08-20.json"
        if not f.exists():
            continue
        rows = json.loads(f.read_text())["bars"]
        closes = [(pd.Timestamp(b["event_time_utc"]), float(b["close"]))
                  for b in sorted(rows, key=lambda b: b["event_time_utc"])]
        for i in range(W, len(closes)):
            win = closes[i - W:i]
            d = compute_dimension("price", win, now=win[-1][0],
                                  known_from=win[-1][0])
            if d.curvature is not None:
                zs.append(d.curvature)
    if len(zs) < 500:
        pytest.skip("insufficient real windows")
    elev = sum(1 for z in zs if abs(z) >= curve.ELEVATED_Z) / len(zs)
    distinct = len(set(round(z, 2) for z in zs))
    assert distinct > 50, "statistic is effectively constant"
    assert 0.0 < elev < 1.0, "elevated is degenerate (always or never on)"
    print(f"\nV2 on {len(zs)} real Thursday windows: "
          f"elevated={100 * elev:.1f}%  z-range=[{min(zs):.2f},{max(zs):.2f}]")
