"""OFFICIAL STACK SEMANTIC EQUIVALENCE — the dynamic proof behind
FRONTIER_NEXTGEN_BUILD_MAP.md's authority graph: a handful of
deterministic official-stack functions are run twice, once with
apex.frontier2 normally importable and once with it made ARTIFICIALLY
UNIMPORTABLE (an ImportError-raising sys.meta_path finder, not just an
absent directory), and every result must be byte-identical.

test_frontier2_firewall.py already proves STATICALLY that nothing in
the production stack imports apex.frontier2. This test proves the
DYNAMIC consequence: even if that import were to fail outright, no
official behavior changes -- because nothing was ever conditioned on
frontier2 existing in the first place.
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys

import pandas as pd
import pytest


class _BlockingLoader(importlib.abc.Loader):
    def create_module(self, spec):
        raise ImportError(f"apex.frontier2 blocked for the OFF-arm of the "
                          f"semantic equivalence test (name={spec.name!r})")

    def exec_module(self, module):        # pragma: no cover -- never reached
        raise ImportError("apex.frontier2 blocked")


class _BlockFrontier2(importlib.abc.MetaPathFinder):
    """A meta_path finder that makes apex.frontier2 (and every
    submodule) raise ImportError, simulating 'the package does not
    exist' more strongly than deleting files would (it also catches any
    accidental lazy/deferred import)."""

    def find_spec(self, name, path, target=None):
        if name == "apex.frontier2" or name.startswith("apex.frontier2."):
            return importlib.machinery.ModuleSpec(name, _BlockingLoader())
        return None


def _run_official_functions():
    import apex.frontier.senses as senses
    import apex.frontier.underwriting as uw
    import apex.governance.session_integrity_gate as gate
    from apex.hunter.session_coverage import compute_session_coverage

    out = {}

    out["route_reasoning"] = senses.route_reasoning(
        is_hunter_candidate=True, on_watchlist=True, persistence_ticks=3)

    prior = uw.OpportunityState(candidate_id="EQUIV-1", symbol="AAPL",
                                state="DISCOVERED")
    reund = uw.reunderwrite(
        prior, current_inputs={"rs_state": "STRONG"},
        direction_quality="STRONG", entry_quality="STRONG",
        now=pd.Timestamp("2026-08-18T14:00:00Z"))
    out["reunderwrite"] = reund.as_record()

    out["decision_eligible"] = gate.decision_eligible("2026-08-17")

    bars = pd.DataFrame({
        "event_time_utc": [pd.Timestamp("2026-08-18T13:30:00Z")
                           + pd.Timedelta(minutes=i) for i in range(5)],
        "open": [100.0, 100.1, 100.2, 100.1, 100.3],
        "high": [100.2, 100.3, 100.3, 100.2, 100.4],
        "low": [99.9, 100.0, 100.1, 100.0, 100.2],
        "close": [100.1, 100.2, 100.1, 100.3, 100.35],
        "volume": [1000, 1200, 900, 1100, 1050],
    })
    cov = compute_session_coverage(
        bars, "2026-08-18", pd.Timestamp("2026-08-18T13:36:00Z"),
        transport_source="TEST", known_from=str(pd.Timestamp("2026-08-18T13:36:00Z")))
    out["session_coverage"] = cov.as_record()

    return out


def _purge_frontier2_from_sys_modules():
    for name in [n for n in sys.modules if n == "apex.frontier2"
                or n.startswith("apex.frontier2.")]:
        del sys.modules[name]


def test_official_stack_is_semantically_identical_with_frontier2_blocked(
        tmp_path, monkeypatch):
    import apex.frontier.senses as senses
    monkeypatch.setattr(senses, "BUS_LEDGER", tmp_path / "bus_on.jsonl")
    monkeypatch.setattr(senses, "BOARD_LEDGER", tmp_path / "board_on.jsonl")

    # ---- ON arm: frontier2 present and importable (prove it CAN be
    # imported here, establishing this isn't a vacuous comparison) -----
    import apex.frontier2  # noqa: F401
    import apex.frontier2.curve  # noqa: F401
    on = _run_official_functions()

    # ---- OFF arm: frontier2 forcibly unimportable ----------------------
    _purge_frontier2_from_sys_modules()
    blocker = _BlockFrontier2()
    sys.meta_path.insert(0, blocker)
    try:
        with pytest.raises(ImportError):
            importlib.import_module("apex.frontier2")
        monkeypatch.setattr(senses, "BUS_LEDGER", tmp_path / "bus_off.jsonl")
        monkeypatch.setattr(senses, "BOARD_LEDGER", tmp_path / "board_off.jsonl")
        off = _run_official_functions()
    finally:
        sys.meta_path.remove(blocker)
        _purge_frontier2_from_sys_modules()
        import apex.frontier2  # noqa: F401  -- restore for subsequent tests

    assert on == off, (
        "official-stack output differs depending on whether apex.frontier2 "
        "can be imported -- something in the production path is coupled "
        "to the shadow build, which must never happen")
