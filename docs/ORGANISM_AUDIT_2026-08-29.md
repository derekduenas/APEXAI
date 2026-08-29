# APEX ORGANISM CONSOLIDATION & KILLER-SYSTEM AUDIT — 2026-08-29

Authority: audit + behavior-neutral consolidation only. No new architecture.
Every claim below was verified against the live DO runtime and canonical
ledgers, not descriptions. Release at audit close: `2424c464` + the
weekend-liveness repair.

---

## 0. WHAT THE AUDIT CAUGHT LIVE (before any table)

1. **apex-catalyst was crash-looping** (678 restarts, ~11 hours): the
   non-trading-day branch of `phase_at()` returned a dict without the
   `session` key the service loop reads unconditionally. First weekend after
   go-live = first execution of that branch. **REPAIRED + regression test.**
   Lesson re-learned: my own "active" verification after Friday's restart was
   taken inside the restart grace window — a shallow echo, not the artifact.
2. **apex-crypto-arena retired (disable-and-observe phase)**: 24/7 Coinbase
   websocket + 60-second ticks + pandas, 9.8MB of ledger, **2 lifetime
   decisions**, written in pre-organism vocabulary (`crypto_assassin`,
   `captain_state`), read by nothing active, expected by neither the health
   model nor the orchestrator, holding a second shadow position book outside
   Capital Arena. Textbook split-brain remnant. Reversible:
   `systemctl enable --now apex-crypto-arena`; ledger and code preserved.

---

## 1. THE ACTUAL ORGANISM MAP (verified argv, writers, readers)

```text
SENSE
  apex-equity-fabric      alpaca_fabric.sh 660      → data/live/alpaca_fabric/bars/   (calendar-triggered by orchestrator)
  apex-btc-ws             btc_ws_stream.py          → results/btc/ws_book_ledger      (Bitnomial L2)
  apex-btc-derivatives    btc_derivatives_poller.py → results/btc/derivatives_ledger  (Deribit funding/OI/basis)
  apex-catalyst           catalyst_service.py       → results/catalyst/{events,reactions,cycles}
                                                      + parallax pass at POST_CLOSE_SEAL

HUNT
  apex-options-paper      options_paper_session.py  → options_live_ledger.jsonl       (calendar-triggered, RTH)
  apex-equity-shadow      equity_shadow_session.py  → outbox/equity_shadow_decisions + shadow_outcomes
  apex-btc-paper          btc_paper_session.py      → results/btc/paper_ledger.jsonl

ALLOCATE (exactly one path, proven)
  apex-organism           organism_service.py       → allocator_decisions + paper_book
    book.fund() is called by allocator.py ONLY; paper_book.jsonl written by book.py ONLY
    risk_kernel: STRUCTURAL_VETO_ONLY, below nothing

EXPERIENCE / REMEMBER
  paper_book.jsonl (canonical) → experience_graph.jsonl (derived, rebuildable)

EVOLVE (faculties, zero trading authority — all verified by AST/non-interference tests)
  AURELIUS     scripts/aurelius.py + ~/bin/aurelius     (CIO; reads, forecasts, cannot promote)
  EdgeForge    apex-edgeforge-observatory (live sidecar) → research ledgers, direction absolute
  Chronos      apex/chronos (causal clock, poison suite) — DORMANT offline lab, no unit, campaign scripts only
  PARALLAX     inside catalyst seal + ~/bin/parallax     — SHADOW OBSERVATORY, fences verified again today

GOVERN
  apex-orchestrator       apex_orchestrator.py      exchange-calendar trigger + reconciler (starts fabric/options daily)
  apex-health.timer       apex_health.py --json     10-min health snapshots
  chain ledgers           append-only, hash-chained
  Operator                sovereign; real capital LOCKED
```

Prohibited arrows (all structurally tested): PARALLAX→anything trading;
faculties→allocation; sleeve→self-funding; anything→Tier-3.

## 2. COMPONENT VERDICT TABLE

| Component | Class | Unique economic purpose | Verdict |
|---|---|---|---|
| equity-fabric | INFRA/SENSE | only bar writer for equity+catalyst reaction measurement | **KEEP** |
| btc-ws + btc-derivatives | INFRA/SENSE | only L2/derivatives capture; feeds BTC predator | **KEEP** |
| catalyst | SENSE (ACTIVE_DECISION_INTELLIGENCE, consulted-never-obeyed) | only world-event interpreter; owns expectations + reactions | **KEEP** (weekend defect repaired) |
| options predator | HUNT | only options expression; 4 sessions, −$82 | **KEEP, frozen** |
| equity day-trading predator | HUNT | only intraday equity expression; honest 1R since repair | **KEEP, frozen** |
| btc predator | HUNT | only BTC expression; episode-based evidence; 0 candidates yet | **KEEP, frozen** |
| capital arena + risk kernel | ALLOCATE | the single allocator + sovereign veto (bypass search: clean) | **KEEP** |
| paper book | EXPERIENCE | the only economic truth; single writer verified | **KEEP** |
| experience graph | REMEMBER | derived memory; never authoritative (verified) | **KEEP** |
| AURELIUS | EVOLVE | CIO with forecast accountability; 8 preserved forecasts | **KEEP** |
| EdgeForge observatory | EVOLVE | prospective skeptic sidecar; distinct from Chronos | **KEEP** |
| Chronos | EVOLVE | historical causal lab (poison suite, causal clock) | **KEEP as DORMANT faculty** — no runtime cost; wake only for a registered historical question |
| PARALLAX | EVOLVE | expectation-violation observatory; all fences re-verified | **KEEP, sealed, stop building** (already stopped) |
| orchestrator + health timer | GOVERN | calendar authority + reconciliation | **KEEP** |
| **crypto-arena** | LEGACY | none — superseded by BTC predator + Capital Arena | **RETIRED (disabled 2026-08-29, observing; reversible)** |
| options-acquire | LEGACY/INFRA | one-shot historical acquisition; inactive | **DEMOTE to manual tool** (no change needed) |
| pattern_observatory, frontier, frontier2, captain, hunter, intraday, vision, world, experiments, world_lab, exploration, regime, causal, execution_manual/paper (~30 packages) | LEGACY CODE | pre-organism eras; no unit runs them; some have 0 importers | **LEAVE IN REPO** — zero runtime cost; repo archaeology is history, not the organism. Do not delete during freeze; candidates for a later `apex/attic/` sweep if repo weight ever hurts. |

**The active organism is ~8 packages and 12 units. The repo holds ~49
packages. The difference is sediment from five eras of building — none of it
running, none of it burning anything but grep time.**

## 3. AUTHORITY AUDIT RESULTS

- **One allocator**: `book.fund()` called only from `allocator.py`; ledger
  written only by `book.py`. The hidden-second-allocator search found exactly
  one — the crypto arena's private book — now retired.
- **Risk kernel sovereign**: no override path exists from AURELIUS, arena,
  catalyst, PARALLAX, or any predator (AST + integration tests).
- **AURELIUS constrained**: transport law, no self-authority, forecasts
  prefix-only, evidence tiers labeled.
- **PARALLAX constrained**: taxonomy_sha stamping, current-session prospective
  fence, contamination fence, preview/canonical separation — all re-verified.
- **Target bias (§49)**: grep for the 100–200%/$10M objective in code found
  ZERO leakage (all "annualized" hits are BTC funding-rate arithmetic).
  The North Star lives only in governance prose, where it belongs.

## 4. THE ECONOMIC SCOREBOARD (canonical ledgers, never pooled)

```text
OPTIONS (canonical sleeve ledger, 4 prospective sessions)
  attacks 7 · resolved 6 · execution_failures 1
  executable PnL by session: −122 / +129 / −54 / −35  →  cumulative −$82
EQUITY (2 prospective sessions, era boundary at the 1R repair)
  decisions 244: NO_THESIS 217 · CHASE_REFUSED 25 · GEOMETRY_REFUSED 1 · ATTACK 1
  the 1 attack: −$586.16 at −1.95R (pre-repair sizing era; record immutable)
BTC (SHADOW, ~5 days)
  296 windows: NONE_OBSERVED 291 · SUSCEPTIBLE_NOT_TRIGGERED 5 · candidates 0
ORGANISM BOOK
  fundings 4 (2 voided as REFUSED_STALE canaries) · outcomes 2 · capital 9,378.84
CATALYST-REACTION  1 prospective session: 224 reactions, 23 disagreements
PARALLAX           prospective evidence 0 (era starts Monday)
EXPECTANCY (every sleeve): NOT_ESTIMABLE — denominators are single digits
CAGR / CAPACITY / $10M PATH: NOT_ESTIMABLE
```

## 5. MONEY-LOSS ATTRIBUTION (all resolved losses, layered honestly)

| Loss | Thesis | Location | Expression | Sizing | Execution | Verdict |
|---|---|---|---|---|---|---|
| SPY −0.19R (08-24) | RIGHT | ok | **WRONG** (option lost while thesis right) | ok | ok | EXPRESSION |
| MSFT −0.21R (08-24) | **WRONG** | — | — | ok | ok | VALID LOSS |
| 08-27 session −$54 | **WRONG** (both) | — | ok | ok | ok | VALID LOSS |
| AAPL −$35 (08-28) | not scored | — | — | — | **FAILURE** | EXECUTION_FAILURE (attribution debt) |
| NVDA −$586 (08-28) | RIGHT (MFE +3.91%) | acceptable band | ok | **WRONG BY CONSTRUCTION** (friction-blind, repaired) | — | SIZING — tuition paid once |

Pattern at n=6: losses are dominated by *thesis wrong* (normal) and two
*non-thesis* defects that were both repaired structurally. No loss yet
attributable to allocation, risk model, or data.

## 6. MONEY-MISSED ATTRIBUTION (the North-Star side of the ledger)

From the opportunity census + funnel: top-5 daily moves were consistently
IN-universe; thesis frequently present and directionally right; losses of
capture happened at **GEOMETRY/TIMING (chase band, 25 refusals) and
EXPRESSION** — not at recognition. Hindsight control (median +0.077% at actual
decision points) says the naive "just take them all" fix is NOT supported.
This is the single most valuable open question the organism owns.

## 7. NORTH STAR GAP ANALYSIS

**What stands between APEX and sustained 100–200%?**
Not architecture. Not intelligence. Not risk plumbing.
**We do not yet have enough prospective evidence to know whether ANY predator
has positive after-cost expectancy.** Candidate throughput is low (7+1+0
funded-eligible candidates across all sleeves, ever) — but the CAUSE of low
throughput is NOT YET IDENTIFIED, and the candidate causes have radically
different solutions (operator taxonomy, sealed):

```text
A. the market simply offered few valid opportunities
B. the universe is unnecessarily narrow
C. APEX sees opportunities and refuses them CORRECTLY
D. APEX sees opportunities but geometry blocks them INCORRECTLY
E. thesis formation itself is too restrictive
F. data/state representation is missing opportunities
```

Our own evidence already makes D the most interesting live hypothesis
(the chase/geometry near-miss population), which is exactly what the sealed
near-miss cohort exists to discriminate. Bottleneck, stated honestly:
**PROSPECTIVE EVIDENCE STARVATION, WITH THE CAUSE OF LOW CANDIDATE
THROUGHPUT NOT YET IDENTIFIED.**

The three evidence questions that matter most (everything else waits):
1. **CHASE-BAND / opportunity capture** — do the 25 chase refusals protect
   capital or forfeit the edge? Discriminator: the sealed near-miss cohort
   (1.78–2.99 ATR band) resolving over coming sessions, vs funded attacks.
2. **After-cost expectancy of the options sleeve** — 4 sessions say −$82 with
   execution as part of the alpha; needs 10+ sessions before the checkpoint
   question ("is friction eating a real edge?") is answerable.
3. **Post-repair equity 1R economics** — friction fraction by stop width
   (FRICTION_DOMINANT_GEOMETRY needs its 4–5 contrasting resolutions).

## 8. $10M SCALABILITY REVIEW (foresight only, nothing built)

- **Scales cleanly**: arena/kernel/book are size-parametric (limits are
  numbers, not assumptions); ledger/evidence machinery is size-agnostic;
  promotion ladder was built for exactly this.
- **Becomes constrained**: 9-symbol mega-cap universe ≈ one macro bet in
  costumes (AURELIUS already flagged it) — breadth, not architecture;
  intraday tight-stop geometry (friction fraction rises as size divides by
  liquidity at the stop); options paper fills vs real book depth.
- **Future transition (proposal only, gated on proven edge)**: horizon
  diversification — the §40 check passes: nothing hard-codes INTRADAY=BEST;
  holding horizon is a per-sleeve constant, not an organism assumption.
  A swing expression would be a new sleeve behind the same arena — the
  architecture already has the socket.

## 9. THE 20 QUESTIONS (§56), plainly

1. Coherent full organism? **YES** (after today's retirement + repair).
2. Major component redundant? **Was: crypto-arena. Now retired.**
3. Legacy service alive without purpose? **No longer.**
4. Hidden competing authorities? **One found (crypto book), removed. None remain.**
5. Trading decision path clean? **YES** — sense→hunt→arena→kernel→book, one hop each.
6. Research path clean? **YES** — outbox→faculties, direction absolute.
7. Economic record canonical? **YES** — with the ledger-mixing law respected.
8. Graph derived, not authoritative? **YES** (rebuildable, tested).
9. AURELIUS constrained? **YES**. 10. PARALLAX constrained? **YES**.
11. Arena the only allocator? **YES** (verified at the call-graph level).
12. Risk kernel sovereign? **YES**.
13. Complexity without purpose? **Runtime: no longer. Repo: ~30 dormant packages, zero runtime cost.**
14. Remove? **crypto-arena (done, observing).** 15. Merge? **Nothing** — every overlap candidate proved distinct. 16. Demote? **options-acquire to manual tool; Chronos stays dormant faculty.**
17. #1 bottleneck to money? **Prospective evidence starvation, bound by candidate throughput.**
18. #1 bottleneck to scale? **Universe breadth / correlated mega-cap concentration** (matters only after edge exists).
19. Compatible with $10M? **PARTIALLY_COMPATIBLE** — core scales; breadth and capacity measurement don't exist yet (correctly).
20. Next? **Run Monday. Frozen trader, honest 1R, baselines armed. Let sessions accumulate.**

## 10. FABLE'S RECOMMENDATION — what actually makes this a killer

The system is already what a killer looks like structurally: small active
core, causally honest, economically ruthless, hard to fool, willing to hold
cash. What it is missing is not a component — it is **at-bats**. Concretely:

1. **Protect the freeze.** The single highest-EV action for the next 10
   sessions is to change nothing and let the counters grow. The
   highest-value defects to date have disproportionately been exposed by
   real prospective flow — though deliberate static attack matters too:
   the weekend crash loop was found because this audit attacked the
   runtime on a Saturday.
2. **The chase-band question is the crown jewel.** It is the one place where
   the data already hints the hunter may be leaving the actual edge on the
   table (thesis right, geometry refused). Do not tune it — let the sealed
   near-miss cohort resolve it. If it resolves toward capture, that is worth
   more than any new faculty ever proposed.
3. **Treat throughput-cause identification as the review-gate work.** At
   checkpoint, first identify WHICH of causes A–F is operating; only then
   consider the lever. If B (narrow universe) is implicated, universe
   breadth is the cleanest expansion — same thesis logic, same thresholds,
   same kernel, same arena, same evidence law — but it is an EXPERIMENT
   that changes opportunity distribution, sector diversity, liquidity,
   friction, simultaneous-candidate frequency, and the census denominator.
   When that day comes: predeclare EQUITY_UNIVERSE_V2 prospectively with
   eligibility RULES (never cherry-picked names), treat it as an ERA
   BOUNDARY, and analyze V2 outcomes separately. No quiet symbol adds, no
   pooling across eras.
4. **OPTIONS CHECKPOINT = 10 PROSPECTIVE SESSIONS — review, never a
   trigger** (operator law, superseding this audit's original "kill on
   schedule" phrasing, which violated our own evidence doctrine: ten
   sessions is a review checkpoint, not an economic sample size). At
   checkpoint, REVIEW ECONOMICS — do not automatically KEEP / KILL /
   PROMOTE / TUNE. Evaluate: resolved executable trades, independent
   opportunity episodes, net expectancy, friction anatomy, thesis-vs-
   expression failures, regime diversity, baseline comparison, selection
   denominator, uncertainty. Ten sessions with nine executable trades is
   nowhere near enough to kill a mechanism unless the failures are
   STRUCTURAL, not statistical. If evidence remains insufficient:
   NOT_ESTIMABLE, plus the observation that would resolve it.

## 11. OPERATOR RATIFICATION — FINAL SEALED STATUS (2026-08-29)

Three corrections ratified into this document (defect-discovery phrasing,
the Options checkpoint law, the throughput-cause taxonomy) — each replacing
an over-claim that could have pushed a bad decision later. The operator's
framing supersedes: APEX has finished building its digestive system; now we
learn whether the food it finds contains calories. Candidate throughput is
not the North Star — ECONOMIC OPPORTUNITY CAPTURE is. Few opportunities ×
high information content × good location × honest risk × low friction ×
correct allocation = extreme geometric compounding, at whatever trade
frequency the market decides.

```text
ARCHITECTURE             COMPLETE ENOUGH
ORGANISM                 COHERENT
REAL CAPITAL             LOCKED
EDGE                     NOT_ESTIMABLE
RETURN CAPABILITY        NOT_ESTIMABLE
100-200% NORTH STAR      UNCHANGED
$10M STRETCH GOAL        UNCHANGED

PRIMARY TASK NOW:
GENERATE CLEAN PROSPECTIVE ECONOMIC EVIDENCE

MONDAY:
RUN UNCHANGED.
```

No more architecture until the market identifies a missing organ.
