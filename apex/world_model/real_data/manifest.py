"""Dataset manifest: the CONTENT COMMITMENT an admission decision points at.

A manifest lists every file the decision may open, by relative name, with
its sha256 and size, plus the declared availability semantics. The decision
commits to the manifest's own sha256, so changing the manifest -- or any
file it lists -- is refused at read time. Building a manifest reads bytes
for hashing only; it parses nothing and returns no rows.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_VERSION = "REAL_DATA_MANIFEST_V0"
_SESSION_FILE = re.compile(r"^(?P<symbol>[A-Z0-9.\-]+)_(?P<date>\d{4}-\d{2}-\d{2})\.json$")


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(root, *, dataset_id: str, source_families: list, availability: dict,
          symbols: list | None = None, corpus_version: str | None = None,
          extra: dict | None = None) -> dict:
    """Walk `root` for <SYMBOL>_<YYYY-MM-DD>.json session files (optionally
    restricted to `symbols`) and commit each by sha256."""
    r = Path(root).resolve()
    files = {}
    for p in sorted(r.rglob("*.json")):
        m = _SESSION_FILE.match(p.name)
        if not m:
            continue
        if symbols and m["symbol"] not in symbols:
            continue
        files[str(p.relative_to(r))] = {"sha256": sha256_of(p), "size": p.stat().st_size,
                                        "symbol": m["symbol"], "session_date": m["date"]}
    dates = sorted(v["session_date"] for v in files.values())
    return {"manifest_version": MANIFEST_VERSION, "dataset_id": dataset_id, "root": str(r),
            "source_families": list(source_families), "availability": dict(availability),
            "corpus_version": corpus_version, "symbols": sorted({v["symbol"] for v in files.values()}),
            "n_files": len(files), "first_session": dates[0] if dates else None,
            "last_session": dates[-1] if dates else None,
            "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "law": "bytes hashed, nothing parsed; a manifest commits content, it admits nothing",
            **(extra or {}), "files": files}


def write(manifest: dict, path) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return sha256_of(p)
