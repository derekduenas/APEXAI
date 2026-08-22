"""UniverseCoverageState — the first-class answer to "how much of the
INTENDED universe can APEX actually see right now," at the universe
level (apex/hunter/session_coverage.py answers the analogous question
per-symbol, for the session-open anchor).

Built for Phase 0.4 (FULL-UNIVERSE SENSORY ARCHITECTURE), in direct
response to the measured 2026-08-17 finding: continuous realtime EODHD
trade coverage was 50/164 symbols (30.5%). A dynamic reallocator cannot
fully solve this -- a symbol must be observed to become interesting, but
cannot become interesting if it is never observed. That is a STRUCTURAL
sensing limit, not a ranking problem, and it must be a measured, typed
fact everywhere it matters, never an implicit assumption.

decision_power: NONE. This module measures and classifies; it
authorizes nothing and purchases nothing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

HEALTHY, PARTIAL, DEGRADED, FAILED = "HEALTHY", "PARTIAL", "DEGRADED", "FAILED"

# below this continuous-coverage fraction, a claim of "broad discovery"
# is not defensible -- absence of a signal cannot be read as absence of
# an event when most of the universe was never watched
BROAD_DISCOVERY_MIN_FRACTION = 0.95


class UniverseCoverageViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class UniverseCoverageState:
    intended_universe: tuple            # every symbol APEX means to trade
    authorized_universe: tuple          # entitlement-eligible subset
    streamed_universe: tuple            # currently subscribed
    continuous_universe: tuple          # streamed with zero gaps this session
    rotated_universe: tuple             # entered/left the stream mid-session
    never_observed: tuple               # in intended_universe, zero minutes ever

    coverage_count: int
    coverage_fraction: float
    continuous_coverage_fraction: float

    first_observed_by_symbol: dict = field(default_factory=dict)
    last_observed_by_symbol: dict = field(default_factory=dict)
    max_gap_by_symbol: dict = field(default_factory=dict)     # seconds

    discovery_latency_scope: str = "CANDIDATE_EVOLUTION_LATENCY_ONLY"
    broad_discovery_valid: bool = False

    source: str | None = None
    transport: str | None = None
    known_from: str | None = None
    as_of: str | None = None

    status: str = FAILED

    def as_record(self) -> dict:
        return {"kind": "universe_coverage_state", **asdict(self)}


def compute_universe_coverage(
    *, intended_universe, authorized_universe, streamed_universe,
    bar_index_by_symbol: dict, as_of, source: str | None = None,
    transport: str | None = None, known_from: str | None = None,
) -> UniverseCoverageState:
    """`bar_index_by_symbol`: {symbol: sorted list/Index of observed bar
    minute timestamps this session}, e.g. from
    apex.intraday.equity_fabric.EquityRealtimeFabric.bars_1m()."""
    import pandas as pd
    intended = tuple(sorted(set(intended_universe)))
    authorized = tuple(sorted(set(authorized_universe) & set(intended)))
    streamed = tuple(sorted(set(streamed_universe) & set(intended)))

    first_obs, last_obs, max_gap, continuous = {}, {}, {}, []
    for sym in streamed:
        idx = bar_index_by_symbol.get(sym)
        if idx is None or len(idx) == 0:
            continue
        ts = sorted(pd.Timestamp(t) for t in idx)
        first_obs[sym] = str(ts[0])
        last_obs[sym] = str(ts[-1])
        gaps = [(ts[i + 1] - ts[i]).total_seconds() for i in range(len(ts) - 1)]
        gap_s = max(gaps) if gaps else 0.0
        max_gap[sym] = round(gap_s, 1)
        if gap_s <= 60.0:                # no minute skipped
            continuous.append(sym)

    never = tuple(s for s in intended if s not in first_obs)
    rotated = tuple(sorted(set(streamed) - set(continuous) - set(never)))
    n_intended = len(intended) or 1
    coverage_fraction = round(len(streamed) / n_intended, 4)
    continuous_fraction = round(len(continuous) / n_intended, 4)
    broad_valid = continuous_fraction >= BROAD_DISCOVERY_MIN_FRACTION

    if not streamed:
        status = FAILED
    elif broad_valid:
        status = HEALTHY
    elif continuous_fraction >= 0.5:
        status = PARTIAL
    else:
        status = DEGRADED

    return UniverseCoverageState(
        intended_universe=intended, authorized_universe=authorized,
        streamed_universe=streamed, continuous_universe=tuple(sorted(continuous)),
        rotated_universe=rotated, never_observed=never,
        coverage_count=len(streamed), coverage_fraction=coverage_fraction,
        continuous_coverage_fraction=continuous_fraction,
        first_observed_by_symbol=first_obs, last_observed_by_symbol=last_obs,
        max_gap_by_symbol=max_gap,
        discovery_latency_scope=("UNIVERSE_DISCOVERY_LATENCY" if broad_valid
                                 else "CANDIDATE_EVOLUTION_LATENCY_ONLY"),
        broad_discovery_valid=broad_valid,
        source=source, transport=transport, known_from=known_from,
        as_of=str(pd.Timestamp(as_of)), status=status)
