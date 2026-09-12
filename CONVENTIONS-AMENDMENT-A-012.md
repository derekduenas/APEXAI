# CONVENTIONS — AMENDMENT A-012 (DRAFTED 2026-09-12, IN FORCE ON OPERATOR ACKNOWLEDGEMENT)

## No release change while a position is open

### 1. FINDING

`FINDING_RELEASE_CHANGE_STRANDS_POSITION.md` (weekend rehearsal, pinned by
`tests/test_weekend_brick5_rehearsal.py`): a process started under a different release refuses to recover the
previous release's FILLED position (`INTENT_FROM_OTHER_RELEASE`), opens its own, discharges only its own, and closes
the session with the old position still open. The obligation is stranded and uncounted.

### 2. RULE

1. **No deploy, rollback, or re-point of `/opt/apex/current` while any `pilot_fill` of the running session lacks a
   discharging `pilot_outcome`.** The check is the operator view's open-position count, taken immediately before
   the change, and recorded with the change.
2. A release change is performed only with the book flat, and the record of the change names the outgoing and
   incoming release identities (`runtime_identity.git_commit` and decision-path tree digest of each).
3. Until the cross-release exit repair proposed in the finding is reviewed and merged, this rule is the only
   protection; it is procedural, and it is therefore a NO-GO condition for any unattended restart.

### 3. SCOPE

Applies to the options paper service and to any future service whose ledger carries obligations that outlive a
process. It does not apply to observation-only processes that hold no positions.
