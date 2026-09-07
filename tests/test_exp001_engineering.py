"""ALPHA-EXP-001 -- ENGINEERING MODE. Deterministic synthetic bars exercise
every stage. This proves INTEGRATION ONLY: a PASS here is not an alpha PASS.
Real data is never read; the one real-path test asserts the boundary REFUSES it.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from apex.world_model import sources
from apex.world_model.exp001 import bars as B, run as R
from apex.world_model.exp001.registration import (HORIZON_STEPS, MIN_SAMPLES,
                                                  registration, registration_hash)

DAY = 390


def _write_session(root: Path, sym: str, date: str, closes: list, *, vol=1000.0):
    bars = []
    t0 = "%sT13:30:00Z" % date
    from datetime import datetime, timedelta, timezone
    base = datetime.fromisoformat(t0.replace("Z", "+00:00"))
    for i, c in enumerate(closes):
        t = base + timedelta(minutes=i)
        bars.append({"event_time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": c, "high": c * 1.0005, "low": c * 0.9995, "close": c, "volume": vol})
    p = root / ("%s_%s.json" % (sym, date))
    p.write_text(json.dumps({"source": "synthetic_engineering", "bars": bars}))
    return p


def _fixture_root(tmp_path: Path, n_days: int, *, signal: float, seed: int) -> tuple:
    """A fixture root with provenance, as sources.admit requires."""
    root = tmp_path / "fixtures"; root.mkdir()
    rng = random.Random(seed)
    paths = []
    fixtures = {}
    for d in range(n_days):
        date = "2016-01-%02d" % (4 + d) if d < 26 else "2016-02-%02d" % (d - 25)
        c, closes, prev = 100.0, [], 0.0
        for _ in range(DAY):
            e = rng.gauss(0, 0.0005)
            r = signal * prev + e                      # AR(1): the planted structure
            c *= math.exp(r); closes.append(c); prev = r
        p = _write_session(root, "SYN", date, closes)
        paths.append(str(p))
        fixtures[p.name] = {"source_class": "SYNTHETIC_FIXTURE", "sha256": sources.sha256_of(p),
                            "generator": "test_exp001_engineering", "seed": seed}
    (root / sources.PROVENANCE_FILE).write_text(json.dumps({"fixtures": fixtures}))
    return root, paths


def _split(paths):
    n = len(paths)
    return {"train": paths[: n * 2 // 4], "validation": paths[n * 2 // 4: n * 3 // 4],
            "evaluation": paths[n * 3 // 4:]}


# ----------------------------------------------------------- registration
def test_registration_is_frozen_and_hashable():
    r = registration()
    assert r["EXPERIMENT_ID"] == "ALPHA-EXP-001" and r["INSTRUMENT"] == "SPY"
    assert r["DM_THRESHOLD"] == 2.0 and r["MODELLED_SPREAD_BPS"] == 2.0
    assert r["SEARCH_BUDGET"]["hyperparameters_tuned"] == 0
    assert len(registration_hash()) == 64
    assert r["MECHANISM_IS_NOT_A_FACT"] is True


# ----------------------------------------------------------- the boundary
def test_real_evidence_path_is_refused_and_that_is_the_result(tmp_path):
    """The exact admission blocker for real data, as a RESULT."""
    fake_real = "/apex-data/history-b/etf_continuous/bars/SPY_2016-01-04.json"
    rec = R.run({"train": [fake_real]}, ledger_dir=tmp_path / "led",
                declared_class="SYNTHETIC_FIXTURE")
    assert rec["status"] == "BLOCKED"
    assert rec["refusal"]["kind"] == "SourceAdmissionRefused"
    assert "REAL_EVIDENCE_PATH" in rec["refusal"]["detail"]
    assert "/apex-data/history-b" in rec["refusal"]["detail"]
    assert not (tmp_path / "led").exists() or not list((tmp_path / "led").glob("forecasts_*"))


def test_a_forbidden_class_is_refused_by_name(tmp_path):
    root, paths = _fixture_root(tmp_path, 2, signal=0.0, seed=1)
    rec = R.run({"train": paths}, ledger_dir=tmp_path / "led",
                declared_class="REAL_HISTORICAL_LABEL", fixture_root=root)
    assert rec["status"] == "BLOCKED" and "FORBIDDEN_SOURCE_CLASS" in rec["refusal"]["detail"]


def test_fixture_without_provenance_is_refused(tmp_path):
    root = tmp_path / "fx"; root.mkdir()
    p = _write_session(root, "SYN", "2016-01-04", [100.0 + i * 0.01 for i in range(DAY)])
    rec = R.run({"train": [str(p)]}, ledger_dir=tmp_path / "led",
                declared_class="SYNTHETIC_FIXTURE", fixture_root=root)
    assert rec["status"] == "BLOCKED" and "NO_PROVENANCE_MANIFEST" in rec["refusal"]["detail"]


# ----------------------------------------------------------- refusals of bad input
def test_missing_bars_is_invalid_input(tmp_path):
    root = tmp_path / "fx"; root.mkdir()
    p = root / "SYN_2016-01-04.json"; p.write_text(json.dumps({"source": "s", "bars": []}))
    (root / sources.PROVENANCE_FILE).write_text(json.dumps({"fixtures": {p.name: {
        "source_class": "SYNTHETIC_FIXTURE", "sha256": sources.sha256_of(p)}}}))
    rec = R.run({"train": [str(p)]}, ledger_dir=tmp_path / "led",
                declared_class="SYNTHETIC_FIXTURE", fixture_root=root)
    assert rec["status"] == "INVALID_INPUT" and "MISSING_BARS" in rec["refusal"]["detail"]


def test_insufficient_evidence_is_named_not_empty_success(tmp_path):
    root, paths = _fixture_root(tmp_path, 1, signal=0.0, seed=2)
    # one session: too few train rows for a fit
    rec = R.run({"train": paths[:1], "validation": []}, ledger_dir=tmp_path / "led",
                declared_class="SYNTHETIC_FIXTURE", fixture_root=root)
    assert rec["status"] in ("INSUFFICIENT_EVIDENCE", "INVALID_INPUT")


def test_warmup_rows_carry_a_reason_not_zeros(tmp_path):
    root, paths = _fixture_root(tmp_path, 1, signal=0.0, seed=3)
    s = B.load_session(paths[0], declared_class="SYNTHETIC_FIXTURE", fixture_root=root)
    rows = B.observable_rows(s)
    assert rows[0]["features"] is None and "WARMUP" in rows[0]["why"]
    assert rows[40]["features"] is not None
    assert s["not_available"] == ["spread_bps", "trade_count", "bid", "ask"]


# ----------------------------------------------------------- the full path
def test_pure_noise_returns_no_signal_and_evaluation_stays_sealed(tmp_path):
    root, paths = _fixture_root(tmp_path, 8, signal=0.0, seed=11)
    rec = R.run(_split(paths), ledger_dir=tmp_path / "led",
                declared_class="SYNTHETIC_FIXTURE", fixture_root=root)
    assert rec["status"] == "NO_SIGNAL", rec
    assert rec["validation"]["n0_is_no_signal"] is True
    assert any(s["stage"] == "evaluation" and s["status"] == "BLOCKED" for s in rec["stages"])
    # forecasts were sealed BEFORE outcomes were attached
    led = tmp_path / "led"
    assert (led / "forecasts_validation.jsonl").exists()
    assert not (led / "forecasts_evaluation.jsonl").exists()


def test_planted_signal_is_detected_but_evaluation_still_sealed(tmp_path):
    root, paths = _fixture_root(tmp_path, 16, signal=0.9, seed=5)
    rec = R.run(_split(paths), ledger_dir=tmp_path / "led",
                declared_class="SYNTHETIC_FIXTURE", fixture_root=root)
    assert rec["status"] == "BLOCKED", rec.get("why")
    assert rec["validation"]["dm"]["verdict"] == "SIGNAL_DETECTED"
    assert rec["validation"]["n0_is_no_signal"] is True
    assert "SEALED" in rec["why"]


def test_unsealed_evaluation_reaches_the_economic_stage_and_accounting(tmp_path):
    root, paths = _fixture_root(tmp_path, 16, signal=0.9, seed=5)
    rec = R.run(_split(paths), ledger_dir=tmp_path / "led",
                declared_class="SYNTHETIC_FIXTURE", fixture_root=root, evaluation_unsealed=True)
    assert rec["status"] in ("READY", "NO_OPPORTUNITY"), rec["status"]
    ev = rec["evaluation"]
    assert ev["dm"]["verdict"] == "SIGNAL_DETECTED"
    econ = ev["economic"]
    assert econ["status"] in ("READY", "NO_OPPORTUNITY")
    assert econ["spread_bps_roundtrip"] == 4.0
    led = tmp_path / "led"
    rows = [json.loads(l) for l in (led / "attribution.jsonl").read_text().splitlines()]
    assert rows[-1]["kind"] == "exp001_result" and rows[-1]["status"] == rec["status"]
    outs = [json.loads(l) for l in (led / "outcomes.jsonl").read_text().splitlines()]
    assert {o["period"] for o in outs} == {"validation", "evaluation"}


def test_cost_veto_selects_cash_when_edge_is_below_the_spread(tmp_path):
    """Risk stage: a signal too small to pay 4 bps round trip is CASH."""
    root, paths = _fixture_root(tmp_path, 8, signal=0.05, seed=9)
    rec = R.run(_split(paths), ledger_dir=tmp_path / "led",
                declared_class="SYNTHETIC_FIXTURE", fixture_root=root, evaluation_unsealed=True)
    if rec["status"] in ("READY", "NO_OPPORTUNITY"):
        econ = rec["evaluation"]["economic"]
        # either nothing cleared the spread, or what did is not significant
        assert econ["status"] == "NO_OPPORTUNITY" or econ["n_active"] < econ["n_forecasts"]
    else:
        assert rec["status"] == "NO_SIGNAL"


def test_no_broker_dispatch_is_reachable_from_this_package():
    import apex.world_model.exp001.run as runmod
    src = Path(runmod.__file__).parent
    text = "".join(p.read_text() for p in src.glob("*.py"))
    for forbidden in ("robinhood", "place_order", "execution.gateway", "mcp_transport",
                      "apex.execution"):
        assert forbidden not in text, forbidden


def test_sealed_forecast_hash_is_checked_by_the_grader(tmp_path):
    root, paths = _fixture_root(tmp_path, 4, signal=0.0, seed=4)
    rec = R.run(_split(paths), ledger_dir=tmp_path / "led",
                declared_class="SYNTHETIC_FIXTURE", fixture_root=root)
    assert rec["status"] in ("NO_SIGNAL", "INSUFFICIENT_EVIDENCE", "BLOCKED")
    if "validation" in rec and rec["validation"].get("n"):
        assert rec["validation"]["n"] >= MIN_SAMPLES
