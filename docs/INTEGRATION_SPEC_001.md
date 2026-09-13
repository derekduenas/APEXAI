# INTEGRATION-SPEC-001 — PREMARKET → SETUP LAB → CROSS-INSTRUMENT EXPRESSION WAR, with TRADINGVIEW EYES

Repository inspection and reviewable specification only (2026-09-12). Written against `exit-scheduling-003` at
`009a641`, with the TradingView modules read from `origin/tradingview-connector-001` at `39fbd21`.

**Nothing in this document has been built, wired, fitted, evaluated, deployed or authorized by writing it.** No
provider call was made, no credential was touched, no limit or risk law was changed, no recorded evaluation was run.
Every claim below was verified by reading this repository; where I could not verify something I say so.

---

## 0. What this specification is for

APEX can already take one instrument class — a single long option — from forecast to intent to paper fill to Book,
with unresolved accounting kept explicit. What it cannot do is **decide what to look at, decide what kind of trade
expresses a view, and compare those expressions on equal terms.** Those three absences are the subject here.

The goal is not more components. It is **one reconstructible decision**: from the observation that made a symbol
interesting, through the setup that named the opportunity, to the expression chosen over its rivals, to the outcome
— with every step's evidence, provenance and refusals recorded on the same ledger.

---

## 1. Verified inventory

Legend: **BUILT** = code exists and is tested · **WIRED** = reachable from the live options decision path ·
**ABSENT** = does not exist.

### 1.1 The live path, end to end

```
entrypoint → pulse_options.TwinSources → decision_wb.FunnelEngine
   (GARCH-t variance + MarkovSwitching2 regime + ConditionalSimulator + expression_war.compare + PRIME)
 → options_pilot.session.scan → risk_authority.approve → risk_certificate.certify + risk_kernel.check
 → Book → lifecycle.LifecycleRunner
```

This is the only path that can produce an intent. **Only long single options can traverse it** (§6).

### 1.2 Stage by stage

| area | status | evidence |
|---|---|---|
| forecast → intent → paper fill → Book | **BUILT + WIRED** | exercised on recorded data; unresolved accounting stays explicit |
| arrival-based exits, restart continuity, policy binding | **BUILT + WIRED** | EXIT-SCHEDULING-002/003; synthetic only; recorded feed **not** wired |
| premarket | **BUILT, NOT WIRED** | four independent implementations (§4.1); zero references from the options path |
| setup detection | **BUILT, NOT WIRED** | `apex/hunter/playbooks_v1.py` H001/H002 only; consumed solely by `hunter/forward_pass.py` |
| regime | **BUILT + WIRED** | `worldmodel_wb/regime.MarkovSwitching2`, mandatory in FULL mode; feeds simulator variance only |
| forecasting | **BUILT + WIRED, NOT VALIDATED** | `EXP002_L`, artifact stamped `experiment_status: INVALID_NULL_CONTROL`, `no_validated_edge_claim: true` |
| expression war | **BUILT + WIRED, NO AUTHORITY** | `SELECTION_AUTHORITY = "NONE"`; options-only candidates (§6.1) |
| stocks / verticals as candidates | **ABSENT** | structurally excluded (§6.2, §6.3) |
| account semantics | **ABSENT** | verified: no `settled_cash`, `available_cash`, `committed_capital`, `options_level` or `buying_power` anywhere in `apex/options_pilot/` or `apex/organism/` |
| challengers / learning | **BUILT, NOT WIRED** | `edgeforge`, `frontier2`; a parallel shadow lane |
| TradingView | **ADAPTER BUILT, NOT WIRED, NOT SMOKE-TESTED** | §8 |

I confirmed the disconnect directly: `grep -rn "premarket\|playbook\|hunter" apex/options_pilot/ apex/decision_wb/
apex/pulse_options/` returns **nothing**.

### 1.3 What the recorded diagnostic actually showed

FLOW-VALIDATION-001: twelve scan instants, one partial session. Every scan produced `WAIT` with
`NO_ELIGIBLE_CANDIDATE`. Eighteen option candidates per scan, **zero affordable**: cheapest ask principal $650
against a $500 per-trade cap. **The funnel's selection value is therefore unmeasured** — it never got to choose.
That is the single most important fact about the current system's intelligence, and this specification must not
paper over it.

---

## 2. The gap, in one sentence

APEX has eyes that see, a lab that hypothesises, and a hand that trades exactly one instrument — and **none of the
three are connected to each other**, so no recorded decision can currently be traced from an observation to a
setup to a considered choice among expressions.

---

## 3. Target architecture

Three stages, each with a contract, all writing to the existing ledger. **Every stage is refusable**: a stage that
cannot state its output honestly emits a named refusal and the pipeline continues to WAIT rather than degrade
silently.

```
  PREMARKET CONTEXT ──► SETUP LAB ──► CROSS-INSTRUMENT EXPRESSION WAR ──► RISK ──► PRIME ──► intent
   (what is worth        (what is      (which instrument expresses      (may we)  (should we)
    looking at, and       true about    this view best, priced and
    why, with             it right      certified on equal terms)
    availability)         now)
```

**A stage boundary is a record, not a function call.** Each stage's output is persisted with its own
`snapshot_id`, source receipts and refusals, so a decision can be reconstructed from the ledger alone.

### 3.1 The universal availability discipline

Already enforced in `replay.most_recent_available()` and `tradingview/normalize.py`, and it must govern every new
stage:

> An input's availability instant is when it **reached this system**, never its own event time. A datum with no
> recorded availability does not enter a decision; it is not backdated.

---

## 4. Stage 1 — PREMARKET CONTEXT

### 4.1 The choice to make first

Four premarket implementations exist and share no contract:

| module | what it is | decision power |
|---|---|---|
| `apex/pulse/premarket.py` | `PULSE_PREMARKET_PATH_V0`, an observation path | superseded by `PULSE_BOUNDED_STATE_V1` per `test_whole_ledger_guard.py` |
| `apex/catalyst/premarket.py` | phases, schedule, catalyst environment, pre-bell brief | LLM brief, `FORBIDDEN_IN_BRIEF` guards |
| `apex/frontier/premarket.py` | sealed premarket packets | `NONE_FRONTIER_SHADOW` |
| `apex/hunter/watchlist.py` + `chartstate.py` | watchlist with rvol, `RVOL_VALID`/`INVALID_SESSION`/`UNKNOWN` | hunter lane only |

**Recommendation: none of them is promoted as-is.** Specify a thin `PremarketContext` record that the options path
consumes, and let the existing modules become *producers* of it. Promoting one implementation wholesale would
import its lane's assumptions (and, for two of them, a different deployment host — `apex-equities` under launchd
versus `/opt/apex/current` under systemd; see `docs/DEPLOYMENT_DIVERGENCE_001.md`).

### 4.2 The contract

```
PREMARKET_CONTEXT_V0
  snapshot_id              stable id; every downstream record references it
  as_of_epoch / _utc       the instant this context claims to describe
  session_date, phase      from catalyst.premarket.phase_at
  per symbol:
    prior_close, gap_pct                 value + availability + quality state
    rvol_tod                             RVOL_VALID | RVOL_INVALID_SESSION | RVOL_UNKNOWN (never a number when not VALID)
    key_levels[]                         {level, kind, derivation, source_receipt}
    event_context                        from catalyst.twin_snapshot.event_snapshot (already wired, SHADOW)
    external_context[]                   TradingView observations (§8), EXTERNAL_CONTEXT_ONLY
  refusals[]               named, per field
  authority                "CONTEXT_ONLY: admits no risk and selects nothing by itself"
```

**Quality states are not optional.** `apex/hunter/watchlist.py` already models rvol as a value *plus* a validity
state precisely because a half-session rvol is not a small error, it is a different number. That discipline carries
over: a field is `VALID` with a number, or it is one of the named non-numeric states — never a number with a
caveat.

### 4.3 What premarket must not do

It must not rank, score, or select. It answers "what is true and knowable about this symbol before the open", and
nothing else. Selection is Stage 2's job and authority is Stage 4's.

---

## 5. Stage 2 — SETUP LAB

### 5.1 Honest starting position

**No profitable strategy has emerged from this work.** The only concrete, named setups in the repository are
`HUNTER-001` (long continuation) and `HUNTER-002` (failed-extension reversion), deliberately opposed, consumed only
by the hunter forward pass. The hypothesis machinery (`edgeforge/hypotheses.py`, `research/hypothesis.py`,
`edgeforge/registry.py` with `DISCOVERY_STATUSES` including `NULL_RESULT`) is real and unused by the live path.

This specification therefore treats the Setup Lab as **a contract and a scoreboard, not a claim of edge**.

### 5.2 The contract

```
SETUP_OBSERVATION_V0
  snapshot_id              references the PremarketContext it was computed from
  setup_id, setup_version, setup_hash        frozen definition, hashed like an exit policy
  symbol, as_of_epoch
  matched: bool
  features{}               every input value WITH its availability instant
  levels{}                 entry reference, invalidation reference, target reference — as PRICE LEVELS ONLY
  horizon_s                the time over which the claim is made
  claim                    a falsifiable statement: direction + horizon + invalidation
  authority                "RESEARCH_ONLY" until promoted through the existing ladder
  refusals[]
```

Three rules that keep this from becoming a signal generator by accident:

1. **A setup states levels and a horizon; it never states a size, an instrument or a probability.** Sizing is risk's;
   instrument choice is Stage 3's; calibrated probability must be earned, not asserted.
2. **A setup is frozen and hashed before it is evaluated**, exactly as exit policies are. `setup_hash` is recomputed
   from the definition's own fields, so an edited setup cannot silently inherit an old record's evidence.
3. **Every setup carries its null.** The registry already models `NULL_RESULT`; a setup with no recorded null
   comparison is not eligible for promotion.

### 5.3 The scoreboard the operator actually needs

For the eventual chronological evaluation (step 4 of the sequence), each setup accumulates: instances, matched
rate, forecast quality against its own stated horizon, after-cost outcome, unresolved-position count, and the
comparison against **WAIT** and against a **simple rule**. A setup that cannot beat WAIT is not a setup.

---

## 6. Stage 3 — CROSS-INSTRUMENT EXPRESSION WAR

This is the substantive engineering problem, and it is **blocked by two independent walls**, both deliberate.

### 6.1 What `expression_war.compare` is today

`apex/multiverse_wb/expression_war.py` compares candidates over shared Monte Carlo paths, records
`expected_net_pnl`, `p_loss`, quantiles, `certified_max_loss`, IV sensitivity and quote uncertainty — and carries
`SELECTION_AUTHORITY = "NONE: the pilot's deterministic rule selects; this comparison is recorded, not applied"`.

**Every candidate is a long option.** `_pnl_paths` unconditionally prices with `bsm_price_vec(S_H, inst["strike"],
…, right=inst["right"])` and returns `100.0 * (exit_bid - entry_ask) - fees`. There is no share expression and no
spread expression in the comparison at all. The `WAIT` row is a hardcoded zero.

So the name overstates it: it is an **option-strike comparison**, not a cross-instrument tournament.

### 6.2 Wall one — shares cannot be certified

`apex/organism/risk_certificate.py`:

```
CERTIFIED_RISK_AUTHORITY = {DEFINED_MAX_LOSS: True, STOP_DEFINED: False, UNBOUNDED: False, NOT_ESTIMABLE: False}
_certify_stock:  risk_class = UNBOUNDED if direction == "SHORT" else STOP_DEFINED
                 certified_max_loss = None
```

and `apex/options_pilot/risk_authority.py:156` hard-refuses anything that is not `DEFINED_MAX_LOSS`.

**A long share position is `STOP_DEFINED`, which has no certified authority, so it cannot reach PRIME.** The law
behind it is stated in the module: *a stop yields an INTENDED maximum loss, never a GUARANTEED one.* The named
unlock is `STOP_DEFINED_RISK_MODEL_V1`, which **does not exist in code** — it appears only inside refusal strings.

This wall is correct and should not be removed to make the tournament possible. What it means is that a share
expression can enter the comparison **as a research-observation candidate that is structurally ineligible for
PRIME**, and the comparison must show it as such rather than omitting it. Making shares *eligible* is a separate,
evidence-gated brick: `STOP_DEFINED_RISK_MODEL_V1` earned on real gap and slippage evidence, never a relabelling.

### 6.3 Wall two — verticals are refused by the exit rule, not by their structure

`VERTICAL_NOT_CERTIFIABLE`: a debit vertical is bounded by its debit **only at expiry**. Every exit rule here is
pre-expiry (`EXIT_AT_HORIZON_15M_V1` closes 15 minutes after fill), and closing early requires buying back the
short leg, realising `(long bid − short ask)`, which can be negative by two spreads that are not knowable in
advance.

**This is the most tractable unlock in the system**, because the module states the condition itself: *"Under a
hold-to-expiry exit rule this same structure WOULD be `DEFINED_MAX_LOSS`."* A vertical becomes certifiable the
moment it is paired with a hold-to-expiry exit policy — which the exit-policy binding work now makes safe to
introduce, because a position's exit contract is resolved from its own fill and cannot be swapped by a later
process.

That is a real design consequence of the last two bricks: **per-expression exit policies are now safe**, because
the policy is bound to the position rather than to the process.

### 6.4 The contract

```
EXPRESSION_CANDIDATE_V0
  setup_ref                 the SETUP_OBSERVATION_V0 this expresses
  expression                LONG_CALL | LONG_PUT | CALL_VERTICAL | PUT_VERTICAL | STOCK
  direction, quantity
  exit_policy_id/hash       THE EXIT CONTRACT IS PART OF THE CANDIDATE, not a global setting
  pricing{}                 quoted sides used, their receipts, spread, quote_uncertainty
  economics{}               expected_net_pnl, p_loss, quantiles, IV sensitivity, mc_se_mean — over SHARED paths
  money{}                   the three quantities of §7, never collapsed
  certificate{}             risk_certificate.certify output, verbatim
  eligibility               PRIME_ELIGIBLE | RESEARCH_OBSERVATION_ONLY | REFUSED  + why
  affordability             FEASIBLE | INFEASIBLE + which quantity bound it
```

### 6.5 The comparison rules

1. **Shared paths or no comparison.** All candidates for one setup are scored on the same simulated paths with the
   same seed and parameter hash, or the comparison is refused. Comparing across different path sets is not a
   comparison.
2. **Ineligible candidates are shown, not hidden.** A share candidate that is `RESEARCH_OBSERVATION_ONLY` appears in
   the record with its economics and its ineligibility. Silently dropping it would hide the fact that the certified
   option may be the *worse* trade that happens to be the only permitted one — which is precisely the thing the
   operator needs to be able to see.
3. **Affordability is a gate, not a rank.** See §7.
4. **The tournament proposes; it does not select.** `SELECTION_AUTHORITY` stays `NONE` until a review grants it.
   Until then the deterministic rule still selects and the tournament is recorded alongside — which is exactly how
   its selection value can be measured before it is trusted.

---

## 7. The three money quantities, kept separate

The operator has been explicit about this and the current code conflates two of them in places. All three must
appear on every candidate, never collapsed into one "risk" number:

| quantity | definition | where it binds |
|---|---|---|
| **cash committed** | what actually leaves the account to open — `ask × 100 × n + entry fees` for a long option; `price × shares` for stock | affordability against available capital; **this is the quantity that killed all 12 recorded scans** ($650 cheapest vs $500) |
| **planned stop loss** | the *intended* loss at the declared invalidation level — `canonical_planned_risk(...)`; `planned_risk_basis` is `UNVERIFIED_UPSTREAM_LABEL` when no stop exists | the kernel's `LIMIT_DENOMINATION = PLANNED_RISK_DECLARED_1R` |
| **maximum possible loss** | what the structure makes economically possible: the debit for a long option; `None` for stock (gap risk is unbounded below in principle and only reported at `GAP_REPORT_POINTS`) | `certified_max_loss`, and the `DEFINED_MAX_LOSS` gate |

Two consequences the specification must enforce:

- **A stop is not a certificate.** Planned loss and certified maximum loss are different kinds of claim, and the
  code already says so. A candidate that offers only a planned loss is research-observation only.
- **An affordable trade is not necessarily a good trade.** Affordability filters the candidate set; it must never
  contribute to ranking. The FLOW-VALIDATION-001 result — WAIT on all twelve scans — was the *correct* answer to
  "can we afford any of these", and tells us nothing about whether any of them was worth taking.

**On the illustrative figures:** the $25–$100 paper-risk range discussed earlier was illustrative only and is **not
an approved setting**. The current authorized limits are unchanged and remain: $500 per trade, $1,500 aggregate,
$600 same-underlying, $1,000 same-family, $1,000 session drawdown halt, on `STARTING_PAPER_CAPITAL = 10,000`.
Nothing in this specification proposes changing them.

### 7.1 The account semantics that do not exist

Verified absent from `apex/options_pilot/` and `apex/organism/`: `settled_cash`, `available_cash`,
`committed_capital`, `options_level`, `buying_power`, account restrictions. The only cash concept is the derived
`STARTING_PAPER_CAPITAL + Σ cashflows` identity plus an `available_capital` argument that callers must supply.

**A cross-instrument tournament makes this gap load-bearing**, because shares and options consume capital and
permissions differently (and a vertical needs an options level that is not modelled at all). Specifying the
tournament without specifying account semantics would produce a comparison that is arithmetically fine and
operationally false. This is called out as a prerequisite, not folded in silently.

---

## 8. TRADINGVIEW EYES

### 8.1 Verified status, today

I re-verified this session rather than trusting the earlier record:

| capability | status | how verified |
|---|---|---|
| server reachable & account authorized | **CONNECTED** | `claude mcp list` → `mcp-tradingview … ✔ Connected` |
| tools visible to **this** session | **NOT AVAILABLE** | `ToolSearch` for TradingView tools returns nothing; the session's startup notice lists `mcp-tradingview` as needing authentication |
| retained live smoke evidence | **NONE** | no smoke artefact in `docs/evidence/`; the connector record states zero calls were ever made |
| adapter | **BUILT, 51 synthetic tests** | `origin/tradingview-connector-001` @ `39fbd21` |
| adapter present on the current branch | **NO** | `apex/tradingview/` does not exist on `exit-scheduling-003` |
| unattended APEX service access | **NOT CONNECTED** | `adapter.runtime_status()["unattended_apex_runtime"]` says so explicitly |
| chart rendering / screenshots | **NOT AVAILABLE** | the documented connector offers no chart-image tool |
| options chains / executable option quotes | **NOT AVAILABLE** | not offered by this connector |

**The distinction the operator drew is the correct one and the code already encodes it.** `runtime_status()`
separates `interactive_claude_code` (a person's OAuth session, held by the Claude client) from
`unattended_apex_runtime` (`NOT_CONNECTED`, "no runtime route exists"), and lists what it will never do: export or
copy Claude's tokens, read Claude's credential storage, or embed a credential anywhere. A connected interactive
client is **not** evidence that a Python service can authenticate.

### 8.2 Available tools mapped to Twin inputs

Allowlisted in `apex/tradingview/allowlist.py` (a literal tuple — anything new is denied by default):

| tool | Twin input | class |
|---|---|---|
| `search_symbols` | symbol resolution to `EXCHANGE:TICKER` | reference |
| `get_ohlcv` | bars for **display and cross-check**, never the price of record | `EXTERNAL_CONTEXT` |
| `get_technicals_rating` | indicator context | `EXTERNAL_CONTEXT_ONLY`, `calibrated = False` |
| `get_news`, `get_news_story` | narrative context, joins the existing event lane | `EXTERNAL_CONTEXT_ONLY` |
| `get_earnings_calendar`, `get_economic_calendar`, `get_dividends_calendar` | scheduled-event context | `EXTERNAL_CONTEXT_ONLY` |
| `get_screener_columns` | field discovery before any screener use | reference |

`get_active_watchlist` stays excluded: the official documentation carries a read-only label **and** describes
activation/creation side effects for it. The described behaviour governs; the label does not.

### 8.3 The specified handoff

```
TradingView observation
  → request_start / response_receipt          (adapter, both recorded)
  → known_from = response_receipt             (normalize.py; NEVER the candle's own time)
    historical_availability = NOT_ESTABLISHED
    valid_for_as_of(t) refuses t < known_from
  → TRADINGVIEW_OBSERVATION_V0 {tool, args, payload_digest, entitlement_state, authority}
  → bound into PREMARKET_CONTEXT_V0.external_context[] under that context's snapshot_id
  → carried by reference (snapshot_id + payload_digest) into SETUP_OBSERVATION_V0.features.provenance
  → carried by reference into EXPRESSION_CANDIDATE_V0
  → the decision record names every external observation that informed it, by digest
```

**The binding is by reference and digest, not by copy.** A decision record says *which* observation informed it and
proves the bytes; it does not embed a second copy that could drift.

### 8.4 Failure and staleness semantics

- Every adapter failure is already a **named state**, not an exception: `TOOL_DENIED`, `BUDGET_EXHAUSTED`,
  `RATE_LIMITED`, `TIMEOUT`, `AUTHENTICATION_FAILED`, `PROVIDER_UNAVAILABLE`, `MALFORMED_RESPONSE`.
- A missing or stale observation makes its field `UNKNOWN`/`STALE` in the premarket context. **It never becomes a
  number with a caveat, and it never blocks the stage** — the context is emitted with that field refused.
- `entitlement_state` is `UNKNOWN` unless verified; the adapter does not claim a plan it has not checked, so
  real-time versus delayed is an open question on every observation until proven otherwise.
- **TradingView failure must never stop exit servicing.** Already contracted: `adapter.never_blocks()` states
  `EXIT_SERVICING_INDEPENDENT` and a test asserts the module imports nothing from the execution or exit path. The
  specification's addition is that the *new* stages must preserve it — premarket, setup lab and the tournament sit
  strictly before intent creation, and no exit, retry or deadline may await any of them.

### 8.5 Four capabilities, kept distinct

| capability | status |
|---|---|
| chart rendering (a human-viewable chart) | **UNAVAILABLE** from this connector |
| optional visual interpretation (an AI reviewer explaining a chart) | **UNAVAILABLE**; and it could only ever explain, never establish expectancy |
| quantitative setup detection | **NEEDS BUILDING** (§5), computed from timestamped market data, never from an image |
| execution quotes | **NOT FROM HERE** — the primary market-data feeds remain responsible for timely bars and executable quotes |

A screenshot cannot establish that a trade has positive expectancy. The chart's role is to let a person — or an
optional reviewer — inspect the same facts the quantitative system computed.

### 8.6 The authentication question, unanswered

There is no specified service-authentication route because I could not find one documented. TradingView documents
OAuth 2.1 with **no token lifetime**, and `runtime_status()` records `refresh_lifecycle: UNDOCUMENTED`. An
unattended route needs its own reviewed credential with a stated owner and refresh lifecycle. **That has not been
designed, authorized or built, and this specification does not propose borrowing Claude's session for it.**

---

## 9. Build order, with the authorization each step needs

| # | step | authorization beyond ordinary build |
|---|---|---|
| 1 | Wire recorded observations into V2 and re-run the diagnostic | synthetic acceptance first; the recorded rerun is a separate grant |
| 2 | `PREMARKET_CONTEXT_V0` record + one producer, options path reads it as context only | none — admits no risk |
| 3 | TradingView smoke test (≤10 calls, from `/Users/derekduenas`) and merge the adapter forward | a session that can see the tools; the operator's existing bounded grant |
| 4 | `SETUP_OBSERVATION_V0` + the two existing playbooks as producers, `RESEARCH_ONLY` | none — no selection authority |
| 5 | Per-expression exit policies, incl. a hold-to-expiry policy | policy freeze + review (now safe: policies bind to positions) |
| 6 | Verticals into the tournament as `PRIME_ELIGIBLE` under hold-to-expiry | risk review of the certificate change |
| 7 | Account semantics (`settled_cash`, permissions, options level) | required before any multi-instrument sizing is trusted |
| 8 | Shares into the tournament as `RESEARCH_OBSERVATION_ONLY` | none for observation; PRIME eligibility needs `STOP_DEFINED_RISK_MODEL_V1` on real gap/slippage evidence |
| 9 | Chronological evaluation over comparable opportunities | evaluation grant; contract frozen before execution |

Steps 5 and 6 are the highest value per unit of risk: they are the only route to a genuinely
`DEFINED_MAX_LOSS` multi-leg expression, the module itself names the condition, and the exit-policy binding just
built is what makes per-expression policies safe.

---

## 10. Open decisions for the operator

1. **Which premarket producer** feeds `PREMARKET_CONTEXT_V0` first — and whether the cross-host divergence
   (`apex-equities` launchd vs `/opt/apex/current` systemd) is resolved before or after wiring.
2. **Whether ineligible candidates appear in the tournament record.** I recommend yes (§6.5) — it is the only way to
   see when the permitted trade is the worse trade — but it puts uncertifiable economics on the ledger, which is a
   choice worth making deliberately.
3. **Whether a hold-to-expiry exit policy is acceptable for this book at all**, given it holds exposure far longer
   than 15 minutes. Verticals' certifiability depends entirely on it.
4. **Whether the tournament may ever hold selection authority**, and what evidence would earn it. Until then its
   value stays unmeasured no matter how much of it is built.

---

## 11. What this specification deliberately does not do

- It does not change any limit, risk law, fee, selection policy or exit policy.
- It does not propose making shares PRIME-eligible, or removing either certification wall.
- It does not claim any strategy, setup or model has an edge. `EXP002_L` remains stamped
  `INVALID_NULL_CONTROL`, and `BRICK4_WALKFORWARD_CONTRACT.md` still reports **0 fittable sessions**.
- It does not authorize a provider call, a deployment, a credential change or an account change.
- It does not specify an exhausted-position rescue route; that remains a separate policy with its own authority.
