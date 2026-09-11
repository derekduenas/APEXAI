# APEX Frontier Build — status

Mandate: `APEX_Frontier_Build_Mandate.md` (operator, 2026-09-11). This document is
the single build-status record; `docs/frontier_build_manifest.json` is its
machine-readable twin. **Self-review cannot set independent acceptance**: the
`ACCEPTED` state below is reserved for the independent reviewer, and the
operational states (`SHADOW_AUTHORIZED`, `DEPLOYED`) are reserved for the operator.

Scope expansion recorded: the mandate authorizes offline implementation,
isolated dependencies, synthetic qualification, documentation and reviewable
commits across M0–M6. It does not amend executed experiments (EXP-001B
NO_SIGNAL, EXP-002 INVALID_NULL_CONTROL, EXP-003 withdrawn, EXP-004
NOT_SELECTED), grant historical fitting/rescoring, open sealed data, create
admissions, change trust roots, lift the maintenance block, start services,
connect brokers or send orders.

Branch: `frontier-build` (worktree `~/apex-frontier-wt`), created from
`options-pilot-001` at `360536cb`. The authoritative host checkout stayed at
`360536cb` while this branch was built; nothing older was written over it.

| Milestone | State | Checkpoint | Evidence |
|---|---|---|---|
| M0 — four remaining recording defects | `SYNTHETIC_VERIFIED` (awaiting independent acceptance) | `360536cb` (r4) | `docs/OPTIONS_PILOT_RECORDING_BOUNDARY.md` §10; tests `test_r4_*` (boundary) and `test_f6_lifecycle_recovery_through_the_entry_point`; contained run at 360536cb: 92 pilot / 461 regression passed |
| M1 — execution accounting + operational paper loop | `SYNTHETIC_VERIFIED` | see manifest (`m1_commit`) | `apex/options_pilot/{fees,book,risk_authority,exit_policy}.py`; boundary/session/entrypoint integration; `tests/test_options_pilot_accounting.py` (14) + the 92 r4 tests updated for fees/exit policy; local run 106 passed |
| M2 — PULSE / Twin / inference adapters | `NOT_STARTED` | — | — |
| M3 — World Model workbench | `NOT_STARTED` | — | — |
| M4 — Multiverse + market-implied | `NOT_STARTED` | — | — |
| M5 — fusion, supervision, learning | `NOT_STARTED` | — | — |
| M6 — operator view + commissioning package | `NOT_STARTED` | — | — |

## M0 — closed at `360536cb` (reconciled against the mandate's four items)

1. Expiry after quote receipt, before fill commit → `pilot_intent_expired` + refusal; exclusivity with fills and
   cancellation under the transaction protocol (`_CommitRefused.terminal_kind` → `expire_intent` in its own
   transaction, which refuses if a finishing fill or terminal record exists). No unfinished-intent state remains
   (`test_r4_expiry_between_receipt_and_commit_persists_terminal`).
2. Missing/stale exit → numbered valuation attempts, `discharges_position=false`; the obligation survives restarts;
   prior failed attempts are never overwritten (`test_r4_missing_or_stale_exit_keeps_the_position_outstanding`,
   entry-point lifecycle test using the real provider returning `None` then a stale quote).
3. Late duplicate delivery → historical receipt reconciliation needs identity/provenance + full chain/reference
   verification only; forecast currency governs a NEW fill (`test_r4_late_duplicate_delivery_reconciles…`).
4. Complete 120-s cutoff freshness + future-target policy at intent creation and new-fill commit, including the
   130-s-old-inputs / fresh-quote case (`test_r4_forecast_freshness_is_rechecked_at_intent_and_at_commit`).

## M1 — what was built

- **Fees** (`fees.py`): `FeeSchedule` with id/version/provenance/verification record; `SYNTHETIC_FEES_V1`
  (labelled invented) and `UNVERIFIED` (unknown ≠ zero). Entry fee on the fill, exit fee on the discharging
  outcome, each exactly once; `recompute_fees` for the Book. `ExecutionPolicy V1`: 0.25 s simulated latency
  (freshness measured at the simulated execution instant), 3 fill attempts (first quote + 2 re-quotes) inside
  the intent TTL, fill quantity ∈ {0, 1}, displayed size is a constraint, every fill labelled SIMULATED.
- **Certified risk authority** (`risk_authority.py`): the real `risk_certificate.certify()` recomputed from legs
  `("BUY", right, strike, max_entry_price)` and the real `risk_kernel.check()` against Book inputs. Approval
  binds to intent identity + envelope + fee schedule; `accepts()` honours only its own provenance. The
  **envelope** (`RISK_ENVELOPE_V1`) reserves `min(indicative ask × 1.1, cap $5.00) × 100`; infeasible
  envelopes (indicative ask above the cap) refuse at intent time; the executable ask is rechecked against the
  envelope at fill (`ASK_ABOVE_ENVELOPE` → WAIT).
- **Atomic reservations**: the intent record IS the reservation; the kernel is re-run against the Book
  reconstructed from the snapshot INSIDE the intent's commit transaction (`RISK_LIMIT_AT_COMMIT`), so six
  barrier-released SPY intents reserve exactly two under the $600 same-underlying cap. Reservations convert to
  positions at the actual debit on fill, and are released by a terminal REFUSE attempt, expiry, cancellation or
  re-quote exhaustion — each an exactly-once record.
- **Book** (`book.py`): reconstructed from records only — reservations, positions, closed positions, cashflows,
  session/total realized P&L, outstanding obligations (unfinished intents, unresolved positions, exit-exhausted
  positions); primary-field recomputation of debits, fees and P&L with named integrity problems; cash identity.
- **Exit policy** (`exit_policy.py`, `EXIT_AT_HORIZON_15M_V1`, frozen): due at fill + 900 s; 120-s window;
  ≤5 attempts spaced 15 s; valuation failure keeps the obligation; exhaustion records `pilot_exit_exhausted`
  and the position REMAINS an obligation (P&L unknown); early valuation is refused (`EXIT_NOT_DUE`); recovery
  runs may attempt exhausted/late positions, labelled. Declared as a NEW policy distinct from the legacy
  hold-to-close protocol.
- **Session/entry point**: `attempt_exits` drives the policy deterministically (controlled clock "sleeps" by
  advancing); an unfilled intent of the closing session is cancelled at close (terminal record, exclusive with
  fills); the close record carries the Book summary, cancelled intents, exhausted exits and failed valuation
  attempts; the report carries book, fee schedule, exit and execution policies.
- **Production route**: `ProductionSources` uses the certified authority with the UNVERIFIED fee schedule and
  LIVE_FEED provenance, so every intent is refused `FEE_SCHEDULE_UNVERIFIED` until a provider schedule is
  verified and recorded. The forecast provider is still `NO_REVIEWED_INFERENCE_ADAPTER` (M2).

## Known limitations carried forward

- Kernel limits are the organism's predeclared PAPER limits ($500/trade). SPY ATM 21-DTE options usually
  price above $5.00, so the current pilot rule will refuse most SPY ATM intents as `RISK_ENVELOPE_INFEASIBLE`.
  This is a commissioning decision (strike rule, underlying, or an operator-approved limit change), not a
  software default to be tuned here.
- Fees: no provider schedule verified; production refuses. Verification is an operator task (M6 package).
- Multi-contract and spread support (integer partial fills, legging, assignment) is out of scope for the pilot.
