"""Pre-registration and period-lock guards.

Two mechanical gates, neither of which depends on anyone remembering a rule.

1. SIGNATURE. The protocol header carries blank `Registered:` and `Author:`
   fields, and CONVENTIONS.md carries a blank `Author:`. An unsigned
   pre-registration is not one. `require_signed()` refuses to load real vendor
   data while any placeholder remains. Synthetic data is exempt -- Stages 1-3
   are pipeline verification and touch no real prices.

2. PERIOD LOCK. Validation (2018-2021) and holdout (2022-2026) each get ONE
   evaluation, ever. `require_unlocked()` refuses to run against a locked period
   unless a hand-created token file exists, and every unlock is appended to an
   immutable log. This is deliberately not a flag: it takes a separate,
   deliberate act outside the run command.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from apex.config import REPO_ROOT, Config, file_hash

PLACEHOLDER = re.compile(r"_{3,}")
UNLOCK_DIR = REPO_ROOT / "results" / "_unlocks"
UNLOCK_LOG = REPO_ROOT / "results" / "unlock_log.jsonl"


class RegistrationError(RuntimeError):
    """The pre-registration is not signed, or a locked period was addressed."""


def _header(text: str, n_lines: int = 20) -> str:
    return "\n".join(text.splitlines()[:n_lines])


def signature_status(config: Config, repo_root: Path | None = None) -> dict:
    """Report which registration fields are still placeholders."""
    root = repo_root or REPO_ROOT
    protocol = root / config.get("experiment.protocol_file")
    conventions = root / config.get("experiment.conventions_file")

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


def require_unlocked(config: Config, period: str, repo_root: Path | None = None) -> None:
    """Gate execution against a locked evaluation period.

    protocol section 7: validation gets one evaluation; the holdout gets one
    evaluation, once, ever. In-sample is unlocked because it is explicitly for
    pipeline verification.
    """
    root = repo_root or REPO_ROOT
    spec = config.period(period)
    if not spec.get("locked", True):
        return

    token = (root / "results" / "_unlocks" / f"{period}.unlock").resolve()
    if not token.exists():
        raise RegistrationError(
            f"period '{period}' ({spec['start']} to {spec['end']}) is LOCKED.\n"
            f"  protocol section 7 grants it ONE evaluation, ever.\n"
            f"  To spend it, create the token file by hand:\n"
            f"      {token}\n"
            f"  containing a one-line reason and today's date. Creating it is a "
            f"decision with a date and a rationale, not a command-line flag."
        )

    log_path = root / "results" / "unlock_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    prior = []
    if log_path.exists():
        prior = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    spent = [entry for entry in prior if entry.get("period") == period]
    if spent:
        raise RegistrationError(
            f"period '{period}' has ALREADY been evaluated on "
            f"{spent[0]['timestamp']} (config {spent[0]['config_hash'][:12]}).\n"
            f"  protocol section 7 grants one evaluation, once, ever. A second run is "
            f"not available. A modified specification is a new hypothesis "
            f"requiring a new pre-registration."
        )

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "period": period,
                    "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "config_hash": config.hash,
                    "reason": token.read_text(encoding="utf-8").strip(),
                }
            )
            + "\n"
        )
