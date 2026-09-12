# Milestone 1 — three points made explicit

## 1. Environment attribution: two different causes, not one

Both tests failed in the shared checkout during recovery-candidate work.
They have nothing in common beyond that, and conflating them would hide a real
finding.

### A. `test_sac1_10_a_swarm_view_in_a_replay_record_trips_the_wire`
**Cause: a hard-coded interpreter path in the test, at the deployed base.**

At the deployed release the test spawns a child process with a literal
`.venv/bin/python`. No checkout on this host has an in-tree virtual
environment — not the shared checkout, not either dedicated worktree — so the
child cannot start and the test fails with `FileNotFoundError`.

| Where | Result | Why |
|---|---|---|
| Clean worktree at the deployed commit, no R1/R2 | FAIL | the hard-coded path |
| Shared checkout on the recovery candidate | FAIL | the same |
| Shared checkout on the development line | PASS | already fixed upstream |
| Dedicated integration worktree | PASS | already fixed upstream |

**What makes it pass:** not an environment change. A commit between the
deployed release and the integration candidate replaced the literal path with
`sys.executable`, with the comment that the suite runs under whichever
interpreter invoked it. The fix already exists on the development line.

**What would make the deployed-base version pass:** creating an in-tree
`.venv/bin/python`. I did not do that and recommend against it. Manufacturing
an environment to satisfy a hard-coded path is the wrong direction; the
upstream fix is correct.

**Note the pattern.** This is the same defect class as the provenance gap in
R1's multiprocess test, which the reviewer caught: a literal path deciding
which interpreter or checkout a child process uses. It has now appeared twice.

**RESOLVED under a narrow authorized scope extension.** The upstream fix has
been ported into the recovery candidate as its own commit,
`07dcbb05caf58f1ac714bb3fe87e16d46aeb98d8`, test-only, from source commit
`b53042bcb3293a73efa0391de7264d31a194e06a`.

Only the interpreter hunk was carried. That upstream commit also adds an
`import sys` and the same comment to `test_every_declared_launchd_job_has_a_plist_on_disk`,
which does not use `sys` — it reads `_sys.platform` through an alias imported
elsewhere — so that import would be unused and the comment would describe a
change not present in that function. Omitting it is deliberate and recorded.

Preserved, measured against the deployed base: assertions 65 to 65, test
functions 31 to 31, skip markers 3 to 3, lines 565 to 568. No in-tree virtual
environment was created; manufacturing an environment so a hard-coded path
resolves is the wrong direction.

### B. `test_the_prompt_carries_only_explicit_context`
**Cause: an untracked runtime artifact in the shared checkout.**

The test asserts the word "first" does not reappear in a rebuilt prompt. The
file `results/edgeforge/research_board.jsonl` — untracked at both bases, a
runtime artifact of earlier work — contains a note beginning "I first read this
as ~hourly restarts". The prompt builder pulls the board in, and the assertion
matches that text.

| Where | Result |
|---|---|
| Clean worktree at the deployed commit | PASS |
| Shared checkout on the recovery candidate | FAIL |
| Dedicated integration worktree | PASS, 17 of 17 in the module |

**What makes it pass:** a checkout containing no untracked runtime artifacts,
which is exactly what a dedicated worktree is. Nothing about the code changed.

**The distinction that matters:** A is a defect in the test, fixed upstream. B
is not a defect at all; it is a dirty working tree. A survives into a clean
environment; B does not. This is why the submitted results come from dedicated
worktrees with a before-and-after manifest, and why neither failure is carried
into the candidates' recorded results.

## 2. Candidate scope: what "four files match" means

The inventory is **two production files plus their two test files**. Not four
production files.

**Updated after the authorized scope extension.** The recovery candidate now
carries five files relative to the deployed release: **two production files,
two new test modules, and one existing-test portability fix**.

| File | Role | Change |
|---|---|---|
| `apex/governance/chain_ledger.py` | production, shared primitive | R1 |
| `scripts/apex_orchestrator.py` | production, the daemon | R2 |
| `tests/test_chain_tail_bounded.py` | test | new, R1 evidence |
| `tests/test_orchestrator_incident_history.py` | test | new, R2 evidence |
| `tests/test_sac1_tier1.py` | test | portability fix, ported from upstream |

Only the first two ship as executable production code. The rest are tests.

The first four are byte-identical between the integration and recovery
candidates, which is why R1 and R2 can be discussed as one change across both.
The fifth differs: the integration candidate already carried the upstream fix
through its normal history, while the recovery candidate now carries an
equivalent, narrower port of it.

None of this is a basis for transferring a regression result between them. The
candidates sit on different bases, 37 commits apart, and each was tested on its
own tree with its own source manifest.

## 3. Availability: the finance plugins and Context7 are different answers

**The seven finance plugins are UNAVAILABLE in this Claude Code session.**
The operator has confirmed they were installed in Claude Chat, not in Claude
Code, which explains the observation exactly: they are real installations that
this session cannot reach. No plugin setup is needed for this milestone, and
none was attempted. Finance,
Financial Analysis, Wealth Management, Bigdata.com, Daloopa, LSEG and S&P
Global expose no tools and no skills here. Checked three ways: the session's
plugin listing is empty, no skill namespace matches any of them, and a tool
search for fundamentals, filings, earnings and pricing returns only the
pre-existing Robinhood connector. Nothing about their coverage, entitlements,
point-in-time semantics or licensing can be verified, and none of it should be
planned against. Installation on the operator's side does not make a capability
reachable by an agent session.

**Context7 IS available and answering.** Verified by a live call: a library
resolution for pytest returned ranked results.

One thing worth recording from that check. Context7's pytest entry documents
version 9.0.0; the candidate environment runs **pytest 9.1.1** on Python
3.12.3, with pandas 3.0.5 and numpy 2.4.6. Documentation is therefore one minor
version ahead of nothing and one behind the installed runtime, so where the two
could disagree I relied on the code and the tests rather than the documentation.
Nothing was upgraded to match the docs.

Neither R1 nor R2 turned on uncertain library behaviour. Both use only the
standard library — `json`, `hashlib`, `pathlib`, `subprocess`, `threading`,
`fcntl` — and every behavioural claim in this milestone is backed by a test
that runs against the installed versions.
