# EODHD_HUNTER_PILOT — Coverage Gate (FROZEN 2026-08-15, BEFORE any census)

Reconciled with APEX governance norms and frozen before a single coverage
number exists. If EODHD fails this gate the thresholds do NOT move: the
verdict is PILOT_DATA_INSUFFICIENT and the recommendation is a provider
upgrade. Do not rescue the provider.

Pilot window: 2022-01-01 → latest completed date. Rationale (recorded
before testing): EODHD documents materially better intraday availability
for post-2021 delistings — a structural coverage boundary, NOT a
return-favorability choice.

THE GATE — all four required:

1. Overall PIT eligible-minute coverage >= 98% across systematic formation
   dates (Sharadar defines the universe; EODHD coverage is an observed
   limitation, never the universe definition).
2. No material systematic undercoverage of distressed/delisted names:
   coverage of names delisted within the window must be >= 90%, and the
   gap between delisted-name coverage and active-name coverage <= 8
   percentage points. (Missingness concentrated in failures is
   survivorship bias wearing a vendor costume.)
3. Benchmark/sector context coverage >= 99.5% (SPY/sector ETFs and the
   index constituents needed for relative strength).
4. Identity: unresolved/ambiguous mappings <= 0.5% of the PIT universe;
   every ambiguity fails closed and is recorded.

Stratifications required in the census (mcap, ADV, price, sector,
exchange, eventual delisting state) — an aggregate pass with a stratum
failure in delisted/distressed names FAILS the gate.
