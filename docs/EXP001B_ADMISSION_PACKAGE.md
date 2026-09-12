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
  closes 13:00). For 2016–2021 the tables are independently reconciled against
  the primary exchange announcements (see limitation 2). A wrong table does
  **not** refuse rows — an omitted early close silently admits post-close bars
  and an added one silently discards valid ones, both reproduced — which is why
  the loader refuses any date outside the reconciled window.

## 4. Unresolved limitations

1. Publication/revision timing is unmeasured; results are conditional on
   the bar-close assumption.
2. The calendar for 2016–2021 is now **independently reconciled date by date**
   against the primary NYSE Group announcements — 1,565 weekdays, 54 holidays,
   12 early closes, zero mismatches
   (`results/exp001b_calendar_reconciliation_2016_2021.json`), with a
   metadata-only corpus cross-check confirming every session and none on a
   holiday. Early closes are corroborated by file size for 10 of 12 and
   uncorroborated — not contradicted — for 2. Dates outside the window are
   refused (`CALENDAR_NOT_VERIFIED`). Two missing XLRE sessions in the corpus
   are irrelevant to SPY.
3. EXP-001B's hypothesis is weak by design; power figures from EXP-001
   were illustrative and are not restated as expectations.
4. Host trust paths are not compliant, and the gap is larger than ownership:
   `/apex-data` is owned by the research account, so nothing beneath it can
   hold trust, and that account holds full passwordless sudo. The admission
   root is therefore `/etc/apex/admissions`, which does not exist yet; the
   verifier refuses with `TRUST_PATH_MISSING`. The exact, unexecuted remedy —
   including a separate non-sudo research account — is
   `ADMISSION_OPERATOR_PACKAGE.md`.
5. Signing key custody is out of band; the verifier can only check that
   the research uid does not own the trust paths.

## 5. What is requested (one item) and what is not

**Requested:** the admission authority reviews this package, performs
`ADMISSION_OPERATOR_PACKAGE.md` items 1–6, and issues the signed decision from
`docs/admissions/EXP001B_ADMISSION_DECISION_PROPOSED.json` with
`code.commit` = the reviewed HEAD (the relevant source tree hash
`24322971…` is fixed by the code commit `6be2507f` and unchanged by documentation commits). Then, separately, authorize exactly:

```text
PYTHONPATH=<dedicated checkout> /opt/apex/shared/venv/bin/python scripts/alpha_exp_real_execute.py --decision /etc/apex/admissions/<decision>.json --execute
```

**Not requested and not performed:** evaluation unsealing, any economic
stage, EXP-002, participant model, new data acquisition, options-paper
hold removal, production change.
