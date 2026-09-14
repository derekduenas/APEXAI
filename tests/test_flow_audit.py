import json
from pathlib import Path

import pytest

from apex.court.court import FunnelCourt
from tests.test_premarket_twin_handoff import morning, NOW
from apex.court.flow_audit import audit_run, PASS, WAIT, OPTIONAL_UNWIRED, BLOCKED


def test_full_funnel_is_a_sequentially_green_trade(tmp_path):
    c = FunnelCourt(run_id='full', out_root=tmp_path)
    out = c.run()
    audited = audit_run(c.dir, require_trade=True)
    assert out['decision'] == 'TRADE'
    assert audited['complete'] is True, audited
    assert audited['first_failure'] is None
    assert [s['status'] for s in audited['layers'] if s['required']].count(PASS) >= 12
    assert audited['layers'][0]['status'] == OPTIONAL_UNWIRED
    assert audited['independent_reconstruction']['problems'] == []


def test_insufficient_history_stops_before_model_layers(tmp_path):
    c = FunnelCourt(run_id='short', out_root=tmp_path, n_bars=40)
    out = c.run()
    audited = audit_run(c.dir)
    assert out['decision'] == 'WAIT'
    assert audited['complete'] is False
    assert audited['stop_layer'] == 'VARIANCE'
    layers = {s['layer']: s for s in audited['layers']}
    assert layers['MULTIVERSE']['status'] in (BLOCKED, WAIT)
    assert layers['EXPRESSION_WAR']['status'] in (BLOCKED, WAIT)


def test_missing_ledger_is_refused(tmp_path):
    with pytest.raises(ValueError, match='LEDGER_MISSING'):
        audit_run(tmp_path / 'missing')


def test_audit_does_not_trust_court_summary(tmp_path):
    c = FunnelCourt(run_id='summary', out_root=tmp_path)
    c.run()
    summary_path = c.dir / 'court_run.json'
    summary = json.loads(summary_path.read_text())
    summary['decision'] = 'WAIT'
    summary['complete'] = False
    summary_path.write_text(json.dumps(summary))
    audited = audit_run(c.dir, require_trade=True)
    assert audited['decision'] == 'TRADE'
    assert audited['complete'] is True


def test_attached_premarket_is_reported_as_context_only(morning, tmp_path):
    c = FunnelCourt(run_id='premarket', out_root=tmp_path, t0=NOW, premarket_root=morning,
                    synthetic_bars=training_bars_for_audit(), synthetic_chain=chain_for_audit())
    c.run()
    audited = audit_run(c.dir, require_trade=True)
    premarket = audited['layers'][0]
    assert premarket['status'] == PASS
    assert premarket['evidence']['model_consumed'] is False


def training_bars_for_audit():
    from apex.court import world as W
    return W.bars(n=500, end_epoch=NOW, drift_bp_per_bar=0.8, vol_bp_per_bar=4.0)


def chain_for_audit():
    return [{'expiration': '2026-10-09', 'strike': k, 'right': right, 'ask': 2.45}
            for k in (640.0, 645.0, 650.0, 655.0) for right in ('CALL', 'PUT')]


def test_cli_claims_output_and_refuses_overwrite(tmp_path):
    from scripts.audit_flow_run import main
    out = tmp_path / 'audit.json'
    with pytest.raises(ValueError, match='LEDGER_MISSING'):
        main([str(tmp_path / 'missing'), str(out)])
    first = out.read_bytes()
    assert json.loads(first)['status'] == 'FAILED'
    with pytest.raises(FileExistsError):
        main([str(tmp_path / 'missing'), str(out)])
    assert out.read_bytes() == first
