# DECISION_PATH_REPAIR_001 — candidate for independent review

Review base: `b9998d02b7c3dc8030e753277fd5fbd1bba9ff8f`. Branch: `decision-path-repair-001` from that commit (HEAD was
the review base; ancestry verified; nothing reset or amended). Contract `docs/R4_JOINT_MARKET_STATE_SPEC.md` at blob
`a0228fac4a2dab4c455c9fc8a41d1378522a27de` **unchanged** (Amendment A1 preserved). Synthetic tests and offline code
only. No backtest, fitting, provider request, collector restart, service activation, deployment, broker order,
admission change or risk-limit change.

Reproducers: `scripts/decision_path_probes.py` → `docs/evidence/decision_path_reproductions.json` (before, 12/12
reproduced) and `docs/evidence/decision_path_after.json` (after, 0/12).

## Finding → reproducer → repair → acceptance test (severity order)

| # | Finding | Reproducer (before) | Repair | Acceptance test |
|---|---|---|---|---|
| 1 | **Adverse IV sign.** `shift = -se if CALL else +se` made the long-put "adverse" scenario an IV-up benefit | `F4`: mapping present in source | `apex/joint_wb/engine.py` `_adverse`: shift = −SE for every long vanilla option (vega > 0); an unsupported expression raises `ADVERSE_IV_SIGN_UNDETERMINED`; the parameter record names the direction `IV_DOWN` and the expression | `TestAdverseIV`: through the real engine, a selected CALL and a selected PUT both have scenario ≤ BASE; through `accounting.price_paths` on fixed paths, IV-down lowers both a call and a put; registry completeness and no-silent-pass preserved |
| 2 | **PRIME spread gate unreachable.** engine passed `entry_spread_rel=None`; supervision read `(x or 0)`, which also swallowed a measured 0.0 | `F3`: both idioms present, PRIME ACTs | engine carries `entry_spread_rel` (sanitize_quote's `(ask−bid)/mid`) and `quote_identity` on every candidate row and into PRIME's comparison, and records `trace.prime_input`; supervision: missing/non-finite/negative spread → ABSTAIN "unknown or invalid; a missing spread is not zero"; a measured 0.0 passes on its merits; threshold 0.15 unchanged | `TestPrimeSpread`: None/NaN abstain, 0.0 acts, 0.16 abstains, 0.14 acts (real `supervise`); a 0.16-spread candidate that clears rules 0–4 abstains **through the real engine** (rules 0–5 all present in the trace); a 0.02 control trades and PRIME's input equals the selected row's spread and quote identity |
| 3 | **Right normalization manufactured PUT.** `"CALL" if startswith("C") else "PUT"` | `F2a`: empty right → PUT | `apex/pulse_options/sources.py` `live_chain_rows`: declared encodings `{C, CALL, P, PUT}` only; anything else excluded `RIGHT_NOT_DECLARED` and recorded on `ChainRows.exclusions` | `TestQuoteNormalization::test_provider_boundary_refuses_and_records_every_malformed_row`: no PUT exists in the output for missing/None/"X" rights |
| 4 | **Policy identity.** CLI default V1, session default V2; report named one, execution ran the other | `F1` | `PILOT_RULE_V2` added to `SELECTION_POLICIES` and the CLI (default V2 = `DEFAULT_RULE`); `run_pilot` resolves the policy once, rejects unknown names and rule/funnel conflicts, passes it to `session.scan`, which dispatches by name (no attribute lookup, no fallback) and refuses on a rule-id mismatch; the report carries `policy_identity` and `run_pilot` raises if any persisted intent's rule id differs from the policy's; funnel policies matched on their exact rule ids | `TestPolicyIdentity`: CLI V1 and CLI V2 on the fixture where they disagree (645 vs 650): report, invoked rule, persisted intent and pins all agree; CLI default equals session default; unknown policy rejected by CLI and `run_pilot`; a mislabeled run fails the identity check |
| 5 | **Quote hardening.** fractional/bool sizes truncated, infinities survived, zero/negative/non-finite asks entered V2, conflicting duplicates resolved by order | `F2b–F2e` | provider boundary as in 3 plus finite positive strike/ask, finite bid ≤ ask, digit-only integer sizes, parseable timestamp not in the future and ≤ 120 s; pure selector boundary (`expression_rule.validate_rows`) re-validates independently, validates timing when `as_of_epoch` is supplied, excludes conflicting duplicates as `DUPLICATE_CONFLICT`, collapses identical ones, records every exclusion in `strike_selection.exclusions` and the census | `TestQuoteNormalization`: adapter→selector path with conflicting and identical duplicates is order-independent and keeps the valid alternative; every malformed value is excluded at the selector even when the provider let it through; bool is not a size |
| 6 | **BEFORE-record timing gap.** Spec's intent-time toll used a later fill quote; ordering omitted the indicative quotes | `F6` | `records.py`: `TOLL_FORMULA_V1` (hashed text; intent-time inputs only; exit half-spread declared equal to entry, labelled an assumption with an amendment proposal), `expected_toll` (`NOT_ESTIMABLE` when fees unknown), `doctrine_stamp` (six fields + tail_asymmetry, `NOT_MEASURED`/`UNKNOWN` sealed explicitly; footprint computed), `pins`; boundary seals them in the intent and writes `entry_cost_update` on the fill from the executable quote, referencing the intent's value; `SEAL_SPEC_OBSERVATION_ONE.md` corrected | `TestBeforeRecord`: fields sealed from intent-time inputs; unknown fees → `NOT_ESTIMABLE`; the quote callback observes forecast and intent already persisted with the BEFORE fields; the fill does not change the intent's hash |
| 5′ | **Freshness (adjudicated, not patched from memory).** | `F5`: 30 s quotes → `n_eligible 0` | `docs/FRESHNESS_ADJUDICATION_2026-09-12.md`: §1.1 quoted; ruling: the code applied the 15 s execution limit at proposal time, which the contract places at the boundary; indicative quotes ≤ 120 s now rank and may propose; the boundary's 15 s executable check and every refusal are unchanged | `TestFreshnessTwoStage`: 30 s chain + fresh executable quote fills; fresh chain + 16 s executable quote cannot fill (`STALE_SELECTED_CONTRACT`, no position); 121 s chain row cannot be selected; the replaced R4 test proves ranking at 30 s and refusal at 121 s |
| 7 | **Real integration** | — | — | `TestRealIntegration`: unconditional TRADE through session → boundary → certified fill → exit → reconciled Book with a realised P&L and no integrity problems; mandatory WAIT leaves no position and no reservation |

Also changed: `apex/backtest_wb/replay.py` passes the rule and `as_of_epoch` (default V1, the sealed study
definition); the synthetic harness's chain rows now carry an indicative quote with identity; the funnel-WAIT test
ages the chain with the quotes; the old one-stage freshness test was replaced.

## Commands and environment

```
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_options_pilot_boundary.py tests/test_options_pilot_entrypoint.py \
  tests/test_options_pilot_accounting.py tests/test_options_pilot_operator_view.py tests/test_pulse_options_twin.py \
  tests/test_defect_repair_001.py tests/test_decision_path_repair_001.py tests/test_funnel_engine.py tests/test_joint_wb.py \
  tests/test_joint_wb_repairs.py tests/test_backtest_wb.py tests/test_reality_harness.py
```
Mac, Python 3.11.9, numpy 2.4.6, single process. Results are pasted in the delivery message with exit codes.

## Combined-suite EXP-002 / EXP-004 failures

Reproduction attempts: the two modules together → 25 passed. Every module alphabetically before and including
`test_exp004` in the full run's order → result recorded in the delivery message. The claim "environmental" is not
made unless the ordered run passes; if it fails, the shared state is named.

## Unresolved

- The equal-half-spread assumption in `TOLL_FORMULA_V1` is declared, not estimated; the amendment (session
  exit-spread distribution after ≥ 20 sessions) is proposed for review, not applied.
- `git_commit` in `pins` is honest text, not a hash: the release id is the deployment pin.
- The live bars/NBBO HTTP client for the pilot process is still `_no_http`; only chain/quote are wired.
- `DEPLOYMENT_DIVERGENCE_001` is OPEN (record written this block); nothing deploys until it closes.
- The nightly pull was found armed on the Mac (`com.apex.nightly-pull` launchd) and ran during this block; the
  operator listed arming it as their own pending decision. Not touched; reported.

## 8. Why the suite missed this — root cause per finding

| Finding | Test that should have caught it | Why it did not |
|---|---|---|
| Adverse IV sign | `TestF1AdverseScenarios::test_every_registered_scenario_is_evaluated_and_recorded` | It asserted the **label** (`direction == "against the position"`) and that a value existed. It never asserted the sign of the shift or that the scenario value ≤ BASE. And the fixture only ever selected CALLs: under the default `v_hat = 1e-6` every negative drift saturates the spread state and puts never trade, so the PUT branch of the mapping was never executed by any test. *Property never asserted + fixture one-sided.* |
| PRIME spread gate | `test_joint_wb` T-series tests that assert rule 5 ran (`ACT`/`ABSTAIN`) | They checked that PRIME **ran** and what it returned on the risk input. Nothing asserted that the candidate handed to PRIME carried a spread; the hardcoded `None` in production code was itself a double, and every test accepted it. No supervision test passed `None` or `0.0`. *A double in the real path + property never asserted.* |
| Right normalization | `TestLiveWiring::test_chain_fn_returns_validator_shaped_rows…` (written last block) | Its "malformed row is dropped" fixture malformed only the strike. Rights in every fixture were `C` or `CALL`. The claim "nothing invented" was asserted for one field and read as if for all. *Fixture too clean.* |
| Policy identity | `test_options_pilot_entrypoint` (CLI runs) and `test_options_pilot_boundary` (rule id on the intent) | The CLI tests asserted decisions, never the rule id against the report. The boundary tests asserted the rule id by calling `session.scan` **directly**, bypassing provider and CLI. Each half was green; the join between them was never under test. *A double standing in for the real path.* |
| Quote hardening | `validate_quote` tests (bool sizes, NaN timestamps) prove the **fill** boundary is strict | No validator existed on the chain path, so no test could exist for it; `choose()` tests used hand-built clean dicts. The suite tested the one boundary that had a validator and inferred the other. *No test of that behaviour.* |
| Freshness | `test_14_9s_is_executable_and_15_1s_is_indicative_only` | It **encoded the defect**: written from a reviewer's instruction, it asserted a 15.1 s quote yields `n_eligible 0`. A test derived from an instruction rather than from the contract clause is a regression lock on whatever the instruction said. *Assertion encodes the instruction, not the contract.* |
| BEFORE-record timing | none possible for a spec sentence; a formula test would have caught the input | No toll test existed because no toll field existed. *No test.* |

**The pattern.** The hypothesis is confirmed with one refinement: the suite tests that components ran and what
*labels* they emitted, and labels are plumbing. Every one of these gates was covered by a test that checked its
presence (a key in a trace, a string in a parameter record, a rule number in a list) and none by a test that checked
its **direction, threshold, or input identity**. Fixtures were one-sided (always CALL, always fresh, always clean,
always narrow), so the branches where the sign, the default, or the fallback mattered were never executed.
Integration tests called the layer below the join they claimed to cover.

**Smallest strategy change (proposed, not built).** A per-gate *flip test* obligation: every gate, threshold, or
sign in the decision path must have exactly two fixtures through the real path, one just inside and one just outside
the property, and the test asserts that the **decision flips** between them. Applied to these findings: IV up vs IV
down on a PUT (flips the scenario ordering), spread 0.14 vs 0.16 (flips PRIME), right `"P"` vs `"X"` (flips
inclusion), CLI V1 vs V2 on a fixture where they choose different strikes (flips the contract), age 14 s vs 16 s at
the fill and 119 s vs 121 s at the chain (flips at the right stage). Five of the six findings are caught by that
rule alone; the sixth (a spec sentence) is caught by the toll test the field now has. A test that cannot name the
fixture on the other side of its threshold is a presence test, and presence tests are not evidence about economics.
