"""Prediction producers and the three baselines (directive v2.0 section 1.5).

Every producer is a pure function from declared inputs to Prediction objects.
The FROZEN monotone mapping from rank to probability (declared here, never
fitted) keeps mechanical producers honest: their calibration is an empirical
question the harness answers, not a curve tuned to please it.

THE BLIND TWIN: `blind_producer` takes NO market data by construction -- its
signature has no argument that could carry any, and its inputs_hash is the
hash of an empty context. If a rank producer's Brier score does not beat its
blind twin, its confidence is fluency, not information.
"""

from __future__ import annotations

import pandas as pd

from apex.reality.harness import Prediction, make_prediction

HORIZON = 20                 # trading days, matches the research grid
TIER = 2                     # mechanical signal-derived claims
RANK_SLOPE = 0.2             # p = 0.5 + RANK_SLOPE * (pct - 0.5), in (0.4, 0.6)
BASE_RATE_UP = 0.53          # unconditional 20-day equity direction base rate
MOMENTUM_P = 0.60            # naive rule: p(up) when trailing 60d return > 0


def _relative(trade_date, created_at, subject, peers, probability, producer,
              inputs, rationale) -> Prediction:
    return make_prediction(
        trade_date=trade_date, horizon_days=HORIZON, subject=subject,
        claim_type="relative", probability=probability, epistemic_tier=TIER,
        producer=producer, inputs=inputs, rationale=rationale,
        resolution_rule="relative_vs_peer_median",
        resolution_params={"peers": list(peers)}, created_at=created_at)


def rank_producer(name: str, trade_date: str, created_at: str,
                  rank_pct: pd.Series, subjects, peers) -> list[Prediction]:
    """P(subject beats peer median) from a cross-sectional rank percentile,
    through the FROZEN mapping. rank_pct in [0,1], higher = better."""
    out = []
    for s in subjects:
        pct = float(rank_pct[s])
        p = 0.5 + RANK_SLOPE * (pct - 0.5)
        out.append(_relative(
            trade_date, created_at, s, peers, p, name,
            inputs={"rank_pct": pct, "trade_date": trade_date},
            rationale={"mapping": "0.5+0.2*(pct-0.5)", "rank_pct": round(pct, 4)}))
    return out


def blind_producer(name: str, trade_date: str, created_at: str,
                   subjects, peers) -> list[Prediction]:
    """The stripped-context twin. NO market data can reach it: the signature
    carries none, and every claim is the ignorance prior 0.5."""
    return [_relative(trade_date, created_at, s, peers, 0.5, name,
                      inputs={},        # the hash of nothing, provably
                      rationale={"mapping": "blind ignorance prior"})
            for s in subjects]


def momentum_rank_producer(trade_date: str, created_at: str,
                           trailing_60d: pd.Series, subjects, peers) -> list[Prediction]:
    """Baseline 2 in the form that BITES: naive momentum as a cross-sectional
    rank on the SAME subjects and peer set as the signal producers, through
    the SAME frozen mapping. gp_rank must beat THIS, not just the coin flip --
    profitability ranks are momentum-flavored, and this baseline is how that
    flavor stops being creditable as signal."""
    pct = trailing_60d.rank(pct=True)
    out = []
    for s in subjects:
        p = 0.5 + RANK_SLOPE * (float(pct[s]) - 0.5)
        out.append(_relative(
            trade_date, created_at, s, peers, p, "baseline_momentum_rank",
            inputs={"trailing_60d_return": float(trailing_60d[s]),
                    "rank_pct": float(pct[s]), "trade_date": trade_date},
            rationale={"rule": "naive momentum rank, frozen mapping"}))
    return out


def base_rate_producer(trade_date: str, created_at: str, subject: str) -> Prediction:
    return make_prediction(
        trade_date=trade_date, horizon_days=HORIZON, subject=subject,
        claim_type="direction", probability=BASE_RATE_UP, epistemic_tier=1,
        producer="baseline_base_rate", inputs={"trade_date": trade_date},
        rationale={"rule": "unconditional base rate"},
        resolution_rule="direction_up", resolution_params={},
        created_at=created_at)


def momentum_producer(trade_date: str, created_at: str, subject: str,
                      trailing_60d_return: float) -> Prediction:
    up = trailing_60d_return > 0
    return make_prediction(
        trade_date=trade_date, horizon_days=HORIZON, subject=subject,
        claim_type="direction", probability=MOMENTUM_P if up else 1 - MOMENTUM_P,
        epistemic_tier=1, producer="baseline_momentum",
        inputs={"trailing_60d_return": float(trailing_60d_return)},
        rationale={"rule": "naive momentum", "trailing_up": bool(up)},
        resolution_rule="direction_up", resolution_params={},
        created_at=created_at)
