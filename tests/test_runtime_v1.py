"""PULSE_V1 runtime wiring + scale tests.

The acceptance property: evidence may grow by orders of magnitude while
restore complexity, checkpoint size and RSS stay bounded.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from apex.pulse.checkpoint import UnboundedStateRefused
from apex.pulse.packet_root import verify
from apex.pulse.runtime_v1 import (PULSE_V1_VERSION, PulseV1Runtime,
                                   RuntimeViolation)

UTC = timezone.utc
T0 = datetime(2026, 9, 2, 13, 30, tzinfo=UTC)


def _packet(subject: str, t: datetime) -> dict:
    body = {"subject": subject, "scheduled_time": t.isoformat(),
            "schema_version": "MARKET_TWIN_STATE_V1",
            "features": {"mid": {"v": 100.0, "q": "VALID"}}}
    sid = hashlib.sha256(
        f"{subject}|{t.isoformat()}".encode()).hexdigest()[:32]
    body["state_id"] = sid
    body["packet_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body


def _composer(n=8):
    def compose(t, ck):
        out = []
        for i in range(n):
            p = _packet(f"SYM{i}", t)
            ck.rolling.observe(f"SYM{i}", t, 100.0 + i)
            out.append(p)
        return out
    return compose


def _rt(tmp_path, n=8, **kw):
    return PulseV1Runtime(results_dir=tmp_path,
                          compose_packets=_composer(n), **kw)


# ======================= RUNTIME WRITER ==============================
def test_cycle_persists_packets_and_commitment(tmp_path):
    rt = _rt(tmp_path)
    r = rt.run_cycle(T0)
    assert r.persisted
    assert len(r.packets) == 8
    assert r.commitment["packet_count"] == 8
    assert rt.ledger.exists() and rt.cycle_log.exists()
    assert rt.verify_cycle(T0)["VALID"]


def test_first_cycle_is_genesis(tmp_path):
    rt = _rt(tmp_path)
    r = rt.run_cycle(T0)
    assert r.commitment["prev_cycle_hash"] == "GENESIS"


def test_cycles_chain(tmp_path):
    rt = _rt(tmp_path)
    rt.run_cycle(T0)
    r2 = rt.run_cycle(T0 + timedelta(minutes=1))
    assert r2.commitment["prev_cycle_hash"] != "GENESIS"
    rows = [json.loads(x) for x in
            rt.cycle_log.read_text().splitlines() if x.strip()]
    assert rows[1]["prev_hash"] == rows[0]["entry_hash"]


def test_packets_carry_none_state(tmp_path):
    rt = _rt(tmp_path)
    r = rt.run_cycle(T0)
    assert all(p["decision_power"] == "NONE_STATE" for p in r.packets)
    assert all(p["pulse_version"] == PULSE_V1_VERSION for p in r.packets)


def test_packet_without_identity_is_refused(tmp_path):
    def bad(t, ck):
        return [{"subject": "X"}]
    rt = PulseV1Runtime(results_dir=tmp_path, compose_packets=bad)
    with pytest.raises(RuntimeViolation):
        rt.run_cycle(T0)


# ======================= PACKET ROOT WIRED ===========================
def test_tampering_a_persisted_packet_breaks_the_cycle(tmp_path):
    """The V0 gap, closed: substitution with count preserved."""
    rt = _rt(tmp_path)
    rt.run_cycle(T0)
    assert rt.verify_cycle(T0)["VALID"]

    rows = [json.loads(x) for x in
            rt.ledger.read_text().splitlines() if x.strip()]
    rows[3]["features"]["mid"]["v"] = 999.0
    rows[3]["packet_hash"] = hashlib.sha256(   # attacker recomputes
        json.dumps({k: v for k, v in rows[3].items()
                    if k != "packet_hash"}, sort_keys=True).encode()
    ).hexdigest()
    rt.ledger.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")

    r = rt.verify_cycle(T0)
    assert not r["VALID"]
    assert r["packet_count_matches"]        # count unchanged
    assert not r["packet_root_matches"]     # root moved


def test_deleting_a_persisted_packet_breaks_the_cycle(tmp_path):
    rt = _rt(tmp_path)
    rt.run_cycle(T0)
    rows = [json.loads(x) for x in
            rt.ledger.read_text().splitlines() if x.strip()]
    rt.ledger.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows[:-1])
        + "\n")
    assert not rt.verify_cycle(T0)["VALID"]


def test_inserting_a_packet_breaks_the_cycle(tmp_path):
    rt = _rt(tmp_path)
    rt.run_cycle(T0)
    extra = _packet("INTRUDER", T0)
    with rt.ledger.open("a") as fh:
        fh.write(json.dumps(extra, sort_keys=True) + "\n")
    assert not rt.verify_cycle(T0)["VALID"]


def test_reordering_persisted_packets_is_tolerated(tmp_path):
    """Canonical ordering by state_id: write order must not matter."""
    rt = _rt(tmp_path)
    rt.run_cycle(T0)
    rows = [json.loads(x) for x in
            rt.ledger.read_text().splitlines() if x.strip()]
    rt.ledger.write_text(
        "\n".join(json.dumps(r, sort_keys=True)
                  for r in reversed(rows)) + "\n")
    assert rt.verify_cycle(T0)["VALID"]


# ======================= BOUNDED RESTART =============================
def test_restart_uses_checkpoint_not_ledger(tmp_path):
    rt = _rt(tmp_path)
    for i in range(5):
        rt.run_cycle(T0 + timedelta(minutes=i))
    probe = rt.restore_cost_probe("2026-09-02")
    assert probe["restore_mode"] == "CHECKPOINT_LOADED"
    assert probe["reads_ledger"] is False


def test_missing_checkpoint_falls_back_to_bounded_rebuild(tmp_path):
    rt = _rt(tmp_path)
    rt.run_cycle(T0)
    rt.checkpoint_path.unlink()
    ck, mode = rt.restore("2026-09-02")
    assert "BOUNDED_REBUILD" in mode
    assert ck.rolling.cardinality() == 0     # clean, not full-history


def test_corrupt_checkpoint_falls_back_to_bounded_rebuild(tmp_path):
    rt = _rt(tmp_path)
    rt.run_cycle(T0)
    rt.checkpoint_path.write_text("{garbage")
    _, mode = rt.restore("2026-09-02")
    assert "BOUNDED_REBUILD" in mode


def test_checkpoint_stays_bounded_across_a_long_session(tmp_path):
    """390 cycles -- a full RTH session -- with a 60-minute window."""
    rt = _rt(tmp_path, n=8, rolling_window_minutes=60)
    sizes = []
    for i in range(390):
        r = rt.run_cycle(T0 + timedelta(minutes=i))
        sizes.append(r.checkpoint_bytes)
    assert sizes[-1] < 8 * 1024 * 1024
    # after the window fills, size must plateau rather than grow
    late = sizes[120:]
    assert max(late) <= min(late) * 1.35, (min(late), max(late))


def test_oversized_state_is_refused_not_silently_written(tmp_path):
    rt = _rt(tmp_path, n=200, max_checkpoint_bytes=16 * 1024)
    with pytest.raises(UnboundedStateRefused):
        for i in range(50):
            rt.run_cycle(T0 + timedelta(minutes=i))


# ======================= TRUE SLOT OCCUPANCY =========================
def test_lifecycle_points_are_recorded(tmp_path):
    rt = _rt(tmp_path)
    lc = rt.run_cycle(T0).lifecycle
    for f in ("service_start", "state_restore_complete", "capture_start",
              "capture_complete", "composition_complete",
              "persistence_complete", "service_exit"):
        assert getattr(lc, f) is not None, f


def test_true_occupancy_spans_restore_and_persist(tmp_path):
    """The region V0's metric could not see is inside V1's.

    Uses a slot in the PAST, as a real timer fire always is.
    """
    rt = _rt(tmp_path)
    slot = datetime.now(UTC) - timedelta(seconds=5)
    lc = rt.run_cycle(slot).lifecycle
    assert lc.true_slot_occupancy_s is not None
    assert lc.internal_work_s is not None
    assert not lc.clock_anomaly
    assert lc.true_slot_occupancy_s >= lc.internal_work_s


def test_negative_occupancy_is_flagged_not_praised(tmp_path):
    """A cycle finishing before its slot began must not read as the
    fastest cycle of the day."""
    rt = _rt(tmp_path)
    future = datetime.now(UTC) + timedelta(hours=12)
    lc = rt.run_cycle(future).lifecycle
    assert lc.true_slot_occupancy_s < 0
    assert lc.clock_anomaly is True


# ======================= SCALE =======================================
def test_restore_cost_independent_of_ledger_size(tmp_path):
    """THE acceptance property for PULSE-005."""
    rt = _rt(tmp_path)
    rt.run_cycle(T0)
    small = rt.restore_cost_probe("2026-09-02")

    # grow the append-only evidence by ~200x without touching state
    filler = json.dumps(_packet("FILLER", T0), sort_keys=True) + "\n"
    with rt.ledger.open("a") as fh:
        for _ in range(200_000):
            fh.write(filler)

    big = rt.restore_cost_probe("2026-09-02")
    assert big["ledger_bytes"] > 50 * small["ledger_bytes"]
    assert big["checkpoint_bytes"] == small["checkpoint_bytes"]
    # restore must not scale with the ledger
    assert big["restore_seconds"] < max(0.25,
                                        small["restore_seconds"] * 8)


def test_prev_hash_lookup_is_tail_only(tmp_path):
    """O(1) tail read, so cycle-log growth cannot re-create PULSE-005."""
    rt = _rt(tmp_path)
    for i in range(30):
        rt.run_cycle(T0 + timedelta(minutes=i))
    t0 = time.perf_counter()
    rt._prev_cycle_hash()
    assert (time.perf_counter() - t0) < 0.25
