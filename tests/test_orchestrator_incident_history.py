"""ORCHESTRATOR-OOM-001-R2: bounded incident history.

The outage's generator: MAX_RECOVERY_ATTEMPTS guarded only the branch that
STARTS a service, so the branch for externally supervised services appended
one entry per tick forever, and the whole list was re-serialised into every
ledger record. These tests pin the bound, the preserved information, the
separation of observations from attempts, and the record size.

Deterministic: no network, no real clock dependence, no service is started
(dry-run only), and nothing is written outside tmp_path.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "apex_orchestrator_under_test", ROOT / "scripts" / "apex_orchestrator.py")
ORCH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ORCH)

from apex.ops.orchestrator import ServiceSpec  # noqa: E402

T0 = datetime(2026, 9, 5, 21, 0, 0, tzinfo=timezone.utc)


def supervised(name="btc-paper"):
    return ServiceSpec(name=name, phases_running=(), always_on=True,
                       first_work_deadline_s=1800, supervised_by="systemd")


def self_started(name="options-paper"):
    return ServiceSpec(name=name, phases_running=("RTH",), always_on=True,
                       first_work_deadline_s=1800,
                       start_cmd=("/bin/true",), supervised_by="orchestrator")


class _Clock:
    """tick() measures the incident deadline with time.time(). Left on the
    real clock a test runs in milliseconds and every verdict is WITHIN_GRACE,
    so the alarm under test never fires. This drives that clock from the same
    simulated one, and swaps only the module reference inside the
    orchestrator."""

    def __init__(self, holder):
        self._h = holder

    def time(self):
        return self._h["t"].timestamp()

    def sleep(self, _s):
        raise AssertionError("a test must never sleep")


def run_ticks(monkeypatch, tmp_path, specs, n, *, phase="IDLE",
              observed=False, work=False, state=None, start_t=T0,
              past_grace=True):
    """n consecutive 60 s ticks with a controlled roster and clock."""
    clock = {"t": start_t}
    monkeypatch.setattr(ORCH, "time", _Clock(clock))
    monkeypatch.setattr(ORCH, "default_roster", lambda host: specs)
    monkeypatch.setattr(ORCH, "process_running", lambda name: observed)
    monkeypatch.setattr(ORCH, "first_work_seen", lambda name: work)
    monkeypatch.setattr(ORCH, "qualify_host", lambda **k: None)
    monkeypatch.setattr(ORCH, "phase_at", lambda t, s: {
        "phase": phase, "why": "fixed for the test", "trading_day": False,
        "half_day": False})
    monkeypatch.setattr(ORCH, "now", lambda: clock["t"])
    monkeypatch.setattr(ORCH, "LEDGER", tmp_path / "ledger.jsonl")
    if state is None:
        state = {"attempts": {}, "host": "cloud"}
        if past_grace:
            # already past every declared first-work deadline, so the
            # SESSION_MISSED_START verdict is exercised rather than skipped
            state["phase"] = phase
            state["phase_started"] = clock["t"].timestamp() - 7200
    out = None
    for _ in range(n):
        out = ORCH.tick(state, dry_run=True)
        clock["t"] = clock["t"] + timedelta(seconds=60)
    return state, out


# ------------------------------------------------- the bound itself
@pytest.mark.parametrize("ticks", [1, 2, 5, 60, 500, 1907, 3000])
def test_retained_history_is_bounded_however_long_the_incident_runs(
        monkeypatch, tmp_path, ticks):
    """1907 is the number observed in production before the tail window
    was exceeded. The retained history must not grow with it."""
    state, _ = run_ticks(monkeypatch, tmp_path, [supervised()], ticks)
    st = state["attempts"]["btc-paper"]
    hist = ORCH._attempt_history(st, "btc-paper")
    assert st["deferrals"]["count"] == ticks
    assert len(st["deferrals"]["recent"]) <= ORCH.MAX_DEFERRAL_DETAIL
    assert len(hist) <= ORCH.MAX_RECOVERY_ATTEMPTS + 1 + ORCH.MAX_DEFERRAL_DETAIL
    assert len(hist) <= 4                      # no real attempts here


def test_the_information_that_matters_survives_the_bound(monkeypatch, tmp_path):
    state, _ = run_ticks(monkeypatch, tmp_path, [supervised()], 1907)
    d = state["attempts"]["btc-paper"]["deferrals"]
    assert d["count"] == 1907
    assert d["first_utc"] == T0.isoformat()
    assert d["last_utc"] == (T0 + timedelta(seconds=60 * 1906)).isoformat()
    assert d["supervised_by"] == "systemd"
    summary = [h for h in ORCH._attempt_history(state["attempts"]["btc-paper"],
                                                "btc-paper")
               if h.get("kind") == "deferral_summary"]
    assert len(summary) == 1
    assert summary[0]["count"] == 1907
    assert summary[0]["first_utc"] == d["first_utc"]
    assert summary[0]["last_utc"] == d["last_utc"]
    assert summary[0]["detail_entries_retained"] == len(d["recent"])


def test_the_bounded_sample_keeps_the_first_and_the_most_recent(
        monkeypatch, tmp_path):
    """The first says when it went missing; the last say it still is."""
    state, _ = run_ticks(monkeypatch, tmp_path, [supervised()], 50)
    recent = state["attempts"]["btc-paper"]["deferrals"]["recent"]
    assert len(recent) == ORCH.MAX_DEFERRAL_DETAIL
    assert recent[0]["attempted_utc"] == T0.isoformat()
    assert recent[-1]["attempted_utc"] == (T0 + timedelta(seconds=60 * 49)).isoformat()
    assert recent[-2]["attempted_utc"] == (T0 + timedelta(seconds=60 * 48)).isoformat()


# --------------------------------- observations are not attempts
def test_deferrals_never_consume_the_recovery_allowance(monkeypatch, tmp_path):
    """A service the orchestrator DOES start must still get exactly
    MAX_RECOVERY_ATTEMPTS, no matter how long another one has deferred."""
    specs = [supervised(), self_started()]
    state, _ = run_ticks(monkeypatch, tmp_path, specs, 400)
    sup = state["attempts"]["btc-paper"]
    own = state["attempts"]["options-paper"]
    assert sup["deferrals"]["count"] == 400
    assert sup["recovery"] == [], "a deferral was recorded as an attempt"
    assert len(own["recovery"]) == ORCH.MAX_RECOVERY_ATTEMPTS
    assert own["deferrals"]["count"] == 0, "a start was recorded as a deferral"
    assert all(a["outcome"] == "DRY_RUN" for a in own["recovery"])


def test_deferrals_never_bypass_the_allowance_either(monkeypatch, tmp_path):
    """The reverse direction: a supervised service is never started, so
    its recovery list stays empty however long the incident lasts."""
    state, _ = run_ticks(monkeypatch, tmp_path, [supervised()], 1000)
    assert state["attempts"]["btc-paper"]["recovery"] == []


def test_a_self_started_service_stops_after_its_allowance(monkeypatch, tmp_path):
    state, _ = run_ticks(monkeypatch, tmp_path, [self_started()], 200)
    own = state["attempts"]["options-paper"]
    assert len(own["recovery"]) == ORCH.MAX_RECOVERY_ATTEMPTS == 3
    hist = ORCH._attempt_history(own, "options-paper")
    assert len(hist) == 3 and not any(h.get("kind") == "deferral_summary"
                                      for h in hist)


# ------------------------------------------------- record size
def test_the_serialised_record_stops_growing(monkeypatch, tmp_path):
    """The actual outage mechanism: every record carried the whole history,
    so records grew 135 bytes per tick until one exceeded the chain
    primitive's 262144-byte tail window.

    Each run_ticks call restarts its simulated clock, so phase_started is
    re-seeded into the past before every call. Otherwise elapsed goes
    negative, the verdict is WITHIN_GRACE, and the record measured would be
    one with no incident in it at all -- which would prove nothing."""
    from apex.governance.chain_ledger import INITIAL_TAIL_BYTES
    sizes, deferrals = [], []
    state = {"attempts": {}, "host": "cloud", "phase": "IDLE",
             "phase_started": T0.timestamp() - 7200}
    for n in (1, 10, 100, 1000, 2000):
        state["phase_started"] = T0.timestamp() - 7200
        state, out = run_ticks(monkeypatch, tmp_path, [supervised()], n,
                               state=state)
        assert out["incidents"], "no incident in the record being measured"
        sizes.append(len(json.dumps(out, sort_keys=True, default=str)))
        deferrals.append(state["attempts"]["btc-paper"]["deferrals"]["count"])
    assert deferrals == [1, 11, 111, 1111, 3111]
    # Two regimes, and only one of them is growth. Filling the bounded sample
    # from one entry to its cap costs a few hundred bytes ONCE. After that the
    # record is flat: 11 deferrals and 3111 deferrals differ only by the digits
    # of the count.
    assert sizes[0] < sizes[1], "the sample never filled: %s" % sizes
    assert max(sizes) - min(sizes) < 400, "one-time fill too large: %s" % sizes
    flat = sizes[1:]
    assert max(flat) - min(flat) < 20, "still growing with duration: %s" % sizes
    assert deferrals[-1] / deferrals[1] > 280      # 283x the deferrals ...
    assert max(flat) - min(flat) <= 4              # ... for 4 bytes
    assert max(sizes) < INITIAL_TAIL_BYTES / 10
    # for contrast, the old behaviour cost 135 bytes per deferral: 3111 of
    # them would have been about 420 KB, past the chain tail window
    assert 135 * deferrals[-1] > INITIAL_TAIL_BYTES
    assert max(sizes) < 135 * deferrals[-1] / 250


def test_record_size_is_bounded_for_a_fixed_incident_population(
        monkeypatch, tmp_path):
    """Five simultaneously missing supervised services, held for a long
    incident. Size is set by the POPULATION, not by the duration."""
    specs = [supervised("svc-%d" % i) for i in range(5)]
    short, out_short = run_ticks(monkeypatch, tmp_path, specs, 2)
    long_, out_long = run_ticks(monkeypatch, tmp_path, specs, 2500)
    assert out_short["incidents"] and out_long["incidents"]
    s = len(json.dumps(out_short, sort_keys=True, default=str))
    l = len(json.dumps(out_long, sort_keys=True, default=str))
    assert all(long_["attempts"]["svc-%d" % i]["deferrals"]["count"] == 2500
               for i in range(5))
    assert l - s < 2000, "size grew with duration: %d -> %d" % (s, l)
    assert l < 20000


# ------------------------------------------------- phase and recovery
def test_a_phase_transition_starts_a_new_incident_history(monkeypatch, tmp_path):
    state, _ = run_ticks(monkeypatch, tmp_path, [supervised()], 500,
                         phase="IDLE")
    assert state["attempts"]["btc-paper"]["deferrals"]["count"] == 500
    state, _ = run_ticks(monkeypatch, tmp_path, [supervised()], 3,
                         phase="RTH", state=state,
                         start_t=T0 + timedelta(hours=12))
    d = state["attempts"]["btc-paper"]["deferrals"]
    assert d["count"] == 3, "the phase change did not reset the history"
    assert d["first_utc"] == (T0 + timedelta(hours=12)).isoformat()
    assert state["phase"] == "RTH"


def test_recovery_stops_the_history_growing(monkeypatch, tmp_path):
    state, _ = run_ticks(monkeypatch, tmp_path, [supervised()], 100)
    assert state["attempts"]["btc-paper"]["deferrals"]["count"] == 100
    # the service comes back and produces work
    state, out = run_ticks(monkeypatch, tmp_path, [supervised()], 50,
                           observed=True, work=True, state=state)
    assert state["attempts"]["btc-paper"]["deferrals"]["count"] == 100
    assert out["incidents"] == []
    assert out["reconciliation"]["missing"] == []


def test_a_service_that_is_up_but_not_working_still_defers(monkeypatch, tmp_path):
    """Alive is not started. Observed-but-no-work must still be noticed,
    and must not be counted as a recovery attempt."""
    state, _ = run_ticks(monkeypatch, tmp_path, [supervised()], 10,
                         observed=True, work=False)
    st = state["attempts"]["btc-paper"]
    assert st["recovery"] == []
    # observed=True takes neither branch, so nothing is appended at all
    assert st["deferrals"]["count"] == 0
    hist = ORCH._attempt_history(st, "btc-paper")
    assert hist == []


# ------------------------------------------------- format and compatibility
def test_the_summary_entry_declares_what_it_is(monkeypatch, tmp_path):
    state, _ = run_ticks(monkeypatch, tmp_path, [supervised()], 20)
    hist = ORCH._attempt_history(state["attempts"]["btc-paper"], "btc-paper")
    summary = hist[0]
    assert summary["kind"] == "deferral_summary"
    assert summary["outcome"] == "DEFERRED_TO_SUPERVISOR"
    assert summary["detail"] == "systemd"
    assert "not recovery attempts" in summary["note"]
    # the sampled entries keep the ORIGINAL per-deferral shape
    for e in hist[1:]:
        assert set(e) == {"service", "attempted_utc", "outcome", "detail"}
        assert e["outcome"] == "DEFERRED_TO_SUPERVISOR"


def test_len_of_the_history_is_no_longer_the_deferral_count(monkeypatch, tmp_path):
    """The compatibility implication, pinned so it cannot surprise a reader:
    a consumer counting entries must now read `count` from the summary."""
    state, _ = run_ticks(monkeypatch, tmp_path, [supervised()], 900)
    hist = ORCH._attempt_history(state["attempts"]["btc-paper"], "btc-paper")
    assert len(hist) == 4
    summary = next(h for h in hist if h.get("kind") == "deferral_summary")
    assert summary["count"] == 900 != len(hist)


def test_the_incident_verdict_still_carries_evidence(monkeypatch, tmp_path):
    """Bounding the history must not empty the alarm."""
    state, out = run_ticks(monkeypatch, tmp_path, [supervised()], 200)
    assert len(out["incidents"]) == 1
    inc = out["incidents"][0]
    assert inc["verdict"] == "SESSION_MISSED_START"
    assert inc["severity"] == "CRITICAL"
    assert inc["recovery_attempts"], "evidence must ride with the alarm"
    assert inc["decision_power"] == "NONE_OPERATIONAL"
    summary = next(h for h in inc["recovery_attempts"]
                   if h.get("kind") == "deferral_summary")
    assert summary["count"] == 200


def test_the_ledger_record_is_appended_and_readable(monkeypatch, tmp_path):
    state, out = run_ticks(monkeypatch, tmp_path, [supervised()], 300)
    led = tmp_path / "ledger.jsonl"
    rows = [json.loads(x) for x in led.read_text().splitlines() if x.strip()]
    assert len(rows) == 300
    assert all(rows[i]["prev_hash"] == rows[i - 1]["entry_hash"]
               for i in range(1, len(rows)))
    assert max(len(json.dumps(r, sort_keys=True)) for r in rows) < 6000
