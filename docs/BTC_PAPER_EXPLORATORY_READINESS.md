# BTC PREDATOR — READY_FOR_PAPER_EXPLORATORY_REVIEW

**Date:** 2026-08-24
**Requested authority:** `OBSERVE` → `PAPER_EXPLORATORY`
**Status: SUBMITTED FOR AUTHORITY REVIEW. Not promoted. Not
self-promoted.**

The question `PAPER_EXPLORATORY` asks: *do we trust the plumbing enough
to simulate attacks and learn from them?* Everything below is offered
against that question and no other.

---

## 1. The complete rung ladder

| rung | state | tests |
|---|---|---|
| L0–L2 book/lineage/ledger | **PASS, FROZEN** (2026-08-23) | 45+ |
| Participant state | built — identification law enforced | 23 |
| Forced-action thesis | built — falsifiers mandatory | 17 |
| Attack geometry | built — both dimensions veto | 21 |
| Paper execution + resolver | built — options-proven laws | 17 |
| Composed session driver | built — ran on real capture | — |

## 2. The composed path ran on real data

`scripts/btc_paper_session.py` composed the full path — derivatives
ledger → Inputs → participant state → forced-action thesis → attack
geometry → sealed card → paper fill → resolution — over **13.1 hours of
real captured market state** (2,870 L2 book tops, 9,289 Deribit polls,
2026-08-23 14:22 → 08-24 03:27 UTC).

Result: 51 decision windows, **50 `NONE_OBSERVED`, 1
`SUSCEPTIBLE_NOT_TRIGGERED`, 0 attacks.** That is the correct reading
of a quiet Sunday BTC session, and a session of honest refusals proves
the plumbing exactly as well as attacks would. The paper ledger chain
verifies intact (53 rows), and the output artifact carries provenance
verifiable under the artifact law (`commit 88ae4d2`,
`digest f4a707a4…`).

The attack-and-resolve path itself is proven by tests, including the
cases that flatter paper systems when omitted:

- a **gap through invalidation** resolves at the bid actually
  available, not the level we wished for (−3.7R recorded, not −1R);
- **ambiguous observations resolve against us** — one book top showing
  both target and invalidation touched takes the invalidation;
- **invalid books are skipped, never traded** — panic prints from an
  INVALID book cannot resolve anything;
- a **flat market still loses both half-spreads**, and the friction
  identity `pnl = mid_change − entry_friction − exit_friction` holds
  exactly on every resolved outcome;
- fill size is **capped by resting touch liquidity** — a fill larger
  than the book is fiction.

## 3. The cross-venue proxy, declared not smuggled

Bitnomial — the attack venue, where the commissioned L2 book lives —
publishes open interest **daily**. The participant stack correctly
refuses daily OI for intraday claims, so thesis inputs come from
Deribit, whose OI is measured `OI_REALTIME`. This is stamped into the
protocol and every record as a **named proxy**: Deribit positioning
describes Deribit participants, used as a proxy for the BTC leveraged
complex. Presenting it as Bitnomial positioning would be exactly the
identification error L3 exists to refuse.

## 4. What the sleeve refuses, structurally

- Mid-cascade entry (a latency race against liquidation engines).
- Any attack without an invalidation level.
- Any thesis its inputs cannot carry (`NOT_ESTIMABLE`, never a quieter
  version of the same claim).
- Any reading stated as fact: every supported interpretation carries
  competing explanations, and a test fails one that does not.
- Any calibrated probability: `calibration: NONE_FITTED` until a
  governed process fits one against prospective outcomes.

## 5. What is explicitly NOT claimed

- No edge. Zero prospective attack outcomes exist; the one tradeable
  moment the sleeve knows (`PATIENT_LIQUIDITY_INTO_EXHAUSTION`) is
  stamped unproven.
- No learned threshold anywhere; every rule is classified structural
  or exploratory-prior.
- The 13-hour run is a plumbing proof over ~13 hours of one quiet
  weekend session — `n_effective` is 1 session, and it says nothing
  about behaviour in a volatile regime.

## 6. The ask

Promote the BTC Predator to `PAPER_EXPLORATORY` so the composed loop
may run continuously and accumulate sealed prospective decisions —
including, most valuably, its refusals. Known limitation for the
review: forced-flow signatures are rare by nature, so productive
evidence will accumulate slowly and mostly through the
`SUSCEPTIBLE`/`NEAR_MISS` cohorts until a real deleveraging event
occurs. That is the honest shape of this hunt.

**This report promotes nothing. Authority review is required.**
