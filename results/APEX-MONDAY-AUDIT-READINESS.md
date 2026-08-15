# APEX — MONDAY AUDIT READINESS (Saturday 2026-08-15, post-remediation)

## VERDICT: MONDAY_AUDIT_READY = YES

Gate checklist: ZERO unresolved P0 (none found). ZERO unresolved P1
(3 found, 3 remediated same-day with failing-test-first repairs). Forward
clock loaded and verified after every change. Ledger chain now survives
torn writes and readers tolerate them. Birth law deterministic at every
boundary probed (±1µs). Playbooks and scanner changed ONLY via versioned
engineering repairs (sovereign-constant import; no threshold or predicate
value changed — diffs auditable). Twin passes PIT/consistency; freshness
graded WEAK and accepted for observational Monday. Simulator remains
diagnostic/uncalibrated and now refuses unknown ATR. ML remains gated and
no longer zero-fills. Swarm optional, auth-gated, cannot carry claims
when blocked. Capital sovereign; monotone caution held under mutation.
PAPER_ELIGIBLE unreachable; broker sealed; Credit 5 sealed; holdout
sealed. Tests: 847 → 857, all green.

## Final report figures

P0: 0. P1: 3 (all fixed). P2: 8 (6 fixed, 2 deferred with reasons —
F-11 dormant-path, F-17 measure-first). P3: 6 (deferred, recorded).
Bugs found: 4 (torn-write, falsy-and regime, zero-fill, fabricated ATR).
Scientific defects: 2 (single-symbol analog support; time-of-day
seasonality uncontrolled — flagged for post-Week-1 baselines). Lookahead
defects: 0 (full-pass poison clean). Phantom components: 0. Ornamental:
1 (causal layer, Hunter path). Hardcoded assumptions: consolidated to
sovereign constants where economic; frozen research parameters
documented. Duplicate sources of truth: 2 found (liquidity constants —
fixed; trade-management law — deferred, dormant). Unreachable safety
code: 0. Unsafe fallbacks: 2 (fixed). Misleading probability language: 1
naming risk (recorded). Mutation testing: 8 sabotages, 7 caught, the
survivor's gap closed with a new adversarial test (now 8/8 catchable).

## Component verdicts

Digital Twin: **honest but thin** — PIT-STRONG, provenance-STRONG,
freshness WEAK, completeness WEAK-ADEQUATE; sufficient for observational
Monday, not yet for serious world-representation (missing: intraday
regime PMF, per-facet TTL, correlation, event load). Regime: PARTIAL,
conservative-only, now truthfully recorded in state records. ChartState:
SOUND (fixture-validated, leakage-proof; OR-under-gaps caveat recorded).
Analog: SOUND after v1.1 (leakage-proof, diversity-guarded, honest
sparsity). ML: SOUND-AND-DARK (refuses correctly; clean training path).
Simulator: DEFENSIBLE as a diagnostic (empirical conditional resampling,
future-blind, frequencies-not-probabilities); NOT defensible as a
probability source — and it does not claim to be. Swarm: safe by
construction, empty chair. Capital: SOVEREIGN (mutation-proof caution).
Trade management: certified counterexamples; dual-law debt recorded.
Memory: SOUND (structural time firewall, lineage complete). Full
pipeline: **the documented spine is the actual call graph** (no hidden
shortcuts found).

## The fifteen answers

1. Does APEX do what its documentation claims? **Yes, with 3 documented
   divergences found and fixed (F-03) or recorded (F-11, F-12).**
2. All intelligence components connected? **Yes — active ones verified by
   caller+effect; dormant ones typed, not faked.**
3. Ornamental/phantom? **One ornamental (causal, Hunter path), zero
   phantom.**
4. Can future information leak into a decision at T? **No path found:
   full-pass poison clean, firewalls mutation-tested, boundaries exact.**
5. Can uncalibrated output masquerade as calibrated probability? **No:
   type-enforced statuses, mint_calibrated sole mint, mutation caught.**
6. Can missing data increase aggression? **No: every missing input
   refuses or caps at WATCH; two silent defaults found and removed.**
7. Can an LLM override deterministic laws? **No: non-OK assessments
   cannot carry claims; manage() refuses LLM actors; no call-graph path.**
8. Can production reach paper/live illegally? **No: PAPER_ELIGIBLE
   unreachable, synthetic auth pytest-only, broker sealed (re-verified).**
9. Twin strong enough for serious intraday representation? **Not yet —
   honest and safe, but thin (named gaps); enough for observation.**
10. Simulator scientifically defensible? **As an uncalibrated diagnostic,
    yes; as a probability source, no — and it knows that.**
11. Hunter-001/002 internally coherent? **Yes (dimensional/geometric
    coherence audited); as HYPOTHESES they are PLAUSIBLE/UNTESTED.**
12. Can tests detect sabotage? **7/8 at audit; 8/8 after F-10's test.**
13. Five most dangerous remaining ways APEX could fool us: (1) time-of-
    day seasonality masquerading as playbook edge (no ToD baseline yet);
    (2) the 15-minute observation cadence making recorded formations
    unrepresentative of tradable prices; (3) analogue memory maturing
    into subtly autocorrelated support (same-event clustering across
    symbols); (4) EODHD feed quality quietly degrading mid-session in
    ways the staleness rule misses; (5) we, the operators, growing
    attached to early green numbers below N_effective thresholds.
14. Five highest-value post-evidence improvements: intraday regime
    PMF into the Twin; time-of-day baseline; measured spreads (kills
    COST_UNKNOWN honestly); analogue memory from the historical shadow
    exercise (exploratory class); per-facet freshness TTLs.
15. Safe and scientifically honest enough to begin Monday's forward
    observation? **YES.**
