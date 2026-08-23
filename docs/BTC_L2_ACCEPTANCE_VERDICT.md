# BTC L2 — FINAL ACCEPTANCE VERDICT

**Adjudicated:** 2026-08-23
**Verdict: PASS**
**Authority after this gate:** OBSERVE (unchanged). L2 confers no trading power.

---

## 1. The finish line, as pre-registered

Both floors were sealed into the ledger *before* the interval began, so
neither could be moved to fit the result.

| Criterion | Floor | Achieved | |
|---|---|---|---|
| Continuous fresh interval | ≥ 4.00 h | **4.01 h** | PASS |
| Reconciliations | ≥ 1000 | **1443** | PASS |
| Persistent divergences | 0 | **0** | PASS |
| Chain integrity | intact | **2,361 rows, 0 broken links, 0 bad hashes** | PASS |

Window: 2026-08-23 14:22:09 → 18:22:56 UTC. The interval ran on the Mac,
untouched, while all other work happened on the physically isolated
cloud host.

## 2. The two adjudicated defects are closed

**Defect A — stale snapshot regression.** The venue's periodic snapshots
frequently lag the applied book. v1 replaced state unconditionally, so a
lagging snapshot regressed the book and resurrected deleted levels.

The v2 stale-snapshot law reconciles against a lagging snapshot but
refuses to apply it. The scale of the problem in this window is the
point: **100% of persisted reconciliations (34 of 34) arrived stale
versus the applied book.** Under v1 every single one would have
regressed state. This was never a rare race; it is the venue's normal
behaviour, and v1 was wrong continuously rather than occasionally.

Seventeen divergences were raised during the interval. All seventeen
were resolved on the following snapshot and classified
`RECONCILIATION_RACE_CONFIRMED`. Zero persisted.

**Defect B — ledger append race.** Two intra-process writers (watchdog
and reader thread) could interleave and fork the hash chain, which is
what tainted generation 1. The repaired `chain_append` wraps the whole
read-prev / hash / write transaction in a thread lock plus an `flock`,
and fsyncs.

Under a live concurrent writer this interval appended **2,361 rows with
zero broken links and zero bad hashes**, verified by recomputing every
hash from genesis.

## 3. Lineage is provable, not asserted

Generation 1 was closed `FORENSIC_TAINTED_CONCURRENCY_DEFECT` and never
repaired — a repaired ledger is not evidence. It is preserved immutable
at `results/btc/forensic_2026-08-23/ws_book_ledger.jsonl`, and its
sha256 sealed in the g2 genesis row still matches the file on disk
today (`6f533f7924e063b3…`). The exclusion is auditable by anyone who
re-hashes the file.

## 4. What else the interval showed

One book invalidation fired, `CROSSED_OR_LOCKED_BOOK`. The engine
invalidated, resynced, and recovered; final book quality is `VALID`.
That is the guard working, not a failure — a crossed book is exactly
the state the engine must refuse to treat as tradeable.

## 5. Consequences

- **BTC L0–L2 are FROZEN.** Reopening requires a version bump plus
  regression acceptance against this interval.
- **BTC-L3 is AUTHORIZED_TO_BUILD.** It has not been started, and this
  verdict does not start it.
- Live capture continues under authority OBSERVE. Nothing here confers
  any decision power, and no economic claim is made or implied.

## 6. What this verdict is *not*

It says the book engine reconstructs the venue's book faithfully and the
ledger records that reconstruction tamper-evidently. It says nothing
about whether anything profitable can be done with that book. The L2
gate is an instrumentation gate. Confusing a passed instrumentation gate
for evidence of an edge is the error this ladder exists to prevent.
