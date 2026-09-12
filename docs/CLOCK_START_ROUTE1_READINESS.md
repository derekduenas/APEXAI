# Clock Start Block, items 5 and 6 — route 1 readiness and the exit-spread collection spec

Date: 2026-09-11. Readiness list and arithmetic only. Nothing here was built, activated or ordered.

Operator decision on record: **route 1** (long OTM single call/put, existing certificate and vocabulary untouched),
verticals deferred until exit-spread data earns the certificate amendment, route 2 refused.

## 5. What stands between today and the first sealed paper observation

### 5.1 Does the boundary, the certificate and the exit rule admit an OTM long single leg today, unchanged?

| Layer | Source | Admits an OTM long single? | Proof |
|---|---|---|---|
| Boundary vocabulary | `apex/options_pilot/records.py:267` | **Yes.** `LONG_CALL` / `LONG_PUT`, `BUY`, quantity 1. No strike or moneyness condition anywhere in `validate_intent` or `validate_contract`. | read of the function; the only contract checks are symbol, expiration, right, positive strike |
| Risk certificate | `apex/organism/risk_certificate.py` `LONG_OPTION_BASIS` | **Yes.** A long single option is `DEFINED_MAX_LOSS` at the debit "under any exit rule". Strike is not an input to the bound. | the certificate refuses only `VERTICAL` expressions and unboundable instruments |
| Risk envelope | `apex/options_pilot/risk_authority.py:41-48` | **Yes, for asks ≤ 5.00.** `max_entry_price = min(reference_ask × 1.10, 500/100)`. | today's nearest feasible call K=773 ask 4.63; put K=749 ask 4.88 |
| Exit rule | `apex/options_pilot/exit_policy.py` `EXIT_AT_HORIZON_15M_V1` | **Yes.** Sell at an observed executable bid in [fill+900 s, fill+1020 s], ≤ 5 attempts. A long single sells at a bid ≥ 0, so the debit stays the ceiling. | policy text; note the pilot's exit is **15 minutes after fill, not session close** (see contradictions) |
| **Strike selection** | `apex/options_pilot/expression_rule.py` `PILOT_RULE_V1` | **No.** The frozen rule picks the strike **nearest to spot**. Today that is K=764, ask 9.20, which the envelope refuses (`RISK_ENVELOPE_INFEASIBLE`). The rule never looks at the next strike. | rule text: "strike: nearest to spot (ties -> lower strike)" |
| Strike selection, funnel path | `apex/decision_wb/engine.py` `FULL_FUNNEL_V1`, `strikes_each_side=4` | **No, at the default width.** The candidate set is ATM ± 4 strikes (760–768); the nearest feasible call today is 9 strikes out. Every candidate fails the envelope and the funnel returns WAIT. The width is a constructor parameter, not exposed on the CLI. | `engine.py:274`; `scripts/options_paper_session.py` exposes `--pilot-selection-policy` only |

**Conclusion.** Everything that judges an OTM long single leg admits it unchanged. Nothing that *chooses* a strike
can reach one. "Route 1 requires zero change to any rule" is false by exactly one line: the strike rule. The
smallest honest change is a new versioned expression rule (`PILOT_RULE_V2`: nearest strike whose indicative ask
≤ the envelope cap, on the signal's side of spot) or, on the funnel path, widening `strikes_each_side` to cover
the feasible band (≥ 9 today, and the width should be set from the cap, not hard-coded). Either is a reviewed rule
change and new capability under the standing freeze; **it is the operator's call which, and this document builds
neither.** Note that the commissioning package already named this fork on 2026-09-10 (its §2 item 2, option b).

### 5.2 What data must be flowing, and is the collector the only blocker?

The collector is **not** the only blocker, and it is not a blocker for the pilot process at all: the pilot does not
read the collection. The pilot's live sources (`apex/pulse_options/sources.py` `live_twin_sources`) need:

| Input | Live path today | State |
|---|---|---|
| 1-minute bars (forecast features) | Alpaca data v2 via `AlpacaBarsAdapter`, gated by `LiveGate` | adapter exists and served the collector this morning; needs `APEX_PILOT_LIVE_DATA=ENABLED` + credentials for the pilot process |
| Underlying NBBO (spot, book) | Alpaca via `alpaca.nbbo` | same; the collector's HTTP 504 stop shows this endpoint fails without retry (three consecutive → stop) |
| Option chain (strike/expiry set, indicative asks) | `chain_fn` **raises `CHAIN_ADAPTER_NOT_COMMISSIONED`** | the parsing exists and the collector used it (`option_expirations`, `option_chain_snapshot` from the options fabric), but the pilot's `chain_fn` is still a stub that refuses |
| Option quote at fill and at exit | `quote_fn` **raises `QUOTE_ADAPTER_NOT_COMMISSIONED`** | same: a per-contract NBBO adapter exists in the fabric, the pilot stub refuses |
| Fee schedule | `UNVERIFIED_FEES` | the certified authority **refuses every LIVE_FEED intent** until a `FeeSchedule` with `provenance=PROVIDER_VERIFIED` and `verified_against={provider, document, date}` is committed (`risk_authority.py:102`) |

So the data blockers are three wiring facts inside the pilot (chain_fn, quote_fn, fee schedule), not the
collector. The collector matters for a different reason: it is the only thing producing the multi-session
exit-spread record that route 3 needs (§6), and it is stopped.

### 5.3 What the seal must contain

Everything below except the last row is **already sealed** by the boundary today, per the record validators:

| Sealed field | Where it lives today | Purpose in the first observations |
|---|---|---|
| forecast record (distribution, direction_signal, artifact hash, feature receipts) | `pilot_forecast` | the signal under test |
| intent (expression, contract, quantity 1, `reference_ask`, risk_envelope, fee schedule, execution_policy, TTL) | `pilot_intent`, bound to the forecast by hash | what was decided, before any fill |
| fill quote (bid, ask, bid_size, ask_size, provider timestamp, receipt clock) | `validate_quote` → fill record | entry side of the toll |
| exit quote(s) within the policy window (same shape) | outcome record | exit side of the toll |
| risk decision with `CERTIFIED_KERNEL` provenance | intent/fill binding | proves the bound was certified, not self-attested |
| **pre-registered expected toll** | **not a field today** | the toll model under test |

**On the "Layer A executable toll model".** Layer A is the *equities* observed-SIP-NBBO round-trip surface
(`scripts/h5_friction_fidelity.py`, the single-name friction layer). No options toll model exists in the
repository, and the certificate's own `FEE_TREATMENT` says options fees are `NOT_RECORDED_IN_ANY_APEX_ARTIFACT`.
The honest options analogue is fully determined by fields the seal already carries, so it can be **pre-registered
as a formula now, with no code**, and evaluated from sealed data afterwards:

```
expected_toll_$ = 100 × [ (ask_fill − bid_fill)/2 + (ask_exit_ref − bid_exit_ref)/2 ] + fee_in + fee_out
```

where the exit half-spread is taken from the *same contract's* quote at decision time (the only exit-spread
information available before the fill), and the realised toll is `100 × [(ask_fill − mid_fill) + (mid_exit − bid_exit)] + fees`
from the sealed fill and exit quotes. The first observations then score the toll formula (expected vs realised) and
the signal (direction vs outcome) from the same records. Today's held data prices that formula for the nearest
feasible call: spread 0.01–0.08 across 166 snapshots (median 0.04), so an expected toll of about **$4 + fees** per
round trip against a $463 debit. Adding an `expected_toll` field to the intent record so it is sealed *inside* the
record rather than derived from it is a one-line record change; it is capability under the freeze and is listed
below as an operator choice, not done.

### 5.4 Operator actions required, in order

| # | Action | Who | Unblocks |
|---|---|---|---|
| 1 | Decide the strike rule: `PILOT_RULE_V2` (nearest feasible on the signal side) **or** funnel width from the cap. Authorize that one reviewed change. | operator | the only reason every SPY scan ends in WAIT |
| 2 | Supply the fee document (broker + OCC/regulatory per-contract) and authorize the committed `PROVIDER_VERIFIED` `FeeSchedule`. | operator supplies; builder commits under review | the certified authority's refusal of every LIVE_FEED intent |
| 3 | Authorize wiring the pilot's `chain_fn` / `quote_fn` to the options-fabric adapters the collector already uses (the commissioning package's §2 item 3, "HTTP client wired in the same reviewed change"). | operator | strike selection and fills from live quotes |
| 4 | Decide whether `expected_toll` is sealed as a field (record change) or pre-registered as the formula above (no change). | operator | the toll test being in-band vs derived |
| 5 | Lift the maintenance block, pin a release containing 1–3, enable `APEX_PILOT_LIVE_DATA` for the pilot process only, authorize paper capital. | operator | the first live scan |
| 6 | Restart the collector (with or without the retry/backoff change, which is a separate operational decision). | operator | §6 data; not required for the first observation |

Nothing on this list is a research task. Items 1–3 are each one reviewed change of a few lines; items 4–6 are
sentences.

## 6. Exit-spread collection spec (to earn route 3)

**What the certificate needs.** Its objection to verticals is that the buy-back cost of the short leg, two
bid/ask spreads, is "not knowable from state available at decision time". To replace "not knowable" with "modelled
with a declared distribution", the record must show the distribution of the *close-out gap*

```
gap = debit_at_entry − closeout_at_exit
    = (ask_long − bid_short)_entry − (bid_long − ask_short)_exit
```

across sessions, times of day and volatility states, and its dependence on the state the engine already forecasts
(spread state `x_sp`, size `x_sz`).

**What one session already shows** (today's 166 SPY chain snapshots, 09:30–12:15 ET, ATM 5-wide call vertical,
read-only, no credits):

| Quantity | min | median | p90 | max |
|---|---|---|---|---|
| debit ($/share) | 2.72 | 2.78 | 2.83 | 2.87 |
| close-out gap, immediate ($/share) | 0.06 | 0.09 | 0.11 | 0.17 |
| gap as % of debit | 2.1 | 3.2 | 3.9 | 5.9 |
| ATM call spread | 0.03 | 0.05 | 0.06 | 0.09 |

The largest gap was at the open (0.17, 5.9 %); by late morning it sat at 0.06–0.09. That is the shape the
certificate would need to see many times, not once, and it is the *immediate* gap; the 15-minute-later gap
(entry at t, exit quotes at t+15 min) is the one that matters and is also computable from the same file.

**Per session, capture:**

| Field | Cadence | Source | Already collected? |
|---|---|---|---|
| Full near-expiry chain, both sides, sizes, provider timestamp | every 60 s, 09:30–16:00 ET | ThetaData (existing subscription) | yes, but the collector stopped at 12:15 today and covers one session |
| Underlying NBBO | every 15 s | Alpaca SIP (existing data keys) | yes |
| Session tags: date, VIX open (from the chain itself via ATM IV), early-close flag, event-day flag | once | derived | no, trivial |

From each session, the derived table is: for every snapshot t with a snapshot at t+15 min, for the ATM and ±1
strike anchors and widths {1, 2, 5}: debit(t), closeout(t+15), gap, gap/debit, the spread state at t. That is
about 150 rows per session per (anchor, width) cell, heavily autocorrelated within the session, so **the unit of
evidence is the session, not the row** (the same CR1 clustering the R4 contract already uses).

**Vendor cost.** Zero marginal: ThetaData and Alpaca are existing subscriptions, the collector already runs under
`MemoryMax=1400M` in the research slice, and today's session cost 33 MB on disk (12.3 MB for the SPY chain). Twenty
sessions ≈ 0.7 GB. The only cost is the collector's retry/backoff defect, which ends a session on three
consecutive provider failures.

**How many sessions before an amendment is evidence-backed rather than asserted.** The certificate needs a
*bound*, not a mean, so the target is a high quantile of the gap with a stated coverage claim. With sessions as
the unit and no distributional assumption, the one-sided 95 % upper tolerance statement "the session-level p95 gap
is below X" needs at least 20 sessions for X to be the observed maximum with 64 % confidence and 59 sessions for
95 % confidence (the standard order-statistic count: n ≥ log(0.05)/log(0.95) = 59). The R4 contract's own
reporting floor is 20 independent sessions. So: **20 sessions is the floor at which a declared bound stops being a
guess; 60 sessions is where it carries a 95 % statement**, and both must include at least a few high-vol days or
the bound is a calm-market bound. At one session per market day that is 4 to 12 weeks from the day the collector
restarts. It cannot start accruing until it does.

Nothing above recommends amending the certificate. It says what the amendment would have to show.
