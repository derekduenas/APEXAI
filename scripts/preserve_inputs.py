"""FLOW-VALIDATION-001 — copy the recorded inputs to a durable location and manifest them.

    python scripts/preserve_inputs.py <source_collection_dir> <source_prior_bars.json> <destination_dir>

WHY. The four recorded inputs currently live only in a session scratchpad, which is session-scoped and may be
cleaned at any moment. An evaluation whose inputs can evaporate is not reproducible, and a digest declared by the
same process that reads the file proves almost nothing. This script makes the copy, writes an INDEPENDENT manifest
beside it, and then re-reads the copies to prove they match.

WHAT IT WRITES

    <destination>/collection/{chain,nbbo,bars}_SPY.jsonl
    <destination>/prior_bars.json
    <destination>/INPUTS_MANIFEST.json     digests, sizes, source paths, and the acquisition history

The manifest is the file `scripts/loop_demonstration.py` takes as its fifth argument, which turns its digest check
from "the bytes did not change between two reads" into "the bytes are the ones this manifest names".

IT NEVER OVERWRITES. A destination that already exists is refused, so a second preservation cannot quietly replace
the inputs an earlier evaluation was bound to.

THE ACQUISITION HISTORY IS CARRIED, NOT LAUNDERED. Copying a file does not change how it was obtained. The prior-bar
file was retrieved outside authorization (`SCOPE_DEVIATION_001.md`) and the manifest says so on the record, in the
same place a reader will look for its digest."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SYMBOL = "SPY"
COLLECTION_FILES = ("chain_%s.jsonl" % SYMBOL, "nbbo_%s.jsonl" % SYMBOL, "bars_%s.jsonl" % SYMBOL)

ACQUISITION_HISTORY = {
    "collection": {
        "dataset_id": "PILOT-COLLECTION/2026-09-11",
        "role": "PROSPECTIVE_OBSERVATION",
        "status": "BURNED",
        "burned_on": "2026-09-12",
        "acquired": "collected by scripts/options_pilot_collector.py under operator authorization",
        "prior_uses": ["STAGE0_CENSUS", "STAGE0_CENSUS_FEES_AUTHORIZED", "TRACE_REPLAY_PART1",
                       "FUNNEL_FIRST_RUN", "LOOP_DEMONSTRATION_2026-09-12"],
        "may_support": "mechanism validation only",
        "may_never_support": "any claim about edge, expectancy or calibration"},
    "prior_bars": {
        "dataset_id": "ALPACA-SPY-1MIN-2026-09-02..09-11",
        "acquired": "2026-09-12, host, from the deployed release",
        "authorization": "NONE AT ACQUISITION TIME",
        "recorded_in": "SCOPE_DEVIATION_001.md and docs/evidence/EVIDENCE_REGISTER.json",
        "note": ("preserving a file does not authorize how it was obtained. Any new use needs its own ruling; this "
                 "manifest carries the history so a later reader cannot mistake a tidy copy for a clean provenance.")},
}


class PreservationRefused(RuntimeError):
    """The copy cannot be made honestly. Named, never silent."""


def digest(path: Path) -> dict:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return {"sha256": h.hexdigest(), "bytes": path.stat().st_size}


def preserve(src_dir, src_prior, dest_dir) -> dict:
    src_dir, src_prior, dest = Path(src_dir), Path(src_prior), Path(dest_dir)
    if dest.exists():
        raise PreservationRefused("DESTINATION_EXISTS: %s. Preserved inputs are never replaced; choose a new "
                                  "destination so an earlier evaluation's inputs stay bound." % dest)
    missing = [f for f in COLLECTION_FILES if not (src_dir / f).is_file()]
    if missing:
        raise PreservationRefused("SOURCE_INCOMPLETE: %s missing from %s" % (missing, src_dir))
    if not src_prior.is_file():
        raise PreservationRefused("SOURCE_PRIOR_BARS_MISSING: %s" % src_prior)

    before = {"prior_bars": {**digest(src_prior), "source": str(src_prior)}}
    for f in COLLECTION_FILES:
        label = f.split("_")[0]
        before[label] = {**digest(src_dir / f), "source": str(src_dir / f)}

    (dest / "collection").mkdir(parents=True)
    for f in COLLECTION_FILES:
        shutil.copy2(src_dir / f, dest / "collection" / f)
    shutil.copy2(src_prior, dest / "prior_bars.json")

    # RE-READ THE COPIES. A copy that was not verified after writing is a hope, not a preservation.
    after, problems = {}, []
    for label, f in (("chain", "collection/" + COLLECTION_FILES[0]), ("nbbo", "collection/" + COLLECTION_FILES[1]),
                     ("bars", "collection/" + COLLECTION_FILES[2]), ("prior_bars", "prior_bars.json")):
        p = dest / f
        d = digest(p)
        after[label] = {**d, "path": str(p)}
        if d["sha256"] != before[label]["sha256"]:
            problems.append("%s: source %s, copy %s" % (label, before[label]["sha256"][:16], d["sha256"][:16]))
        if d["bytes"] != before[label]["bytes"]:
            problems.append("%s: size %d vs %d" % (label, before[label]["bytes"], d["bytes"]))
    if problems:
        raise PreservationRefused("COPY_VERIFICATION_FAILED: %s" % "; ".join(problems))

    manifest = {
        "kind": "INPUTS_MANIFEST",
        "created_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "destination": str(dest),
        "inputs": {k: {"sha256": v["sha256"], "bytes": v["bytes"], "path": v["path"]} for k, v in after.items()},
        "sources": {k: v["source"] for k, v in before.items()},
        "verified": "every copy was re-read after writing and matches its source by digest and size",
        "acquisition_history": ACQUISITION_HISTORY,
        "use": ("pass this file as the fifth argument of scripts/loop_demonstration.py so the replay authorization "
                "verifies the inputs against an INDEPENDENT declaration rather than against itself"),
    }
    (dest / "INPUTS_MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    m = preserve(sys.argv[1], sys.argv[2], sys.argv[3])
    print(json.dumps({"destination": m["destination"], "manifest": m["destination"] + "/INPUTS_MANIFEST.json",
                      "inputs": {k: v["sha256"][:16] for k, v in m["inputs"].items()}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
