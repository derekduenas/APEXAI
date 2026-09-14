"""Local sealed premarket packet -> prior context. No signal or model authority.

Checks content integrity, not publisher authenticity. Receipt is the local read;
the producer's seal time is a claimed availability bound, not source freshness.
"""
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from zoneinfo import ZoneInfo

MAX_BYTES = 2 * 1024 * 1024
SCHEMA = "PREMARKET_PRIOR_CONTEXT_V1"


def unavailable(status="NOT_WIRED"):
    return {"schema": SCHEMA, "status": status, "authority": "PRIOR_CONTEXT_ONLY",
            "model_consumed": False, "selection_effect": "NONE",
            "authenticity": "UNVERIFIED", "packet": None}


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("INVALID_TIME")
    return float(value)


def _instant(value):
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("NAIVE_TIME")
    return t.timestamp()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_KEY")
        result[key] = value
    return result


def read_context(*, root, symbol, as_of, snapshot_id, clock):
    """Read only the requested market date. No fallback to a previous day's file.

    The full parsed packet is retained so its seal can be independently checked
    from the decision ledger. A later change on disk cannot change this capture.
    """
    result = unavailable()
    result.update(symbol=symbol, snapshot_id=snapshot_id, as_of_epoch=as_of)
    if root is None:
        return result
    try:
        as_of = _number(as_of)
        day = datetime.fromtimestamp(as_of, ZoneInfo("America/New_York")).date().isoformat()
        path = Path(root) / (day + ".json")
        # Nonblocking open also prevents an accidental FIFO from hanging a scan.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise ValueError("NOT_REGULAR_FILE")
            raw = f.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("PACKET_TOO_LARGE")
        receipt = _number(clock.now())
        result.update(file_sha256=hashlib.sha256(raw).hexdigest(), read_receipt_epoch=receipt)
        packet = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(packet, dict):
            raise ValueError("PACKET_NOT_OBJECT")
        body = {k: v for k, v in packet.items() if k != "packet_sha256"}
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest()
        if packet.get("packet_sha256") != digest:
            raise ValueError("SEAL_MISMATCH")
        if packet.get("sealed") != "SEALED_BEFORE_OPEN":
            raise ValueError("NOT_SEALED")
        if packet.get("decision_power") != "NONE_FRONTIER_SHADOW":
            raise ValueError("AUTHORITY_MISMATCH")
        if packet.get("market_date") != day:
            raise ValueError("WRONG_MARKET_DATE")
        sealed = _instant(packet["as_of_time"])
        bell = datetime.fromisoformat(day + "T09:30:00").replace(tzinfo=ZoneInfo("America/New_York")).timestamp()
        if sealed >= bell:
            raise ValueError("SEALED_AFTER_OPEN")
        version = packet.get("schema", "PREMARKET_CONTEXT_PACKET_V1")
        if version == "PREMARKET_CONTEXT_PACKET_V2":
            times = packet["time"]
            if _number(times["packet_sealed_at"]) != sealed:
                raise ValueError("SEAL_TIME_MISMATCH")
            known = _number(times["packet_known_from"])
            cutoff = _number(times["packet_data_cutoff"])
            if cutoff > sealed or known < sealed:
                raise ValueError("INVALID_TIME_ORDER")
            result.update(source_freshness="PRODUCER_REPORTED",
                          data_cutoff_epoch=cutoff,
                          cutoff_age_at_decision_s=as_of - cutoff)
        elif version == "PREMARKET_CONTEXT_PACKET_V1":
            known = sealed
            result.update(source_freshness="UNRECONSTRUCTIBLE", data_cutoff_epoch=None)
        else:
            raise ValueError("SCHEMA_UNSUPPORTED")
        if known > as_of or known > receipt:
            raise ValueError("LATE_PACKET")
        result.update(status="ATTACHED_CONTEXT", packet_sha256=digest,
                      packet_known_from=known, packet=packet,
                      reader="TwinSources.snapshot -> forecast inputs -> pilot_decision",
                      limits="Seal validates content only; no source authenticity or model use established.")
        return result
    except FileNotFoundError:
        result["status"] = "MISSING"
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        result.update(status="REFUSED", reason=type(exc).__name__ + ":" + str(exc)[:160])
    return result
