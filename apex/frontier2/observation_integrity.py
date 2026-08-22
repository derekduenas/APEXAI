"""ObservationIntegrityState — F13 (partial): the single gate every
Frontier-2 organ must check before treating ANY breadth-based or
symbol-level input as trustworthy.

This module invents no new sensing. It COMPOSES three contracts already
built and tested tonight (Phase 0.1 / Phase 0.4):

    apex.hunter.session_coverage.SessionCoverage
    apex.intraday.universe_coverage.UniverseCoverageState
    apex.intraday.disagreement.DataDisagreementState (zero or more)

into one quality verdict. `compute()` is a pure function over already
-constructed contract objects — no I/O, fully deterministic, unit
-testable without touching disk. `load_latest()` is the thin, honest I/O
edge: it reads what is ACTUALLY on disk right now and is explicit about
what it could not find, rather than inventing a stand-in.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from apex.frontier2 import FRONTIER2_POWER

FULL, PARTIAL, LIMITED, INVALID, UNKNOWN = (
    "FULL", "PARTIAL", "LIMITED", "INVALID", "UNKNOWN")
QUALITIES = (FULL, PARTIAL, LIMITED, INVALID, UNKNOWN)


class ObservationIntegrityViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class ObservationIntegrityState:
    as_of: str
    known_from: str
    session_date: str | None

    session_anchor_valid: bool | None          # None = not measured
    session_coverage_quality: str               # FULL/PARTIAL/DEGRADED/INVALID/UNKNOWN

    broad_discovery_valid: bool | None          # None = not measured
    broad_coverage_fraction: float | None
    broad_continuous_coverage_fraction: float | None
    discovery_latency_scope: str | None

    disagreement_checked: int
    disagreement_material: int
    disagreement_symbols_material: tuple = ()

    quality: str = UNKNOWN
    quality_reasons: tuple = ()
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        if self.quality not in QUALITIES:
            raise ObservationIntegrityViolation(
                f"unknown quality {self.quality!r}")

    def as_record(self) -> dict:
        return {"kind": "observation_integrity_state", **asdict(self)}

    def breadth_usable(self) -> bool:
        """The one question every downstream breadth-consuming module
        (Curve first) must ask before it may emit a non-LIMITED
        breadth-based state."""
        return bool(self.broad_discovery_valid) and self.quality in (FULL, PARTIAL)


def compute(*, session_coverage=None, universe_coverage=None,
           disagreements: tuple = (), as_of, known_from,
           session_date: str | None = None) -> ObservationIntegrityState:
    """`session_coverage`: a SessionCoverage instance, or None if not
    measured for this call (symbol-level checks may omit it).
    `universe_coverage`: a UniverseCoverageState instance, or None.
    `disagreements`: tuple of DataDisagreementState instances checked
    this tick (may be empty -- that means zero overlap symbols were
    checked, NOT zero disagreement)."""
    import pandas as pd
    reasons = []

    sc_quality = UNKNOWN
    anchor_valid = None
    if session_coverage is not None:
        sc_quality = session_coverage.quality
        anchor_valid = session_coverage.session_anchor_valid
        if not anchor_valid:
            reasons.append("SESSION_ANCHOR_INVALID")
        session_date = session_date or session_coverage.session_date

    broad_valid = None
    broad_frac = None
    broad_cont_frac = None
    disc_scope = None
    if universe_coverage is not None:
        broad_valid = universe_coverage.broad_discovery_valid
        broad_frac = universe_coverage.coverage_fraction
        broad_cont_frac = universe_coverage.continuous_coverage_fraction
        disc_scope = universe_coverage.discovery_latency_scope
        if not broad_valid:
            reasons.append("BROAD_DISCOVERY_NOT_VALID")

    material_syms = tuple(sorted({
        d.symbol for d in disagreements if getattr(d, "material", False)}))
    if material_syms:
        reasons.append("PROVIDER_DISAGREEMENT_MATERIAL")

    # THE VERDICT LADDER — deliberately conservative: any single failure
    # caps quality below FULL, and a missing measurement is UNKNOWN, not
    # an assumed pass. A dimension that was simply never CHECKED (its
    # contract object is None) is treated as not applicable to THIS
    # call, not as an automatic downgrade -- a caller checking only
    # broad coverage must be able to reach FULL without also supplying
    # a per-symbol SessionCoverage it has no reason to have in hand.
    if session_coverage is None and universe_coverage is None:
        quality = UNKNOWN
        reasons.append("NO_INTEGRITY_INPUTS_PROVIDED")
    elif anchor_valid is False or sc_quality == "INVALID":
        quality = INVALID
    elif broad_valid is False:
        quality = LIMITED
    elif material_syms:
        quality = PARTIAL
    elif session_coverage is not None:
        quality = {"FULL": FULL, "PARTIAL": PARTIAL,
                  "DEGRADED": LIMITED}.get(sc_quality, UNKNOWN)
    else:
        # only universe_coverage was checked, and every branch above
        # that could have failed it already returned.
        quality = FULL

    return ObservationIntegrityState(
        as_of=str(pd.Timestamp(as_of)), known_from=str(pd.Timestamp(known_from)),
        session_date=session_date,
        session_anchor_valid=anchor_valid, session_coverage_quality=sc_quality,
        broad_discovery_valid=broad_valid, broad_coverage_fraction=broad_frac,
        broad_continuous_coverage_fraction=broad_cont_frac,
        discovery_latency_scope=disc_scope,
        disagreement_checked=len(disagreements),
        disagreement_material=len(material_syms),
        disagreement_symbols_material=material_syms,
        quality=quality, quality_reasons=tuple(reasons))


def load_latest(*, as_of=None) -> ObservationIntegrityState:
    """Honest I/O edge: reads results/intraday/universe_coverage.json if
    present. SessionCoverage has no standalone ledger yet (Phase 0.1
    embeds it inside per-symbol ChartState/world_state records, which
    this function deliberately does NOT reach into -- that coupling
    belongs to a caller with a specific symbol/session in hand, not to
    a system-wide loader). Absence of a piece is reported, not
    fabricated."""
    import json
    from pathlib import Path
    import pandas as pd

    now = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.now(tz="UTC")
    p = Path("results/intraday/universe_coverage.json")
    if not p.exists():
        return compute(as_of=now, known_from=now)

    from apex.intraday.universe_coverage import UniverseCoverageState
    raw = json.loads(p.read_text())
    fields = {f: raw.get(f) for f in UniverseCoverageState.__dataclass_fields__}
    for tup_field in ("intended_universe", "authorized_universe",
                      "streamed_universe", "continuous_universe",
                      "rotated_universe", "never_observed",
                      "disagreement_symbols_material"):
        if tup_field in fields and fields[tup_field] is not None:
            fields[tup_field] = tuple(fields[tup_field])
    uc = UniverseCoverageState(**fields)
    return compute(universe_coverage=uc, as_of=now, known_from=now)
