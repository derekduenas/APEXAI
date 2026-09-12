# SYSTEM_VALIDATION_STATUS — the honest coverage map (2026-09-12)

Every layer on the decision path. **EXERCISED ON REAL DATA** means it has run against recorded or live market data
at least once. **SYNTHETIC ONLY** means it has only ever run against fixtures. **NEVER EXECUTED** means no run of any
kind has reached it. Simulated fills are not a disqualifier; fixture inputs are.

## The decision path

| Layer | Status | Evidence / what blocks it |
|---|---|---|
| Bar ingest (`BarStore`, `load_bars`) | **REAL** | 5,339 bars incl. 5,170 prior-session bars, funnel first run |
| Snapshot compose (`pulse_options.snapshot`) | **REAL** | every trace-replay and census scan |
| Features (`ret_1/5/15`, `rv_30`) | **REAL** | refused correctly during warm-up; produced after |
| **Signal (`HEURISTIC_DIRECTION_V1`)** | **REAL** | sign of `ret_15`. **It is a placeholder, not a signal** — `SIGNAL_STATUS_001.md` |
| Forecast artefact (`EXP002_L`) | **REAL** | recorded on every forecast; `drives_expression_selection: false` |
| Event snapshot + `EVENT_GATE_V0` | **SYNTHETIC ONLY** | 13 fixture tests. Blocked on: no catalyst cycle has succeeded on the host (Mac cycle 2026-08-26 failed 8/8 on SSL). One successful cycle would move it |
| Chain normalization + `DUPLICATE_POLICY_V1` | **REAL** | 166 snapshots × 331 rows; **no malformed or conflicting row has ever been observed in real data** — the refusals themselves are synthetic-only |
| `PILOT_RULE_V2` strike selection | **REAL** | 166/166 scans both directions |
| **Funnel `FULL_FUNNEL_V1`** | **REAL, as of today** | first execution ever, 2026-09-12. **Constructs 18 candidates, 0 survive the envelope, 0 reach PRIME** — `FUNNEL_FIRST_RUN_RESULT.md` |
| Variance fit (GARCH-t / EWMA) | **REAL, as of today** | `READY` on 12/12 scans with 5,170 prior bars; never fitted on real data before today |
| Causal regime filter | **REAL, as of today** | ran inside the funnel; its output never reached a decision because no candidate survived |
| Conditional simulator (2,000 paths) | **REAL, as of today** | ran; its P&L paths were never compared because no candidate survived |
| Expression war (`multiverse_wb.expression_war`) | **REAL, as of today** | reached; every candidate rejected by the envelope before comparison |
| **PRIME supervision** | **SYNTHETIC ONLY** | never reached on real data on any path. Rule path does not consult it by design; funnel path never got past the envelope. Blocked on: a funnel candidate surviving the envelope |
| **Joint engine `JOINT_FUNNEL_V1` (R4)** | **NEVER EXECUTED** | no authorized fit exists (R4-FIT-001/002 not granted) and the constructor refuses without one. To run once: an operator grant plus a fit on authorized data |
| Risk envelope (`RISK_ENVELOPE_V1`) | **REAL** | fires on every ATM candidate; is the reason the funnel produces nothing |
| Risk certificate (`certify`) | **REAL** | `DEFINED_MAX_LOSS`, cert hash sealed, trace replay |
| Risk kernel (`check`, limits, reservations) | **REAL** | approved at commit with `SUM_OF_VERIFIED_CERTIFIED_MAX_LOSS` |
| Kernel **drawdown halt** | **SYNTHETIC ONLY** | never triggered on real data. Blocked on: a real session with realised losses reaching the halt |
| Kernel **aggregate / same-underlying / family caps** | **SYNTHETIC ONLY** | never bound on real data (only one position has ever existed) |
| Fee schedule + decimal arithmetic | **REAL** | priced the trace-replay trade; published-schedule tests are synthetic |
| Intent validation + canonical binding | **REAL** | trace replay, reconstructed byte-for-byte |
| Fill path (simulated) | **REAL quote, SIMULATED fill** | no order placement code exists anywhere |
| Exit policy `EXIT_AT_HORIZON_15M_V1` | **REAL** | attempt 1 refused on a stale bid, attempt 2 resolved |
| Exit **window exhaustion** (5 attempts) | **SYNTHETIC ONLY** | never exhausted on real data |
| Book reconciliation | **REAL** | 1 closed position, integrity problems `[]` |
| Ledger chain + receipts | **REAL** | 61 records, chain verified, every hash recomputed |
| **Recovery: restart with an open position** | **SYNTHETIC ONLY** | rehearsed on fixtures. Blocked on: a real session interrupted with a position open |
| **Recovery: cross-release** | **SYNTHETIC ONLY, and BROKEN** | `FINDING_RELEASE_CHANGE_STRANDS_POSITION.md` — **OPEN**, blocks deploy/rollback while a position exists |
| Duplicate-delivery reconciliation | **SYNTHETIC ONLY** | fixture-rehearsed |
| Scoring / attribution (`experience.py`) | **NEVER EXECUTED on a real outcome** | one real outcome exists (the replay trade) and it was never scored. Blocked on: nothing — it could be run on that outcome today |
| Calibration / reality loop | **REAL** | but on the equities producer set, not the options path |
| Live bars/NBBO HTTP client | **REAL** | endpoints OK under `HTTP_POLICY_V1`, weekend smoke |
| Live chain/quote client | **REAL, via the collector** | the pilot's own `chain_fn` has never fetched: forecast refuses first on a closed market |
| Order placement | **DOES NOT EXIST** | structurally absent and defended by `assert_no_placement_surface` |

## Never executed, and what one run would take

| Layer | Blocked on | To run once |
|---|---|---|
| Joint engine (R4) | no authorized fit | an `R4-FIT-001`/`002` grant, then a fit on authorized data; the engine and its 70 tests exist |
| PRIME on real data | no funnel candidate survives the envelope | a candidate rule that reaches the cap-feasible band (reviewed change), or a cap change (operator) |
| Kernel drawdown halt, aggregate caps | only one position has ever existed | multiple live sessions, or a deliberate fixture at real scale |
| Scoring on a real outcome | nothing | run `experience.py` against the one real outcome in the quarantined replay ledger |
| Event stream on real data | no successful catalyst cycle on the host | one cycle; the Mac's failure was an SSL trust store |

## The honest summary

Eleven layers have now touched real data, six of them for the first time today. **Five layers have never executed at
all on any real input, and one of them — PRIME — sits behind a candidate set that cannot reach a feasible contract.**
The joint engine, four weeks of R4 work, has never run outside tests. The signal is a placeholder. The system's
plumbing is in far better shape than its economics: everything that records, validates, refuses and reconciles has
been exercised; almost nothing that *decides* has.
