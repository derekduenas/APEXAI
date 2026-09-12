#!/usr/bin/env python3
"""Measure the privilege paths available to a research identity.

"Not in sudoers" is not the question. An account can reach root through a
supplementary group (docker, lxd, disk, shadow), a writable directory on
root's PATH, a writable systemd unit or cron file, an ACL, or a writable
file that a privileged process later reads or runs. This audit enumerates
those paths for a named account and records what it MEASURED and what it
could not measure. It changes nothing and needs no privileges of its own.

    python scripts/research_identity_privilege_audit.py <out.json> [username]

With no username it audits the account running it. A username that does not
exist yet is reported as NOT_PRESENT together with the checks that must be
re-run after it is created -- an audit of a non-existent account is a plan,
not evidence, and is labelled as such.
"""
from __future__ import annotations

import grp
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Groups that confer root-equivalent or near-root capability on a Debian host.
PRIVILEGED_GROUPS = {
    "root": "uid 0 group", "sudo": "sudo(8) access", "admin": "legacy sudo group",
    "wheel": "su/sudo group", "adm": "reads system logs", "shadow": "reads /etc/shadow",
    "disk": "raw block device access = read/write any file", "docker": "docker socket = root",
    "lxd": "container creation = root", "kvm": "vm host access", "systemd-journal": "reads all logs",
    "staff": "writes /usr/local", "video": "device access",
}
# Paths whose writability by the audited account would be a privilege path.
SENSITIVE_PATHS = [
    "/etc", "/etc/sudoers.d", "/etc/systemd/system", "/lib/systemd/system",
    "/usr/lib/systemd/system", "/etc/cron.d", "/etc/cron.daily", "/etc/profile.d",
    "/usr/local/bin", "/usr/local/sbin", "/usr/bin", "/bin",
    "/var/run/docker.sock", "/etc/apex", "/etc/apex/admissions",
    "/etc/apex/admissions/trust", "/opt/apex", "/opt/apex/current", "/opt/apex-repo",
    "/apex-data", "/apex-data/core", "/apex-data/core/ops", "/apex-data/history-a",
    "/apex-data/history-b", "/apex-data/research", "/home/apex/.apex-secrets",
    "/opt/apex/shared", "/opt/apex/shared/venv", "/opt/apex/shared/venv/lib",
]
SETUID_DIRS = ["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/usr/local/sbin"]
# setuid binaries that are ordinary on a Debian/Ubuntu host; anything else is listed
EXPECTED_SETUID = {
    "su", "sudo", "mount", "umount", "passwd", "chsh", "chfn", "gpasswd", "newgrp",
    "pkexec", "fusermount", "fusermount3", "ping", "ping6", "at", "chage", "expiry",
    "ssh-agent", "unix_chkpwd", "pam_extrausers_chkpwd", "dbus-daemon-launch-helper",
    "polkit-agent-helper-1", "snap-confine", "mount.nfs", "sg", "write",
    "crontab", "sudoedit", "umount.nfs", "chrt", "bsd-write",
}
SETUID_ALLOWLIST_NOTE = ("EXPECTED_SETUID is a conservative allowlist of binaries that are standard "
                         "on this distribution; its purpose is to surface UNUSUAL setuid binaries, "
                         "not to certify the standard ones")


def _facts(p: Path) -> dict:
    try:
        st = os.stat(p)
    except OSError as e:
        return {"path": str(p), "present": False, "error": str(e)}
    mode = stat.S_IMODE(st.st_mode)
    return {"path": str(p), "present": True, "uid": st.st_uid, "gid": st.st_gid,
            "mode": "%o" % mode, "sticky": bool(st.st_mode & stat.S_ISVTX),
            "group_writable": bool(mode & stat.S_IWGRP),
            "other_writable": bool(mode & stat.S_IWOTH)}


ACL_TOOL = shutil.which("getfacl")


def _acl(p: Path) -> str | None:
    """None means EITHER no extra ACL entries OR no getfacl on the host --
    the caller records acl_tool_available so the two are never confused."""
    if not ACL_TOOL:
        return None
    try:
        r = subprocess.run(["getfacl", "-p", "--omit-header", str(p)],
                           capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return None
        lines = [l for l in r.stdout.splitlines() if l and not l.startswith(("user::", "group::", "other::"))]
        return "; ".join(lines) or None
    except (OSError, subprocess.SubprocessError):
        return None


def account(username: str | None) -> dict:
    if username is None:
        pw = pwd.getpwuid(os.geteuid())
    else:
        try:
            pw = pwd.getpwnam(username)
        except KeyError:
            return {"name": username, "present": False,
                    "note": "account does not exist yet; the checks below are a PLAN, not evidence, "
                            "and must be re-run after creation"}
    groups = sorted({g.gr_name for g in grp.getgrall() if pw.pw_name in g.gr_mem}
                    | {grp.getgrgid(pw.pw_gid).gr_name})
    return {"name": pw.pw_name, "present": True, "uid": pw.pw_uid, "gid": pw.pw_gid,
            "home": pw.pw_dir, "shell": pw.pw_shell, "groups": groups,
            "privileged_groups": {g: PRIVILEGED_GROUPS[g] for g in groups if g in PRIVILEGED_GROUPS}}


def sudo_rights(self_audit: bool) -> dict:
    if not self_audit:
        return {"measured": False,
                "why": "sudo -n -l reports for the CALLING account only; for another account it must "
                       "be run as that account (see the verification command in the operator package)"}
    try:
        r = subprocess.run(["sudo", "-n", "-l"], capture_output=True, text=True, timeout=30)
        txt = ((r.stdout or "") + (r.stderr or "")).strip()
        return {"measured": True, "returncode": r.returncode, "output": txt[:2000],
                "can_become_root": ("NOPASSWD: ALL" in txt) or ("(ALL : ALL) ALL" in txt)
                or ("(ALL) ALL" in txt)}
    except (OSError, subprocess.SubprocessError) as e:
        return {"measured": False, "error": str(e)}


def main(out_path: str, username: str | None) -> int:
    self_audit = username is None or username == pwd.getpwuid(os.geteuid()).pw_name
    acct = account(username)
    rec = {"produced_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "audited_account": acct, "audited_by_euid": os.geteuid(), "self_audit": self_audit,
           "sudo": sudo_rights(self_audit), "setuid_allowlist_note": SETUID_ALLOWLIST_NOTE,
           "acl_tool_available": bool(ACL_TOOL),
           "acl_note": ("getfacl is %s on this host; a null acl field therefore means %s"
                        % ("present" if ACL_TOOL else "ABSENT",
                           "no extra ACL entries" if ACL_TOOL else
                           "UNMEASURED, not 'no ACLs' -- install the acl package to measure")),
           "paths": [], "setuid_unexpected": [],
           "writable_path_dirs": [], "limitations": [
               "writability is tested with the CALLING account's credentials; for another account "
               "these are structural facts (owner, mode, ACL) plus a group-membership implication, "
               "not a live access test",
               "this enumerates known privilege paths; it cannot prove none exists",
               "an account with sudo defeats every filesystem fact recorded here",
               "a passing audit is evidence about the paths enumerated here; it cannot prove that "
               "no privilege path exists",
           ]}
    for p in SENSITIVE_PATHS:
        f = _facts(Path(p))
        if f.get("present"):
            f["acl"] = _acl(Path(p))
            f["writable_by_caller"] = os.access(p, os.W_OK)
            gname = grp.getgrgid(f["gid"]).gr_name if f["gid"] is not None else None
            f["group_name"] = gname
            f["reachable_by_audited_account"] = bool(
                (acct.get("present") and f["uid"] == acct.get("uid"))
                or f["other_writable"]
                or (f["group_writable"] and gname in (acct.get("groups") or [])))
        rec["paths"].append(f)
    for d in SETUID_DIRS:
        dp = Path(d)
        if not dp.is_dir():
            continue
        try:
            for e in sorted(dp.iterdir()):
                try:
                    st = e.stat()
                except OSError:
                    continue
                if st.st_mode & (stat.S_ISUID | stat.S_ISGID) and e.name not in EXPECTED_SETUID:
                    real = os.path.realpath(e)       # /bin is a symlink to /usr/bin here
                    if real in {x["realpath"] for x in rec["setuid_unexpected"]}:
                        continue
                    rec["setuid_unexpected"].append({"path": str(e), "realpath": real,
                                                     "uid": st.st_uid,
                                                     "mode": "%o" % stat.S_IMODE(st.st_mode)})
        except OSError:
            continue
    for d in os.environ.get("PATH", "").split(":"):
        if d and os.path.isdir(d) and os.access(d, os.W_OK):
            rec["writable_path_dirs"].append(d)
    reachable = [f["path"] for f in rec["paths"] if f.get("reachable_by_audited_account")]
    rec["verdict"] = {
        "privileged_group_memberships": list((acct.get("privileged_groups") or {}).keys()),
        "sudo_can_become_root": rec["sudo"].get("can_become_root"),
        "sensitive_paths_reachable": reachable,
        "writable_path_dirs": rec["writable_path_dirs"],
        "unexpected_setuid": [x["path"] for x in rec["setuid_unexpected"]],
        "suitable_as_research_identity": bool(
            acct.get("present") and not acct.get("privileged_groups")
            and not rec["sudo"].get("can_become_root")
            and not rec["writable_path_dirs"]
            and not [p for p in reachable if p.startswith(("/etc", "/opt/apex", "/apex-data/core",
                                                           "/apex-data/history", "/home/apex/.apex-secrets"))]),
    }
    Path(out_path).write_text(json.dumps(rec, indent=1, sort_keys=True, default=str))
    print(json.dumps({"account": acct.get("name"), "present": acct.get("present"),
                      "groups": acct.get("groups"),
                      "privileged_groups": list((acct.get("privileged_groups") or {}).keys()),
                      "sudo_can_become_root": rec["sudo"].get("can_become_root"),
                      "sensitive_paths_reachable": reachable,
                      "writable_path_dirs": rec["writable_path_dirs"],
                      "unexpected_setuid": rec["verdict"]["unexpected_setuid"],
                      "suitable_as_research_identity": rec["verdict"]["suitable_as_research_identity"]},
                     indent=1))
    return 0


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
