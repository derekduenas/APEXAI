# Hard-coded path literals in the test suite — corrected count and a limitation of this milestone's own runs

## The reporting correction

An earlier summary of mine called this the "third instance" while naming only
two. That was wrong as written. I then scanned the suite rather than guessing,
and the true count is **higher**, not lower: **five occurrences across five
files**, in two related classes.

## The scan

Parse tree of every test module in the integration candidate, looking for
string constants naming an interpreter or a checkout root.

| # | File | Line | Literal | Class | Status |
|---|---|---|---|---|---|
| 1 | `tests/test_chain_tail_bounded.py` | — | checkout root, in a child's import path | interpreter/checkout | **fixed** — caught in review, now derived from `__file__` |
| 2 | `tests/test_sac1_tier1.py` | 441 | `.venv/bin/python` | interpreter/checkout | **fixed** — upstream fix ported into the recovery candidate |
| 3 | `tests/test_research_board.py` | 158 | `/opt/apex/shared/venv/bin/python` | interpreter/checkout | **OPEN** |
| 4 | `tests/test_whole_ledger_guard.py` | 43 | `/opt/apex-repo` as the audit subject | interpreter/checkout | **OPEN** |
| 5 | `tests/test_pulse_anchor_freshness.py` `tests/test_pulse_derived.py` | 20, 329 | `/opt/apex-repo/results/pulse007_frozen_packets.jsonl` | external fixture | **OPEN** |

So: two were already fixed during this milestone, and three remain open. None
is a defect in production code, and none is proposed for repair here — that
would be scope creep. They are registered.

## The part that bounds a claim I made

Items 4 and 5 read **outside the tree under test**. The provenance harness
gives each candidate a dedicated worktree, sets `PYTHONPATH` and the working
directory to it, and takes a manifest of every tracked file before and after.
That establishes the identity of the candidate's own source. It does **not**
cover a test that reaches out to an absolute path elsewhere on the host.

Three shards in the integration run do exactly that:

- `test_whole_ledger_guard.py` audits `/opt/apex-repo`, not its own worktree.
- `test_pulse_anchor_freshness.py` and `test_pulse_derived.py` open a frozen
  packet fixture from `/opt/apex-repo/results/`, unguarded — a bare `open()`
  with no existence check.

**This nearly corrupted my own run, through my own doing.** While the
integration regression was executing in its worktree, `/opt/apex-repo` was
checked out on the recovery candidate, which is based on the deployed release
and does not contain that fixture at all. Had those shards run in that state
they would have failed with `FileNotFoundError`, and the failure would have
said nothing about the candidate — only about which branch a different
directory happened to be on.

I caught it at shard 114 of 215, before the affected shards were reached, and
set `/opt/apex-repo` to the integration candidate commit `3b9a26f2` with a
clean tree. Recorded at the moment of the change:

```
/opt/apex-repo HEAD          3b9a26f2c949e7e53063eea7948f0422f1e573c0
candidate worktree HEAD      3b9a26f2c949e7e53063eea7948f0422f1e573c0
/opt/apex-repo tracked dirt  0
fixture sha256, both paths   8994d9191dd1fe187d2c770708b98a3cc78433bcd48a3d675bf8c0954de12f52
```

So the external dependency now resolves to content byte-identical to the
candidate's own copy, and the shards measure the candidate.

**Stated as a limitation, not smoothed over.** For those three shards the
result depends on an input outside the manifest's coverage. I set that input
deliberately and recorded its hash, which is the strongest available claim, but
it is weaker than the guarantee the other 212 shards carry. A reviewer should
read the integration result as: 212 shards whose source identity is established
by manifest, and 3 whose subject is an external path that was verified
byte-identical to the candidate at run time.

## What this suggests, without proposing it

The provenance harness could be strengthened to detect this rather than rely on
me noticing: scan the candidate for absolute-path literals before the run and
either fail, or record each one's resolved content hash as a declared external
input. That is a change to the harness, not to any candidate, and it is not in
this milestone's scope. Registered as the recommended follow-up.
