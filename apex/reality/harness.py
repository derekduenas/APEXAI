"""Prediction harness: schema, chained store, resolution, scoring.

INVARIANTS (directive v2.0 section 1.3 -- violating any makes the record
worthless):
  * predictions are append-only and hash-chained, with a head anchor so
    truncation is detectable;
  * the resolution rule and its params are frozen AT CREATION;
  * an unresolved prediction past its resolution date SCORES AS A FAILURE --
    silence is not an escape hatch;
  * every prediction carries the hash of the inputs that produced it;
  * probability is strictly inside (0, 1) -- certainty is never warranted and
    log loss must always be defined.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


class RealityError(ValueError):
    """A prediction-harness invariant was violated."""


def canonical_hash(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


CLAIM_TYPES = ("direction", "relative", "volatility", "range")


@dataclass(frozen=True)
class Prediction:
    """One falsifiable claim. Frozen: no field can be edited after creation."""

    prediction_id: str
    created_at: str            # utc iso, immutable
    trade_date: str            # last trading day whose data the producer saw
    horizon_days: int          # TRADING days until resolution
    subject: str               # security_id | index id
    claim_type: str
    probability: float
    epistemic_tier: int
    producer: str              # agent_id + model_version (+ prompt hash for LLMs)
    inputs_hash: str
    rationale: dict            # structured fields, not free prose
    resolution_rule: str       # name in RESOLUTION_RULES, frozen at creation
    resolution_params: dict    # frozen at creation


def make_prediction(*, trade_date: str, horizon_days: int, subject: str,
                    claim_type: str, probability: float, epistemic_tier: int,
                    producer: str, inputs: dict, rationale: dict,
                    resolution_rule: str, resolution_params: dict,
                    created_at: str) -> Prediction:
    if not (0.0 < probability < 1.0):
        raise RealityError(
            f"probability must be strictly inside (0,1); got {probability}. "
            f"Certainty is never warranted and log loss must stay defined.")
    if claim_type not in CLAIM_TYPES:
        raise RealityError(f"unknown claim_type {claim_type!r}")
    if resolution_rule not in RESOLUTION_RULES:
        raise RealityError(f"unknown resolution_rule {resolution_rule!r}")
    if horizon_days < 1:
        raise RealityError("horizon must be at least one trading day")
    return Prediction(
        prediction_id=str(uuid.uuid4()), created_at=created_at,
        trade_date=trade_date, horizon_days=int(horizon_days), subject=subject,
        claim_type=claim_type, probability=float(probability),
        epistemic_tier=int(epistemic_tier), producer=producer,
        inputs_hash=canonical_hash(inputs), rationale=dict(rationale),
        resolution_rule=resolution_rule, resolution_params=dict(resolution_params),
    )


# ---------------------------------------------------------------------------
# the chained store
# ---------------------------------------------------------------------------

class PredictionLedger:
    """Append-only, hash-chained, head-anchored. Mirrors the research ledger's
    discipline: an edited line breaks the chain; a truncated file disagrees
    with the anchor."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.anchor = self.path.with_suffix(".anchor")

    def _lines(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().strip().splitlines()]

    def append(self, record: dict) -> dict:
        lines = self._lines()
        prev = lines[-1]["entry_hash"] if lines else "GENESIS"
        body = {**record, "prev_hash": prev}
        body["entry_hash"] = canonical_hash(body)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(body, sort_keys=True, default=str) + "\n")
        self.anchor.write_text(body["entry_hash"] + "\n")
        return body

    def append_prediction(self, pred: Prediction) -> dict:
        return self.append({"kind": "prediction", **asdict(pred)})

    def append_resolution(self, prediction_id: str, outcome: float,
                          resolved_at: str) -> dict:
        return self.append({"kind": "resolution", "prediction_id": prediction_id,
                            "outcome": float(outcome), "resolved_at": resolved_at})

    def verify(self) -> int:
        """Raises on any tamper or truncation; returns the entry count."""
        lines = self._lines()
        prev = "GENESIS"
        for i, line in enumerate(lines):
            body = {k: v for k, v in line.items() if k != "entry_hash"}
            if line.get("prev_hash") != prev:
                raise RealityError(f"chain broken at entry {i}")
            if canonical_hash(body) != line["entry_hash"]:
                raise RealityError(f"entry {i} was modified after being written")
            prev = line["entry_hash"]
        if self.anchor.exists():
            anchored = self.anchor.read_text().strip()
            if lines and lines[-1]["entry_hash"] != anchored:
                raise RealityError(
                    "head anchor disagrees with the file: TRUNCATION or rollback")
            if not lines and anchored:
                raise RealityError("anchor exists but the file is empty: TRUNCATION")
        return len(lines)

    def predictions(self) -> list[dict]:
        return [l for l in self._lines() if l["kind"] == "prediction"]

    def resolutions(self) -> dict:
        return {l["prediction_id"]: l for l in self._lines()
                if l["kind"] == "resolution"}


# ---------------------------------------------------------------------------
# resolution rules -- deterministic, chosen at creation, never at resolution
# ---------------------------------------------------------------------------

def _window(prices: pd.DataFrame, subject: str, trade_date: str, horizon: int):
    """The horizon window: trade_date (exclusive base) to +horizon trading days.
    Returns None when the data does not yet reach the resolution date."""
    if subject not in prices.columns:
        return None
    s = prices[subject].dropna()
    days = s.index
    pos = days.searchsorted(pd.Timestamp(trade_date), side="right") - 1
    if pos < 0 or days[pos] != pd.Timestamp(trade_date):
        return None
    if pos + horizon >= len(days):
        return None                       # not yet resolvable
    return s.iloc[pos: pos + horizon + 1]


def resolve_direction(prices, pred) -> float | None:
    w = _window(prices, pred["subject"], pred["trade_date"], pred["horizon_days"])
    if w is None:
        return None
    return 1.0 if float(w.iloc[-1] / w.iloc[0] - 1) > 0 else 0.0


def resolve_relative(prices, pred) -> float | None:
    """P(subject return > cross-sectional median of the recorded peer set)."""
    peers = pred["resolution_params"]["peers"]
    rets = []
    for p in [pred["subject"], *peers]:
        w = _window(prices, p, pred["trade_date"], pred["horizon_days"])
        rets.append(None if w is None else float(w.iloc[-1] / w.iloc[0] - 1))
    if rets[0] is None:
        return None
    peer_rets = [r for r in rets[1:] if r is not None]
    if len(peer_rets) < max(3, len(peers) // 2):
        return None                       # peer set not yet resolvable
    return 1.0 if rets[0] > float(np.median(peer_rets)) else 0.0


def resolve_volatility(prices, pred) -> float | None:
    w = _window(prices, pred["subject"], pred["trade_date"], pred["horizon_days"])
    if w is None:
        return None
    realized = float(w.pct_change().dropna().std() * np.sqrt(252))
    return 1.0 if realized > float(pred["resolution_params"]["threshold"]) else 0.0


def resolve_range(prices, pred) -> float | None:
    w = _window(prices, pred["subject"], pred["trade_date"], pred["horizon_days"])
    if w is None:
        return None
    lo, hi = pred["resolution_params"]["low"], pred["resolution_params"]["high"]
    return 1.0 if float(lo) <= float(w.iloc[-1]) <= float(hi) else 0.0


RESOLUTION_RULES = {
    "direction_up": resolve_direction,
    "relative_vs_peer_median": resolve_relative,
    "realized_vol_above": resolve_volatility,
    "close_in_range": resolve_range,
}


def resolve(prices: pd.DataFrame, pred: dict) -> float | None:
    """None = not yet resolvable. The rule comes from the RECORD, frozen at
    creation -- there is no argument for choosing one here, by design."""
    return RESOLUTION_RULES[pred["resolution_rule"]](prices, pred)


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def scoreable(preds: list[dict], resolutions: dict, data_through: str) -> list[dict]:
    """Pair predictions with outcomes. A prediction whose resolution date has
    passed (trade_date + ~1.6x horizon in calendar days, conservative) without
    a recorded resolution SCORES AS A FAILURE: outcome is set to whichever
    value the stated probability finds most painful. Silence is not neutral."""
    rows = []
    for p in preds:
        r = resolutions.get(p["prediction_id"])
        if r is not None:
            rows.append({**p, "outcome": r["outcome"], "penalised": False})
            continue
        due = (pd.Timestamp(p["trade_date"])
               + pd.Timedelta(days=int(p["horizon_days"] * 1.6) + 5))
        if due <= pd.Timestamp(data_through):
            worst = 0.0 if p["probability"] >= 0.5 else 1.0
            rows.append({**p, "outcome": worst, "penalised": True})
    return rows


def brier(rows) -> float:
    return float(np.mean([(r["probability"] - r["outcome"]) ** 2 for r in rows]))


def log_loss(rows) -> float:
    return float(-np.mean([
        r["outcome"] * np.log(r["probability"])
        + (1 - r["outcome"]) * np.log(1 - r["probability"]) for r in rows]))


def calibration_curve(rows, n_buckets: int = 10) -> list[dict]:
    """Stated probability vs realized frequency, per bucket. THE number."""
    out = []
    edges = np.linspace(0, 1, n_buckets + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = [r for r in rows if lo <= r["probability"] < hi] if hi < 1 else \
              [r for r in rows if lo <= r["probability"] <= hi]
        if sel:
            out.append({"bucket": f"[{lo:.1f},{hi:.1f})", "n": len(sel),
                        "stated_mean": round(float(np.mean(
                            [r["probability"] for r in sel])), 4),
                        "realized_freq": round(float(np.mean(
                            [r["outcome"] for r in sel])), 4)})
    return out


def reliability_resolution(rows, n_buckets: int = 10) -> dict:
    """Murphy decomposition. Reliability: are the probabilities honest (lower
    is better)? Resolution: are they informative (higher is better)? A
    producer saying the base rate to everything is perfectly reliable and
    perfectly useless -- both numbers are required."""
    n = len(rows)
    base = float(np.mean([r["outcome"] for r in rows]))
    rel = res = 0.0
    for b in calibration_curve(rows, n_buckets):
        rel += b["n"] / n * (b["stated_mean"] - b["realized_freq"]) ** 2
        res += b["n"] / n * (b["realized_freq"] - base) ** 2
    return {"reliability": round(rel, 6), "resolution": round(res, 6),
            "base_rate": round(base, 4), "uncertainty": round(base * (1 - base), 6),
            "n": n}


def score_by_producer(preds, resolutions, data_through) -> dict:
    rows = scoreable(preds, resolutions, data_through)
    report = {}
    for producer in sorted({r["producer"] for r in rows}):
        sel = [r for r in rows if r["producer"] == producer]
        report[producer] = {
            "n_scored": len(sel),
            "n_penalised_unresolved": sum(1 for r in sel if r["penalised"]),
            "brier": round(brier(sel), 6),
            "log_loss": round(log_loss(sel), 6),
            **reliability_resolution(sel),
            "calibration": calibration_curve(sel),
        }
    return report
