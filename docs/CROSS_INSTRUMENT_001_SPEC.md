# CROSS-INSTRUMENT-001 — shares, options and WAIT on one forecast and one account state

**SPECIFICATION FOR REVIEW BEFORE IMPLEMENTATION. Nothing here is built. No new trading authority is implied, no
provider activation, no deployment, no risk-limit change.** Recorded as the next proposed brick by
OPERATING-LOOP-001.

## The objective this serves

APEX must ultimately use ONE market-state and forecast pipeline to compare long-only shares, eligible options and
WAIT, execute paper decisions through the governed boundary, and record outcomes for challenger learning.
OPERATING-LOOP-001 built the loop those instruments share. This brick adds the second instrument to it.

## What is being demonstrated

That at ONE instant, from ONE forecast and ONE account state, the system can produce a comparable proposal for each
admissible instrument, decide between them and WAIT under a declared rule, and record every quantity the comparison
turned on — **without any of the three being able to look cheaper than it is.**

This is not an edge claim, and the signal is still a placeholder (`SIGNAL_STATUS_001.md`). What it establishes is
comparability.

## 1. The instruments

| instrument | what it is | in scope |
|---|---|---|
| `LONG_SHARES` | a long position in the underlying, whole shares, no leverage, no margin | yes |
| `LONG_CALL` / `LONG_PUT` | the existing single-leg option expressions, unchanged rules | yes |
| `WAIT` | the null. Its result is exactly zero and it is the floor the others must clear | yes |
| short shares, spreads, multi-leg, margin | — | **NO.** Out of scope; a request for one is refused by name |

## 2. The five quantities, separated, per candidate

They are DIFFERENT quantities and the brick's core requirement is that they are never collapsed into one number.
Each is recorded per candidate, with its basis, or the literal `UNKNOWN` and a reason.

| quantity | shares | options |
|---|---|---|
| **purchase principal** | price × shares | ask × 100 × contracts |
| **certified loss bound** | the maximum the certificate will attest can be lost. For an unstopped long share position that is the full principal | the debit |
| **planned stop risk** | the loss at the declared stop, if a stop is declared: (entry − stop) × shares, plus exit costs | as today, from the risk certificate |
| **fees** | the equity schedule's own components, entry and exit, decimal cents, under a complete fee identity | the existing options identity |
| **capital usage** | cash committed while the position is open | cash committed while the position is open |

**Certified loss bound and planned stop risk are not interchangeable.** For an option the debit bounds both. For an
unstopped share position the bound is the principal while the planned stop risk may be far smaller, and a
comparison that silently uses the smaller of the two would make shares look cheap. The kernel sizes on the
certified bound; the comparison reports both.

## 3. What must be built

1. **An equity fee schedule with the same canonical identity** as `ROBINHOOD_RHF_2026`: the seven identity fields,
   decimal-cent arithmetic, per-component rounding rules, `terms_digest`, `PROVENANCE`. Introduced as `CANDIDATE`
   with `known = False` until an operator authorizes it from a published document. **Unknown is never zero**: until
   authorized, a share candidate's fees are UNKNOWN and its net is NOT_ESTIMABLE, exactly as the options path
   behaves today.
2. **A share expression rule**, `SHARE_RULE_V1`, deterministic and named, with its own rule id: from the direction
   signal and the per-trade cap, the largest whole share quantity whose certified loss bound fits the envelope.
3. **A risk certificate and kernel path for shares.** `apex/organism/risk_certificate.py` must certify a share
   expression, and the kernel must see share risk in the same `open_risk` / `same_underlying_risk` /
   `same_family_risk` inputs. **A share position and an option position on the same underlying compete for the same
   same-underlying limit.** No limit is raised to accommodate this.
4. **Book support for share positions**: quantity, principal, entry and exit fees, cash, reservations, and the same
   integrity recomputation from primary fields.
5. **A comparison record**, `pilot_instrument_comparison`, persisted BEFORE the intent, holding one row per
   candidate with all five quantities, the model identity at each stage, the admissibility verdict, and the reason
   any candidate was excluded.
6. **A declared selection rule over the comparable set.** It is a rule, frozen and named, not a preference. Its
   inputs are only what the record above holds.
7. **Exit policy for shares.** Options exit at a 15-minute horizon. Shares need their own declared exit obligation,
   scheduled by the same lifecycle scheduler as `EXIT_DUE`, and the two must be able to be open at once.

## 4. Acceptance criteria

- At one instant, from one forecast and one account state, a comparison record exists with a row per candidate and
  every one of the five quantities present or explicitly UNKNOWN.
- Shares and options on the same underlying contend for the same same-underlying limit; a proof that opening one
  reduces the capacity available to the other.
- A share candidate whose fee schedule is unauthorized yields NOT_ESTIMABLE economics and cannot be selected on a
  net that does not exist.
- The certified loss bound and the planned stop risk are recorded separately for the same candidate, and a proof
  that the kernel sized on the bound.
- WAIT is a candidate in the record, with a total of exactly zero and `zero_basis = ACTUAL_NO_TRADE_POLICY`.
- Both instruments' exits are serviced by the shared scheduler at their own deadlines, including when both are open.
- The comparison is deterministic: the same inputs produce the same record and the same selection.
- Out-of-scope instruments are refused by name, not silently ignored.
- Synthetic acceptance only, through the real boundary, session, kernel and Book.

## 5. Scope boundaries

Synthetic inputs. No provider request, no historical evaluation, no fitting, no deployment, no service activation,
no fee authorization, no order, no limit change. **Cross-release recovery stays an open blocker and is not touched.**
Challenger learning from recorded outcomes is a LATER brick: this one produces the record that learning would read,
and proposes nothing about how it is used. No automatic retuning of any kind is in scope.

## 6. What it will still not establish

Nothing about edge. The direction signal is a placeholder, the equity fee schedule will start unauthorized, and one
instant is not a sample. It establishes that the two instruments can be compared honestly on identical inputs, which
is a precondition for measuring anything at all.
