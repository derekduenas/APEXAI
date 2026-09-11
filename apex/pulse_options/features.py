"""ONE feature implementation for replay and live inference (M2).

The frozen artifact's recipe (apex.world_model.exp001b.bars.observable_rows):
    ret_1 = log(c[t] / c[t-1m]);  ret_5 = log(c[t] / c[t-5m]);
    rv_30 = RMS of the 30 one-minute log returns in (t-30m, t]
computed from bars at EXACTLY t - k*60 s, k = 0..30; any missing minute
refuses the row; nothing is filled. Here the same numbers come from the
snapshot's ret_1 / ret_5 / rv_30 fields, which `rolling_windows` computes with
that exact definition, so replay (historical bars) and live (ingested bars)
share one code path. Parity with observable_rows is a tested property."""
from __future__ import annotations

from .snapshot import usable_value

FEATURE_ORDER = ("ret_1", "ret_5", "rv_30")
FEATURE_SET = "EXP001B_FEATURES_V1: [ret_1, ret_5, rv_30] from exact-minute completed bars, 30-bar warm-up"


class FeaturesRefused(ValueError):
    pass


def feature_vector(snapshot: dict) -> dict:
    """{"ret_1","ret_5","rv_30"} from a snapshot, or refuse with the field's reason."""
    out = {}
    for name in FEATURE_ORDER:
        f = snapshot["fields"].get(name)
        if not f or f.get("quality") != "VALID":
            raise FeaturesRefused("FEATURE_UNAVAILABLE: %s is %s (%s)" % (name, (f or {}).get("quality"), (f or {}).get("note")))
        out[name] = f["value"]
    if not out["rv_30"] > 0:
        raise FeaturesRefused("ZERO_RV_30")
    return out


def features_from_bars(bars: list, *, as_of: float) -> dict:
    """The same recipe applied directly to a bar list (used by the parity test and by replay)."""
    from .ingest import rolling_windows
    win = rolling_windows([b for b in bars if b["available"] <= as_of], as_of=as_of, lengths=(1, 5, 30))
    if any(win[L] is None for L in (1, 5, 30)):
        raise FeaturesRefused("MISSING_FEATURE_BARS")
    return {"ret_1": win[1]["ret"], "ret_5": win[5]["ret"], "rv_30": win[30]["rv"]}
