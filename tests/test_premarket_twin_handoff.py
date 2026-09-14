"""Production premarket -> Twin -> persisted decision, entirely synthetic."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from apex.audit import premarket_fixture as FX
from apex.frontier import premarket_stages as PS
from apex.pulse_options.premarket_context import read_context
from apex.options_pilot.clock import Clock

REPO = Path(__file__).resolve().parents[1]
NOW = FX.et_epoch(9, 35)


@pytest.fixture(scope="module")
def morning(tmp_path_factory):
    work = tmp_path_factory.mktemp("premarket-handoff")
    FX.install_world(repo_root=work)
    root = work / "packets"
    env = {k: v for k, v in os.environ.items() if not k.startswith("APEX_PREMARKET_")}
    env.update(APEX_PREMARKET_ROOT=str(root),
               APEX_PREMARKET_TRANSPORT="apex.audit.premarket_fixture:transport",
               APEX_PREMARKET_CAPTAIN="apex.audit.premarket_fixture:captain", PYTHONPATH=str(REPO))
    from datetime import datetime, timezone
    for stage, h, m in PS.STAGE_SCHEDULE:
        env["APEX_PREMARKET_NOW"] = datetime.fromtimestamp(FX.et_epoch(h, m), timezone.utc).isoformat()
        r = subprocess.run([sys.executable, str(REPO / "scripts/premarket_stage.py"), "--stage", stage],
                           cwd=work, env=env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stdout + r.stderr
    assert (root / (FX.TRADING_DATE + ".json")).exists()
    return root


def read(root, now=NOW):
    return read_context(root=root, symbol="SPY", as_of=now, snapshot_id="test-snapshot", clock=Clock(lambda: now))


def rewrite(root, packet, reseal=True):
    if reseal:
        packet["packet_sha256"] = hashlib.sha256(json.dumps(
            {k: v for k, v in packet.items() if k != "packet_sha256"}, sort_keys=True).encode()).hexdigest()
    root.mkdir(exist_ok=True)
    (root / (FX.TRADING_DATE + ".json")).write_text(json.dumps(packet))


def test_production_packet_arrives_with_blind_spots_and_time(morning):
    ctx = read(morning)
    assert ctx["status"] == "ATTACHED_CONTEXT", ctx
    assert ctx["packet"]["blind_spots"]
    assert ctx["packet_known_from"] == FX.et_epoch(9, 25)
    assert ctx["data_cutoff_epoch"] == FX.et_epoch(9, 20)
    assert ctx["cutoff_age_at_decision_s"] == 900
    assert ctx["model_consumed"] is False


@pytest.mark.parametrize("case,reason", [("altered", "SEAL_MISMATCH"), ("date", "WRONG_MARKET_DATE"),
    ("authority", "AUTHORITY_MISMATCH"), ("schema", "SCHEMA_UNSUPPORTED"), ("time", "INVALID_TIME_ORDER")])
def test_invalid_context_is_refused(morning, tmp_path, case, reason):
    p = json.loads((morning / (FX.TRADING_DATE + ".json")).read_text())
    if case == "altered": p["blind_spots"] = []
    if case == "date": p["market_date"] = "2026-08-25"
    if case == "authority": p["decision_power"] = "TRADE"
    if case == "schema": p["schema"] = "UNDECLARED"
    if case == "time": p["time"]["packet_known_from"] = FX.et_epoch(9, 0)
    rewrite(tmp_path, p, reseal=case != "altered")
    ctx = read(tmp_path)
    assert ctx["status"] == "REFUSED" and reason in ctx["reason"], ctx
    assert ctx["packet"] is None


def test_packet_unavailable_before_seal(morning):
    ctx = read(morning, FX.et_epoch(9, 24))
    assert ctx["status"] == "REFUSED" and "LATE_PACKET" in ctx["reason"]


def test_missing_and_not_wired_are_distinct(tmp_path):
    assert read(tmp_path)["status"] == "MISSING"
    assert read(None)["status"] == "NOT_WIRED"


def test_live_configuration_reaches_twin_without_provider_access(tmp_path):
    from apex.options_pilot.entrypoint import LiveWiring, ProductionSources
    p = ProductionSources(wiring=LiveWiring(premarket_root=tmp_path))
    assert p._twin.premarket_root == tmp_path
    assert p.describe()["wiring"]["premarket_root"] == str(tmp_path)
    assert not p.wiring.attach_market_data_http


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'[]', b'{', b'{"a":NaN}'])
def test_malformed_local_files_are_context_refusals(tmp_path, raw):
    (tmp_path / (FX.TRADING_DATE + ".json")).write_bytes(raw)
    assert read(tmp_path)["status"] == "REFUSED"


def test_local_file_limit_is_enforced(tmp_path):
    from apex.pulse_options.premarket_context import MAX_BYTES
    (tmp_path / (FX.TRADING_DATE + ".json")).write_bytes(b' ' * (MAX_BYTES + 1))
    assert "PACKET_TOO_LARGE" in read(tmp_path)["reason"]


def test_full_funnel_persists_the_same_packet_and_reconstructs(morning, tmp_path):
    from apex.court.court import FunnelCourt
    from apex.court import world as W
    from apex.court.verify import reconstruct
    from datetime import datetime, timezone
    midnight = datetime.fromisoformat(FX.TRADING_DATE).replace(tzinfo=timezone.utc).timestamp()
    # Separate training history and the 65-minute current tape. Extending the
    # same upward walk to 1400 bars changes spot to 725 while the fixed chain
    # remains near 645, which correctly fails option no-arbitrage checks.
    bars = W.bars(n=500, end_epoch=midnight, drift_bp_per_bar=0.8, vol_bp_per_bar=4.0)
    bars += W.bars(n=65, end_epoch=NOW, drift_bp_per_bar=0.8, vol_bp_per_bar=4.0)
    # Explicit two-sided October chain. The inherited harness also has a single
    # September call for DTE-refusal tests; on this earlier August date that
    # unrelated expiry becomes eligible and is not a complete ATM fixture.
    chain = [{"expiration": "2026-10-09", "strike": k, "right": right, "ask": 2.45}
             for k in (640.0, 645.0, 650.0, 655.0) for right in ("CALL", "PUT")]
    c = FunnelCourt(run_id="premarket-full", out_root=tmp_path, t0=NOW,
                    premarket_root=morning, synthetic_bars=bars, synthetic_chain=chain)
    out = c.run()
    rows = [json.loads(s) for s in (c.dir / "ledger.jsonl").read_text().splitlines()]
    fc = next(r for r in rows if r["kind"] == "pilot_forecast")
    decision = next(r for r in rows if r["kind"] == "pilot_decision")
    ctx = decision["premarket_context"]
    assert ctx == fc["inputs"]["premarket_context"]
    assert ctx["snapshot_id"] == fc["inputs"]["snapshot_id"]
    assert ctx["packet_sha256"] == read(morning)["packet_sha256"]
    assert ctx["status"] == "ATTACHED_CONTEXT" and not ctx["model_consumed"]
    assert out["decision"] == "TRADE", out
    proof = reconstruct(c.dir)
    assert proof["problems"] == [], proof
    assert proof["execution_verification"]["open_positions"] == 0
    control = FunnelCourt(run_id="no-premarket", out_root=tmp_path, t0=NOW, synthetic_bars=bars,
                          synthetic_chain=chain)
    control_out = control.run()
    assert control_out["decision"] == out["decision"]
    assert reconstruct(control.dir)["pnl_recomputed"] == proof["pnl_recomputed"]
    control_rows = [json.loads(s) for s in (control.dir / "ledger.jsonl").read_text().splitlines()]
    control_fc = next(r for r in control_rows if r["kind"] == "pilot_forecast")
    for key in ("location", "scale", "nu", "model_hash", "params_hash"):
        assert fc[key] == control_fc[key]
    for key in ("contract", "expression", "quantity", "reference_ask"):
        assert next(r for r in rows if r["kind"] == "pilot_intent")[key] == next(
            r for r in control_rows if r["kind"] == "pilot_intent")[key]
