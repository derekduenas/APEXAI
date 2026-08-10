"""STAGE 3 -- measured enforcement of the protocol section 4 timing firewall.

    "Any calculation that references a price at or after T+1 in the feature set
     is a lookahead violation and voids the run."

`features._max_input_offsets` DECLARES how far back each component's latest
input sits. A declaration cannot catch a bug in the code it describes: if a
feature silently began reading T+1, the table would go on claiming T-5. This
module measures the property instead, by black-box perturbation:

    Destroy everything strictly after T. Recompute. Anything the pipeline knew
    at T that changed was read from the future.

No instrumentation of individual array operations is required, the test covers
universe eligibility and cross-sectional scoring as well as features, and it
cannot be satisfied by editing a comment.

TWO MODES, because they fail differently:

  PERTURB   Overwrite post-T values, preserving the panel's shape and missing-
            data pattern. Catches a feature that reads a specific future row.

  TRUNCATE  Cut the panel off at T entirely. Catches code that reads "the last
            row", or otherwise depends on how far the data extends.

Both also blank the forward-looking METADATA fields -- `delist_date`,
`last_date`, `first_date` beyond T, and the delisting reason that accompanies
them -- because a filter that peeked at "this name is delisted next year" would
be a survivorship leak invisible to a price-only perturbation.

SCOPE. Forward returns are deliberately NOT audited. They are the label; looking
forward is their job. Everything decided BEFORE the trade is audited: eligibility,
all eight feature components, the composite score and the decile assignment.

KNOWN LIMITATION, disclosed rather than papered over: perturbation preserves the
post-T missing-data pattern, so a feature that read only the SHAPE of future
missingness (without reading a value) would escape the perturb mode. Truncate
mode covers that case, which is why both run by default and why `audit_lookahead`
refuses to report a clean result from a single mode.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd

from apex.config import Config
from apex.contracts import Panel
from apex.features import compute_features
from apex.features.composite import build_scores
from apex.universe import apply_feature_completeness, build_universe

PERTURB = "perturb"
TRUNCATE = "truncate"
DEFAULT_MODES = (PERTURB, TRUNCATE)

# Recomputation on an identical prefix is deterministic, so a clean audit should
# be exact. The tolerance exists only to absorb the last bit of floating-point
# reassociation, not to forgive a real difference.
TOLERANCE = 1e-10

_PRICE_FRAMES = (
    "close_adj",
    "high_adj",
    "low_adj",
    "close_unadj",
    "volume",
    "shares_out",
)
_SERIES = ("benchmark_tr", "vol_index")
_META_DATES = ("first_date", "last_date", "delist_date")


class AuditError(ValueError):
    """The audit was asked for something it cannot meaningfully answer."""


# ---------------------------------------------------------------------------
# building the counterfactual panels
# ---------------------------------------------------------------------------


def _blank_future_meta(meta: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    """Erase metadata that was not knowable at `date`.

    A delisting date in the future is exactly the kind of fact whose accidental
    use reintroduces survivorship bias, so the audit removes it rather than
    trusting that nothing reads it.
    """
    out = meta.copy()
    for column in _META_DATES:
        if column in out.columns:
            values = pd.to_datetime(out[column], errors="coerce")
            out[column] = values.where(values <= date)
    if "delist_reason" in out.columns and "delist_date" in out.columns:
        out["delist_reason"] = out["delist_reason"].where(out["delist_date"].notna())
    return out


def perturb_after(panel: Panel, date: pd.Timestamp, seed: int = 0) -> Panel:
    """Replace every observation strictly after `date` with unrelated values.

    Finite values are multiplied by exp(N(0, 1)), which changes them materially
    while preserving positivity -- `Panel` rejects non-positive adjusted prices,
    and a perturbation that violated the contract would be testing the contract
    rather than the pipeline. The missing-data pattern is preserved; see the
    module docstring for why TRUNCATE mode exists to cover what that misses.
    """
    date = pd.Timestamp(date)
    rng = np.random.default_rng(seed)
    future = panel.dates > date
    if not future.any():
        raise AuditError(f"no observations after {date.date()}; nothing to perturb")

    replacements: dict[str, object] = {}
    for name in _PRICE_FRAMES:
        frame = getattr(panel, name).copy()
        block = frame.loc[future]
        noise = np.exp(rng.standard_normal(block.shape))
        frame.loc[future] = block.to_numpy() * noise
        replacements[name] = frame

    for name in _SERIES:
        series = getattr(panel, name).copy()
        block = series.loc[future]
        series.loc[future] = block.to_numpy() * np.exp(rng.standard_normal(block.shape))
        replacements[name] = series

    replacements["meta"] = _blank_future_meta(panel.meta, date)
    return dataclasses.replace(panel, **replacements)


def truncate_at(panel: Panel, date: pd.Timestamp) -> Panel:
    """Cut the panel off at `date`, so nothing after it exists at all."""
    date = pd.Timestamp(date)
    keep = panel.dates <= date
    if not keep.any():
        raise AuditError(f"no observations at or before {date.date()}")

    dates = panel.dates[keep]
    replacements: dict[str, object] = {"dates": dates}
    for name in _PRICE_FRAMES:
        replacements[name] = getattr(panel, name).loc[keep]
    for name in _SERIES:
        replacements[name] = getattr(panel, name).loc[keep]
    replacements["meta"] = _blank_future_meta(panel.meta, date)
    return dataclasses.replace(panel, **replacements)


# ---------------------------------------------------------------------------
# what gets audited
# ---------------------------------------------------------------------------


def audit_targets(panel: Panel, config: Config) -> dict[str, pd.DataFrame]:
    """Every quantity the pipeline decides BEFORE the trade.

    Mirrors `pipeline.build_panel_pipeline` exactly, minus forward returns. If
    that ordering ever changes, this must change with it -- which is why the
    stage sequence is duplicated here explicitly rather than reached through a
    convenience wrapper that might quietly acquire a forward-looking step.
    """
    universe = build_universe(panel, config)
    features = compute_features(panel, universe.eligible, config)
    universe = apply_feature_completeness(universe, features.complete())
    scores = build_scores(features, universe.eligible, config)

    return {
        "eligible": universe.eligible,
        **features.components,
        "apex_score": scores.apex_score,
        "decile": scores.decile,
    }


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    date: pd.Timestamp
    mode: str
    component: str
    n_securities: int
    max_abs_delta: float

    def describe(self) -> str:
        return (
            f"  {self.date.date()}  [{self.mode}]  {self.component}: "
            f"{self.n_securities} securities differ, max |delta| = "
            f"{self.max_abs_delta:.6g}"
        )


@dataclass(frozen=True)
class AuditReport:
    audit_dates: tuple
    modes: tuple
    components: tuple
    violations: tuple
    n_comparisons: int

    @property
    def clean(self) -> bool:
        return not self.violations

    def explain(self) -> str:
        head = (
            f"lookahead audit: {self.n_comparisons} comparisons over "
            f"{len(self.audit_dates)} dates x {len(self.modes)} modes x "
            f"{len(self.components)} components"
        )
        if self.clean:
            return head + "\n  CLEAN -- nothing known at T changed when the future was destroyed"
        lines = [
            head,
            f"  {len(self.violations)} VIOLATION(S) of protocol section 4 -- the run is void:",
        ]
        lines.extend(v.describe() for v in self.violations)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# the audit
# ---------------------------------------------------------------------------


def _row(frame: pd.DataFrame, date: pd.Timestamp) -> np.ndarray:
    if date not in frame.index:
        return np.array([])
    return frame.loc[date].to_numpy()


def _differences(clean: np.ndarray, other: np.ndarray) -> tuple[int, float]:
    """Count and size of the disagreements between two rows, NaN-aware."""
    if clean.size == 0 or other.size == 0 or clean.size != other.size:
        return max(clean.size, other.size), float("inf")

    if clean.dtype == bool or other.dtype == bool:
        differ = clean.astype(object) != other.astype(object)
        return int(differ.sum()), 1.0 if differ.any() else 0.0

    a = clean.astype("float64")
    b = other.astype("float64")
    a_nan, b_nan = np.isnan(a), np.isnan(b)

    pattern_differs = a_nan != b_nan
    both_present = ~a_nan & ~b_nan
    scale = np.maximum(1.0, np.maximum(np.abs(a), np.abs(b)))
    with np.errstate(invalid="ignore"):
        value_differs = both_present & (np.abs(a - b) > TOLERANCE * scale)

    differ = pattern_differs | value_differs
    if not differ.any():
        return 0, 0.0
    delta = np.abs(a - b)[both_present & value_differs]
    return int(differ.sum()), float(delta.max()) if delta.size else float("inf")


def audit_lookahead(
    panel: Panel,
    config: Config,
    audit_dates,
    target_fn=audit_targets,
    modes: tuple = DEFAULT_MODES,
    seed: int = 20260809,
) -> AuditReport:
    """Measure protocol section 4 compliance at each date in `audit_dates`.

    Raises rather than reporting a clean result when the audit could not have
    detected anything -- an unauditable date is not a passing date.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(list(audit_dates)))
    if len(dates) == 0:
        raise AuditError("no audit dates supplied")

    unknown = [d for d in dates if d not in panel.dates]
    if unknown:
        raise AuditError(f"audit dates absent from the panel calendar: {unknown[:5]}")

    if len(modes) < 2:
        raise AuditError(
            "a single-mode audit cannot certify a clean result; perturb and "
            "truncate catch different classes of violation (see module docstring)"
        )

    clean_targets = target_fn(panel, config)
    components = tuple(sorted(clean_targets))

    # An all-NaN row means the features are not computable yet, and every
    # comparison would be NaN-against-NaN: a vacuous pass.
    for date in dates:
        informative = any(
            np.isfinite(_row(frame, date).astype("float64", copy=False)).any()
            for name, frame in clean_targets.items()
            if frame.dtypes.iloc[0] != bool and name != "eligible"
        )
        if not informative:
            raise AuditError(
                f"no feature is computable at {date.date()}; auditing it would "
                f"compare NaN against NaN and pass vacuously. Audit dates must "
                f"sit at or after the section 9 anchor."
            )

    violations: list[Violation] = []
    n_comparisons = 0

    for date in dates:
        for mode in modes:
            if mode == PERTURB:
                counterfactual = perturb_after(panel, date, seed=seed)
            elif mode == TRUNCATE:
                counterfactual = truncate_at(panel, date)
            else:
                raise AuditError(f"unknown audit mode '{mode}'")

            recomputed = target_fn(counterfactual, config)

            for component in components:
                n_comparisons += 1
                n_differ, max_delta = _differences(
                    _row(clean_targets[component], date),
                    _row(recomputed.get(component, pd.DataFrame()), date),
                )
                if n_differ:
                    violations.append(
                        Violation(
                            date=date,
                            mode=mode,
                            component=component,
                            n_securities=n_differ,
                            max_abs_delta=max_delta,
                        )
                    )

    return AuditReport(
        audit_dates=tuple(dates),
        modes=tuple(modes),
        components=components,
        violations=tuple(violations),
        n_comparisons=n_comparisons,
    )
