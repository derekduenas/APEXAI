# ALPHA-EXP-001B — revised admission package (submitted assessment, not a decision)

Supersedes `EXP001_ADMISSION_PACKAGE.md` for the purpose of admission.
EXP-001's package, eligibility and qualifications are preserved as history.

```text
DATASET_ELIGIBILITY:    ASSESSED — history-b/etf_continuous, SPY, fields event_time_utc/open/high/low/close/volume,
                        2016-01-04..2021-12-31 (train + validation), NYSE regular session per exchange calendar
REAL_DATA_ADMISSION:    NOT_AUTHORIZED (proposal unsigned and PROPOSED; no allowed_signers; trust paths non-compliant)
EXP_001B_REAL_EXECUTION: NOT_PERFORMED
```

## 1. Precise eligible research use

**Use:** run `scripts/alpha_exp_real_execute.py --execute` for ALPHA-EXP-001B
(registration `b3930727…`) on SPY one-minute bars for the registered train
(2016–2019) and validation (2020–2021) periods only. The command fits M0/M1
on train, seals validation forecasts before outcomes, grades against the
target bar's completion, applies DM-HAC and the N0 null, and stops. It
performs **no economic stage** and **never opens evaluation**.

**Expected process outcomes:** `SCIENTIFIC_COMPLETE` with `NO_SIGNAL`
(the prior expectation for a weak, widely known effect), or
`EVALUATION_SEALED` if validation reports `SIGNAL_DETECTED`. Either is a
completed, sealed result; neither authorizes evaluation.

## 2. Fields and their eligibility

| Field | Eligible | Limitation |
|---|---|---|
| `event_time_utc` | yes | bar OPEN instant; completion is `+60 s` by convention |
| `open` | yes | used only by the (sealed, not-run) evaluation economic legs |
| `high`, `low` | admitted, unused by EXP-001B | — |
| `close` | yes | features and target |
| `volume` | admitted, unused | — |
| `bid`, `ask`, `trade_count`, `spread_bps`, `publication_time` | **not in corpus** | declared NOT_AVAILABLE; never zero-filled |

## 3. Temporal semantics the decision must carry

- `event_time`: PER_ROW; `receipt_time`: BULK 2026-08-29; `publication_time`
  and `revision_time`: NOT_AVAILABLE; `corporate_actions`:
  RAW_UNADJUSTED_EXPLICIT (SPY has no splits in range; dividends are not
  adjusted and are not relevant to 15-minute intra-session returns).
- `restricted_use` names: no point-in-time availability claims; no revision
  modelling; availability ASSUMED at bar completion, labelled on every
  forecast (`availability_basis = ASSUMED_BAR_CLOSE`).
- Session: NYSE regular session in exchange-local time (DST-aware, early
  closes 13:00); the calendar tables are rule-derived plus Good Friday and
  special-closure tables for 2016–2026 and are **not independently verified
  against each year's exchange notice** — a wrong table refuses rows, it
  does not invent them.

## 4. Unresolved limitations

1. Publication/revision timing is unmeasured; results are conditional on
   the bar-close assumption.
2. The calendar is rule-derived (see 3); two missing XLRE sessions in the
   corpus are irrelevant to SPY.
3. EXP-001B's hypothesis is weak by design; power figures from EXP-001
   were illustrative and are not restated as expectations.
4. Host trust paths are not yet compliant (`/apex-data/governance` owned by
   `apex`, mode 775; no `trust/allowed_signers`); the verifier refuses
   until an operator fixes ownership. Engineering will not do this.
5. Signing key custody is out of band; the verifier can only check that
   the research uid does not own the trust paths.

## 5. What is requested (one item) and what is not

**Requested:** the admission authority reviews this package, brings the
trust paths into compliance, and issues the signed decision from
`docs/admissions/EXP001B_ADMISSION_DECISION_PROPOSED.json` with
`code.commit` = the reviewed HEAD (the relevant source tree hash
`720f1ad0…` is already fixed by the code commits `74003aef` + `28153e1a` and unchanged by
documentation commits). Then, separately, authorize exactly:

```text
PYTHONPATH=/apex-data/tmp/si002_wt /opt/apex/shared/venv/bin/python scripts/alpha_exp_real_execute.py --decision <path> --execute
```

**Not requested and not performed:** evaluation unsealing, any economic
stage, EXP-002, participant model, new data acquisition, options-paper
hold removal, production change.
