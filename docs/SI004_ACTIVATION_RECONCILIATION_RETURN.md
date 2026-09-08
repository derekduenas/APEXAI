# RESEARCH ACTIVATION — final package reconciliation — return

```text
PROBABILITY_CONTRACT:  CORRECTED — World Model owns the distribution INCLUDING versioned dynamics;
                       Multiverse executes and may use sampling weights with declared proposal,
                       target, correction, effective sample size and validation; stress stays separate
ENVIRONMENT:           dedicated root-owned /opt/apex-research/venv (numpy==2.4.6) SPECIFIED;
                       production venv UNTOUCHED; interpreter + third-party provenance now RECORDED per run
DATASET_ISOLATION:     containment PROBED read-only — evaluation files unreadable at the FILESYSTEM level,
                       10/10 expectations met (results/si004_sandbox_probe.json)
DECISIONS:             consolidated from seven to THREE
RTH_OBSERVATION:       scheduled 2026-09-08T13:15:00Z; host time at check 2026-09-08T00:16Z; NOT YET FIRED
SETUP_EXECUTED:        NONE — no account, permission, mount, package, credential, admission or run
```

Base `9e4dc64cf`; final code `560fdc722`; bound source tree changed to
`616a191252be80aef59880a0c9f925de5f010ee44a65550975604009a4bb7545`
(the proposal's `source_tree_sha256` is updated to match).

## 1. RTH observation — by absolute time, and my stale wording corrected

- Observer `pid 1714883` is **alive**, started `2026-09-07 17:54:06 UTC`.
- Its target is absolute and unchanged in the script:
  `T=$(date -u -d "2026-09-08T13:15:00Z" +%s)`, then a wait loop, then a
  3,600 s observation across the 13:30Z open.
- **Host time at this check: `2026-09-08T00:16Z`.** The target is therefore
  **≈13 hours ahead, later today** — my previous "fires tomorrow" was
  written on 2026-09-07 and was stale by the time you read it. Corrected.
- **Artifact: none yet.** `/apex-data/tmp/m1_rth/` does not exist. I checked
  whether that would break the write and it will not: the observer runs
  `mkdir -p /apex-data/tmp/m1_rth` itself *after* the wait, immediately
  before writing. No defect; no action needed.
- **Result: NOT YET AVAILABLE.** No second observer launched, window
  untouched.

## 2. Probability contract — corrected

You were right that "the Multiverse never re-weights" was too rigid; it
would have forbidden correct Monte Carlo practice. Corrected in
`APEX_CANONICAL_ARCHITECTURE_V2.md` §A2 and `APEX_INTERFACES_V0.md` §2:

- The **World Model owns the forecast distribution** — latent state,
  parameters, weights over competing models, **and the versioned transition
  model**, because dynamics are part of what the forecast *means*. The
  interface now carries `transition_model {id, version, source}`.
- The **Multiverse executes** that contract and **may** use computational
  sampling weights — importance sampling, stratification, antithetic or
  common random numbers, rare-event tilting — provided each declares its
  **proposal** and **target**, carries the **correction** with the samples,
  reports **effective sample size after weighting**, and is **validated**
  against a case with a known answer.
- What stays prohibited is a change to the target distribution the World
  Model did not author: silent re-weighting, tilting to make an outcome
  look likelier, or reporting proposal-distribution quantities as the
  forecast. *A weight whose provenance and correction are not recorded is
  not a sampling weight; it is an unauthorised edit.*
- **Stress branches remain entirely separate** and never acquire probability
  mass — computational weights included: a stress branch is not a rare event
  being sampled efficiently, it is a scenario with no assigned probability.

## 3. Environment isolation — dedicated, production venv untouched

Measured: the research path loads **exactly one** third-party package,
`numpy 2.4.6`, pulled in by `apex/world_model/__init__.py` and **never
called** by EXP-001B (which is pure `math`/`statistics`), plus
`/etc/python3.12/sitecustomize.py`.

Chosen: a **separate root-owned `/opt/apex-research/venv`** built from the
system interpreter with `numpy==2.4.6` pinned. `/opt/apex/shared/venv` is
**not modified** and no package is installed into it. (My earlier draft
suggested re-owning the production venv; that is withdrawn.)

Provenance is now **recorded rather than asserted** (`560fdc72`):
`_RUN.json` carries the interpreter (realpath, version, **sha256 of the
binary**, venv-or-not, site-packages on `sys.path`) and every loaded
non-stdlib module with version, file and origin.

**A defect I introduced and caught by reading the output rather than
trusting the test:** the first version classified library roots by prefix,
but in a virtualenv `sysconfig` `platstdlib` *is* the venv root and
`site-packages` sits underneath it — so every installed package was
silently swallowed and numpy did not appear. Site roots are now matched
first, and the test was strengthened from a structural assertion to a
**positive capture** assertion: numpy must be present with its real
version. The passing structural test had not caught it.

**Trusted parties, stated:** the administrator and any root-capable account
(today including `apex`) are **trusted** and unconstrained by any of this.
Isolation is enforced against exactly one identity — the new
`apexresearch` account.

## 4. Dataset isolation — measured, not claimed

You were right that world-readable corpora mean loader refusal is not
filesystem isolation. The launch now uses the existing containment
(`systemd-run`, `wmresearch.slice`) with a **restricted dataset view**.

Two facts forced the design, both measured:

- `/apex-data/history-b` is **its own volume** (`/dev/sda`) and
  `/apex-data/research` is on the root volume, so hardlinks across them are
  impossible — reproduced as `Invalid cross-device link`.
- The view is therefore **copies**: ~145 MB for the 1,511 admitted SPY
  sessions on a volume with 143 GB free. Copies are strictly safer than
  hardlinks (the run cannot touch corpus inodes even in principle) and every
  file is verified byte-for-byte against the manifest at read time. The
  corpus itself is **not modified** and its permissions are untouched.
- Alternative paths checked: **no symlinks** anywhere in the corpus bars
  directory, and the verification step re-checks `find -type l` on the view.

Probed read-only as a **non-root** user (`results/si004_sandbox_probe.json`,
`scripts/si004_sandbox_probe.sh`), 10/10 expectations met:

| Check | Result |
|---|---|
| admitted session readable | ✅ yes |
| **evaluation-period file readable** | ✅ **no — filesystem level, before any loader check** |
| other corpus files / `integrity.jsonl` visible | ✅ no |
| `/apex-data/core`, `/apex-data/history-a` | ✅ inaccessible |
| `/home/apex/.apex-secrets` | ✅ not readable |
| corpus writable | ✅ no |
| manifest readable | ✅ yes |
| network | ✅ none |
| `git status` on a read-only checkout | ✅ works (rc 0) when ownership matches |

The first probe ran as **root** and was misleading — `InaccessiblePaths`
was bypassed by DAC and git failed with "dubious ownership". Re-probed
non-root, which is the arrangement that will actually run. Two fixes came
out of it: `/apex-data/history-a` and `/apex-data/runtime` added to
`InaccessiblePaths`, and `GIT_CONFIG_GLOBAL=/dev/null`,
`GIT_CONFIG_NOSYSTEM=1` set so source identity cannot be influenced by user
or system git configuration.

**What this provides and does not:** it prevents the *research identity*
from reading evaluation data, other corpora, evidence or credentials, from
writing the corpus, and from reaching the network. It provides **nothing**
against the administrator or any root-capable account. Evaluation data is
now covered by two independent refusals — temporal scope plus
`CALENDAR_NOT_VERIFIED` in the loader, and non-presentation by the
filesystem.

## 5. Decisions: seven → three

`RESEARCH_ACTIVATION_PACKAGE.md` §8. The rest were implementation choices
and are made here against measurement (copy view; no ACL work — `setfacl`
is absent and the corpus is already world-readable and non-writable to a
non-`apex` account; `/etc/apex` as trust root; dedicated environment rather
than touching production).

| # | Decision | Concrete effect |
|---|---|---|
| **D1** | Approve **authorization A** (operational setup) | the isolated runner exists; still no data access, no run |
| **D2** | `numpy==2.4.6` from the package index **or** `--system-site-packages` (distro numpy 1.26.4) | the first reproduces the environment the regression ran under; the second requires re-running the applicable regression under it first |
| **D3** | Approve **authorization B**: issue the signed decision, key generated and held off-host | the run becomes possible; the run still verifies everything itself |

## 6. The package

`docs/RESEARCH_ACTIVATION_PACKAGE.md` — one executable package with the
four authorizations kept separate (**A** setup · **B** signed admission ·
**C** train/validation execution · **D** evaluation unsealing, not part of
this package), exact commands and targets, verification run **as the
research user**, rollback that removes capability but deliberately leaves
sealed evidence, resource limits, and the full run identity. It states
plainly that no operator declaration substitutes for verification: the
command still checks signature, ancestor chain, verifier provenance,
manifest and per-file hashes, scope, source identity before and after, and
import bytes, and refuses regardless of what setup was believed to have
established.

## 7. Commits, tests, preservation

| Commit | Content |
|---|---|
| `560fdc722` | interpreter + third-party provenance recorded per run; venv path-matching defect fixed; positive-capture test |
| `50f6664ae` | probability-contract correction, activation package, sandbox probe script + artifact, updated proposal, this return |

Applicable bounded regression on `560fdc72` (24 modules touching
`world_model`, `chain_ledger` or `exp001`, one contained shard each, as
`apex`, `MemoryMax=1400M`):

```text
24 modules, 24 rc=0, 742 passed, 0 failed, 0 errors; 00:16:42Z -> 00:25:16Z; MemoryMax=1400M per shard, User=apex
test_bounded_regression 12 | test_exchange_calendar 34 | test_exp001_economic_path 12 | test_exp001_engineering 13
test_exp001b_temporal 12 | test_ledger_concurrency 4 | test_live_book 17 | test_real_data_boundary 45
test_result_audit 37 | test_result_validator 164 | test_verification_law 12 | test_world_model_authority 24
test_world_model_bootstrap 24 | test_world_model_contracts 86 | test_world_model_court 30 | test_world_model_inference 17
test_world_model_r3 13 | test_world_model_r4 8 | test_world_model_r5 13 | test_world_model_r51 9
test_world_model_r7 11 | test_world_model_r71_qualification 13 | test_world_model_teststand 43 | test_world_model_worlds 89
```

(742 vs 740 last pass: the two added environment-provenance tests. Scope
unchanged; the sealed World Model surface hash is re-pinned by
`test_result_audit`, `test_result_validator`, `test_world_model_r7` and
`test_world_model_r71_qualification` in this run.)

Preservation: production release `73fc712d`, three maintenance holds,
options-paper inactive with `ConditionResult=no`, orchestrator
success/NRestarts static, observer `1714883` alive and untouched, EXP-001B
registration `b3930727…` unchanged, sealed WM courts untouched,
`/opt/apex/shared/venv` unmodified, corpus permissions unmodified. No
account, admission, key or real-data execution exists.
