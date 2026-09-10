# EXP-004 setup, verify and probe — records

**No signing, no `launch --apply`, no historical execution.** The EXP-004
output directory is **empty**. No decision naming EXP-004 exists on the host.

Pinned to `ea87faa42537a14678bb6fc5cb1e9aacc83cf40f` throughout.

## 0. Two reporting corrections carried in first

- **The disposable key.** The helper previously set `throwaway_key_destroyed: true` *before* cleanup and then suppressed cleanup errors — that established an attempt, not destruction. It now records observations taken **after** cleanup: `temp_dir_removed_observed`, `private_key_absent_observed` (both `true`), with a note that `shutil.rmtree(ignore_errors=True)` can fail silently and that these are existence checks, not proof of removal. Rebuilding the request produced a **byte-identical** document, sha256 `290e4cce…1cdaeb`.
- **Wording.** "Nothing signed" was wrong: the dry validation *did* sign, with a disposable key. The correct statement is **no PRODUCTION admission has been signed**, and the production signing key has never been on this host. The helper's docstring said the key was "destroyed before this script exits"; that sentence is corrected too.

Neither correction moved the launcher or the experiment pin: the bound tree is
still `8fbe6ed6…96991`.

## 1. Launcher hash checked BEFORE invoking it

```
expected 823b0125b58b86ba653f0dfedf3c495dfe05cc7df79e4671c8717e4a57776b9e
actual   823b0125b58b86ba653f0dfedf3c495dfe05cc7df79e4671c8717e4a57776b9e   -> OK
```

Targets reconfirmed free immediately before setup: neither directory existed
and `id apexresearch4` failed. The same hash is present in the prepared
checkout afterwards.

## 2. Setup — `setup --apply`, all three targets explicit, 19 s

`results/exp004_setup_setup.json`. Twelve stages, all **VERIFIED**:
`research_root`, `out`, `account` (uid **112**, groups `[apexresearch4]`,
`privileged_groups: []`), `own_research_paths`, `runner_root`, `venv`,
`requirements` (`numpy==2.4.6`), `packages`, `pinned`, `harden_runner`
(runner root uid 0, 2,628 entries checked for uid separation), `checkout`
(commit `ea87faa4…`, tree `8fbe6ed6…`), `dataset_view` (1,511 files,
`SPY_2016-01-04.json` → `SPY_2021-12-31.json`).

## 3. Verify and probe — separate invocations, separate exit codes, separate files

| | exit code | record |
|---|---|---|
| `verify` | **0** | `results/exp004_setup_verify.json` |
| `probe` | **0** | `results/exp004_setup_probe.json` |

`verify`: `status OK`, `state COMPLETE`, all eight checks pass —
`identity` (uid 112, gid 115, `/usr/sbin/nologin`, no privileged groups),
`environment`, `packages`, `pinned`, `runner_not_writable_by_research`,
`checkout_identity`, `dataset_inventory` (1,511), `permissions`
(`out_owner_uid 112`, `view_mode 755`).

`probe`: `ok true`, `executed true`, **`deviations {}`**. Observations equal
expectations on every line: admitted readable; **evaluation not readable**;
other corpus files not visible; core, history-a and secrets not readable;
corpus not writable; manifest readable; **network not reachable**.
Admitted example `SPY_2016-01-04.json`; denied example `SPY_2022-01-03.json`.

## 4. Independent reconciliation

`results/exp004_setup_reconciliation.json`.

| Check | Result |
|---|---|
| **All 1,511 admitted files re-hashed against the manifest** | **1,511 recomputed, 0 mismatches, 0 missing, no out-of-range file present** |
| manifest inventory vs admitted view | 2,679 total entries, 1,511 in range, 1,511 in the view — the larger inventory authorises nothing outside 2016–2021 |
| checkout identity (verified **independently** of the launcher) | commit `ea87faa4…`, tree `8fbe6ed6…`, 67 files, `dirty []`, **matches the pin** |
| hashes inside the prepared checkout | launcher `823b0125…`, execute script `73aca971…`, registration `9155024f…` |
| ownership | research root, checkout, out, dataset_view owned by uid 112; runner root and venv owned by root, mode 755 |
| account restrictions | uid 112, gid 115, groups `[apexresearch4]` only, **no privileged groups**, shell `/usr/sbin/nologin`, **`sudo_permitted: false`** — "User apexresearch4 is not allowed to run sudo on APEX." |
| probe configuration | `MemoryMax=1400M` **unchanged**; every bind and read-write path names `exp004`; **no other environment named** in any property |
| **output directory** | **EMPTY** |
| `exp004_admission.json` | **ABSENT** |

**Method note:** the independent identity check initially failed with git's
"dubious ownership" because the checkout belongs to uid 112 while the check ran
as root. I ran it **as the owning account** rather than widening git's trust
with a global `safe.directory` exception.

## 5. Preservation of the existing environments

All unchanged: the three signed decisions (`1eafbe1f…`, `28bc2859…`,
`dd968c31…`), `allowed_signers` `ae30f60d…`, the EXP-001B rev2 sealed result
`4b23021d…`, the EXP-002 sealed result `0c397d70…`, the EXP-001B aborted-run
forecasts `7a6cbe36…`, accounts 109/110/111 (and now 112), and the other
environments' output directories.

## 6. State and next gates

Prepared and verified; **nothing signed, nothing executed, output empty**.

1. This record is reviewed.
2. The operator signs the request **off-host** with `~/.ssh/apex_admission_ed25519` (fingerprint `SHA256:A9uPHHPKZSzeWcRkOGyAa6M1gHVJhj4fFKAAgrIgumI`, namespace `apex-admission`) and installs the pair as root, mode 644, at `/etc/apex/admissions/exp004_admission.json{,.sig}`. Claude holds no key.
3. Preparation (`launch` without `--apply`) is run and reviewed.
4. Execution is authorised explicitly and separately.
