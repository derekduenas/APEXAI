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
# CONVENTIONS.md header: "... SHA-256 `a569c718...`"
PINNED_HASH = re.compile(r"SHA-256\s*`?([0-9a-f]{64})`?", re.IGNORECASE)


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

    match = PINNED_HASH.search(_header(conventions.read_text(encoding="utf-8")))
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

    token = (root / "results" / "_unlocks" / f"{period}.unlock").resolve()
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
