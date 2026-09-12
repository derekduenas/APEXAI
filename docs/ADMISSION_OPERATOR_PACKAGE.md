# Admission operator package — exact minimal changes (NOT executed)

Engineering has performed none of these. They are the smallest set that makes
the boundary's claim true on this host. Every one requires privileges the
research work does not use, and the last one is the load-bearing item.

## 0. What was measured, not assumed

`results/si002_trust_path_audit.json` (produced on the host by
`scripts/si002_trust_path_audit.py`, which changes nothing):

| Finding | Measurement |
|---|---|
| `/apex-data` is owned by the research account (uid 1000, mode 0755) | so `governance/`, `admissions/` and anything under them **can be renamed away and replaced**, whatever the leaf's own owner and mode say. The earlier "root-own the admissions directory" instruction would not have worked. |
| replaceable components of the superseded admission root | `/apex-data`, `/apex-data/governance`, `/apex-data/governance/admissions` |
| `/etc` is root-owned (0755) and not writable by the research account | `/etc/apex/admissions` has **no component replaceable by ordinary filesystem operations** of that account. It is **not** protected from that account's passwordless sudo — see the next row. Ordinary-operation protection and privilege protection are different claims and are never merged here. |
| the research account holds **full passwordless sudo** | it can become root, so **no filesystem check is a boundary against it**; this is the one finding that code cannot fix |
| `/usr/bin/ssh-keygen` and its whole ancestor chain are root-owned, not group/other-writable | the verifier resolves to a trusted executable today |
| production verifier decision on today's host | `WOULD_REFUSE` — `TRUST_PATH_MISSING: /etc/apex` |

## 1. Create the trust chain (root)

```bash
sudo install -d -o root -g root -m 0755 /etc/apex /etc/apex/admissions /etc/apex/admissions/trust
```

## 2. Generate the authority key OFF this host

The signing key must never exist on the research host. On the admission
authority's own machine:

```bash
ssh-keygen -t ed25519 -f apex_admission_authority -C "apex admission authority"
```

Copy only the **public** line here.

## 3. Install allowed_signers (root)

```bash
printf '%s namespaces="apex-admission" %s\n' "<principal>" "$(cat apex_admission_authority.pub | cut -d' ' -f1,2)" \
  | sudo tee /etc/apex/admissions/trust/allowed_signers >/dev/null
sudo chown root:root /etc/apex/admissions/trust/allowed_signers
sudo chmod 0644 /etc/apex/admissions/trust/allowed_signers
```

`<principal>` must equal `provenance.decided_by` in the decision.

## 4. Sign the decision OFF this host, install it root-owned

```bash
# on the authority's machine, after filling code.commit and provenance:
ssh-keygen -Y sign -f apex_admission_authority -n apex-admission EXP001B_ADMISSION_DECISION.json
# then, here:
sudo install -o root -g root -m 0644 EXP001B_ADMISSION_DECISION.json     /etc/apex/admissions/
sudo install -o root -g root -m 0644 EXP001B_ADMISSION_DECISION.json.sig /etc/apex/admissions/
```

## 5. Create the research output root (research-writable, by design)

```bash
sudo install -d -o apex -g apex -m 0755 /apex-data/research
```

## 6. The load-bearing change: research must not be able to become root

Today the account that would run the experiment has `(ALL) NOPASSWD: ALL`.
While that is true, items 1–4 are hygiene, not a boundary: that account can
rewrite `allowed_signers`, the decision, the sealed run records, or this
paragraph. Removing `apex` from `sudo` is **not** the fix — the orchestrator
and the test containment use it. The minimal defensible change is a separate
unprivileged account for research:

```bash
sudo adduser --disabled-password --gecos "" apexresearch     # NOT in sudo, NOT in apex's groups
sudo install -d -o apexresearch -g apexresearch -m 0755 /apex-data/research
sudo git clone --shared /opt/apex-repo /apex-data/research/checkout   # dedicated, non-shared checkout
sudo chown -R apexresearch:apexresearch /apex-data/research/checkout
# run the experiment as that account:
sudo -u apexresearch env PYTHONPATH=/apex-data/research/checkout \
  /opt/apex/shared/venv/bin/python scripts/alpha_exp_real_execute.py --decision <path> --execute
```

With that account, `enforce_ownership` becomes meaningful: `/etc/apex/...`
is root-owned, the research account cannot write any component of it, and
the ancestor check passes for the first time. Until then, `/etc/apex`
protects against an unprivileged replacement that the current account does
not need to attempt.

## 7. What is still not protected, stated

- Anyone who can become root can defeat all of it, **including today's
  `apex` account via passwordless sudo**. Moving the trust root to
  `/etc/apex/admissions` stops ordinary filesystem replacement by an
  unprivileged account; it stops nothing that `sudo` can do. Item 6 is
  therefore not a hardening extra — it is the condition under which items
  1–5 mean anything.
- The output root and the checkout must be writable by research; their
  integrity rests on the before/after source check and the write-once run
  records, which a root-capable actor could still rewrite.
- Key custody is out of band. The verifier can only check that the research
  account owns no component of the trust chain.

## 8. Verification the operator can run afterwards (read-only)

```bash
sudo -u apexresearch env PYTHONPATH=<checkout> /opt/apex/shared/venv/bin/python \
  scripts/si002_trust_path_audit.py /tmp/audit.json
```

Expected once 1–6 are done: `production_trust_check: WOULD_PASS`,
`production_admission_root.research_account_can_replace_some_component:
false`, `can_become_root: false`.

---

# Part II — research execution identity (prepared, NOT executed)

Added at `2af98967`. Nothing below has been run: no account exists, no
permission changed, no trust material created. The privileges of the
*current* account were measured, not assumed
(`results/research_identity_privilege_audit_apex.json`,
`scripts/research_identity_privilege_audit.py`, read-only).

## II.0 What was measured about the account research runs as today

| Property | Measured value |
|---|---|
| groups | `apex`, **`sudo`**, `users` |
| privileged group memberships | `sudo` → can become root |
| sensitive paths reachable by ownership or group | `/opt/apex`, `/opt/apex/current`, `/opt/apex-repo`, `/apex-data`, `/apex-data/core`, `/apex-data/core/ops`, **`/apex-data/history-a`**, **`/apex-data/history-b`**, **`/home/apex/.apex-secrets`** |
| writable directories on `PATH` | none |
| unexpected setuid binaries | none (allowlist is conservative; its purpose is to surface unusual ones, not to certify standard ones) |
| **interpreter environment** | `/opt/apex/shared/venv` is **`apex`-owned, mode 0775** — the account can write the site-packages that any research run would import |
| ACLs | **UNMEASURED** — `getfacl`/`setfacl` are not installed on this host. A null ACL field in the artifact means "not measured", not "no ACLs". |
| **suitable as a research identity** | **no** |

Three consequences beyond sudo. This account **owns the corpora** it would
read, so "the data did not change" would be self-referential — the manifest
sha256 check is what actually catches a change. It can read
`/home/apex/.apex-secrets`, which holds broker and vendor credentials. And
it can write `/opt/apex/shared/venv`, so it could place a module that a
research run would import; that matters precisely once `apex` is no longer
the account running research. A research identity must have none of the
three.

## II.1 The smallest arrangement that works

| Requirement | Arrangement |
|---|---|
| dedicated non-sudo identity | new account `apexresearch`; primary group `apexresearch`; **no** supplementary groups at all |
| no signing credentials | never a member of any group owning `/etc/apex/**`; signing key never on this host |
| no broker credentials | `/home/apex/.apex-secrets` stays 0700 `apex`; `apexresearch` is not in group `apex` |
| corpus access | **read-only**, and it already is: the corpus directories are `apex`-owned mode 0755/0775 and world-readable, so a non-`apex` account can read and cannot write. No ACL is needed — which is fortunate, because `setfacl` is not installed here. |
| code | a dedicated checkout owned by `apexresearch`, never `/opt/apex-repo` (already refused by `SHARED_CHECKOUT`) |
| environment | the existing `/opt/apex/shared/venv` — but it is **`apex`-owned and group-writable today**, so either root-own it (`chown -R root:root`, mode 0755) or build a separate root-owned research venv. Until one of those is done, the `apex` account can inject an importable module into a research run. |
| output | `/apex-data/research`, owned by `apexresearch` |
| trusted signer configuration | `/etc/apex/admissions/**`, root-owned — Part I items 1–4 |
| containment | the existing `systemd-run --slice=wmresearch.slice -p MemoryMax=…` pattern, run **by the administrator**, not by research |
| separation of duties | administrative setup (root) and research execution (`apexresearch`) are different sessions, different accounts, different commands |

## II.2 Exact setup commands (administrator; NOT executed)

```bash
# 1. identity: no sudo, no supplementary groups, no login shell needed
sudo adduser --system --group --disabled-password --shell /usr/sbin/nologin \
     --home /home/apexresearch apexresearch
sudo passwd -l apexresearch
# verify it inherited nothing:
id apexresearch                       # expect: uid=… gid=… groups=apexresearch only

# 2. corpus: NOTHING TO DO. The corpus and manifest directories are already
#    world-readable and are not writable by a non-apex account. Verify only:
stat -c '%A %U:%G %n' /apex-data /apex-data/history-b \
     /apex-data/history-b/etf_continuous /apex-data/history-b/etf_continuous/bars \
     /apex-data/governance/admissions/manifests
#    (If stricter isolation is ever wanted: `apt-get install acl` first --
#     setfacl is NOT present on this host today.)

# 2b. interpreter: remove the apex account's write access to what research imports
sudo chown -R root:root /opt/apex/shared/venv && sudo chmod -R go-w /opt/apex/shared/venv
#    ALTERNATIVE, if other units depend on that venv being apex-writable:
#    build a separate root-owned venv for research instead and use it below.

# 3. dedicated checkout at the reviewed commit, owned by research
sudo install -d -o apexresearch -g apexresearch -m 0755 /apex-data/research
sudo git clone --no-hardlinks /opt/apex-repo /apex-data/research/checkout
sudo git -C /apex-data/research/checkout checkout --detach <REVIEWED_COMMIT>
sudo chown -R apexresearch:apexresearch /apex-data/research/checkout

# 4. output root
sudo install -d -o apexresearch -g apexresearch -m 0755 /apex-data/research/out
```

`--no-hardlinks` matters: a hardlinked clone shares object files with
`/opt/apex-repo`, which the research account must not be able to affect.

## II.3 Verification (administrator runs; read-only)

```bash
# privilege paths of the NEW account, measured as that account
sudo -u apexresearch /opt/apex/shared/venv/bin/python \
  /apex-data/research/checkout/scripts/research_identity_privilege_audit.py \
  /tmp/audit_research.json
# expect: privileged_groups [], sudo_can_become_root false,
#         sensitive_paths_reachable [] (or only /apex-data/research*),
#         writable_path_dirs [], suitable_as_research_identity true

# trust chain, measured as that account
sudo -u apexresearch /opt/apex/shared/venv/bin/python \
  /apex-data/research/checkout/scripts/si002_trust_path_audit.py /tmp/trust_research.json
# expect: production_trust_check WOULD_PASS, can_become_root false

# corpus is readable and NOT writable; the venv is not writable either
sudo -u apexresearch test -r /apex-data/history-b/etf_continuous/integrity.jsonl && echo READ_OK
sudo -u apexresearch test -w /apex-data/history-b/etf_continuous && echo WRITABLE_BAD || echo NOT_WRITABLE_OK
sudo -u apexresearch test -w /opt/apex/shared/venv/lib && echo VENV_WRITABLE_BAD || echo VENV_NOT_WRITABLE_OK
# secrets are unreachable
sudo -u apexresearch cat /home/apex/.apex-secrets/ALPACA_API_KEY_ID 2>&1 | grep -q denied && echo SECRETS_DENIED_OK
```

**A passing audit is evidence about the paths it enumerates, not a proof
that no privilege path exists.** It is not a substitute for the checks the
verifier performs at run time.

## II.4 Rollback (administrator; NOT executed)

```bash
sudo chown -R apex:apex /opt/apex/shared/venv      # only if 2b was applied and must be undone
sudo rm -rf /apex-data/research/checkout           # keeps /apex-data/research/out and its sealed runs
sudo deluser --remove-home apexresearch
sudo rm -rf /etc/apex                              # removes the trust root; admission then refuses
```

Rollback removes capability, never evidence: sealed run directories under
`/apex-data/research/out` are left in place deliberately.

## II.5 Who signs, and how the public material reaches the host

- **Signing happens off-host**, on the admission authority's own machine,
  with a key that is never copied here. Engineering does not hold it and
  does not generate it.
- **Only the public line travels**, and only into a root-owned file: the
  authority pastes it into `/etc/apex/admissions/trust/allowed_signers`
  through a root session (Part I item 3). Transport does not need to be
  confidential — it needs to be *authentic*, so the authority should confirm
  the key fingerprint out of band after installation:
  `ssh-keygen -lf /etc/apex/admissions/trust/allowed_signers`.
- **The signed decision and its `.sig`** are produced off-host and installed
  root-owned (Part I item 4). The research account never writes either.
- Engineering's role ends at preparing the unsigned proposal.

## II.6 The run package the authority approves

When the setup above is done and the decision is signed, the run is fully
named by:

| Item | Value |
|---|---|
| reviewed commit | `<REVIEWED_COMMIT>` on `strategic-integration-002` |
| source commitment | `source_tree_sha256 = 24322971f61bcf2c02d1f98d77aa3c2ea20f1695122af03779bd64e70316dd8c` (48 files under the bound paths) |
| experiment | `ALPHA-EXP-001B` |
| registration hash | `b3930727334f24379f72df3919c98d689448b2f3f265b2fa6013559ee1bef5c9` |
| dataset manifest | `etf_continuous_SPY_manifest_v0.json`, sha256 `3ac8b250eefb47c5f66c7217508e1080f5f86ae5e4a63c20062a4e931a424c39` (2,679 SPY sessions) |
| scope | **train 2016–2019 + validation 2020–2021 only**; evaluation and reserve are not in the decision |
| availability restriction | `ASSUMED_BAR_CLOSE`; no publication or revision record; the calendar is verified for 2016–2021 only |
| output | `/apex-data/research/out/ALPHA-EXP-001B/runs/<unique>` — write-once identity, authority and result records |
| resource limits | `systemd-run --slice=wmresearch.slice -p MemoryMax=1400M`, one process, no network use by the experiment |
| expected process outcomes | `0 SCIENTIFIC_COMPLETE` (incl. `NO_SIGNAL`) · `4 EVALUATION_SEALED` · `3 AUTHORIZATION_REFUSED` · `5 INVALID_INPUT_OR_FAILURE` |
| evidence returned | `_RUN.json` (decision sha256, signer, source identity, import verification, runtime), `_RESULT.json` (status, stages, validation DM-HAC and N0, `acceptance_qualification`), the sealed forecast ledger, and the refusal counts per period |

Command (to be authorized separately, not run here):

```bash
sudo systemd-run --pipe --wait --collect --slice=wmresearch.slice -p MemoryMax=1400M \
  -p User=apexresearch -p Group=apexresearch \
  --setenv=PYTHONPATH=/apex-data/research/checkout \
  --working-directory=/apex-data/research/checkout \
  /opt/apex/shared/venv/bin/python scripts/alpha_exp_real_execute.py \
  --decision /etc/apex/admissions/<decision>.json --execute
```

**No operator declaration substitutes for verification.** The command still
performs every check itself — signature, ancestor chain, verifier
provenance, manifest and per-file hashes, scope, source identity before and
after, import bytes — and refuses if any fails, regardless of what the
setup was believed to have established.
