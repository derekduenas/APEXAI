"""The canonical component registry: every architectural component, as data.

WHY THIS OWNS COMPLETENESS
--------------------------
The operator should not have to remember missing components one conversation at
a time. This registry is the single machine-readable list of every component
from raw data to live P&L, each with its lifecycle state and governance facts.
`tests/test_component_registry.py` reconciles the `state` claims against what is
actually on disk and against the firewall contracts, so the registry cannot
quietly drift from reality: a component claimed BUILT must have a module, a
PLANNED one must not, and every firewall layer must appear here.

It is a DECLARATION, not an engine. It imports nothing but the firewall table it
cross-checks against, and it changes no behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Lifecycle states, in maturity order.
ABSENT = "ABSENT"
PLANNED = "PLANNED"
UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
BUILT = "BUILT"
CERTIFIED = "CERTIFIED"                 # BUILT + audited guards
ACTIVE = "ACTIVE"                       # running in production
RETIRED = "RETIRED"
STATES = (ABSENT, PLANNED, UNDER_CONSTRUCTION, BUILT, CERTIFIED, ACTIVE, RETIRED)


@dataclass(frozen=True)
class Component:
    """One architectural component with all 18 governance facts."""

    name: str
    state: str
    purpose: str
    module: str                         # the apex.* module, or "" if not built
    inputs: tuple
    outputs: tuple
    allowed_deps: tuple
    forbidden_deps: tuple
    pit_required: bool
    holdout_access: bool                # only the ONE validation look is True-adjacent
    is_new_hypothesis: bool
    consumes_credit: bool
    optimize_allowed: bool
    provenance: tuple                   # required stamps
    tests_required: tuple
    activation_prereqs: tuple
    downstream: tuple
    failure_behavior: str

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"{self.name}: bad state {self.state!r}")


_PROV_MIN = ("dataset_fingerprint", "protocol_hash", "config_hash", "repo_sha")


def _c(**kw) -> Component:
    kw.setdefault("inputs", ())
    kw.setdefault("outputs", ())
    kw.setdefault("allowed_deps", ())
    kw.setdefault("forbidden_deps", ())
    kw.setdefault("pit_required", False)
    kw.setdefault("holdout_access", False)
    kw.setdefault("is_new_hypothesis", False)
    kw.setdefault("consumes_credit", False)
    kw.setdefault("optimize_allowed", False)
    kw.setdefault("provenance", _PROV_MIN)
    kw.setdefault("tests_required", ())
    kw.setdefault("activation_prereqs", ())
    kw.setdefault("downstream", ())
    kw.setdefault("failure_behavior", "raise; never degrade silently")
    return Component(**kw)


# The whole system. Grouped by layer in comments; one flat registry.
REGISTRY: dict[str, Component] = {c.name: c for c in [

    # ---- LAYER 0: data / research substrate --------------------------------
    _c(name="pit_data", state=CERTIFIED, module="apex.data.snapshot_loader",
       purpose="point-in-time frozen vendor data with known_from",
       pit_required=True, downstream=("universe", "feature_factory"),
       tests_required=("lookahead audit", "fingerprint")),
    _c(name="universe", state=CERTIFIED, module="apex.universe",
       purpose="section-3 eligibility, survivorship-safe", pit_required=True,
       downstream=("feature_factory", "digital_twin")),
    _c(name="feature_registry", state=CERTIFIED, module="apex.features.registry",
       purpose="canonical FeatureSpecs, lifecycle, 23 features"),
    _c(name="feature_factory", state=CERTIFIED, module="apex.features.factory",
       purpose="PIT-safe feature builders", pit_required=True),
    _c(name="feature_redundancy", state=CERTIFIED, module="apex.features.redundancy",
       purpose="structural + empirical redundancy detection"),
    _c(name="feature_pit_validation", state=CERTIFIED,
       module="apex.features.pit_validation", purpose="per-feature PIT checks",
       pit_required=True),
    _c(name="digital_twin", state=CERTIFIED, module="apex.research.twin",
       purpose="deterministic PIT state at T; v1 = eligibility+features",
       pit_required=True, failure_behavior="refuse future feeds, never drop"),
    _c(name="digital_twin_multifacet", state=PLANNED, module="",
       purpose="market/regime/portfolio/model state facets on the twin",
       pit_required=True, activation_prereqs=("regime_engine", "portfolio")),
    _c(name="event_data", state=ABSENT, module="",
       purpose="earnings ANNOUNCEMENT dates for PEAD",
       failure_behavior="DATA GAP: vendor gives filing dates only"),
    _c(name="alternative_data", state=ABSENT, module="",
       purpose="sentiment / attention / positioning",
       failure_behavior="DATA GAP: not in vendor"),

    # ---- LAYER 1: discovery ------------------------------------------------
    _c(name="hypothesis_dossier", state=CERTIFIED, module="apex.research.hypothesis",
       purpose="frozen hypothesis wrapping the certified screening Dossier",
       is_new_hypothesis=True, downstream=("novelty", "screen")),
    _c(name="research_swarm", state=CERTIFIED, module="apex.research.swarm",
       purpose="8 epistemic roles; disagreement preserved; no score",
       forbidden_deps=("apex.pipeline", "apex.registration", "apex.governance.ledger"),
       is_new_hypothesis=True),
    _c(name="novelty_engine", state=CERTIFIED, module="apex.research.novelty",
       purpose="NOVEL/RECOMBINATION/REDUNDANT/MODIFICATION/DUPLICATE, no score"),
    _c(name="combination_engine", state=UNDER_CONSTRUCTION, module="apex.research.novelty",
       purpose="bounded CombinationProposal (object built); marginal-IC testing PLANNED",
       is_new_hypothesis=True, consumes_credit=True),
    _c(name="contamination_control", state=CERTIFIED, module="apex.research.hypothesis",
       purpose="provenance epochs; descendant-of-failure flagging"),
    _c(name="human_gate", state=CERTIFIED, module="apex.research.gate",
       purpose="presents; decides nothing; cannot register"),
    _c(name="research_manifest", state=CERTIFIED, module="apex.research.manifest",
       purpose="content-addressed science identity; science!=provenance!=presentation"),
    _c(name="research_memory", state=PLANNED, module="",
       purpose="durable cumulative record of every hypothesis/rejection/lineage/"
               "abandonment reason, unifying ledger + screen_log + dossiers",
       activation_prereqs=(), downstream=("novelty_engine",),
       failure_behavior="GAP: today memory is split across ledger + screen_log + git"),

    # ---- governance substrate ----------------------------------------------
    _c(name="screening", state=CERTIFIED, module="apex.governance.screening",
       purpose="reject-only, S1-S13, tamper-evident log",
       forbidden_deps=("apex.pipeline", "apex.registration", "apex.governance.ledger")),
    _c(name="registration", state=CERTIFIED, module="apex.registration",
       purpose="signing, protocol pin, unlock tokens", consumes_credit=True),
    _c(name="research_ledger", state=CERTIFIED, module="apex.governance.ledger",
       purpose="hash-chained credit ledger with annulment", consumes_credit=True),
    _c(name="success_criteria", state=CERTIFIED, module="apex.evaluate.criteria",
       purpose="per-experiment registered criteria; never hardcoded"),
    _c(name="firewalls", state=CERTIFIED, module="apex.governance.firewalls",
       purpose="layer-boundary contracts armed before their engines"),
    _c(name="auditors", state=CERTIFIED, module="apex.audit.execution_path",
       purpose="lookahead, cross-sectional, import-closure isolation"),

    # ---- LAYER 2: validation + in-experiment research ----------------------
    _c(name="ic_engine", state=CERTIFIED, module="apex.evaluate.ic",
       purpose="Spearman IC, Newey-West HAC t"),
    _c(name="null_simulation", state=CERTIFIED, module="apex.evaluate.reference",
       purpose="simulated HAC dispersion null"),
    _c(name="decile_engine", state=CERTIFIED, module="apex.evaluate.deciles",
       purpose="equal-count deciles, orientation-aware"),
    _c(name="stats_robustness", state=CERTIFIED, module="apex.stats.robustness",
       purpose="block bootstrap, permutation null, subperiod, multiple-comparison"),
    _c(name="research_attribution", state=CERTIFIED, module="apex.report.attribution",
       purpose="section-9 sector attribution of a decile spread"),
    _c(name="ml_search_accounting", state=CERTIFIED, module="apex.ml.search_ledger",
       purpose="file-drawer denominator; select_best refuses; NO fitting"),
    _c(name="ml_estimator", state=UNDER_CONSTRUCTION, module="",
       purpose="supervised/nonlinear models, nested purged walk-forward CV",
       is_new_hypothesis=True, consumes_credit=True, optimize_allowed=True,
       forbidden_deps=("apex.governance.screening", "apex.research.swarm"),
       activation_prereqs=("ml governance declaration",),
       failure_behavior="first .fit() prohibited until governance satisfied"),
    _c(name="model_registry", state=PLANNED, module="",
       purpose="versioned model artifacts, family accounting, drift",
       activation_prereqs=("ml_estimator",)),
    _c(name="causal_claim", state=CERTIFIED, module="apex.causal.claim",
       purpose="claim object; refuses 'confirmed' w/o rung+assumptions+placebo",
       is_new_hypothesis=True, consumes_credit=True),
    _c(name="causal_executors", state=UNDER_CONSTRUCTION, module="",
       purpose="placebo / neutralised-re-test runners",
       activation_prereqs=("a validated or in-sample signal",)),
    _c(name="regime_engine", state=CERTIFIED, module="apex.regime.engine",
       purpose="deterministic PIT regime assignment from declared def",
       pit_required=True, is_new_hypothesis=True, consumes_credit=True),
    _c(name="regime_state_builders", state=UNDER_CONSTRUCTION, module="",
       purpose="PIT builders for trailing-vol/breadth/trend state series",
       pit_required=True, activation_prereqs=("digital_twin_multifacet",)),

    # ---- LAYER 3: monetisation (gated on validated alpha) ------------------
    _c(name="portfolio_construction", state=BUILT,
       module="apex.portfolio.construction",
       purpose="L/S beta/sector-neutral attribution ladder rungs 0-5; "
               "evidence_class enforced by test; borrow proxy = ASSUMPTION",
       forbidden_deps=("apex.pipeline", "apex.registration", "apex.governance.ledger"),
       activation_prereqs=("a VALIDATED_ALPHA to exercise on real spread",),
       failure_behavior="policy versioned, never fitted to validation"),
    _c(name="economic_viability", state=CERTIFIED, module="apex.portfolio.viability",
       purpose="declared net/turnover/degradation/breadth thresholds, before use"),
    _c(name="risk_engine", state=BUILT, module="apex.portfolio.risk",
       purpose="declared limits (position/sector/heat/corr/drawdown-budget/"
               "defined-risk-only) with first-class reasoned REJECT; reads "
               "no forecast, ranks nothing",
       failure_behavior="limits are constraints, never hidden alpha selectors"),
    _c(name="backtest_engine", state=PLANNED, module="",
       purpose="evaluator of signal+policy+costs; never an optimiser",
       activation_prereqs=("portfolio_construction",)),
    _c(name="capacity_engine", state=BUILT, module="apex.portfolio.capacity",
       purpose="participation/sqrt-impact/spread -> capacity USD and NET-of-"
               "implementation economics; costs flow INTO the ranking, never "
               "reported beside it",
       failure_behavior="an edge consumed by implementation is refused, not "
                        "footnoted"),
    _c(name="cost_model", state=BUILT, module="apex.evaluate.turnover",
       purpose="drift-aware turnover + per-side cost (decile-spread scope)",
       failure_behavior="borrow cost documented as omission"),

    # ---- LAYER 4: deployment ------------------------------------------------
    _c(name="paper_shadow", state=ACTIVE, module="",
       purpose="LIVE paper track (scripts/paper_track.py): 6 frozen portfolios "
               "on the nightly lake, chained marks, holdout guard; "
               "SHADOW and LIVE stages remain PLANNED",
       activation_prereqs=("capacity_engine (for SHADOW/LIVE stages only)",),
       failure_behavior="no automatic promotion; human-authorised transitions"),
    _c(name="execution", state=PLANNED, module="",
       purpose="consume approved weights, emit fills; generates no research",
       forbidden_deps=("apex.pipeline", "apex.registration", "apex.governance.ledger",
                       "apex.evaluate", "apex.features"),
       activation_prereqs=("paper_shadow", "risk_engine")),
    _c(name="live_monitoring", state=PLANNED, module="",
       purpose="drift/decay detection; REVIEW/PAUSE/KILL, never retune",
       activation_prereqs=("execution",),
       failure_behavior="alert is a request for human judgement, never an action"),
    _c(name="lifecycle_attribution", state=PLANNED, module="",
       purpose="feature/factor/model/regime/portfolio/cost/execution attribution",
       activation_prereqs=("backtest_engine",)),

    # ---- LAYER 5: forward evidence + intelligence (v2.0-v4.0) ---------------
    _c(name="reality_harness", state=ACTIVE, module="apex.reality.harness",
       purpose="chained+anchored prediction ledger, 4 resolution rules frozen "
               "at creation, Brier/log-loss/calibration, Murphy decomposition, "
               "unresolved-past-due scores as failure, PRELIMINARY stamps",
       failure_behavior="silence is scored as failure, never as neutrality"),
    _c(name="reality_producers", state=ACTIVE, module="apex.reality.producers",
       purpose="mechanical producers + biting baselines + the blind twin "
               "(signature cannot carry market data)"),
    _c(name="llm_producers", state=BUILT, module="apex.reality.llm_producer",
       purpose="full/stripped pairs, parallel models (haiku+opus) never "
               "substitution, pair-atomic, rule-17 no-backdating guard",
       activation_prereqs=("headless CLI login (operator, outstanding)",),
       failure_behavior="an unpaired variant is discarded, never recorded"),
    _c(name="expression_engine", state=BUILT, module="apex.expression.engine",
       purpose="distribution + chain -> ranked defined-risk structures; "
               "spread paid, theta integrated; only CALIBRATED may recommend",
       activation_prereqs=("calibrated distributions from the reality loop",),
       failure_behavior="as_recommendation() refuses non-CALIBRATED sources"),
    _c(name="world_vintage", state=BUILT, module="apex.world.vintage",
       purpose="as-released macro vintages; asof() returns the knowable, "
               "REVISED_ONLY refused from confirmatory paths",
       pit_required=True,
       activation_prereqs=("FRED/ALFRED key for the live macro feed (operator)",)),
    _c(name="world_state", state=ACTIVE, module="apex.world.state",
       purpose="online-only state variables + classifier (median detection "
               "lag 4d), labels never revised, staleness infectious; NO "
               "notion of a profitable state exists (enforced by test)"),
    _c(name="exploration_governance", state=BUILT, module="apex.exploration.cv",
       purpose="purged CV + embargo (fails closed), walk-forward, trial "
               "ledger with visible denominator, DSR at the TRUE trial "
               "count, PBO/CSCV, candidate contract requiring correlation-"
               "to-validated and regime-label provenance; in-sample only "
               "structurally; no select_best exists",
       forbidden_deps=("apex.registration", "apex.governance.ledger"),
       failure_behavior="a candidate missing any receipt is refused, not "
                        "emitted with a warning"),

    # ---- the decision chain (built 2026-08-15, end-to-end proven) ----------
    _c(name="distribution_estimator", state=BUILT,
       module="apex.distribution.estimator",
       purpose="signal + conditioning -> provenance-preserving pmf; four "
               "statuses never conflated; CALIBRATED minted ONLY against a "
               "reality-loop report (>=10 effective dates, reliability "
               "<=0.01); v1 = historical empirical conditional",
       activation_prereqs=("reality-loop calibration data for the "
                           "CALIBRATED stamp",),
       failure_behavior="an uncalibrated pmf structurally cannot be treated "
                        "as calibrated downstream"),
    _c(name="opportunity_engine", state=BUILT, module="apex.opportunity.engine",
       purpose="the machine's final sentence: distribution + expression + "
               "risk + capacity -> governed TRADE/NO-TRADE + economic "
               "ranking; 8 rejection paths each proven by adversarial test; "
               "options demoted to stock without calibration; live_intent "
               "refused without CALIBRATED",
       failure_behavior="NO-TRADE is first-class and refusals are retained "
                        "in the report"),
    _c(name="calibration_harness", state=PLANNED, module="",
       purpose="walk-forward chain-calibration ledger: replayable "
               "snapshot(T) -> decision -> outcome(T+h); computes PIT/"
               "coverage/reliability per component ONCE per frozen "
               "methodology (docs/SYSTEM-CALIBRATION-AUDIT.md section 4); "
               "one design with the discovery runner",
       activation_prereqs=("discovery_exercise_runner",),
       failure_behavior="calibration is never recomputed after model "
                        "inspection; a recalibrated model is a new version"),
    # ---- APEX HUNTER (P0 contracts, 2026-08-15; P1+ gated on intraday data)
    _c(name="hunter_contracts", state=BUILT, module="apex.hunter.contracts",
       purpose="TradeThesis (immutable+hashed), PlaybookDefinition (no "
               "mechanism = no candidate), fail-closed gate (unknown never "
               "becomes safe)",
       forbidden_deps=("apex.registration", "apex.governance.ledger"),
       failure_behavior="a thesis without invalidation is refused"),
    _c(name="hunter_lifecycle", state=BUILT, module="apex.hunter.lifecycle",
       purpose="model lifecycle IDEA->...->LIVE with MECHANICAL calibration "
               "gating; DEGRADED loses live eligibility structurally; no "
               "override API exists",
       failure_behavior="promotion without calibration evidence raises"),
    _c(name="hunter_statemachine", state=BUILT, module="apex.hunter.statemachine",
       purpose="ruled+chained trade transitions; a stop NEVER widens "
               "(counterexampled)",
       failure_behavior="an unruled transition is refused as a mood"),
    _c(name="broker_adapter", state=BUILT, module="apex.hunter.broker",
       purpose="abstract broker seam; live methods SEALED (subclass cannot "
               "re-enable; dated governance change only)",
       failure_behavior="live execution raises LiveExecutionDisabled"),
    _c(name="intraday_foundation", state=BUILT, module="apex.intraday.contract",
       purpose="P1A kernel: provider-neutral contract, PIT identity bridge "
               "(ambiguity fails closed), three-meaning corporate actions, "
               "DST-safe sessions, ReplayClock (no lookahead through bar "
               "construction), deterministic streamed replay, manifests. "
               "NOT CERTIFIED: gates B/J await the Massive subscription",
       pit_required=True,
       activation_prereqs=("MASSIVE_API_KEY (operator; licensing check)",
                           "certification sample", "cross-source reconciliation"),
       failure_behavior="unknown identity/stale/unresolved-CA fail closed; "
                        "an unwired adapter refuses, never fabricates"),
    _c(name="hunter_intelligence", state=PLANNED, module="",
       purpose="intraday replay, scanner funnel, ChartState, playbook "
               "evaluation -- ALL gated on an intraday data source "
               "(DATA_GAP: repo has zero intraday data; Robinhood MCP absent)",
       activation_prereqs=("intraday minute-bar archive OR broker MCP",
                           "hunter_contracts")),
    _c(name="discovery_exercise_runner", state=ABSENT, module="",
       purpose="THE remaining gap this tranche exposed: the machine can "
               "DECIDE on a fully-specified candidate but cannot yet FEED "
               "itself candidates from real data -- the runner that walks "
               "real in-sample signals + live state through the chain and "
               "emits the historical opportunity report",
       activation_prereqs=("distribution_estimator", "opportunity_engine",
                           "real options chain data OR stock-only declared")),
]}


def by_state(state: str) -> tuple:
    return tuple(c for c in REGISTRY.values() if c.state == state)


def maturity_summary() -> dict:
    out = {s: 0 for s in STATES}
    for c in REGISTRY.values():
        out[c.state] += 1
    return {s: n for s, n in out.items() if n}
