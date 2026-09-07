"""Admitted session loader for the EXP-001 row shape, on the REAL-DATA route.

Produces exactly what apex.world_model.exp001.bars.load_session produces,
so run() cannot tell the routes apart downstream -- only the admission
record differs, and it says which contract admitted the file. Field
restriction is enforced HERE: a bar is rebuilt from the permitted fields
only, so a field the decision did not admit never reaches a feature.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apex.world_model.exp001 import bars as B
from . import boundary
from .boundary import Grant, RealDataRefused

BAR_SECONDS = 60          # alpaca 1m bars: the bar is KNOWN at its close
REQUIRED_FIELDS = ("event_time_utc", "open", "high", "low", "close", "volume")


def load_session(path, *, grant: Grant, symbol: str, session_date: str) -> dict:
    missing = [f for f in REQUIRED_FIELDS if f not in grant.fields]
    if missing:
        raise RealDataRefused("FIELD_NOT_PERMITTED: EXP-001 rows need %s; the decision did not "
                              "admit %s" % (list(REQUIRED_FIELDS), missing))
    adm = boundary.open_file(grant, path, symbol=symbol, session_date=session_date,
                             fields=REQUIRED_FIELDS)
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
    # rebuild each bar from PERMITTED fields only; known_from = bar close
    slim = []
    for b in bars:
        if not isinstance(b, dict):
            raise B.BarsRefused("MALFORMED_BAR: %s" % Path(path).name)
        slim.append({k: b.get(k) for k in REQUIRED_FIELDS})
    session = B.session_from_doc({"source": fam, "bars": slim}, Path(path), raw, adm)
    for r in session["rows"]:
        r["known_from"] = r["t"] + BAR_SECONDS
    session["route"] = boundary.REAL_DATA_CONTRACT
    session["restricted_use"] = adm.get("restricted_use")
    session["doc_sha256"] = hashlib.sha256(raw).hexdigest()
    return session


def loader_for(grant: Grant):
    """A callable(path) -> session for run(session_loader=...). Symbol and
    date are read from the committed manifest entry, never from the caller."""
    droot = Path(grant.dataset_root).resolve()

    def _load(path):
        key = str(Path(path).resolve().relative_to(droot)) if droot in Path(path).resolve().parents \
            else str(path)
        rec = grant.manifest["files"].get(key)
        if rec is None:
            raise RealDataRefused("UNCOMMITTED_FILE: %s" % key)
        return load_session(path, grant=grant, symbol=rec["symbol"], session_date=rec["session_date"])
    return _load


def sessions_by_period(grant: Grant, periods: dict, *, symbol: str) -> dict:
    """Session paths per registered period, intersected with the grant's
    temporal range. Lists paths only; opens nothing."""
    lo, hi = grant.temporal_range
    droot = Path(grant.dataset_root)
    out = {}
    for period, (p0, p1) in periods.items():
        a, b = max(p0, lo), min(p1, hi)
        out[period] = sorted(str(droot / k) for k, v in grant.manifest["files"].items()
                             if v["symbol"] == symbol and a <= v["session_date"] <= b)
    return out
