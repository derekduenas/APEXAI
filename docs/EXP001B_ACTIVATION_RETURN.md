# EXP001B-ACTIVATION-001 — RETURN

Branch `exp001b-activation-001`, based on `4e10e87` (BLS correction). Scope taken
from the CSO's strategic correction: stop turning each source defect into the next
project, review the activation wrapper independently, complete authorized setup,
and establish exactly what remains before EXP-001B can run.

---

## 1. INDEPENDENT REVIEW OF THE WRAPPER

V1 already fixed the V0 defect: it performs its actions rather than describing
them. The review asked the next question — **does each stage's verify test the
property the stage exists to establish, or something adjacent and cheaper?**

Four did not. Each was reproduced by a failing test before anything was changed.

| # | stage | what it checked | what it was for |
|---|---|---|---|
| 1 | `harden_runner` | mode bits only | the research account must not be able to modify the runner |
| 2 | `harden_runner` | two directories | its own action is `chmod -R` |
| 3 | `own_research_paths` | nothing, if the account was absent | ownership was applied |
| 4 | directory stages | reported the mode found | the mode requested |

**Finding 1 is the substantive one.** Mode bits are no defence against the *owner*,
who may `chmod` at will. A runner tree owned by the research account satisfies
every permission check while completely failing the property the stage exists for.
Ownership is the load-bearing fact and was the one fact not checked.

**Finding 3 is the V0 defect surviving in one verifier**: its only assertion sat
behind `if the account exists`, so a missing account made the stage a no-op that
still recorded `VERIFIED`. `run_verify` carried the same permissive conditional.

**Finding 4** required a change to the action as well: `mkdir`'s mode argument is
masked by umask, so an unenforceable expectation is not a check. The runner now
chmods explicitly.

### An honest limit, made explicit rather than quietly relaxed

The unprivileged test harness cannot hold two distinct uids, and its stand-in
`chown` is a no-op — so it **cannot exercise ownership separation at all**. That
blindness is exactly why the weak verifier survived review.

Rather than weaken the check to fit the harness, `Targets` now carries
`uid_separation_exercisable`. The harness sets it `False` and the waiver travels
into the evidence, so a record produced under it cannot be mistaken for a pass.
Production defaults to strict and the real property is proven on the host.

### Two further defects, found by running it rather than reading it

- **The verifier could not read the checkout it had just handed over.** Root clones,
  chowns the tree to the research account, then inspects it — and git refuses on
  dubious ownership. Fixed with an exception pinned to the one repo, and with the
  other account's global and system config neutralised.
- **The wrapper was single-shot and could not recover from its own partial
  failure.** Preflight demands untouched ground; rollback rightly refuses to delete
  a parent holding evidence. Together those left a partial run with no way forward
  and no way back. Setup is now resumable: it asks reality first, carries only
  stages whose objects satisfy their own verifier *now*, and performs the rest.
  Nothing is carried because a previous record claimed it — a test breaks a
  recorded object and asserts the resume rebuilds it.

---

## 2. AUTHORIZED SETUP — EXECUTED AND VERIFIED

Twelve stages complete. Independent `verify` afterwards, all checks passing:

| check | measured |
|---|---|
| identity | uid 109, **privileged groups: none** |
| environment | `/opt/apex-runner/venv/bin/python` |
| packages | numpy 2.4.6 |
| runner not writable by research | uid 0 across **2628 entries**, `uid_separation_checked: true` |
| checkout identity | commit `2b4860b5`, tree `616a1912…` |
| dataset inventory | **1511 files** |
| permissions | out owned by 109, view mode 755 |

`entries_checked: 2628` is the recursive ownership proof the harness could not
produce. This is the first time that property has actually been established.

### The probe entered the sandbox and measured

Nine properties, **zero deviations**:

```
admitted_readable            True     evaluation_readable        False
manifest_readable            True     other_corpus_files_visible False
core_readable                False    history_a_readable         False
secrets_readable             False    corpus_writable            False
network_reachable            False
```

The two that matter most: **the sealed evaluation period is unreadable from inside
the sandbox** (`SPY_2022-01-03.json` denied while `SPY_2016-01-04.json` is
readable), and **the network is unreachable**. The evaluation seal is enforced by
construction, not by discipline.

---

## 3. EXACTLY WHAT REMAINS BEFORE EXP-001B CAN RUN

Everything except one thing, and that thing is not mine to produce.

| requirement | state |
|---|---|
| research environment, account, venv, pinned packages | **DONE** |
| source checkout at a pinned commit and tree hash | **DONE** |
| dataset view, 1511 admitted sessions, hash-verified | **DONE** |
| sandbox isolation proven by entering it | **DONE** |
| manifest present and hash-matched (`3ac8b250…`) | **DONE** |
| trust root `/etc/apex/admissions` | **ABSENT — authority creates** |
| allowed signers `/etc/apex/admissions/trust/allowed_signers` | **ABSENT — authority installs** |
| **signed admission decision** | **ABSENT — authority signs** |

### Why I did not produce the signature

The boundary refuses a decision whose `decided_by` is `SELF`, `CALLER`, or
`ENGINEERING`. Self-admission is structurally impossible *by design*, and that
design is the product of the last several bricks. Creating the signing key and
signing my own admission would satisfy the check while destroying the property it
exists to protect — the same error as verifying mode bits while ignoring ownership,
committed at the level that matters most.

So the request is prepared and left unsigned: `results/exp001b_admission_request.json`.
Every field the boundary requires is present and filled from measurement, so the
authority has to **judge**, not hunt. It carries `decision: REQUESTED_NOT_GRANTED`
and no signature, and a test asserts it would be refused if it were ever presented
as an admission.

One field is deliberately `PENDING_FINAL_COMMIT`: the decision must commit to the
exact code that will run, which is the commit the authority approves.

### The three steps the authority takes

1. Create `/etc/apex/admissions`, root-owned, and install the allowed-signers file.
2. Review the request, author the decision with `decision: ADMIT` and real
   `provenance.decided_by` / `decided_utc`, and pin `code.commit`.
3. Sign it with `ssh-keygen -Y sign` and place decision and signature under the
   trust root.

Then `launch --apply` runs the frozen protocol. Preparation refuses on source
drift, view drift, a missing signature, or a decision outside the trust root — all
already covered by tests.

---

## 4. VERIFICATION

| check | result |
|---|---|
| activation + review tests | 40 passed |
| with the real-data boundary suite | 87 passed |
| broad regression (activation, boundary, exp001, catalyst, event, calendar) | 399 passed, 1 skipped |
| protected surfaces | **57 files, 0 drifted, 0 missing** |
| bound source tree | `616a1912…` unchanged |
| trust root / signing key | **not created** |
| admission | **not issued** |
| experiment | **not run** |
| alpha claim | **none** |

---

## 5. WHAT THIS DOES AND DOES NOT ESTABLISH

It establishes that the research environment is real, isolated, and measured, and
that the sealed evaluation period is protected by construction rather than by
intention. It establishes that the wrapper's verifiers now test the properties
they exist for.

It establishes **nothing whatever about whether APEX can make money.** No
experiment has run. The first governed historical result is one signature away,
and that signature is the operator's to give.

---

## 6. BLS — CLOSED AS A BOUNDED FOLLOW-UP

Per the correction, BLS is not pursued further here. The reviewer's qualification
was applied to the record at `4e10e87`: the rolling 24-hour reset is reported as an
**inference**, not a finding, and the document now states why it cannot be settled
from what we retain — nothing keeps the refused response bodies, only the rendered
error string. Persisting them is folded into QUOTA-001.

BLS is relevant to a future macro-event experiment. It is **not** a dependency of
the price-only EXP-001B, and it is not treated as one.
