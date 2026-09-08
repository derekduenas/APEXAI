# RESEARCH ACTIVATION PACKAGE — one executable setup

**Nothing here has been executed.** No account, permission, mount, package,
credential, admission or run. Every command below was written against
*measured* host facts, and the containment composition was probed read-only
before being written down (`results/si004_sandbox_probe.json`).

This supersedes, for execution purposes, the step lists in
`ADMISSION_OPERATOR_PACKAGE.md`; that document remains the measurement
record and the background for why each step exists.

## 0. Four authorizations, deliberately separate

| # | Authorization | Who | Grants | Does **not** grant |
|---|---|---|---|---|
| **A** | Operational setup | administrator (root) | the isolated runner exists: identity, environment, checkout, dataset view, trust chain | any access to data by research; no experiment runs |
| **B** | Signed dataset admission | admission authority (off-host key) | *this* dataset, fields, universe, temporal range, experiment and code identity may be read | execution; the run still verifies everything itself |
| **C** | Train/validation execution | operator, after A and B | one run of EXP-001B over train+validation | evaluation, economics, promotion |
| **D** | Evaluation unsealing | reviewer, later | opening 2022–2024 | anything else; today blocked twice over (§7) |

A without B reads nothing. B without A cannot verify (`TRUST_PATH_MISSING`).
C requires both and re-checks both. **D is not part of this package.**

## 1. Trust model — who is trusted, and against whom isolation is enforced

- **Trusted:** the administrator, and any account that can become root
  (today that includes `apex`, which holds full passwordless sudo). Nothing
  in this package constrains them, and it does not try to.
- **Isolation is enforced against exactly one identity:** the new
  `apexresearch` account under which the experiment runs. That is the
  account that must not reach evaluation data, secrets, the corpus for
  writing, the trust chain, or the network.
- Therefore: `/etc/apex/admissions` resists **ordinary filesystem
  replacement by `apexresearch`**. It does not resist `sudo`, and no claim
  here should be read that way.

## 2. Step A1 — dedicated research environment (do NOT touch the production venv)

The production venv `/opt/apex/shared/venv` is left exactly as it is:
`apex`-owned, 15 packages, used by the orchestrator and the test harness.

Measured: the research run path loads **exactly one** third-party package —
`numpy 2.4.6` — plus `/etc/python3.12/sitecustomize.py`. numpy is pulled in
by `apex/world_model/__init__.py` (the synthetic-lab models) and is **not
called** by the EXP-001B path, which is pure `math`/`statistics`.

```bash
sudo install -d -o root -g root -m 0755 /opt/apex-research
sudo /usr/bin/python3.12 -m venv /opt/apex-research/venv
echo 'numpy==2.4.6' | sudo tee /opt/apex-research/requirements.txt
sudo /opt/apex-research/venv/bin/pip install --no-cache-dir -r /opt/apex-research/requirements.txt
sudo /opt/apex-research/venv/bin/pip freeze | sudo tee /opt/apex-research/pinned.txt
sudo chown -R root:root /opt/apex-research && sudo chmod -R go-w /opt/apex-research
```

Root-owned and not writable by research, so the account cannot inject an
importable module into its own run. Provenance is then recorded **by the
run itself**: `_RUN.json` carries the interpreter (realpath, version,
sha256 of the binary, venv or not, site-packages on `sys.path`) and every
loaded non-stdlib module with version, file and origin.

*If the host has no package index at setup time*, the fallback is
`python3 -m venv --system-site-packages`, which yields the distro's
**numpy 1.26.4** — a different environment from the one the regression ran
under. That is acceptable only if the applicable regression is re-run under
it first. This is operator decision **D2** in §8.

## 3. Step A2 — identity and dedicated checkout

```bash
sudo adduser --system --group --disabled-password --shell /usr/sbin/nologin \
     --home /home/apexresearch apexresearch
sudo passwd -l apexresearch
id apexresearch                      # expect: only the apexresearch group

sudo install -d -o apexresearch -g apexresearch -m 0755 /apex-data/research
sudo install -d -o apexresearch -g apexresearch -m 0755 /apex-data/research/out
sudo git clone --no-hardlinks /opt/apex-repo /apex-data/research/checkout
sudo git -C /apex-data/research/checkout checkout --detach <REVIEWED_COMMIT>
sudo chown -R apexresearch:apexresearch /apex-data/research/checkout
```

`--no-hardlinks` keeps the clone's objects independent of `/opt/apex-repo`.
Ownership by `apexresearch` matters: git refuses a repository owned by
someone else (`dubious ownership`), which the probe reproduced.

## 4. Step A3 — restricted dataset view (the admitted files only)

Measured layout: `/apex-data/history-b` is its own volume (`/dev/sda`);
`/apex-data/research` is on the root volume, so **hardlinks across them are
impossible** (`Invalid cross-device link`, reproduced). The view is
therefore made of **copies** — ~145 MB for 1,511 SPY sessions, on a volume
with 143 GB free. Copies are strictly safer than hardlinks: the run cannot
touch the corpus inodes even in principle, and every file is verified
byte-for-byte against the manifest `sha256` at read time.

```bash
sudo install -d -o apexresearch -g apexresearch -m 0755 \
     /apex-data/research/dataset_view /apex-data/research/dataset_view/etf_continuous \
     /apex-data/research/dataset_view/etf_continuous/bars

# copy ONLY the admitted train+validation sessions (2016-01-04..2021-12-31, SPY)
cd /apex-data/history-b/etf_continuous/bars
sudo sh -c 'for f in SPY_201[6-9]-*.json SPY_202[01]-*.json; do \
      cp -p "$f" /apex-data/research/dataset_view/etf_continuous/bars/; done'
sudo chown -R apexresearch:apexresearch /apex-data/research/dataset_view
sudo chmod -R a-w /apex-data/research/dataset_view

# verify the view: count, date bounds, and content equality
ls /apex-data/research/dataset_view/etf_continuous/bars | wc -l          # expect 1511
ls /apex-data/research/dataset_view/etf_continuous/bars | sed -n '1p;$p' # expect 2016-01-04 .. 2021-12-31
ls /apex-data/research/dataset_view/etf_continuous/bars | grep -c 'SPY_202[2-9]'  # expect 0
cd /apex-data/history-b/etf_continuous/bars && \
  for f in $(ls /apex-data/research/dataset_view/etf_continuous/bars); do \
    cmp -s "$f" "/apex-data/research/dataset_view/etf_continuous/bars/$f" || echo "DIFFERS $f"; done
find /apex-data/research/dataset_view -type l                             # expect NOTHING: no symlinks
```

The original corpus permissions are **not modified**.

## 5. Step A4 — trust chain

Exactly as `ADMISSION_OPERATOR_PACKAGE.md` Part I items 1–4:
`/etc/apex/admissions` and `/etc/apex/admissions/trust` root-owned 0755;
`allowed_signers` root-owned 0644 holding only the authority's **public**
line; the signed decision and its `.sig` installed root-owned 0644. The
**private key never exists on this host** and is never generated here.
Public material reaches the host through a root session, and its
fingerprint is confirmed out of band:
`ssh-keygen -lf /etc/apex/admissions/trust/allowed_signers`.

## 6. Step C — the launch (authorization C; after A and B)

Composition probed read-only as a non-root user; measured results in the
table below.

```bash
sudo systemd-run --pipe --wait --collect --slice=wmresearch.slice \
  -p User=apexresearch -p Group=apexresearch \
  -p MemoryMax=1400M -p TasksMax=64 \
  -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes \
  -p PrivateNetwork=yes -p NoNewPrivileges=yes -p RestrictSUIDSGID=yes \
  -p TemporaryFileSystem=/apex-data/history-b \
  -p BindReadOnlyPaths=/apex-data/research/dataset_view/etf_continuous/bars:/apex-data/history-b/etf_continuous/bars \
  -p InaccessiblePaths=/apex-data/core \
  -p InaccessiblePaths=/apex-data/history-a \
  -p InaccessiblePaths=/apex-data/runtime \
  -p ReadOnlyPaths=/apex-data/governance \
  -p ReadOnlyPaths=/etc/apex \
  -p ReadWritePaths=/apex-data/research/out \
  --setenv=PYTHONPATH=/apex-data/research/checkout \
  --setenv=GIT_CONFIG_GLOBAL=/dev/null --setenv=GIT_CONFIG_NOSYSTEM=1 \
  --working-directory=/apex-data/research/checkout \
  /opt/apex-research/venv/bin/python scripts/alpha_exp_real_execute.py \
  --decision /etc/apex/admissions/<decision>.json --execute
```

| Property | Probed result (non-root) |
|---|---|
| admitted session files visible | only the view's contents |
| **an evaluation-period file readable** | **NO** — filesystem level, before any loader check |
| `integrity.jsonl` and other symbols visible | NO (tmpfs over `history-b`) |
| `/apex-data/core`, `/apex-data/history-a` | inaccessible |
| `/home/apex/.apex-secrets` | not readable (`ProtectHome`) |
| corpus writable | NO |
| manifest readable | YES |
| network | none (`PrivateNetwork`) |
| `git status` on a read-only checkout | works (rc 0) when ownership matches |

`GIT_CONFIG_GLOBAL=/dev/null` and `GIT_CONFIG_NOSYSTEM=1` both silence the
`ProtectHome` warnings the probe showed and make source identity
independent of any user or system git configuration.

## 7. What this protects, and what it does not

**Provides** (measured, not asserted): the research process cannot read
evaluation or reserve session files, other symbols, other corpora, live
evidence, or credentials; cannot write the corpus; cannot reach the
network; cannot gain privileges (`NoNewPrivileges`); is memory-bounded; and
writes only into its own output root.

**Does not provide:** protection against the administrator or any
root-capable account — including today's `apex`. It is not a security
boundary against privilege; it is a correctness boundary against the
research identity reading what it was not admitted to read.

**Two independent refusals now cover evaluation data**, and they are not
the same thing: the loader refuses by temporal scope and by
`CALENDAR_NOT_VERIFIED`, and the filesystem does not present the files at
all. Before this package, only the first existed, and world-readable files
meant the second claim could not be made.

## 8. Operator decisions that genuinely remain

Not seven. Three, each with a concrete effect:

| # | Decision | Concrete effect |
|---|---|---|
| **D1** | Approve authorization **A** (this package) | the isolated runner exists; still no data access and no run |
| **D2** | Research environment: pinned `numpy==2.4.6` via the package index, **or** `--system-site-packages` with distro numpy 1.26.4 | the first reproduces the environment the regression ran under; the second requires re-running the applicable regression under it first |
| **D3** | Approve authorization **B**: issue the signed decision, naming the reviewed commit and confirming the key is generated and held off-host | the run becomes possible; the run still verifies everything itself |

Everything else previously listed as a "decision" was an implementation
choice and has been made here against measurement: copy-based view (cross-
device hardlinks are impossible), no ACL work (`setfacl` is absent and the
corpus is already world-readable and non-writable to a non-`apex` account),
`/etc/apex` as the trust root, dedicated root-owned environment rather than
modifying the production venv.

## 9. Run identity (what authorization C approves)

| Item | Value |
|---|---|
| commit | `<REVIEWED_COMMIT>` on `strategic-integration-002` |
| source commitment | `source_tree_sha256 = 616a191252be80aef59880a0c9f925de5f010ee44a65550975604009a4bb7545` (48 files under the bound paths) |
| experiment / registration | `ALPHA-EXP-001B` / `b3930727334f24379f72df3919c98d689448b2f3f265b2fa6013559ee1bef5c9` |
| dataset manifest | `etf_continuous_SPY_manifest_v0.json`, sha256 `3ac8b250eefb47c5f66c7217508e1080f5f86ae5e4a63c20062a4e931a424c39` |
| scope | train 2016–2019 + validation 2020–2021 **only**; distributional only; no economic stage |
| availability restriction | `ASSUMED_BAR_CLOSE`; no publication or revision record; calendar reconciled for 2016–2021 only |
| environment | `/opt/apex-research/venv`, `numpy==2.4.6`, recorded per run |
| output | `/apex-data/research/out/ALPHA-EXP-001B/runs/<unique>` |
| limits | `MemoryMax=1400M`, `TasksMax=64`, no network |
| expected outcomes | `0 SCIENTIFIC_COMPLETE` (incl. `NO_SIGNAL`) · `4 EVALUATION_SEALED` · `3 AUTHORIZATION_REFUSED` · `5 INVALID_INPUT_OR_FAILURE` |
| evidence returned | `_RUN.json` (decision sha256, signer, source identity, import verification, interpreter and third-party provenance, trust chain), `_RESULT.json` (status, stages, per-period refusal counts, validation DM-HAC and N0, `acceptance_qualification`), sealed forecast ledger |

## 10. Rollback (removes capability, never evidence)

```bash
sudo rm -rf /apex-data/research/dataset_view /apex-data/research/checkout
sudo rm -rf /opt/apex-research
sudo deluser --remove-home apexresearch
sudo rm -rf /etc/apex                 # admission then refuses TRUST_PATH_MISSING
# /apex-data/research/out and its sealed runs are deliberately left in place
```

Nothing above touches the production venv, the release, the holds, the
orchestrator, the corpora or their permissions.
