"""MECHANISM INDEPENDENCE -- five views of price are not five witnesses.

THE FAILURE THIS PREVENTS. A pattern that fires on "curve positive AND
momentum positive AND relative strength positive AND VWAP reclaimed AND
opening range broken" looks like five confirmations. It is ONE
observation -- price went up -- restated five times. Confidence that
rises with the number of restatements is how a system convinces itself.

So every component declares its MECHANISM GROUP, and pattern strength is
bounded by the count of DISTINCT groups, never by the count of
components.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from apex.pattern_observatory import OBSERVATORY_POWER

GROUPS = ("PRICE", "VOLUME", "VOLATILITY", "POSITIONING", "OPTIONS",
          "BREADTH", "SECTORS", "CROSS_ASSET", "EVENTS",
          "CRYPTO_DERIVATIVES", "SYSTEM_STATE")

# Every component the Observatory can observe, mapped to the mechanism it
# actually derives from. Where a component is a transform of price it is
# PRICE, however sophisticated the transform.
COMPONENT_GROUP = {
    "curve_positive": "PRICE", "curve_negative": "PRICE",
    "curve_state_change": "PRICE", "direction_quality": "PRICE",
    "price_refusal": "PRICE", "obs_return_from_open": "PRICE",
    "obs_opening_range_break": "PRICE", "propagation_lead_lag": "PRICE",
    "expectation_violation": "PRICE",
    "obs_vwap_reclaim": "VOLUME", "obs_rvol_elevated": "VOLUME",
    "volume_divergence": "VOLUME",
    "vol_repricing": "VOLATILITY", "skew_change": "VOLATILITY",
    "term_structure": "VOLATILITY",
    "crowded_short": "POSITIONING", "crowded_long": "POSITIONING",
    "positioning_extreme": "POSITIONING", "forced_flow": "POSITIONING",
    "options_surface_state": "OPTIONS", "options_dislocation": "OPTIONS",
    "breadth_deteriorating": "BREADTH", "breadth_improving": "BREADTH",
    "breadth_divergence": "BREADTH",
    "sector_rotation": "SECTORS", "sector_leadership_change": "SECTORS",
    "sector_dispersion": "SECTORS",
    "cross_asset_risk_off": "CROSS_ASSET",
    "edgar_event": "EVENTS", "catalyst": "EVENTS",
    "perp_funding": "CRYPTO_DERIVATIVES", "perp_oi": "CRYPTO_DERIVATIVES",
    "perp_liquidation": "CRYPTO_DERIVATIVES",
    "observation_integrity": "SYSTEM_STATE",
    "system_cognition": "SYSTEM_STATE",
    "fastwatch_density": "PRICE",
}


def group_of(component: str) -> str:
    return COMPONENT_GROUP.get(component, "PRICE")


def analyse(components: list) -> dict:
    """Independent mechanism count and the duplication behind it."""
    by_group: dict = {}
    for c in components:
        by_group.setdefault(group_of(c), []).append(c)
    duplicated = {g: v for g, v in by_group.items() if len(v) > 1}
    n_ind = len(by_group)
    return {
        "kind": "mechanism_independence",
        "n_components": len(components),
        "independent_mechanism_count": n_ind,
        "groups": {g: sorted(v) for g, v in sorted(by_group.items())},
        "duplicated_groups": {g: sorted(v) for g, v in sorted(duplicated.items())},
        "inflation_ratio": (round(len(components) / n_ind, 3) if n_ind else None),
        "law": "pattern strength is bounded by DISTINCT mechanism groups, "
               "never by component count",
        "decision_power": OBSERVATORY_POWER,
    }


# ---------------------------------------------------------------------
# MECHANISM FUSION -- combining evidence WITHOUT double counting.
# ---------------------------------------------------------------------
# Five price indicators are one witness. Five genuinely different
# mechanisms -- price deterioration, breadth collapse, crowded leveraged
# funds, skew repricing, credit weakening -- are five witnesses, and that
# is a categorically different claim.
#
# Fusion strength therefore counts DISTINCT GROUPS and applies a
# DIMINISHING contribution within each group: the second price indicator
# adds a little, the fifth adds almost nothing. There is no configuration
# in which duplicated evidence sums linearly.

# Declared weights. Groups that are more independent of price get more
# weight, because they carry information price alone cannot.
GROUP_WEIGHT = {
    "PRICE": 1.0, "VOLUME": 0.9, "BREADTH": 1.0, "SECTORS": 1.0,
    "VOLATILITY": 1.1, "OPTIONS": 1.1, "POSITIONING": 1.3,
    "CROSS_ASSET": 1.2, "EVENTS": 1.2, "CRYPTO_DERIVATIVES": 1.2,
    "SYSTEM_STATE": 0.3,        # tells us about APEX, not the market
}
WITHIN_GROUP_DECAY = 0.35       # 2nd member of a group adds 35%, 3rd 12%...


def fuse(components: list, *, quality_by_component: dict | None = None) -> dict:
    """Fusion strength, explicitly NOT a probability and NOT a score to
    rank trades by. It answers one question: how many genuinely different
    things is this claim resting on?"""
    q = quality_by_component or {}
    penalty = {"VALID": 1.0, "LIMITED": 0.8, "DEGRADED": 0.5,
               "INVALID": 0.0, "UNKNOWN": 0.0}
    by_group: dict = {}
    for c in components:
        by_group.setdefault(group_of(c), []).append(c)

    total, detail = 0.0, {}
    for g, members in sorted(by_group.items()):
        w = GROUP_WEIGHT.get(g, 1.0)
        contrib = 0.0
        for i, m in enumerate(sorted(members)):
            qm = penalty.get(q.get(m, "UNKNOWN"), 0.0) if q else 1.0
            contrib += w * (WITHIN_GROUP_DECAY ** i) * qm
        detail[g] = {"members": sorted(members), "weight": w,
                     "contribution": round(contrib, 4)}
        total += contrib

    n_ind = len(by_group)
    return {
        "kind": "mechanism_fusion",
        "independent_mechanism_count": n_ind,
        "n_components": len(components),
        "fusion_strength": round(total, 4),
        "naive_count_would_be": len(components),
        "by_group": detail,
        "dominant_group": (max(detail, key=lambda g: detail[g]["contribution"])
                           if detail else None),
        "single_mechanism": n_ind <= 1,
        "law": "within-group evidence decays geometrically; duplicated "
               "indicators can never sum linearly into confidence",
        "is_probability": False,
        "decision_power": OBSERVATORY_POWER,
    }
