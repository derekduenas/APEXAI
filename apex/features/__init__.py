"""Feature assembly.

Each category is an independent module, unit-tested against hand-computed
values. This module only assembles them and stamps provenance.

Ordering constraint, forced rather than chosen: F1's universe-mean benchmark and
F4a's sector benchmark are computed against PRE-completeness eligibility (the
section 3 filters alone). Using post-completeness eligibility would be circular --
whether F1 is computable cannot be an input to F1's own benchmark. Feature
completeness is folded into eligibility afterwards, by
`universe.apply_feature_completeness`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from apex.config import Config
from apex.contracts import FEATURE_COMPONENTS, FeaturePanel, Panel
from apex.features import f1_momentum, f2_trend, f3_volatility, f4_relative_strength

_MODULES = (f1_momentum, f2_trend, f3_volatility, f4_relative_strength)


def _max_input_offsets(config: Config) -> dict[str, int]:
    """Trading days back from T of the LATEST input each component touches.

    F1 and F4 skip the most recent 5 days, so their latest input is dated T-5.
    F2 and F3 both read the close of day T itself, so their latest input is T.

    Stage 3 replaces this declared table with provenance measured from the
    actual data access, and its mutation test -- shift one feature forward by a
    day, confirm the audit catches it and that IC visibly jumps -- is what
    proves the measurement works. A declared table cannot catch a bug in the
    shift that produced it; it is a scaffold for the auditor, not the auditor.
    """
    f1_skip = int(config.get("features.f1.skip_days"))
    f4_skip = int(config.get("features.f4.skip_days"))
    return {
        "f1_mom_126": f1_skip,
        "f1_mom_63": f1_skip,
        "f2_close_over_sma200": 0,
        "f2_frac_above_sma50": 0,
        "f3_vol_ratio": 0,
        "f3_atr_over_close": 0,
        "f4_vs_sector": f4_skip,
        "f4_vs_market": f4_skip,
    }


def compute_features(panel: Panel, eligible: pd.DataFrame, config: Config) -> FeaturePanel:
    components: dict[str, pd.DataFrame] = {}
    for module in _MODULES:
        components.update(module.compute(panel, eligible, config))

    missing = [c for c in FEATURE_COMPONENTS if c not in components]
    if missing:
        raise ValueError(f"feature assembly produced no values for {missing}")

    offsets = _max_input_offsets(config)
    present = pd.DataFrame(False, index=panel.dates, columns=panel.securities)
    for frame in components.values():
        present |= frame.notna()

    latest_offset = min(offsets[name] for name in components)
    positions = np.arange(len(panel.dates)) - latest_offset
    positions = np.clip(positions, 0, len(panel.dates) - 1)
    stamp = panel.dates[positions]

    max_input_date = pd.DataFrame(
        np.repeat(stamp.to_numpy()[:, None], len(panel.securities), axis=1),
        index=panel.dates,
        columns=panel.securities,
    ).where(present)

    return FeaturePanel(
        dates=panel.dates,
        securities=panel.securities,
        components=components,
        max_input_date=max_input_date,
    )
