"""TEST-NULL-RIG-MEMORY-001 (WM-0E-R6.1): the test-support memory repair,
proven: semantic equivalence on a PREREGISTERED 3-seed subset against a
verbatim replica of the OLD computation path, cache lifetime bounds, no
linear growth across completed seeds, seed identities preserved, and the
original null-rig nodeid set unchanged."""
import gc
import json
import os
import resource

import numpy as np
import pandas as pd
import pytest

from tests import conftest as CF

EQUIV_SEEDS = (90210, 90211, 90212)          # preregistered; old path completes safely

# The nodeid baseline. On world-model-shadow-v0 this guard read the R6 master
# inventory; that evidence file does not exist on this branch, and a guard that
# skips is not a guard. The set is therefore PINNED here, collected from
# tests/test_null_rig.py at this branch's base commit -- BEFORE the repair --
# so the test fails if the repair adds, drops or renames a single case.
# tests/test_null_rig.py is byte-identical on both branches (sha256
# cf0c5a0d2631abe4b4b9a89f2afd13bda40b5f08f5e124a08074558d1cbea931), so this is
# the same 12 nodeids the R6 master recorded.
BASE_COMMIT = "15ce57581757c80f2ec7df424fa29ae33a69d273"
BASELINE_NODEIDS = tuple(sorted((
    "tests/test_null_rig.py::test_random_walk_ic_is_not_significant",
    "tests/test_null_rig.py::test_random_walk_decile_spread_is_not_significant",
    "tests/test_null_rig.py::test_null_panel_produces_a_real_cross_section",
    "tests/test_null_rig.py::test_null_ic_series_has_the_autocorrelation_the_overlap_implies",
    "tests/test_null_rig.py::test_newey_west_matches_its_null_reference_fast",
    "tests/test_null_rig.py::test_newey_west_matches_its_null_reference_full",
    "tests/test_null_rig.py::test_the_fast_sweep_declares_itself_underpowered",
    "tests/test_null_rig.py::test_null_decile_spread_is_centred_on_zero",
    "tests/test_null_rig.py::test_shuffled_score_destroys_ic",
    "tests/test_null_rig.py::test_shuffled_score_on_real_data",
    "tests/test_null_rig.py::test_deferred_assertions_are_declared",
    "tests/test_null_rig.py::test_positive_control_is_recovered_and_scales",
)))


def _old_run(seed: int, alpha: float):
    """VERBATIM replica of the R6 `_run` body (a36dd5f35), uncached."""
    config = CF.load_config("experiment", "costs", "synthetic")
    overrides = {"panel.n_securities": config.get("null_rig.n_securities"),
                 "panel.start": config.get("null_rig.start"), "panel.end": config.get("null_rig.end"),
                 "sectors.n_sectors": config.get("null_rig.n_sectors")}
    source = CF.SyntheticSource(config=config, seed=seed, alpha=alpha, overrides=overrides)
    output = CF.build_panel_pipeline(source.load(), config)
    period = config.period("in_sample")
    return output, CF.evaluate(output, config, period["start"], config.get("null_rig.end"))


def _old_sweep(config, seeds):
    rows = []
    for s in seeds:
        _, ev = _old_run(s, 0.0)
        rows.append({"seed": s, "mean_ic": ev.ic_daily.mean, "t_stat": ev.ic_daily.t_stat,
                     "n_periods": ev.ic_daily.n_periods, "spread_annual": ev.deciles.spread_annualised_gross,
                     "spread_t": ev.deciles.spread_t_stat})
    return pd.DataFrame(rows)


def _rss():
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024


def test_semantic_equivalence_old_vs_new_on_preregistered_seeds(config):
    base = int(config.get("null_rig.base_seed"))
    assert EQUIV_SEEDS == tuple(base + i for i in range(3))
    old = _old_sweep(config, EQUIV_SEEDS)
    new = CF.null_sweep(config, 3)
    assert list(new["seed"]) == list(old["seed"]) == list(EQUIV_SEEDS)
    for col in ("mean_ic", "t_stat", "n_periods", "spread_annual", "spread_t"):
        assert np.array_equal(new[col].to_numpy(), old[col].to_numpy()), col     # EXACT
    # the daily IC series consumer, exact
    _, ev_old = _old_run(base, 0.0)
    assert CF.null_ic_series(config).equals(ev_old.ic_daily.series.dropna())
    # a run_factory consumer, exact
    _, ev_new = CF._run(7, 0.0)
    _, ev_old7 = _old_run(7, 0.0)
    assert ev_new.ic_daily.t_stat == ev_old7.ic_daily.t_stat and ev_new.ic_daily.mean == ev_old7.ic_daily.mean


def test_heavy_cache_bounded_and_sweep_does_not_populate_it(config):
    assert CF._run.cache_info().maxsize == CF.HEAVY_CACHE_MAXSIZE == 4
    before = CF._run.cache_info().currsize
    CF.null_sweep(config, 3)
    assert CF._run.cache_info().currsize == before                 # sweep bypasses the heavy cache
    assert CF._sweep_row.cache_info().currsize >= 3
    row = CF._sweep_row(EQUIV_SEEDS[0], 0.0)
    assert isinstance(row, tuple) and len(row) == 5 and all(isinstance(v, (float, int)) for v in row)


def test_memory_does_not_grow_linearly_with_completed_sweep_seeds(config):
    """Old path: +90 MiB per seed (measured). New path: after two more seeds
    the growth must be well under one old seed's retention."""
    CF.null_sweep(config, 3); gc.collect()
    r3 = _rss()
    CF.null_sweep(config, 5); gc.collect()
    r5 = _rss()
    assert r5 - r3 < 60.0, "sweep still retains per-seed state: +%.0f MiB for 2 seeds" % (r5 - r3)


def test_all_forty_seed_identities_and_assertions_still_active(config):
    assert int(config.get("null_rig.n_seeds")) == 40 and int(config.get("null_rig.n_seeds_fast")) == 8
    base = int(config.get("null_rig.base_seed"))
    src = open(os.path.join(os.path.dirname(CF.__file__), "test_null_rig.py")).read()
    for name in ("_assert_grand_mean_is_zero", "_assert_matches_null_reference", "assert not verdict.underpowered",
                 "assert verdict.underpowered", "assert abs(mean_spread) < z_threshold * standard_error",
                 "assert t_stats[-1] > 5.0", "@pytest.mark.slow"):
        assert name in src, name
    # the sweep still walks base .. base+n-1 in order
    rows = CF.null_sweep(config, 3)
    assert list(rows["seed"]) == [base, base + 1, base + 2]


def test_null_rig_nodeid_set_unchanged_from_the_base_commit():
    """The repair must not change WHICH tests run -- only how the fixtures hold
    memory. Unconditional: there is no evidence file here that could be absent."""
    assert len(BASELINE_NODEIDS) == 12
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "pytest", "tests/test_null_rig.py",
                          "--collect-only", "-q", "-p", "no:cacheprovider"],
                         capture_output=True, text=True)
    assert out.returncode == 0, (out.stdout[-2000:] + out.stderr[-2000:])
    now = tuple(sorted(l.strip() for l in out.stdout.splitlines()
                       if l.startswith("tests/test_null_rig.py::")))
    assert now == BASELINE_NODEIDS, set(now) ^ set(BASELINE_NODEIDS)
    src = open("tests/test_null_rig.py").read()
    assert src.count("@pytest.mark.skip(") == 1        # only the pre-existing DEFERRED skip
    # and this brick did not touch the module itself
    assert subprocess.run(["git", "diff", "--quiet", BASE_COMMIT, "--",
                           "tests/test_null_rig.py"]).returncode == 0
