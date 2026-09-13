# INTEGRATION-SPEC-001 — PREMARKET → SETUP LAB → CROSS-INSTRUMENT EXPRESSION WAR, with TRADINGVIEW EYES

**Revision 2 (2026-09-12).** Documentation only. Written against `exit-scheduling-003`; TradingView modules read
from `origin/tradingview-connector-001` at `39fbd21`.

**Nothing here has been built, wired, fitted, evaluated, deployed or authorized by writing it.** No provider call,
no credential change, no limit or risk-law change, no recorded evaluation.

## Revision 2 — what changed and why

Review of revision 1 (`c37e60b`) found two financial errors that would have steered the build wrong. Both are
corrected, and both corrections make the specification **more** conservative, not less:

1. **"Stock gap risk is unbounded below" was wrong.** A fully paid long share position can lose at most its
   purchase cost plus costs — the price floors at zero. Unbounded loss belongs to a *short* position. My text also
   contradicted the code it was describing: `risk_certificate._certify_stock` already records
   `structural_worst_case = round(notional, 2)` for LONG, a finite bound. §7 is rewritten.
2. **Hold-to-expiry is not an automatic safety unlock for verticals, and revision 1 treated it as one.** Withdrawn
   entirely — §6.3. Holding to expiry introduces exercise, assignment, settlement and residual stock exposure, and
   American-style short legs can be assigned before expiration with no automatic exercise of the long leg to cover.
   The debit bound describes a paired payoff under assumptions; it does not certify a lifecycle.
3. **The intraday objective stands.** No holding period is lengthened to satisfy the certificate code. Policy
   binding prevents substitution; it does not make a new policy economically or operationally safe.
4. **Account semantics now precede sizing and instrument eligibility** in the build order (§9).
5. Added: comparable horizons and capital duration (§7.4); descriptive premarket attention ranking (§4.4);
   ineligible candidates as model-conditioned estimates (§6.6); setups bound to a **current intraday** Twin
   snapshot (§5.3); how setups reach forecasts and how World Model / Multiverse outputs reach expression
   evaluation (§5.5); a concrete TradingView implementation step (§8.7).

---

## 0. Purpose

APEX can take one instrument class — a single long option — from forecast to intent to paper fill to Book, with
unresolved accounting explicit. It cannot decide what to look at, name what it thinks is true, or compare ways of
expressing that view. The goal is **one reconstructible decision**: from the observation that made a symbol
interesting, through the setup, to the expression chosen over its rivals, to the outcome — every step's evidence,
provenance and refusals on the same ledger.

---

## 1. Verified inventory

**BUILT** = exists and is tested · **WIRED** = reachable from the live options decision path · **ABSENT**.

```
entrypoint → pulse_options.TwinSources → decision_wb.FunnelEngine
   (GARCH-t variance + MarkovSwitching2 regime + ConditionalSimulator + expression_war.compare + PRIME)
 → options_pilot.session.scan → risk_authority.approve → risk_certificate.certify + risk_kernel.check
 → Book → lifecycle.LifecycleRunner
```

| area | status | note |
|---|---|---|
| forecast → intent → paper fill → Book | BUILT + WIRED | unresolved accounting stays explicit |
| exits: arrival triggering, restart continuity, original-policy binding | BUILT + WIRED | synthetic; recorded feed now wired separately (see the recorded-wiring deliverable) |
| premarket | BUILT, **NOT WIRED** | four implementations, no shared contract (§4.1) |
| setup detection | BUILT, **NOT WIRED** | `hunter/playbooks_v1.py` H001/H002 only |
| regime | BUILT + WIRED | reweights simulator variance only; no regime→strategy routing |
| forecasting | BUILT + WIRED, **NOT VALIDATED** | `EXP002_L`, artifact stamped `INVALID_NULL_CONTROL`, `no_validated_edge_claim: true` |
| expression comparison | BUILT + WIRED, **NO AUTHORITY** | `SELECTION_AUTHORITY = "NONE"`; options-only (§6.1) |
| stocks / verticals as candidates | **ABSENT** | §6.2, §6.3 |
| intraday Twin `snapshot_id` | **ABSENT** | verified: `snapshot_id` exists only in `catalyst/twin_snapshot.py` and `vision/render.py`, not on the options-path snapshot. **A build item, not an existing hook.** |
| account semantics | **ABSENT** | verified: no `settled_cash`, `available_cash`, `committed_capital`, `options_level`, `buying_power` in `apex/options_pilot/` or `apex/organism/` |
| TradingView | ADAPTER BUILT, NOT WIRED, NOT SMOKE-TESTED | §8 |

`grep -rn "premarket\|playbook\|hunter" apex/options_pilot/ apex/decision_wb/ apex/pulse_options/` returns
**nothing**. The disconnect is total.

**What the recorded diagnostic showed.** Twelve scans, all `WAIT` / `NO_ELIGIBLE_CANDIDATE`; eighteen option
candidates per scan, zero affordable (cheapest ask principal $650 against a $500 per-trade cap). **The funnel's
selection value is unmeasured** — it never got to choose.

---

## 2. The gap

Eyes that see, a lab that hypothesises, and a hand that trades exactly one instrument — **none connected**. No
recorded decision can be traced from an observation to a setup to a considered choice among expressions.

---

## 3. Architecture

```
  PREMARKET CONTEXT ──► SETUP LAB ──► CROSS-INSTRUMENT EXPRESSION WAR ──► RISK ──► PRIME ──► intent
   (prior context:      (is it true    (which expression, priced and     (may we)  (should we)
    where to look)       RIGHT NOW,     certified on comparable terms)
                         on the current
                         intraday
                         snapshot)
```

Each stage boundary is **a persisted record, not a function call**, carrying its own ids, receipts and refusals. A
stage that cannot state its output honestly emits a named refusal; the pipeline degrades to WAIT, never to a guess.

**Availability discipline, everywhere** (already enforced in `replay.most_recent_available` and
`tradingview/normalize.py`): an input's availability is when it **reached this system**, never its own event time.
A datum with no recorded availability does not enter a decision and is not backdated.

---

## 4. Stage 1 — PREMARKET CONTEXT

### 4.1 Four implementations, no contract

`apex/pulse/premarket.py` (superseded by `PULSE_BOUNDED_STATE_V1`) · `apex/catalyst/premarket.py` (phases,
schedule, environment, LLM pre-bell brief with `FORBIDDEN_IN_BRIEF` guards) · `apex/frontier/premarket.py` (sealed
packets, `NONE_FRONTIER_SHADOW`) · `apex/hunter/watchlist.py` + `chartstate.py` (rvol with validity states).

**Recommendation: promote none of them wholesale.** Specify a thin record the options path consumes and let the
existing modules become producers. Wholesale promotion imports a lane's assumptions and, for two of them, a
different deployment host (`apex-equities` launchd vs `/opt/apex/current` systemd —
`docs/DEPLOYMENT_DIVERGENCE_001.md`).

### 4.2 The contract

```
PREMARKET_CONTEXT_V0
  packet_id                 stable id; referenced (never copied) by downstream records
  as_of_epoch / _utc, session_date, phase
  per symbol:
    prior_close, gap_pct          value + availability + quality state
    rvol_tod                      RVOL_VALID | RVOL_INVALID_SESSION | RVOL_UNKNOWN (never a number unless VALID)
    liquidity                     spread, size, ADV — each with availability
    key_levels[]                  {level, kind, derivation, source_receipt}
    event_context                 catalyst.twin_snapshot.event_snapshot (already wired, SHADOW)
    external_context[]            TradingView observations by reference + digest (§8)
  attention_rank[]          see §4.4
  refusals[]
  authority                 "PRIOR_CONTEXT_ONLY: admits no risk, authorizes no trade, expires into the session"
```

**Quality states are not optional.** `hunter/watchlist.py` already models rvol as value *plus* validity because a
half-session rvol is a different number, not a small error. A field is `VALID` with a number, or it is one of the
named non-numeric states — never a number with a caveat.

### 4.3 Premarket is prior context, not a decision input of record

The packet says where to point attention before the open. **It expires into the session**: by the time a setup is
evaluated, the question is what the *current intraday* snapshot says (§5.3). The packet is retained and referenced
so a decision can be traced back to what drew attention, and it is never mistaken for evidence about the moment of
decision.

### 4.4 Descriptive attention ranking is permitted

Premarket **may rank names** by measured attention criteria — gap magnitude, relative volume, liquidity, catalyst
relevance — and record the ranking with the measurements behind it. Three constraints:

- The ranking is **descriptive**: "these are the most active/liquid/eventful names", never "these are the best
  trades". It carries `authority: PRIOR_CONTEXT_ONLY`.
- Every criterion is a **measured, timestamped quantity with an availability instant**, and the weights are
  declared and versioned. No learned or tuned scoring enters at this stage.
- The ranking **selects nothing and sizes nothing**. It bounds where the Setup Lab looks; it never implies a
  setup exists, and it never reaches the tournament or PRIME.

---

## 5. Stage 2 — SETUP LAB

### 5.1 Honest starting position

**No profitable strategy has emerged from this work.** The only concrete named setups are `HUNTER-001` (long
continuation) and `HUNTER-002` (failed-extension reversion), deliberately opposed, consumed only by the hunter
forward pass. The hypothesis machinery (`edgeforge/hypotheses.py`, `edgeforge/registry.py` with `NULL_RESULT`
among its statuses, `research/hypothesis.py`) is real and unused by the live path. This stage is **a contract and a
scoreboard, not a claim of edge**.

### 5.2 Detected pattern versus evidence for promotion

Revision 1 said "a setup that cannot beat WAIT is not a setup". That conflated two different things, and the
distinction matters for how the lab is built:

| | |
|---|---|
| **A detected pattern** | a frozen, falsifiable definition that either matches or does not match on given data. Detection is a measurement. A pattern that matches rarely, or that has no measured advantage, **is still a valid detected pattern** and belongs in the registry with its record. |
| **Evidence supporting promotion** | an accumulated, prospective, after-cost comparison against WAIT and against a simple rule, on comparable opportunities, with its nulls. Absence of this evidence blocks promotion; it does not invalidate the detection. |

Recording patterns that do not clear the bar is how the null record gets built. Deleting them would leave only
survivors, which is the selection bias the whole apparatus exists to avoid.

### 5.3 The contract — bound to a CURRENT intraday snapshot

```
SETUP_OBSERVATION_V0
  setup_id, setup_version, setup_hash    frozen definition, hashed from its own fields (like an exit policy)
  symbol, as_of_epoch
  twin_snapshot_id                       *** THE CURRENT INTRADAY SNAPSHOT, mandatory ***
  model_identities{}                     forecast/variance/regime model + params ids actually in force
  input_receipts[]                       every input value WITH its availability instant
  premarket_packet_ref                   the morning packet, as REFERENCED PRIOR CONTEXT (optional, never required)
  matched: bool
  features{}                             computed from timestamped market data only
  levels{}                               entry reference, invalidation reference, target reference — PRICE LEVELS
  horizon_s                              the time over which the claim is made
  claim                                  falsifiable: direction + horizon + invalidation
  authority                              "RESEARCH_ONLY" until promoted through the existing ladder
  refusals[]
```

**A setup referencing only its premarket context is insufficient and is refused.** Premarket guides attention;
**intraday observations determine whether the setup still exists.** A gap that mattered at 09:00 may be closed by
10:15, and a record that cannot say what the market looked like at the moment of evaluation cannot support a
decision.

This requires a build item: **`snapshot_id` does not currently exist on the options-path Twin snapshot**
(`TwinSources.snapshot` returns a composed dict with no id). Adding a content-addressed id plus its input receipts
is a prerequisite for this stage, not an incidental detail.

Three rules that keep a setup from becoming a signal generator by accident:

1. **A setup states levels and a horizon. It never states a size, an instrument, or a probability.** Sizing is
   risk's; instrument choice is Stage 3's; calibrated probability must be earned.
2. **Frozen and hashed before evaluation**, so an edited setup cannot inherit an old record's evidence.
3. **Every setup carries its null.**

### 5.4 The scoreboard

Per setup: instances, match rate, forecast quality against its own stated horizon, after-cost outcome, unresolved
positions, and comparison against **WAIT** and a **simple rule** — on comparable opportunities (§7.4).

### 5.5 How setups reach forecasts, and how the World Model reaches expression evaluation

This is the wiring question revision 1 left unanswered. The current path:

```
TwinSources.snapshot(symbol, as_of)
  → forecast_fn → artifact.forecast(snap, direction_signal=…)      # EXP002_L; direction_signal is None on FULL_FUNNEL
  → FunnelEngine.fit()   GARCH-t variance + MarkovSwitching2 regime
  → FunnelEngine.decide() → ConditionalSimulator(S0, variance, nu, iv0, spread, regime=…) → PATHS
  → expression_war.compare(paths, candidates, …)                   # scores candidates on THOSE paths
  → PRIME supervision
```

Two specified rules:

- **A setup must not become a covert direction signal.** The FULL funnel deliberately excludes the heuristic
  `signal_fn` from the forecast and records it on the trace instead. A setup enters the same way by default:
  **recorded as context, not as a forecast input.** If a setup is ever to condition the forecast, that must be an
  explicit, versioned conditioning input, evaluated against the unconditioned forecast on the same data, and
  promoted on that comparison — never a quiet extra argument.
- **What a setup legitimately does control is the CANDIDATE SET and the HORIZON.** It says which direction is
  being expressed, over what horizon, and with what invalidation level — and that determines which expressions are
  even generated (which strikes, which structures, which durations). The World Model / Multiverse contribution
  reaches expression evaluation exactly as it does today: through the **shared simulated paths** every candidate is
  scored on. That is the correct seam, and it already exists — what is missing is candidates other than long
  options to score on it.

---

## 6. Stage 3 — CROSS-INSTRUMENT EXPRESSION WAR

### 6.1 What exists today

`expression_war.compare` scores candidates over shared Monte Carlo paths and records `expected_net_pnl`, `p_loss`,
quantiles, `certified_max_loss`, IV sensitivity and quote uncertainty, under
`SELECTION_AUTHORITY = "NONE: the pilot's deterministic rule selects; this comparison is recorded, not applied"`.

**Every candidate is a long option.** `_pnl_paths` unconditionally prices with `bsm_price_vec(…, inst["strike"],
right=inst["right"])` and returns `100.0 * (exit_bid − entry_ask) − fees`. No share expression, no spread
expression. The `WAIT` row is a hardcoded zero. It is an **option-strike comparison**, not a cross-instrument
tournament.

### 6.2 Shares: the code's classification is a policy, not a financial fact

```
CERTIFIED_RISK_AUTHORITY = {DEFINED_MAX_LOSS: True, STOP_DEFINED: False, UNBOUNDED: False, NOT_ESTIMABLE: False}
_certify_stock:  risk_class = UNBOUNDED if direction == "SHORT" else STOP_DEFINED
                 certified_max_loss   = None
                 structural_worst_case = round(notional, 2)      # LONG — a FINITE bound
```
and `risk_authority.py:156` hard-refuses anything that is not `DEFINED_MAX_LOSS`.

**Read this correctly.** A fully paid long share position has a **finite maximum loss: its purchase cost plus
costs**, because the price cannot go below zero. The code already knows this — it records the full notional as
`structural_worst_case`. What `STOP_DEFINED` and `certified_max_loss = None` express is a **certification policy
decision**: the pilot certifies against a *stop-based planned loss*, and a stop does not guarantee its number, so
no certified figure is issued. That is a statement about what the system is willing to certify, **not** a claim
that shares lack a bounded economic downside.

Two distinct routes should therefore be examined, and **neither becomes eligible automatically**:

| route | bound | what it needs |
|---|---|---|
| **A. Fully funded shares under a purchase-cost bound** | maximum loss = `price × shares + costs`, finite and knowable at entry, requiring no stop to hold | a certificate whose bound is the funded cost; capital treatment that reserves the **full purchase cost** (not a stop distance); and the account semantics of §7.3 to establish the cash is actually available and committed |
| **B. Stop-based sizing** | a *planned* loss, smaller than A, **not guaranteed** — gap, halt and slippage risk sit between intent and fill | `STOP_DEFINED_RISK_MODEL_V1` earned on real gap and slippage evidence, exactly as the refusal string says. Does not exist in code today |

Route A is the more tractable of the two and does not depend on new evidence about stops — but it is a different
kind of trade: it commits the entire purchase cost as risk capital, which at a $500 per-trade limit buys very
little of a $650 underlying. That arithmetic is a finding for the operator, not an argument for changing the limit.

### 6.3 Verticals: automatic eligibility via hold-to-expiry is WITHDRAWN

Revision 1 proposed pairing verticals with a hold-to-expiry exit rule to make them `DEFINED_MAX_LOSS`, on the
strength of the module's own comment. **That was wrong, and it is withdrawn.**

`VERTICAL_NOT_CERTIFIABLE` correctly identifies why a *pre-expiry* exit breaks the debit bound: closing early
requires buying back the short leg, realising `(long bid − short ask)`, which can be negative by two spreads not
knowable in advance. But **holding to expiry does not simply remove that problem — it substitutes a different
set of risks that the certificate does not currently model at all**:

- **Early assignment.** American-style short legs can be assigned before expiration, at the holder's discretion.
- **No automatic offsetting exercise.** The long leg is not necessarily exercised automatically to cover an
  assignment on the short leg; that is a separate action with its own timing and conditions.
- **Resulting stock positions.** An assignment can leave a stock position — with its own overnight exposure,
  capital requirement and, for a resulting short, a different risk class entirely.
- **Settlement and execution mechanics.** Exercise style, settlement type, cut-off times, pin risk near the
  strike, and broker-specific auto-exercise thresholds all sit between the payoff diagram and the realised result.

**The familiar debit-spread loss bound describes the paired payoff under its assumptions. It does not certify the
execution and settlement lifecycle.** (See OIC's exercise-and-assignment guidance and its bull-call-spread
explanation, and Schwab's assignment guidance.)

**Requirements before any vertical certificate is proposed** — all of them, explicitly modelled and tested:

1. assignment probability treatment, including early assignment, and what the system does when it occurs;
2. the exercise/assignment decision path: who acts, when, and what happens if nothing acts;
3. residual position handling — what a resulting stock position is, how it is classified, sized and exited;
4. settlement mechanics and cut-offs, including pin risk at the strike;
5. execution risk on the closing legs where an early close is still possible;
6. the capital and permission requirements of each state (§7.3), including a resulting stock position;
7. a bound that holds across **all** of the above, not only at the payoff diagram.

**And the intraday objective is preserved.** We do not lengthen a holding period to pass a certificate. If a
multi-day structure is ever wanted it must be justified on its own economics and operations, as its own decision.
Exit-policy binding (EXIT-SCHEDULING-003) means a policy cannot be silently substituted — that is a safety
property about *substitution*, and it says nothing about whether a longer-horizon policy is itself sound.

### 6.4 The contract

```
EXPRESSION_CANDIDATE_V0
  setup_ref, twin_snapshot_id           the setup and the CURRENT snapshot it was evaluated on
  expression                            LONG_CALL | LONG_PUT | CALL_VERTICAL | PUT_VERTICAL | STOCK
  direction, quantity
  exit_policy_id / hash                 THE EXIT CONTRACT IS PART OF THE CANDIDATE
  holding_horizon_s, capital_duration   see §7.4 — never omitted
  pricing{}                             quoted sides used, receipts, spread, quote_uncertainty
  economics{}                           MODEL-CONDITIONED: expected_net_pnl, p_loss, quantiles, IV sensitivity,
                                        mc_se_mean — over SHARED paths, with the model identities that produced them
  money{}                               the three quantities of §7, never collapsed
  certificate{}                         risk_certificate.certify output, verbatim
  eligibility                           PRIME_ELIGIBLE | RESEARCH_OBSERVATION_ONLY | REFUSED  + why
  affordability                         FEASIBLE | INFEASIBLE + which quantity bound it
```

### 6.5 Comparison rules

1. **Shared paths or no comparison.** All candidates for one setup are scored on the same paths, same seed, same
   parameter hash, or the comparison is refused.
2. **Comparable horizons, or the comparison is refused** (§7.4).
3. **Affordability is a gate, not a rank** (§7.2).
4. **The tournament proposes; it does not select.** `SELECTION_AUTHORITY` stays `NONE` until a review grants it.
   Recording it alongside the deterministic rule is precisely how its selection value gets measured before it is
   trusted.

### 6.6 Ineligible candidates: shown, with model-conditioned economics

Ineligible candidates **appear in the record** with their reason, so it is visible when the permitted trade is not
the one the model preferred. Revision 1 overstated what that shows, and the language is now fixed:

> A candidate's `economics{}` are **model-conditioned estimates** produced by a simulator whose forecast input is
> currently stamped `INVALID_NULL_CONTROL`. A more attractive estimate is **not** evidence that an ineligible
> candidate is a better trade. It is evidence about what this model, on these paths, under these assumptions,
> estimated — nothing more.

Every ineligible candidate row therefore carries `economics_basis: MODEL_CONDITIONED_ESTIMATE`, the model
identities behind it, and an explicit statement that no superiority is established. This preserves the visibility
without manufacturing a claim.

---

## 7. Money, kept separate

### 7.1 The three quantities

| quantity | definition | binds |
|---|---|---|
| **cash committed** | what leaves the account to open: `ask × 100 × n + entry fees` (long option); `price × shares + costs` (stock); net debit + costs (debit vertical) | affordability against available capital — **the quantity that produced WAIT on all twelve recorded scans** ($650 vs $500) |
| **planned stop loss** | the *intended* loss at the declared invalidation level (`canonical_planned_risk`); `planned_risk_basis = UNVERIFIED_UPSTREAM_LABEL` with no stop. **Intended, never guaranteed** | the kernel's `LIMIT_DENOMINATION = PLANNED_RISK_DECLARED_1R` |
| **maximum possible loss** | what the structure makes economically possible: the debit for a long option; **the purchase cost plus costs for a fully paid long share**; unbounded only for a *short* share position; for a vertical, not established until §6.3's requirements are met | `certified_max_loss` and the `DEFINED_MAX_LOSS` gate |

Consequences:

- **A stop is not a certificate.** Planned loss and maximum possible loss are different kinds of claim.
- **A finite maximum loss is not automatic eligibility.** Route A in §6.2 has a finite bound *and* still needs a
  certificate, capital treatment and account semantics before anything is eligible.
- **An affordable trade is not necessarily a good trade** (§7.2).

### 7.2 Affordability is a gate

Affordability filters the candidate set; it must **never** contribute to ranking. FLOW-VALIDATION-001's twelve
WAITs were the correct answer to "can we afford any of these" and tell us nothing about whether any was worth
taking.

**The $25–$100 paper-risk range discussed earlier was illustrative and is NOT an approved setting.** Authorized
limits are unchanged: $500 per trade, $1,500 aggregate, $600 same-underlying, $1,000 same-family, $1,000 session
drawdown halt, `STARTING_PAPER_CAPITAL = 10,000`. Nothing here proposes changing them.

### 7.3 Account semantics — a prerequisite, not a follow-on

Verified absent from `apex/options_pilot/` and `apex/organism/`: `settled_cash`, `available_cash`,
`committed_capital`, `options_level`, `buying_power`, account restrictions. The only cash concept is the derived
`STARTING_PAPER_CAPITAL + Σ cashflows` plus an `available_capital` argument callers must supply.

**This must be specified and built before instrument eligibility or multi-instrument sizing**, because different
instruments consume different resources:

```
ACCOUNT_STATE_V0
  settled_cash, unsettled_proceeds, settlement_schedule
  available_to_open            per instrument class, not one number
  committed_capital[]          per open position, with what it is committed against
  options_level                and what each level permits (long options / spreads / naked)
  margin_state                 cash vs margin account, and what that changes
  restrictions[]               PDT, good-faith, position limits, halted instruments
  as_of + receipts
```

Ranking a share against an option without this produces a comparison that is arithmetically fine and
**operationally false** — the share may require cash the account does not have settled, and the vertical may
require a permission level it does not hold.

### 7.4 Comparable horizons and capital duration

A fifteen-minute option trade and a multi-week expiry trade are **not interchangeable uses of capital** and cannot
be ranked as though they were. Every candidate carries:

- **`holding_horizon_s`** — the intended holding period under its own exit policy;
- **`capital_duration`** — how long the committed cash is unavailable for anything else, including settlement;
- **overnight/weekend exposure count**, since gap risk is not present in an intraday holding period.

Rules:

1. **Candidates are only compared within a comparable-horizon band**, set by the setup's own `horizon_s`. A
   candidate whose holding horizon materially exceeds the setup's claim is not a competing expression of that
   setup; it is a different trade and is recorded as `REFUSED: HORIZON_INCOMPARABLE`.
2. Where horizons differ inside the band, the comparison must state **return per unit of capital-time**, not raw
   expected P&L, and say so.
3. A longer-horizon candidate carries risks a fifteen-minute one does not — overnight gaps, events inside the
   window, assignment for short legs. Those must be in the economics or the candidate is refused, not discounted.

**This rule is also what prevents "hold to expiry" from re-entering through the back door** as a way to make a
structure certifiable: a multi-week vertical is not a comparable expression of a fifteen-minute setup.

---

## 8. TRADINGVIEW EYES

### 8.1 Verified status, re-checked this session

| capability | status | how verified |
|---|---|---|
| server reachable, account authorized | **CONNECTED** | `claude mcp list` → `mcp-tradingview … ✔ Connected` |
| tools visible to **this** session | **NOT AVAILABLE** | `ToolSearch` for TradingView tools returns nothing; session startup lists `mcp-tradingview` as needing authentication |
| retained live smoke evidence | **NONE** | no artefact in `docs/evidence/`; the connector record states zero calls were ever made |
| adapter | **BUILT, synthetic tests only** | `origin/tradingview-connector-001` @ `39fbd21` |
| adapter on the current branch | **NO** | `apex/tradingview/` absent from `exit-scheduling-003` |
| unattended APEX access | **NOT_CONNECTED** | `adapter.runtime_status()["unattended_apex_runtime"]` |
| chart rendering / screenshots | **NOT AVAILABLE** | connector documents no chart-image tool |
| options chains / executable option quotes | **NOT AVAILABLE** | not offered by this connector |

**The bounded smoke test cannot be performed from this session** — not for want of authorization, but because no
`mcp__mcp-tradingview__*` tool is exposed to it. A Claude Code session builds its tool registry at start and does
not pick up a server authorized later. The precise blocker: **this session's registry contains zero tools from that
provider**; the previously authorized bounded smoke (≤10 calls, allowlisted read-only tools) remains unspent and
will be performed in a session that can see them, started from `/Users/derekduenas` where the server is registered.

### 8.2 Tool catalog → Twin inputs

Allowlisted in `apex/tradingview/allowlist.py` (a literal tuple; anything unlisted is denied by default):

| tool | Twin input | class |
|---|---|---|
| `search_symbols` | symbol resolution to `EXCHANGE:TICKER` | reference |
| `get_ohlcv` | bars for **display and cross-check**, never the price of record | `EXTERNAL_CONTEXT` |
| `get_technicals_rating` | indicator context | `EXTERNAL_CONTEXT_ONLY`, `calibrated = False` |
| `get_news`, `get_news_story` | narrative context, joins the existing event lane | `EXTERNAL_CONTEXT_ONLY` |
| `get_earnings_calendar`, `get_economic_calendar`, `get_dividends_calendar` | scheduled-event context | `EXTERNAL_CONTEXT_ONLY` |
| `get_screener_columns` | field discovery before any screener use | reference |

`get_active_watchlist` stays excluded: the documentation carries a read-only label **and** describes
activation/creation side effects. The described behaviour governs.

**The catalog above is from documentation, not from an authenticated enumeration.** It is reconciled against the
live catalog the first time a session exposes the tools; a tool that appears and is not in the allowlist is denied
until reviewed in by a person.

### 8.3 The handoff

```
TradingView observation
  → request_start / response_receipt                 (adapter records both)
  → known_from = response_receipt                    (normalize.py; NEVER the candle's own time)
    historical_availability = NOT_ESTABLISHED; valid_for_as_of(t) refuses t < known_from
  → TRADINGVIEW_OBSERVATION_V0 {tool, args, payload_digest, entitlement_state, authority}
  → PREMARKET packet   → attached to packet_id            (PRIOR CONTEXT)
    INTRADAY observation → attached to the CURRENT twin_snapshot_id   (decision-time context)
  → carried by reference (id + payload_digest) into SETUP_OBSERVATION_V0.input_receipts
  → carried by reference into EXPRESSION_CANDIDATE_V0 and the decision record
```

**Premarket observations remain prior context; new intraday observations attach to the current snapshot.** The
binding is **by reference and digest, never by copy** — a decision record names which observation informed it and
proves the bytes, rather than embedding a second copy that can drift.

### 8.4 Showing which inputs actually informed a decision

Every decision record carries `external_inputs_used[]`: for each observation, its id, tool, digest, `known_from`,
which snapshot it attached to, and **which field of the decision it fed**. An observation that was fetched but did
not feed anything is recorded as `RETRIEVED_UNUSED`. A reader can then answer "what did the eyes contribute to
this trade" without inference.

### 8.5 Failure, staleness, and what must never block

- Adapter failures are already **named states**, not exceptions: `TOOL_DENIED`, `BUDGET_EXHAUSTED`,
  `RATE_LIMITED`, `TIMEOUT`, `AUTHENTICATION_FAILED`, `PROVIDER_UNAVAILABLE`, `MALFORMED_RESPONSE`.
- A missing or stale observation makes its field `UNKNOWN`/`STALE`. It never becomes a number with a caveat.
- **A TradingView outage must not block a scan that has sufficient primary data.** The scan proceeds, the external
  field is refused by name, and the decision record shows the absence. Only a scan that *depended* on an external
  input for something load-bearing may be refused — and that dependency must be declared in advance, not
  discovered at failure time.
- **A TradingView outage must never block exit servicing.** Already contracted: `adapter.never_blocks()` states
  `EXIT_SERVICING_INDEPENDENT` and a test asserts the module imports nothing from the execution or exit path. The
  new stages preserve it: premarket, setup lab and the tournament all sit strictly before intent creation, and no
  exit, retry or deadline may await any of them.
- `entitlement_state` is `UNKNOWN` unless verified — real-time vs delayed is open on every observation.

### 8.6 Four capabilities, kept distinct

| capability | status |
|---|---|
| chart rendering (human-viewable chart) | **UNAVAILABLE** from this connector |
| optional AI visual interpretation | **UNAVAILABLE**; and it could only ever explain, never establish expectancy |
| quantitative setup detection | **NEEDS BUILDING** (§5) — from timestamped market data, never from an image |
| execution quotes | **NOT FROM HERE** — primary feeds remain responsible for timely bars and executable quotes |

### 8.7 The concrete implementation step

**TV-1 — Reuse the existing adapter, wire it as premarket external context.** A single bounded step, not a
roadmap entry:

1. **Merge `apex/tradingview/` forward** from `origin/tradingview-connector-001` (`39fbd21`) unchanged — adapter,
   allowlist, normalize, and its tests. No new provider code is written.
2. **Run the previously authorized bounded smoke** (≤10 calls, allowlisted read-only tools) from a session that
   can see the tools, started from `/Users/derekduenas`. Retain the response digests, `known_from` instants and
   entitlement states as evidence under `docs/evidence/`. If the tools are still not visible, **report the precise
   blocker and stop** — no partial result is presented as a smoke test.
3. **Reconcile the live tool catalog** against `ALLOWED_TOOLS`/`DENIED_TOOLS`; record any difference. Anything new
   is denied until reviewed in.
4. **Implement `PREMARKET_CONTEXT_V0.external_context[]`** as references + digests to `TRADINGVIEW_OBSERVATION_V0`
   records, with `authority = EXTERNAL_CONTEXT_ONLY`.
5. **Implement `external_inputs_used[]`** on the decision record (§8.4), including `RETRIEVED_UNUSED`.
6. **Prove the two independence properties** with tests: a scan with sufficient primary data completes with every
   TradingView state from §8.5 injected; and exit servicing completes with the connector unavailable throughout.

**Unattended APEX access stays `NOT_CONNECTED`** until a supported authentication route exists with a stated
credential owner and refresh lifecycle. TradingView documents OAuth 2.1 with no token lifetime, and
`runtime_status()` records `refresh_lifecycle: UNDOCUMENTED`. **Claude's OAuth credentials are not borrowed,
exported or read, and an interactive connection is never reported as a service connection.** Step TV-1 delivers
observations captured through an interactive session; a continuous unattended feed is a separate, unauthorized
brick.

---

## 9. Build order

Account semantics now precede sizing and instrument eligibility.

| # | step | authorization beyond ordinary build |
|---|---|---|
| 1 | Recorded-observation wiring into the shared V2 runner | synthetic acceptance only; a recorded rerun is a separate grant **(delivered)** |
| 2 | `twin_snapshot_id` + input receipts on the intraday snapshot | none — prerequisite for §5 and §8 |
| 3 | `PREMARKET_CONTEXT_V0` + one producer + descriptive attention ranking | none — admits no risk, authorizes no trade |
| 4 | **TV-1** (§8.7) | the existing bounded smoke grant; nothing further |
| 5 | `SETUP_OBSERVATION_V0` + the two existing playbooks as producers, `RESEARCH_ONLY` | none — no selection authority |
| 6 | **`ACCOUNT_STATE_V0`** (§7.3) | none to model; required before any of 7–9 |
| 7 | Horizon and capital-duration treatment in the comparison (§7.4) | none |
| 8 | Shares into the tournament as `RESEARCH_OBSERVATION_ONLY`, with route A and route B analysed separately (§6.2) | none for observation; eligibility needs a reviewed certificate |
| 9 | Verticals: **the §6.3 requirements first**, then a certificate proposal | risk review; not proposed until 1–7 of §6.3 are modelled |
| 10 | Chronological evaluation over comparable opportunities | evaluation grant; contract frozen before execution |

Steps 2, 3 and 6 are the unglamorous prerequisites that everything downstream depends on. Nothing in 8 or 9 should
start before 6.

---

## 10. Open decisions for the operator

1. **Which premarket producer** feeds `PREMARKET_CONTEXT_V0` first, and whether the cross-host divergence is
   resolved before or after wiring.
2. **Whether route A (fully funded shares, purchase-cost bound) is worth pursuing** given that committing the full
   purchase cost against a $500 per-trade limit buys very little of a $650 underlying. This may be an argument that
   the instrument set, not the limit, is the constraint — but that is your call.
3. **Whether verticals are worth the §6.3 work at all** on an intraday horizon, given that early assignment and
   settlement modelling is substantial and the intraday objective forbids simply holding to expiry.
4. **Whether the tournament may ever hold selection authority**, and what evidence would earn it.

---

## 11. What this specification does not do

- It does not change any limit, risk law, fee, selection policy or exit policy.
- It does not propose making shares or verticals PRIME-eligible, and it withdraws revision 1's hold-to-expiry
  proposal entirely.
- It does not lengthen any holding period to satisfy the certificate code.
- It does not claim any strategy, setup or model has an edge. `EXP002_L` remains `INVALID_NULL_CONTROL`;
  `BRICK4_WALKFORWARD_CONTRACT.md` still reports **0 fittable sessions**.
- It does not authorize a provider call, deployment, credential change or account change.
- It does not specify an exhausted-position rescue route.
