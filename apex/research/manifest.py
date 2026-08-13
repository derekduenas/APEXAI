"""ResearchManifest: an immutable, content-addressed record of one research run.

THREE THINGS KEPT APART (the whole point)
-----------------------------------------
Every research artifact mixes three kinds of information, and conflating them is
how a later notebook edit silently changes a result:

  SCIENCE      what determines the answer: hypothesis, dataset, features,
               protocol, config, model, policy, cost model, seed, sample.
  PROVENANCE   who/when/where: author, timestamp, repo SHA, environment.
  PRESENTATION how it is shown: titles, prose, figure captions.

The manifest hashes SCIENCE alone into `science_id`. Changing a scientific input
changes the identity; editing a caption or re-running on a new machine does NOT.
A result is the same result iff its `science_id` matches, regardless of when or
by whom it was rendered.

This reuses the hashing discipline already in the ledger and the screening
dossier; it does not introduce a new identity scheme, only applies the existing
one to a whole run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


class ManifestError(ValueError):
    """A manifest was malformed or mutated after completion."""


# The scientific inputs whose change MUST change the result's identity. A run
# missing any of these is not reconstructible and is refused.
SCIENCE_KEYS = (
    "experiment_id",
    "hypothesis_dossier_hash",
    "dataset_fingerprint",
    "feature_signature",
    "protocol_hash",
    "config_hash",
    "sample_definition",
    "method",
    "seed",
)

# Optional scientific inputs -- present only for later layers. Included in the
# science hash when set, so a model or policy change also changes identity.
OPTIONAL_SCIENCE_KEYS = (
    "twin_digest",
    "model_version",
    "portfolio_policy_version",
    "cost_model_version",
    "regime_definition_version",
)


@dataclass(frozen=True)
class ResearchManifest:
    """Immutable record of one run. `science_id` is its scientific identity."""

    science: dict           # the scientific inputs (SCIENCE_KEYS [+ optional])
    provenance: dict        # author, timestamp, repo_sha, environment
    presentation: dict = field(default_factory=dict)   # titles, captions
    output_hashes: dict = field(default_factory=dict)  # artifact -> sha256

    def __post_init__(self) -> None:
        missing = [k for k in SCIENCE_KEYS if k not in self.science]
        if missing:
            raise ManifestError(
                f"manifest is not reconstructible -- missing scientific inputs "
                f"{missing}. Every science key is required."
            )
        extra = [k for k in self.science
                 if k not in SCIENCE_KEYS + OPTIONAL_SCIENCE_KEYS]
        if extra:
            raise ManifestError(
                f"unknown scientific input(s) {extra}: science must not carry "
                f"free-form fields, or its identity becomes unstable"
            )

    def _canonical_science(self) -> str:
        return json.dumps(self.science, sort_keys=True, separators=(",", ":"),
                          default=str)

    @property
    def science_id(self) -> str:
        """The scientific identity. Changes iff a scientific input changes."""
        return hashlib.sha256(self._canonical_science().encode()).hexdigest()

    @property
    def full_id(self) -> str:
        """Identity over science + provenance + presentation + outputs.

        Two runs with the same science but different provenance share a
        `science_id` and differ in `full_id` -- exactly the distinction that
        lets a re-render be recognised as the same science.
        """
        payload = json.dumps(
            {"science": self.science, "provenance": self.provenance,
             "presentation": self.presentation, "output_hashes": self.output_hashes},
            sort_keys=True, separators=(",", ":"), default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def same_science_as(self, other: "ResearchManifest") -> bool:
        return self.science_id == other.science_id

    def as_dict(self) -> dict:
        return {
            "science_id": self.science_id,
            "full_id": self.full_id,
            "science": self.science,
            "provenance": self.provenance,
            "presentation": self.presentation,
            "output_hashes": self.output_hashes,
        }
