# RESEARCH ACTIVATION PACKAGE — one executable setup

**Nothing here has been executed.** No account, permission, mount, package,
credential, admission or run. Every command below was written against
*measured* host facts, and the containment composition was probed read-only
before being written down (`results/si004_sandbox_probe.json`).

This supersedes, for execution purposes, the step lists in
`ADMISSION_OPERATOR_PACKAGE.md`; that document remains the measurement
record and the background for why each step exists.

**Everything below is executed through one fail-stop wrapper**,
`scripts/research_activation.py` (`RESEARCH_ACTIVATION_V0`). The loose shell
snippets an earlier draft carried printed expectations and continued; the
wrapper *aborts*. A mismatched hash, a missing or extra file, a conflicting
destination, an unexpected identity or a partial setup each raise and exit
non-zero, and `launch` refuses to start unless a complete setup manifest
exists. Every command is dry-run by default and does nothing without
`--apply`.

## 0. Four authorizations, deliberately separate

| # | Authorization | Who | Grants | Does **not** grant |
|---|---|---|---|---|
| **A** | Operational setup | administrator (root) | the isolated runner exists: identity, environment, checkout, trust chain, and a dataset view **containing copies of the admitted train/validation bytes** | reading anything outside that view; **no statistical parsing and no experiment**. Setup *does* move historical bytes — it is not a no-data step, and calling it one would be false |
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

## 1b. Resolved inputs — no unchecked placeholders

Two values are supplied by people, and **both are validated before anything
happens**; the wrapper refuses non-zero if either is absent or unresolvable,
and the launch record carries their resolved values, not the strings.

```bash
COMMIT=<the commit the reviewer approves on strategic-integration-002>
DECISION=/etc/apex/admissions/<the decision file the authority installs>

# validates both: the commit must exist and yield the expected source
# commitment; the decision must exist, sit under the trust root and have a
# detached signature beside it
research_activation.py preflight --commit "$COMMIT" --decision "$DECISION"
```

`preflight` resolves `COMMIT` to its full sha and computes the
`source_tree_sha256` the checkout **would** produce — from the repository,
without checking anything out — so a wrong commit is caught before a single
directory is created. At the time of writing, `ed2db569…` resolves to
`616a191252be80aef59880a0c9f925de5f010ee44a65550975604009a4bb7545`
(48 bound files), which equals what the boundary computes from a real
checkout; the two computations are independent and are cross-checked by a
test.

`launch` re-resolves both and refuses `UNRESOLVED_INPUTS` if either is
missing, `SETUP_INCOMPLETE` if the setup manifest is absent, and
`DECISION_OR_SIGNATURE_MISSING` if the `.sig` is not beside the decision.

## 2. Step A1 — dedicated research environment (do NOT touch the production venv)

The production venv `/opt/apex/shared/venv` is left exactly as it is:
`apex`-owned, 15 packages, used by the orchestrator and the test harness.

Measured: the research run path loads **exactly one** third-party package —
`numpy 2.4.6` — plus `/etc/python3.12/sitecustomize.py`. numpy is pulled in
by `apex/world_model/__init__.py` (the synthetic-lab models) and is **not
called** by the EXP-001B path, which is pure `math`/`statistics`.

**Path note (caught before this package was finalised):**
`/opt/apex-research` **already exists**, is `apex`-owned, and holds the
World Model shadow worktree (`world-model-shadow`, branch
`world-model-shadow-v0` @ `d01e961b6`). An earlier draft of this step would
have told the operator to `chown -R root:root` that directory, which would
have re-owned a live research worktree. The environment therefore goes to
`/opt/apex-runner`, which is free, under root-owned `/opt`.

```bash
sudo install -d -o root -g root -m 0755 /opt/apex-runner
sudo /usr/bin/python3.12 -m venv /opt/apex-runner/venv
echo 'numpy==2.4.6' | sudo tee /opt/apex-runner/requirements.txt
sudo /opt/apex-runner/venv/bin/pip install --no-cache-dir -r /opt/apex-runner/requirements.txt
sudo /opt/apex-runner/venv/bin/pip freeze | sudo tee /opt/apex-runner/pinned.txt
sudo chown -R root:root /opt/apex-runner && sudo chmod -R go-w /opt/apex-runner
```

Root-owned and not writable by research, so the account cannot inject an
importable module into its own run. Provenance is then recorded **by the
run itself**: `_RUN.json` carries the interpreter (realpath, version,
sha256 of the binary, venv or not, site-packages on `sys.path`) and every
loaded non-stdlib module with version, file and origin.

The pin is **`numpy==2.4.6`**, the version the regression ran under.
The `--system-site-packages` alternative (distro numpy 1.26.4) is
**withdrawn**: it would put the run in an environment no regression had
exercised, and the reviewer chose the pin. If the package index is
unreachable at setup time, setup **stops** — it does not silently fall back.

## 3. Step A2 — identity and dedicated checkout

```bash
sudo adduser --system --group --disabled-password --shell /usr/sbin/nologin \
     --home /home/apexresearch apexresearch
sudo passwd -l apexresearch
id apexresearch                      # expect: only the apexresearch group

sudo install -d -o apexresearch -g apexresearch -m 0755 /apex-data/research
sudo install -d -o apexresearch -g apexresearch -m 0755 /apex-data/research/out
sudo git clone --no-hardlinks /opt/apex-repo /apex-data/research/checkout
sudo git -C /apex-data/research/checkout checkout --detach "$COMMIT"
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
with 143 GB free. Copies cannot touch the corpus inodes even in principle,
and every file is verified byte-for-byte.

**The view is built by the wrapper, from the committed manifest — never
from a filename glob.** A glob follows whatever happens to be on disk; the
manifest is what the admission decision commits to. The wrapper:

1. verifies the manifest's own sha256 against the pinned value;
2. checks the manifest's `root` equals the target corpus root;
3. selects only entries with `symbol == SPY` and `2016-01-04 ≤
   session_date ≤ 2021-12-31`, and refuses if any selected entry falls
   outside that range;
4. refuses a **duplicated** selection name;
5. for every file: refuses a **symlink** anywhere between the corpus root
   and the file, refuses a path that **escapes** the corpus root, refuses a
   **missing** source, and refuses a **source hash mismatch**;
6. copies into **fresh staging** (`dataset_view.staging`, which must not
   pre-exist) and re-hashes every copy;
7. **reconciles the complete inventory** — no missing name, no extra name,
   and exactly 1,511 files — then renames staging into place atomically;
8. on **any** failure, removes the staging directory, so a partial view can
   never be mistaken for a complete one.

It parses no market rows: bytes are hashed and copied, and only the
manifest JSON is read.

```bash
# dry run (default): resolves and checks everything, creates nothing
sudo -u root /opt/apex-runner/venv/bin/python \
     /apex-data/research/checkout/scripts/research_activation.py \
     setup --commit "$COMMIT"

# apply, after the dry run is reviewed
sudo -u root /opt/apex-runner/venv/bin/python \
     /apex-data/research/checkout/scripts/research_activation.py \
     setup --commit "$COMMIT" --apply
```

The original corpus permissions are **not modified**, and no recursive
ownership change is applied to any pre-existing tree.

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
  /opt/apex-runner/venv/bin/python scripts/alpha_exp_real_execute.py \
  --decision "$DECISION" --execute
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

## 7. What this protects, against whom — and what it does not

**Account permissions and sandbox restrictions are different things, and
only one of them is a boundary here.**

| | The `apexresearch` **account**, unsandboxed | The **research process**, launched as in §6 |
|---|---|---|
| evaluation-period corpus file | **CAN read it** — the corpus is world-readable (0664/0755) and `nologin` does not change that | **cannot** — the path does not exist in its mount namespace |
| other symbols, other corpora | can read | cannot |
| `/apex-data/core` live evidence | can read | cannot |
| `/home/apex/.apex-secrets` | cannot (0700, different owner) | cannot |
| corpus for writing | cannot | cannot |
| network | can | cannot |

So: **the account is not the boundary — the launch configuration is.** An
experiment run by any other means as that account would not be isolated,
which is why §6's configuration is the only approved way to run it and why
the probe uses that same configuration object.

`nologin` and the absent supplementary groups stop the account being *used
interactively* and stop privilege escalation; they do not restrict reads of
world-readable files.

**Provides** (measured, non-root): the research *process* cannot read
evaluation or reserve sessions, other symbols, other corpora, live evidence
or credentials; cannot write the corpus; cannot reach the network; cannot
gain privileges; is memory- and task-bounded; writes only into its own
output root.

**Does not provide:** protection against the administrator or any
root-capable account — including today's `apex`. This is a correctness
boundary against the research identity, not a security boundary against
privilege.

**Evaluation data is now covered twice, by different mechanisms:** the
loader refuses by temporal scope and `CALENDAR_NOT_VERIFIED`, and the
filesystem does not present the files at all. Before this package only the
first existed.

## 8. Operator decisions that genuinely remain

**Two.** The environment decision is closed: the reviewer chose pinned
`numpy==2.4.6` and the alternative is withdrawn.

| # | Decision | Concrete effect |
|---|---|---|
| **D1** | Approve authorization **A** and run `setup --apply` | the isolated runner exists, and the view holds copies of the admitted train/validation bytes; no experiment runs |
| **D2** | Approve authorization **B**: issue the signed decision, key generated and held off-host | the run becomes possible; the run still verifies everything itself |

Everything else is an implementation choice already made against
measurement: copy-based view (cross-device hardlinks are impossible), no
ACL work (`setfacl` is absent; the corpus is already world-readable and
non-writable to a non-`apex` account), `/etc/apex` as the trust root,
`/opt/apex-runner` for the environment (because `/opt/apex-research`
already holds the World Model shadow worktree), and pinned numpy.

## 9. Run identity (what authorization C approves)

| Item | Value |
|---|---|
| commit | `$COMMIT`, resolved and recorded by `preflight`/`launch` (no placeholder reaches the run) |
| source commitment | `source_tree_sha256 = 616a191252be80aef59880a0c9f925de5f010ee44a65550975604009a4bb7545` (48 files under the bound paths) |
| experiment / registration | `ALPHA-EXP-001B` / `b3930727334f24379f72df3919c98d689448b2f3f265b2fa6013559ee1bef5c9` |
| dataset manifest | `etf_continuous_SPY_manifest_v0.json`, sha256 `3ac8b250eefb47c5f66c7217508e1080f5f86ae5e4a63c20062a4e931a424c39` |
| scope | train 2016–2019 + validation 2020–2021 **only**; distributional only; no economic stage |
| availability restriction | `ASSUMED_BAR_CLOSE`; no publication or revision record; calendar reconciled for 2016–2021 only |
| environment | `/opt/apex-runner/venv`, `numpy==2.4.6`, recorded per run |
| output | `/apex-data/research/out/ALPHA-EXP-001B/runs/<unique>` |
| limits | `MemoryMax=1400M`, `TasksMax=64`, no network |
| expected outcomes | `0 SCIENTIFIC_COMPLETE` (incl. `NO_SIGNAL`) · `4 EVALUATION_SEALED` · `3 AUTHORIZATION_REFUSED` · `5 INVALID_INPUT_OR_FAILURE` |
| evidence returned | `_RUN.json` (decision sha256, signer, source identity, import verification, interpreter and third-party provenance, trust chain), `_RESULT.json` (status, stages, per-period refusal counts, validation DM-HAC and N0, `acceptance_qualification`), sealed forecast ledger |

## 10. Rollback — capability only, evidence never

Driven by `_ACTIVATION_MANIFEST.json`, which records **every object setup
created** and classifies each as `capability` or `evidence`. Rollback
removes only `capability` objects that this activation recorded creating.
It refuses entirely if the manifest is absent, rather than guessing what it
owns.

```bash
# dry run: prints exactly what would be removed and what is preserved
sudo -u root /opt/apex-runner/venv/bin/python \
     /apex-data/research/checkout/scripts/research_activation.py rollback
```

| Class | Objects | Rollback |
|---|---|---|
| capability | `/opt/apex-runner` (+venv, packages), `apexresearch` account, `/apex-data/research/checkout`, `/apex-data/research/dataset_view` | removed |
| evidence | `/apex-data/research/out` and every sealed run under it, `_ACTIVATION_MANIFEST.json`, `pinned.txt` | **never removed** |
| never touched | `/etc/apex`, `/etc/apex/admissions`, signed decisions, `.sig` signatures, `allowed_signers` | **never removed, not even if recorded** — a guard drops any object under the trust root from the removal list before it is acted on |

The earlier draft's `sudo rm -rf /etc/apex` is **withdrawn**: it would have
destroyed signed admission records, signatures and trust fingerprints, and
`/etc/apex` may hold configuration this activation never created. To
*disable* verification capability without destroying evidence, the
authority removes or replaces `allowed_signers` itself — after recording
its fingerprint (`ssh-keygen -lf`) — which is an admission-authority act,
not a rollback of this setup.

Nothing in rollback touches the production venv, the release, the holds,
the orchestrator, the corpora or their permissions.
