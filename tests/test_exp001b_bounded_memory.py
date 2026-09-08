"""Old versus new equivalence for the bounded-memory repair.

The repair must change memory, not arithmetic. These tests run the PRE-REPAIR
run() and the repaired run() over identical deterministic fixtures and require
the sealed forecasts and the final statistics to agree, not merely the counts.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from apex.world_model.exp001b import bars as B, run as NEW
from apex.world_model.exp001b import exchange_calendar as C

FIXED_TIME = 1_700_000_000.0
OLD_SRC = Path(__file__).parent / "fixtures" / "exp001b" / "run_pre_bounded_memory.py"


def load_old():
    """Import the pre-repair module inside the real package so its relative
    imports resolve to the same bars/models/grader the new one uses."""
    spec = importlib.util.spec_from_file_location("apex.world_model.exp001b._run_old", OLD_SRC)
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "apex.world_model.exp001b"
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def doc(day, n, seed):
    rng = random.Random(seed)
    t = datetime.fromisoformat("%sT14:30:00+00:00" % day)
    px, bars = 400.0, []
    for i in range(n):
        r = rng.gauss(0, 3e-4)
        o = px * math.exp(rng.gauss(0, 5e-5)); px = px * math.exp(r)
        bars.append({"event_time_utc": (t + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": max(o, px) * 1.0001, "low": min(o, px) * 0.9999,
                     "close": px, "volume": 1000})
    return {"source": "alpaca_sip_raw_1m", "bars": bars}


def trading_days(start: str, count: int):
    out, k = [], 0
    d0 = datetime.fromisoformat(start)
    while len(out) < count:
        day = (d0 + timedelta(days=k)).strftime("%Y-%m-%d"); k += 1
        try:
            C.session_bounds(day, require_verified=True)
            out.append(day)
        except Exception:
            continue
    return out


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "fx"; root.mkdir()
    days = trading_days("2020-01-06", 34)
    fx = {}
    for i, day in enumerate(days):
        p = root / ("SYN_%s.json" % day)
        p.write_text(json.dumps(doc(day, 390, seed=i + 1)))
        fx[p.name] = {"source_class": "SYNTHETIC_FIXTURE",
                      "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "generator": "equiv"}
    (root / "_PROVENANCE.json").write_text(json.dumps({"fixtures": fx}))
    return {"root": root, "train": days[:24], "validation": days[24:]}


def loader_for(root):
    def load(p):
        day = Path(p).stem.replace("SYN_", "")
        return B.load_session(Path(p), declared_class="SYNTHETIC_FIXTURE", fixture_root=root,
                              symbol="SPY", session_date=day)
    return load


def execute(module, corpus, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    root = corpus["root"]
    sessions = {"train": [root / ("SYN_%s.json" % d) for d in corpus["train"]],
                "validation": [root / ("SYN_%s.json" % d) for d in corpus["validation"]],
                "evaluation": []}
    real = time.time
    time.time = lambda: FIXED_TIME          # creation_time must not differ between runs
    try:
        rec = module.run(sessions, ledger_dir=out_dir, session_loader=loader_for(root), seed=7)
    finally:
        time.time = real
    ledgers = {p.name: p.read_text() for p in sorted(out_dir.iterdir()) if p.is_file()}
    return rec, ledgers


def test_sealed_forecasts_are_byte_identical(tmp_path, corpus):
    old_rec, old_led = execute(load_old(), corpus, tmp_path / "old")
    new_rec, new_led = execute(NEW, corpus, tmp_path / "new")
    assert old_rec["status"] not in ("INVALID_INPUT",), old_rec
    name = "forecasts_validation.jsonl"
    assert name in old_led and name in new_led
    assert old_led[name].count("\n") > 100, "fixture must exercise a real number of rows"
    assert new_led[name] == old_led[name], "sealed forecasts differ"
    # the hash chain over them is therefore identical too
    assert hashlib.sha256(new_led[name].encode()).hexdigest() == \
           hashlib.sha256(old_led[name].encode()).hexdigest()


def test_final_statistics_are_identical_not_merely_the_counts(tmp_path, corpus):
    old_rec, _ = execute(load_old(), corpus, tmp_path / "old")
    new_rec, _ = execute(NEW, corpus, tmp_path / "new")
    assert new_rec["status"] == old_rec["status"]
    ov, nv = old_rec["validation"], new_rec["validation"]
    assert nv["n"] == ov["n"]
    for stat in ("dm", "n0"):
        assert set(nv[stat]) == set(ov[stat]), stat
        for k, v in ov[stat].items():
            got = nv[stat][k]
            if isinstance(v, float):
                assert got == v or math.isclose(got, v, rel_tol=0, abs_tol=0), \
                    "%s.%s differs: %r -> %r" % (stat, k, v, got)
            else:
                assert got == v, "%s.%s differs: %r -> %r" % (stat, k, v, got)
    assert nv["n0_is_no_signal"] == ov["n0_is_no_signal"]


def test_the_whole_record_agrees_apart_from_timing(tmp_path, corpus):
    old_rec, _ = execute(load_old(), corpus, tmp_path / "old")
    new_rec, _ = execute(NEW, corpus, tmp_path / "new")

    def scrub(d):
        d = json.loads(json.dumps(d, default=str))
        d.pop("elapsed_s", None)
        return d
    assert scrub(new_rec) == scrub(old_rec)


def test_the_outcomes_ledger_agrees(tmp_path, corpus):
    _, old_led = execute(load_old(), corpus, tmp_path / "old")
    _, new_led = execute(NEW, corpus, tmp_path / "new")
    assert new_led["outcomes.jsonl"] == old_led["outcomes.jsonl"]


def test_the_repair_does_not_retain_forecasts_for_a_validation_run(tmp_path, corpus):
    """The mechanism of the fix, asserted directly rather than inferred from a
    memory number: a validation run keeps no forecast list."""
    new_rec, _ = execute(NEW, corpus, tmp_path / "new")
    assert "_f1" not in new_rec["validation"]
    assert "_f1" not in json.dumps(new_rec)
