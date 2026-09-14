"""Audit one persisted APEX run layer by layer.

Usage: python scripts/audit_flow_run.py RUN_DIR OUTPUT [--require-trade]
The output is exclusive-create: a failed or repeated audit never overwrites evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from apex.court.flow_audit import audit_run


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    require_trade = False
    if '--require-trade' in args:
        require_trade = True
        args.remove('--require-trade')
    if len(args) != 2:
        raise SystemExit('usage: audit_flow_run.py RUN_DIR OUTPUT [--require-trade]')
    run_dir, output = Path(args[0]), Path(args[1])
    # Claim the report path before opening the run, so invalid runs still leave
    # a named audit attempt and reruns cannot overwrite prior evidence.
    with output.open('x') as fh:
        try:
            report = audit_run(run_dir, require_trade=require_trade)
        except Exception as error:  # an audit refusal is itself persisted
            json.dump({'schema': 'FLOW_AUDIT_V1', 'status': 'FAILED',
                       'error_type': type(error).__name__, 'error': str(error)}, fh, indent=2)
            fh.write('\n')
            raise
        json.dump(report, fh, indent=2, allow_nan=False)
        fh.write('\n')
    return 0 if report['complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
