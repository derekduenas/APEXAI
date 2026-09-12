# Seal spec — observation one (OTM long single leg, paper)

Date: 2026-09-11; corrected 2026-09-12 (decision-path review, finding 6: the intent-time toll formula referenced a
later fill quote, and the ordering statement omitted that indicative quotes exist before the forecast/funnel/intent). One page. States exactly what the sealed BEFORE record contains, what may only be written
after, and why outcomes cannot modify the BEFORE record. Every field below is either already produced by the
recording boundary today (marked ✓) or is named as pending with the change it needs.

## 1. The BEFORE record is three hash-chained entries, in this order, on disk before any quote is fetched

| Entry | Sealed content | Status |
|---|---|---|
| `pilot_forecast` | symbol, target, units, horizon 15 min, family, location, scale, ν, `model_id`, `model_hash`, `params_hash`, `artifact_digest`; the five input epochs (reference, target_end, input_event, input_available, input_cutoff, created); `direction_signal` (heuristic label) and its meaning; `validation_status`; `drives_expression_selection: false`; `horizon_relationship`; session and scan ids; provenance labels | ✓ |
| `pilot_intent` | expression `LONG_CALL`/`LONG_PUT`, action BUY, contract (symbol, expiration, strike, right), `contract_id`, quantity 1; `signal_used`; **`expression_rule` = `PILOT_RULE_V2` id string** and **`strike_selection`** (rule, spot, strike, distance $, distance %, strikes from ATM, cap, census, what-V1-could-not-express); `reference_ask` (indicative, chain snapshot); `risk_envelope` (`max_entry_price`, basis, policy id); `fees` (schedule id + provenance); `execution_policy`; `forecast_ref` (seq, entry_hash, forecast_hash, forecast_id); created/expiry epochs, TTL 120 s; certified risk decision (`CERTIFIED_KERNEL` provenance, authority id, `certified_max_loss`, kernel check) | ✓ |
| `pilot_funnel` (funnel paths only) | FUNNEL_TRACE_V2, contract pin, engine describe | ✓ when a funnel policy is selected; not on the V2 rule path |

Also sealed in the BEFORE record, by reference: the release id, session id, exit policy id and its hash
(`EXIT_AT_HORIZON_15M_V1`: due = fill + 900 s, window 120 s, ≤ 5 attempts, exhaustion keeps the obligation), and
the boundary's provenance labels (`LIVE_FEED`, `PROSPECTIVE_ORCHESTRATION`).

**The quote and its age** are sealed in the `pilot_fill` entry, which is written after the intent and before any
outcome: bid, ask, bid_size, ask_size, provider timestamp, receipt clock, measured age of the crossed side at the
simulated execution instant, the fill price, and the canonical proposal digest re-checked against the intent.
A fill is part of BEFORE with respect to the outcome, and AFTER with respect to the intent. It cannot change the
intent: the intent's `entry_hash` is already in the chain and the fill carries `intent_ref` to it.

## 2. Ordering, corrected

Actual session order (`apex/options_pilot/session.py`): **indicative chain quotes exist first** (the chain snapshot
the rule selects from, each row carrying its own provider timestamp) → `pilot_forecast` persisted → (funnel paths
only) `pilot_funnel` persisted → `pilot_intent` persisted, sealing the indicative reference quote it was selected on
→ fresh executable quote fetched → `pilot_fill` persisted → exit window → `pilot_outcome`. Three cost quantities
are therefore distinct and are sealed at three different times:

| Quantity | Time | Inputs | Where sealed |
|---|---|---|---|
| **intent-time expected toll** (`TOLL_FORMULA_V1`) | before any executable quote | the indicative reference quote's bid/ask + the fee schedule | `pilot_intent.expected_toll` |
| **post-requote entry cost update** | after the fresh executable quote is received, in the same committed record as the fill decision | the executable quote | `pilot_fill.entry_cost_update` (references the intent's estimate; never rewrites it) |
| **realised exit accounting** | inside the exit window | the sealed fill and exit quotes | `pilot_outcome` |

`TOLL_FORMULA_V1` (text hashed in `apex/options_pilot/records.py`, hash sealed in every intent's `pins`):

```
expected_toll_$ = 100 x (ask_ref - bid_ref) + fee_in + fee_out
```

with `ask_ref`/`bid_ref` the indicative quote the selection was made on and the exit half-spread **assumed** equal
to the entry half-spread. That assumption is declared, not estimated, and is the one unresolved estimator choice:
see the amendment proposal below. If the fee schedule is unknown the field reads `NOT_ESTIMABLE` with the reason;
nothing is fabricated.

## 2a. BEFORE fields now implemented (2026-09-12)

| Field | Content | State on observation one |
|---|---|---|
| `expected_toll` | formula id, formula hash, inputs, value or `NOT_ESTIMABLE` | `NOT_ESTIMABLE` on the live boundary until the fee schedule is verified; estimated on synthetic |
| `doctrine.fields` | the six doctrine fields, each `{value, source}`; `tail_asymmetry` | five read `NOT_MEASURED` with the reason; `our_expected_footprint` = 1 / indicative ask size; `tail_asymmetry` = `UNKNOWN` |
| `pins` | release, expression rule id, exit policy id + hash, execution policy hash, fee schedule id + hash, risk authority id, toll formula id + hash, contract pin (funnel paths) | complete; `git_commit` reads "not available in process" honestly, the release id is the deployment pin |
| `reference_quote` | the indicative quote (bid, ask, sizes, timestamp) the selection used | sealed |
| `strike_selection` | rule version, spot, strike, distance, census, exclusions (selector and provider) | sealed |

**Amendment proposal for review, not applied:** replace the equal-half-spread assumption with the session's
observed exit-spread distribution once `docs/CLOCK_START_ROUTE1_READINESS.md` §6 has ≥ 20 sessions; until then
the assumption stands and is labelled.

## 3. What may only be written AFTER

| Entry | Written when | Content |
|---|---|---|
| `pilot_fill` | after the intent is on disk, at most once per intent | the executed quote and price, or `UNFILLED` / `WAIT` with the reason (stale, mismatch, envelope) |
| `pilot_outcome` | inside the exit window, or on recovery | the exit quote(s), realised P&L, or `EXIT_WINDOW_EXHAUSTED` with the obligation still open |
| `pilot_decision` | end of every scan | TRADE / WAIT / REFUSE with ids of every entry above |
| resolution and scoring | later, from the sealed entries only | expected vs realised toll; direction vs outcome |

## 4. Why outcomes cannot modify the BEFORE record

- Every entry is appended to a hash chain with `prev_hash` and `entry_hash` over its canonical JSON; a later entry
  references earlier ones by `(seq, entry_hash)`. Changing a byte of the intent changes its hash and breaks every
  reference to it. `verify_chain` runs at session open and on recovery.
- The ledger is append-only and fsynced; there is no update path in `apex/options_pilot/ledger.py`.
- The fill re-derives the canonical proposal from the intent and refuses on mismatch (`proposal_digest`), so an
  outcome cannot be attached to a reshaped intent.
- The intent-time toll is a formula whose hash is sealed in the intent; its inputs are the indicative quote sealed in
  the same record. The fill's cost update is a separate field on a later record and carries a reference to the
  intent's value. Nothing computed after a record is an input to that record.
