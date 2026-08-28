"""Observation Lab commissioning — playback causality, tier fences,
contamination law, vocabulary bans, and trader non-interference.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import scripts.parallax_lab as LAB
from apex.organism import parallax as PX


def exp(sym="NVDA", de="POSITIVE"):
    return {"parallax_id": "PX_E1", "episode_id": "E1", "symbol": sym,
            "sector_etf": "XLK", "index_etf": "SPY",
            "beta_family": "US_LARGE_BETA",
            "event_time": "2026-08-28T13:55:00Z",
            "known_from": "2026-08-28T14:00:00Z",
            "expectation_created_at": "2026-08-28T14:00:00Z",
            "expected_direction": de,
            "expectation_vector": {}, "mechanism_basis": [],
            "uncertainty": [], "inputs_used": [],
            "support_independence": "UNKNOWN",
            "expectation_contract_sha": "abc",
            "sealed_pre_reaction": True,
            "headline": "h", "verification": "VERIFIED",
            "event_type": "EARNINGS",
            "decision_power": PX.AUTHORITY}


def bars(closes, *, start_m=1):
    out = []
    for i, c in enumerate(closes):
        m = start_m + i
        out.append({"event_time_utc":
                    f"2026-08-28T{14 + m // 60:02d}:{m % 60:02d}"
                    f":00.000Z",
                    "open": c, "high": c + 0.1, "low": c - 0.1,
                    "close": c, "volume": 9})
    return out


CLOSE = datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)


# ===================================================== CAUSAL FENCE

def test_checkpoint_sees_only_bars_before_it():
    """Tape: rallies 25 min then collapses. The 15m frame must
    classify from the rally alone -- if the collapse leaks in, the
    playback is hindsight theater."""
    tape = ([100 + i * 0.2 for i in range(25)]
            + [105 - i * 0.5 for i in range(35)])
    cache = {"NVDA": bars(tape), "XLK": [], "SPY": []}
    e = exp()
    cp15 = datetime(2026, 8, 28, 14, 15, tzinfo=timezone.utc)
    v15 = LAB._measure_at(e, cp15, CLOSE, lambda s: cache.get(s, []))
    vend = LAB._measure_at(e, CLOSE, CLOSE, lambda s: cache.get(s, []))
    assert v15["violation_class"] == "EXPECTED_REACTION"
    assert vend["violation_class"] in ("FAILED_POSITIVE_REACTION",
                                       "NO_IDENTIFIABLE_REACTION")


def test_measure_without_ledger_writes_nothing(tmp_path,
                                               monkeypatch):
    """Playback and previews measure without sealing; a default write
    to the canonical ledger would contaminate the prospective record."""
    monkeypatch.setattr(PX, "VIOLATIONS", tmp_path / "v.jsonl")
    cache = {"NVDA": bars([100 + i * 0.2 for i in range(30)]),
             "XLK": [], "SPY": []}
    LAB._measure_at(exp(), CLOSE, CLOSE, lambda s: cache.get(s, []))
    assert not (tmp_path / "v.jsonl").exists()


# ============================================== VOCABULARY FIREWALL

def test_rendered_output_contains_no_trade_language():
    cache = {"NVDA": bars([100 - i * 0.2 for i in range(30)]),
             "XLK": [], "SPY": []}
    v = LAB._measure_at(exp(), CLOSE, CLOSE,
                        lambda s: cache.get(s, []))
    out = LAB.render({"t": CLOSE, "stage": "SESSION_CLOSE",
                      "exp": exp(), "violation": v,
                      "provenance": "RETROSPECTIVE_PARALLAX"
                                    "_DERIVATION"})
    up = out.upper()
    for banned in ("BUY", "SELL", " LONG", "SHORT", "ATTACK",
                   "POSITION SIZE", "TRADE NOW"):
        assert banned not in up, f"console displays {banned!r}"
    assert "CAPITAL VISIBILITY: FORBIDDEN" in out


# ============================================ PREVIEW VS CANONICAL

def test_preview_is_labeled_and_appends_only_on_change(tmp_path,
                                                       monkeypatch):
    monkeypatch.setattr(LAB, "PREVIEWS", tmp_path / "p.jsonl")
    cache = {"NVDA": bars([100 - i * 0.2 for i in range(30)]),
             "XLK": [], "SPY": []}
    v = LAB._measure_at(exp(), CLOSE, CLOSE,
                        lambda s: cache.get(s, []))
    item = {"violation": v}
    LAB._record_preview(item)
    LAB._record_preview(item)             # unchanged -> no new row
    rows = [json.loads(l) for l in
            (tmp_path / "p.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["label"] == "PARALLAX_LIVE_PREVIEW"
    assert "never replace or mutate the canonical" in rows[0]["law"]


# =================================================== TIER FENCES

def test_stats_tiers_are_never_pooled(tmp_path, monkeypatch,
                                      capsys):
    monkeypatch.setattr(PX, "VIOLATIONS", tmp_path / "v.jsonl")
    monkeypatch.setattr(LAB, "PREVIEWS", tmp_path / "p.jsonl")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results/parallax").mkdir(parents=True)
    LAB.cmd_stats(None)
    out = capsys.readouterr().out
    for tier in ("PROSPECTIVE", "RETROSPECTIVE_COMMISSIONING",
                 "MODEL_TIME_CONTAMINATED", "LIVE_PREVIEW"):
        assert tier in out
    assert "NEVER pooled" in out
    assert "PARALLAX_EDGE = NOT_ESTIMABLE" in out


def test_independence_stays_not_estimable_in_stats(tmp_path,
                                                   monkeypatch,
                                                   capsys):
    led = tmp_path / "v.jsonl"
    monkeypatch.setattr(PX, "VIOLATIONS", led)
    monkeypatch.setattr(LAB, "PREVIEWS", tmp_path / "p.jsonl")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results/parallax").mkdir(parents=True)
    led.write_text(json.dumps({
        "kind": "parallax_violation", "eligible": True,
        "violation_class": "FAILED_POSITIVE_REACTION",
        "expectation_debt": "HIGH", "episode_id": "E1",
        "symbol": "NVDA", "known_from": "2026-08-28T14:00:00Z",
        "signed_return": -0.01}) + "\n")
    LAB.cmd_stats(None)
    out = capsys.readouterr().out
    assert "independent episodes NOT_ESTIMABLE" in out


# ========================================= CONTAMINATION LAW

def test_contaminated_mode_is_refused_without_the_flag(capsys):
    class A:
        mode = "contaminated"
        allow_model_time_contaminated = False
        session = None
    rc = LAB.cmd_historical(A())
    out = capsys.readouterr().out
    assert rc == 3
    assert "MODEL TIME CONTAMINATION LAW" in out
    assert "This law is permanent" in out


def test_contaminated_mode_with_flag_warns_and_wires_no_generator(
        capsys):
    class A:
        mode = "contaminated"
        allow_model_time_contaminated = True
        session = None
    rc = LAB.cmd_historical(A())
    out = capsys.readouterr().out
    assert rc == 0
    assert "WARNING" in out
    assert "generation is intentionally absent" in out


# ====================================== TRADER NON-INTERFERENCE

def test_nothing_on_a_trading_path_imports_the_lab():
    for mod in list(Path("apex/predators").rglob("*.py")) + [
            Path("apex/organism/allocator.py"),
            Path("apex/organism/book.py"),
            Path("apex/organism/risk_kernel.py"),
            Path("apex/capital/arena.py"),
            Path("apex/catalyst/pipeline.py"),
            Path("scripts/options_paper_session.py"),
            Path("scripts/equity_shadow_session.py"),
            Path("scripts/organism_service.py"),
            Path("scripts/catalyst_service.py")]:
        for n in ast.walk(ast.parse(mod.read_text())):
            mods = ([a.name for a in n.names]
                    if isinstance(n, ast.Import)
                    else [n.module or ""]
                    if isinstance(n, ast.ImportFrom) else [])
            assert not any("parallax_lab" in m for m in mods), \
                f"{mod} depends on the observation lab"


def test_commissioning_reruns_are_deduped_not_summed(tmp_path,
                                                     monkeypatch,
                                                     capsys):
    """Three append-only runs of the same 2 observations must report
    2, not 6 -- the latest (corrected) row per id wins."""
    monkeypatch.setattr(PX, "VIOLATIONS", tmp_path / "v.jsonl")
    monkeypatch.setattr(LAB, "PREVIEWS", tmp_path / "p.jsonl")
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "results/parallax"
    d.mkdir(parents=True)
    rows = []
    # run 1: three observations, one later found ineligible; run 2
    # (corrected): only two. The canonical view must show run 2 alone
    # -- a per-id dedupe cannot retract PX_C.
    for run, ids in ((1, ("PX_A", "PX_B", "PX_C")),
                     (2, ("PX_A", "PX_B"))):
        for pid in ids:
            rows.append(json.dumps({
                "kind": "parallax_violation", "eligible": True,
                "parallax_id": pid, "episode_id": pid,
                "symbol": "NVDA",
                "known_from": "2026-08-28T14:00:00Z",
                "violation_class": "FAILED_POSITIVE_REACTION"
                if run == 2 else "EXPECTED_REACTION",
                "expectation_debt": "HIGH"}))
        rows.append(json.dumps({"kind": "parallax_session_pass",
                                "session": "2026-08-28"}))
    (d / "commissioning.jsonl").write_text("\n".join(rows) + "\n")
    LAB.cmd_stats(None)
    out = capsys.readouterr().out
    assert "raw observations     2" in out
    assert "FAILED_POSITIVE_REACTION         2" in out
    assert "EXPECTED_REACTION" not in out.split(
        "RETROSPECTIVE_COMMISSIONING")[1].split("==")[0]


def test_spec_freeze_hashes_the_actual_rules():
    f1 = LAB.spec_freeze()
    f2 = LAB.spec_freeze()
    assert f1["taxonomy_sha256"] == f2["taxonomy_sha256"]
    assert len(f1["parallax_source_sha256"]) == 64
