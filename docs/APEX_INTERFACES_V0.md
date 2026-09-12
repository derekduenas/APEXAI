# APEX interface specifications — `SPECIFIED_NOT_IMPLEMENTED`

Four contracts introduced by `APEX_CANONICAL_ARCHITECTURE_V2.md` Addendum A.
**None is implemented.** No module produces or consumes any of them today,
no test asserts them, and none may be produced until its activation gate in
`IMPLEMENTATION_ROADMAP_V2.md` opens. They are written now so that the first
implementation is a contract to satisfy rather than a shape invented under
deadline.

Conventions borrowed from the contracts that already exist, deliberately:
absent means **NOT ESTIMATED**, never zero (`WORLD_MODEL_FORECAST_V0`); every
record carries the identity of what it consumed; every record can be a named
refusal instead of a value; nothing carries trading, order, capital or
promotion authority.

---

## 1. `LATENT_STATE_ESTIMATE_V0`

An inference about unobserved market state. Produced by the World Model,
**never** written back to the Twin.

| Field | Type | Meaning / rule |
|---|---|---|
| `contract` | str | `LATENT_STATE_ESTIMATE_V0` |
| `observation_snapshot_id` | str | identity of the Twin snapshot consumed |
| `observation_snapshot_hash` | str | content hash of that snapshot — the estimate is bound to what it saw |
| `inference_model_id`, `inference_model_version` | str | the estimator and its frozen version |
| `as_of` | float | the instant the estimate describes |
| `availability_basis` | enum | `MEASURED_PUBLICATION` \| `ASSUMED_BAR_CLOSE` \| `ASSUMED_OTHER` \| `NOT_AVAILABLE` — assumed availability is never rendered as measured |
| `known_from` | float | when this estimate could first have been formed |
| `state_variables` | dict | name → `{estimate, units, support}`; names are registered, not free text |
| `representation` | enum | `POINT_WITH_UNCERTAINTY` \| `WEIGHTED_SAMPLES` \| `PARAMETRIC` |
| `samples` | list\|None | `[{state, weight}]` when `WEIGHTED_SAMPLES`; weights sum to 1 and their **effective sample size** is reported |
| `uncertainty` | dict | per variable: `{sd \| interval \| quantiles}`, plus `epistemic` / `aleatoric` where the estimator can separate them, `None` where it cannot |
| `missing_inputs` | list | inputs the estimator wanted and did not get, named |
| `out_of_distribution` | dict | `{flag, measure, threshold, basis}` — how far the observation sits from the fitting set |
| `assumptions` | list | stated, not implied |
| `limitations` | list | what this estimate cannot support |
| `authority` | dict | `ORDER_AUTHORITY: NONE`, `TRADING_AUTHORITY: NONE`, `TWIN_WRITE: FORBIDDEN` |

Refusal instead of a value: `INSUFFICIENT_OBSERVATIONS`,
`OUT_OF_DISTRIBUTION_REFUSED`, `MODEL_NOT_VALIDATED_FOR_THIS_STATE`,
`AVAILABILITY_UNKNOWN`.

Prohibited: a `state_variables` entry without an `uncertainty` entry; a
posterior probability produced by anything other than a fitted, registered
estimator; any field that would let a consumer treat an estimate as an
observation.

---

## 2. `MULTIVERSE_PATH_SET_V0`

Conditional simulation over starting states, parameters, models and
disturbances. Consumes World Model weights; never re-weights them.

| Field | Type | Meaning / rule |
|---|---|---|
| `contract` | str | `MULTIVERSE_PATH_SET_V0` |
| `starting_state_source` | str | the `LATENT_STATE_ESTIMATE_V0` id consumed — a single certain starting state is only legal if that estimate itself is degenerate, and it is then labelled `DEGENERATE_START` |
| `uncertainty_propagated` | list | any of `STARTING_STATE`, `PARAMETERS`, `MODEL_CHOICE`, `DISTURBANCES`, `PARTICIPANT_REACTION`, `REGIME` — those **not** listed are held fixed and that is recorded |
| `distribution_owner` | const | `WORLD_MODEL` — owns the latent-state, parameter and model-choice distributions **and the versioned transition model** that defines the forecast |
| `transition_model` | dict | `{id, version, source}` — the dynamics the Multiverse was asked to execute, authored and versioned by the World Model |
| `sampling_scheme` | dict\|None | `{method, proposal, target, correction, effective_sample_size_after_weighting, validation}` — importance sampling and friends are permitted and must carry their correction; a weight without recorded provenance and correction is an unauthorised edit to the target, not a sampling weight |
| `n_paths`, `seed` | int | reproducibility |
| `simulation_error` | dict | Monte Carlo error of the reported quantities at this `n_paths` |
| `model_uncertainty` | dict | dispersion attributable to model/parameter choice — **never reduced by raising `n_paths`** |
| `weighted_forecast` | dict | the probability-weighted distribution |
| `model_disagreement` | dict | dispersion **across** models, reported beside the forecast, never folded in |
| `unweighted_stress` | list | branches with **no** probability mass |
| `proposed_branches` | list | LLM- or human-proposed causal branches, each `UNWEIGHTED` until quantitatively evaluated, with proposer and rationale |
| `ensemble` | dict | `{members, shared_information, pairwise_overlap, effective_independent_members}` — an ensemble whose effective count is not reported may not be weighted |
| `limitations` | list | stated |

Prohibited: probability mass on an `unweighted_stress` or `proposed_branches`
entry (computational weights included — a stress branch is not a rare event
being sampled efficiently, it is a scenario with no assigned probability);
any change to the target distribution the World Model did not author;
sampling weights without a declared proposal, target and correction;
reporting proposal-distribution quantities as the forecast; an ensemble
weighted by member count without the correlation adjustment; reporting
`simulation_error` as if it were forecast uncertainty.

---

## 3. `PREDICTABILITY_MAP_ENTRY_V0`

One measured cell of predictive capability. Lives with evaluation and
Experience; PRIME may consume it only when its activation gate opens.

| Field | Type | Meaning / rule |
|---|---|---|
| `contract` | str | `PREDICTABILITY_MAP_ENTRY_V0` |
| `cell` | dict | `{target, horizon, market_state_or_regime, information_tier, model_id, model_version, evidence_maturity}` |
| `grouping_rule_id` | str | the **registered** rule that defined this cell, registered before scoring |
| `comparator` | dict | the declared alternative the skill is measured against — there is no "skill" without one |
| `score` | dict | out-of-sample metric, its value, and the scoring rule |
| `improvement` | dict | `{estimate, uncertainty, method}` — an interval, never a bare point |
| `calibration` | dict | PIT / coverage / reliability evidence at this cell |
| `support` | dict | `{n_raw, n_effective, dependence_treatment}` — overlapping targets are adjusted for, and the adjustment is named |
| `search_accounting` | dict | `{cells_registered, cells_scored, multiplicity_treatment}` |
| `status` | enum | `MEASURED` \| `INSUFFICIENT_EVIDENCE` \| `NOT_REGISTERED` |
| `limitations` | list | stated |
| `authority` | dict | `SELECTION_AUTHORITY: NONE` until a separately validated rule exists |

Prohibited: a cell created after seeing results; interpolation into an
unmeasured cell; a point improvement without uncertainty; consumption by
PRIME before the activation gate; treating a capability estimate as a
prediction about the next forecast.

---

## 4. `INFORMATION_ACQUISITION_REQUEST_V0`

A proposal to obtain an observation, judged by decision value. Lives in
PULSE; approved by a human in the first implementation.

| Field | Type | Meaning / rule |
|---|---|---|
| `contract` | str | `INFORMATION_ACQUISITION_REQUEST_V0` |
| `unresolved_question` | str | what is not known, stated as a question |
| `candidate_source` | dict | `{name, permissions_required, terms, admission_route_if_acquired}` |
| `expected_availability` | dict | `{latency, publication_semantics, revision_semantics, coverage}` |
| `cost` | dict | `{monetary, request_budget, operational_burden}` |
| `decision_affected` | dict | `{decision_id, current_choice, choices_that_could_change}` |
| `expected_decision_value` | dict | `{basis, estimate_or_NOT_ESTIMABLE, why}` — **distinct from information gain**, which is recorded separately and is not sufficient justification |
| `information_gain` | dict\|None | uncertainty reduction, when estimable |
| `priority_rule` | str | the deterministic, auditable rule that ordered this request |
| `result` | enum | `PENDING` \| `APPROVED` \| `REFUSED` \| `ACQUIRED` \| `FAILED` — failures are recorded, not dropped |
| `changed_forecast` | bool\|None | after the fact |
| `changed_decision` | bool\|None | after the fact — the honest scorecard for the whole mechanism |
| `missingness_note` | str | what this request's outcome implies about sample selection |

Prohibited now and until separately authorized: autonomous purchasing,
unrestricted browsing, a learned acquisition policy, and any acquired
dataset reaching research without its own admission decision.

---

## 5. Status

| Interface | Status | Gate |
|---|---|---|
| `LATENT_STATE_ESTIMATE_V0` | SPECIFIED_NOT_IMPLEMENTED | a registered hypothesis naming the latent variable it improves |
| `MULTIVERSE_PATH_SET_V0` | SPECIFIED_NOT_IMPLEMENTED | a real-data World Model forecast exists to start from |
| `PREDICTABILITY_MAP_ENTRY_V0` | SPECIFIED_NOT_IMPLEMENTED | ≥ 1 completed registered experiment with sealed scores |
| `INFORMATION_ACQUISITION_REQUEST_V0` | SPECIFIED_NOT_IMPLEMENTED | the first acquisition question a human wants ordered |

None of these is on the critical path to EXP-001B.
