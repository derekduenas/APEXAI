"""RESOURCE_PROFILE_V1 -- measured capacity evidence with provenance.

GOVERNANCE-TOOL-001
-------------------
build_plan.py derived production limits from the LIVE systemd
MemoryPeak counter. That counter RESETS at every service lifecycle
boundary. Minutes after ThetaTerminal was restarted it read 410 MB,
and the planner proposed MemoryMax = 615,352,320 for a service whose
real nine-day working set is 1.11 GiB. Applying that would have
strangled the dependency the restart had just rescued.

THE LAW
-------
A CURRENT MemoryPeak IS AN OBSERVATION SINCE THE LATEST LIFECYCLE
RESET -- NOT HISTORICAL EVIDENCE OF REQUIRED CAPACITY.

A limit proposal may use persistent historical peaks, credible
concurrent load, normal working set, known transient behaviour, job
criticality and host reserve. It may NOT rest on a current MemoryPeak,
a current RSS, or one post-restart sample. Where the evidence is
insufficient the answer is INSUFFICIENT_EVIDENCE_FOR_LIMIT_DERIVATION
-- never an invented cap.

VERSION-TIED EVIDENCE
---------------------
A historical peak is evidence, not an eternal requirement. A peak
observed under a defective implementation (btc_paper reading 350 MB
every 30s) must not become the permanent budget for its repaired
successor. Profiles therefore carry the release they were observed
under, and a profile whose release no longer matches is STALE rather
than authoritative.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum

PROFILE_VERSION = "RESOURCE_PROFILE_V1"
MiB = 1024 * 1024


class EvidenceQuality(Enum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT_WINDOW = "INSUFFICIENT_WINDOW"      # too little time
    INSUFFICIENT_NO_HISTORY = "INSUFFICIENT_NO_HISTORY"
    POST_RESTART_ONLY = "POST_RESTART_ONLY"          # the Theta trap
    STALE_VERSION = "STALE_VERSION"                  # code changed
    DEFECTIVE_REGIME = "DEFECTIVE_REGIME"            # peak from a bug


class LimitDerivationRefused(Exception):
    """INSUFFICIENT_EVIDENCE_FOR_LIMIT_DERIVATION."""


# minimum observation before a peak may be called capacity evidence
MIN_OBSERVATION = timedelta(hours=6)
# a market-facing service must have been observed across RTH
MIN_OBSERVATION_MARKET = timedelta(hours=24)


@dataclass
class ResourceProfile:
    service: str
    observation_start: str
    observation_end: str
    historical_peak_bytes: int | None
    current_peak_bytes: int | None
    normal_p50_bytes: int | None = None
    normal_p95_bytes: int | None = None
    lifecycle_boundaries: int = 0          # restarts inside the window
    last_restart: str | None = None
    observed_under_release: str | None = None
    market_context: str = "UNKNOWN"        # RTH / OFF_HOURS / MIXED
    sources: list[str] = field(default_factory=list)
    method: str = ""
    evidence_quality: str = EvidenceQuality.INSUFFICIENT_NO_HISTORY.value
    note: str = ""

    @property
    def observation_span(self) -> timedelta:
        try:
            return (datetime.fromisoformat(self.observation_end)
                    - datetime.fromisoformat(self.observation_start))
        except (TypeError, ValueError):
            return timedelta(0)

    @property
    def peak_is_post_restart_only(self) -> bool:
        """Did every observation happen after the last restart?"""
        if not self.last_restart:
            return False
        try:
            lr = datetime.fromisoformat(self.last_restart)
            start = datetime.fromisoformat(self.observation_start)
        except (TypeError, ValueError):
            return False
        return lr >= start and self.historical_peak_bytes is None

    def profile_hash(self) -> str:
        d = {k: v for k, v in asdict(self).items() if k != "note"}
        return hashlib.sha256(
            json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["profile_version"] = PROFILE_VERSION
        d["observation_span_hours"] = round(
            self.observation_span.total_seconds() / 3600, 2)
        d["profile_hash"] = self.profile_hash()
        return d


def assess(profile: ResourceProfile, *, market_facing: bool = False,
           current_release: str | None = None) -> EvidenceQuality:
    """Decide whether this profile may drive a production limit."""
    if (current_release and profile.observed_under_release
            and profile.observed_under_release != current_release):
        return EvidenceQuality.STALE_VERSION
    if profile.evidence_quality == EvidenceQuality.DEFECTIVE_REGIME.value:
        return EvidenceQuality.DEFECTIVE_REGIME
    if profile.historical_peak_bytes is None:
        if profile.current_peak_bytes is not None:
            return EvidenceQuality.POST_RESTART_ONLY
        return EvidenceQuality.INSUFFICIENT_NO_HISTORY
    if profile.peak_is_post_restart_only:
        return EvidenceQuality.POST_RESTART_ONLY
    need = MIN_OBSERVATION_MARKET if market_facing else MIN_OBSERVATION
    if profile.observation_span < need:
        return EvidenceQuality.INSUFFICIENT_WINDOW
    return EvidenceQuality.SUFFICIENT


def derive_limits(profile: ResourceProfile, *, multiplier: float = 1.5,
                  market_facing: bool = False,
                  current_release: str | None = None) -> dict:
    """Propose (MemoryHigh, MemoryMax) or REFUSE.

    Never falls back to the current peak. Refusing is the correct
    answer when the evidence cannot support a number.
    """
    q = assess(profile, market_facing=market_facing,
               current_release=current_release)
    if q is not EvidenceQuality.SUFFICIENT:
        raise LimitDerivationRefused(
            f"INSUFFICIENT_EVIDENCE_FOR_LIMIT_DERIVATION: "
            f"{profile.service} -> {q.value}. "
            f"historical_peak={profile.historical_peak_bytes} "
            f"span={profile.observation_span} "
            f"restarts={profile.lifecycle_boundaries}")
    base = profile.historical_peak_bytes
    assert base is not None
    return {
        "service": profile.service,
        "MemoryHigh": base,
        "MemoryMax": int(base * multiplier),
        "derived_from": "historical_peak_bytes",
        "evidence_quality": q.value,
        "observation_span_hours": round(
            profile.observation_span.total_seconds() / 3600, 2),
        "profile_hash": profile.profile_hash(),
        "LAW": "a current MemoryPeak is an observation since the "
               "latest lifecycle reset, not historical evidence of "
               "required capacity",
    }


# ------------------------------------------------------------ harvest
_PEAK_RE = re.compile(r"([\d.]+)([KMG])\s+memory peak", re.I)
# systemd's own journal lines, e.g.
#   2026-09-02T02:05:11+0000 APEX systemd[1]: Started apex-x.service
_SYSTEMD_LINE = re.compile(r"^\S+\s+\S+\s+systemd\[1\]:")
_MULT = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}


def harvest_historical_peak(unit: str, *, since: str = "-30d") -> dict:
    """Recover peaks from systemd's OWN post-run accounting.

    systemd logs 'Consumed ... N memory peak' when a unit stops. Those
    lines survive restarts, which is exactly what the live MemoryPeak
    counter does not.
    """
    out = subprocess.run(
        ["sudo", "journalctl", "-u", unit, "--since", since,
         "--no-pager", "-o", "short-iso"],
        capture_output=True, text=True).stdout
    peaks, restarts, first, last = [], 0, None, None
    for ln in out.splitlines():
        ts = ln.split()[0] if ln.split() else None
        if ts:
            first = first or ts
            last = ts
        # ONLY systemd's own messages. Grepping raw journal text for
        # "Started " also matches the SERVICE'S OWN application log
        # output: that false positive reported 700 restarts for
        # apex-catalyst, which has actually run unbroken for 3.2 days
        # with NRestarts=0. Substrate facts must come from the
        # substrate, not from text a service printed about itself.
        if _SYSTEMD_LINE.match(ln) and "Started " in ln:
            restarts += 1
        m = _PEAK_RE.search(ln) if _SYSTEMD_LINE.match(ln) else None
        if m:
            peaks.append(int(float(m.group(1)) * _MULT[m.group(2).upper()]))
    return {
        "unit": unit, "peaks_found": len(peaks),
        "historical_peak_bytes": max(peaks) if peaks else None,
        "restarts_in_window": restarts,
        "first_seen": first, "last_seen": last,
        "KNOWN_BLIND_SPOT": (
            "systemd emits its 'N memory peak' accounting on a CLEAN "
            "stop. A run terminated by SIGKILL (OOM) contributes no "
            "peak record, so for a service that dies by OOM this "
            "harvest UNDER-REPORTS: equity-fabric returns 1.61 GB here "
            "while its OOM kills occurred against a 2.5 GB cap. Treat "
            "a harvested peak as a LOWER BOUND, and cross-check the "
            "kernel OOM record for services with oom_kill > 0."),
    }


def build_profile(unit: str, *, since: str = "-30d",
                  current_peak: int | None = None,
                  release: str | None = None,
                  market_context: str = "UNKNOWN") -> ResourceProfile:
    h = harvest_historical_peak(unit, since=since)
    now = datetime.now(timezone.utc).isoformat()
    lr = subprocess.run(
        ["systemctl", "show", unit, "-p", "ExecMainStartTimestamp",
         "--value"], capture_output=True, text=True).stdout.strip()
    p = ResourceProfile(
        service=unit,
        observation_start=h["first_seen"] or now,
        observation_end=h["last_seen"] or now,
        historical_peak_bytes=h["historical_peak_bytes"],
        current_peak_bytes=current_peak,
        lifecycle_boundaries=h["restarts_in_window"],
        last_restart=lr or None,
        observed_under_release=release,
        market_context=market_context,
        sources=[f"journalctl -u {unit} (systemd post-run accounting)"],
        method="max of systemd 'N memory peak' records, which survive "
               "restarts; the live MemoryPeak counter does not")
    p.evidence_quality = assess(p).value
    return p
