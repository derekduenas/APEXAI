# Commissioning checklist — SPY options paper pilot

Updated 2026-09-12 (decision-path repair, candidate for independent review). Four columns, four different claims.
"Implemented" means code and tests exist on the candidate. "Independently reviewed" means someone other than the
builder read it against the source. "Connected" means the live path is wired and gated. "Operationally
authorized" means the operator said so on the record. A row is not done until every column it needs is filled.

| Item | Implemented | Independently reviewed | Connected | Operationally authorized |
|---|---|---|---|---|
| Recording boundary (forecast → intent → fill → outcome, hash-chained, atomic reservation) | yes (r2 accepted) | yes (r2, r3) | n/a | n/a |
| Certified risk authority + kernel re-check at commit | yes | yes (r3) | yes | limits: paper $500/trade unchanged |
| Expression rule `PILOT_RULE_V2` (nearest cap-feasible on the signal side) + policy identity end to end | yes (this candidate) | **no** | n/a | default authorized 2026-09-11 |
| Provider-boundary quote validation (declared rights, finite prices, integer sizes, timing, exclusions) | yes (this candidate) | **no** | n/a | n/a |
| PRIME spread gate reachable (spread + quote identity carried; missing ≠ zero) | yes (this candidate) | **no** | n/a | n/a |
| Adverse IV scenario is IV-down for every long option | yes (this candidate) | **no** | n/a | n/a |
| Two-stage freshness per §1.1 (indicative 120 s ranks; 15 s executable at the boundary) | yes (this candidate; `docs/FRESHNESS_ADJUDICATION_2026-09-12.md`) | **no** | n/a | n/a |
| BEFORE fields sealed at intent time (expected_toll, doctrine, pins, reference_quote) | yes (this candidate) | **no** | n/a | estimator amendment pending review |
| Live chain / quote functions | yes (2026-09-11) | **no** | wired, gated by `LiveGate`; **the live bars/NBBO HTTP client is NOT attached** (`_no_http` default; the collector attached its own) | not authorized |
| Live bars / NBBO HTTP client for the pilot process | **no** | no | no | no |
| Fee schedule `PROVIDER_VERIFIED` | **no** (certified authority refuses every LIVE_FEED intent until then) | no | no | **awaiting the broker's published fee document** |
| Release pinned from `main` at a reviewed commit and installed on the host | **no** | no | no | no — `DEPLOYMENT_DIVERGENCE_001` OPEN, nothing deploys until it closes |
| Maintenance block lifted, `APEX_PILOT_LIVE_DATA=ENABLED` for the pilot process only | no | n/a | no | no |
| Paper capital authorized | n/a | n/a | n/a | **no** |
| Collector restarted (for the exit-spread record, not for the pilot) | n/a | n/a | stopped | no |
| Nightly Sharadar pull | armed on the Mac (`com.apex.nightly-pull` launchd, ran 2026-09-12 14:07Z) | n/a | yes | **was already armed; operator to confirm this is intended** |

Blocking for a first sealed observation, in order: fee document → live bars/NBBO client for the pilot process →
release pinned from reviewed `main` (closes `DEPLOYMENT_DIVERGENCE_001`) → maintenance block / live switch → paper
capital. None of these is a research task.

Nothing in this table claims alpha, calibration, profitable expectancy, or live readiness. Synthetic completion is
synthetic completion.
