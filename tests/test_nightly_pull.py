"""The live lake: append-only, incremental, and REFUSED as evidence.

The single load-bearing claim: a live-lake dataset can never open a locked
period, spend a credit, or back a verdict -- not because a new guard says so,
but because its fingerprint is minted inside the existing development
namespace, whose four refusal points are already counterexampled. These tests
prove that claim can fail (a confirmatory fingerprint passes the same gate)
and exercise the incremental mechanics with a stub client.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from apex.dev.namespace import DevelopmentDatasetRefused, require_confirmatory

_SPEC = importlib.util.spec_from_file_location(
    "nightly_pull",
    Path(__file__).resolve().parent.parent / "scripts" / "nightly_pull.py",
)
np_mod = importlib.util.module_from_spec(_SPEC)
sys.modules["nightly_pull"] = np_mod
_SPEC.loader.exec_module(np_mod)


class StubClient:
    """Canned rows; counts calls. No network, no key."""

    def __init__(self, fail_after: int | None = None):
        self.calls = 0
        self.fail_after = fail_after

    def fetch_table(self, table, params=None, limit=None):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("simulated API failure")
        cols = ["ticker", "date", "value"]
        rows = [["AAA", "2026-07-01", "1.0"], ["BBB", "2026-07-01", "2.0"]]
        return cols, rows


# --- the governance claim -----------------------------------------------------

def test_the_lake_fingerprint_is_refused_where_evidence_is_required(tmp_path):
    result = np_mod.run_pull(StubClient(), tmp_path / "lake", "2026-07-01", "2026-07-02")
    fp = result["manifest"]["dataset_fingerprint"]

    with pytest.raises(DevelopmentDatasetRefused):
        require_confirmatory(fp, context="test")


def test_counterexample_a_confirmatory_fingerprint_passes_the_same_gate():
    """If the gate refused everything, the refusal above would prove nothing."""
    require_confirmatory("a" * 64, context="test")  # must NOT raise


def test_the_lake_refuses_to_live_inside_the_snapshot_tree(tmp_path):
    bad = tmp_path / "data" / "snapshots" / "sharadar" / "current"
    with pytest.raises(np_mod.LiveLakeError, match="immutable evidence"):
        np_mod.require_outside_snapshots(bad)


def test_counterexample_a_root_outside_snapshots_is_accepted(tmp_path):
    assert np_mod.require_outside_snapshots(tmp_path / "data" / "live") \
        == (tmp_path / "data" / "live").resolve()


# --- incremental mechanics ----------------------------------------------------

def test_the_first_pull_starts_the_day_after_the_frozen_snapshot(tmp_path):
    lake = tmp_path / "lake"
    rng = np_mod.pull_range(lake)
    assert rng is not None
    assert rng[0] == "2026-07-01"  # FROZEN_SNAPSHOT_END + 1 day


def test_a_current_lake_is_a_noop(tmp_path):
    lake = tmp_path / "lake"
    lake.mkdir()
    future = "2099-01-01"
    np_mod.state_path(lake).write_text(json.dumps({"lake_through": future}))
    assert np_mod.pull_range(lake) is None


def test_state_advances_only_after_a_successful_pull(tmp_path):
    lake = tmp_path / "lake"
    with pytest.raises(RuntimeError, match="simulated API failure"):
        np_mod.run_pull(StubClient(fail_after=1), lake, "2026-07-01", "2026-07-02")

    # the crashed pull left no state: next night retries the SAME range
    assert np_mod.lake_through(lake) == np_mod.FROZEN_SNAPSHOT_END

    np_mod.run_pull(StubClient(), lake, "2026-07-01", "2026-07-02")
    assert np_mod.lake_through(lake) == "2026-07-02"


def test_a_rerun_skips_verified_slices(tmp_path):
    lake = tmp_path / "lake"
    first = np_mod.run_pull(StubClient(), lake, "2026-07-01", "2026-07-02")
    assert first["stats"]["fetched"] > 0

    second = np_mod.run_pull(StubClient(), lake, "2026-07-01", "2026-07-02")
    assert second["stats"]["fetched"] == 0
    assert second["stats"]["skipped"] == first["stats"]["fetched"]


def test_the_pull_log_is_hash_chained(tmp_path):
    lake = tmp_path / "lake"
    np_mod.run_pull(StubClient(), lake, "2026-07-01", "2026-07-02")
    np_mod.run_pull(StubClient(), lake, "2026-07-03", "2026-07-04")

    lines = [json.loads(l) for l in
             (lake / "pull_log.jsonl").read_text().strip().splitlines()]
    assert lines[0]["prev_hash"] == "GENESIS"
    assert lines[1]["prev_hash"] == lines[0]["entry_hash"]


def test_counterexample_a_tampered_log_entry_breaks_the_chain(tmp_path):
    """The chain must be able to detect what it exists to detect."""
    lake = tmp_path / "lake"
    np_mod.run_pull(StubClient(), lake, "2026-07-01", "2026-07-02")

    import hashlib
    line = json.loads((lake / "pull_log.jsonl").read_text().strip())
    recorded = line.pop("entry_hash")
    line["rows"] = {k: 999_999 for k in line["rows"]}  # falsify the row counts
    recomputed = hashlib.sha256(
        json.dumps(line, sort_keys=True).encode()
    ).hexdigest()
    assert recomputed != recorded
