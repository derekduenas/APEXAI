# ALPHA-EXP-001 — admission package for independent review

Everything a reviewer needs to decide whether, and on what terms, the
registered experiment may run on real data. Nothing here admits anything.
Sources are cited by branch and commit; the registration hash binds the design.

| | |
|---|---|
| Research branch | `alpha-exp-001`, off `world-model-shadow-v0` at `d01e961b` |
| Registration + path | `7f26e938f71741bb7740a83a46851e682c557bbb` |
| Qualifications | `4074017291114abcb8b19172af3edf2f24d2bc41` |
| Registration hash | `1a3f55a522f7595f179033827ad10d87e873b7839f1cc08fb05624067c8f391c` |
| Registration timing | committed before any real row was read; none read since |

---

## 1. Registered hypothesis and evaluation design

**Hypothesis.** Conditional on the last 1 and 5 one-minute returns and the
trailing 30-bar realised volatility, the 15-minute forward log return of SPY
during the regular session has a distribution that a volatility-scaled
Gaussian with a fitted conditional mean predicts with higher out-of-sample log
likelihood than the same Gaussian with zero mean.

**Mechanism, flagged as plausible and not established.** Any such effect is
smaller than the spread that would pay to price it — which is why it may not
pay us either. `MECHANISM_IS_NOT_A_FACT = True` in the registration.

**Target.** `y_t = log(close[t+15] / close[t])`, the laboratory's frozen
`H_15M` horizon, decision cutoff at bar close at t, outcome known at bar close
at t+15.

**Instrument and session.** SPY, regular session bars 13:30–20:00Z only.

**Models — one baseline, one challenger, no search.**
- M0 `M0_VOL_SCALED_GAUSSIAN`: mean 0, σ = k · rv_30 with k fit on TRAIN as mean|y| / mean(rv_30).
- M1 `M1_CONDITIONAL_GAUSSIAN`: mean a + b1·ret_1 + b5·ret_5 by OLS on TRAIN, σ as M0.
- Search budget: 2 model families, 1 feature set, **0 tuned hyperparameters**.

**Features.** `EXP001_OBSERVABLE_FEATURES_V0` = (ret_1, ret_5, rv_30), all
from bars with event_time ≤ t. The laboratory's frozen feature set includes
spread and trade_count; the corpus does not carry them and the laboratory's
own law forbids zero-filling, so EXP-001 declares its own set. Warm-up rows
carry a reason, not zeros.

**Chronology.**

| Period | Dates | Use |
|---|---|---|
| train | 2016-01-04 → 2019-12-31 | fitting only |
| validation | 2020-01-01 → 2021-12-31 | statistical stage |
| evaluation | 2022-01-01 → 2024-12-31 | **sealed in code**; opened only by explicit unseal after validation |
| reserve | 2025-01-01 → 2026-08-28 | untouched |

**Overlap treatment.** Adjacent targets share 14 of 15 increments. A 15-bar
embargo is applied at every session boundary; the statistic is
dependence-aware (below); no target's future crosses into the next session.

**Primary statistic.** `DEPENDENCE_AWARE_DM_HAC_V0` (laboratory's, unmodified):
d = logL_M1 − logL_M0 per sample, Bartlett kernel, L = H − 1 = 14, one-sided
threshold 2.0, n ≥ 4(L+1) = 60.

**Null control.** N0 block permutation: outcomes permuted across 20-bar
blocks with state kept; must return NO_SIGNAL or the harness is declared
broken and nothing counts.

**Secondary metrics.** Pinball loss at 0.05/0.5/0.95; PIT calibration.

**Criteria, frozen.** Validation z ≤ 2.0 → NO_SIGNAL, evaluation not opened.
Economic: mean after-cost return of the best non-cash expression ≤ 0 →
NO_OPPORTUNITY. PASS requires z > 2.0 on validation and on evaluation and
after-cost mean > 0 with a dependence-aware z > 2.0 on evaluation — and is
then "historically evaluated", not "validated".

## 2. Source and field eligibility, with limitations — SUBMITTED, pending review

| Source | Classification (submitted) | Limitations that bind the design |
|---|---|---|
| `history-b/etf_continuous`, SPY 1m, Alpaca SIP `adjustment=raw`, 2016-01-04→2026-08-28, corpus `5c0d768b7ee2ea14`, 0 missing sessions | ELIGIBLE_WITH_EXPLICIT_LIMITATIONS | (1) no per-bar receipt or publication time: bulk-retrieved 2026-08-29 as the vendor's view then; corrections between event time and retrieval are invisible; (2) raw adjustment, corporate actions explicit; SPY has no splits in span; (3) extended-hours bars present, excluded by design; (4) no bid/ask/spread/trade_count — executable prices unobservable, every cost is an assumption |
| `history-b/pit_singlename` (300 names, monthly PIT membership decided before each month) | ELIGIBLE_WITH_EXPLICIT_LIMITATIONS — not used by EXP-001 | same bar limitations; a superseded defective membership file retained |
| `history-a/options_history` (6 underlyings, 2018→, `acquired_at` per file, source timestamps per row) | ELIGIBLE_WITH_EXPLICIT_LIMITATIONS for daily-or-longer horizons | NOT_ESTIMABLE as a 15-minute benchmark; not claimed |
| ThetaData pilot sample (85 sampled days) | BLOCKED | stratified pilot; superseded by S1 |
| Live capture (7 sessions, receipt-stamped) | prospective substrate only | too short for history |
| decisions/outcomes ledgers | BLOCKED as input | contain resolved outcomes; cost model reused, data not |

"Eligible with limitations" is an assessment, not a status. The reviewer
decides whether limitations (1)–(4) are acceptable **for this experiment**.

## 3. Cutoff and availability semantics

| Role | EXP-001 | Established by |
|---|---|---|
| event time | bar start, vendor field | vendor |
| receipt time | 2026-08-29 bulk fetch (history); per file for live capture | git history / capture record |
| publication time | not available for bars; **assumed** at bar close | ASSUMPTION |
| revision time | not available; corrections invisible | LIMITATION |
| decision cutoff | bar close at t | registration |
| outcome time | bar close at t+15 | target |

Receipt establishes possession at receipt, not earlier publication.
Historical timestamps alone do not establish point-in-time correctness.

## 4. Data and version manifests

- Corpus: `history-b/etf_continuous/integrity.jsonl`, chain-appended,
  `corpus_version 5c0d768b7ee2ea14`, duplicates 0, non-monotonic 0, missing
  sessions per symbol recorded, builder `scripts/etf_corpus_fetch.py`
  (`feed=sip`, `adjustment=raw`, `timeframe=1Min`).
- Registration: `results/exp001_registration.json` on `alpha-exp-001`, hash above.
- Code under test: `apex/world_model/exp001/{registration,bars,models,run}.py` at `7f26e938`.
- Laboratory reused unmodified: `sources.py`, `forecast.py`, `grader.py`,
  `inference.py`, `targets.py` at `d01e961b`.

## 5. Economic assumptions

Execution model `NEXT_BAR_OPEN_PLUS_MODELLED_SPREAD`; `MODELLED_SPREAD_BPS =
2.0` crossed on entry and exit (cited from `day_trader.py`); expressions
{CASH, LONG_15M, SHORT_15M}; stop at 1.0 · rv_30; certified 1R = stop distance
+ round-trip spread; realised after-cost return on the same bars; dependence-
aware standard error versus CASH. Market benchmark = executable range = last
close ± modelled half-spread. Options-implied at 15 minutes: NOT_ESTIMABLE.

## 6. Positive-control development history — test development, preserved

| Attempt | Fixture | n | gain | HAC SE | iid SE | t | Verdict | N0 t |
|---|---|---|---|---|---|---|---|---|
| 1 | AR(1) φ=0.35, 8 sessions | 662 | — | — | — | — | NO_SIGNAL | — |
| 2 | φ=0.60, 12 | 993 | — | — | — | — | NO_SIGNAL | — |
| diag | φ=0.00, 16 | 1324 | −0.0015 | 0.0040 | 0.0015 | −0.39 | NO_SIGNAL | +0.87 |
| diag | φ=0.60, 16 | 1324 | −0.0066 | 0.0128 | 0.0080 | −0.51 | NO_SIGNAL | −2.25 |
| 3 | φ=0.90, 16 | 1324 | +0.1146 | 0.0550 | 0.0245 | +2.08 | SIGNAL_DETECTED | −4.43 |

The final PASS proves detection of that synthetic structure at ~1,300 rows and
a working null control. It does not establish sensitivity to plausible market
effects. Fixture parameters are not part of the registration.

**Power — ILLUSTRATIVE ONLY.** Under E[d] ≈ R²/2, SD[d] ≈ √R², n ≈ 170k,
HAC inflation 2.2× (measured) to 3.2× (theory): t ≈ √(n·R²)/(2·inflation) →
≈0.9 at R² 0.01%, ≈3.0 (2.0) at 0.1%, ≈9 at 1%. These figures do not
establish the statistic's power without a justified mapping, nor what effect
sizes are plausible. NO_SIGNAL is an expectation at the low end, not a
predetermined verdict.

## 7. The separate real-data admission contract — PROPOSED, not implemented

Three things held apart:

1. **The synthetic laboratory's prohibition** (`WORLD_MODEL_SOURCE_BOUNDARY_V0`) — intact and must remain.
2. **Dataset eligibility** — section 2, submitted.
3. **A separately governed real-data research path** — this contract, the reviewer's decision.

**Proposed `WORLD_MODEL_REAL_DATA_BOUNDARY_V0`:**

- A distinct module and authority manifest, not an exemption in the lab's boundary.
- Admits a dataset only against: an eligibility record (per source/field/cutoff), a per-file provenance manifest (corpus version, sha256, vendor, retrieval date, per-field limitations), and a named declared class from a real-data vocabulary (e.g. `ADMITTED_HISTORICAL_BARS`).
- Forbids, by resolved path and by class, the same categories the lab forbids: labels, resolved outcomes, book P&L, execution results. Refuses on any mismatch between manifest and file.
- Records every admission as a chain-appended decision naming the reviewer, the registration hash, and the limitations accepted.
- `exp001.run` takes the boundary as a parameter and executes unchanged through either.

**The exact blocker today:** attempting the run yields
`REAL_EVIDENCE_PATH: /apex-data/history-b/... resolves inside /apex-data/history-b`
from the lab's boundary; no real-data boundary exists. EXP-001 is blocked by
the absence of (3) and the correct refusal of (1), not by (2).

## 8. Ready-to-run configuration (unchanged from `EXP001_ADMISSION_AND_READINESS.md`)

SPY, `history-b/etf_continuous/bars`, corpus `5c0d768b7ee2ea14`, train/validation
session lists by date, `evaluation_unsealed=False`, ledger under
`/apex-data/core/world_model/exp001/<run_id>/`, contained at 1400 MiB.

## 9. What the reviewer is asked to decide

1. Whether limitations (1)–(4) are acceptable for a 15-minute SPY experiment.
2. Whether to create the real-data boundary as proposed, or an alternative.
3. Whether the field set may narrow (e.g. exclude `volume`, the most
   revision-prone field) rather than treating the corpus as blocked.

If (1) and (2) are affirmative, the next milestone is the registered run and
its economic evaluation. If a field fails, the experiment narrows to
defensible inputs; it is not abandoned.
