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
| `/etc` is root-owned (0755) and not writable by the research account | `/etc/apex/admissions` has **no replaceable component** |
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
the ancestor check passes for the first time.

## 7. What is still not protected, stated

- Anyone who can become root can defeat all of it. The checks are against
  ordinary replacement by the research account, not against privilege.
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
