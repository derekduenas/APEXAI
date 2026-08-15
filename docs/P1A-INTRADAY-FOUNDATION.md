# P1A — Intraday Data Foundation + Replay Kernel (deliverables 1–8, 12)

Date: 2026-08-15. **STATUS: KERNEL BUILT AND COUNTEREXAMPLED; P1A IS
NOT CERTIFIED** — acceptance gates B (certification sample) and J
(cross-source reconciliation) are BLOCKED_EXTERNAL on the Massive
subscription, an operator act (with the individual/non-professional
licensing check the operator flagged). No gate is claimed passed that
requires vendor data.

## 1. Data architecture

Two tiers, frozen: Tier 1 = whole-market 1-minute vendor-UNADJUSTED
aggregates (the replay substrate, history to 2003-09); Tier 2 = on-demand
NBBO/trade slices for serious candidates only — never bulk history (the
quote files run to TB/year; the minute files do not). Raw is immutable and
content-addressed; every partition carries a `PartitionManifest` and is not
replay-eligible until VALIDATED (enforced, tested). Symbols stored as they
existed at the time; APEX applies its own corporate-action interpretation
downstream.

## 2. Provider contract

`IntradayProvider` (get_bars / get_reference_state / get_corporate_actions /
get_quotes / get_trades / availability) is provider-neutral; Massive is
adapter V1 and **fails closed with remediation while unwired** — it never
returns an empty frame, because a fabricated "no market" is worse than an
error. Databento is a future second adapter behind the same interface.

## 3. Identity mapping

`SecurityIdentityMap` windows (provider symbol × [valid_from, valid_to) →
apex_security_id, with CIK/FIGI/permaticker external ids, method,
confidence, evidence). Proven: a recycled ticker resolves to different
issuers across time; the dead zone between issuers refuses; overlapping
windows are AMBIGUOUS and refuse; permaticker disagreements with the
existing Sharadar identity layer are FINDINGS, never auto-resolved.

## 4. Corporate actions

Three price meanings, never interchangeable, all tested: RAW (immutable
prints), TRADABLE_PRICE_AT_T (what the agent saw — the day before a 2:1
split executes, it saw 104, not 52), ANALYTICAL_NORMALIZED (continuity
series that REFUSES to exist unless the caller declares
`retrospective_use_declared=True` — the marking is structural, not a
comment). The split-as-crash counterexample passes in both directions.

## 5. Replay semantics

`ReplayClock`: a minute bar stamped T covers [T, T+1m) and is visible from
T+1m — at T+59s it refuses with "NO LOOKAHEAD THROUGH BAR CONSTRUCTION";
the clock never runs backwards. `replay_events`: typed events
(SESSION_STATE / BAR_AVAILABLE / …) in visibility order, streamed one
day-partition at a time via generators — nothing concatenates history
(the OOM lesson, designed in). Missing minutes yield NOTHING (absence is
data); duplicate (symbol, minute) rows raise; `stream_hash` binds the
event stream to (dataset fingerprint, adapter version, config hash) — same
inputs, same hash; different provenance, different hash. All tested.

## 6. Certification sample — SPECIFIED, awaiting data

Frozen composition on subscription: dates from 2006 / 2008 / 2012 / 2020 /
2024 / 2026 covering high+low liquidity, forward+reverse splits, a ticker
change, a delisting, an acquisition, an ETF, missing-minute behavior,
pre/post-market, extreme volatility, one early close, one DST boundary,
and several Sharadar-reconcilable APEX securities. Engineering only; no
forward-return inspection.

## 7. Cross-source reconciliation — SPECIFIED, awaiting data

Daily OHLCV derived from intraday bars vs the trusted Sharadar daily lake
per certification security/date; documented expected differences and
tolerances; catastrophic-mismatch detection; the comparison never silently
prefers the prettier vendor.

## 8. Failure modes (implemented + tested now)

DataQuality with UNKNOWN as a valid state; AMBIGUOUS_IDENTITY / STALE /
CORPORATE_ACTION_UNRESOLVED / PROVIDER_ERROR fail closed; unvalidated
partitions are replay-ineligible; the broker is unreachable from replay
(source-scan test); the unwired adapter refuses with the operator
remediation.

## 12. Unresolved external-data limitations

Massive subscription + MASSIVE_API_KEY (operator; Sharadar key hygiene
applies identically). Auction imbalance, timestamped news, options chains:
separate later feeds. Session calendar: fixture-grade holiday/early-close
seeds must be replaced by the vendor calendar at first ingestion — marked
in code.
