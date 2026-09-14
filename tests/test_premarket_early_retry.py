"""Exercise repeated scheduled invocations through the production CLI, offline."""
import json
import os
from pathlib import Path
import subprocess
import sys

from apex.audit import premarket_fixture as FX
from apex.frontier import premarket_stages as PS

REPO = Path(__file__).resolve().parents[1]


def test_early_trigger_does_not_cancel_the_scheduled_morning(tmp_path):
    FX.install_world(repo_root=tmp_path)
    root = tmp_path / "morning"
    env = {k: v for k, v in os.environ.items() if not k.startswith("APEX_PREMARKET_")}
    env.update(APEX_PREMARKET_ROOT=str(root),
               APEX_PREMARKET_TRANSPORT="apex.audit.premarket_fixture:transport",
               APEX_PREMARKET_CAPTAIN="apex.audit.premarket_fixture:captain",
               PYTHONPATH=str(REPO))

    def invoke(stage, h, m):
        import pandas as pd
        env["APEX_PREMARKET_NOW"] = pd.Timestamp(
            FX.et_epoch(h, m), unit="s", tz="UTC").isoformat()
        r = subprocess.run([sys.executable, str(REPO / "scripts/premarket_stage.py"),
                            "--stage", stage], cwd=tmp_path, env=env,
                           capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout

    for stage, h, m in PS.STAGE_SCHEDULE:
        assert "TOO_EARLY" in invoke(stage, 3, 0)
        journal = root / "journal" / FX.TRADING_DATE / "events.jsonl"
        before = [json.loads(line) for line in journal.read_text().splitlines()]
        assert not any(e["stage"] == stage and e["state"] == "CAPTURED" for e in before)
    for stage, h, m in PS.STAGE_SCHEDULE:
        actual = invoke(stage, h, m)
        assert "RECONCILED_DUPLICATE" not in actual, actual
        events = [json.loads(line) for line in journal.read_text().splitlines()]
        assert sum(e["stage"] == stage and e["state"] == "COMPLETED" for e in events) == 1
        assert "RECONCILED_DUPLICATE" in invoke(stage, h, m)
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    assert sum(e["state"] == "ABSORBED" for e in events) == 4
    assert sum(e["stage"] == "seal" and e["state"] == "COMPLETED" for e in events) == 1


def test_early_receipt_is_retained_without_ending_stage(tmp_path):
    from apex.frontier import premarket_journal as PJ
    j = PJ.open_journal(FX.TRADING_DATE, root=tmp_path)
    j.append(stage="seal", state="TOO_EARLY")
    assert j.stage_state("seal") == "TOO_EARLY"
    assert j.stage_outcome("seal") == "PENDING"
    j.append(stage="seal", state="COMPLETED")
    assert j.stage_outcome("seal") == "COMPLETED"
