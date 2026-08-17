"""LAB-07 -- the forward reserve must be a CONTROL, not a number.

The defect: FORWARD_RESERVE_CALL_UNITS existed, lab_spare_units() computed
headroom from it, and nothing in the system ever called that function.
QuotaGovernor.used starts at zero in every process, and the fast runner
constructed one governor per (worker x day) while printing that "workers
can never collectively exceed the lab total". One GMT day duly consumed
all 100,000 provider units, reserve included.

These tests fail if the reserve ever goes back to being advisory.
"""
from __future__ import annotations

import json
import multiprocessing as mp

import pytest

from apex.intraday import quota_ledger as ql
from apex.intraday.eodhd import (DAILY_LIMIT_CALL_UNITS,
                                 FORWARD_RESERVE_CALL_UNITS, QuotaGovernor)

DAY = "2026-08-16T12:00:00Z"


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ql, "SPEND_DIR", tmp_path / "quota")
    return tmp_path / "quota"


# --- the ceilings themselves ------------------------------------------------

def test_lab_ceiling_is_the_limit_minus_the_reserve(ledger):
    assert ql.ceiling(ql.LAB) == (DAILY_LIMIT_CALL_UNITS
                                  - FORWARD_RESERVE_CALL_UNITS)
    assert ql.ceiling(ql.FORWARD) == DAILY_LIMIT_CALL_UNITS


def test_an_undeclared_purpose_is_refused_not_guessed(ledger):
    with pytest.raises(ValueError):
        ql.spend(1, "WHATEVER")
    with pytest.raises(ValueError):
        QuotaGovernor(purpose="PRODUCTION")      # near-miss name, still no


def test_the_governor_defaults_to_lab_so_a_forgetful_caller_cannot_spend_the_reserve():
    assert QuotaGovernor().purpose == ql.LAB


# --- the actual bug: the reserve is untouchable by the lab ------------------

def test_lab_stops_at_the_reserve_boundary_and_leaves_it_whole(ledger):
    cap = ql.ceiling(ql.LAB)
    assert ql.spend(cap, ql.LAB, DAY)["granted"] is True
    refused = ql.spend(1, ql.LAB, DAY)
    assert refused["granted"] is False
    assert "forward reserve is untouchable" in refused["reason"]
    # the whole reserve survived, to the unit
    assert ql.read(DAY)["units"] == DAILY_LIMIT_CALL_UNITS - FORWARD_RESERVE_CALL_UNITS
    assert ql.headroom(ql.FORWARD, DAY) == FORWARD_RESERVE_CALL_UNITS


def test_forward_may_spend_the_reserve_because_that_is_what_it_is_for(ledger):
    ql.spend(ql.ceiling(ql.LAB), ql.LAB, DAY)     # lab exhausted
    got = ql.spend(FORWARD_RESERVE_CALL_UNITS, ql.FORWARD, DAY)
    assert got["granted"] is True, "the reserve must be reachable by FORWARD"
    assert ql.spend(1, ql.FORWARD, DAY)["granted"] is False  # true limit holds


def test_refusal_is_a_pause_not_a_crash(ledger):
    """The never-spin rule: exhaustion returns False, it does not raise.

    NOTE: seed the CURRENT bucket, not the hardcoded DAY — acquire() uses
    wall-clock now, and this test silently depended on the calendar
    agreeing with the fixture until the GMT rollover proved otherwise."""
    ql.spend(ql.ceiling(ql.LAB), ql.LAB)
    g = QuotaGovernor(daily_budget=10_000, purpose=ql.LAB)
    assert g.acquire(5) is False
    assert "QUOTA_CEILING_LAB" in g.last_refusal
    assert g.used == 0, "a refused claim must not be counted as spent"


# --- the structural defect: per-process counters bound nothing --------------

def _child(n, dirpath, q):
    ql.SPEND_DIR = dirpath
    g = QuotaGovernor(daily_budget=10 ** 9, purpose=ql.LAB)  # no local bound
    q.put(sum(1 for _ in range(n) if g.acquire(1000)))


def test_fresh_processes_cannot_each_grant_themselves_a_budget(ledger, tmp_path):
    """THE regression. Four processes, each with an effectively infinite
    LOCAL budget -- exactly the fast runner's per-(worker x day) governor.
    Their COLLECTIVE spend must still stop at the lab ceiling."""
    ql.SPEND_DIR.mkdir(parents=True, exist_ok=True)
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    procs = [ctx.Process(target=_child, args=(40, ql.SPEND_DIR, q))
             for _ in range(4)]
    for p in procs:
        p.start()
    granted = sum(q.get() for _ in procs)
    for p in procs:
        p.join(timeout=60)
    # 4 processes x 40 claims x 1000 units = 160k attempted, ceiling is 65k
    assert granted * 1000 <= ql.ceiling(ql.LAB)
    assert ql.read()["units"] <= ql.ceiling(ql.LAB)
    assert ql.headroom(ql.FORWARD) >= FORWARD_RESERVE_CALL_UNITS


def test_the_counter_survives_a_restart(ledger):
    ql.spend(20_000, ql.LAB, DAY)
    assert ql.read(DAY)["units"] == 20_000          # re-read from disk
    assert ql.headroom(ql.LAB, DAY) == ql.ceiling(ql.LAB) - 20_000


# --- reconciliation: the provider is the referee ----------------------------

def test_reconciliation_raises_to_the_provider_never_lowers(ledger):
    ql.spend(10_000, ql.LAB, DAY)
    out = ql.reconcile_with_provider(50_000, "2026-08-16", DAY)
    assert out["raised"] is True and out["units"] == 50_000
    # a provider counter LOWER than local (in-flight spend) must not lower us
    out2 = ql.reconcile_with_provider(30_000, "2026-08-16", DAY)
    assert out2["units"] == 50_000, "local in-flight spend was discarded"


def test_a_stale_provider_bucket_is_ignored(ledger):
    """The documented EODHD behavior: after midnight GMT the counter can
    still show yesterday's usage. Importing it would falsely read as
    'exhausted' the moment the reserve resets."""
    ql.spend(1_000, ql.LAB, DAY)
    out = ql.reconcile_with_provider(99_999, "2026-08-15", DAY)
    assert out["reconciled"] is False
    assert ql.read(DAY)["units"] == 1_000


def test_a_new_gmt_day_is_a_new_bucket_not_a_mutated_one(ledger):
    ql.spend(60_000, ql.LAB, "2026-08-16T23:00:00Z")
    nxt = "2026-08-17T00:30:00Z"
    assert ql.read(nxt)["units"] == 0
    assert ql.headroom(ql.LAB, nxt) == ql.ceiling(ql.LAB)


def test_a_corrupt_counter_file_reads_as_zero_not_as_garbage(ledger):
    ql.spend(500, ql.LAB, DAY)
    p = ql.SPEND_DIR / "spend_2026-08-16.json"
    p.write_text(json.dumps({"gmt_date": "2026-08-16"})[:-3])   # torn write
    assert ql.read(DAY)["units"] == 0


# --- the claim the runner prints must match what the code does --------------

def test_the_fast_runner_no_longer_claims_a_false_invariant():
    src = open("scripts/hunter_replay_fast.py").read()
    assert "can never collectively exceed the lab total" not in src, (
        "the false aggregate-invariant claim is back")
    assert "quota_ledger" in src, "the runner must consult the real bound"


def test_the_forward_clock_declares_itself_forward():
    src = open("scripts/hunter_forward_clock.py").read()
    assert src.count('QuotaGovernor(purpose="FORWARD")') >= 2, (
        "the production clock must be able to reach the reserve")


def test_the_reserve_helper_is_no_longer_callerless():
    """The original disease: a governance number with zero enforcement."""
    import subprocess
    out = subprocess.run(["grep", "-rn", "quota_ledger", "--include=*.py",
                          "apex/", "scripts/"], capture_output=True, text=True)
    callers = [ln for ln in out.stdout.splitlines()
               if "apex/intraday/quota_ledger.py" not in ln]
    assert len(callers) >= 3, f"reserve enforcement is not wired in: {callers}"
