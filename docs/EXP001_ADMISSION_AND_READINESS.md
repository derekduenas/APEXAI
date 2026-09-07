# ALPHA-EXP-001 — admission decision, blocker, and readiness

## 1. The result of attempting to run on real data

**BLOCKED at the laboratory's source boundary, by design.** This is a
completed result, not an error.

`apex.world_model.sources.admit()` refuses on two independent grounds, and
both were exercised by tests on the exact paths:

| Ground | Refusal text (verbatim prefix) |
|---|---|
| The path | `REAL_EVIDENCE_PATH: /apex-data/history-b/... resolves inside /apex-data/history-b, which holds real market evidence, prospective outcomes or book state. The declared class ... does not change what the file IS.` |
| The class | `PERMITTED_SOURCE_CLASSES = {SYNTHETIC_FIXTURE, NULL_FIXTURE, MANUAL_FIXTURE}`; no real-data class exists, so any real class is `UNKNOWN_SOURCE_CLASS` and refused rather than defaulted |

No override exists. **I did not add one.** Adding a permitted class or a
real-evidence root exemption is a governance decision about the World Model's
research authority (`WORLD_MODEL_RESEARCH_AUTHORITY_V0`), and it is exactly the
"unresolved source" the mandate says must not be self-authorized.

## 2. What the reviewer must decide

One of:

**A. Extend the boundary** — add a permitted class, e.g.
`ADMITTED_HISTORICAL_BARS`, whose admission requires a provenance manifest
naming the corpus version, the per-file sha256, the vendor, the retrieval
date, and the per-field limitations from the eligibility table; and add
`/apex-data/history-b/etf_continuous` to a **new** list of admitted-with-record
roots, distinct from `REAL_EVIDENCE_ROOTS`. The boundary keeps refusing
labels, outcomes, book P&L and execution results.

**B. Mirror into a fixture root** — copy the SPY session files for the
registered periods into `/apex-research/world-model-fixtures/exp001/` with a
`_PROVENANCE.json` declaring each file's sha256 and `source_class`. This runs
today with no code change to the boundary, at the cost of a second copy of
~2.7k files (~450 MB) and a manifest that a reviewer signs.

Recommendation: **B for the first run**, because it changes nothing in the
boundary and every admitted file is individually hashed and declared; A
afterwards, if repeated real-data experiments are wanted.

Either way the record must state: `ELIGIBLE_WITH_EXPLICIT_LIMITATIONS`, with
limitations 1–4 of the eligibility table carried verbatim.

## 3. Ready-to-run configuration

```
experiment            ALPHA-EXP-001   registration_hash: see results/exp001_registration.json
instrument            SPY
corpus                /apex-data/history-b/etf_continuous/bars   corpus_version 5c0d768b7ee2ea14
declared_class        <the class chosen in section 2>
train                 SPY_2016-01-04.json .. SPY_2019-12-31.json    (~1006 sessions)
validation            SPY_2020-01-02.json .. SPY_2021-12-31.json    (~505 sessions)
evaluation            SPY_2022-01-03.json .. SPY_2024-12-31.json    SEALED: evaluation_unsealed=False
reserve               2025-01-01 .. 2026-08-28                       SEALED, not passed in
ledger_dir            /apex-data/core/world_model/exp001/<run_id>/  (chain-appended, forecasts BEFORE outcomes)
command               python -c "from apex.world_model.exp001 import run as R; import json; \
                        print(json.dumps(R.run(SESSIONS, ledger_dir=LED, declared_class=CLS, fixture_root=ROOT), indent=1))"
containment           wmresearch.slice, MemoryMax=1400M   (measured engineering peak: well under 1 GiB)
```

The evaluation period stays sealed even if validation detects a signal; the
run returns `BLOCKED` with the validation record and asks for an explicit
unseal. That is enforced in code, not by convention.

## 4. Power, stated before the run

The dependence-aware statistic pays for the 15-step overlap: on the synthetic
fixtures the HAC standard error was 2.2× the iid one, and a planted structure
with R²≈18% reached t=2.08 only at n≈1,300 rows. Effective sample scales as
roughly n/15.

On real SPY, validation holds ~170k regular-session rows, n_eff ≈ 11k. A
realistic 15-minute predictability of R²≈0.1% gives an expected t≈0.3. **The
registered expectation is therefore NO_SIGNAL.** That is a legitimate completed
result: it would establish, with a dependence-aware test and a working null
control, that this information tier does not move the 15-minute distribution
enough to see, let alone to pay 4 bps. If the result is instead
SIGNAL_DETECTED, that is a surprise to be treated with suspicion first, and the
sealed evaluation is the only place it can be confirmed.

No search is permitted to change this: one baseline, one challenger, zero
tuned hyperparameters, registered before any real row is read.

## 5. Prospective evaluation readiness

**Implemented and tested in engineering mode:** forecasts are chain-appended
to a ledger *before* any outcome is attached; outcomes are attached as a
separate record; the grader void-checks the forecast hash; attribution is
written last.

**Prospective substrate:** `data/live/alpaca_fabric/bars` — our own capture,
receipt-stamped, coverage-labelled, seven sessions so far. A prospective run is
the same `run.py` pointed at each new session after its close, with the
forecast sealed at bar close and graded 15 bars later. Configuration:

```
mode                  PROSPECTIVE (forecast sealed at t; outcome attached at t+15 bars)
sessions              data/live/alpaca_fabric/bars/SPY_<date>.json, one per completed session
declared_class        requires the same admission decision as section 2 (live capture is also a real-evidence root)
schedule              after each session close; NOT a daemon; NOT activated
```

**Not activated.** No new production service is started, no data-admission
gate is bypassed, and calendar time is the binding input: prospective
accumulation cannot be hurried and does not become admissible merely by
existing.

## 6. Time roles, held apart

| | EXP-001 uses | Established by |
|---|---|---|
| event time | bar start, from the vendor | vendor field |
| receipt time | bulk fetch 2026-08-29 for history; per-file for live capture | git history / capture record |
| publication time | not available for bars; assumed at bar close | ASSUMPTION, recorded |
| revision time | not available; corrections are invisible | LIMITATION, recorded |
| decision cutoff | bar close at t | registration |
| outcome time | bar close at t+15 | target definition |

Historical research is **not admitted** by the eligibility assessment being
complete. Eligibility says what could be admitted and on what terms; admission
is the decision in section 2, and it has not been made.
