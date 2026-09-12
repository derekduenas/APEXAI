# DEFECT_STRIKE_RULE_001 — recorded under PROFIT_TRANSITION_DIRECTIVE hard law one

Date: 2026-09-11. Class: **DEFECT**, not a waiting state and not a preference call.

> 0 trades because nothing earned capital = VALID.
> 0 trades because attacks are structurally impossible = DEFECT. — `PROFIT_TRANSITION_DIRECTIVE.md`, hard law one

## The defect

| Component | Behaviour | Consequence under the paper limits |
|---|---|---|
| `PILOT_RULE_V1` (`apex/options_pilot/expression_rule.py`, frozen 2026-09-04) | strike = nearest to spot, cap never consulted | SPY ATM 21-DTE asks 9.20 / 9.26 on 2026-09-11 vs the kernel cap of 5.00 per share ($500 / 100) → every intent `RISK_ENVELOPE_INFEASIBLE` |
| `FULL_FUNNEL_V1` (`apex/decision_wb/engine.py`, `strikes_each_side = 4`) | candidate set = ATM ± 4 strikes, envelope applied inside it | nearest cap-feasible strike on 2026-09-11 was 9 strikes out (call K=773 ask 4.63; put K=749 ask 4.88) → every candidate rejected → WAIT |

Neither path could construct a feasible trade on any scan, at any signal strength, in any market state
observed today. The candidate set and the cap-feasible set cannot intersect **by construction**. That is the
DEFECT branch verbatim: the machine did not decline the market's offers, it could not see them.

The commissioning package named this fork on 2026-09-10 (§2 item 2) and left it as an operator decision. It was
misclassified there as a decision. The instrument feasibility memo of 2026-09-11 established the fact (63 call
and 74 put strikes feasible that day) and the Clock Start readiness list named the rule as the single blocking
line. This record names it as what it is.

## The repair

`PILOT_RULE_V2`: among strikes on the **signal's side** of spot (CALL: K ≥ spot; PUT: K ≤ spot) whose indicative
chain ask is ≤ `max_entry_price`, the one nearest to spot (ties → lower). Session default. V1 is retained,
frozen, for replay of records that sealed it, and now carries the defect marker in its own selection record.

**Refused alternative:** setting the funnel's strike width from the cap. That would make what the machine *sees*
a function of the account balance: observations at a $500 cap would not be comparable to observations at any
other cap, and candidate generation, the research layer, would carry a financing fact. The cap enters in
expression, downstream of the signal, through exactly one function (`risk_authority.entry_cap_price`), and a
test asserts the funnel module never references it.

**What V2 seals that V1 could not express** (`strike_selection` in every `pilot_intent`): the rule version, spot,
chosen strike, its distance from spot in dollars and percent, the number of strikes from ATM, the cap, the census
(strikes / on-side / with-ask / feasible), and the sentence "V1 would have chosen K=… (ask …), which the envelope
refuses; the nearest feasible strike is N strikes / p% from spot".

## What this does not change

The funnel path (`FULL_FUNNEL_V1`, `JOINT_FUNNEL_V1`) still evaluates ATM ± 4 and still cannot intersect the cap on
a day like today. It is not the session default, and widening it from the cap is refused above. If the funnel is
to become the default expression path it needs a candidate-set rule that is blind to capital and still reaches the
feasible band (for example a fixed moneyness band), which is a separate reviewed change and is not made here.
