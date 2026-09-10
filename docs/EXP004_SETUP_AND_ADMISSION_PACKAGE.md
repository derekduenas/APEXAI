# EXP-004 setup and unsigned admission package — for review BEFORE setup

**Nothing was created, signed, installed, or executed.** No environment exists
for EXP-004, no decision naming it has been signed, and no historical data has
been read by it. Preflight is read-only and created nothing.

Pinned to **`ea87faa42537a14678bb6fc5cb1e9aacc83cf40f`**, verified clean and
checked out into a frozen worktree; every artifact below was produced from that
worktree.

## 1. Identity at the pin

| | |
|---|---|
| candidate commit | `ea87faa42537a14678bb6fc5cb1e9aacc83cf40f` (`dirty: []`) |
| bound source tree | `8fbe6ed6155df0e4b8fb09f6dd8ce54c7e1cf064cea29592e08fa44a41996991`, 67 files |
| EXP-004 registration | `9155024f51825d13487cdc035432d85b357d22e39a40f967477873a7a6145bf9` — frozen, and the value the launcher resolves at the pin |
| execute script (bound) | `73aca971ce8fd16658bcd0b0c1e7c13b877cbb2981a3f9e40be499a79300f2c0` |
| **launcher (NOT bound)** | `823b0125b58b86ba653f0dfedf3c495dfe05cc7df79e4671c8717e4a57776b9e` — re-check this at setup |
| manifest | `3ac8b250eefb47c5f66c7217508e1080f5f86ae5e4a63c20062a4e931a424c39` |

## 2. Isolated targets, disjoint from every existing environment

| | EXP-004 | already in use |
|---|---|---|
| research root | `/apex-data/research-exp004` | `/apex-data/research`, `-rev2`, `-exp002` |
| runner root | `/opt/apex-runner-exp004` | `/opt/apex-runner`, `-rev2`, `-exp002` |
| research user | `apexresearch4` | `apexresearch` 109, `apexresearch2` 110, `apexresearch3` 111 |
| decision file | `/etc/apex/admissions/exp004_admission.json` | `exp001b_admission.json`, `exp001b_admission_rev2.json`, `exp002_admission.json` |

**Read-only preflight: `ok: true`, `blocking: []`, nothing created.** All
fourteen checks pass, including `identity_absent` (apexresearch4 does not
exist), all four `destination_free`, `manifest_hash 3ac8b250eefb47c5`,
`inventory_count 1511 selected, expected 1511`, and `commit_resolves ea87faa4…`.
Verified afterwards: the two directories still do not exist and `id
apexresearch4` still fails. Record: `results/exp004_preflight.json`.

## 3. Unsigned admission request

`results/exp004_admission_request.json`, sha256
**`290e4cce9e443a4aa9fb3b654e119083869e1e98f4340e851168ab658c1cdaeb`**.

`decision: REQUESTED_NOT_GRANTED`; provenance names no principal;
`decided_utc: null`. Scope: SPY, `alpaca_sip_raw_1m`, OHLCV + `event_time_utc`,
2016-01-04 → 2021-12-31, with roles **fit** (2016-01-04 → 2018-12-31) and
**development_EXPOSED** (2019-01-01 → 2021-12-31); evaluation and reserve
declared `SEALED; never requested`. The request states on its face that a
result would be an **exposed-data candidate screen** granting no sealed access,
and carries the memory qualification with its scope (including that the
governed path at registered scale has never been run).

**Dry-validated against the REAL boundary with a disposable key**, generated in
a temp directory and destroyed in the same process (`throwaway_key_destroyed:
true`). The real signing key was never on this host.

| Check | Result |
|---|---|
| as `ALPHA-EXP-004` | **grant issued** — commit `ea87faa4…`, manifest `3ac8b250…`, range 2016-01-04 → 2021-12-31, 2,679 manifest files |
| as `ALPHA-EXP-002` | `EXPERIMENT_MISMATCH: decision serves 'ALPHA-EXP-004', caller is 'ALPHA-EXP-002'` |
| as `ALPHA-EXP-001B` | `EXPERIMENT_MISMATCH: … caller is 'ALPHA-EXP-001B'` |
| EXP-004 with EXP-002's registration hash | `REGISTRATION_MISMATCH` |

## 4. Preservation checks

| Item | sha256 / state |
|---|---|
| `exp001b_admission.json` | `1eafbe1f…cd0fa2` |
| `exp001b_admission_rev2.json` | `28bc2859…6a9d11` |
| `exp002_admission.json` | `dd968c31…89b6` |
| `exp004_admission.json` | **ABSENT** — nothing installed |
| `allowed_signers` | `ae30f60d…83e0` unchanged |
| EXP-001B rev2 sealed result | `4b23021d…78c909` |
| EXP-002 sealed result | `0c397d70…f9ad3f` |
| EXP-001B aborted-run forecasts | `7a6cbe36…6a3407` |
| accounts | 109 / 110 / 111 present; `apexresearch4` **does not exist** |
| environments | three present; no `research-exp004`, no `apex-runner-exp004` |

Record: `results/exp004_package_checks.json`.

## 5. Generated operator commands

Produced by the pinned launcher, not typed by hand.

**Preparation — resolves and checks inputs, prints the plan, launches NOTHING:**

```
sudo -n /usr/bin/python3.12 scripts/research_activation.py launch \
  --research-root /apex-data/research-exp004 --runner-root /opt/apex-runner-exp004 \
  --research-user apexresearch4 --experiment ALPHA-EXP-004 \
  --commit ea87faa42537a14678bb6fc5cb1e9aacc83cf40f \
  --decision /etc/apex/admissions/exp004_admission.json
```

**Execution — runs the registered experiment inside the sandbox:** the same
command with `--apply` appended. That single flag is the only difference.

Both must be run from `/apex-data/research-exp004/checkout` **after** setup, and
after re-checking the launcher hash in §1.

## 6. Sequence from here, each a separate gate

1. **This package is reviewed** ← we are here; nothing has been created.
2. Setup (`setup --apply`) creates the account, runner venv, pinned checkout and dataset view; then `verify` and `probe`.
3. The operator signs the request **off-host** with `~/.ssh/apex_admission_ed25519` (fingerprint `SHA256:A9uPHHPKZSzeWcRkOGyAa6M1gHVJhj4fFKAAgrIgumI`) in namespace `apex-admission`, and installs the pair as root, mode 644. Claude holds no key.
4. Preparation is run and reviewed.
5. Execution is authorised **explicitly and separately**.

## 7. What a result would and would not be

A completed run yields a development-pool screen on **exposed** 2019–2021 data:
whether adding `F̃` improves the distributional score beyond the ingredients and
their product, under two matched dispersion specifications. It grants no sealed
access and is not confirmation. It is not evidence of alpha, options
profitability, GARCH value, or tradability. EXP-001B returned `NO_SIGNAL`;
EXP-002 was invalidated by its own registered control.
