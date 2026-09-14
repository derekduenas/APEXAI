import hashlib
import json

import pytest

from scripts.flow_data_preflight import FAMILIES, inspect_manifest, main


def manifest(tmp_path):
    data = tmp_path / 'data.json'
    data.write_bytes(b'[]')
    path = tmp_path / 'manifest.json'
    body = {'sessions': [{'market_date': '2026-09-11', 'exposure_status': 'BURNED',
                         'inputs': {f: {'path': 'data.json', 'sha256': hashlib.sha256(b'[]').hexdigest()}
                                    for f in FAMILIES}}]}
    path.write_text(json.dumps(body))
    return path, body


def test_matching_bytes_do_not_establish_readiness_or_clean_data(tmp_path):
    path, _ = manifest(tmp_path)
    result = inspect_manifest(path)
    assert result['all_input_bytes_match']
    assert not result['evaluation_ready']
    assert result['sessions'][0]['coverage_status'] == 'NOT_INSPECTED'
    assert result['sessions'][0]['exposure_status_claim'] == 'BURNED'


@pytest.mark.parametrize('fault,status', [('missing', 'MISSING'), ('edited', 'MISMATCH'),
                                         ('empty', 'EMPTY'), ('unpin', 'PIN_REQUIRED'),
                                         ('undeclared', 'NOT_DECLARED')])
def test_input_failures_are_named(tmp_path, fault, status):
    path, body = manifest(tmp_path)
    if fault == 'missing':
        (tmp_path / 'data.json').unlink()
    elif fault == 'edited':
        (tmp_path / 'data.json').write_text('[1]')
    elif fault == 'empty':
        (tmp_path / 'data.json').write_bytes(b'')
    elif fault == 'unpin':
        body['sessions'][0]['inputs']['bars'].pop('sha256')
    else:
        body['sessions'][0]['inputs'].pop('bars')
    path.write_text(json.dumps(body))
    result = inspect_manifest(path)
    assert not result['all_input_bytes_match']
    assert result['sessions'][0]['inputs'][0]['status'] == status


def test_cli_never_overwrites_and_keeps_failure(tmp_path):
    output = tmp_path / 'out.json'
    with pytest.raises(FileNotFoundError):
        main([str(tmp_path / 'missing'), str(output)])
    before = output.read_bytes()
    assert json.loads(before)['status'] == 'FAILED'
    with pytest.raises(FileExistsError):
        main(['ignored', str(output)])
    assert output.read_bytes() == before


def test_duplicate_dates_refuse(tmp_path):
    path, body = manifest(tmp_path)
    body['sessions'] *= 2
    path.write_text(json.dumps(body))
    with pytest.raises(ValueError, match='DUPLICATE'):
        inspect_manifest(path)
