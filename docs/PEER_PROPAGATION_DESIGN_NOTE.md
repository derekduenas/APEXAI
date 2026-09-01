# Peer Propagation — Design Note (NO BUILD during Combat Week 1)

Sealed 2026-08-30. Design-only per the combat-week directive §10.
No outcomes were examined in preparing this note.

## The question

Does material company information (earnings) propagate incompletely
to economically related securities — i.e., does symbol X's PM
earnings event predict symbol Y's next-session behavior beyond
market beta?

## What a governed peer map requires

Causal, declared-in-advance relatedness — never fitted correlations
on the outcomes we intend to score (4-trade correlation = false
precision, per the Arena's own doctrine).

## Verified available structural source (autonomous, PIT-safe)

**SEC SIC codes** from `data.sec.gov/submissions/CIK*.json` —
verified live: CRM → 7372 Services-Prepackaged Software; AAPL → 3571
Electronic Computers. Properties:

- structural (regulator-assigned industry), not outcome-derived;
- autonomous (same EDGAR pipeline as `edgar_timing.py`, CIK bridge
  already exists);
- versionable: fetch once for the 299 PIT names, seal as
  `peer_map_v1` with a capture timestamp BEFORE any scoring.

Granularity: 4-digit SIC is narrow (good); 3-digit fallback where a
4-digit group has <2 PIT members. Both variants must be sealed in the
same version — choosing between them after seeing results is a
search dimension and is forbidden.

## What the tournament ledger already provides

Every sealed watch row is a timestamped event with certified timing.
A propagation study needs only: for each PM event, the next-session
checkpoint returns of the event symbol's sealed peers (same
resolution machinery, extra symbols). Marginal cost: one extra
Alpaca-bars fetch per peer per event day.

## Deliberately unresolved (decide at build time, not now)

1. Peer outcome horizon: same reaction session vs +1 session.
2. Whether the peer must NOT itself be reporting that week
   (contamination rule — likely yes).
3. Whether A3 conditions on the event symbol's surprise class
   (that would nest A3 inside A2's unproven claim — probably start
   unconditional, mirroring the A1/A2 separation lesson).

## Trigger to build

After the first resolved tournament week, if operations acceptance
held: seal `peer_map_v1` from SIC codes, extend the resolver to also
record peer checkpoint returns for sealed events, and register
`A3_EARNINGS_PEER_PROPAGATION_V1` with authority NONE. No historical
expedition — A3 is born prospective.
