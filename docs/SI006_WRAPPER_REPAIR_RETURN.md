# ACTIVATION WRAPPER — real action paths — return

```text
REPRODUCED:   4/4 of the reviewer's findings against the committed wrapper at 87948c1
WRAPPER:      RESEARCH_ACTIVATION_V1 — setup executes and verifies every stage; verify checks what
              exists; probe enters the sandbox; rollback cannot schedule evidence; launch implemented
TESTS:        27 behaviour tests with a controlled subprocess stand-in (was 29 description tests)
EXECUTED:     nothing — no account, directory, venv, package, view, admission or research run
```

The finding was correct and the defect was mine: `setup --apply` returned
exit 0 and recorded twelve objects as created while only the dataset view
existed. I had written the plan as command *strings* and then assigned the
plan to `created`.

## 1. Reproduction, against the committed code

`scripts/si006_reproduce_wrapper_gaps.py` →
`results/si006_wrapper_reproductions.json`, run against a worktree pinned at
`87948c122` with disposable fixtures. **4/4 reproduced:**

| # | Claim | Measured |
|---|---|---|
| 1 | setup records planned objects as created without creating them | exit 0, `applied: true`, **12 objects recorded**, `venv` absent, `checkout` absent, only the view built |
| 2 | verify succeeds with an absent account, environment and checkout | exit 0 with `account.present: false`, `venv` absent |
| 3 | probe executes nothing | exit 0, **0 `systemd-run` invocations** |
| 4 | rollback schedules evidence-containing parents | `/…/research` in `remove` while `/…/research/out` and `_ACTIVATION_MANIFEST.json` in `preserve`; same for `/…/runner` vs `pinned.txt` |

**This is distinct from `results/si004_sandbox_probe.json`,** which executed
a real `systemd-run` and measured actual containment. That probe remains
valid evidence for the configuration it tested; it was never the thing at
fault. The reproduction artifact says so in its own header.

## 2. Setup is now a staged operation

Twelve stages, each with an `execute` and a `verify`:
`research_root → out → account → own_research_paths → runner_root → venv →
requirements → packages → pinned → harden_runner → checkout → dataset_view`.

- Every action runs through a checked **argv list** (no shell) or a direct
  filesystem call; a non-zero exit raises.
- **An object is recorded only after its own verification passes** —
  `VENV_NOT_CREATED`, `PACKAGE_VERSION_MISMATCH` (imports numpy and compares
  to the pin), `REQUIREMENTS_CONTENT`, `CHECKOUT_COMMIT_MISMATCH`,
  `CHECKOUT_SOURCE_MISMATCH`, `VIEW_HASH_MISMATCH`, `IDENTITY_PRIVILEGED`,
  `OWNERSHIP_NOT_APPLIED`, `RUNNER_GROUP_OR_OTHER_WRITABLE`.
  A test drives a stand-in that reports success while creating nothing: the
  stage still fails and nothing is recorded.
- **Partial progress is persisted after every stage** (atomic replace, plus
  an append-only `_ACTIVATION_LOG.jsonl`), and a failure sets
  `state: PARTIAL_FAILED` with `failed_at`.
- `state: COMPLETE` is set only after all twelve verify.
- Dry run is the default: `state: DRY_RUN`, `created: []`, nothing touched.

## 3. Verify and probe do their jobs

**verify** requires `state == COMPLETE`, then checks the real account
(groups, no privileged group), the interpreter, the installed numpy version,
`pinned.txt`, that the runner tree is not group/other-writable, the checkout
commit **and** source hash, the full dataset inventory **re-hashed**, and
ownership/permissions. Tested: it fails on an absent account, a deleted
interpreter and a tampered view file.

**probe** builds the launch configuration, **invokes `systemd-run`**, runs
the access checks inside it, parses the results and compares them to
`PROBE_EXPECTATIONS`; any deviation, or a silent sandbox, raises
`PROBE_FAILED`. The denied example is a SPY file the manifest knows about
whose date is outside the admitted range — so the probe proves exclusion of
a file that exists. Tests assert the invocation happened, that the argv
carries `ProtectSystem=strict`, `PrivateNetwork=yes`, `NoNewPrivileges=yes`
and the `BindReadOnlyPaths` of the view, and that a violated expectation
fails.

## 4. Launch

`prepare_launch` requires `state == COMPLETE`, the five critical stages
present in the record, the requested commit equal to the recorded one, the
**working-tree** identity equal to the recorded source commitment, a clean
tree, the view count intact, the interpreter present, and a decision that
exists, is signed and sits under the trust root.

A test caught a real gap while I wrote it: my first version compared
*committed blobs*, so an edited working file passed. It now uses a
working-tree computation, and a test asserts that computation agrees
exactly with `apex.world_model.real_data.boundary.source_identity` —
otherwise a launch could pass here and be refused there.

`--apply` is **implemented**: it runs the command, captures the research
process outcome, and writes an immutable launch record into the output
root. It is exercised against a stand-in and **was not run for real**.

## 5. Rollback respects containment

`rollback_plan` computes evidence paths first, then, for each capability
object, refuses to schedule any directory that contains evidence: such a
parent is **preserved** with `why_preserved: PARENT_CONTAINS_EVIDENCE`, and
only its recorded capability **children** are removed. A final guard raises
`ROLLBACK_WOULD_REMOVE_EVIDENCE` if anything scheduled still contains
evidence. Trust material is preserved even when recorded as capability.

For the real layout: `/apex-data/research` and `/opt/apex-runner` are
**preserved** (they hold `out/`, the manifest, the log and `pinned.txt`);
`checkout`, `dataset_view`, `venv`, `requirements.txt` and the account are
removed. `--apply` is implemented and tested on fixtures: after it, the
capability objects are gone and `out/`, the manifest and the log all still
exist.

Refusals: `NO_SETUP_MANIFEST`, `SETUP_RECORD_CONTRACT`,
`SETUP_RECORD_INCONSISTENT`. After a partial setup, only what was verified
is scheduled.

## 6. Tests — behaviour, not descriptions

27 tests. The stand-in records **every command in order**, performs real
filesystem work, and emulates only what needs root or a package index.
Ordering is asserted (`adduser < venv < pip install < pip freeze < git
clone`), invocation is asserted, failure propagation is asserted, and the
creation record is checked against what is actually on disk. There is an
end-to-end `setup → verify → probe → launch(prepare) → rollback` on
disposable fixtures.

Focused only, as instructed: the wrapper is outside `RELEVANT_SOURCE_PATHS`
and no execution dependency changed, so the bound tree stays
`616a191252be80aef59880a0c9f925de5f010ee44a65550975604009a4bb7545` and the
full World Model regression was not rerun.

## 7. Real dry-run on production targets

```text
preflight  ok=true  blocking=[]  inventory=1511 (2016-01-04..2021-12-31, SPY)
           resolved_commit 87948c122 -> tree 616a1912…, 48 files
           non-blocking false: trust_root_present, allowed_signers_present (authority creates)
setup      state=DRY_RUN  created=[]  12 stages planned
verify     exit 3  NO_SETUP_MANIFEST
probe      exit 3  NO_SETUP_MANIFEST
rollback   exit 3  NO_SETUP_MANIFEST
setup (no --commit)      exit 3  UNRESOLVED_INPUTS
launch (no --decision)   exit 3  UNRESOLVED_INPUTS
setup --commit (dry run) exit 0
```

Exit codes were read directly, not through a pipeline — the first reading
showed `rc=0` because `$?` was `tail`'s.

After all of it: `/opt/apex-runner` absent, `/apex-data/research` absent,
`apexresearch` absent.

## 8. Still separate, still unauthorized

| | Authorization | Status |
|---|---|---|
| setup | **A** | prepared and now genuinely executable; **not executed** |
| signing | **B** | not issued; no key on this host |
| research execution | **C** | implemented; **not run** |
| evaluation unsealing | **D** | not part of this package |
