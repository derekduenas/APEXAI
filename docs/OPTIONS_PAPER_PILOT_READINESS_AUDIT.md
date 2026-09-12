# Options paper-pilot readiness audit

**Audit and design only.** No model fitting, no historical rescoring, no broker
orders, no deployment, no change to any service. Every claim below cites a file
or a retained record on the host. Where a fact could not be established it is
marked UNKNOWN.

Repository audited: `/opt/apex-repo` at `eca00a9e5`. Live evidence:
`/apex-data/core/options_live_ledger.jsonl` (94 hash-chained records, 9
sessions 2026-08-24 → 2026-09-04) and `/apex-data/core/outbox/v1_decisions.jsonl`
(916 records, 2026-08-27 → 2026-09-04). Service `apex-options-paper.service`:
**inactive, disabled, under a maintenance block** since 2026-09-07
(`MAINTENANCE_BLOCKED_PENDING_LAUNCH_AUTHORIZATION`, drop-in
`ConditionPathExists=!/apex-data/core/ops/MAINTENANCE_BLOCK_options_paper`).

---

## 1. What exists, verified against code and records

| Component | Where | What it does | Status |
|---|---|---|---|
| Option quotes | `apex/intraday/options_feed.py::option_chain_snapshot` | ThetaData terminal (`:25503`, **live now**, Java process running); per-contract `timestamp, bid, ask, bid_size, ask_size, expiration, strike, right`; drops zero, negative and crossed quotes | present |
| Underlying NBBO + bars | same module, Alpaca SIP | data-only keys; **paper-trading endpoint returns 401** (runbook §"Feeds") | present, data only |
| Freshness | `apex/predators/options/live_world.py::observe` | `q_age` = now − newest quote, `MAX_QUOTE_AGE_S = 120`, `MAX_BAR_AGE_S = 300`; `feed_quality != GOOD` → session **refuses** (`options_paper_session.py:106`); geometry independently maps stale → `execution UNKNOWN` → `cq UNKNOWN` → **not attackable** (`attack_geometry.py:160-162, 176-247`) | present, threshold lax (see G2) |
| Seal before fill | `options_paper_session.py:210-244` | `seal_before_card` → `chain_append(options_live_card)` → `simulate_entry(..., sealed_card_hash=)` → `chain_append(options_live_attack)`. `simulate_entry` **refuses** without a ≥32-char sealed hash (`paper_execution.py:78-81`) | present, enforced |
| Durable decision channel | `apex/ops/outbox.py` | append-only, hash-chained, `known_from` on every record, checkpointed consumer cursor; 916 records retained | present |
| Fill law | `paper_execution.py::simulate_entry` | long pays that contract's ASK, short receives its BID, stock crosses the executable side; full contract identity `(expiration, strike, right)`; no midpoint, no model price; pedigree recorded | present, tested |
| Exit accounting | `paper_execution.py::_exit_value/_exit_accounting/resolve` | marks out at quoted sides (long → BID, short → ASK); exact identity `pnl = mid_change − entry_friction − exit_friction` verified per outcome (`friction_identity_holds`); **causal path invariant** enforced in `resolve` (post-Day-1 defect B) | present, tested |
| Contract selection | `expression.py::CANDIDATE_RULES` (pre-registered 2026-08-23) | `dte_min 21`, nearest eligible expiry, long strike nearest-ATM, vertical wing first strike ≥ 1.5% OTM; session picks the attackable expression with the **smallest breakeven move** (`options_paper_session.py:200-203`) | present, declared |
| Expression competition | `expression.py::build_candidates/compare/normalize` | STOCK, LONG_CALL, LONG_PUT, CALL_VERTICAL, PUT_VERTICAL, NO_TRADE on quoted economics; `compare` returns **`NOT_ESTIMABLE`** when no expected move is supplied | present |
| Defined-risk certification | `apex/organism/risk_certificate.py::certify/_certify_option` | max loss **derived from legs**, multiplier 100 enforced, **DEBIT-only** structures certified; `planned_risk / certified_max_loss / realized_pnl` kept distinct | present, tested |
| Portfolio limits | `apex/organism/risk_kernel.py` | predeclared: `$500/trade`, `$1,500 aggregate`, `$600 same underlying`, `$1,000 same family`, `$1,000 session drawdown halt`; kernel refusal cannot be overridden by the allocator | present |
| Reconciliation | `apex/organism/live_book.py::reconcile` | joins **broker** fills to sealed `live_intent`s 1:1 by `broker_ref`; orphans sealed `UNRECONCILED`, never guessed | present, **no callers** |
| Retained outcomes | live ledger | 19 attacks (11 LONG_PUT, 7 CALL_VERTICAL, 1 LONG_CALL) across SPY, QQQ, IWM, AAPL, MSFT, NVDA; 15 resolved with P&L, **4 `NOT_ESTIMABLE`** (exit quote missing); sum executable P&L **−$262**, total friction **$200**; primary classes THESIS_WRONG 7, THESIS_RIGHT_OPTION_LOST 4, EXECUTION_FAILURE 4, THESIS_RIGHT_FRICTION_SURVIVED 4 | retained |
| Session scoreboard | ledger `options_session_scoreboard` | full refusal funnel per session (last: 131 candidates → 2 attacks; 129 refusals: NO_TRADE 103, NO_DIRECTIONAL_THESIS 18, GEOMETRY 8) | retained |
| Tests | `tests/test_options_paper_execution.py` (27 tests) + related suites | run at HEAD in this audit — see §4 | see §4 |

---

## 2. Evidence-backed gap table

Ordered by how much each blocks an *honest* pilot, not by effort.

| # | Gap | Evidence | Acceptance criterion |
|---|---|---|---|
| **G0** | **The loop has no forecast input.** The session attacks on *geometry*; `forecast_pedigree="NOT_ESTIMABLE"` is hard-coded (`options_paper_session.py:166`), and `expression.compare` returns `NOT_ESTIMABLE` — "no option may be declared superior to STOCK without a forecast" — so the expected-move normalisation is never exercised live | `options_paper_session.py:166`; `expression.py:444-487`; every retained card lacks a forecast field | A **timestamped forecast record** (`known_from`, sealed hash) exists **before** any quote is consulted, supplies `expected_move_pct` (and direction) to `compare/normalize`, and its hash is carried on the card and the outcome. Test: an attack without a sealed forecast is refused |
| **G1** | **Live cards and outcomes are mislabelled as replay.** Every `options_live_card` and `options_outcome` carries `evidence_class: HISTORICAL_DEVELOPMENT_REPLAY`, `decision_power: NONE_REPLAY`, law "never prospective evidence" — while the same session's friction and scoreboard records say `PROSPECTIVE_PAPER` | ledger records; cause: `options_paper_session.py:39` imports `seal_before_card` from `apex/predators/options/replay.py`, which stamps `EVIDENCE_CLASS` (replay) | A prospective sealer in a live module stamps `PROSPECTIVE_PAPER` / `NONE_PAPER` and `live_promotion_eligible` truthfully; a test asserts no live record ever carries the replay class; the 9 historical sessions are annotated as mislabelled, **not rewritten** |
| **G2a** | **Freshness is checked for the newest quote anywhere in the chain, not for the selected contract and side.** `live_world.observe` computes `q_age` from `newest` across all fetched expirations (`live_world.py:31`); one fresh contract can mask a stale selected one | `live_world.py:26-48` | Freshness is evaluated **per selected contract and per side crossed** at execution time; a stale selected side refuses regardless of the chain's newest quote. Implemented and tested in the recording boundary (`apex/options_pilot/boundary.py::_quote_ok`, `test_freshness_is_checked_for_the_selected_contract_and_side`) |
| **G2** | **Stale-quote threshold is 120 s** and the code says so: `STALE_QUOTE_S = 120.0  # far too lax for live` (`attack_geometry.py:69`); timestamps are handled ET-naive with a documented history of a 4-hour offset bug (`live_world.py:3-5`, `resolve` docstring) | code comments; Day-1 defect B record | A declared **live** quote-age limit (proposal: **≤ 15 s** for option quotes, ≤ 90 s for bars — to be set from measured ThetaData snapshot cadence, §5), tz-aware timestamps end-to-end, and tests that a 16 s quote refuses and a naive timestamp is rejected |
| **G3** | **Risk certification and the risk kernel are not invoked by the options session.** `risk_kernel.check` callers: `hunt.py, allocator.py, baselines.py, flight_sim.py, first_dollar_readiness.py` — not `options_paper_session.py`; `certify` likewise. The session's only limit is "one open paper position per symbol" (`:387`) | `grep` in this audit; `options_paper_session.py:385-388` | `certify()` and `risk_kernel.check()` run **before** `simulate_entry`; their records are chained; a refusal by either is sealed as a refusal; a test forces an aggregate-limit breach and asserts no fill |
| **G4** | **No commissions or fees.** Friction is the half-spread only: retained `entry_friction 0.0`, `exit_friction 1.0` per contract; no per-contract commission, OCC/ORF/exchange fees | `paper_execution.py` (no fee term); friction records | Declared paper fee schedule as constants (per contract, per leg, entry and exit), added as a **fourth term** of the identity `pnl = mid_change − entry_friction − exit_friction − fees`; identity test updated; attribution reports fees separately |
| **G5** | **No latency.** The fill uses the quote snapshot at decision time `T` with zero delay | `simulate_entry` fills from `candidate.legs` prices captured at `T` | Declared decision-to-fill latency `Δ` (proposal: **re-quote at T+Δ, Δ = 2 s**, fill at the re-quoted side; if the re-quote is unavailable or worse by more than a declared tolerance, record `EXECUTION_DEGRADED`); test with an injected worse re-quote |
| **G6** | **No partial fills; size ignored.** `contracts=1` fixed; `bid_size/ask_size` are captured but used only as a geometry "touch size" prior, never in the fill | `options_paper_session.py:230-233`; `attack_geometry.py:150-154` | Fill quantity = `min(intended, touch size at the quoted side)`; unfilled remainder sealed as `UNFILLED`; test with touch < intended |
| **G7** | **Reconciliation exists but is never called, and reconciles against broker fills that do not exist.** `live_book.reconcile` has zero callers; Alpaca paper trading returns 401 (data-only keys); no broker fill stream | `grep` in this audit; runbook "Feeds" | For a simulated-fill pilot: a **simulated-fill reconciliation** that joins every `options_outcome` to exactly one `options_live_card` by `card_hash` and every card to at most one fill, sealing orphans `UNRECONCILED`; run at session end and its record chained. Broker-fill reconciliation stays out of scope until a paper broker endpoint is authorised |
| **G8** | **Missing exit quotes leave outcomes `NOT_ESTIMABLE`** — 4 of 19 (21%) | ledger `r_multiple: NOT_ESTIMABLE` ×4 | A declared exit-quote capture window (proposal: retry every 5 s from T−120 s to the close) and a **per-session `NOT_ESTIMABLE` rate target ≤ 5%**, reported on the scoreboard; missing exits remain `NOT_ESTIMABLE`, never imputed |
| **G9** | **Release drift.** The last paper session ran release `5eff1cf5` (2026-08-30); `/opt/apex/current` is `73fc712d` (2026-09-07 recovery). No paper session has run on the current release | heartbeat `release_commit`; `readlink /opt/apex/current` | The pilot pins one release by commit; **one supervised session** on that release is completed and reviewed before any session counts toward the pilot |
| **G10** | **Outbox path binding unverified.** The script writes `Path("results/outbox/v1_decisions.jsonl")` relative to `WorkingDirectory=/opt/apex/current`; the retained file is at `/apex-data/core/outbox/v1_decisions.jsonl` | `options_paper_session.py:380`; `deploy/apex-options-paper.service:10`; `find` in this audit | Record the actual binding (symlink or otherwise) and pin the outbox path absolutely in the pilot config |
| **G11** | **Sample-size discipline exists but the pilot has no declared stopping rule** | `replay.py::sample_accounting` ("n_raw NEVER implies independence"); scoreboard `attacks_effective_lower_bound` | Pre-declared session count and success criteria (§5) — the pilot ends on the count, not on P&L |

Not gaps, but stated: the Alpaca options entitlement was confirmed (runbook: "options entitlement confirmed", data-only) and its probe tests pass in the milestone-1 regression records; the Robinhood-MCP path is explicitly non-reproducible from a script and is **out of scope** here (`alpaca_options_entitlement_probe.py` docstring).

---

## 3. The shortest complete path — as it stands vs as required

```
NOW:      geometry ──► expression (no forecast) ──► seal(REPLAY label) ──► fill@T ──► hold ──► resolve@close ──► friction
REQUIRED: forecast(sealed, known_from)
             └─► expression(compare with expected_move) ─► certify + kernel.check ─► seal(PROSPECTIVE) ─► fill@T+Δ (size, fees)
                    ─► hold ─► resolve@close (exit-quote window) ─► reconcile(card_hash 1:1) ─► friction(4-term identity) ─► scoreboard
```

Every box in the required line already has code behind it except: the forecast
record (G0), the prospective sealer (G1), the fee term (G4), the re-quote (G5),
the size-aware fill (G6), and the simulated-fill reconciliation (G7). None is a
new model.

---

## 4. Test evidence at HEAD

Run contained (`MemoryMax=1400M`, `wmresearch.slice`) at `/opt/apex-repo`
`eca00a9e5`: **348 passed in 6.13 s** across 29 files — the options
paper-execution, expression, attack-geometry, friction-attribution, scoreboard,
live-session, acquire/replay-causality, research, live-book, paper-track,
shadow-paper, commissioning and entitlement-probe suites.

Two things the passing suites establish about the gaps, not against them:

- `tests/test_options_live_session.py` passes while every retained live card
  carries the replay label — so **no test currently asserts the evidence class
  of live records** (G1 is untested, not merely unfixed).
- `tests/test_live_book.py` passes while `live_book.reconcile` has no caller —
  the reconciliation logic is verified in isolation and **never exercised by the
  session** (G7).

Tests establish the code computes what it claims on fixtures. They do not
establish feed behaviour, cadence, or anything about edge.

---

## 4b. Corrections to this audit after review (before any implementation)

- **G0 as first written included modelling choices.** `rv_30·s₀` is a Student-t
  *scale* for the registered 15-minute return, not an expected directional move
  and not a hold-to-close forecast; combining it with a trend label and stretching
  the horizon would have manufactured a new forecasting specification. Corrected:
  the pilot keeps the **native 15-minute horizon** and identifies the **exact
  frozen parameter artifact** (EXP-002 sealed result, `params_hash
  ca04fc6e713e1a5c`, registered L arm with shared `s* = 3.288, ν* = 6.384`, from
  an experiment whose DEVELOPMENT result was **INVALID_NULL_CONTROL** — its
  observed-period report line reads NOT_SELECTED, but the experiment's status is
  INVALID_NULL_CONTROL — a well-specified forecast, explicitly not a validated
  one; see `docs/OPTIONS_PILOT_ARTIFACT_INVENTORY.md`). No `expected_move_pct` is
  manufactured. *(Wording corrected in OPTIONS-PILOT-001 r2; the earlier text said
  "a NOT_SELECTED experiment".)*
- **Expression comparison by expiration breakeven is withdrawn for the pilot.**
  Breakevens at expiry cannot say which 21+ DTE option best monetises a move
  before today's close. The pilot uses **one deterministic rule** with no
  "best option" or mispricing claim (`apex/options_pilot/expression_rule.py`).
  Horizon-consistent option valuation is a separate capability.
- **The seal check is weaker than §1 reported.** `simulate_entry` accepts any
  string of ≥ 32 characters; it does not establish that the hash belongs to a
  persisted, matching card. The session does append the card first, but the
  fill function proves nothing. The recording boundary therefore verifies the
  intent by **re-reading the ledger and recomputing its hash** and does not rely
  on `simulate_entry`'s check.
- **G2a (above):** freshness must be per selected contract and side.

## 5. Smallest proposed pilot specification

**Name:** `OPTIONS-PILOT-001`, authority `PAPER_EXPLORATORY` (already granted
2026-08-23; the maintenance block is a *launch* authorisation, separate).

**Purpose.** Establish a **complete, measurable learning loop** from a
timestamped forecast to an honestly simulated options decision and its
reconciled outcome. The pilot measures the **loop**, not edge. Success is
defined on loop integrity, not on P&L.

**What is fixed**

| | |
|---|---|
| universe | **SPY only** — one symbol; the forecasting work is on SPY, and one symbol keeps the sample discipline honest |
| forecast input | one sealed **forecast record per scan**: `known_from = T`, `direction` from the existing equity faculty (unchanged), `expected_move_pct` = the registered dispersion law `rv_30·s₀` scaled to the hold horizon (a *dispersion* forecast the pipeline already produces — **not** a validated directional edge; EXP-001B/002/004 passed none), and a `forecast_hash`. No new model is fitted |
| expressions | as registered: LONG_CALL / LONG_PUT / CALL_VERTICAL / PUT_VERTICAL / NO_TRADE, `CANDIDATE_RULES` unchanged, `contracts = 1`, hold to regular-session close (`OPTIONS_HOLD_TO_CLOSE`) |
| risk | `certify()` + `risk_kernel.check()` with the predeclared limits, both **before** the fill, both chained |
| fill | quoted sides, **re-quoted at T + 2 s**, quantity ≤ touch size, **fees added as a fourth identity term** (paper schedule declared in the registration) |
| freshness | option quote ≤ 15 s, bars ≤ 90 s, tz-aware; stale → sealed refusal. **Before setting the limit, measure the ThetaData snapshot cadence for one session and record it** — if the feed cannot deliver ≤ 15 s, the limit is set from the measurement and reported, not silently relaxed |
| labels | every card, fill and outcome stamped `PROSPECTIVE_PAPER` / `NONE_PAPER`; a test forbids the replay class in live records |
| reconciliation | simulated-fill reconciliation at session end, 1:1 by `card_hash`, orphans sealed |
| exits | exit-quote capture window (retry every 5 s from close − 120 s); `NOT_ESTIMABLE` never imputed |
| release | one pinned release commit; one supervised warm-up session on it, reviewed, before day 1 counts |
| duration | **10 sessions**, declared in advance; the pilot ends on the count |

**Success criteria (loop integrity, all required):**

1. 100% of attacks have a sealed forecast record and a sealed card **before** the fill (timestamps prove order).
2. 100% of outcomes reconcile 1:1 to a card; zero `UNRECONCILED`.
3. The four-term friction identity holds on every resolved outcome.
4. `NOT_ESTIMABLE` outcomes ≤ 5% of attacks.
5. Every refusal (stale, geometry, risk, kernel) is sealed with its reason; the scoreboard funnel sums to the scan count.
6. No live record carries a replay label.
7. Measured quote ages, re-quote slippage, fees and fill sizes are reported per session.

**What the pilot does not claim:** any edge, any tradability, any options
profitability. P&L is reported because the loop produces it; it is not a
criterion. Under the sample-independence law, ten sessions are at most ten
episodes.

**Estimation budget:** zero model fits. The only estimated quantity is the
ThetaData cadence measurement used to set the freshness limit.

**Sequence to authorise, each a separate gate:** (1) implement G0, G1, G4–G7
with tests → review; (2) measure feed cadence, set freshness, pin release →
review; (3) lift the maintenance block for **one** warm-up session → review;
(4) ten-session pilot → review.
