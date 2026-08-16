"""APEX Analog Engine v1 — "when APEX has seen states most like this one,
what happened next?"

NOT chart-pattern matching: similarity is defined over economically
meaningful state (regime, volatility, breadth, relative strength, RVOL,
VWAP/OR geometry, time of day, liquidity), with a FROZEN feature schema
and frozen distance semantics. Distance itself is information: a state
unlike anything in memory returns NO_VALID_ANALOGS or ANALOG_SUPPORT=LOW
— sparse memory can never output confident probabilities.

THE LEAKAGE LAW (tested as a deliberate counterexample): the future
outcome of a candidate analogue can NEVER influence whether it is
selected as a neighbour. Neighbour identities are frozen from state
features alone; outcomes are joined only afterward. Changing every
future return in memory must leave the selected neighbours identical.

Evidence classes are never mixed: a query answers from ONE class per
result (EODHD_FORWARD_OBSERVATION or EODHD_HISTORICAL_EXPLORATORY), and
historical-exploratory results carry the survivorship limitation and can
never graduate anything (evidence law).

Structural time firewall: rows at-or-after the query's as_of, and rows
whose OUTCOME had not yet resolved by as_of, are excluded before distance
is ever computed — a Monday query can never retrieve a Tuesday outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from apex.hunter.evidence import EvidenceClass

ANALOG_ENGINE_VERSION = "hunter_analog_v1.1"

# ---------------------------------------------------------------- schema
# FROZEN v1 feature schema: (name, extractor path in the stored candidate
# record, scale). Scales are declared magnitudes that put features on
# comparable units (a z-ish normalization with FIXED constants — never
# fitted from the memory being queried, so no future leakage through
# normalization). Weights are uniform ACROSS THE DECLARED SCALES —
# a deliberate, recorded starting point, revisable only as a new version.
ANALOG_FEATURE_SCHEMA_V1 = (
    ("minutes_into_session", ("chart_state", "minutes_into_session"), 130.0),
    ("day_return",           ("chart_state", "day_return"),           0.01),
    ("r_30m",                ("chart_state", "r_30m"),                0.005),
    ("r_60m",                ("chart_state", "r_60m"),                0.007),
    ("distance_to_vwap",     ("chart_state", "distance_to_vwap"),     0.004),
    ("position_in_or",       ("chart_state", "position_in_or"),       0.5),
    ("rvol_tod",             ("chart_state", "rvol_tod"),             1.0),
    ("realized_vol_ann",     ("chart_state", "realized_vol_ann"),     0.15),
    ("range_vs_atr",         ("chart_state", "range_vs_atr"),         0.5),
    ("gap_frac",             ("chart_state", "gap_frac"),             0.01),
    ("excess_market_60m",    ("relative_strength", "excess_market_60m"), 0.005),
    ("excess_sector_60m",    ("relative_strength", "excess_sector_60m"), 0.005),
    ("cross_sectional_pct",  ("relative_strength", "cross_sectional_pct"), 0.3),
    ("market_day_return",    ("market_state", "day_return"),          0.008),
)
MAX_MISSING_FEATURES = 4          # more missing than this = not comparable
SUPPORT_MIN_N = 20                # below this, support is LOW at best
SUPPORT_MIN_SYMBOLS = 5           # one stock cannot dominate support
SUPPORT_DISTANCE_HIGH = 1.0       # mean per-feature scaled distance bar


@dataclass(frozen=True)
class AnalogQuery:
    as_of: str                    # tz-aware ISO; rows >= as_of are invisible
    security_id: str
    horizon_minutes: int
    playbook_id: str | None
    candidate_record: dict        # decision-record shape (chart_state, rs, market)


@dataclass(frozen=True)
class AnalogResult:
    status: str                   # OK | ANALOG_SUPPORT_LOW | NO_VALID_ANALOGS
    evidence_class: str
    n_raw: int
    n_effective: int
    n_symbols: int
    neighbour_ids: tuple
    distances: tuple              # per selected neighbour, scaled
    mean_distance: float | None
    coverage: dict                # features present/missing
    forward_returns: tuple
    p_positive: float | None
    median_return: float | None
    q10: float | None
    q90: float | None
    mae: tuple
    mfe: tuple
    target_before_stop_rate: float | None
    regime_mix: dict
    uncertainty: str              # HIGH/MEDIUM/LOW (support-based, honest)
    provenance: dict
    survivorship_limitation: bool
    calibration_status: str = "UNCALIBRATED"
    engine_version: str = field(default=ANALOG_ENGINE_VERSION)


def _get(record: dict, path: tuple):
    cur = record
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def feature_vector(record: dict) -> tuple:
    """(values, missing_names) under the frozen schema."""
    vals, missing = [], []
    for name, path, scale in ANALOG_FEATURE_SCHEMA_V1:
        v = _get(record, path)
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            vals.append(np.nan)
            missing.append(name)
        else:
            vals.append(float(v) / scale)
        del name
    return np.array(vals), tuple(missing)


def _distance(q: np.ndarray, x: np.ndarray) -> float | None:
    """Mean absolute scaled difference over MUTUALLY PRESENT features;
    None when overlap is too thin to mean anything."""
    both = np.isfinite(q) & np.isfinite(x)
    if both.sum() < len(q) - MAX_MISSING_FEATURES:
        return None
    return float(np.mean(np.abs(q[both] - x[both])))


def retrieve(query: AnalogQuery, memory_rows: list, *,
             evidence_class: EvidenceClass, k: int = 50) -> AnalogResult:
    """memory_rows: [{candidate: decision-shaped dict, outcome: realization
    dict | None, resolved_at: iso, session_date, symbol, decision_id,
    evidence_class: str, regime: str|None}].

    LAB-08: "ALL rows must share evidence_class" used to be a sentence
    addressed to the caller. It is now VERIFIED here, before a single
    neighbour is chosen or a single field is stamped -- because this
    function's output carries an evidence_class label that downstream
    consumers trust, and a label the engine never checked is a laundering
    machine, not a guarantee."""
    from apex.hunter.evidence import require_declared_class
    require_declared_class(memory_rows, evidence_class,
                           where="analog.retrieve")
    as_of = pd.Timestamp(query.as_of)
    if as_of.tzinfo is None:
        raise ValueError("as_of must be tz-aware")
    qv, q_missing = feature_vector(query.candidate_record)
    prov = {"engine": ANALOG_ENGINE_VERSION, "as_of": str(as_of),
            "schema": "ANALOG_FEATURE_SCHEMA_V1", "k": k,
            "memory_rows_offered": len(memory_rows)}
    limitation = evidence_class is EvidenceClass.EODHD_HISTORICAL_EXPLORATORY

    def empty(status: str) -> AnalogResult:
        return AnalogResult(
            status=status, evidence_class=evidence_class.value,
            n_raw=0, n_effective=0, n_symbols=0,
            neighbour_ids=(), distances=(),
            mean_distance=None,
            coverage={"query_missing": list(q_missing)},
            forward_returns=(), p_positive=None, median_return=None,
            q10=None, q90=None, mae=(), mfe=(),
            target_before_stop_rate=None, regime_mix={},
            uncertainty="HIGH", provenance=prov,
            survivorship_limitation=limitation)

    if len(q_missing) > MAX_MISSING_FEATURES:
        return empty("NO_VALID_ANALOGS")

    # STRUCTURAL TIME FIREWALL: candidate formed before as_of AND outcome
    # resolved before as_of. Applied before any distance computation.
    visible = []
    for row in memory_rows:
        t_formed = pd.Timestamp(row["candidate"].get("t_utc"))
        resolved = row.get("resolved_at")
        if t_formed >= as_of:
            continue
        if resolved is None or pd.Timestamp(resolved) >= as_of:
            continue
        visible.append(row)
    if not visible:
        return empty("NO_VALID_ANALOGS")

    # NEIGHBOUR SELECTION FROM STATE ONLY — outcomes not touched here.
    scored = []
    for row in visible:
        xv, _ = feature_vector(row["candidate"])
        d = _distance(qv, xv)
        if d is not None:
            scored.append((d, row))
    if not scored:
        return empty("NO_VALID_ANALOGS")
    scored.sort(key=lambda p: p[0])
    chosen = scored[:k]

    # outcomes are read ONLY AFTER neighbour identities are frozen
    h = query.horizon_minutes
    rets, maes, mfes, tbs, regimes, ids, dists = [], [], [], [], [], [], []
    sessions, symbols = set(), set()
    for d, row in chosen:
        ids.append(row.get("decision_id", "?"))
        dists.append(round(d, 4))
        sessions.add(row.get("session_date"))
        symbols.add(row.get("symbol"))
        regimes.append(row.get("regime") or "UNKNOWN")
        o = row.get("outcome") or {}
        r = o.get(f"ret_{h}m")
        if r is not None:
            rets.append(float(r))
        if o.get(f"mae_{h}m") is not None:
            maes.append(float(o[f"mae_{h}m"]))
        if o.get(f"mfe_{h}m") is not None:
            mfes.append(float(o[f"mfe_{h}m"]))
        if o.get("target_before_stop") is not None:
            tbs.append(bool(o["target_before_stop"]))

    n_raw = len(rets)
    n_eff = min(len(sessions), n_raw)
    mean_d = float(np.mean(dists)) if dists else None
    if n_raw == 0:
        return empty("NO_VALID_ANALOGS")
    # F-02: support quality requires DIVERSITY — one symbol (or a handful)
    # repeating across sessions is one phenomenon observed often, not broad
    # support, and a wrongly-confident OK would SUPPRESS capital caution
    low_support = (n_eff < SUPPORT_MIN_N
                   or len(symbols) < SUPPORT_MIN_SYMBOLS
                   or (mean_d is not None and mean_d > SUPPORT_DISTANCE_HIGH))
    status = "ANALOG_SUPPORT_LOW" if low_support else "OK"
    return AnalogResult(
        status=status, evidence_class=evidence_class.value,
        n_raw=n_raw, n_effective=n_eff, n_symbols=len(symbols),
        neighbour_ids=tuple(ids), distances=tuple(dists),
        mean_distance=round(mean_d, 4) if mean_d is not None else None,
        coverage={"query_missing": list(q_missing),
                  "visible_rows": len(visible), "scored_rows": len(scored)},
        forward_returns=tuple(round(r, 5) for r in rets),
        p_positive=round(float(np.mean([r > 0 for r in rets])), 3),
        median_return=round(float(np.median(rets)), 5),
        q10=round(float(np.quantile(rets, 0.10)), 5),
        q90=round(float(np.quantile(rets, 0.90)), 5),
        mae=tuple(round(x, 5) for x in maes),
        mfe=tuple(round(x, 5) for x in mfes),
        target_before_stop_rate=(round(float(np.mean(tbs)), 3)
                                 if tbs else None),
        regime_mix={r: regimes.count(r) for r in sorted(set(regimes))},
        uncertainty="HIGH" if low_support else "MEDIUM",
        provenance=prov, survivorship_limitation=limitation)
