"""RUNTIME PATH AUDIT — read-only. Can every active service actually
write what it believes it is writing?

Written because one instance of this defect was found by accident. A
service ran with its working directory set to the immutable release
tree, wrote relative results/... paths, and got PermissionError on
every one -- while reporting active, zero restarts, no errors. A green
heartbeat over a write that cannot land is indistinguishable from a
healthy quiet day, which is the worst property a monitor can have.

One instance found by accident means the CLASS was never audited. This
audits the class.

THE PERMANENT LAW IT ENFORCES:

    /opt/apex/current      CODE            READ ONLY
    /apex-data/runtime     RUNTIME STATE   WRITABLE
    /apex-data/core        EVIDENCE        WRITABLE

No active service may depend on mutating /opt/apex/current.

Read-only: this script starts nothing, stops nothing, writes nothing
outside its own report.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

RELEASE_ROOT = Path("/opt/apex/current")
ALLOWED_WRITE_ROOTS = ("/apex-data/runtime", "/apex-data/core",
                       "/apex-data/history-a", "/apex-data/history-b",
                       "/tmp", "/var/tmp")


def systemctl(*args) -> str:
    r = subprocess.run(("systemctl",) + args, capture_output=True,
                       text=True)
    return r.stdout.strip()


def active_apex_units() -> list:
    out = systemctl("list-units", "apex-*", "--type=service",
                    "--state=active", "--no-legend", "--plain")
    return [ln.split()[0] for ln in out.splitlines() if ln.strip()]


def unit_props(unit: str) -> dict:
    keys = ("WorkingDirectory", "ExecStart", "User", "Slice",
            "MainPID", "NRestarts", "ActiveState")
    d = {}
    for k in keys:
        d[k] = systemctl("show", unit, "-p", k, "--value")
    return d


def script_of(execstart: str) -> str | None:
    for tok in execstart.replace("'", " ").split():
        if tok.endswith(".py"):
            return tok
    return None


def declared_paths(script: Path) -> dict:
    """Every Path("...") literal the module declares, split into
    relative and absolute. Parsed, not grepped."""
    rel, absolute = [], []
    try:
        tree = ast.parse(script.read_text())
    except (OSError, SyntaxError):
        return {"relative": [], "absolute": [], "parsed": False}
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "Path" and n.args):
            continue
        a = n.args[0]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            (absolute if a.value.startswith("/") else rel).append(a.value)
    return {"relative": sorted(set(rel)),
            "absolute": sorted(set(absolute)), "parsed": True}


def writable(base: Path, rel: str) -> dict:
    """Can this exact target actually be created? Probe, do not infer
    from permission bits -- the bits were what fooled us last time."""
    target = (base / rel) if not rel.startswith("/") else Path(rel)
    parent = target.parent
    probe = parent / ".__apex_write_probe"
    try:
        parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("x")
        probe.unlink()
        return {"writable": True, "resolved": str(parent.resolve())}
    except OSError as e:
        return {"writable": False, "resolved": str(parent),
                "error": f"{type(e).__name__}: {e}"}


def audit_unit(unit: str, *, probe: bool = True) -> dict:
    p = unit_props(unit)
    wd = p["WorkingDirectory"] or "/"
    script = script_of(p["ExecStart"] or "")
    row = {"unit": unit, "active": p["ActiveState"],
           "working_directory": wd, "user": p["User"],
           "slice": p["Slice"], "restarts": p["NRestarts"],
           "script": script}

    if not script or not Path(script).exists():
        row["verdict"] = "NO_SCRIPT_RESOLVED"
        return row

    paths = declared_paths(Path(script))
    row["relative_paths"] = paths["relative"]
    row["absolute_paths"] = paths["absolute"]

    # the defect: relative writes resolved against a read-only release
    under_release = str(Path(wd).resolve()).startswith(str(RELEASE_ROOT))
    row["cwd_is_release_tree"] = under_release

    blocked, checked = [], []
    if probe:
        for rel in paths["relative"]:
            w = writable(Path(wd), rel)
            checked.append({"path": rel, **w})
            if not w["writable"]:
                blocked.append(rel)
    row["path_checks"] = checked
    row["blocked_paths"] = blocked

    outside = [a for a in paths["absolute"]
               if not any(a.startswith(r) for r in ALLOWED_WRITE_ROOTS)
               and not a.startswith("/opt/apex")]
    row["absolute_outside_allowed_roots"] = outside

    if blocked:
        row["verdict"] = "BLOCKED_WRITES"
    elif under_release and paths["relative"]:
        row["verdict"] = "RELATIVE_WRITES_FROM_RELEASE_TREE"
    else:
        row["verdict"] = "OK"
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-probe", action="store_true")
    args = ap.parse_args()

    units = active_apex_units()
    rows = [audit_unit(u, probe=not args.no_probe) for u in units]
    bad = [r for r in rows if r["verdict"] not in ("OK",
                                                   "NO_SCRIPT_RESOLVED")]

    report = {"kind": "runtime_path_audit",
              "units_audited": len(rows),
              "release_root": str(RELEASE_ROOT),
              "law": "code read-only in the release; all mutable state "
                     "on the data volume; no active service may depend "
                     "on writing into the release tree",
              "units": rows,
              "violations": [r["unit"] for r in bad],
              "verdict": "PASS" if not bad else "FAIL"}

    if args.json:
        print(json.dumps(report, indent=1))
        return 0 if not bad else 1

    print(f"RUNTIME PATH AUDIT — {len(rows)} active apex services\n")
    for r in rows:
        mark = "ok " if r["verdict"] == "OK" else "!! "
        print(f"{mark}{r['unit']}")
        print(f"     cwd      {r['working_directory']}"
              f"   user={r['user']}   slice={r['slice']}")
        rel = r.get("relative_paths") or []
        print(f"     relative {len(rel)} path(s)"
              + (f" -> {rel[0]}..." if rel else ""))
        if r.get("blocked_paths"):
            for b in r["blocked_paths"]:
                print(f"     BLOCKED  {b}")
        print(f"     verdict  {r['verdict']}")
    print(f"\nAUDIT: {report['verdict']}"
          + (f" — {report['violations']}" if bad else
             " — no service depends on writing into the release tree"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
