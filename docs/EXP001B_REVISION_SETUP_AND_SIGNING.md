# EXP-001B — REVISION SETUP AND SIGNING PACKAGE

A **bounded-memory engineering revision of the same registered experiment**, after
an aborted attempt. The registration, the hypothesis and the statistical procedure
are unchanged. Changing bound code requires a fresh admission and a fresh checkout;
it does not require a new registration.

Read-only. Nothing here has been signed or executed.

---

## 1. ONE REVIEWED REVISION, CONTAINING BOTH

`ed4825684cd00ce5c70ef12bf12e3f08b684b212`

| | |
|---|---|
| bound experiment tree | `06eee315eb02c697fd3a0f1723c6e12c9d878d89f31832149abf783fef1e8345`, 48 files |
| identical to the qualified tree | **yes** |
| launcher `scripts/research_activation.py` | sha256 `5aeb8288647d55342278b7eff22d9875e42f280015302ea038bfe4ba91edc712` |

**The launcher is not a bound path, so the admission cannot pin it.** Matching the
bound experiment hash establishes the experiment and nothing else. That gap is
closed two ways: the launcher is pinned by the *commit*, and the operator runs it
**from the fresh checkout** rather than from anywhere else, after checking its
hash. The previous request pinned `22ea5104`, which carried the qualified `run.py`
but not the later launcher repairs, so it is superseded.

### Which tests establish which half

| half | established by |
|---|---|
| experiment (`run.py`) | 5 equivalence tests against the pre-repair source: sealed forecast ledger byte-identical, outcomes ledger identical, whole record identical apart from elapsed time, `dm` and `n0` compared value by value; plus the 65-test exp001b suite; plus the aligned qualification |
| launcher | outcome classification through the real CLI with controlled child processes (7), result-to-run binding (5), the exit-4 contract (4), resumption (6), the verifier repairs, and sealing through the real execute path with disposable authority (3) |

---

## 2. FRESH ENVIRONMENT

| object | path |
|---|---|
| research root | `/apex-data/research-rev2` |
| checkout | `/apex-data/research-rev2/checkout` |
| dataset view | `/apex-data/research-rev2/dataset_view` |
| output | `/apex-data/research-rev2/out` |
| runner root | `/opt/apex-runner-rev2` |

A second runner root is needed because preflight requires every destination to be
free and the existing one must stay intact.

**Preserved untouched:** the existing checkout at `277e4a02`, `/opt/apex-runner`,
the trust root with the signed v2 decision, and the aborted run directory, which
stays read-only.

### One thing blocks this, and it is not implemented here

The CLI has **no flags for the roots** — target injection is a testing interface
only — so a second environment cannot be built through the wrapper as it stands.

Three options, with a recommendation:

1. **Add `--research-root` and `--runner-root` (recommended).** Small, changes no
   check, guard or default, and production behaviour is identical when the flags
   are absent.
2. Roll back the existing environment and reuse the paths. **Rejected:** rollback
   preserves evidence by refusing to remove parents that contain it, and reusing
   the paths would put a new run where the old evidence lives.
3. Build the tree by hand. **Rejected:** nothing would be verified.

The re-pin guard is **not bypassed and not weakened.** It correctly refuses to
move the existing checkout across a bound-tree change, which is exactly why a
fresh checkout is required. The only change made to it was its refusal *text*,
which wrongly called this a new experiment.

---

## 3. HOW EACH PROPERTY IS VERIFIED

| property | check |
|---|---|
| checkout identity | commit equals the admitted commit, bound tree equals `06eee315…`, working tree clean |
| **launcher identity** | sha256 of the launcher in the fresh checkout equals `5aeb8288…`, checked **before** invoking it |
| dataset view | `verify` **re-hashes every admitted file** and refuses on a mismatch; count must be 1511 |
| environment | unprivileged uid with no privileged groups, venv interpreter present, numpy pinned at 2.4.6, runner tree root-owned and not group- or other-writable across every entry |
| activation record | state COMPLETE, every stage VERIFIED with its evidence, plus the append-only stage log |
| sandbox configuration | `probe` **enters** the sandbox and measures nine properties with zero deviations, and a test asserts the probed property list is identical to the launch list |

Check the launcher hash first:

```bash
sha256sum /apex-data/research-rev2/checkout/scripts/research_activation.py
```

---

## 4. SIGNING

Unchanged from the established process, and the key stays where it is. Start from
`results/exp001b_admission_request_v3.json`, set `decision` to ADMIT, fill
`provenance`, confirm `code.commit` is `ed482568…`, then:

```bash
ssh-keygen -Y sign -f ~/.ssh/apex_admission_ed25519 -n apex-admission exp001b_admission.json
```

The trust root and your public key are already installed and unchanged. Only the
decision and signature need replacing. Verify on the host before proceeding:

```bash
ssh-keygen -Y verify -f /etc/apex/admissions/trust/allowed_signers -I apex-admission -n apex-admission -s /etc/apex/admissions/exp001b_admission.json.sig < /etc/apex/admissions/exp001b_admission.json
```

Any rerun writes to a **new run directory**. The aborted one is closed.

---

## 5. THE QUALIFICATION, INCLUDING WHAT IT DOES NOT SETTLE

166,110 validation rows, matching an independently calculated expectation exactly,
covering every eligible minute of every admitted session including the three early
closes. Both grading passes completed.

| | |
|---|---|
| effective cap | 1,468,006,400 bytes |
| cgroup peak, read before exit | 1,468,006,400 bytes |
| memory events | `max 1`, `oom 0`, `oom_kill 0` |
| anonymous working set peak | 881,557,504 bytes |

**Headroom at peak was zero in cgroup terms. The peak equalled the cap.**

The counters show the limit was reached once and that no kill occurred. Reclaim of
clean page cache from the 567 MB output file is the explanation most consistent
with that, and with the anonymous set peaking well below the cap. **It was not
directly instrumented, so it is a supported reading rather than a conclusively
established cause,** and other contributions to the cgroup total were not measured
separately. The practical consequence stands either way: the margin is not
anonymous headroom, and a workload that grew the anonymous set materially could
still fail.

---

## 6. SEQUENCE FROM HERE

1. Targeted source review of this one revision.
2. Add the two root flags so the second environment can be built through the wrapper.
3. Setup, verify, probe.
4. Authority signs the v3 request bound to `ed482568…`.
5. Install decision and signature; verify on host.
6. Verify, prepare, then execute into a new run directory.

No signing and no historical execution have occurred.
