"""Pre-registration and period-lock guards.

Three mechanical gates, none of which depends on anyone remembering a rule.

1. SIGNATURE. The protocol header carries blank `Registered:` and `Author:`
   fields, and CONVENTIONS.md carries a blank `Author:`. An unsigned
   pre-registration is not one. `require_signed()` refuses to load real vendor
   data while any placeholder remains. Synthetic data is exempt -- Stages 1-3
   are pipeline verification and touch no real prices.

2. PROTOCOL PIN. CONVENTIONS.md records the protocol's SHA-256 in its header.
   Nothing ever checked it, so the single most damaging silent change available
   -- editing a threshold in the pre-registration after seeing a result -- was
   possible without trace. `require_protocol_unmodified()` recomputes the hash
   and refuses if it has moved.

3. PERIOD LOCK. Opening a budgeted period takes a hand-created token file AND a
   research credit. The token is the deliberate act; the ledger is the
   accounting, and the two are separate on purpose -- deleting a token does not
   restore a credit, because the credit was already spent.

The ledger (apex/governance/ledger.py) enforces the budget, refuses a second
look by the same experiment, and is hash-chained so that deleting a failed
experiment is detected rather than rewarded.
"""

from __future__ import annotations

import re
from pathlib import Path

from apex.config import REPO_ROOT, Config, file_hash, git_sha
from apex.dev.namespace import require_confirmatory
from apex.governance.ledger import ResearchLedger

PLACEHOLDER = re.compile(r"_{3,}")
# CONVENTIONS pins each experiment's protocol beside its FILENAME:
#     **Governs:** `<file>.md`, SHA-256 `<64 hex>`
# Keyed on the filename, not on "first hash in the document" -- CONVENTIONS now
# pins more than one protocol (#001 in the header, #002 in section 8), and a
# positional match would validate #002 against #001's pin.
def _pin_pattern(filename: str) -> "re.Pattern":
    return re.compile(
        re.escape(filename) + r"`?,?\s*SHA-256\s*`?([0-9a-f]{64})`?", re.IGNORECASE
    )


class RegistrationError(RuntimeError):
    """The pre-registration is not signed, was modified, or a locked period was addressed."""


def _header(text: str, n_lines: int = 20) -> str:
    return "\n".join(text.splitlines()[:n_lines])


def _paths(config: Config, repo_root: Path | None) -> tuple[Path, Path]:
    root = repo_root or REPO_ROOT
    return (
        root / config.get("experiment.protocol_file"),
        root / config.get("experiment.conventions_file"),
    )


# ---------------------------------------------------------------------------
# 1. signature
# ---------------------------------------------------------------------------


def signature_status(config: Config, repo_root: Path | None = None) -> dict:
    """Report which registration fields are still placeholders."""
    protocol, conventions = _paths(config, repo_root)

    missing: list[str] = []
    for path, label in ((protocol, "protocol"), (conventions, "conventions")):
        if not path.exists():
            raise RegistrationError(f"{label} document not found at {path}")
        for line in _header(path.read_text(encoding="utf-8")).splitlines():
            if PLACEHOLDER.search(line) and any(
                key in line for key in ("Registered", "Author", "SHA-256")
            ):
                missing.append(f"{label}: {line.strip()}")

    return {
        "signed": not missing,
        "unsigned_fields": missing,
        "protocol_hash": file_hash(protocol),
        "conventions_hash": file_hash(conventions),
    }


def require_signed(config: Config, repo_root: Path | None = None) -> dict:
    """Gate real-data loading on a signed pre-registration.

    Raises rather than warns. A warning would be ignored exactly once, which is
    all it takes.
    """
    status = signature_status(config, repo_root)
    if not status["signed"]:
        fields = "\n  ".join(status["unsigned_fields"])
        raise RegistrationError(
            "pre-registration is UNSIGNED -- refusing to load real market data.\n"
            "  The following fields are still placeholders:\n  "
            f"{fields}\n"
            "  Fill and freeze them, commit, then re-run. Synthetic data "
            "(Stages 1-3) does not require a signature."
        )
    return status


# ---------------------------------------------------------------------------
# 2. protocol pin
# ---------------------------------------------------------------------------


def protocol_pin_status(config: Config, repo_root: Path | None = None) -> dict:
    """Compare the protocol's actual hash against the one CONVENTIONS pins."""
    protocol, conventions = _paths(config, repo_root)
    if not conventions.exists():
        raise RegistrationError(f"conventions document not found at {conventions}")

    # Search the WHOLE document: #002's pin is in section 8, not the header.
    match = _pin_pattern(protocol.name).search(conventions.read_text(encoding="utf-8"))
    pinned = match.group(1).lower() if match else None
    actual = file_hash(protocol)

    return {
        "pinned_hash": pinned,
        "actual_hash": actual,
        "matches": pinned is not None and pinned == actual,
    }


def require_protocol_unmodified(config: Config, repo_root: Path | None = None) -> dict:
    """Refuse to proceed if the pre-registration has changed since it was pinned."""
    if not bool(config.get("governance.enforce_protocol_pin")):
        return protocol_pin_status(config, repo_root)

    status = protocol_pin_status(config, repo_root)
    if status["pinned_hash"] is None:
        raise RegistrationError(
            "CONVENTIONS.md does not pin a protocol SHA-256 in its header. "
            "An unpinned pre-registration can be edited without trace."
        )
    if not status["matches"]:
        raise RegistrationError(
            "the protocol has been MODIFIED since it was frozen.\n"
            f"  CONVENTIONS pins: {status['pinned_hash']}\n"
            f"  actual hash:      {status['actual_hash']}\n"
            "  Protocol section 10: a modified specification is a new hypothesis "
            "requiring a new pre-registration. If the change is legitimate, record "
            "it in the amendment log, re-pin the hash, and register a new "
            "experiment id -- do not edit in place."
        )
    return status


# ---------------------------------------------------------------------------
# 3. period lock
# ---------------------------------------------------------------------------


def open_ledger(config: Config, repo_root: Path | None = None) -> ResearchLedger:
    root = repo_root or REPO_ROOT
    return ResearchLedger(
        path=root / config.get("governance.ledger_file"),
        budget=int(config.get("governance.research_budget")),
    )


def unlock_token_path(period: str, repo_root: Path | None = None) -> Path:
    """THE canonical location of a period's unlock token.

    One definition, because the alternative was tried and failed. The dry-run
    certification computed this path independently as `REPO/validation.unlock`,
    which is not where tokens live. Its "no unlock token exists" check therefore
    read a location that can never exist, passed vacuously, and reported clean
    governance while a real token sat at the true path. A guard that cannot
    fail is not a guard.

    Every caller -- the gate that enforces the lock and any report that
    describes it -- must resolve the path through here, so the two cannot drift
    apart again.
    """
    root = repo_root or REPO_ROOT
    return (root / "results" / "_unlocks" / f"{period}.unlock").resolve()


def unlock_token_status(period: str, repo_root: Path | None = None) -> dict:
    """Report-facing view of the token. Reads; never creates."""
    token = unlock_token_path(period, repo_root)
    present = token.exists()
    return {
        "path": str(token),
        "present": present,
        "authorises": token.read_text(encoding="utf-8").strip() if present else None,
    }


def require_unlocked(
    config: Config, period: str, dataset_hash: str, repo_root: Path | None = None
) -> None:
    """Gate execution against a locked evaluation period.

    Unlocked periods (in-sample) return immediately and cost nothing. A locked
    period requires BOTH a hand-created token -- a decision with a date and a
    rationale, not a command-line flag -- and an available research credit.
    """
    root = repo_root or REPO_ROOT
    spec = config.period(period)
    if not spec.get("locked", True):
        # in-sample is unlocked, free, and has no statistical standing. Running
        # DEVELOPMENT data here is the entire point of the development path, so
        # it is deliberately NOT refused.
        return

    # Every BUDGETED period refuses development data, before the token is even
    # looked at.
    require_confirmatory(dataset_hash, context=f"opening locked period '{period}'")

    token = unlock_token_path(period, repo_root)
    if not token.exists():
        raise RegistrationError(
            f"period '{period}' ({spec['start']} to {spec['end']}) is LOCKED.\n"
            f"  Directive section 4 grants {config.get('governance.research_budget')} "
            f"confirmatory evaluations in total, and this would spend one.\n"
            f"  To spend it, create the token file by hand:\n"
            f"      {token}\n"
            f"  containing a one-line reason and today's date. Creating it is a "
            f"decision with a date and a rationale, not a command-line flag."
        )

    # The token must NAME the experiment it authorises.
    #
    # `results/_unlocks/validation.unlock` survives the run that spent it, so a
    # later experiment finds a token already sitting there and the token gate
    # waves it through. The ledger still refuses a repeat of the same
    # (experiment, period), but a DIFFERENT experiment would sail past a stale
    # token that was never written for it. Binding the token to the experiment
    # id closes that, and keeps the token a deliberate act per experiment rather
    # than a file that happens to exist.
    experiment_id = config.get("experiment.id")
    authorisation = token.read_text(encoding="utf-8")
    if experiment_id not in authorisation:
        raise RegistrationError(
            f"the unlock token at {token} does not authorise '{experiment_id}'.\n"
            f"  It reads: {authorisation.strip()!r}\n"
            f"  A token is per-experiment. A stale token left behind by an\n"
            f"  earlier experiment must not open a period for a later one.\n"
            f"  Write a new token naming '{experiment_id}' and a dated reason."
        )

    status = signature_status(config, repo_root)
    ledger = open_ledger(config, repo_root)
    ledger.spend(
        experiment_id=config.get("experiment.id"),
        hypothesis=config.get("experiment.hypothesis"),
        period=period,
        config_hash=config.hash,
        protocol_hash=status["protocol_hash"],
        conventions_hash=status["conventions_hash"],
        git_sha=git_sha(root),
        dataset_hash=dataset_hash,
        reason=token.read_text(encoding="utf-8").strip(),
    )
