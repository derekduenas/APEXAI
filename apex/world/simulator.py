"""Digital Twin 2.0 layers + the probabilistic world simulator.

Three concepts, never conflated:
  TwinSnapshot        — the observed world at T (the existing descriptive
                        Twin: state records + ChartState; unchanged).
  TwinTransitionModel — legal transition machinery (v1: conditional
                        empirical block resampling; declared source).
  WorldSimulation     — many plausible short-horizon future paths FROM
                        the current state.

NOT price + Gaussian noise: paths are built from the symbol's own PRIOR
sessions' 1m return sequences, resampled in contiguous blocks conditioned
on time-of-day — volatility clustering and intraday seasonality survive
because real intraday segments are reused whole. The declared source is
"conditional_block_bootstrap_v1"; a Gaussian shortcut under that
declaration is a contract violation (tested).

FUTURE-BLIND LAW: a simulation at T may read today's bars only through
the same visibility choke point as ChartState, plus PRIOR sessions.
Counterexample test: replace every bar after T with absurd values — the
simulation must be bit-identical.

BRANCH WEIGHTS ARE NOT PROBABILITIES: outputs carry
branch_scenario_frequencies with calibration_status
UNCALIBRATED_SCENARIO_WEIGHT. Until a calibration report earns the word,
nothing downstream may print them as probabilities, and simulation can
never manufacture expected edge, PAPER_ELIGIBLE, or live eligibility —
it is DIAGNOSTIC / OBSERVE_ONLY (capital ignores it for authorization).

Reweighting is append-only: Simulation(T2) is a NEW simulation from the
new snapshot; Simulation(T1) is never mutated.

Determinism: seed = sha256(candidate_id | version | twin_hash | config),
so identical inputs reproduce identical scenario sets.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from apex.hunter.chartstate import visible_bars
from apex.intraday.sessions import Session, classify

SIMULATOR_VERSION = "hunter_world_sim_v1"
SOURCE = "conditional_block_bootstrap_v1"
BLOCK_MINUTES = 15
TOD_WINDOW_MINUTES = 45              # donor blocks start within +/- this
BRANCHES = ("STRONG_CONTINUATION", "MODERATE_CONTINUATION", "RANGE",
            "FAILED_BREAKOUT", "REVERSAL", "SHOCK")


@dataclass(frozen=True)
class TwinSnapshot:
    """Observed world at T — descriptive only, all as-of."""
    as_of: str
    market: dict                     # market ChartState summary / state rec
    symbol_state: dict               # candidate ChartState summary
    data_health: tuple = ()

    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps(
            asdict(self), sort_keys=True, default=str).encode()
        ).hexdigest()[:16]


@dataclass(frozen=True)
class WorldSimulationResult:
    simulation_id: str
    as_of: str
    horizon_minutes: int
    n_paths: int
    source: str
    calibration_status: str          # UNCALIBRATED_SCENARIO_WEIGHT (v1 always)
    branch_scenario_frequencies: dict
    return_q10: float
    return_median: float
    return_q90: float
    mae_median: float
    mfe_median: float
    target_first_frequency: float | None
    stop_first_frequency: float | None
    path_examples: tuple             # a few terminal returns for inspection
    uncertainty: str
    provenance: dict
    simulator_version: str = field(default=SIMULATOR_VERSION)

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "world_simulation"
        d["authorization_power"] = "NONE_DIAGNOSTIC_ONLY"
        return d


def _prior_day_return_curves(history: pd.DataFrame, today: str) -> list:
    """Per prior session: (minute_of_day array, 1m return array)."""
    reg = history[history["event_time_utc"].map(
        lambda t: classify(t) is Session.REGULAR)].copy()
    if reg.empty:
        return []
    reg["d"] = (reg["event_time_utc"].dt.tz_convert("America/New_York")
                .dt.date.astype(str))
    curves = []
    for d, f in reg.groupby("d"):
        if d >= today:
            continue                         # PRIOR sessions only
        px = f["close"].astype(float).to_numpy()
        if len(px) < 60:
            continue
        mins = ((f["event_time_utc"] - f["event_time_utc"].iloc[0])
                .dt.total_seconds() // 60).to_numpy(dtype=int)
        rets = np.diff(px) / px[:-1]
        curves.append((mins[1:], rets))
    return curves


def _classify_branch(term_ret: float, path_min: float, path_max: float,
                     direction: str, scale: float) -> str:
    sign = 1.0 if direction == "LONG" else -1.0
    z = sign * term_ret / max(scale, 1e-6)
    span = (path_max - path_min) / max(scale, 1e-6)
    if abs(z) >= 3.0 or span >= 5.0:
        return "SHOCK"
    if z >= 1.5:
        return "STRONG_CONTINUATION"
    if z >= 0.5:
        return "MODERATE_CONTINUATION"
    if z > -0.5:
        return "RANGE"
    if z > -1.5:
        return "FAILED_BREAKOUT"
    return "REVERSAL"


def simulate(candidate: dict, snapshot: TwinSnapshot, bars: pd.DataFrame,
             history: pd.DataFrame, *, horizon_minutes: int = 60,
             n_paths: int = 200, atr_frac: float | None = None) -> WorldSimulationResult | None:
    """None when there is no legal donor material (honest refusal)."""
    t = pd.Timestamp(snapshot.as_of)
    vis = visible_bars(bars, t)                # THE choke point; future-blind
    if vis.empty:
        return None
    today = str(t.tz_convert("America/New_York").date())
    curves = _prior_day_return_curves(history, today)
    if len(curves) < 5:
        return None
    minute_now = int((t - vis["event_time_utc"].iloc[0]).total_seconds() // 60)
    entry = float(vis["close"].astype(float).iloc[-1])
    direction = candidate.get("direction", "LONG")
    stop, target = candidate.get("stop"), candidate.get("target")
    scale = ((atr_frac or 0.02) * np.sqrt(horizon_minutes / 390.0))

    cfg = {"h": horizon_minutes, "n": n_paths, "block": BLOCK_MINUTES,
           "tod": TOD_WINDOW_MINUTES, "src": SOURCE}
    seed_material = (f"{candidate.get('decision_id', '?')}|{SIMULATOR_VERSION}"
                     f"|{snapshot.content_hash()}|{json.dumps(cfg, sort_keys=True)}")
    rng = np.random.default_rng(
        int.from_bytes(hashlib.sha256(seed_material.encode()).digest()[:8],
                       "big"))

    branches, terms, maes, mfes, t_first, s_first = [], [], [], [], [], []
    for _ in range(n_paths):
        path = []
        while len(path) < horizon_minutes:
            mins, rets = curves[rng.integers(len(curves))]
            want = minute_now + len(path)
            ok = np.where(np.abs(mins - want) <= TOD_WINDOW_MINUTES)[0]
            if len(ok) == 0:
                ok = np.arange(len(mins))
            start = int(ok[rng.integers(len(ok))])
            path.extend(rets[start:start + BLOCK_MINUTES].tolist())
        r = np.array(path[:horizon_minutes])
        px = entry * np.cumprod(1 + r)
        sign = 1.0 if direction == "LONG" else -1.0
        term = float(px[-1] / entry - 1)
        terms.append(sign * term)
        maes.append(float(sign * (px.min() if sign > 0 else px.max())
                          / entry - sign))
        mfes.append(float(sign * (px.max() if sign > 0 else px.min())
                          / entry - sign))
        branches.append(_classify_branch(term, float(px.min() / entry - 1),
                                         float(px.max() / entry - 1),
                                         direction, scale))
        if stop is not None and target is not None:
            if sign > 0:
                s_i = np.argmax(px <= stop) if (px <= stop).any() else None
                t_i = np.argmax(px >= target) if (px >= target).any() else None
            else:
                s_i = np.argmax(px >= stop) if (px >= stop).any() else None
                t_i = np.argmax(px <= target) if (px <= target).any() else None
            t_first.append(t_i is not None and (s_i is None or t_i < s_i))
            s_first.append(s_i is not None and (t_i is None or s_i <= t_i))

    freq = {b: round(branches.count(b) / n_paths, 3) for b in BRANCHES}
    return WorldSimulationResult(
        simulation_id=hashlib.sha256(seed_material.encode()).hexdigest()[:16],
        as_of=str(t), horizon_minutes=horizon_minutes, n_paths=n_paths,
        source=SOURCE, calibration_status="UNCALIBRATED_SCENARIO_WEIGHT",
        branch_scenario_frequencies=freq,
        return_q10=round(float(np.quantile(terms, 0.10)), 5),
        return_median=round(float(np.median(terms)), 5),
        return_q90=round(float(np.quantile(terms, 0.90)), 5),
        mae_median=round(float(np.median(maes)), 5),
        mfe_median=round(float(np.median(mfes)), 5),
        target_first_frequency=(round(float(np.mean(t_first)), 3)
                                if t_first else None),
        stop_first_frequency=(round(float(np.mean(s_first)), 3)
                              if s_first else None),
        path_examples=tuple(round(x, 5) for x in terms[:5]),
        uncertainty="HIGH",
        provenance={"donor_sessions": len(curves), "config": cfg,
                    "seed_material_hash": hashlib.sha256(
                        seed_material.encode()).hexdigest()[:12]})
