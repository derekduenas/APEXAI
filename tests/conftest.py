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


def tiny_frame(values, dates=None, securities=None) -> pd.DataFrame:
    array = np.asarray(values, dtype="float64")
    index = dates if dates is not None else pd.bdate_range("2020-01-01", periods=array.shape[0])
    columns = securities if securities is not None else [f"S{i}" for i in range(array.shape[1])]
    return pd.DataFrame(array, index=index, columns=pd.Index(columns, name="security_id"))
