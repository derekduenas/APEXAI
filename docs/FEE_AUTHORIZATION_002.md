# FEE-AUTHORIZATION-002 — source verification is not operator authorization (2026-09-13)

Branch `tradingview-integration-003`. Code pin at entry `35af566`, evidence head `ee63990`.

**Monday's scheduled paper run is HELD. No merge, no deployment, no fee promotion, no paper execution.**

## The finding, reproduced before any repair

`docs/evidence/fee_authorization_002/FINDING_REPRODUCTION_before_repair.txt`

`ROBINHOOD_RHF_2026` v2026-09-12b described itself as an unauthorized candidate while being constructed as
`PROVIDER_VERIFIED`:

| | |
|---|---|
| D1 | the object said **both** CANDIDATE and AUTHORIZED — the source comment said "returns to candidate", the `note` said "AUTHORIZED by the operator 2026-09-12 and the LIVE default from that date" |
| D2 | the **superseded** 2026-09-12 authorization travelled *inside* the schedule, attached to arithmetic it never covered |
| D3 | `IDENTITY_FIELDS` named **no** authorization field, so nothing downstream could detect its absence or supersession |
| D4 | **the explicit-candidate bypass**: `LIVE_DEFAULT_FEES = UNVERIFIED_FEES` refused, but passing the candidate explicitly produced `decision=TRADE, intents=1, fills=1` |
| D5 | the supersession was applied by mutating a dict *inside* a frozen dataclass after construction, and nothing ever read it |

Root cause: `known = provenance != "UNVERIFIED"`. `provenance` carried two different facts — that a **document**
was verified, and that the **computation** was cleared for use — and `known` is what every downstream gate
consulted. A schedule became usable the moment it was transcribed. **No person had to agree to the arithmetic.**

This was my own reporting error too: I demonstrated the bypass in the stand-up audit and read it as proof the gate
worked, when it was proof the gate was a default rather than a control.

## The repair

1. **Two facts, kept apart.** `provenance` now means source verification only (`source_verified`). A new
   immutable `FeeAuthorization` records the operator act.
2. **Authorization evidence** carries `schedule_id`, `version`, `source_document_sha256`, `terms_digest`,
   **`computation_digest`**, `effective_date`, `status`, `authorized_by`, `authorized_utc`, `scope` — each matched
   **exactly**; a near miss is a refusal naming the field that differs.
3. **`computation_digest`** is new and is the field that would have caught this: the *rates* were identical
   between v2026-09-12 and v2026-09-12b; only **how the SEC component is computed** changed. A terms digest alone
   could not distinguish them, which is exactly how the superseded authorization survived.
4. **Bound into the canonical identity** — `authorization_status`, `authorization_digest`, `computation_digest`
   and `source_document_sha256` are in `IDENTITY_FIELDS`, so a persisted approval stops verifying the moment the
   authorization changes, is removed or is superseded.
5. **The control, not the default.** `FeeSchedule.usable` = known **and** authorized. Refusal happens at
   **`Boundary.__init__`** — before any quote request, certificate, kernel check, intent or fill — and again,
   independently, in `CertifiedRiskAuthority.approve()`. `charge()` returns `NOT_AUTHORIZED`, never a number.
6. **Stale records corrected.** The schedule's note now reads `CANDIDATE, NOT AUTHORIZED`; the superseded
   authorization is detached into `ROBINHOOD_RHF_2026_SUPERSEDED_AUTHORIZATION` with
   `applies_to_current_schedule = False`. No object says both.

`SYNTHETIC_FEES` is exempt (`requires_authorization == False`): it is labelled synthetic, can never be a live cost
claim, and authorizing a fixture would be theatre. `UNVERIFIED_FEES` still *constructs* — a session that records
refusals is evidence; one that cannot start is not.

## After the repair

```
LIVE_DEFAULT (UNVERIFIED)  decision=REFUSE   FEE_SCHEDULE_UNKNOWN
explicit ROBINHOOD v-b     BOUNDARY REFUSED  BOUNDARY_REFUSES_UNAUTHORIZED_FEE_SCHEDULE
SYNTHETIC fixture          decision=TRADE    (unaffected)
```

## What is NOT done here

No authorization has been authored or installed. `ROBINHOOD_RHF_2026.authorization is None`. The exact digests and
a proposed payload are in `docs/evidence/fee_authorization_002/PROPOSED_AUTHORIZATION.txt` for review.

No merge, no deployment, no pilot restart, no lifting of the hold, no paper execution.
