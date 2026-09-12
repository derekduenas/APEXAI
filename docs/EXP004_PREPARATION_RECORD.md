# EXP-004 — signed admission installed, verified, and prepared

**Preparation only. Nothing was executed; the output directory is empty.**
Execution authorisation remains a separate gate.

## 1. Signed decision

| | |
|---|---|
| path | `/etc/apex/admissions/exp004_admission.json` (+ `.sig`), root:root, mode 644 |
| **decision sha256** | **`2919dba0e94d5c6428abeac2768b7cb21abbbf0fb7e8d56a067f09328d0edc2a`** |
| decision / decided_by / decided_utc | `ADMIT` / `apex-admission` / `2026-09-10T14:52:40Z` |
| review reference | `EXP004-HISTORICAL-SCREEN` |

The digest necessarily differs from the reviewed request's
`290e4cce…1cdaeb`: `decision` and `provenance` changed, which is what
authoring a decision means. Everything else was retained — verified below.

**Retained from the reviewed request:**

| | |
|---|---|
| code commit (the pin) | `ea87faa42537a14678bb6fc5cb1e9aacc83cf40f` |
| bound source tree | `8fbe6ed6155df0e4b8fb09f6dd8ce54c7e1cf064cea29592e08fa44a41996991` |
| launcher (not bound) | `823b0125b58b86ba653f0dfedf3c495dfe05cc7df79e4671c8717e4a57776b9e` |
| registration | `9155024f51825d13487cdc035432d85b357d22e39a40f967477873a7a6145bf9` |
| dataset / manifest | `history-b/etf_continuous` / `3ac8b250eefb47c5…` |
| scope roles | fit `2016-01-04 → 2018-12-31`; **development_EXPOSED** `2019-01-01 → 2021-12-31` |
| evaluation and reserve | `SEALED; never requested by this experiment` |
| output root / environment | `/apex-data/research-exp004/out`; `apexresearch4`, `/opt/apex-runner-exp004` |

## 2. Signature verification against the EXISTING allowed-signers configuration

`allowed_signers` sha256 `ae30f60db42443ad58a573daa31e94ea0b6ca985148303682c7ca6ccfbaf83e0`
— unchanged, not touched for this admission.

```
ssh-keygen -Y verify -f /etc/apex/admissions/trust/allowed_signers \
  -I apex-admission -n apex-admission -s exp004_admission.json.sig < exp004_admission.json

Good "apex-admission" signature for apex-admission with ED25519 key
SHA256:A9uPHHPKZSzeWcRkOGyAa6M1gHVJhj4fFKAAgrIgumI          (exit 0)
```

## 3. Dataset re-verification after installation — exit 0

`results/exp004_verify_postinstall.json`. `status OK`, `state COMPLETE`, all
eight checks pass, including `dataset_inventory` (1,511 files,
`SPY_2016-01-04.json` → `SPY_2021-12-31.json`, every file re-hashed against
the manifest by the wrapper's own check), `checkout_identity` at the pin, and
`runner_not_writable_by_research` over 2,628 entries.

## 4. Preparation — `launch` WITHOUT `--apply`, exit 0

`results/exp004_prepare.json`. **`applied: false`**, `ok: true`,
note: *"prepared only; authorization C is required to run this command"*,
prepare effect: *"resolves and checks inputs, prints the plan, and launches
NOTHING"*.

Resolved: commit `ea87faa4…`, tree `8fbe6ed6…`, interpreter
`/opt/apex-runner-exp004/venv/bin/python`, decision
`/etc/apex/admissions/exp004_admission.json`, **decision_sha256 `2919dba0…`
matching the installed file**, `view_files 1511`, experiment `ALPHA-EXP-004`,
registration `9155024f…`.

Ten checks performed and passed: setup record COMPLETE, required stages
present, requested commit matches the setup record, checkout working tree
clean, bound source tree hash matches, dataset view file count matches,
interpreter present, decision file exists, signature file exists, decision
contained in the trust root.

**Two checks preparation deliberately does NOT perform**, both covered
elsewhere and stated rather than implied:

- `signature_cryptographically_VERIFIED: false` — done by the boundary at execution time, and independently verified in §2 above.
- `dataset_view_file_HASHES_rechecked: false` — preparation counts files only. The wrapper's `verify` re-hashes every admitted file and was re-run in §3; an independent recomputation of all 1,511 hashes is in `results/exp004_setup_reconciliation.json`.

## 5. State

Output directory `/apex-data/research-exp004/out` is **empty**. No run
directory, no launch record, no result. The only difference from the setup
brick is that a signed decision now exists and has been verified.

**The remaining gate is explicit execution authorisation.** The command would
be the preparation command with `--apply` appended, run from
`/apex-data/research-exp004/checkout`. I will not run it without that
authorisation.

## 6. What the run would answer

Whether the clipped signed body-volume feature `F̃` improves the predictive
density of 15-minute-ahead SPY log returns **beyond its two ingredients and
their product**, under **both** registered dispersion specifications, on the
**exposed** 2019–2021 development pool. A pass is a candidate screen: it grants
no sealed access, is not confirmation, and is not evidence of alpha, options
profitability or tradability.
