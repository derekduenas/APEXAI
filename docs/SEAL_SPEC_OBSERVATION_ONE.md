# Seal spec — observation one (OTM long single leg, paper)

Date: 2026-09-11. One page. States exactly what the sealed BEFORE record contains, what may only be written
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

## 2. Fields the directive requires that the boundary does not yet seal

| Field | Where it should live | Today | Change needed |
|---|---|---|---|
| **pre-registered options toll formula + hash** | `pilot_intent.expected_toll` | not a field | one record field. Formula (frozen text, hash below): `expected_toll_$ = 100 × [ (ask_fill − bid_fill)/2 + (ask_ref − bid_ref)/2 ] + fee_in + fee_out`, where `ref` is the same contract's chain quote at decision time and `fill` the executed quote. Realised toll = `100 × [(ask_fill − mid_fill) + (mid_exit − bid_exit)] + fees` from the sealed fill and exit quotes. The formula is hashed, not the numbers, so it cannot be reshaped after outcomes land. |
| **the six doctrine fields** (`capacity_suitability`, `giant_competition_risk`, `signal_half_life`, `our_expected_footprint`, `crowding`, `forced_participant_strength`) | `pilot_intent.doctrine` | not fields on the pilot record; each exists as a measurement contract elsewhere (`SMALL_CAPITAL_ADVANTAGE_DOCTRINE.md`) | one record field carrying each as `{value | "NOT_MEASURED", source}`. For observation one every one of the six will honestly read `NOT_MEASURED` except `our_expected_footprint` (1 contract vs quoted size, computable from the chain row). A field that says NOT_MEASURED is sealed; a missing field is not. |
| **`tail_asymmetry`** | `pilot_intent.doctrine.tail_asymmetry` | exists as a string field in `options_research/forward_distribution.py`, always `"UNKNOWN"` | same field; `"UNKNOWN"` sealed |
| **the full pin** | `pilot_intent.pins` | release id sealed; contract pin sealed only on funnel paths | one field: `{release, git_commit, expression_rule_version, exit_policy_hash, fee_schedule_id, risk_kernel_limits_hash, r4_contract_blob (if a funnel path), toll_formula_hash}` |

These are four record fields on one validator plus the doctrine stamp. They are capability under the freeze and
are **not built here**; the operator decides whether observation one waits for them or seals the formula by
reference to this document's hash.

**Toll formula hash** (sha256 of the exact formula line above, ASCII, no trailing space):
`TOLL_FORMULA_V1 = sha256("expected_toll_$ = 100 x [ (ask_fill - bid_fill)/2 + (ask_ref - bid_ref)/2 ] + fee_in + fee_out")`
= see `docs/evidence/toll_formula_v1.sha256` (written beside this document so the hash is a file, not a claim).

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
- The toll is a formula whose hash is sealed before the fill; the numbers that enter it come from entries sealed
  before the exit. Nothing computed after the exit is an input to anything sealed before it.
