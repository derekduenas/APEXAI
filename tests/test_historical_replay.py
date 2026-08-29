"""Phase 0 commissioning — adapter integrity, causal truncation,
poison invisibility, determinism, world separation.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import scripts.historical_replay as HR


def corpus_day(tmp_path, sym="SPY", date="2019-03-05", n=200,
               drift=0.05):
    d = tmp_path / "corpus" / sym
    d.mkdir(parents=True)
    bars = []
    for i in range(n):
        h, m = 13 + (i + 35) // 60, (i + 35) % 60
        px = 280 + i * drift
        bars.append({"t": f"2019-03-05T{h:02d}:{m:02d}:00Z",
                     "o": px, "h": px + 0.1, "l": px - 0.1, "c": px,
                     "v": 60_000, "n": 5, "vw": px})
    (d / "underlying_20190305.json.gz").write_bytes(
        gzip.compress(json.dumps({"bars": bars}).encode()))
    return tmp_path / "corpus"


def test_adapter_reports_the_full_denominator(tmp_path):
    c = corpus_day(tmp_path)
    r = HR.adapt("SPY", "2019-03-05", corpus=c,
                 out_root=tmp_path / "bars")
    assert r["adapted"] and r["succeeded"] == 200 and r["failed"] == 0
    out = json.loads((tmp_path / "bars" / "SPY_2019-03-05.json")
                     .read_text())
    b0 = out["bars"][0]
    assert set(b0) == {"event_time_utc", "open", "high", "low",
                       "close", "volume"}


def test_adapter_rejects_nonmonotonic_and_malformed_rows(tmp_path):
    c = corpus_day(tmp_path)
    src = c / "SPY" / "underlying_20190305.json.gz"
    d = json.loads(gzip.decompress(src.read_bytes()))
    d["bars"].insert(50, d["bars"][10])          # out of order
    d["bars"].insert(60, {"t": "2019-03-05T15:00:00Z"})  # malformed
    src.write_bytes(gzip.compress(json.dumps(d).encode()))
    r = HR.adapt("SPY", "2019-03-05", corpus=c,
                 out_root=tmp_path / "bars")
    assert r["failed"] == 2 and r["succeeded"] == 200


def test_replay_labels_and_world_separation(tmp_path):
    c = corpus_day(tmp_path)
    HR.adapt("SPY", "2019-03-05", corpus=c, out_root=tmp_path / "bars")
    dled = tmp_path / "d.jsonl"
    oled = tmp_path / "o.jsonl"
    r = HR.replay_session("SPY", "2019-03-05",
                          bars_root=tmp_path / "bars",
                          decisions_ledger=dled, outcomes_ledger=oled)
    assert r["replayed"] and r["ticks"] > 0
    row = json.loads(dled.read_text().splitlines()[0])
    assert row["kind"] == "historical_decision"
    assert row["evidence_class"] == "STRATIFIED_HISTORICAL_DIAGNOSTIC"
    assert row["era"] == "DISCOVERY"
    # never the prospective field's ledgers, never the outbox
    assert not Path("results/equities/field/decisions.jsonl").exists()
    src = Path(HR.__file__).read_text()
    assert "outbox_emit" not in src


def test_h0_passes_on_clean_data_and_proves_all_three_fences(
        tmp_path):
    c = corpus_day(tmp_path)
    rep = HR.h0("SPY", "2019-03-05", corpus=c,
                scratch=tmp_path / "h0")
    assert rep["verdict"] == "PASS"
    assert rep["deterministic"] is True
    assert rep["future_bar_ignored"] is True
    assert rep["poison_field_invisible"] is True


def test_below_floor_sessions_are_sealed_reasons_not_dropped(
        tmp_path):
    c = corpus_day(tmp_path)
    src = c / "SPY" / "underlying_20190305.json.gz"
    d = json.loads(gzip.decompress(src.read_bytes()))
    for b in d["bars"]:
        b["v"] = 100                              # thin
    src.write_bytes(gzip.compress(json.dumps(d).encode()))
    HR.adapt("SPY", "2019-03-05", corpus=c, out_root=tmp_path / "bars")
    r = HR.replay_session("SPY", "2019-03-05",
                          bars_root=tmp_path / "bars",
                          decisions_ledger=tmp_path / "d.jsonl",
                          outcomes_ledger=tmp_path / "o.jsonl")
    assert r["replayed"] is False
    assert r["why"] == "below incumbent floor"
