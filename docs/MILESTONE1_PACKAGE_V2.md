# MILESTONE PACKAGE — operating hold, commissioning through the open, EXP-001 admission, chain readiness, dashboard v0

Supersedes nothing; extends `docs/MILESTONE1_PACKAGE.md` (recovery) with the
work authorized afterwards. Every status is one of implemented · integrated ·
tested · historically evaluated · prospectively validated · authorized for
production, and none is promoted here.

## 1. Exact commits and configuration changes

| Line | Commit | Content |
|---|---|---|
| `milestone1-r2` | `56b9b6b3` | options-paper hold APPLIED 2026-09-07T17:52:27Z, verification |
| `milestone1-r2` | `4122f819` | hold record correction (zero journal entries, not one) |
| `milestone1-r2` | `ec1bfc50` | APEX Dashboard v0 |
| `milestone1-r2` | `cf4d8886` | full-chain readiness map, six registered evaluations defined |
| `alpha-exp-001` | `e3e1a934` | EXP-001 admission package |
| `alpha-exp-001` | `dc321587` | economic path, engineering mode, 25 tests |
| production | `73fc712d` | unchanged; deployed 15:46:07Z |

**Configuration changes on the host, all recorded with hashes:**
one marker `/apex-data/core/ops/MAINTENANCE_BLOCK_options_paper`
(`fafdcb7d…`), one dedicated drop-in
`/etc/systemd/system/apex-options-paper.service.d/10-maintenance-block.conf`
(`df7af29b…`), one `daemon-reload`. `slice.conf` and the two other services'
drop-ins are unchanged by hash. Nothing else was touched; no service was
restarted.

## 2. Hold verification (without launching)

| Required | Result |
|---|---|
| published script equals staged copy | byte-identical `a7cbb53c…` |
| unit state before acting | inactive/dead/disabled; **no launch since deploy** (journal: no entries) |
| systemd loads the condition | drop-in listed by `systemctl show` |
| condition prevents activation | `systemd-analyze`: conditions failed |
| deployed preflight reports MAINTENANCE_BLOCKED | yes, from the running release |
| blocked decision consumes no recovery attempt | three forced-RTH ticks: `recovery_attempts=0`, `count=3`, no action, no real start invocation |
| unit remains inactive | inactive, `ConditionResult=no` |
| orchestrator continues useful work | counter 4017, success, 0 kills, 127→ ticks |
| equity-fabric and btc-resolver holds intact | markers present, drop-ins unchanged |

Removal is never automatic; it requires explicit activation authorization.

## 3. RTH observation — PENDING (armed)

A host-side observer (`pid 1714883`) fires at **2026-09-08T13:15:00Z** and
samples for 3,600 s across the 13:30Z open: completed ticks and heartbeat,
unit restart/OOM signals, unit cgroup peak, newest ledger record size and
history entries, launch/refusal outcomes, and ledger prefix hashes. It touches
nothing. Output: `/apex-data/tmp/m1_rth/commission_rth.{log,json}`. The
quiet-period figures (30 samples, peak 13.5 MiB) and the trading-hours
figures will be reported **separately** and are not comparable to the
previous multi-day peak.

**Production evidence of R2 already in hand (quiet period):** at
18:31:39Z the newest record carried one incident, `btc-paper`
`SESSION_MISSED_START`, with **166 deferrals since 15:46:21Z held in 4 history
entries and 1,777 bytes**. Under the previous code that would have been 166
per-tick entries (~22 KB) growing every minute — the exact mechanism that
produced the 262,275-byte record.

## 4. EXP-001 admission package

`docs/EXP001_ADMISSION_PACKAGE.md` on `alpha-exp-001` (`e3e1a934`): registered
hypothesis, target, chronological splits with embargo, primary statistic
(DM-HAC, L=14, threshold 2.0), null control, search budget (2/1/0),
per-source and per-field eligibility with limitations, cutoff and
availability semantics, data/version manifests, economic assumptions,
positive-control development history with every measured statistic, the
illustrative and explicitly non-binding power figures, and the proposed
`WORLD_MODEL_REAL_DATA_BOUNDARY_V0` as a separate contract that leaves the
synthetic laboratory's prohibition intact.

**Exact blocker:** `REAL_EVIDENCE_PATH: /apex-data/history-b/... resolves
inside /apex-data/history-b` from the lab boundary; no real-data boundary
exists. Blocked by the absence of the contract and the correct refusal of
the lab, **not** by dataset eligibility. Decision requested: accept the
limitations for this experiment, create the boundary, and narrow fields if
any fails rather than blocking the corpus.

## 5. Full-chain readiness map

`docs/MILESTONE1_CHAIN_READINESS_MAP.md` (`cf4d8886`): every component with
implementation path, inspected callers, inputs/outputs, tests, evidence,
readiness, and missing work. No component is above "tested". The
Participant model and a real-data Multiverse are NOT_IMPLEMENTED by mandate.
Six bounded evaluations (E1–E6) are defined — full strategy vs cash, vs the
simplest alternative, PRIME removal, Risk removal (research only), spread
sensitivity, capacity — none run, all gated on admission.

## 6. Executable economic path — engineering mode

`apex/world_model/exp001/economic_path.py` (`dc321587`), 25 tests green:

forecast → executable-range benchmark (option-implied at 15m NOT_ESTIMABLE)
→ {CASH, LONG_15M, SHORT_15M} as STOCK → SIMULATED marketable fill through
the modelled spread, sized from the executable loss at the stop → PRIME_RULES_V0
→ `apex.capital.arena.compete` → `apex.organism.risk_certificate.certify`
→ `apex.organism.book` on an isolated ledger → outcome → attribution.

What the tests prove: refusals at the front, NO_SIGNAL selects cash with no
position, abstention below one round trip, fill rejection and partial fill
handled, **independent Risk refuses a stock-with-stop and the refusal is
accounted**, Risk cannot be bypassed (single funding site after certify), no
broker dispatch reachable, isolated book, no outcome on an unfunded path, no
outcome before its forecast, every trace ends at a named stage.

**What is missing, stated:** the fundable class is DEFINED_MAX_LOSS, i.e. a
long option; the path stops at Risk's correct refusal for stock. Wiring the
option expression needs a quote chain and the leg-derived certification
(`legs`, `contracts`, `multiplier`, `net_debit`). Not a placeholder; the next
engineering step. Unsupported execution assumptions (queue position, latency,
adverse selection) are labelled, not fabricated.

## 7. Dashboard v0 — preview and data-source mapping

`scripts/apex_dashboard.py` (`ec1bfc50`), stdlib server bound to
`127.0.0.1:8790`, read-only, no controls, no credentials, no external loads,
15-second bounded refresh, UTC throughout. Previewed locally through an SSH
tunnel in the browser pane; all three views render from live artifacts.

| View | Metric group | Authoritative source | Quality semantics |
|---|---|---|---|
| Command Center | operating mode | `docs/MILESTONE1_PACKAGE.md` | DECLARED |
| | deployed release, branch heads | `readlink /opt/apex/current`, `git rev-parse` | MEASURED |
| | 13 units: state, result, restarts, cap, peak | `systemctl show`; unit cgroup `memory.peak` while running | MEASURED / NOT_AVAILABLE between restarts |
| | maintenance holds | `/apex-data/core/ops/MAINTENANCE_BLOCK_*` | MEASURED; enforced by systemd drop-ins |
| | heartbeats | `/apex-data/core/heartbeats/*.json` | MEASURED / ALIVE_IDLE (beat fresh, no recent work) / STALE (beat stopped) |
| | newest orchestrator record | `/apex-data/core/ops/orchestrator.jsonl` tail | MEASURED |
| | journal OOM counts | — | **NOT_AVAILABLE** (no sudo in the dashboard) |
| | forecast/scenario/opportunity/expression/risk/book/learning views | — | **NOT_READY**, shown explicitly |
| Market Data | six health artifacts | `intraday/*_health.json`, `btc/*_health.json`, `crypto/crypto_health.json` | MEASURED |
| | ETF corpus | `history-b/etf_continuous/integrity.jsonl` | event per bar; receipt bulk 2026-08-29; publication/revision NOT_AVAILABLE |
| | PIT single-name | `history-b/pit_singlename/membership_v1.jsonl` | MEASURED (last membership row) |
| | options history | `history-a/options_history/manifest.jsonl` | receipt per file; publication per row |
| | live capture | `data/live/alpaca_fabric/bars` | receipt per file |
| | PULSE verdicts | `results/pulse010r_SUMMARY.json` | RECORDED |
| Research | EXP-001 registration | `alpha_wt/results/exp001_registration.json` | RECORDED |
| | execution/admission status | `docs/EXP001_ADMISSION_PACKAGE.md` | RECORDED |
| | evidence classes | — | synthetic only; historical NONE; prospective NONE |

Synthetic fixtures appear nowhere as live evidence. Not published; not a
production service.

## 8. Remaining blockers and next acceptance criteria

| Item | Blocker | Acceptance |
|---|---|---|
| RTH commissioning | time: 2026-09-08T13:30Z | restart counter static, zero kills, ticks completing, `options-paper` and `equity-fabric` MAINTENANCE_BLOCKED with no action, prefixes intact, unit peak recorded and reported separately from the quiet period |
| options-paper activation | authorization | explicit; the hold is never lifted automatically |
| seven long-lived writers on the old chain reader | separate restart authorization | not part of recovery |
| EXP-001 real run | admission decision (section 4) | limitations accepted, `WORLD_MODEL_REAL_DATA_BOUNDARY_V0` created, fields narrowed if any fails |
| funded expression class | engineering | long-option path through leg-derived certification, engineering tests |
| E1–E6 | admission | registered before any real row; sealed evaluation consumed once |

No live brokerage action, capital deployment, model promotion, hold removal,
or real-data execution occurred. Phase 2 remains OPEN. Real-data admission
remains NOT_AUTHORIZED. Nothing here establishes trading performance.
