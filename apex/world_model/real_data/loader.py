"""Admitted session loader for the EXP-001B row shape on the REAL-DATA route.

Field restriction is enforced HERE: a bar is rebuilt from the permitted
fields only. The six clocks are set by exp001b.bars from the exchange
calendar; this module adds nothing to them and substitutes nothing for the
publication time this corpus lacks.
"""
from __future__ import annotations

import json
from pathlib import Path

from apex.world_model.exp001b import bars as B
from . import boundary
from .boundary import Grant, RealDataRefused

REQUIRED_FIELDS = ("event_time_utc", "open", "high", "low", "close", "volume")


def load_session(path, *, grant: Grant, symbol: str, session_date: str) -> dict:
    missing = [f for f in REQUIRED_FIELDS if f not in grant.fields]
    if missing:
        raise RealDataRefused("FIELD_NOT_PERMITTED: EXP-001B rows need %s; the decision did not admit %s"
                              % (list(REQUIRED_FIELDS), missing))
    adm = boundary.open_file(grant, path, symbol=symbol, session_date=session_date, fields=REQUIRED_FIELDS)
    raw = adm.pop("raw")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise B.BarsRefused("MALFORMED_JSON: %s: %s" % (Path(path).name, e))
    fam = doc.get("source", "UNDECLARED")
    if fam not in grant.source_families:
        raise RealDataRefused("SOURCE_FAMILY_NOT_PERMITTED: file declares %r, decision admits %s"
                              % (fam, list(grant.source_families)))
    bars = doc.get("bars")
    if not isinstance(bars, list):
        raise B.BarsRefused("MISSING_BARS: %s" % Path(path).name)
    slim = []
    for b in bars:
        if not isinstance(b, dict):
            raise B.BarsRefused("MALFORMED_BAR: %s" % Path(path).name)
        slim.append({k: b.get(k) for k in REQUIRED_FIELDS})
    session = B.session_from_doc({"source": fam, "bars": slim}, Path(path), raw, adm,
                                 symbol=symbol, session_date=session_date)
    session["route"] = boundary.REAL_DATA_CONTRACT
    session["restricted_use"] = adm.get("restricted_use")
    return session


def loader_for(grant: Grant):
    """callable(path) -> session; symbol and date come from the committed
    manifest entry, never from the caller."""
    droot = Path(grant.dataset_root).resolve()

    def _load(path):
        rp = Path(path).resolve()
        key = str(rp.relative_to(droot)) if droot in rp.parents else str(path)
        rec = grant.manifest["files"].get(key)
        if rec is None:
            raise RealDataRefused("UNCOMMITTED_FILE: %s" % key)
        return load_session(path, grant=grant, symbol=rec["symbol"], session_date=rec["session_date"])
    return _load


def sessions_by_period(grant: Grant, periods: dict, *, symbol: str) -> dict:
    """Paths per registered period, intersected with the grant's temporal
    range. Lists only; opens nothing."""
    lo, hi = grant.temporal_range
    droot = Path(grant.dataset_root)
    out = {}
    for period, (p0, p1) in periods.items():
        a, b = max(p0, lo), min(p1, hi)
        out[period] = sorted(str(droot / k) for k, v in grant.manifest["files"].items()
                             if v["symbol"] == symbol and a <= v["session_date"] <= b)
    return out
