# ALPHA-EXP-001B — successor registration (why it supersedes ALPHA-EXP-001)

Status: **REGISTERED in code** (`apex/world_model/exp001b/registration.py`,
record `results/exp001b_registration.json`, hash
`b3930727334f24379f72df3919c98d689448b2f3f265b2fa6013559ee1bef5c9`).
**No real row has been read under it. No admission exists for it.**

ALPHA-EXP-001 (`1a3f55a5…`) is preserved byte-for-byte: its registration
module, its registration record and its code remain in the tree and are
pinned by hash in `tests/test_exp001b_temporal.py` and
`tests/test_real_data_boundary.py`. It is superseded, not edited.

## Why a successor and not a patch

The reviewer's source inspection of `566600dc` found that EXP-001's
*declared specification* — not only its implementation — was defective in
ways that change what a result would mean. Each defect was reproduced with
disposable fixtures against the actual functions before any repair
(`results/si002_reproductions.json`). A registration is frozen; correcting
its session definition, its clocks and its economic convention is a new
experiment with a new identity.

| # | Reproduced defect in EXP-001 | Introduced | EXP-001B specification |
|---|---|---|---|
| F1 | forecast `known_from` = bar OPEN, one minute before the inputs finished forming | `7f26e938f` | `known_from` = `assumed_available` = bar completion; `availability_basis = ASSUMED_BAR_CLOSE` recorded on every forecast |
| F2 | outcome availability = target bar's OPEN | `7f26e938f` | `outcome_available` = target bar completion; grader receives it |
| F3 | "regular session" = fixed 13:30–20:00 UTC; winter sessions included an hour of pre-market and dropped the last regular hour; early closes included two post-close hours | `7f26e938f` | NYSE regular session in exchange-local time; the governed `apex.intraday.sessions.classify` rule reproduced inside the experiment package (the laboratory may not import production modules) and parity-tested against it over 2016–2026 with the same tables; bars outside `[open, close)` dropped and counted; wrong-date / unaligned / non-session refused |
| F4 | horizon = 15 retained rows; a 10-minute gap made "15 minutes" 25 | `7f26e938f` | target = bar at exactly t+15 min; features need every minute bar in [t−30, t]; missing minutes refuse rows; nothing filled |
| F5 | economics computed on validation | `7f26e938f` | `VALIDATION_IS_DISTRIBUTIONAL_ONLY = True`; economics only on a separately unsealed evaluation |
| F6 | economics realised close-to-close despite `NEXT_BAR_OPEN` registration | `7f26e938f` | entry at open of bar t+1 min, exit at open of bar t+16 min, half spread per leg; missing leg → NOT_EXECUTABLE, counted |
| F7 | `certified_1R = rv_30 + spread` | `7f26e938f` | no `certified_1R`; `stop_distance_rv30_diagnostic` named as diagnostic, ineligible as 1R; certification only by `risk_certificate.certify` (not produced here) |

Unchanged from EXP-001: hypothesis, instrument, features, two models with
zero tuned hyperparameters, chronological splits, DM-HAC statistic and
threshold, N0 block-permutation null, modelled spread. `SEARCH_BUDGET`
records `horizons: 1`.

## Six clocks, kept apart

| Clock | EXP-001B meaning | Source |
|---|---|---|
| `event_time` | bar OPEN instant | vendor `event_time_utc` |
| `bar_complete` | `event_time + 60 s` | arithmetic |
| `assumed_available` | = `bar_complete`; **assumed**, not measured | convention, labelled |
| `publication_time` | `None` — NOT_AVAILABLE for this corpus | never substituted |
| `decision_time` | = forecast `known_from` = `assumed_available` of the current bar | models.forecast |
| `outcome_available` | `bar_complete` of the target bar | bars.targets |

`AVAILABILITY_LIMITATION`: this corpus does not establish historical
publication or revision timing; results are conditional on the bar-close
assumption and the admission decision must name that restricted use.

## Real outcomes consulted: none

Every value above was chosen from the reproduced defects and the existing
EXP-001 registration. No real corpus row was read at any point in this
milestone (the reproductions and tests use synthetic fixtures under
tempdir; the content manifest hashed bytes without parsing).
