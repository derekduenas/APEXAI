#!/usr/bin/env python3
"""Record what the ACTUAL host permits, component by component.

Leaf ownership of an admission directory establishes nothing if any ancestor
can be renamed by the research account. This audit walks every component,
records uid/gid/mode/sticky, tests real writability, resolves the signature
verifier, and reports whether the account running it could replace any part
of the trust chain. It changes nothing.

    PYTHONPATH=. python scripts/si002_trust_path_audit.py <out.json>
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from apex.world_model.real_data import boundary

TARGETS = {
    "admission_root": "/apex-data/governance/admissions",
    "allowed_signers": "/apex-data/governance/admissions/trust/allowed_signers",
    "manifest_dir": "/apex-data/governance/admissions/manifests",
    "output_root": "/apex-data/research",
    "proposed_alternative_trust_root": "/etc/apex/admissions",
}


def chain(p: str) -> list:
    out = []
    for c in boundary.ancestors(Path(p)):
        try:
            f = boundary.path_facts(c)
        except OSError as e:
            out.append({"path": str(c), "absent": True, "error": str(e)}); break
        # a component is REPLACEABLE by us if we can write its parent
        parent = c.parent
        try:
            f["parent_writable_by_euid"] = os.access(parent, os.W_OK) if parent != c else False
        except OSError:
            f["parent_writable_by_euid"] = None
        f["writable_by_euid"] = os.access(c, os.W_OK)
        out.append(f)
    return out


def main(out_path: str) -> int:
    euid = os.geteuid()
    rec = {"produced_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "host_user": {"euid": euid, "uid": os.getuid(), "groups": sorted(os.getgroups())},
           "targets": {}, "verdicts": {}}
    for name, p in TARGETS.items():
        c = chain(p)
        rec["targets"][name] = {"path": p, "exists": Path(p).exists(), "chain": c}
        replaceable = [f for f in c if not f.get("absent")
                       and (f.get("parent_writable_by_euid") or f.get("writable_by_euid"))]
        rec["verdicts"][name] = {
            "research_account_can_replace_some_component": bool(replaceable),
            "replaceable_components": [f["path"] for f in replaceable],
            "why": "a component whose PARENT is writable by this account can be renamed away and "
                   "replaced, whatever the component's own owner and mode say"}
    # signature verifier resolution
    which = shutil.which("ssh-keygen")
    ver = {"PATH": os.environ.get("PATH", ""), "which_ssh_keygen": which,
           "trusted_constant": boundary.TRUSTED_SSH_KEYGEN}
    try:
        ver["trusted_executable_resolved"] = boundary.trusted_executable(
            boundary.TrustConfig(admission_root=Path("/"), allowed_signers=Path("/"),
                                 checkout_root=Path("/")))
        ver["status"] = "TRUSTED"
    except boundary.RealDataRefused as e:
        ver["status"] = "REFUSED"; ver["refusal"] = str(e)
    ver["chain"] = chain(which or boundary.TRUSTED_SSH_KEYGEN)
    rec["verifier"] = ver
    # privilege of the research account: does it hold sudo?
    try:
        r = subprocess.run(["sudo", "-n", "-l"], capture_output=True, text=True, timeout=30)
        txt = (r.stdout or "") + (r.stderr or "")
        rec["research_account_privilege"] = {
            "sudo_l_returncode": r.returncode, "sudo_l_output": txt.strip()[:2000],
            "can_become_root": ("NOPASSWD: ALL" in txt) or ("(ALL : ALL) ALL" in txt),
            "note": "if this account can become root, NO filesystem ownership check is a boundary "
                    "against it; research must run as an account without sudo"}
    except (OSError, subprocess.SubprocessError) as e:
        rec["research_account_privilege"] = {"error": str(e)}
    # production verifier decision on the real paths, without any decision file
    try:
        boundary._check_ancestor_chain(Path(TARGETS["admission_root"]), boundary.production_trust(),
                                       "admission_root")
        rec["production_trust_check"] = {"status": "WOULD_PASS"}
    except boundary.RealDataRefused as e:
        rec["production_trust_check"] = {"status": "WOULD_REFUSE", "refusal": str(e)}
    Path(out_path).write_text(json.dumps(rec, indent=1, sort_keys=True, default=str))
    print(json.dumps({"verdicts": {k: v["research_account_can_replace_some_component"]
                                   for k, v in rec["verdicts"].items()},
                      "verifier": ver["status"],
                      "can_become_root": rec["research_account_privilege"].get("can_become_root"),
                      "production_trust_check": rec["production_trust_check"]["status"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
