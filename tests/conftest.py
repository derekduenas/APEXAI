"""Shared fixtures.

Pipeline runs are cached by (seed, alpha) because the null rig needs many
independent worlds and each one costs a few seconds. The cache is keyed on
exactly the inputs that determine the output, which is also a standing check
that the pipeline really is a pure function of them.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
import pytest

from apex.config import load_config
from apex.data.synthetic import SyntheticSource
from apex.pipeline import build_panel_pipeline, evaluate


@pytest.fixture(autouse=True)
def _isolate_quota_ledger(tmp_path_factory):
    """LAB-07: the quota spend counter is a real governance artifact that
    decides whether the forward reserve is intact. A test run must never
    write into it -- phantom test units would refuse a real Monday tick.

    PER-TEST scope (was session-scoped): with one shared dir, tests that
    legitimately spend units polluted later tests' headroom reads -- 11
    residual units surfaced as a flaky 64989 != 65000 the moment the GMT
    rollover split spends across bucket files mid-run. Cross-test coupling
    through a governance counter is the same disease the counter exists
    to prevent."""
    from apex.intraday import quota_ledger
    real = quota_ledger.SPEND_DIR
    quota_ledger.SPEND_DIR = tmp_path_factory.mktemp("quota_ledger")
    yield
    quota_ledger.SPEND_DIR = real


@pytest.fixture(scope="session")
def config():
    return load_config("experiment", "costs", "synthetic")


@lru_cache(maxsize=64)
def _run(seed: int, alpha: float):
    config = load_config("experiment", "costs", "synthetic")
    overrides = {
        "panel.n_securities": config.get("null_rig.n_securities"),
        "panel.start": config.get("null_rig.start"),
        "panel.end": config.get("null_rig.end"),
        "sectors.n_sectors": config.get("null_rig.n_sectors"),
    }
    source = SyntheticSource(config=config, seed=seed, alpha=alpha, overrides=overrides)
    output = build_panel_pipeline(source.load(), config)
    period = config.period("in_sample")
    return output, evaluate(output, config, period["start"], config.get("null_rig.end"))


@pytest.fixture(scope="session")
def null_run():
    """One null-world pipeline run, for tests that need only a single panel."""
    return _run(0, 0.0)


@pytest.fixture(scope="session")
def run_factory():
    return _run


def null_sweep(config, n_seeds: int) -> pd.DataFrame:
    """Run `n_seeds` independent null worlds and collect their statistics."""
    base = int(config.get("null_rig.base_seed"))
    rows = []
    for i in range(n_seeds):
        _, evaluation = _run(base + i, 0.0)
        rows.append(
            {
                "seed": base + i,
                "mean_ic": evaluation.ic_daily.mean,
                "t_stat": evaluation.ic_daily.t_stat,
                "n_periods": evaluation.ic_daily.n_periods,
                "spread_annual": evaluation.deciles.spread_annualised_gross,
                "spread_t": evaluation.deciles.spread_t_stat,
            }
        )
    return pd.DataFrame(rows)


def null_ic_series(config, seed_offset: int = 0) -> pd.Series:
    """One null world's DAILY IC series, for autocorrelation-structure checks."""
    base = int(config.get("null_rig.base_seed"))
    _, evaluation = _run(base + seed_offset, 0.0)
    return evaluation.ic_daily.series.dropna()


@lru_cache(maxsize=8)
def _reference(n_obs: int, overlap: int, lag: int, kernel: str, reps: int, seed: int):
    from apex.evaluate.reference import simulate_null_tstats

    return simulate_null_tstats(
        n_obs=n_obs,
        overlap=overlap,
        lag=lag,
        kernel=kernel,
        n_replications=reps,
        seed=seed,
    )


def reference_for(config, n_obs: int):
    """The null reference matching the estimator the pipeline actually reports."""
    return _reference(
        int(n_obs),
        int(config.get("horizon.forward_trading_days")),
        int(config.get("evaluation.newey_west_lag")),
        "bartlett",
        int(config.get("null_rig.reference_replications")),
        int(config.get("null_rig.reference_seed")),
    )


def patched(config, overrides: dict):
    """A copy of `config` with dotted keys replaced.

    Unit tests for a filter need thresholds a ten-row panel can actually reach.
    Patching is explicit and returns a NEW Config -- the loaded one is never
    mutated, so a patched threshold cannot leak into another test.
    """
    import copy

    from apex.config import Config

    data = copy.deepcopy(config.data)
    for dotted, value in overrides.items():
        node = data
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node[part]
        if value is DELETE:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    return Config(data=data, sources=config.sources + ("patched",))


# Sentinel for patched(): remove a key entirely. Needed because "the key is
# ABSENT" is itself a documented behavior (e.g. no market-cap ceiling for the
# #001-#003 universe) and setting a value cannot express absence.
DELETE = object()

# The FROZEN #001-#003 large-cap universe (protocol v1.0 section 3). Tests
# that document layer behavior against the historical universe pin these
# explicitly instead of drifting with whatever experiment is currently
# registered -- the live config now carries #004's small-cap band.
LEGACY_LARGE_CAP_UNIVERSE = {
    "universe.min_market_cap_usd": 1_000_000_000.0,
    "universe.max_market_cap_usd": DELETE,
    "universe.min_addv_usd": 10_000_000.0,
    "universe.min_close_usd": 5.0,
}


def hand_panel(
    dates,
    close_adj: dict,
    *,
    close_unadj: dict | None = None,
    shares_out: dict | None = None,
    volume: dict | None = None,
    high_adj: dict | None = None,
    low_adj: dict | None = None,
    meta: dict | None = None,
    benchmark: list | None = None,
    vix: list | None = None,
):
    """A hand-specified `Panel`, so tests can assert exact arithmetic.

    Defaults are chosen to clear every protocol section 3 filter, so a test only
    has to specify the one quantity it is actually about. `security_id` is
    deliberately distinct from `ticker`, which `Panel` requires -- tickers are
    recycled and joining on them reintroduces survivorship contamination.
    """
    from apex.contracts import SECURITY_META_COLUMNS, Panel

    index = pd.DatetimeIndex(pd.to_datetime(dates))
    securities = pd.Index(sorted(close_adj), name="security_id")

    def frame(source: dict | None, default) -> pd.DataFrame:
        if source is None:
            source = {s: [default] * len(index) for s in securities}
        return pd.DataFrame(
            {s: pd.Series(source[s], index=index, dtype="float64") for s in securities},
            index=index,
            columns=securities,
        )

    adjusted = frame(close_adj, np.nan)
    unadjusted = frame(close_unadj, np.nan) if close_unadj else adjusted.copy()

    rows = []
    for security in securities:
        overrides = (meta or {}).get(security, {})
        rows.append(
            {
                "security_id": security,
                "ticker": overrides.get("ticker", f"T{security}"),
                "exchange": overrides.get("exchange", "NYSE"),
                "security_type": overrides.get("security_type", "common"),
                "sector": overrides.get("sector", "tech"),
                "first_date": overrides.get("first_date", index[0]),
                "last_date": overrides.get("last_date", index[-1]),
                "delist_date": overrides.get("delist_date", pd.NaT),
                "delist_reason": overrides.get("delist_reason", None),
            }
        )
    meta_frame = pd.DataFrame(rows, index=securities)[list(SECURITY_META_COLUMNS)]

    return Panel(
        dates=index,
        securities=securities,
        close_adj=adjusted,
        high_adj=frame(high_adj, np.nan) if high_adj else adjusted * 1.01,
        low_adj=frame(low_adj, np.nan) if low_adj else adjusted * 0.99,
        close_unadj=unadjusted,
        # Defaults must clear every filter by a wide margin even at a low price,
        # so a test that cares about ONE filter is not silently failing on a
        # different one. At the $5 boundary these give $5B cap and $50m ADDV.
        shares_out=frame(shares_out, 1e9),
        volume=frame(volume, 1e7),
        meta=meta_frame,
        benchmark_tr=pd.Series(
            benchmark if benchmark is not None else [100.0] * len(index), index=index
        ),
        vol_index=pd.Series(vix if vix is not None else [20.0] * len(index), index=index),
    )


def tiny_frame(values, dates=None, securities=None) -> pd.DataFrame:
    array = np.asarray(values, dtype="float64")
    index = dates if dates is not None else pd.bdate_range("2020-01-01", periods=array.shape[0])
    columns = securities if securities is not None else [f"S{i}" for i in range(array.shape[1])]
    return pd.DataFrame(array, index=index, columns=pd.Index(columns, name="security_id"))
