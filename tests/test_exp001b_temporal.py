"""ALPHA-EXP-001B temporal and economic semantics, against the reproduced
EXP-001 defects (results/si002_reproductions.json). Disposable fixtures.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apex.world_model import grader, sources
from apex.world_model.exp001 import registration as R1
from apex.world_model.exp001b import bars as B, models as M, run as R
from apex.world_model.exp001b import registration as REG
from apex.world_model.targets import OutcomeRecord

REPO = Path(__file__).resolve().parents[1]
PIN_EXP001_HASH = "1a3f55a522f7595f179033827ad10d87e873b7839f1cc08fb05624067c8f391c"
PIN_EXP001_PY = "11afb3428d0df660497b6c03e7f677edf6dfe8a23ebf990f07ccc2ce0eace6ea"
PIN_EXP001_JSON = "96ea6edc1f89dfc2a6c3188d30e460067c13ad0561b75feebdbe26c0dc803367"


def doc(day, *, start_utc, n, seed=1, signal=0.0, gap_after=None, gap_minutes=0):
    rng = random.Random(seed)
    t = datetime.fromisoformat("%sT%s:00+00:00" % (day, start_utc))
    px, bars, last, minute = 400.0, [], 0.0, 0
    for i in range(n):
        if gap_after is not None and i == gap_after:
            minute += gap_minutes
        r = signal * last + rng.gauss(0, 3e-4); last = r
        o = px * math.exp(rng.gauss(0, 5e-5)); px = px * math.exp(r)
        bars.append({"event_time_utc": (t + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": max(o, px) * 1.0001, "low": min(o, px) * 0.9999, "close": px,
                     "volume": 1000})
        minute += 1
    return {"source": "alpaca_sip_raw_1m", "bars": bars}


def lab(tmp_path, docs: dict):
    root = tmp_path / "lab"; root.mkdir(exist_ok=True)
    fx = {}
    for name, d in docs.items():
        p = root / name; p.write_text(json.dumps(d))
        fx[name] = {"source_class": "SYNTHETIC_FIXTURE", "sha256": sources.sha256_of(p), "generator": "t"}
    (root / "_PROVENANCE.json").write_text(json.dumps({"fixtures": fx}))
    return root


def load(root, name, day):
    return B.load_session(root / name, declared_class="SYNTHETIC_FIXTURE", fixture_root=root,
                          symbol="SPY", session_date=day)


def _hm(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M")


# ------------------------------------------------ session (F3)
def test_winter_session_keeps_exactly_the_regular_bars(tmp_path):
    root = lab(tmp_path, {"SPY_2019-01-15.json": doc("2019-01-15", start_utc="13:00", n=480)})  # 08:00-16:00 ET
    s = load(root, "SPY_2019-01-15.json", "2019-01-15")
    assert s["n_regular"] == 390 and _hm(s["rows"][0]["event_time"]) == "14:30"
    assert _hm(s["rows"][-1]["event_time"]) == "20:59"
    assert s["dropped_outside_session"] == {"before_open": 90, "after_close": 0}
    assert s["rows"][0]["minute"] == 0 and s["rows"][-1]["minute"] == 389


def test_summer_session_and_early_close(tmp_path):
    root = lab(tmp_path, {"SPY_2019-06-03.json": doc("2019-06-03", start_utc="13:00", n=480),
                          "SPY_2019-11-29.json": doc("2019-11-29", start_utc="13:30", n=390)})
    s = load(root, "SPY_2019-06-03.json", "2019-06-03")
    assert _hm(s["rows"][0]["event_time"]) == "13:30" and s["n_regular"] == 390
    e = load(root, "SPY_2019-11-29.json", "2019-11-29")
    assert e["n_regular"] == 210 and e["bounds"]["early_close"]
    assert _hm(e["rows"][-1]["event_time"]) == "17:59"
    assert e["dropped_outside_session"]["after_close"] == 120


def test_wrong_date_unaligned_and_non_session_are_refused(tmp_path):
    root = lab(tmp_path, {"a.json": doc("2019-01-16", start_utc="14:30", n=60),      # bars dated the 16th
                          "b.json": doc("2019-06-03", start_utc="13:30", n=60),
                          "c.json": doc("2019-07-04", start_utc="13:30", n=60)})
    with pytest.raises(B.BarsRefused, match="^SESSION_DATE_MISMATCH"):
        load(root, "a.json", "2019-01-15")
    d = json.loads((root / "b.json").read_text()); d["bars"][3]["event_time_utc"] = "2019-06-03T13:33:30Z"
    (root / "b.json").write_text(json.dumps(d))
    prov = json.loads((root / "_PROVENANCE.json").read_text())
    prov["fixtures"]["b.json"]["sha256"] = sources.sha256_of(root / "b.json")
    (root / "_PROVENANCE.json").write_text(json.dumps(prov))
    with pytest.raises(B.BarsRefused, match="^UNALIGNED_BAR"):
        load(root, "b.json", "2019-06-03")
    with pytest.raises(B.BarsRefused, match="^NOT_A_SESSION: HOLIDAY"):
        load(root, "c.json", "2019-07-04")


# ------------------------------------------------ horizon and missing bars (F4)
def test_missing_minutes_refuse_rows_instead_of_stretching_the_horizon(tmp_path):
    root = lab(tmp_path, {"g.json": doc("2019-06-04", start_utc="13:30", n=390, gap_after=100, gap_minutes=10)})
    s = load(root, "g.json", "2019-06-04")
    rows = B.observable_rows(s)
    tg = B.targets(s, rows)
    for r, (y, tk, why) in zip(rows, tg):
        if y is not None:
            assert tk - r["event_time"] == (REG.HORIZON_MINUTES + 1) * 60     # exactly 15 min + completion
    # rows whose t+15min lands in the gap have no target
    gap_start = rows[100]["event_time"] - 10 * 60
    in_gap = [why for r, (y, tk, why) in zip(rows, tg)
              if gap_start <= r["event_time"] + 15 * 60 < rows[100]["event_time"]]
    assert in_gap and all(w.startswith("MISSING_TARGET_BAR") for w in in_gap)
    # rows within 30 min after the gap cannot form features
    after = [r for r in rows if rows[100]["event_time"] <= r["event_time"] < rows[100]["event_time"] + 30 * 60]
    assert after and all(r["features"] is None and r["why"].startswith("MISSING_FEATURE_BARS") for r in after)
    later = [r for r in rows if r["event_time"] >= rows[100]["event_time"] + 30 * 60]
    assert later and all(r["features"] is not None for r in later)
    # nothing invented: every used price is a real bar's price
    assert sum(1 for r in rows if r["features"]) < len(rows)


def test_embargo_excludes_targets_reaching_the_close(tmp_path):
    root = lab(tmp_path, {"s.json": doc("2019-06-05", start_utc="13:30", n=390)})
    s = load(root, "s.json", "2019-06-05")
    rows = B.observable_rows(s); tg = B.targets(s, rows)
    tail = [why for r, (y, tk, why) in zip(rows, tg) if r["minute"] >= 390 - 30]
    assert tail and all(w.startswith("EMBARGO") for w in tail)


# ------------------------------------------------ clocks (F1, F2)
def test_forecast_and_outcome_use_completion_clocks(tmp_path):
    root = lab(tmp_path, {"s.json": doc("2019-06-05", start_utc="13:30", n=390)})
    s = load(root, "s.json", "2019-06-05")
    rows = B.observable_rows(s); tg = B.targets(s, rows)
    r = rows[60]; y, tk, _ = tg[60]
    assert r["bar_complete"] == r["event_time"] + 60 == r["assumed_available"]
    assert r["publication_time"] is None
    params = {"k": 1.0, "a": 0.0, "b1": 0.0, "b5": 0.0, "n_train": 0, "params_hash": "x"}
    fc = M.forecast(REG.M0["id"], params, r, input_id="i", input_hash="h", creation_time=0.0)
    assert fc.known_from == r["assumed_available"]                       # not the bar open
    assert fc.uncertainty_metadata["availability_basis"] == "ASSUMED_BAR_CLOSE"
    assert fc.uncertainty_metadata["publication_time"] == "NOT_AVAILABLE"
    assert tk == r["event_time"] + 16 * 60                                  # target bar's completion
    oc = OutcomeRecord(world_id="c", world_hash="t", subject="SPY", step=60, horizon=REG.HORIZON,
                       target_value=y, outcome_known_time=tk)
    g = grader.grade(fc, oc, grading_time=tk + 1.0)
    assert g.forecast_known_from < g.outcome_known_time
    # a forecast that claims its answer's clock is refused by the grader
    late = OutcomeRecord(world_id="c", world_hash="t", subject="SPY", step=60, horizon=REG.HORIZON,
                         target_value=y, outcome_known_time=fc.known_from)
    with pytest.raises(grader.GradingViolation):
        grader.grade(fc, late, grading_time=tk)
    with pytest.raises(ValueError, match="NO_AVAILABILITY_CLOCK"):
        M.forecast(REG.M0["id"], params, {**r, "assumed_available": None}, input_id="i", input_hash="h",
                   creation_time=0.0)


# ------------------------------------------------ run semantics (F5, F6, F7)
def _periods(tmp_path, signal):
    days = {"train": ["2019-06-03", "2019-06-04"], "validation": ["2020-06-01", "2020-06-02"],
            "evaluation": ["2022-06-01", "2022-06-02"]}
    docs = {"SPY_%s.json" % d: doc(d, start_utc="13:30", n=390, seed=1000 * ["train", "validation", "evaluation"].index(k) + i, signal=signal)
            for k, ds in days.items() for i, d in enumerate(ds)}
    root = lab(tmp_path, docs)
    sbp = {k: [str(root / ("SPY_%s.json" % d)) for d in ds] for k, ds in days.items()}

    def loader(p):
        name = Path(p).name
        return load(root, name, name[4:14])
    return root, sbp, loader


def test_validation_is_distributional_only_and_evaluation_stays_sealed(tmp_path):
    root, sbp, loader = _periods(tmp_path, 0.9)
    led = tmp_path / "run1"; led.mkdir()
    rec = R.run(sbp, ledger_dir=led, session_loader=loader)
    assert rec["validation_is_distributional_only"]
    assert "economic" not in rec["validation"]
    assert rec["status"] == "SEALED_EVALUATION_PENDING" and R.STATUS[rec["status"]] == "EVALUATION_SEALED"
    assert any(s["stage"] == "evaluation" and s["status"] == "SEALED" for s in rec["stages"])
    assert "evaluation" not in rec
    assert not (led / "forecasts_evaluation.jsonl").exists()
    with pytest.raises(FileNotFoundError):
        R.run(sbp, ledger_dir=tmp_path / "absent", session_loader=loader)


def test_no_signal_is_a_scientific_completion(tmp_path):
    root, sbp, loader = _periods(tmp_path, 0.0)
    led = tmp_path / "run2"; led.mkdir()
    rec = R.run(sbp, ledger_dir=led, session_loader=loader)
    assert rec["status"] in ("NO_SIGNAL", "SEALED_EVALUATION_PENDING")   # phi=0 -> NO_SIGNAL expected
    assert rec["validation"]["n0_is_no_signal"]
    assert "economic" not in rec["validation"]


def test_economics_only_on_unsealed_evaluation_under_next_bar_open(tmp_path):
    root, sbp, loader = _periods(tmp_path, 0.9)
    led = tmp_path / "run3"; led.mkdir()
    rec = R.run(sbp, ledger_dir=led, session_loader=loader, evaluation_unsealed=True)
    assert "economic" not in rec["validation"]
    econ = rec["evaluation"]["economic"]
    assert econ["stage"] == "EVALUATION_ONLY" and econ["execution_model"] == "NEXT_BAR_OPEN_PLUS_MODELLED_SPREAD"
    assert "certified_1R" not in econ and econ["certification"].startswith("NONE")
    assert rec["status"] in ("READY", "NO_OPPORTUNITY")


def test_economic_legs_follow_the_registered_convention(tmp_path):
    root = lab(tmp_path, {"s.json": doc("2019-06-05", start_utc="13:30", n=390, seed=5)})
    s = load(root, "s.json", "2019-06-05")
    rows = B.observable_rows(s); tg = B.targets(s, rows)
    i = 80; r = rows[i]
    legs = B.execution_legs(s, r)
    assert legs["entry_time"] == r["event_time"] + 60 and legs["exit_time"] == r["event_time"] + 16 * 60
    assert legs["decision_time"] == r["assumed_available"] == legs["entry_time"]
    params = {"k": 1.0, "a": 0.01, "b1": 0.0, "b5": 0.0, "n_train": 0, "params_hash": "x"}   # strong positive mu
    fc = M.forecast(REG.M1["id"], params, r, input_id="i", input_hash="h", creation_time=0.0)
    y, tk, _ = tg[i]
    econ = R.economic_evaluation([fc], [(r, y, tk)], [s])
    rt = 2 * REG.MODELLED_SPREAD_BPS / 1e4
    expect = math.log(legs["exit_open"] / legs["entry_open"]) - rt
    assert econ["n_active"] == 1
    assert math.isclose(econ["mean_after_cost"], expect, rel_tol=0, abs_tol=1e-15)
    assert abs(expect - (y - rt)) > 0                                        # differs from close-to-close
    # missing exit leg -> NOT_EXECUTABLE, counted, not imputed
    s2 = {**s, "rows": [x for x in s["rows"] if x["event_time"] != r["event_time"] + 16 * 60]}
    econ2 = R.economic_evaluation([fc], [(r, y, tk)], [s2])
    assert econ2["n_not_executable"] == 1 and econ2["status"] == "NO_OPPORTUNITY"


def test_no_field_is_named_certified_1R_with_a_number():
    src = (REPO / "apex/world_model/exp001b/run.py").read_text()
    assert '"certified_1R": None' in src and "stop_distance_rv30_diagnostic" in src
    assert "risk_certificate" not in src                       # no certification produced here


# ------------------------------------------------ governance preservation
def test_exp001_is_preserved_and_exp001b_supersedes_it_with_reasons():
    assert R1.registration_hash() == PIN_EXP001_HASH
    assert hashlib.sha256((REPO / "apex/world_model/exp001/registration.py").read_bytes()).hexdigest() == PIN_EXP001_PY
    assert hashlib.sha256((REPO / "results/exp001_registration.json").read_bytes()).hexdigest() == PIN_EXP001_JSON
    assert REG.registration_hash() != PIN_EXP001_HASH and REG.EXPERIMENT_ID == "ALPHA-EXP-001B"
    assert REG.SUPERSEDES["registration_hash"] == PIN_EXP001_HASH
    assert len(REG.SUPERSEDES["reproduced_defects"]) == 7 and REG.SUPERSEDES["real_outcomes_consulted"] is False
    assert REG.VALIDATION_IS_DISTRIBUTIONAL_ONLY and REG.ECONOMIC_STAGE.startswith("EVALUATION only")
    assert REG.SEARCH_BUDGET["horizons"] == 1
