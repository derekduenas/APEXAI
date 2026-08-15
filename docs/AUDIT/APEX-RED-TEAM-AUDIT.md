# APEX RED TEAM AUDIT — FROZEN REPORT (2026-08-15, pre-remediation)

Baseline: commit `58f8f5d`, clean tree, 847 passed / 1 skipped, 10 births,
protocol hash `bf4db439`, clock + nightly-pull loaded, ledger empty (first
records Monday). Full findings with severities: results/AUDIT-FINDINGS.json
(17 findings: 3×P1, 8×P2, 6×P3, 0×P0). This report records the repository
AS OBSERVED; nothing was repaired during inspection.

## Attack summary

**Secrets (Phase 26): CLEAN.** Both operator tokens absent from working
tree, full local git history, logs, artifacts, ops scripts. No echo/set-x
leakage paths in wrappers.

**Future leakage (Phases 5–6): CLEAN.** A reusable future-poison probe
(everything after T set to 99999/1e12) run against ChartState,
RelativeStrengthState, extension geometry, DailyContext, the FULL
production decision pass (scan → playbook → bundle → capital), and the
world simulator produced bit-identical outputs. The only divergence was
uuid4 identifiers — which is itself finding F-09 (reproducibility, P2).

**Birth law (Phase 24): CORRECT AT EVERY BOUNDARY.** Exact-timestamp
equality refuses; ±1µs behaves exactly as specified; missing dependency
kind refuses; future birth refuses; naive timestamps raise. Deterministic,
no override path.

**Chain integrity (Phase 25): P1 FOUND (F-01).** A torn write (crash
mid-append) permanently crashes the chain writer AND every ledger reader.
The archive would go dark and stay dark. Reproduced with a truncated
trailing line. Additionally: HOLIDAYS is an empty fixture-grade set
(F-08); no lock against manual/launchd interleaving (F-14, P3); launchd
itself cannot double-launch (StartInterval skips while running).

**Mutation testing (Phase 29): 7/8 CAUGHT.** Sabotaged guards — birth
gate, current-bar visibility, stop widening, caution direction, scenario
calibration claim, evidence mixing, cost-unknown — all broke at least one
test. SURVIVED: removing the analog *formed-at* firewall line (shadowed by
the resolved-at line for honest data; no adversarially-shaped test isolates
it — F-10). The resolved-at line itself is load-bearing (verified by its
own mutation).

**Analog engine (Phase 13): one P1.** Distance ordering is intuitive
(0.0 / 0.036 / 3.5 on identical/near/unrelated fixtures); future outcomes
cannot alter neighbours; a query formed at as_of cannot match itself;
historical class carries the survivorship limitation. BUT 50 same-symbol
rows yield status=OK (F-02): one stock can dominate support, and a
wrongly-confident OK *suppresses* the capital ×0.75 caution factor — an
anti-conservative channel. One-day dominance is partially capped by the
session-based n_effective.

**Monotone caution (Phase 19):** law holds under mutation and property
checks; sovereign constants (MAX_POSITION_WEIGHT, MAX_PARTICIPATION) have
single sources. Gate ordering: no irreversible action precedes risk
(nothing irreversible exists in production). Duplicate liquidity constants
exist between scanner and universe builder (F-07).

**Fail-closed sweep (Phase 27):** two real violations — simulator's
`atr_frac or 0.02` fabricates a vol scale (F-04); ML dataset builder
coerces ≤4 missing features to scaled-zero (F-05). Also the memory
regime `and`-idiom bug that yields 0.0 on a flat market (F-06). The
`except Exception` blocks in the clock/forward pass are all
degrade-and-continue with printed types, per the Monday-safety law, and
none can increase aggression (verified: enrichment failure removes the
caution *inputs* but the missing-forecast state still caps at
OBSERVE/WATCH with NO_CALIBRATED_FORECAST).

**Phantom/ornamental (Phase 2):** the causal layer contributes no Hunter
decision effect (hardcoded ASSOCIATIONAL — F-12, honest but ornamental);
TradeThesis is not constructed by paper authorization and paper.manage
duplicates the sealed state machine's law (F-11, dormant since
PAPER_ELIGIBLE is unreachable); the daily-horizon opportunity engine and
distribution estimator are deliberate sockets (documented DORMANT, not
phantom). Everything else claimed ACTIVE has a verified production caller
and decision effect.

**Protocol drift (Phases 1/35): P1 FOUND (F-03).** The frozen protocol
§2 promises `regime` in state records; the clock writes none. Discovered
BEFORE the first record exists — additive repair is legal and required.

**False confidence (Phase 36):** simulator outputs say scenario
frequency everywhere (correct); the one surface risk is AnalogResult's
field name `p_positive` for an uncalibrated empirical frequency (F-13,
P3). No display path prints "probability" from an uncalibrated source.

## Answers to the mandated attacks

Try to break the Twin → degraded honestly under stale/missing feeds, but
per-facet freshness is coarse (see DIGITAL-TWIN-AUDIT.md). Fool the
Analog Engine → succeeded once (single-symbol dominance, F-02). Leak the
future into ML → failed (labels only from realizations; features from the
frozen as-of schema; overlap gated by N_eff not rows). Make the simulator
hallucinate precision → failed (frequencies + UNCALIBRATED label + zero
authorization power), though it fabricates a vol scale when ATR is
missing (F-04). Make the Swarm override risk → impossible in the call
graph; non-OK status cannot carry claims; manage() refuses LLM actors.
Make Capital aggressive under uncertainty → failed under mutation. Make
the paper engine invent fills → failed (touch = AMBIGUOUS, no P&L). Make
memory forget failures → failed (every candidate kind reaches the ledger;
rejections retained). Make tests pass with broken guards → succeeded once
(F-10), 7/8 caught.
