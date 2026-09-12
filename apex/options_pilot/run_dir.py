"""RUN-SCOPED OUTPUT DIRECTORIES (OPERATING-LOOP-001 item 3).

Every evaluation gets its OWN directory. Collisions are refused. Nothing here ever unlinks, truncates or overwrites a
previous run's artifact.

WHY THIS EXISTS. The loop demonstration's driver wrote to a fixed directory and unlinked its ledgers on start. The
corrected re-run therefore DESTROYED the original run's JSON and all three of its ledgers, and the only surviving
account of the original is transcript testimony rather than evidence
(docs/LOOP_DEMONSTRATION_CORRECTIONS.md §1, "preservation failure"). A run that cannot be compared with the run it
corrects is not evidence about a correction.

WHAT A RUN DIRECTORY HOLDS.
    RUN_START.json     written before any work: run id, start instant, code pin, input digests, configuration digest
    RUN_COMPLETE.json  written on success: completion instant, status COMPLETED, the caller's summary
    RUN_FAILED.json    written on failure: completion instant, status FAILED, the exception type and message
    <artifacts>        ledgers, reports, traces -- each claimed once through `path_for`, which refuses a name twice

A FAILED RUN IS PRESERVED EXACTLY AS IT DIED: the partial ledger, whatever artifacts exist, and RUN_FAILED.json
naming what went wrong. Nothing is cleaned up. `status()` reads the directory back, so a reviewer can tell a
completed run, a failed run and an interrupted run apart without the process that produced them."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from . import instant as I

START_FILE = "RUN_START.json"
COMPLETE_FILE = "RUN_COMPLETE.json"
FAILED_FILE = "RUN_FAILED.json"
MARKER_FILES = (START_FILE, COMPLETE_FILE, FAILED_FILE)

PRESERVATION_POLICY = (
    "RUN_DIR_V1: one evaluation, one directory, claimed by creation. A directory that already exists is a COLLISION "
    "and is refused; an artifact name claimed twice is refused. Nothing in this module unlinks, truncates or "
    "overwrites. A failed run keeps its partial artifacts and gains a RUN_FAILED marker.")


class RunDirRefused(RuntimeError):
    """A collision, an overwrite, or a run directory that does not say what it must say."""


def digest_file(path) -> dict:
    p = Path(path)
    h = hashlib.sha256()
    n = 0
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return {"path": str(p), "sha256": h.hexdigest(), "bytes": n}


def digest_obj(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def code_pin(repo: str | Path | None = None) -> dict:
    """The exact commit the run executed, and whether the tree was dirty. UNAVAILABLE is recorded, never guessed."""
    root = str(repo or Path(__file__).resolve().parents[2])
    def git(*a):
        return subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, timeout=20)
    try:
        rev = git("rev-parse", "HEAD")
        if rev.returncode != 0:
            return {"status": "UNAVAILABLE", "why": (rev.stderr or "git rev-parse failed").strip()[:200]}
        st = git("status", "--porcelain")
        return {"status": "PINNED", "commit": rev.stdout.strip(),
                "branch": git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or None,
                "dirty": bool(st.stdout.strip()), "dirty_paths": st.stdout.strip().splitlines()[:40]}
    except Exception as e:                                                    # noqa: BLE001
        return {"status": "UNAVAILABLE", "why": "%s: %s" % (type(e).__name__, str(e)[:160])}


class RunDir:
    """A claimed, collision-free output directory for exactly one evaluation."""

    def __init__(self, path: Path, run_id: str, started_epoch: float):
        self.path = Path(path)
        self.run_id = run_id
        self.started_epoch = started_epoch
        self._claimed: dict = {}

    # -------------------------------------------------------- artifacts
    def path_for(self, name: str) -> Path:
        """Claim an artifact name. Refuses a name that already exists on disk or was already claimed in this run."""
        if not name or name in MARKER_FILES or "/" in name or name.startswith("."):
            raise RunDirRefused("ARTIFACT_NAME_REFUSED: %r (reserved, empty, nested or hidden)" % (name,))
        p = self.path / name
        if name in self._claimed:
            raise RunDirRefused("ARTIFACT_NAME_ALREADY_CLAIMED: %r in run %s; a run never writes one name twice"
                                % (name, self.run_id))
        if p.exists():
            raise RunDirRefused("ARTIFACT_EXISTS: %s; this module never overwrites an artifact" % p)
        self._claimed[name] = str(p)
        return p

    def write(self, name: str, text: str) -> Path:
        p = self.path_for(name)
        p.write_text(text)
        return p

    def write_json(self, name: str, obj) -> Path:
        return self.write(name, json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n")

    def artifacts(self) -> list:
        return sorted(f.name for f in self.path.iterdir() if f.is_file())

    # -------------------------------------------------------- terminal markers
    def _marker(self, name: str, body: dict) -> Path:
        p = self.path / name
        if p.exists():
            raise RunDirRefused("RUN_ALREADY_TERMINAL: %s exists; a run reports its outcome once" % p)
        p.write_text(json.dumps(body, indent=1, sort_keys=True, default=str) + "\n")
        return p

    def complete(self, *, now_epoch: float, summary: dict | None = None) -> Path:
        return self._marker(COMPLETE_FILE, {
            "kind": "RUN_COMPLETE", "run_id": self.run_id, "status": "COMPLETED",
            "started_utc": I.canonical_utc(self.started_epoch), "completed_utc": I.canonical_utc(now_epoch),
            "artifacts": self.artifacts(), "summary": summary or {}})

    def failed(self, *, now_epoch: float, error: BaseException | str, summary: dict | None = None) -> Path:
        err = error if isinstance(error, str) else "%s: %s" % (type(error).__name__, str(error)[:400])
        return self._marker(FAILED_FILE, {
            "kind": "RUN_FAILED", "run_id": self.run_id, "status": "FAILED", "error": err,
            "started_utc": I.canonical_utc(self.started_epoch), "failed_utc": I.canonical_utc(now_epoch),
            "artifacts_preserved": self.artifacts(), "summary": summary or {},
            "note": "the partial artifacts above are preserved exactly as the run left them; nothing was removed"})

    def status(self) -> dict:
        out = {"run_id": self.run_id, "path": str(self.path), "artifacts": self.artifacts()}
        if (self.path / COMPLETE_FILE).exists():
            out["status"] = "COMPLETED"
        elif (self.path / FAILED_FILE).exists():
            out["status"] = "FAILED"
        else:
            out["status"] = "INCOMPLETE"
            out["why"] = "neither %s nor %s is present: the run did not report an outcome" % (COMPLETE_FILE, FAILED_FILE)
        return out


def new_run(base, *, run_id: str, now_epoch: float, inputs: dict | None = None, config: dict | None = None,
            repo=None, note: str | None = None) -> RunDir:
    """Claim `base/run_id`. Refuses if it already exists, whatever it contains.

    `inputs` maps a label to a file path; each is digested so a later reviewer can prove which bytes were consumed."""
    base = Path(base)
    if not run_id or "/" in run_id or run_id.startswith("."):
        raise RunDirRefused("RUN_ID_REFUSED: %r" % (run_id,))
    path = base / run_id
    if path.exists():
        raise RunDirRefused("RUN_DIR_COLLISION: %s already exists. A run never writes into another run's directory "
                            "and never removes one; choose a new run id." % path)
    base.mkdir(parents=True, exist_ok=True)
    path.mkdir()                                            # not exist_ok: the mkdir itself is the claim
    rd = RunDir(path, run_id, now_epoch)
    digests = {}
    for label, p in (inputs or {}).items():
        try:
            digests[label] = digest_file(p)
        except OSError as e:
            digests[label] = {"path": str(p), "status": "UNREADABLE", "why": str(e)[:160]}
    body = {"kind": "RUN_START", "run_id": run_id, "status": "STARTED", "note": note,
            "started_utc": I.canonical_utc(now_epoch), "started_epoch": now_epoch,
            "started_canonical_us": I.canonical_micros(now_epoch),
            "code_pin": code_pin(repo), "inputs": digests, "config": config or {},
            "config_digest": digest_obj(config or {}), "preservation_policy": PRESERVATION_POLICY,
            "timestamp_rule": I.CONVERSION_RULE}
    (path / START_FILE).write_text(json.dumps(body, indent=1, sort_keys=True, default=str) + "\n")
    return rd
