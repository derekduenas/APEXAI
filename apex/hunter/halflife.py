"""Alpha half-life estimation + intelligence routing (blueprint principle:
match the intelligence APEX buys to how long the information advantage
plausibly survives).

The estimator reads ONLY realized forward outcomes for a playbook
(15/30/60/90m EV curve) and reports the first horizon at which EV decays
below half its peak — a deliberately CRUDE, declared rule. Below the
evidence floor the answer is NOT_YET_ESTIMABLE, which is the correct
Monday output and routes to the conservative default.

Routing is SCHEDULING, never sizing: a short half-life buys LESS
LLM deliberation (the assassin still runs; the slow committee is skipped
— you cannot spend four minutes deliberating a 24-minute edge), a long
half-life permits the deep desk. Routing can only reduce intelligence
spend relative to the default; it can never make capital more
aggressive, relax a gate, or touch a stop.
"""

from __future__ import annotations

import numpy as np

from apex.hunter.contracts import HORIZONS_MINUTES

HALFLIFE_VERSION = "hunter_halflife_v1"
MIN_EFFECTIVE_TO_ESTIMATE = 10        # sessions with scored outcomes


def estimate(playbook_id: str, scored_rows: list) -> dict:
    """scored_rows: merged decision+realization dicts for THIS playbook
    (forward-eligible, resolvable). Typed refusal below the floor."""
    sessions = {r.get("session_date") for r in scored_rows}
    if len(sessions) < MIN_EFFECTIVE_TO_ESTIMATE:
        return {"status": "NOT_YET_ESTIMABLE", "playbook_id": playbook_id,
                "n_sessions": len(sessions),
                "floor": MIN_EFFECTIVE_TO_ESTIMATE,
                "version": HALFLIFE_VERSION}
    curve = {}
    for h in HORIZONS_MINUTES:
        rets = [r[f"ret_{h}m"] for r in scored_rows
                if r.get(f"ret_{h}m") is not None]
        if rets:
            curve[h] = float(np.mean(rets))
    if not curve or max(curve.values()) <= 0:
        return {"status": "NO_POSITIVE_EDGE_MEASURED",
                "playbook_id": playbook_id,
                "ev_curve": {f"{h}m": round(v, 5)
                             for h, v in curve.items()},
                "version": HALFLIFE_VERSION}
    peak = max(curve.values())
    surviving = [h for h in sorted(curve) if curve[h] >= 0.5 * peak]
    half = surviving[-1] if surviving else min(curve)
    return {"status": "ESTIMATED_CRUDE", "playbook_id": playbook_id,
            "ev_curve": {f"{h}m": round(v, 5) for h, v in curve.items()},
            "half_life_minutes": half,
            "decay_rule": ("last horizon with EV >= half of peak "
                           "(declared crude)"),
            "n_sessions": len(sessions), "version": HALFLIFE_VERSION}


def route_intelligence(halflife: dict) -> dict:
    """half-life -> how much reasoning to buy. Conservative default when
    unknown. FAST_ONLY skips the slow committee, never the assassin."""
    status = halflife.get("status")
    if status != "ESTIMATED_CRUDE":
        return {"routing": "STANDARD_DEFAULT", "allow_deep_swarm": True,
                "reason": f"half-life {status}: conservative default"}
    hl = halflife.get("half_life_minutes", 90)
    if hl < 30:
        return {"routing": "FAST_ONLY", "allow_deep_swarm": False,
                "reason": f"~{hl}m half-life: the committee is slower than "
                          f"the edge; assassin only"}
    if hl < 90:
        return {"routing": "STANDARD", "allow_deep_swarm": True,
                "reason": f"~{hl}m half-life: full desk fits the horizon"}
    return {"routing": "DEEP_ELIGIBLE", "allow_deep_swarm": True,
            "reason": f"~{hl}m+ half-life: deep research worthwhile"}
