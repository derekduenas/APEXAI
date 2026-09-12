# APEX — architecture addendum and research activation preparation — return

```text
ADDENDUM_A:              DOCUMENTED; four interfaces SPECIFIED_NOT_IMPLEMENTED; four challengers registered
RESEARCH_IDENTITY:       PREPARED — privilege paths of the current account MEASURED; setup, verification
                         and rollback commands written and NOT executed; no account, permission, trust,
                         service or hold change performed
EXP_001B_REGISTRATION:   UNCHANGED (b3930727…); scope unchanged; still unexecuted on real data
BOUND_SOURCE_TREE:       UNCHANGED (24322971…) — this milestone touched no bound source file
REAL_DATA_ADMISSION:     NOT_AUTHORIZED · SIGNING_KEY: NOT_CREATED · EVALUATION: BLOCKED
RTH_COMMISSIONING:       PENDING (observer pid 1714883 alive, fires 2026-09-08T13:15Z, untouched)
PAPER_TRADING:           HELD ×3 · REAL_MONEY_EXECUTION: NOT_AUTHORIZED · REAL_MARKET_EDGE: NOT_ESTABLISHED
```

Base: `2af98967029ba66575eaf9c015ee4673ef335b6f` (resolved on the host, HEAD
of `strategic-integration-002`), bound source tree
`24322971f61bcf2c02d1f98d77aa3c2ea20f1695122af03779bd64e70316dd8c`, clean.

## 1. The closure's distinctions, carried forward verbatim

Recorded at the head of the architecture addendum (§A0) so a later reader
meets them before the new material:

1. Calendar verification covers **2016–2021 only**.
2. **Classifier parity ≠ calendar verification** — different evidence.
3. **File-size corroboration is not proof of session contents** (10 of 12).
4. **Ordinary filesystem protection does not constrain an account with
   unrestricted sudo.** Your correction is applied in the operator package
   in two places: `/etc/apex/admissions` has no component replaceable *by
   ordinary filesystem operations* of that account, and is **not** protected
   from its passwordless sudo. The two claims are never merged.
5. **Before/after source verification detects persistent change**; it does
   not prove the absence of change-and-restore within a run, nor of
   privileged interference.
6. **EXP-001B has never executed on real data.**
7. **Evaluation remains separately blocked.**

No regression was rerun: this milestone changed documentation plus one
read-only audit script, and no test module imports that script. Failed
gates (gate 2 on `74003aef`) and the correction history stay in the
documents that recorded them.

## 2. Deliverable 1 — architecture addendum

`APEX_CANONICAL_ARCHITECTURE_V2.md`, Addendum A (updated in place, not
duplicated):

| § | Content |
|---|---|
| A1 | Twin holds sourced observations; **World Model** holds inference about latent state. `observations ~ observation_model(latent_state, measurement_uncertainty)` as a conceptual relation. Liquidity pressure, regime, positioning proxies and participant tendencies are estimates with provenance and uncertainty — **never written back to the Twin**. |
| A2 | Uncertainty ownership table: which layer owns starting state, parameters, model choice, disturbances, reactions and regime. **The World Model owns every probability weight; the Multiverse owns dynamics and never re-weights.** Weighted forecast, model disagreement, unweighted stress and LLM-proposed branches stay four separate things. Ensembles must report `effective_independent_members`, not member count. `simulation_error` and `model_uncertainty` are separate fields, and raising path count never reduces the second. |
| A3 | Empirical predictability map by target, horizon, regime, information tier, model version and evidence maturity; each cell needs a declared comparator, calibration, effective support with dependence treatment, an uncertainty interval around improvement, registered grouping rules and search accounting; `INSUFFICIENT_EVIDENCE` is an explicit state. Explicit prohibition on re-slicing until a subgroup looks good; any learned selection rule needs separate validation. |
| A4 | Decision-value-driven acquisition in PULSE: could this observation change a feasible decision enough to justify cost, latency and burden — with **information gain kept distinct from economic value**. Deterministic auditable priorities, human approval, no purchasing, no browsing, no learned policy. Missingness recorded so later research cannot mistake selectively collected data for an unbiased sample. |
| A5 | Attribution extended: observation/data-quality, latent-state, dynamics/parameter, omitted mechanism, regime change, expression/execution, and **outcomes already represented in the forecast** (not an error). All are diagnostic hypotheses; a losing trade does not identify its own cause. |
| A6 | Dashboard views 10–14 (observed vs inferred, assumed vs measured availability, uncertainty vs disagreement, evidence per map cell, acquisition cost/status). Not implemented, not restarted; engineering / historical / prospective-paper / live stay distinct. |
| A7 | **Overlap analysis** — what each refinement reuses, what is genuinely new, and what it must not duplicate. |
| A8 | What the addendum explicitly does not do. |

## 3. Deliverable 1b — interfaces

`APEX_INTERFACES_V0.md`, all four marked **`SPECIFIED_NOT_IMPLEMENTED`**:
`LATENT_STATE_ESTIMATE_V0`, `MULTIVERSE_PATH_SET_V0`,
`PREDICTABILITY_MAP_ENTRY_V0`, `INFORMATION_ACQUISITION_REQUEST_V0`. Each
carries its fields, its named refusals, its prohibitions and its activation
gate. No posterior probabilities were manufactured, no filter implemented,
no ensemble weighted, no acquisition automated. None is on the critical
path to EXP-001B.

`CHALLENGER_REGISTER_V0.md` gains C10–C13 (dynamical predictability
measures; sequential latent-state estimation; correlation-adjusted ensemble
weighting; decision-value-of-information scoring), each with the same eight
fields and an activation gate. C11 overlaps C1 by construction and the
register says so — at most one activates, and the record names which.

`IMPLEMENTATION_ROADMAP_V2.md` gains a §4 with seven component rows and
their gates, and restates that **the critical path is unchanged**: operator
setup → signed decision → EXP-001B train+validation → evidence.

## 4. Deliverable 2 — research execution identity (prepared, not executed)

`ADMISSION_OPERATOR_PACKAGE.md` Part II. The privileges of the account
research runs as today were **measured**, not assumed
(`scripts/research_identity_privilege_audit.py`, read-only;
`results/research_identity_privilege_audit_apex.json`):

| Property | Measured |
|---|---|
| groups | `apex`, **`sudo`**, `users` → can become root |
| sensitive paths reachable | `/opt/apex`, `/opt/apex/current`, `/opt/apex-repo`, `/apex-data`, `/apex-data/core{,/ops}`, `/apex-data/history-a`, `/apex-data/history-b`, `/home/apex/.apex-secrets`, `/opt/apex/shared{,/venv,/venv/lib}` |
| writable PATH dirs | none |
| unexpected setuid | none |
| **suitable as research identity** | **no** |

Three things the audit surfaced that the plan had to change for:

1. **`setfacl`/`getfacl` are not installed.** My first draft made corpus
   access read-only by ACL; that command would have failed. It is also
   unnecessary — the corpus directories are `apex`-owned and world-readable,
   so a non-`apex` account can already read and cannot write. The artifact
   now records `acl_tool_available: false` and states that a null ACL field
   means *unmeasured*, not *no ACLs*.
2. **`/opt/apex/shared/venv` is `apex`-owned, mode 0775.** The account could
   place an importable module into the environment a research run uses. That
   is irrelevant while `apex` *is* research, and load-bearing the moment it
   is not — so root-owning the venv (or a separate root-owned research venv)
   is now an explicit setup step with an alternative for the case where
   other units depend on it.
3. **The corpora are owned by the same account that would read them**, which
   is why "the data did not change" is caught by the manifest sha256 check
   rather than by ownership.

Part II gives: the identity requirements table; exact `adduser` /
verification / checkout / output commands; exact verification commands run
**as the new account** (privilege audit, trust audit, corpus readable and
not writable, venv not writable, secrets denied); exact rollback that
removes capability but deliberately leaves sealed run evidence; who signs
(off-host, authority's own key, never copied here) and how the public
material reaches the host (root session, fingerprint confirmed out of band);
and the full run package — reviewed commit, source commitment
`24322971…`, `ALPHA-EXP-001B`, registration `b3930727…`, manifest
`3ac8b250…` (2,679 sessions), train+validation only, `ASSUMED_BAR_CLOSE`
restriction, output location, `MemoryMax=1400M` containment, the four
expected process outcomes, and the evidence returned.

Stated in the package: **no operator declaration substitutes for
verification** — the command still performs every check itself and refuses
regardless of what setup was believed to have established. And: a passing
audit is evidence about the paths it enumerates, not proof that no
privilege path exists.

## 5. Commits and document checks

| Commit | Content |
|---|---|
| `52d419bc0` | `scripts/research_identity_privilege_audit.py` (read-only audit) + `results/research_identity_privilege_audit_apex.json` |
| `4a3950754` | Addendum A, `APEX_INTERFACES_V0.md`, C10–C13, roadmap §4, operator package Part II + wording correction, this return |

Document checks performed:

- bound source tree **unchanged** at `24322971…` before and after (the audit
  script and `results/` are outside `RELEVANT_SOURCE_PATHS`; the admission
  proposal's `source_tree_sha256` therefore still applies);
- `apex/` untouched — no file under it modified in this milestone;
- EXP-001B registration hash unchanged and its module untouched;
- existing canonical documents **updated in place**; the only new documents
  are the interface specification and this return;
- every new interface and roadmap row carries an explicit
  `SPECIFIED_NOT_IMPLEMENTED` status and an activation gate.

## 6. Decisions still required (short list)

| # | Decision | Who | Blocks |
|---|---|---|---|
| 1 | Accept or reject the EXP-001B admission package as reviewed | admission authority | everything downstream |
| 2 | Approve the research-identity arrangement, including whether to root-own `/opt/apex/shared/venv` or build a separate research venv | operator | running the experiment as a non-privileged account |
| 3 | Name the signing principal and confirm the key is generated and held **off-host** | admission authority | signing at all |
| 4 | Decide whether `/etc/apex` is the right trust root for this host, or whether trust material should live off-host entirely | operator + authority | Part I items 1–4 |
| 5 | Whether to install the `acl` package for stricter corpus isolation, or accept world-readable corpus + non-`apex` account | operator | nothing today; a hardening choice |
| 6 | Enforce N0 on the evaluation branch, and extend calendar verification to 2022–2024 | reviewer | opening evaluation later |
| 7 | Which Addendum A interface (if any) a future registered hypothesis will name first | reviewer | nothing now; sequencing later |

Nothing in this milestone requested or performed admission issuance,
account creation, permission change, service change, hold removal or a
research result.
