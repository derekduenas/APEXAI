"""Build a CONTENT-ADDRESSED release package from an exact commit, plus a rollback artifact and the process-start
identity check (Brick 3). Nothing here deploys: it writes files under an output directory for review.

    python scripts/build_release_package.py --commit <sha> --out out/release/ [--current-link /opt/apex/current]

Outputs (all under --out):
    apex-<sha>.tar.gz               `git archive` of the exact commit (content-addressed by the tarball's sha256)
    RELEASE_MANIFEST.json           commit, tarball sha256, decision-path module digests (the same set runtime_identity
                                    measures), python/dependency versions expected, service command pin, rollback target
    ROLLBACK.json                   the release the host currently points at (taken from --current-link if given, else
                                    recorded as UNKNOWN_NOT_MEASURED) and the exact command to point back to it
    startup_identity_check.py       run at process start on the host: compares runtime_identity() against the manifest and
                                    exits non-zero on any digest or commit mismatch"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from apex.options_pilot.runtime_identity import DECISION_PATH_MODULES, DEPENDENCIES  # noqa: E402

SERVICE_CMD = ("/opt/apex/shared/venv/bin/python -u /opt/apex/releases/{sha}/scripts/options_paper_session.py --pilot-boundary "
               "--pilot-selection-policy PILOT_RULE_V2 --ledger /apex-data/core/options_pilot_ledger.jsonl --out /apex-data/history-a/pilot_$(date +%F).json "
               "--symbols SPY --minutes 390 --interval-min 15")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--current-link", default=None, help="path of the host's current-release symlink, if reachable locally")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    sha = subprocess.run(["git", "rev-parse", a.commit], capture_output=True, text=True, check=True).stdout.strip()
    tar = out / ("apex-%s.tar.gz" % sha)
    with open(tar, "wb") as f:
        subprocess.run(["git", "archive", "--format=tar.gz", "--prefix=%s/" % sha, sha], stdout=f, check=True)
    tar_sha = sha256_file(tar)
    # digest the decision-path modules AS THEY ARE IN THE ARCHIVE (not the working tree)
    digests = {}
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(tar) as tf:
            tf.extractall(td, filter="data")
        root = Path(td) / sha
        for mod in DECISION_PATH_MODULES:
            p = root / (mod.replace(".", "/") + ".py")
            digests[mod] = sha256_file(p) if p.exists() else "MISSING_IN_ARCHIVE"
    tree_digest = hashlib.sha256("".join("%s=%s" % kv for kv in sorted(digests.items())).encode()).hexdigest()
    manifest = {"kind": "RELEASE_MANIFEST", "commit": sha, "tarball": tar.name, "tarball_sha256": tar_sha,
                "decision_path_module_digests": digests, "decision_path_tree_digest": tree_digest,
                "expected_dependencies": DEPENDENCIES, "python_expected": "3.12 on the host (/opt/apex/shared/venv); 3.11.9 on the build Mac",
                "install_path": "/opt/apex/releases/%s" % sha, "current_link": "/opt/apex/current",
                "service_command_pin": SERVICE_CMD.format(sha=sha),
                "activation_boundary": ("NOT ACTIVATED BY THIS PACKAGE: install, re-point /opt/apex/current, lift the maintenance block and enable "
                                        "APEX_PILOT_LIVE_DATA are separate operator actions against this exact package"),
                "scope": "content of the archive and its decision-path digests; host installation is verified by startup_identity_check.py at process start"}
    (out / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
    current = None
    if a.current_link and os.path.islink(a.current_link):
        current = os.path.realpath(a.current_link)
    rollback = {"kind": "ROLLBACK", "current_release_before_install": current or "UNKNOWN_NOT_MEASURED (record `readlink -f /opt/apex/current` on the host before installing)",
                "rollback_command": "ln -sfn %s /opt/apex/current && systemctl restart apex-options-paper.service" % (current or "<previous release path>"),
                "note": "rollback re-points the link; it never deletes a release directory"}
    (out / "ROLLBACK.json").write_text(json.dumps(rollback, indent=1) + "\n")
    (out / "startup_identity_check.py").write_text('''"""Process-start identity check: refuse to start unless the loaded code IS the manifest's release."""
import json, sys
sys.path.insert(0, ".")
from apex.options_pilot.runtime_identity import runtime_identity
m = json.load(open(sys.argv[1]))
ri = runtime_identity()
problems = []
if ri["git_commit"] not in (m["commit"], "NOT_A_GIT_CHECKOUT"):
    problems.append("commit %s != manifest %s" % (ri["git_commit"], m["commit"]))
for k, v in m["decision_path_module_digests"].items():
    if ri["decision_path_module_digests"].get(k) != v:
        problems.append("digest mismatch: %s" % k)
if ri["decision_path_tree_digest"] != m["decision_path_tree_digest"]:
    problems.append("tree digest mismatch")
print(json.dumps({"release": m["commit"], "loaded_tree_digest": ri["decision_path_tree_digest"], "problems": problems}, indent=1))
sys.exit(1 if problems else 0)
''')
    print(json.dumps({"commit": sha, "tarball": str(tar), "tarball_sha256": tar_sha, "tree_digest": tree_digest}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
