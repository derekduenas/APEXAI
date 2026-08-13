"""Architectural firewalls: the layer-boundary contract, as data.

WHAT THIS IS
------------
Not a new governance framework. A DECLARATION of the import-closure boundary
each planned layer must obey, enforced by the same `module_closure` walk that
already certifies experiment isolation. The existing governance (ledger,
screening, registration, criteria) is untouched and unreferenced here.

WHY IT EXISTS NOW, BEFORE THE LAYERS
------------------------------------
The master architecture audit found the validation -> downstream boundary
"unguarded, safe only because the downstream layers are absent." This module
ARMS that boundary before the layers exist. Each planned layer has a declared
package name; the moment someone creates `apex/ml/` or `apex/portfolio/`, the
firewall test enforces its closure against the contract below. A boundary that
only appears with the code it guards is a boundary that arrives too late.

THE ONE RULE THE WHOLE FILE ENCODES
-----------------------------------
Information flows DOWN the layer stack freely and UP only as a new,
provenance-stamped hypothesis. A lower layer (a broker's symbols, a backtest's
favourite parameter, a live model's drift) may never import upward into
research or reach the holdout. `forbidden` is the up-direction and the holdout;
`is_new_hypothesis` marks a layer whose output is a research claim that must
re-enter through registration, never a free refinement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The gated experiment path and the credit/holdout machinery. NOTHING may reach
# these except the layers explicitly permitted to (only the pipeline itself).
REGISTRATION_CORE = frozenset({
    "apex.pipeline",
    "apex.registration",
    "apex.governance.ledger",
})

# The research-discovery layer. Downstream layers must not import UP into it --
# that is how a backtest result or a live model would silently select research.
DISCOVERY_LAYER = frozenset({
    "apex.research.swarm",
    "apex.research.novelty",
    "apex.research.hypothesis",
    "apex.research.gate",
})

# The screen. A screening outcome is never evidence (S13); the evaluation and
# any downstream layer must not reach it.
SCREEN = frozenset({"apex.governance.screening"})


@dataclass(frozen=True)
class LayerContract:
    """The boundary one architectural layer must obey.

    `package` is the import prefix the layer's code will live under (e.g.
    "apex.ml"). `forbidden` is every module it may NEVER reach via its import
    closure. The flags below are governance facts a reader and a test both
    consume; they are declarations, not behaviour.
    """

    name: str
    package: str
    purpose: str
    status: str                       # BUILT / PLANNED / ABSENT
    forbidden: frozenset
    is_new_hypothesis: bool           # output is a research claim -> registration
    consumes_credit: bool             # activation debits a research credit
    may_access_holdout: bool          # always False except the one validation look
    may_optimize: bool                # may it search a parameter space at all


# The whole architecture, as one table. Each row is a boundary that a test can
# enforce whether or not the code behind it exists yet.
CONTRACTS: dict[str, LayerContract] = {
    # -- LAYER 1: research substrate (BUILT) --------------------------------
    "discovery": LayerContract(
        name="research discovery / swarm",
        package="apex.research",
        purpose="turn a mechanism into a frozen, novelty-classified hypothesis",
        status="BUILT",
        forbidden=REGISTRATION_CORE,   # discovery cannot register or spend
        is_new_hypothesis=True,
        consumes_credit=False,         # producing a dossier is free
        may_access_holdout=False,
        may_optimize=False,
    ),
    # -- LAYER 2: alpha discovery (statistics BUILT; rest PLANNED) ----------
    "statistics": LayerContract(
        name="statistical validation toolkit",
        package="apex.evaluate",
        purpose="IC / null / decile / robustness -- evidence, never a search",
        status="BUILT",
        forbidden=SCREEN | DISCOVERY_LAYER,  # evidence cannot read screen/discovery
        is_new_hypothesis=False,
        consumes_credit=False,         # runs inside a registered experiment
        may_access_holdout=False,      # the ONE look is gated by registration, not here
        may_optimize=False,
    ),
    "causal": LayerContract(
        name="causal research layer",
        package="apex.causal",
        purpose="placebo / neutralised / sensitivity tests; assumptions explicit",
        status="UNDER_CONSTRUCTION",
        forbidden=SCREEN | DISCOVERY_LAYER,
        is_new_hypothesis=True,        # a post-validation causal claim is a new question
        consumes_credit=True,
        may_access_holdout=False,
        may_optimize=False,
    ),
    "ml": LayerContract(
        name="machine-learning research layer",
        package="apex.ml",
        purpose="nonlinear hypotheses; a model IS a hypothesis, credit-governed",
        status="UNDER_CONSTRUCTION",
        forbidden=SCREEN | DISCOVERY_LAYER,
        is_new_hypothesis=True,
        consumes_credit=True,
        may_access_holdout=False,
        may_optimize=True,             # inside in-sample nested CV ONLY; declared
    ),
    "regime": LayerContract(
        name="regime engine",
        package="apex.regime",
        purpose="pre-specified PIT regime state; conditioning is a new hypothesis",
        status="UNDER_CONSTRUCTION",
        forbidden=SCREEN | DISCOVERY_LAYER,
        is_new_hypothesis=True,
        consumes_credit=True,          # 'trade only in the best regime' costs a credit
        may_access_holdout=False,
        may_optimize=False,
    ),
    # -- LAYER 3: monetisation (PLANNED, gated on validated alpha) ----------
    "portfolio": LayerContract(
        name="portfolio construction",
        package="apex.portfolio",
        purpose="turn a signal into an investable policy; signal != policy",
        status="PLANNED",
        forbidden=REGISTRATION_CORE | SCREEN | DISCOVERY_LAYER,
        is_new_hypothesis=False,       # a policy is not a new predictive claim
        consumes_credit=False,         # monetisation research, not a credit test
        may_access_holdout=False,
        may_optimize=False,            # policy params are versioned, not fitted to validation
    ),
    "backtest": LayerContract(
        name="realistic backtest engine",
        package="apex.backtest",
        purpose="evaluate a signal+policy+costs jointly; an evaluator, not an optimiser",
        status="PLANNED",
        forbidden=REGISTRATION_CORE | SCREEN | DISCOVERY_LAYER,
        is_new_hypothesis=False,
        consumes_credit=False,
        may_access_holdout=False,
        may_optimize=False,
    ),
    "risk": LayerContract(
        name="risk engine",
        package="apex.risk",
        purpose="exposure / drawdown / tail limits; independent of alpha discovery",
        status="PLANNED",
        forbidden=REGISTRATION_CORE | SCREEN | DISCOVERY_LAYER,
        is_new_hypothesis=False,
        consumes_credit=False,
        may_access_holdout=False,
        may_optimize=False,
    ),
    # -- LAYER 4: deployment (PLANNED, gated on a monetisable backtest) -----
    "execution": LayerContract(
        name="execution / paper / shadow / live",
        package="apex.execution",
        purpose="consume approved weights, emit fills; generates no research",
        status="PLANNED",
        forbidden=(REGISTRATION_CORE | SCREEN | DISCOVERY_LAYER
                   | frozenset({"apex.evaluate", "apex.features"})),
        is_new_hypothesis=False,
        consumes_credit=False,
        may_access_holdout=False,
        may_optimize=False,
    ),
    "monitoring": LayerContract(
        name="live monitoring / attribution / drift",
        package="apex.monitoring",
        purpose="detect drift/decay; may trigger REVIEW/PAUSE/KILL, never retune",
        status="PLANNED",
        forbidden=REGISTRATION_CORE | SCREEN | DISCOVERY_LAYER,
        is_new_hypothesis=False,       # a decay alert becomes a NEW dossier, by hand
        consumes_credit=False,
        may_access_holdout=False,
        may_optimize=False,
    ),
}


def planned_packages() -> dict[str, str]:
    """Layer -> package name, for every contract. Used by the firewall test to
    enforce a boundary the moment its package appears."""
    return {k: c.package for k, c in CONTRACTS.items()}


def new_hypothesis_layers() -> frozenset:
    """Layers whose output is a research claim that must re-enter through
    registration -- ML, causal, regime, discovery. The structural version of
    'a validated factor must not automatically become an ML model'."""
    return frozenset(k for k, c in CONTRACTS.items() if c.is_new_hypothesis)
