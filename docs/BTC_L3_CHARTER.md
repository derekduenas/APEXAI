# BTC-L3 — PARTICIPANT INTELLIGENCE CHARTER

**Authorized:** 2026-08-23, immediately after L2 passed and froze.
**Authority:** OBSERVE. L3 interprets. It sizes nothing and authorizes
nothing.

---

## The shift

L0–L2 answered *"is the state we record true?"* — and that question is
now closed and frozen. L3 asks the first profit-facing question:
**what are the participants doing, and which of them is trapped?**

## The identification problem is the foundation, not a footnote

Every futures contract has a long **and** a short. Rising open interest
means contracts were *created*. It does not say who wanted them, who
was aggressive, or who is vulnerable. So the folk law

> price up + OI up = new longs

is not a law. It is one reading among several, and its competitors are
ordinary: an aggressive seller absorbed by a willing buyer prints
identically; a hedger creates OI with no directional view at all; a
short leg may be a delta hedge against spot held elsewhere.

`apex/btc_sleeve/participant_state.py` is built so that reading can
never be stated as fact. Every interpretation carries its competing
explanations, and **a test fails any supported reading that has none.**

## "Probabilistic" means ordinal, not invented

No outcome data yet links these states to what followed them. Any
number like 0.73 would therefore be fabricated. Support is ordinal —
`CONSISTENT` / `WEAKLY_CONSISTENT` / `INCONSISTENT` / `NOT_ESTIMABLE` —
and every reading is stamped `calibration: NONE_FITTED`. Calibration
becomes available when prospective evidence exists, fitted against
outcomes by a governed process, never by an author's intuition.

## Quality awareness is structural

An interpretation is only as good as its inputs' cadence.
Daily-published open interest cannot support an intraday positioning
claim — it describes yesterday's book. Where inputs cannot carry the
inference the reading is `NOT_ESTIMABLE`, never a quieter version of
the same assertion.

The thirteen authorized interpretations are emitted every time, so a
missing reading is visibly missing rather than silently absent.

## Forced action: what we refuse to pretend

`apex/btc_sleeve/forced_action.py` asks who *must* act rather than who
wants to. Forced action is caused by margin calls, stops and mandates —
**we observe none of these.** So "longs will be liquidated at X" is not
available to us and building it would be fabrication.

What is observable is the *consequence* while it happens: positions
destroyed rapidly, against the side paying funding, into a thinning
book.

The states are therefore ordered around observation and exhaustion, not
prediction:

| state | meaning |
|---|---|
| `NONE_OBSERVED` | ordinary two-way trade |
| `SUSCEPTIBLE_NOT_TRIGGERED` | conditions exist; nothing is happening |
| `DELEVERAGING_IN_PROGRESS` | the signature is present now |
| `DELEVERAGING_EXHAUSTING` | the flow is decaying |
| `NOT_ESTIMABLE` | the inputs cannot carry the question |

## Where the edge plausibly is

A small account **cannot** front-run a cascade — that is a latency
battle against giants, and the module explicitly offers *no* tradeable
moment in the middle of one. What a small account can do is be patient
liquidity when forced flow **exhausts**: the moment supply that had to
sell has finished selling.

That is capacity-limited, low-footprint, and aimed at forced
participants — the terrain the small-capital doctrine points at. It is
also completely unproven, and is stamped so.

## Falsifiability is part of the output

Every thesis states what would disprove it *before* any outcome is
known. A thesis that cannot be wrong is not a thesis.

---

## Attack geometry — built 2026-08-24

`apex/btc_sleeve/attack_geometry.py` closes the third rung. It answers
only the question asked of it:

> When the forced-action thesis is plausible, is there a price location
> with tight invalidation, workable liquidity, a favourable tail and
> limited chase that gives a **small** account an asymmetric attack?

**Both dimensions may veto.** A plausible thesis at a terrible location
is not an attack, and a beautiful location with no thesis is not one
either — the latter is tested explicitly, because it is the more
seductive error.

**Mid-cascade is a structural refusal, not a downgrade.** Entering while
forced flow is still arriving is a latency race against liquidation
engines, and a small account loses that by construction. The attack is
always the *other* side of exhausted forced flow, never its
continuation: if longs were the forced sellers, we are the buyer they
must sell to once their supply runs out.

**Size is judged against the actual book,** which is where the
small-capital doctrine stops being a slogan. A touch holding 60
contracts against our 1 makes our footprint negligible, and the module
names that as the asymmetry we own and a fund does not. Reading the
book directly is legitimate only because L2 passed and froze.

Every rule is classified `STRUCTURAL_INVALIDITY` or
`EXPLORATORY_QUALITY_PRIOR`. Only structural wounds refuse; a wide
spread or an extended chase downgrades and is recorded. No
`LEARNED_ECONOMIC_THRESHOLD` is authorized, because no outcome data
exists to learn one from.

Continuous measurements — invalidation distance in ATR, tail ratio,
extension, spread in ticks, executable size, size-vs-book — are all
preserved rather than collapsed into a verdict, so later study can
judge the priors that judged the trade.

### Still not built

Paper execution and the BTC `PAPER_EXPLORATORY` review. The ladder is
participant state → forced-action thesis → attack geometry → paper
review, and the first three rungs are complete. 61 tests across the
three modules. No live capital, no promotion.
