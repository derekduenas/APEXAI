"""Model-search accounting: the file-drawer denominator for ML. NO FITTING.

WHY THIS EXISTS BEFORE ANY MODEL
--------------------------------
The single failure mode that makes ML dangerous is: try 100 models, keep the
winner, report the winner. That is a 100-comparison search reported as one
result. This module makes the denominator IMPOSSIBLE to hide: every materially
different model specification a researcher considers is recorded here BEFORE any
winner can be named, and the module exposes the count. It fits nothing, imports
no ML library, and returns no "best" -- it is the accountant, not the modeller.

FIRST .fit() IS STILL PROHIBITED
--------------------------------
This is the governance keystone from APEX-RESEARCH-ML-GOVERNANCE.md, not the ML
engine. No sklearn/xgboost/torch import appears here or anywhere in the research
path; `tests/test_architecture_claims.py` still enforces that. The `ml` firewall
contract forbids this package from reaching screening, discovery, or the
registration core -- verified by `tests/test_architecture_firewalls.py`.

A ModelSpec is a DECLARATION. Recording it costs nothing and commits to nothing.
Registering the SEARCH as an experiment (a human act, a credit) is what
authorises a winner to be named -- and even then, the denominator travels with
it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


class SearchError(RuntimeError):
    """A model-search rule was violated."""


@dataclass(frozen=True)
class ModelSpec:
    """A materially distinct model specification. A declaration, not a fit.

    Two specs are the SAME comparison iff they hash equal. Changing the family,
    the feature set, the target, the CV scheme, or any hyperparameter grid entry
    makes a DIFFERENT comparison -- each is a separate draw and must be counted.
    """

    model_family: str
    feature_ids: tuple[str, ...]
    target: str
    cv_scheme: str
    hyperparameter_grid: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_family.strip():
            raise SearchError("a model spec needs a model_family")
        if not self.feature_ids:
            raise SearchError("a model spec must name its features")

    @property
    def spec_hash(self) -> str:
        payload = json.dumps(
            {
                "model_family": self.model_family,
                "feature_ids": sorted(self.feature_ids),
                "target": self.target,
                "cv_scheme": self.cv_scheme,
                "hyperparameter_grid": self.hyperparameter_grid,
            },
            sort_keys=True, separators=(",", ":"), default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class ModelSearchLedger:
    """Append-only record of every model spec considered. The visible denominator.

    Not persisted to the research ledger (that counts EXPERIMENTS). This is the
    in-experiment accounting of how many specifications a single registered ML
    search tried -- the number a reader must see before any winner.
    """

    specs: list = field(default_factory=list)   # list[ModelSpec]

    def consider(self, spec: ModelSpec) -> str:
        """Record a spec. Idempotent per identical spec; distinct specs count.

        Returns the spec hash. This is the ONLY way a model enters the search,
        and it is impossible to consider a model without incrementing the
        denominator.
        """
        if all(s.spec_hash != spec.spec_hash for s in self.specs):
            self.specs.append(spec)
        return spec.spec_hash

    @property
    def n_comparisons(self) -> int:
        """How many DISTINCT specifications were attempted. The denominator."""
        return len({s.spec_hash for s in self.specs})

    def denominator(self) -> dict:
        """The file-drawer report. Every spec, never a ranking."""
        return {
            "n_comparisons": self.n_comparisons,
            "specs": sorted(s.spec_hash for s in self.specs),
        }

    def select_best(self, *args, **kwargs):
        """Deliberately unimplemented. Naming a winner requires a REGISTERED,
        credit-consuming search experiment whose denominator (n_comparisons) is
        recorded with the result. There is no ungoverned path to a winner."""
        raise SearchError(
            "select_best is not available. Naming a best model is a registered "
            "research act: register the search as an experiment (a credit), and "
            "report n_comparisons alongside the winner. See "
            "APEX-RESEARCH-ML-GOVERNANCE.md."
        )
