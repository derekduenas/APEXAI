"""Independent reconciliation of the EXP-004 prepared environment.

Recomputes every admitted file's sha256 against the committed manifest, and
records checkout identity, ownership, account restrictions, the probe's actual
configuration, the output directory's state and preservation of the existing
environments. Read-only.

Run (as root, for the ownership and sudo checks):
    python3 scripts/exp004_setup_reconcile.py <out.json>
"""
from __future__ import annotations

import grp
import hashlib
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

MANIFEST = Path("/apex-data/governance/admissions/manifests/etf_continuous_SPY_manifest_v0.json")
ROOT = Path("/apex-data/research-exp004")
VIEW = ROOT / "dataset_view" / "etf_continuous" / "bars"
CHECKOUT = ROOT / "checkout"
RUNNER = Path("/opt/apex-runner-exp004")
USER = "apexresearch4"
PIN = "ea87faa42537a14678bb6fc5cb1e9aacc83cf40f"
TREE = "8fbe6ed6155df0e4b8fb09f6dd8ce54c7e1cf064cea29592e08fa44a41996991"
PRIVILEGED = {"root", "sudo", "admin", "wheel", "adm", "shadow", "disk", "docker", "lxd", "kvm",
              "systemd-journal", "staff"}


def sha(p) -> str:
    p = Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "ABSENT"


def dataset_reconciliation() -> dict:
    man = json.loads(MANIFEST.read_text())
    files = man["files"]
    inrange = {k: v for k, v in files.items()
               if v["symbol"] == "SPY" and "2016-01-04" <= v["session_date"] <= "2021-12-31"}
    present = sorted(os.listdir(VIEW))
    mismatch, checked = [], 0
    for name in present:
        rec = inrange.get(name)
        if rec is None:
            mismatch.append({"file": name, "why": "NOT_IN_ADMITTED_RANGE"})
            continue
        checked += 1
        if sha(VIEW / name) != rec["sha256"]:
            mismatch.append({"file": name, "computed": sha(VIEW / name)[:16], "manifest": rec["sha256"][:16]})
    missing = sorted(set(inrange) - set(present))
    st = os.lstat(VIEW / present[0])
    return {"manifest_total_entries": len(files), "admitted_in_range": len(inrange), "view_files": len(present),
            "hashes_recomputed": checked, "hash_mismatches": mismatch, "missing_from_view": missing,
            "all_admitted_files_match": (checked == len(inrange) == len(present) == 1511
                                         and not mismatch and not missing),
            "out_of_range_present": [m for m in mismatch if m.get("why") == "NOT_IN_ADMITTED_RANGE"],
            "entry_type": "symlink" if os.path.islink(VIEW / present[0]) else "regular/hardlink",
            "sample_mode": oct(st.st_mode)[-3:], "sample_uid": st.st_uid,
            "note": ("the manifest's full inventory is larger than the admitted view; the extra entries are dates "
                     "outside 2016-2021 and are NOT present in the view")}


def checkout_identity() -> dict:
    # the checkout is owned by the research account; git refuses "dubious
    # ownership" when this runs as root. Run the check AS THE OWNER rather than
    # widening git's trust with a global safe.directory exception.
    out = subprocess.run(["sudo", "-n", "-u", USER, "/opt/apex/shared/venv/bin/python", "-c",
                          "import sys,json,pathlib; sys.path.insert(0, %r);"
                          "from apex.world_model.real_data import boundary;"
                          "print(json.dumps(boundary.source_identity(pathlib.Path(%r))))" % (str(CHECKOUT), str(CHECKOUT))],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return {"error": out.stderr[-400:]}
    ident = json.loads(out.stdout)
    ident["matches_pin"] = ident["commit"] == PIN and ident["tree_sha256"] == TREE and not ident["dirty"]
    ident["launcher_sha256"] = sha(CHECKOUT / "scripts/research_activation.py")
    ident["execute_script_sha256"] = sha(CHECKOUT / "scripts/alpha_exp_real_execute.py")
    ident["registration_sha256"] = sha(CHECKOUT / "apex/world_model/exp004/registration.py")
    return ident


def own(p) -> dict:
    s = os.stat(p)
    return {"path": str(p), "uid": s.st_uid, "gid": s.st_gid, "mode": oct(s.st_mode)[-3:],
            "owner": pwd.getpwuid(s.st_uid).pw_name}


def account() -> dict:
    u = pwd.getpwnam(USER)
    groups = sorted({g.gr_name for g in grp.getgrall() if USER in g.gr_mem} | {grp.getgrgid(u.pw_gid).gr_name})
    s = subprocess.run(["sudo", "-n", "-l", "-U", USER], capture_output=True, text=True)
    txt = (s.stdout + s.stderr).strip()
    return {"user": USER, "uid": u.pw_uid, "gid": u.pw_gid, "shell": u.pw_shell, "home": u.pw_dir,
            "groups": groups, "privileged_groups": sorted(set(groups) & PRIVILEGED),
            "sudo_permitted": ("may run" in txt) or ("NOPASSWD" in txt),
            "sudo_report": txt.splitlines()[-1][:120] if txt else "",
            "login_disabled": u.pw_shell.endswith("nologin")}


def preservation() -> dict:
    names = ("exp001b_admission.json", "exp001b_admission_rev2.json", "exp002_admission.json",
             "exp004_admission.json")
    existing = {p.pw_name: p.pw_uid for p in pwd.getpwall()}
    return {"signed_decisions": {n: sha("/etc/apex/admissions/" + n) for n in names},
            "allowed_signers": sha("/etc/apex/admissions/trust/allowed_signers"),
            "exp001b_rev2_result": sha("/apex-data/research-rev2/out/ALPHA-EXP-001B/runs/"
                                       "20260909T003427Z-exp001b-914a30d3/_RESULT.json"),
            "exp002_result": sha("/apex-data/research-exp002/out/ALPHA-EXP-002/runs/"
                                 "20260909T193814Z-exp002-ca450243/_RESULT.json"),
            "exp001b_aborted_forecasts": sha("/apex-data/research/out/ALPHA-EXP-001B/runs/"
                                             "20260908T131351Z-exp001b-2054eaa4/forecasts_validation.jsonl"),
            "accounts": {n: existing.get(n, "ABSENT") for n in
                         ("apexresearch", "apexresearch2", "apexresearch3", "apexresearch4")},
            "environments": sorted(str(p) for p in Path("/apex-data").glob("research*")),
            "runner_roots": sorted(str(p) for p in Path("/opt").glob("apex-runner*")),
            "other_env_outputs_untouched": {
                p: sorted(os.listdir(p + "/out"))[:3] if os.path.isdir(p + "/out") else "NO_OUT"
                for p in ("/apex-data/research", "/apex-data/research-rev2", "/apex-data/research-exp002")}}


def probe_config(probe_json: str) -> dict:
    d = json.loads(Path(probe_json).read_text())
    props = d.get("properties", [])
    return {"ok": d.get("ok"), "executed": d.get("executed"), "deviations": d.get("deviations"),
            "memory_max_property": [p for p in props if p.startswith("MemoryMax")],
            "memory_max_is_1400M": "MemoryMax=1400M" in props,
            "user_property": [p for p in props if p.startswith("User=")],
            "paths_named": {"bind_read_only": [p for p in props if p.startswith("BindReadOnlyPaths")],
                            "read_write": [p for p in props if p.startswith("ReadWritePaths")],
                            "inaccessible": [p for p in props if p.startswith("InaccessiblePaths")]},
            "paths_are_exp004": all("exp004" in p for p in props
                                    if p.startswith(("BindReadOnlyPaths", "ReadWritePaths"))),
            "no_other_environment_named": not any(x in p for p in props
                                                  for x in ("research-rev2", "research-exp002", "apexresearch3",
                                                            "apexresearch2", "/apex-data/research/")),
            "observations": d.get("observations"), "expected": d.get("expected"),
            "admitted_example": d.get("admitted_example"), "denied_example": d.get("denied_example")}


def main(out_path: str) -> int:
    out_dir = ROOT / "out"
    rec = {"reconciliation": "EXP004_SETUP", "pin": PIN,
           "dataset_view": dataset_reconciliation(),
           "checkout_identity": checkout_identity(),
           "ownership": [own(p) for p in (ROOT, CHECKOUT, out_dir, ROOT / "dataset_view", RUNNER, RUNNER / "venv")],
           "account": account(),
           "probe": probe_config("/apex-data/qualification/exp004/probe.json"),
           "output_directory": {"path": str(out_dir), "entries": sorted(os.listdir(out_dir)),
                                "EMPTY": not os.listdir(out_dir)},
           "preservation": preservation()}
    Path(out_path).write_text(json.dumps(rec, indent=1, sort_keys=True, default=str) + "\n")
    brief = {"all_admitted_files_match": rec["dataset_view"]["all_admitted_files_match"],
             "hashes_recomputed": rec["dataset_view"]["hashes_recomputed"],
             "hash_mismatches": rec["dataset_view"]["hash_mismatches"],
             "checkout_matches_pin": rec["checkout_identity"].get("matches_pin"),
             "launcher_sha256": rec["checkout_identity"].get("launcher_sha256"),
             "account": rec["account"], "probe_1400M": rec["probe"]["memory_max_is_1400M"],
             "probe_paths_exp004": rec["probe"]["paths_are_exp004"],
             "probe_no_other_env": rec["probe"]["no_other_environment_named"],
             "probe_deviations": rec["probe"]["deviations"],
             "output_EMPTY": rec["output_directory"]["EMPTY"],
             "exp004_admission_installed": rec["preservation"]["signed_decisions"]["exp004_admission.json"],
             "accounts": rec["preservation"]["accounts"]}
    print(json.dumps(brief, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
