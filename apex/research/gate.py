"""The discovery -> screen -> human boundary (Parts 9 and 10).

The flow is fixed:

    swarm -> ResearchDossier -> novelty/governance -> cheap screen
          -> SURVIVE/REJECT -> human review -> (human) APEX registration

This module implements everything up to, and STOPPING AT, the human review. It
cannot register an experiment, spend a credit, or reach the holdout. It imports
the certified screen and calls it unchanged -- the screen stays reject-only and
this layer adds no tuning surface.

MECHANICAL VISIBILITY OF ITERATION (Part 9)
-------------------------------------------
If a researcher changes a window, threshold, weight, universe or transformation
after seeing a screening result, that is a NEW hypothesis with a new
`dossier_hash`, logged as a separate screening event. Nothing here lets an
edited idea keep the identity of the one that was screened -- the hash is over
the content, so a changed idea cannot wear the old idea's result.

THE HUMAN GATE STOPS THE MACHINE (Part 10)
------------------------------------------
`ReviewPacket` assembles everything a human needs and answers nothing for them.
It does not decide; it presents. Registration is a separate signed act the
human performs outside this module, and `assert_not_auto_registerable` proves
this layer exposes no path that could create an experiment.
"""

from __future__ import annotations

from dataclasses import dataclass

from apex.governance.screening import (
    REJECT,
    SURVIVE,
    ScreenLog,
    ScreenOutcome,
    ScreenWindow,
    run_screen,
)
from apex.research.hypothesis import DUPLICATE, REDUNDANT
from apex.research.swarm import ResearchDossier


class GateError(RuntimeError):
    """A boundary rule was violated."""


def screen_dossier(
    dossier: ResearchDossier,
    screen_fn,
    log: ScreenLog,
    window: ScreenWindow,
    config,
) -> ScreenOutcome:
    """Send a research dossier to the CERTIFIED screen. Reject-only, unchanged.

    A governance pre-check runs first: a DUPLICATE or REDUNDANT hypothesis is
    refused before the screen is even invoked, so the screen log is not filled
    with ideas already known to be non-novel.
    """
    if dossier.novelty.classification in (DUPLICATE, REDUNDANT):
        raise GateError(
            f"hypothesis is {dossier.novelty.classification}; it does not reach "
            f"the screen. {'; '.join(dossier.novelty.reasons)}"
        )
    # The screen validates, hashes, logs and enforces S1-S13 itself. This layer
    # adds nothing to it.
    return run_screen(dossier.hypothesis.screenable(), screen_fn, log, window, config)


@dataclass(frozen=True)
class ReviewPacket:
    """What a human sees before deciding whether to spend a credit (Part 10).

    Presents; never decides. Every question the human must answer is listed and
    left UNANSWERED -- the packet supplies the evidence, the human supplies the
    judgement.
    """

    dossier: ResearchDossier
    screen_verdict: str

    QUESTIONS = (
        "Is the economic mechanism credible?",
        "Is the hypothesis genuinely novel?",
        "Is the construction fully specified?",
        "Is it PIT-safe?",
        "Is the falsification criterion clear?",
        "Is the idea independently motivated (not selected by a failed result)?",
        "Has screening been used only as reject-only evidence?",
        "Are we comfortable spending one of the three remaining credits?",
    )

    def eligible_for_human_review(self) -> bool:
        """A dossier reaches a human only if the screen did not reject it."""
        return self.screen_verdict == SURVIVE

    def flags(self) -> tuple[str, ...]:
        """Things the human must not miss. Surfaced, not resolved."""
        out = []
        if self.dossier.hypothesis.requires_independent_rejustification():
            out.append(
                "DESCENDANT OF A FAILED EXPERIMENT: this idea's provenance ties "
                "it to a closed result. Part 7 requires it be justified "
                "independently before a credit is spent."
            )
        if self.dossier.unrebutted():
            out.append("UNREBUTTED ADVERSARY OBJECTION: "
                       + " | ".join(self.dossier.adversary_objections()))
        for d in self.dossier.dissent():
            out.append(f"DISSENT -- {d}")
        return tuple(out)

    def render(self) -> dict:
        return {
            "screen_verdict": self.screen_verdict,
            "eligible_for_human_review": self.eligible_for_human_review(),
            "questions_for_the_human": list(self.QUESTIONS),
            "flags": list(self.flags()),
            "dossier": self.dossier.as_dict(),
            "note": (
                "This packet does not register an experiment and cannot. "
                "Registration is a separate signed act performed by a human "
                "outside the discovery layer."
            ),
        }


def assert_not_auto_registerable() -> None:
    """Part 10 / final rule. Prove this layer has no path to registration.

    Structural: the import closure of every apex.research module must not reach
    the pipeline's gated entry point or the research ledger. A discovery layer
    that could import `run_period` or the `ResearchLedger` could turn an idea
    into an experiment without a human, which is the one thing it must never do.

    Uses the audited `module_closure` walk, the same tool that certifies
    experiment isolation, rather than a string scan that would trip over its
    own list of forbidden names.
    """
    from pathlib import Path

    from apex.audit.execution_path import module_closure

    package = Path(__file__).resolve().parents[2]
    forbidden = {"apex.pipeline", "apex.registration", "apex.governance.ledger"}
    offenders = []
    for module in (package / "apex" / "research").glob("*.py"):
        name = "apex.research." + module.stem if module.stem != "__init__" else "apex.research"
        reached = module_closure(package, name) & forbidden
        if reached:
            offenders.append(f"{name} reaches {sorted(reached)}")
    if offenders:
        raise GateError(
            "the discovery layer exposes a path to experiment registration: "
            + "; ".join(offenders)
        )
