"""Inventory declared replay inputs without fitting, scoring, or contacting providers.

A matching digest establishes bytes only, not coverage, authenticity or permission.
Usage: python scripts/flow_data_preflight.py manifest.json output.json
The output is exclusively created: reruns cannot overwrite evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

FAMILIES = ('bars', 'chain', 'nbbo', 'prior_bars')


def inspect_manifest(manifest_path):
    manifest_path = Path(manifest_path)
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    sessions = manifest.get('sessions')
    if not isinstance(sessions, list) or not sessions:
        raise ValueError('SESSIONS_REQUIRED')
    seen = set()
    results = []
    for session in sessions:
        date = session['market_date']
        from datetime import date as Date
        if Date.fromisoformat(date).isoformat() != date or date in seen:
            raise ValueError('INVALID_OR_DUPLICATE_SESSION')
        seen.add(date)
        inputs = session.get('inputs', {})
        rows = []
        for family in FAMILIES:
            item = inputs.get(family)
            row = {'family': family}
            if not isinstance(item, dict) or not item.get('path'):
                rows.append({**row, 'status': 'NOT_DECLARED'})
                continue
            path = Path(item['path']).expanduser()
            if not path.is_absolute():
                path = manifest_path.parent / path
            row['path'] = str(path)
            expected = item.get('sha256')
            row['declared_sha256'] = expected
            if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
                rows.append({**row, 'status': 'PIN_REQUIRED'})
                continue
            if not path.is_file():
                rows.append({**row, 'status': 'MISSING'})
                continue
            digest = hashlib.sha256()
            size = 0
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    size += len(chunk)
                    digest.update(chunk)
            actual = digest.hexdigest()
            rows.append({**row, 'actual_sha256': actual, 'bytes': size,
                         'status': 'EMPTY' if not size else ('MATCH' if actual == expected else 'MISMATCH')})
        results.append({'market_date': date,
                        'exposure_status_claim': session.get('exposure_status', 'UNKNOWN'),
                        'coverage_status': 'NOT_INSPECTED', 'inputs': rows,
                        'input_bytes_match': all(r['status'] == 'MATCH' for r in rows)})
    results.sort(key=lambda r: r['market_date'])
    return {'schema': 'FLOW_DATA_PREFLIGHT_V1', 'manifest_sha256': hashlib.sha256(raw).hexdigest(),
            'sessions': results, 'all_input_bytes_match': all(r['input_bytes_match'] for r in results),
            'evaluation_ready': False,
            'remaining_checks': ['record-level causal availability and coverage',
                                 'dataset-use scope and prior exposure',
                                 'chronological train/test split with overlapping labels purged',
                                 'matched candidate universe and execution assumptions',
                                 'recorded V2 arrival wiring and fee configuration'],
            'limitations': 'Byte inventory only. No authenticity, authority, clean-holdout or profitability claim.'}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        raise SystemExit('usage: flow_data_preflight.py MANIFEST OUTPUT')
    # Claim before reading any input, preserving a failed invocation as well.
    with Path(args[1]).open('x') as output:
        try:
            report = inspect_manifest(args[0])
        except Exception as error:
            json.dump({'status': 'FAILED', 'error_type': type(error).__name__, 'error': str(error)}, output)
            output.write('\n')
            raise
        json.dump(report, output, indent=2, allow_nan=False)
        output.write('\n')
    return 0 if report['all_input_bytes_match'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
