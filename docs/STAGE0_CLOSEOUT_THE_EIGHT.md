# Stage 0 closeout — the eight guards and validators the deployed release lacks (2026-09-12)

Deployed release `73fc712d…` versus `main` (`6eb4a6b`, the merged reviewed tree). "Enforced by another path" was
checked against what the deployed tree actually runs: the legacy paper loop in `scripts/options_paper_session.py`
with the old `apex/organism/risk_kernel.py` (`MAX_RISK_PER_TRADE = 500`, `check()`), no options pilot package, no
certificate, no gateway.

| # | File (absent = A, modified = M) | What it enforces | Enforced in the deployed tree by any other path? |
|---|---|---|---|
| 1 | A `apex/organism/risk_certificate.py` (GUARD) | `DEFINED_MAX_LOSS` certification of an expression from its legs; refuses debit verticals under a pre-expiry exit; refuses unboundable instruments; primary-fact disagreement check on `net_debit` | **NOT AT ALL.** The legacy loop sizes by `declared_1R`, a label, and never certifies a structural bound |
| 2 | M `apex/organism/risk_kernel.py` (GUARD) | main's version adds the certified-loss denomination (aggregate exposure = sum of independently verified `certified_max_loss`), the per-family and same-underlying caps in certified terms, and the session drawdown halt against certified loss | **Partially.** The deployed kernel enforces the old declared-1R dollar caps ($500/trade) only; certified-loss aggregation does not exist there |
| 3 | A `apex/options_pilot/risk_authority.py` (GUARD) | the certified authority: fee schedule must be `PROVIDER_VERIFIED` for LIVE_FEED, `RISK_ENVELOPE_V1` (max entry price from the cap), approval bound to the full intent body, kernel re-check at commit | **NOT AT ALL.** No fee-provenance gate exists in the deployed tree; an unknown cost is treated as zero there |
| 4 | A `apex/options_pilot/risk_gate.py` (GUARD) | binding view and `verify_approval`: an approval is valid only for the exact intent body it was issued for (`binding_hash`, `envelope_binding_hash`) | **NOT AT ALL.** The legacy loop has no intent/approval binding |
| 5 | A `apex/joint_wb/permissions.py` (GUARD) | dataset-and-role permissions for R4 reads; sealed partitions unreadable; FIT runs need an artefact naming range, cutoff and population | **NOT AT ALL**, and not needed by the legacy loop (it reads no R4 dataset); it matters the moment any R4 code is deployed |
| 6 | A `apex/options_pilot/records.py` (VALIDATOR) | forecast/contract/quote/intent validators: finite values, exact integer sizes, crossed-quote refusal, vocabulary (`LONG_CALL`/`LONG_PUT` only), TTL, provenance labels, BEFORE fields | **NOT AT ALL.** The legacy loop's cards carry no comparable validator; its ledger accepted 19 attacks with no quote validation of this kind |
| 7 | A `apex/options_pilot/boundary.py` (VALIDATOR) | the recording boundary: forecast-before-quote ordering, atomic reservation, fresh-quote 15 s check at fill, canonical proposal digest re-check, cross-release intent refusal, exit policy | **NOT AT ALL.** The deployed loop is the "legacy session protocol" the pilot replaced; its fill semantics are the ones r2 found the P1 write failure in |
| 8 | A `apex/options_pilot/ledger.py` (VALIDATOR) | hash-chained, fsynced, append-only ledger with receipts, `commit_once`, `verify_chain`, `verify_receipt` | **Partially.** The deployed tree chains its legacy ledger (`apex/governance/chain_ledger.py`) but has no receipt verification, no `commit_once` idempotency, no transaction lock |
| 9 | A `apex/world_model/real_data/boundary.py` (VALIDATOR) | interpreter and third-party provenance, sticky world-writable ancestor check, real-data admission | **NOT AT ALL**; not on the paper path |

Nine files, not eight: the classification counted the modified kernel separately. **Six of the nine are enforced by
nothing in the deployed tree; two partially; one is off-path.** The deployed release enforces materially less than
the reviewed tree, which is the reason `DEPLOYMENT_DIVERGENCE_001` blocks and the reason the deploy proceeds from
the merged reviewed tree, not from the release that is running.

Book-flat check before the deploy: the legacy ledger's last record is the 2026-09-04 session scoreboard, 19 attacks
with 19 outcomes; no pilot ledger exists yet. Flat.
