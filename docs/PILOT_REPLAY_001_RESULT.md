# PILOT-REPLAY-001 — result (HISTORICAL_DEVELOPMENT_REPLAY; exposed sessions only)

Contract: `apex/backtest_wb/contract.py` (digest `79e9caf08cde5b26`), declared before any corpus read. Evidence:
`docs/evidence/pilot_replay_001_summary.json` (host run under containment, 808 s, peak RSS 177 MB; scans ledger
`/apex-data/tmp/replay001/replay_scans.jsonl`). Period policy: SPY corpus sessions ≤ 2021-12-31 only
(2022+ SEALED; untouched). This is a development replay of the deterministic pilot rule: NOT prospective evidence.

## Population

| | |
|---|---|
| Sessions | 82 (2018-01-02 → 2021-11-22) |
| Scans | 1,886 (15-minute grid) |
| Rule decisions | TRADE 1,179 · REFUSE 707 |
| Non-trade reasons | RISK_ENVELOPE_INFEASIBLE 591 · FORECAST (warm-up) 82 · NO_ELIGIBLE_EXPIRY 22 · NO_DIRECTION_SIGNAL 12 |

## Planned comparisons (nothing else was computed)

| Comparison | Result |
|---|---|
| POLICY vs WAIT (session-block bootstrap, 2,000 draws) | mean net **−5.48 USD/trade**, CI95 [−6.40, −4.50], 61 sessions with trades → `DID_NOT_DEMONSTRATE_IMPROVEMENT_OVER_WAIT` |
| POLICY vs RANDOM_DIRECTION (paired, 1,157 common rows) | mean diff −0.53 (sd 22.7) |
| POLICY vs REVERSED_DIRECTION (paired, 1,120 common rows) | mean diff −0.71 (sd 30.2) |
| Friction | gross −4,140 · fees 2,323 · spread crossing 4,264 → friction 6,586 |
| Artifact calibration (PIT, n = 1,804) | KS 0.039, p = 0.007; mean PIT 0.508 → not calibrated |
| Direction label sign agreement (n = 1,780) | 49.6 %, binomial p = 0.72 → no skill |
| Cap-free counterfactual (recorded, never selected) | 1,770 trades, mean net −6.80 (the 591 envelope-refused rows lose more, not less) |

Hit rate 32.8 % for the rule, 32.8 % random, 31.8 % reversed: the options' 15-minute P&L is dominated by the half-
spread paid twice and fees, not by direction.

## Reading

The deterministic rule has no measurable edge and the heuristic direction label is a coin flip. That is the
baseline the integrated funnel (`docs/FUNNEL_INTEGRATION.md`) must beat on the same rows; PILOT-REPLAY-002 is
declared (`apex/backtest_wb/contract2.py`) and not run, per the operator's instruction to hold backtests until the
funnel is complete. The 591 envelope refusals are the kernel-cap-vs-SPY-price decision the operator owns.
