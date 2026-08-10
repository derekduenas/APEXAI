"""The development-dataset namespace, and the refusals that enforce it.

Requirement, 2026-08-10: "Build the development path so misuse is structurally
impossible, not merely documented."

THE THREAT MODEL

Not a dishonest operator. An ordinary one, months from now, who runs the
development pipeline because it is the one that works, sees a promising number,
and has never read DATA_LIMITATIONS.md. Documentation does not stop that person.
A raised exception does.

FOUR INDEPENDENT REFUSALS

Deliberately redundant, because any one of them may eventually be removed by
someone refactoring in good faith:

  1. `apex/evaluate/verdict.py`   -- no promotion verdict for a dev dataset
  2. `apex/governance/ledger.py`  -- no credit spent, no result recorded
  3. `apex/registration.py`       -- no budgeted period opened
  4. `development_banner()`       -- every dev report stamped, and the stamp
                                     cannot be applied to confirmatory data

WHAT IS *NOT* BLOCKED

Running the development dataset through the in-sample period. That is the whole
point of the exercise, costs no credit, and has no statistical standing under
protocol section 7. A guard that blocked it would make the development path
useless and would be quietly removed -- which is how guards die.
"""

from __future__ import annotations

import hashlib

DEV_PREFIX = "dev-"

LIMITATIONS_DOC = "DATA_LIMITATIONS.md"


class DevelopmentDatasetRefused(RuntimeError):
    """A development dataset was offered where only confirmatory data is valid."""


def dev_fingerprint(source: str, digest: str) -> str:
    """Mint a fingerprint that is permanently marked as development.

    The prefix is part of the identity, not metadata attached to it, so it
    survives serialisation, copying into the ledger, and being passed through
    code that knows nothing about development datasets.
    """
    if not source or not digest:
        raise ValueError("a development fingerprint needs both a source and a digest")
    body = hashlib.sha256(f"{source}|{digest}".encode()).hexdigest()[:48]
    return f"{DEV_PREFIX}{source}-{body}"


def is_development(fingerprint: str) -> bool:
    return bool(fingerprint) and str(fingerprint).startswith(DEV_PREFIX)


def require_confirmatory(fingerprint: str, context: str) -> None:
    """Refuse a development dataset wherever real evidence is required.

    Called from the verdict layer, the ledger and the period gate. The message
    names the document rather than summarising it, so the reader goes and reads
    the actual limitations instead of trusting a one-line paraphrase.
    """
    if not fingerprint or not str(fingerprint).strip():
        raise DevelopmentDatasetRefused(
            f"{context}: no dataset fingerprint supplied. A result without a "
            f"dataset fingerprint is not a result (ruling 1, 2026-08-09)."
        )
    if is_development(fingerprint):
        raise DevelopmentDatasetRefused(
            f"{context}: REFUSED -- '{fingerprint}' is a DEVELOPMENT dataset.\n"
            f"  Development data is for exercising the machinery only. It is\n"
            f"  survivorship-contaminated, its prices are not corporate-action\n"
            f"  adjusted, and its sector classification is a non-point-in-time\n"
            f"  proxy. Any number computed from it is NOT EVIDENCE about\n"
            f"  Experiment #001, however good it looks.\n"
            f"  See {LIMITATIONS_DOC} for the full list of what this dataset\n"
            f"  cannot establish."
        )


def development_banner(fingerprint: str) -> str:
    """The stamp that heads every development report.

    Raises on a confirmatory fingerprint: a label that can be applied to real
    results would tell the reader nothing.
    """
    if not is_development(fingerprint):
        raise ValueError(
            f"'{fingerprint}' is not a development dataset; the "
            f"DEVELOPMENT / NON-CONFIRMATORY banner must not be applied to it"
        )
    return (
        "=" * 78 + "\n"
        "  DEVELOPMENT / NON-CONFIRMATORY\n"
        "=" * 78 + "\n"
        f"  dataset: {fingerprint}\n"
        "\n"
        "  This run exercises the APEX machinery against real-world data.\n"
        "  It is NOT evidence about Experiment #001 and cannot become so.\n"
        "\n"
        "  The universe is survivorship-contaminated to an UNMEASURABLE degree.\n"
        "  Prices are not corporate-action adjusted. Sector is a non-PIT proxy.\n"
        "  Any information coefficient below is MEANINGLESS as a finding.\n"
        "\n"
        f"  Limitations: {LIMITATIONS_DOC}\n"
        "  No research credit consumed. No verdict produced. Holdout untouched.\n"
        + "=" * 78
    )
