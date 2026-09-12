# Stage 1 pre-registration — PIPELINE_COMMISSIONING (written 2026-09-12, before any observation exists)

This statement is committed before the first seal. It cannot be softened after outcomes land because the commit
that carries it precedes every record it governs.

1. **Week one (sessions from 2026-09-14) is `PIPELINE_COMMISSIONING`.** Every record produced by the rule path on
   live market data with simulated fills carries `evidence_class: PROSPECTIVE_PAPER`, `execution_mode:
   PROSPECTIVE_ORCHESTRATION`, `fill_label: SIMULATED`, and this pre-registration id: `STAGE1-PREREG-2026-09-12`.
2. **Its observations are EXCLUDED from expectancy, calibration, and alpha claims.** They test that the loop closes
   (forecast → event context → rule → intent → simulated fill → exit → Book → ledger → resolution → scoring →
   attribution), the identity of every join, and the cost model against the fee schedule. They do not test whether
   the signal has skill. A positive week is not evidence of edge; a negative week is not evidence against it.
3. **FOMC 2026-09-16 is sealed on every record** through the event snapshot (`SCHED-2026-09-12`, FOMC-2026-09-16
   CRITICAL, window 2026-09-15T13:30Z to 2026-09-16T20:00Z) on the forecast's `inputs.event_context` and on each
   decision's `situation_regime.event_context`. `EVENT_GATE_V0` runs in SHADOW: it records what it would veto; it
   vetoes nothing.
4. **Deliverable of the stage:** the first date that produces a complete scored observation chain. Per session:
   candidates constructed, certified, selected; modelled entry cost (`expected_toll`, `TOLL_FORMULA_V1`); modelled
   exit; realised simulated P&L.
5. **Exit condition:** 10 consecutive sessions with a complete scored record chain, zero unresolved-past-due under
   the calendar clock (A-011), `n_effective_dates > 1`.
6. **Not authorized in Stage 1:** paper capital for real placement, any order, any placement code, any gate weakened
   to pass a census, any release change while a position is open (A-012).
7. **Policy identity:** `PILOT_RULE_V2` only. Funnel and joint paths are not selected; the bar client is attached in
   parallel so the funnel's history requirement can be satisfied from live history without gating this stage.
8. **Fee schedule:** `ROBINHOOD_RHF_2026`, `PROVIDER_VERIFIED`, authorized 2026-09-12, digest `7f9c86bf…`, sealed on
   every intent's `pins.fee_schedule_hash`.
