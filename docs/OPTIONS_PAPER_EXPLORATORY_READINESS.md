# OPTIONS PREDATOR — READY_FOR_PAPER_EXPLORATORY_REVIEW

**Date:** 2026-08-23
**Requested authority:** `OBSERVE` → `PAPER_EXPLORATORY`
**Status: SUBMITTED FOR AUTHORITY REVIEW. Not promoted. Not self-promoted.**

`PAPER_EXPLORATORY` asks one question: *do we trust the plumbing enough
to simulate attacks and learn from them?* It does not assert an edge.
Everything below is offered against that question.

---

## 1. What was run

The full causal historical replay over the frozen PhD qualifying
boundary — 105 symbol-days, boundary sha256 `90b3e81467a02dde…`, frozen
before any empirical result was seen.

| | |
|---|---|
| Symbol-days attempted | 105 (100%) |
| Raw decision instants | 420 |
| Resolved decisions | 330 |
| Declined: no directional thesis | 90 |
| Errors | **0** |
| Symbols / dates | 6 / 40 |
| Span | 2018–2022, including 2018-02-05 and 2020-04-01 |

The protocol — decision cadence, direction rule, exit rule, risk bases —
was hash-sealed into the ledger **before the first outcome was read**,
and was not altered afterwards. Ledger: 662 rows, chain verified intact
from genesis (0 broken links, 0 bad hashes).

## 2. Plumbing evidence

**Temporal firewall.** `ReplayWorld.at(T)` returns a state in which the
future is absent from the object, not filtered from it. The future is
reachable only through `reveal_after(T, sealed_card_hash)`, which
refuses without a sealed card. Every one of the 330 decisions sealed a
BEFORE card into the chain before its future was touched.

**Quoted-side fills.** Every leg crossed its own contract's quoted side —
long pays that contract's ask, short receives that contract's bid. No
midpoint, no model price, no cross-contract assumption.

**The accounting identity holds exactly.**

> `pnl = mid_change − entry_friction − exit_friction`

Verified on **660 of 660** option outcomes (169 + 169 + 161 + 161).
Stock outcomes correctly report `NOT_ESTIMABLE` — stock has no quoted
option legs and its fills are modelled, so the identity does not apply
and is not faked. Zero failures means every reported loss is provably
market friction plus mid movement, not arithmetic drift.

**Sample honesty.** `n_raw = 330` reduces to `n_effective_lower_bound =
105`. Four decision instants inside one session are four views of one
day. The system reports the smaller number.

**No winner is crowned.** All 330 decisions emitted
`winner: WITHHELD — requires an explicit comparison basis`. Four
normalization bases are preserved side by side; none is allowed to
decide alone.

## 3. Three defects found and closed — two of them by real data

**Contract identity (real defect).** Exit quotes were keyed on
`(strike, right)`. The same strike exists on every expiry in the chain,
so resolution could silently price a *different expiration* — exactly
the cross-contract assumption the fill law forbids. It surfaced as a
long vertical reporting −$525 against a $155 debit, which is impossible.
Candidates now carry their expiration, fills record which contract they
bought, and resolution refuses to price rather than reach for another
expiry. Correcting it moved a single long call from +$145 to +$200, so
this was corrupting *every* option outcome, not only the visible ones.

**R defaulting to capital (governance defect).** `r_multiple` divided by
capital committed, silently equating "the debit" with "the planned
loss". R now comes from the sealed plan and is **withheld** when no
basis was declared. A long call held to zero risks its premium; the same
call abandoned on underlying invalidation risks far less. Both are
honest; conflating them corrupts every R this system will ever report.

**"Defined risk" overstated (semantic defect).** The debit bounds the
loss *at expiry*. Nine outcomes lost more than their debit. Forensics
proved these were not bugs, so the invariant was wrong, not the code —
see below. Candidates now carry `max_loss_basis = AT_EXPIRY`,
`immediate_liquidation_value` and `round_trip_friction`, all computed
from the same quotes that price the entry, so the cost of leaving is
known before entering.

## 4. The economic observation — and what it is not

Replay economics, `HISTORICAL_DEVELOPMENT_REPLAY`, `n_effective = 105`,
one fixed protocol, nothing tuned:

| expression | n | mid P&L | friction | net P&L | right on mid | right on net |
|---|---|---|---|---|---|---|
| LONG_CALL | 169 | +606 | 2,104 | −1,499 | 63% | 56% |
| LONG_PUT | 161 | +3,040 | 3,170 | −131 | 43% | 40% |
| CALL_VERTICAL | 169 | −1,858 | 3,668 | −5,525 | 47% | 29% |
| PUT_VERTICAL | 161 | −2,126 | 6,375 | −8,501 | 30% | 14% |

Across all option expressions: **mid P&L −338, friction 15,318, net
−15,656.** The directional theses were roughly a coin flip on mid value,
and essentially the entire loss is the round trip. **75 of 304 trades
(25%) were right on mid and lost anyway.** LONG_PUT is the cleanest
illustration: +$3,040 of genuine mid gain, delivered as −$131.

The sharpest single case is SPY on 2018-02-05. The put vertical was
worth +$251 against a $155 debit — the thesis was right, on the day it
was designed for. Both exit spreads had widened to roughly $3.00, and it
realized −$212. **Spreads widen exactly when a volatility thesis pays.**

**What this is not.** It is not evidence that options don't work. It is
evidence that *this* expression protocol, on *this* sample, is dominated
by friction rather than by being wrong — which is a far more actionable
finding, and it points directly at the small-capital doctrine: the
spread is the giant's toll booth, and we walked through it four times
per trade.

**A comparability caveat that must not be buried.** Stock shows +8,656,
but stock fills are `MODELLED_EXECUTION` and cross **no spread at all**,
while option fills are `OBSERVED_QUOTE` and cross real ones. The
stock-versus-option comparison is therefore flattering to stock by
construction and **must not be read as "stock beat options."** Closing
that gap requires real equity NBBO, which is the outstanding item in
`EQUITY_QUOTE_DATA_PLAN.md`.

## 5. What is explicitly NOT claimed

- No prospective evidence exists. Every record is stamped
  `HISTORICAL_DEVELOPMENT_REPLAY` and `live_promotion_eligible: false`.
- No threshold has been fitted to these outcomes, and none may be.
- No learned economic gate is authorized. Attack geometry refuses only
  on structural invalidity.
- 105 symbol-days is a plumbing proof, not a research result.

## 6. The ask

Promote the Options Predator to `PAPER_EXPLORATORY` so it may simulate
attacks forward and begin generating the prospective evidence it does
not yet have. The plumbing is verified: sealed decisions, honest fills,
an exact accounting identity, refusal in place of guessing, and three
defects found and closed — two of them surfaced by real data doing what
synthetic fixtures never did.

**This report does not promote anything. Authority review is required.**
