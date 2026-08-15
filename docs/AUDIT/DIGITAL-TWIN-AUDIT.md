# DIGITAL TWIN AUDIT (2026-08-15, frozen)

## Scorecard (no fake 0–100)

| Dimension | Rating | Evidence |
|---|---|---|
| DATA QUALITY | ADEQUATE | vendor bars normalized, dedup upstream, quality flags propagate |
| PIT SAFETY | STRONG | one visibility choke point; full-pass poison test clean |
| FRESHNESS | WEAK | one global staleness rule (>10min bar age); no per-facet TTL; a stale sector ETF degrades health strings but the freshest-vs-stalest facet mix is not modeled |
| STATE COMPLETENESS | WEAK–ADEQUATE | has trend/vol/breadth-proxy/dispersion/VWAP/liquidity(dollar-vol); MISSING: correlation, event load, regime PMF + transition probability (F-03), per-symbol liquidity beyond ADDV, gap environment at market level, execution health |
| UNCERTAINTY | WEAK | crude binary uncertain proxy (labeled crude, conservative-only); no graded uncertainty |
| TRANSITION DETECTION | MISSING (intraday) | daily online classifier exists (apex/world/state, lag ~4d median) but is NOT wired into the intraday loop |
| CONSISTENCY | ADEQUATE | impossible-world probes: breadth is computed from the same sector returns it summarizes (cannot self-contradict); stale inputs flip `usable=False` rather than asserting a state |
| LATENCY | ADEQUATE | state snapshot ~10s; full tick minutes-scale, within the 900s budget (measure live Monday) |
| PROVENANCE | STRONG | code commit + protocol hash + evidence class in every record; chained |
| DOWNSTREAM USE | ADEQUATE | market state feeds RS, playbook context, capital uncertainty; sector states feed RS; breadth/dispersion recorded but not yet consumed by any decision (observational) |

## Is the current Twin genuinely good enough to represent the world for a serious intraday Hunter?

**NOT YET — it is an honest but thin world.** It is PIT-safe, provenance-
complete, and fail-closed, which is the hard part. What it lacks, exactly:

1. Regime PMF + transition probability in the intraday loop (F-03 — the
   frozen protocol already promises the field).
2. Per-facet freshness TTLs (a 30-minute-old sector state should degrade
   that facet, not just a global health string).
3. Cross-sectional correlation state (day A vs day B in the operator's
   NVDA example is partly a correlation statement; the Twin cannot see it).
4. Event load / catalyst proximity (blocked on timestamped event data —
   already a declared external gap).
5. Graded uncertainty instead of a binary proxy.

None of these block Monday's observational mission; items 1–2 are
engineering, items 3–5 are data/design work for post-Week-1. Do not add
any of them during the observation freeze except the protocol-compliance
field (F-03 remediation).
