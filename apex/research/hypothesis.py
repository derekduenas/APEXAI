"""The canonical research hypothesis, and its provenance discipline.

ONE AUTHORITATIVE DEFINITION (Part 4)
-------------------------------------
A hypothesis is NOT a second dossier format. The screenable content of every
hypothesis is an `apex.governance.screening.Dossier` -- the same object the
certified screen already validates and hashes. `HypothesisDossier` WRAPS it and
adds only what the discovery layer needs and the screen must never see:
provenance, novelty claim, contamination lineage, and the parent it descends
from. `screenable()` returns the underlying `Dossier`, so there is exactly one
place that defines what a valid, hashable hypothesis is.

The discovery metadata is deliberately kept OUT of the screenable content: the
screen must not be able to read "this descends from APEX-002" and let that
influence a verdict, and the content hash must not change when a provenance
note is edited. Two hashes, two jobs.

CONTAMINATION IS A TYPE, NOT A REMINDER (Part 7)
------------------------------------------------
APEX-002's post-mortem found IC concentrated on high-breadth dates. Using that
to motivate a new hypothesis is a failed experiment selecting its successor --
the exact contamination the whole governance stack exists to prevent. Here it
is made structural: every hypothesis declares the EPOCH its rationale comes
from, a rationale sourced from a post-mortem observation is marked
`DESCENDANT_OF_FAILURE`, and the human gate can refuse to spend a credit on one
that has not been independently re-justified.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field

from apex.governance.screening import (
    GOVERNANCE_FIELDS,
    SCIENTIFIC_FIELDS,
    Dossier,
)

# Provenance epoch -- WHEN the information that motivates this hypothesis became
# available. This is the load-bearing distinction for Part 7.
BEFORE_002 = "BEFORE_APEX_002"          # derivable from data/theory alone
DURING_002 = "DURING_APEX_002"          # noticed while #002 ran
POSTMORTEM_002 = "POSTMORTEM_APEX_002"  # from #002's failure analysis
EPOCHS = (BEFORE_002, DURING_002, POSTMORTEM_002)

# Novelty classification of a hypothesis against what already exists.
NOVEL = "NOVEL"
RECOMBINATION = "RECOMBINATION"
REDUNDANT = "REDUNDANT"
MODIFICATION = "MODIFICATION"
DUPLICATE = "DUPLICATE"
NOVELTY_CLASSES = (NOVEL, RECOMBINATION, REDUNDANT, MODIFICATION, DUPLICATE)


class HypothesisError(ValueError):
    """A hypothesis violated a discovery-layer rule."""


@dataclass(frozen=True)
class Provenance:
    """Where a hypothesis came from. Kept OUT of the screenable content."""

    epoch: str
    author: str
    created: str
    parent_dossier_hash: str = ""     # the hypothesis this was iterated from
    motivating_source: str = ""       # e.g. a paper, a data property, a post-mortem
    descends_from_experiment: str = ""  # e.g. "APEX-002" if a descendant

    def __post_init__(self) -> None:
        if self.epoch not in EPOCHS:
            raise HypothesisError(
                f"provenance epoch must be one of {EPOCHS}; got {self.epoch!r}"
            )

    @property
    def is_descendant_of_failure(self) -> bool:
        """Part 7. A rationale drawn from a post-mortem, or explicitly declared
        to descend from a closed experiment, is a descendant of that result and
        must be independently re-justified before it may spend a credit."""
        return self.epoch == POSTMORTEM_002 or bool(self.descends_from_experiment)


@dataclass(frozen=True)
class HypothesisDossier:
    """A research hypothesis: a screenable Dossier plus discovery metadata.

    The two are kept apart on purpose. `content` is what the screen sees and
    hashes; `provenance` and the discovery fields are what the human gate and
    the contamination controls see and must NOT reach the screen.
    """

    content: dict                      # -> screening.Dossier (the science)
    provenance: Provenance
    economic_mechanism: str
    feature_set: tuple[str, ...]       # feature_ids from the registry
    novelty_claim: str                 # the researcher's own claim, prose
    known_risks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Validate the screenable content THROUGH the certified Dossier, so the
        # definition of "complete" lives in exactly one place.
        self.screenable()
        if not self.economic_mechanism.strip():
            raise HypothesisError("a hypothesis needs an economic_mechanism")
        if not self.feature_set:
            raise HypothesisError(
                "a hypothesis must name the feature_ids it uses; an empty set "
                "cannot be checked for novelty or PIT-safety"
            )
        if not self.novelty_claim.strip():
            raise HypothesisError("a hypothesis must state its novelty_claim")

    def screenable(self) -> Dossier:
        """THE authoritative screenable object. One definition, reused."""
        return Dossier(content=self.content)

    @property
    def dossier_hash(self) -> str:
        """S2 identity: the hash of the SCREENABLE content only.

        Provenance is excluded so that re-annotating where an idea came from
        does not change the identity of the idea. Iterating the SCIENCE does.
        """
        return self.screenable().hash

    @property
    def provenance_hash(self) -> str:
        """A separate hash over the discovery metadata, for the audit trail."""
        payload = json.dumps(
            {
                "provenance": asdict(self.provenance),
                "economic_mechanism": self.economic_mechanism,
                "feature_set": sorted(self.feature_set),
                "novelty_claim": self.novelty_claim,
                "known_risks": sorted(self.known_risks),
            },
            sort_keys=True, separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def requires_independent_rejustification(self) -> bool:
        """Part 7 / Part 10. True when the human gate must confirm the idea was
        motivated independently of a failed experiment before a credit is spent."""
        return self.provenance.is_descendant_of_failure


def new_provenance(
    *, epoch: str, author: str, parent_dossier_hash: str = "",
    motivating_source: str = "", descends_from_experiment: str = "",
) -> Provenance:
    """Provenance stamped with the current UTC time. Deterministic given inputs
    except for `created`, which is why `created` is excluded from dossier_hash."""
    return Provenance(
        epoch=epoch,
        author=author,
        created=dt.datetime.now(dt.timezone.utc).isoformat(),
        parent_dossier_hash=parent_dossier_hash,
        motivating_source=motivating_source,
        descends_from_experiment=descends_from_experiment,
    )
