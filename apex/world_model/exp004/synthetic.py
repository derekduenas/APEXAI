"""SYNTHETIC-ONLY entry point for EXP-004.

This module exists so that reduced inference parameters are **unreachable from
the production path**. `run.tournament` and `run.score` take no inference
parameters at all; an admission binds to `run.tournament`. Anything here stamps
`run_mode="SYNTHETIC_TEST"` and `NOT_FOR_HISTORICAL_USE` on the record, so a
record produced with reduced parameters is self-identifying and can never be
mistaken for a historical result.

Nothing in this module may be used on admitted historical data."""
from __future__ import annotations

from . import run as R

NOT_AN_ADMITTED_ENTRY_POINT = True


def synthetic_tournament(fit_sessions: list, dev_sessions: list, *, bootstrap_resamples=None, seed=None) -> dict:
    """Run the registered pipeline on SYNTHETIC fixtures with reduced bootstrap
    replicates, for implementation evidence only. Parameters are validated with
    exact integer types and declared ranges before any session or fit work."""
    params = R.resolve_inference_parameters(bootstrap_resamples, seed, run_mode=R.SYNTHETIC_TEST)
    return R._core(fit_sessions, dev_sessions, params=params)


def synthetic_score(prep: dict, dev_sessions: list, *, bootstrap_resamples=None, seed=None) -> dict:
    params = R.resolve_inference_parameters(bootstrap_resamples, seed, run_mode=R.SYNTHETIC_TEST)
    return R._score(prep, dev_sessions, params=params)
