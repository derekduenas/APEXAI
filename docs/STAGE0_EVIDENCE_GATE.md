# Stage 0 — evidence gate (Live Trading Commissioning Ladder), 2026-09-12

**Outcome: the Stage 0 exit condition is NOT met. The block stops here per the ladder's standing rule.** Nothing was
tuned, nothing deployed, nothing entered Stage 1.

## 0a. Stage census at DEFAULT settings

Data: the collected SPY session 2026-09-11 (166 chain snapshots at 60 s, 09:30–12:15 ET; NBBO at 15 s; the session's
own 1-minute bars). Read-only copy; the reviewer requested this read. Script `scripts/stage0_census.py`, evidence
`docs/evidence/stage0_census_2026-09-11.json`. Defaults: `PILOT_RULE_V2` with the $5.00 cap, `FunnelEngine()` with
`strikes_each_side = 4`, the live default fee schedule (`UNVERIFIED`), no parameter changed.

### Rule path (the Monday policy, `PILOT_RULE_V2`) — counted on all 166 snapshots

| Stage | LONG | SHORT |
|---|---|---|
| chain rows (per snapshot, valid after normalization) | 331 → 331 (0 excluded, 0 conflicts) | same |
| on the signal's side of spot | 71 | 89 |
| cap-feasible (ask ≤ 5.00) | 63 | 74 |
| strike chosen (nearest feasible on the side) | **166 / 166** (K=773, 9 strikes out, ask ≈ 4.97 at the open) | **166 / 166** (K=749, 15 strikes out, ask ≈ 4.95) |
| certified approval at the LIVE default fee schedule | **0 / 166** — `FEE_SCHEDULE_UNVERIFIED: an unknown cost is not zero` | **0 / 166**, same reason |

Reading: the rule path is **not structurally impossible**. It constructs a feasible, cap-compliant trade on every
snapshot in both directions. Its zero is at certification and has one named cause: the fee document is not
authorized. That is an operator authorization gate, not hard law one. PRIME is not a stage on this path by design
(the rule never consults the Multiverse), so "PRIME census" does not apply to the Monday policy.

### Funnel path (`FULL_FUNNEL_V1` at defaults) — every 5th snapshot, 34 scans

| Stage | Count | Named reason |
|---|---|---|
| forecast refused (warm-up) | 6 | `FEATURE_UNAVAILABLE: rv_30 / ret_5` windows not complete before 10:00 ET (correct) |
| forecast produced | 28 | — |
| funnel fit | 0 | `INSUFFICIENT_HISTORY: 0 < 400 bars` (the variance fit needs ≥ 400 prior-session bars; the collection holds none) |
| candidates evaluated | 0 | no fit → no simulation → no candidate table |
| PRIME reached | **0** | `PRIME_ABSTAIN: UNSUPPORTED_STATE: INSUFFICIENT_HISTORY` on all 28 |
| proposal | 0 | — |

Reading: **zero at PRIME, and the cause is data absence, not structure.** The funnel's first stage requires seven
days of prior bars, which the pilot collector never gathered (it ran for one partial session) and which the live
bar client would fetch on Monday only once attached. Whether the funnel can construct a trade at defaults on real
data is therefore **UNDETERMINED**, not DEFECT. It cannot be determined from this session by any honest means, and
tuning `INSUFFICIENT_HISTORY` down would be exactly the failure this gate exists to catch.

### Joint path (`JOINT_FUNNEL_V1`)

0 by construction: no authorized R4 fit (R4-FIT-001/002 not granted). Recorded, not tuned.

### Gate ruling

The ladder's exit condition is "non-zero PRIME census at default". Funnel PRIME census: 0 (data absence). Rule path:
PRIME not applicable, trade construction 166/166, certification 0/166 (fees). **Exit condition not met → stop and
report.** The two facts the operator needs: the Monday policy can build trades; the funnel cannot be judged until a
bar-history feed exists, and it was never going to be the Monday policy.

## 0b. Saturday pull provenance — ESTABLISHED, no quarantine

`logs/nightly_pull.log`: pull 14:00:34Z, paper track 14:00:59Z, reality loop 14:07:23Z (2026-09-12). The automation
checkout's reflog: `main @ b9998d0` until `07:12:16 -0700` (14:12:16Z), when the repair branch was checked out. All
three steps began on **main `b9998d0`**; the reality loop (11 minutes) had imported its modules before the branch
switch. The premise that the pull ran from the repair branch is not supported by the reflog. The lake advance,
paper mark and resolutions stand as main's outputs. Noted as a hazard, not a defect: switching branches under a
running job in the same checkout is what the isolated worktree now prevents.

## 0c. DEPLOYMENT_DIVERGENCE_001 — classified; NOT closed (deploy is the operator's, and main is the wrong tree)

`docs/evidence/deployment_divergence_classification.json`, `git diff 73fc712 main`:

| Class | Added on main (absent from the deployed release) | Modified |
|---|---|---|
| EVIDENCE (evidence/, results/, docs/evidence/) | 2,085 | 1 |
| MODULE (apex/*) | 158 | 11 |
| SCRIPT | 109 | 3 |
| DOC | 107 | 1 |
| TEST | 75 | 10 |
| GUARD (risk certificate/kernel, sealing, gateway, permissions) | 4 | 1 |
| VALIDATOR (records, boundary, ledger, sanitizers) | 4 | 0 |
| OTHER | 7 | 1 |
| **Deployed-only files (unique code on the release)** | **0** | — |

The figure "232 files short" is not the divergence from main; it was the pruning of the candidate relative to its
own lineage. Against main the deployed release lacks **2,549 files and differs in 28**, and carries no unique code.

**Not deployed, for two reasons.** Deployment is an operator action that every prior block reserved, and the
instruction "deploy from main NOW" would install `b9998d0`, which predates the decision-path repair (adverse-IV sign,
unreachable spread gate, PUT-manufacturing normalizer) and the weekend candidate. The tree to deploy is the reviewed
candidate after merge, with the book flat. `CONVENTIONS-AMENDMENT-A-012.md` ("no release change while a position is
open") is drafted for your acknowledgement. Deployed hash ≠ main hash, by design, until you say which tree.

## What Stage 0 leaves on your desk

1. Authorize the fee document (`ROBINHOOD_RHF_2026`, from the broker PDF, digest `7f9c86bf…`). It is the only thing
   between the rule path and a certified intent.
2. Say which tree to deploy (the merged reviewed candidate) and when (book flat). A-012 acknowledgement.
3. Decide whether the funnel census should be produced on Monday's live bar history (which requires attaching the
   client under `LiveWiring`) or whether the ladder proceeds on the rule path, for which PRIME is not a stage.
4. Your two numbers: maximum loss per position and per day, for Stage 3.
