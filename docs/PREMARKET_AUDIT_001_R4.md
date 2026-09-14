# PREMARKET-SEQUENTIAL-AUDIT-001-R4 — Checkpoint 1A: the staged production producer

Base `602d5a232be851890a23cdd3cd6d4e7b560ed3a0`. Checkpoint 1A only.

**No disposable LaunchAgent was created. The production scheduler was NOT installed. The installed plist and
`ops/premarket.sh` are byte-for-byte unchanged and a test asserts it. No trade, no paper unit, no fee promotion,
no deployment.**

---

## 1. The early-start claim, narrowed as instructed

Retained, because it is established:

* the legacy runner computed `wait = target - now` and then slept `min(wait, 3600)`;
* it did not recheck the target after waking;
* a process that started sufficiently early therefore absorbed immediately on waking;
* the absorption carried the target stage's label, and nothing recorded the discrepancy.

**Narrowed:** the 02:00 ET case is a **controlled early-start fixture**. It does not establish that launchd
produced a coalesced wake at that time on this host. Only the disposable operating-system test can, and it has
not been run.

What the fixture does establish, measured from the two sealed packets rather than asserted:

```
early-start sha 2298087f7d902e0f   on-time sha c88a217675fb6902
same market_date, same absorption_label=0920_ET_final, DIFFERENT CONTENT
newest bar in the early packet 10:00Z; sealed as_of 13:25Z
  -> the packet labelled the 09:20 ET final refresh carries data 205 minutes old, and says nothing about it
UNKNOWN_CATALYST_MOVERS  early=[NVDA, AMD, STAL, FUTR, SYND]   on-time=[AMD, STAL]
```

The last line is the part worth staring at. The early packet marks **NVDA, FUTR and SYND as unexplained
dislocations** when each has a filing that explains it — the filings simply were not knowable yet at 03:00 ET.
The defect does not merely deliver stale data; it manufactures false "nobody knows why this is moving" signals,
which is the single most decision-relevant field in the packet.

---

## 2. One authoritative stage implementation

`apex/frontier/premarket_stages.py` now holds the only implementation of source retrieval, raw capture,
normalization, source disposition, builder absorption, the Captain prompt, the brief firewall and stage record
creation. `scripts/premarket_stage.py` (production) calls it. `scripts/premarket_run.py` **delegates to it** and
is retained only as a parity oracle — reachable from no prepared production artifact.

Asserted structurally, not by reading:

* `assemble(` is called from exactly one place across {legacy runner, staged CLI, stages library};
* the legacy `absorb()` body calls `PS.absorb` and calls nothing resembling `assemble`;
* the schedule, the forbidden-term list and the brief prompt each have exactly one definition, and the legacy
  runner is asserted **not** to restate them.

**Transport substitution boundary:** `apex.intraday.eodhd.fetch_intraday_chunk`, reached through an explicit
`fetch=` parameter threaded through `assemble()` and `_premarket_state()` — a passed argument, not a
monkeypatched module attribute. Everything above it (`normalize_rows`, `_premarket_state`, `assemble`,
`catalyst_state`, `seal`) is real in every run, synthetic or not.

All four seams (clock, transport, Captain, output root) plus the crash injector live in
`apex/frontier/premarket_runtime.py`, and `substitutions()` is stamped on **every journal event**. An empty dict
means fully real. A synthetic packet cannot masquerade as a production one, because the record says what was
replaced. The prepared production shell is asserted to export none of these names.

---

## 3. Durable state — and a correction about what the old runner actually kept

The brick describes the old runner as keeping `PremarketBuilder` state in memory for over an hour. Measured, it
kept less than that: **each of its four absorptions called `assemble()` and rebuilt the entire packet from
scratch.** The only thing carried across the morning was the local name `last`; the three earlier packets were
discarded unrecorded. (It also constructed a fresh `QuotaGovernor` per absorption, so its "daily" LAB budget was
in fact a per-stage budget — preserved as-is, since changing it would change behaviour.)

So "reconstruct the builder" means: recover the newest COMPLETED stage's packet byte for byte from evidence —
and, unlike the old runner, keep the earlier ones too.

`PREMARKET_JOURNAL_V1`, per trading date: an append-only hash-chained `events.jsonl`, content-addressed
write-once `blobs/`, O_EXCL `claims/`, and a flock used only across read-tail-plus-append so sequence numbers are
allocated transactionally. JSON only — no pickle, marshal or shelve anywhere in the entry point's import
closure. A later stage re-hashes every link and every referenced blob before trusting a predecessor.

---

## 4. Transitions

`PENDING → STARTED → CAPTURED → NORMALIZED → ABSORBED → COMPLETED`, with terminal alternatives `TOO_EARLY`,
`MISSED_WINDOW`, `SOURCE_UNAVAILABLE`, `REFUSED_INPUT`, `FAILED`, `RECONCILED_DUPLICATE`.

**Declared narrowing:** the brick lists `LATE_START` among the terminal alternatives; it is implemented as a
start *disposition*, because a stage that starts inside the acceptance window still absorbs and still completes.
Making it terminal would discard a stage the window policy accepts. It is recorded either way.

---

## 5. The complete real morning, through the production entry point

`scripts/premarket_synthetic_morning.py` starts no premarket logic of its own: it sets the clock, points the two
transport seams at fixtures, and invokes `scripts/premarket_stage.py` as a **separate OS process per stage**,
exactly as the prepared agents will. Six processes, the real builder, the real `seal()`, the real firewall.

The ten declared observations are now adjudicated **where production actually decides them**, and this corrects
R2's table. R2 reported all ten as PASS; it could not have, because the production packet builder ingests no news
at all — a "macro event" and a "hostile headline" were being adjudicated by the harness. Two rows are honest
absences rather than passes:

| observation | decided by | outcome |
|---|---|---|
| overnight state | `assemble → closing.load_memory` | ACCEPTED_AS_PRIOR_MEMORY |
| premarket price/volume | `_premarket_state` | ACCEPTED |
| macro event | `SOURCES["MACRO_CALENDAR"]` | MARKED_UNAVAILABLE — **not ingested; declared blind spot** |
| company catalyst | `catalyst_state` | ACCEPTED_AS_KNOWN_CATALYST |
| syndicated duplicate | `catalyst_state` | **RETAINED_BOTH — no deduplication exists in production** |
| revision / retraction | `catalyst_state` | **RETAINED_BOTH — no revision linkage exists in production** |
| unavailable source | `_premarket_state` | MARKED_UNAVAILABLE (`NO_BARS`) |
| stale observation | `catalyst.LOOKBACK_HOURS` | EXCLUDED_AS_STALE (real 72h window) |
| future observation | `catalyst` PIT filter on `known_from_utc` | REFUSED_AS_FUTURE |
| hostile headline | `brief_verdict` | REFUSED_BY_FIREWALL |

The future-observation row is worth naming: the same filing is refused at 08:15 and accepted at 09:05, purely by
the real point-in-time rule, and the packet shows the symbol leaving `UNKNOWN_CATALYST_MOVERS` between those two
stages. Nothing in the harness decided that.

**Independent reconstruction** from the persisted artifacts — re-hashing the chain, loading the newest COMPLETED
packet blob, applying only the one documented finalization mutation, recomputing the seal digest with `seal()`'s
own formula, without calling `finalize()` or trusting anything it recorded — reproduces `c88a217675fb…` exactly.

---

## 6. Parity with the legacy runner

Same frozen transport, same recorded Captain response, same fixture world, on-time controlled clock. The oracle
runs in its own process with `time.sleep` replaced by a virtual-clock advance — unavoidable, since it really does
sleep for seventy minutes, and stated so that "oracle" is not mistaken for "production".

```
13 packet fields compared field by field   0 differing
accepted source observations               IDENTICAL
rejection and unavailable reasons          IDENTICAL
accumulated factual state                  IDENTICAL
packet classification (watch_map/states)   IDENTICAL
Captain input (the exact prompt)           IDENTICAL
final seal input                           IDENTICAL
packet_sha256 (reported, not relied on)    IDENTICAL   c88a217675fb6902
```

**Zero runtime-specific differences were enumerated**, because the clock is controlled on both sides. One real
difference did appear on the first run and was repaired rather than excused: `brief_facts()` serialized without
key ordering, so the Captain received a *different prompt for identical facts* depending on which producer had
serialized the packet — the staged path round-trips it through a canonical sorted-key blob, the legacy path did
not. Sorting makes the Captain's input a function of the facts alone.

---

## 7. Failure and recovery — 15/15, and three defects this found in my own work

Every scenario runs through the real CLI as a real OS process; the crashes are real process deaths (`os._exit`,
no unwinding, no `finally`, no lock release) at real phase boundaries.

All fifteen pass. Three of them did not, at first, and each failure was in code written in this brick:

1. **A crashed stage could never resume.** The run-record filename was doing two jobs — per-invocation accounting
   *and* exactly-once enforcement — so every retry found the file and exited as a duplicate. A run record is now
   per invocation; exactly-once belongs to the journal's O_EXCL claim. One mechanism, one job.
2. **The stale lock made that permanent.** R3's rule keyed staleness on *age*; a stage killed mid-run left its
   lock and every retry was refused. The test is now *liveness*: a living holder is never displaced at any age, an
   unreadable claim is treated as held, and a holder whose process is gone is taken over **with the dead holder
   recorded in the new lock body**. Diagnosed, not silent — which was always the actual requirement.
3. `_pid_alive` was referenced in the journal and defined only in `run_record`.

Recovery reuses the original bytes rather than refetching: a crash after capture **replays the recorded capture**,
a crash after absorption **reuses the recorded packet and runs no capture phase at all**. Exactly-once absorption
and immutable sealed output hold across all fifteen.

One observation from the crash runs: **a hard death loses all buffered stdout** — the killed process wrote nothing
to its log. The fsync'd journal recorded every state it had reached. That is the difference between the two, and
it is the reason the journal exists.

---

## 8. The prepared production artifacts

One LaunchAgent **per stage** (six), each with its own trigger and its own explicit stage argument — nothing is
inferred from the clock. The single long-lived agent's `.NEW` was **removed**, not left lying beside its
replacement. All of them are generated from the schedule by `ops/premarket_repair/generate.py`, and a test runs
`--check` so an artifact cannot drift from the times it claims to implement.

```
com.apex.premarket.0815_ET_initial     05:15 local Mon-Fri  ->  ops/premarket.sh 0815_ET_initial
com.apex.premarket.0832_ET_post_macro  05:32 local
com.apex.premarket.0905_ET_refresh     06:05 local
com.apex.premarket.0920_ET_final       06:20 local
com.apex.premarket.seal                06:25 local
com.apex.premarket.reconcile           06:40 local
   -> scripts/premarket_stage.py --stage <stage>
   -> premarket_stages.run_stage / .finalize -> premarket.assemble -> journal -> premarket.seal
```

`StartCalendarInterval` is **local** time, so these plists are correct only while the host tracks US Eastern.
`generate.py` verifies the ET→PT offset is a constant three hours at a winter and a summer instant, and
`status.sh` now checks the host's actual zone. This dependency was previously undocumented.

AST closure from the staged entry point: **23 modules, `scripts/premarket_run.py` not reachable**, and exactly
three `time.sleep` call sites in the whole closure — two EODHD retry/rate-limit backoffs and one Sharadar
rate-limit wait, none parameterized by a stage target. The test asserts that **set**, so a new sleep appearing
anywhere in the reachable closure fails it.

`status.sh` also drops the stale line claiming launchd never retries a missed calendar run. A run missed while
the machine was asleep is coalesced and fires once on wake — and that is precisely the early start the staged
producer now refuses.

---

## 9. What this does NOT establish

* **launchd behaviour on this host.** Not tested. The disposable agent proof is the next brick.
* **Live providers.** Every source in the morning above was a frozen fixture.
* **Captain generation.** The response is a recorded fixture; the prompt, firewall and schema check are real.
* **Downstream consumption.** The sealed packet still reaches no consumer.
* **`PREMARKET_TIME_V1` is still not wired into production.** Built in R1, imported only by tests. `seal()` still
  writes a single `as_of_time`. R2's evidence file printed a PREMARKET_TIME_V1 block that the harness computed,
  not the producer. Wiring it in changes the packet and therefore breaks the parity claim this brick rests on; it
  belongs to a checkpoint that authorises a behaviour change.
* **Missing sources.** COMPANY_NEWS, ANALYST_NEWS, MACRO_CALENDAR and CROSS_ASSET remain NOT_CONNECTED, and the
  packet says so.
* **Stage coverage is not stamped into the packet.** Missing stages are named in the finalization record, not in
  the packet, for the same parity reason.

## 10. Verdict

`PRODUCTION_STAGED_PATH_SYNTHETICALLY_VERIFIED` — the prepared production entry point completed the entire fake
morning through the real sealer, and the packet reconstructs cleanly from the persisted stage artifacts alone.

Checkpoint 1A remains **not complete**: the scheduler is unproven and uninstalled.

Next, in order: the disposable LaunchAgent proof against **this** entry point; then install, arm and observe one
real scheduled morning; then connect additional sources.
