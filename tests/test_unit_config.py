"""Unit-file configuration lint.

SYSTEMD-CONFIG-001: apex-options-paper.service carried
StartLimitIntervalSec in [Service], where systemd ignores it. The
intended 600s restart rate-limit therefore DID NOT EXIST, and the only
evidence was one 'Unknown key name' line in the journal that nobody
read. A directive that is silently ignored is worse than one that is
absent: it creates a belief in protection that is not there.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

UNIT_DIR = Path("/etc/systemd/system")

# directives systemd only honours in [Unit]
UNIT_ONLY = {
    "StartLimitIntervalSec", "StartLimitInterval", "StartLimitBurst",
    "OnFailure", "Requires", "After", "Before", "Wants", "Conflicts",
    "PartOf", "BindsTo", "RefuseManualStart", "RefuseManualStop",
}
# directives systemd only honours in [Service]
SERVICE_ONLY = {
    "ExecStart", "ExecStop", "Restart", "RestartSec", "Type",
    "MemoryMax", "MemoryHigh", "Slice", "OOMPolicy", "User", "Group",
    "WorkingDirectory", "TimeoutStartSec", "RuntimeMaxSec",
}


def _sections(path: Path) -> list[tuple[str, str]]:
    """Return (section, key) for every directive in a unit file."""
    out, section = [], ""
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            out.append((section, key))
    return out


def _apex_units() -> list[Path]:
    if not UNIT_DIR.exists():
        return []
    return sorted(UNIT_DIR.glob("apex-*.service")) + \
        sorted(UNIT_DIR.glob("apex-*.timer"))


@pytest.mark.skipif(not _apex_units(), reason="no APEX units on host")
def test_no_directive_is_in_a_section_systemd_ignores():
    bad = []
    for p in _apex_units():
        if p.name.endswith(".bak-SYSTEMD-CONFIG-001"):
            continue
        for section, key in _sections(p):
            if key in UNIT_ONLY and section != "Unit":
                bad.append(f"{p.name}: {key} in [{section}] "
                           f"(systemd honours it only in [Unit])")
            if key in SERVICE_ONLY and section != "Service":
                bad.append(f"{p.name}: {key} in [{section}] "
                           f"(systemd honours it only in [Service])")
    assert not bad, "silently-ignored unit directives:\n" + "\n".join(bad)


@pytest.mark.skipif(not _apex_units(), reason="no APEX units on host")
def test_systemd_reports_no_unknown_keys():
    """systemd itself is the authority on what it ignored."""
    out = subprocess.run(
        ["systemd-analyze", "verify", *[str(p) for p in _apex_units()]],
        capture_output=True, text=True).stderr
    unknown = [ln for ln in out.splitlines()
               if "Unknown key name" in ln]
    assert not unknown, "systemd is ignoring directives:\n" + \
        "\n".join(unknown)


@pytest.mark.skipif(not _apex_units(), reason="no APEX units on host")
def test_no_active_apex_service_is_unbounded_in_system_slice():
    """APEX_RESOURCE_GOVERNANCE_V1's central guarantee, checked against
    the live host rather than a model of it."""
    out = subprocess.run(
        ["systemctl", "list-units", "--all", "--no-legend", "--plain",
         "apex*.service"], capture_output=True, text=True).stdout
    offenders = []
    for line in out.splitlines():
        unit = line.split()[0] if line.split() else ""
        if not unit.endswith(".service"):
            continue
        def show(p):
            return subprocess.run(
                ["systemctl", "show", unit, "-p", p, "--value"],
                capture_output=True, text=True).stdout.strip()
        if show("ActiveState") != "active":
            continue
        sl, mx = show("Slice"), show("MemoryMax")
        if not sl.startswith("apex") or mx == "infinity":
            offenders.append(f"{unit}: Slice={sl} MemoryMax={mx}")
    assert not offenders, (
        "active APEX services outside governed containment "
        "(the apex-pulse defect):\n" + "\n".join(offenders))
