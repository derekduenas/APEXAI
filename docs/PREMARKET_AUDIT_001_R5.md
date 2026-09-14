# PREMARKET-SEQUENTIAL-AUDIT-001-R5 — Checkpoint 1A: production time truth and timezone safety

Base `533dfbd83d5769a3eb9ad17a5a149c755fdcd2b4`. Checkpoint 1A only.

**No disposable LaunchAgent. The production scheduler was NOT installed. The installed plist and
`ops/premarket.sh` are byte-for-byte unchanged, asserted by test, and no timezone binding was installed into the
live repo.** No trade, paper unit, fee promotion, source connection or downstream wiring.

---

## 1. R4 regression reconciliation — **clean**

Base `602d5a2` and candidate `533dfbd` each ran the full suite with `--junit-xml`, compared **per test ID** by
phase, exception type, failing assertion and normalized traceback.

```
IDENTICAL FAILURES (same id, phase, exception, normalized traceback):  88
NEW FAILURES introduced by the candidate:                               0
FAILURES the candidate FIXED:                                           0
FAILURES whose MECHANISM CHANGED:                                       0
TESTS PRESENT ON ONLY ONE SIDE:                                        45
```

`base 6091 + 43 new = 6134`; `passed 6003 + 43 = 6046`; failed 45 = 45, errors 17 = 17, skipped 26 = 26.

The single test present **only on the base side** is the R4 rename
`test_the_prepared_plist_invokes_the_long_sleeping_runner` →
`test_the_prepared_production_path_no_longer_reaches_the_long_sleeping_runner`, whose assertion was deliberately
inverted when R4 repointed the prepared artifacts. Eight further `TestPreparedProductionPath` tests cover the
same surface; no coverage was removed.

**Two defects in the reconciler itself, found and fixed before any verdict was reported.** Its first run claimed
**50 changed failure mechanisms**. Both causes were in the tool:

1. the two sides live in different worktrees, so every absolute path in every traceback differed — it flagged
   *skipped* tests, which is what gave it away;
2. pytest's truncation notice counts hidden diff lines, and that count grows when the candidate adds files to a
   corpus a test concatenates (93435 → 94815), which made one genuinely identical failure look changed.

A comparator that reports a difference in the thing it failed to normalize is the same defect family this audit
keeps finding — this time in the audit tool.

**R4 introduced no new failure and changed no existing failure mechanism.**

**R5's own full suite is running** against the same base and against R4, so this candidate is not judged by R4's
result. Reported when it lands.

---

## 2. The early-start description, corrected

**R4 overstated this and the correction is accepted.** At 03:00 ET the NVDA, SYND and FUTR filings were genuinely
not yet knowable; `NO_KNOWN_CATALYST_WITHIN_ACTIVE_SOURCES` was the **correct point-in-time answer for that
instant**, produced by a PIT rule that is working as designed. Nothing was fabricated.

The defect is that the old runner stored those correct *early* observations under the **09:20-final stage
identity and packet context**. The consequence is:

> **EARLY OBSERVATIONS MISREPRESENTED AS FINAL-PREMARKET OBSERVATIONS**

The misrepresentation is in the label and the context, not in the classification. An erratum is appended to
`docs/PREMARKET_AUDIT_001_R4.md`; that report's original text is preserved unedited.

**And R5 changes what the same defect looks like.** Under `PREMARKET_CONTEXT_PACKET_V2` the early packet carries
its own contradiction:

```
time.packet_data_cutoff         06:00 ET   <- when this packet stopped accepting input
time.latest_accepted_known_from 06:00 ET   <- the newest thing that actually got in
time.packet_sealed_at           09:25 ET   <- when it was sealed
as_of_time                      13:25Z     (means PACKET_SEALED_AT, and now says so)
```

A 205-minute gap between cutoff and seal, on a packet labelled the final refresh, is now a readable field
comparison. In V1 there was one timestamp and no way to ask the question.

---

## 3. `PREMARKET_TIME_V1` wired into production

Built in R1, imported only by tests until now. The staged CLI, the durable stage records, the Captain input and
the sealed packet all carry it.

**Per source observation:** event / publication / request / receipt / known_from instants, plus
`availability_basis`, `source_timezone`, `normalization` — and `carries_content`.

That last field exists because of a defect found while building this. Taking per-source freshness over *all*
observations let the probe receipts dominate: "we asked SEC EDGAR at 09:20 and nothing matched" is real
information, but it is not *news from 09:20*, and counting it as content made every source perfectly fresh
forever. **A freshness number that can never indicate staleness is not a freshness number.** Content and probes
are now separate, and the packet reports both:

```
per_source_known_from    EODHD 09:20 ET   SEC_EDGAR 09:00 ET   <- newest CONTENT
per_source_last_probe    EODHD 09:20 ET   SEC_EDGAR 09:20 ET   <- when we last ASKED
per_source_freshness_s   EODHD 0.0        SEC_EDGAR 1200.0
```

Fresh on one and ancient on the other means a source that is up and quiet; ancient on both means a source that is
down. A source probed with no content at all reports `UNAVAILABLE_NO_CONTENT_FROM_THIS_SOURCE`, never `0.0`.

**Per stage:** market date, stage, target instant, window open/close, actual process start, capture start and
finish, normalization finish, absorption finish, disposition, lateness, and **code and config identity digests**.

**Per packet:** schema version, morning start *and* this packet's collection start (named apart — they differ by
over an hour), declared information cutoff, latest accepted known_from, per-source known_from / last probe /
freshness, Captain request and response times, created / sealed / known_from.

**The laws hold, each with a test:** `packet_known_from ≥ packet_sealed_at`; freshness derives only from source
instants and is unchanged by sealing later; an accepted input after the declared cutoff refuses; unavailable
times stay unavailable; a late stage's actual capture time is retained and never backdated.

**One deliberate order change.** The Captain now runs **before** the seal. The brick requires the `ai_*` instants
inside the packet and the seal to bind the complete time block; sealing first cannot do both. The brief
*artifact* is still written after the seal because its header cites the sealed digest, and a Captain failure
still leaves the sealed packet standing alone.

---

## 4. Packet schema version

`PREMARKET_CONTEXT_PACKET_V2`. V1 packets keep their bytes and their original interpretation; `interpret()`
reports their source freshness as `UNRECONSTRUCTIBLE` rather than inferring it from the seal clock, while
correctly reporting that their *availability* IS reconstructible.

`as_of_time` is **retained with a machine-readable definition carried on every packet** —
`means: PACKET_SEALED_AT`, `equals: time.packet_sealed_at`, `does_not_mean: [SOURCE_FRESHNESS,
INFORMATION_CUTOFF, LATEST_OBSERVATION_TIME]`, plus the field names that *do* answer those questions. It was kept
rather than removed because `closing_run`, `mission_control` and `frontier_loop` already consume it; removing it
would break real readers to fix a documentation problem.

The seal binds the complete time block — a change to any instant changes the digest (tested).

**Byte parity with the legacy runner is therefore no longer an acceptance requirement.** Semantic parity over the
thirteen V1 fields is, and it holds: **13 of 13 identical**. The differences are enumerated and intentional:

| difference | why |
|---|---|
| `stage_time` absent on the legacy side | one process with no per-stage identity to record |
| `time.ai_request_time` / `ai_response_time` UNAVAILABLE on the legacy side | the oracle still seals *before* briefing, deliberately unchanged |
| `time.morning_started_at` absent on the legacy side | it comes from the journal's session record, which one long-lived process does not keep |
| `packet_sha256` differs | a consequence of the three above |

---

## 5. Market time is authoritative

**Host timezone, from OS evidence rather than assumption:** `/etc/localtime → …/zoneinfo/America/Los_Angeles`
(also `date +%Z` → PDT). `systemsetup -gettimezone` requires administrator access and was **not run** — this
audit changes no host settings. R4 hard-coded `America/Los_Angeles` and verified the assumption at two probe
instants, which is a check that can only agree with itself.

```
STAGE                MARKET     LOCAL  UTC INSTANT (2026-09-14)   MKT-LOC  ALL-YEAR TRIGGERS
0815_ET_initial      08:15 ET   05:15  2026-09-14T12:15:00+00:00  +3.0     05:15
0832_ET_post_macro   08:32 ET   05:32  2026-09-14T12:32:00+00:00  +3.0     05:32
0905_ET_refresh      09:05 ET   06:05  2026-09-14T13:05:00+00:00  +3.0     06:05
0920_ET_final        09:20 ET   06:20  2026-09-14T13:20:00+00:00  +3.0     06:20
seal                 09:25 ET   06:25  2026-09-14T13:25:00+00:00  +3.0     06:25
reconcile            09:40 ET   06:40  2026-09-14T13:40:00+00:00  +3.0     06:40
```

**Two independent mechanisms, because one is not enough:**

1. **Every stage decision is made in market time.** A trigger that fires at the wrong local time lands outside its
   market window and is refused as `TOO_EARLY` or `MISSED_WINDOW`. This holds with no binding installed at all.
2. **The generated schedule is bound to a timezone and the binding is checked.** `timezone_binding.json` records
   the host zone the local triggers were computed for; the CLI refuses with **`TIMEZONE_CONFIGURATION_MISMATCH`**
   (exit 5) if the live host differs, and refuses an *unresolvable* host too rather than assuming a match.

**A host that does not track the market zone needs more than one trigger per stage** — a UTC host needs 12:15 in
summer and 13:15 in winter for one 08:15 ET target, and `StartCalendarInterval` cannot say "whichever is
current". The generator emits **both**; the out-of-season one is refused by mechanism (1).

---

## 6. A latent DST defect, found by these tests

`target_for()` was `now_et.normalize() + Timedelta(hours=h, minutes=m)` — elapsed time from local midnight, which
is not a wall-clock hour on a 23- or 25-hour day. On the spring-forward date the 08:15 target computed as 09:15,
so an on-time arrival was judged `TOO_EARLY`; on the fall-back date it computed as 07:15 and an on-time arrival
was judged `MISSED_WINDOW`. `seal()`'s 09:30 bell guard had the same construction.

**Dormant, not live** — US daylight transitions fall on a **Sunday** in `America/New_York` and this job runs
Monday to Friday, so no scheduled stage has ever hit it. Fixed anyway: a correctness property that holds only by
a calendar coincidence is not a property. A structural test now asserts the construction appears nowhere in the
premarket production modules.

**The same construction still exists at nine other sites** (`shadow_paper`, `mission_control`, `closing_run`,
`arm_session_anchor_evidence`, and the retained legacy runner). Those are outside Checkpoint 1A; they are named
here rather than silently fixed or silently ignored. The legacy runner keeps it deliberately — it is the parity
oracle, and this is now a **second** latent defect it carries.

---

## 7. The morning, and two proofs the brick asked for by name

Six separate OS processes through `scripts/premarket_stage.py`, real builder, real sealer, controlled clock,
frozen transport, recorded Captain response.

**Independent time reconstruction: 25 of 25 checks agree**, with every expectation derived from the fixture's own
declared ground truth rather than from the packet's claims — including that the time block is inside the digest.

**A provider-declared future input** (`SKEW.US`, stamped available 09:45 ET) is refused **at the transport
boundary**, so its rows never reach the normalizer:

```
indices / gap_map / watch_map / blind_spots / source_coverage : does not contain it
the Captain prompt                                            : does not contain it
source_observations                                           : contains the REFUSAL, normalization=REFUSED_AS_FUTURE
```

Refusing it later would be too late — the numbers would already be in the packet with a note attached. The
distinction that makes this safe is that refusal applies to **provider-declared** availability; a receipt three
seconds after a stage starts is latency, not a claim about the future, and is not refused.

**A late-but-allowed stage** (five minutes after target) absorbs and keeps its actual time visible:
`disposition=LATE_START`, `target_instant=08:32`, `process_started_market=08:37`, `lateness_s=300.0`. Not
backdated to its target.

---

## 8. Failure and recovery: 15/15 — and a concurrency defect that lost a whole stage

`RECONCILED_DUPLICATE` was counted as a terminal outcome. A **losing** racer could therefore append its own
duplicate marker before the **winner** reached its work; the winner read that marker, concluded the stage was
already done, and abandoned it. **Five concurrent processes produced zero absorptions — the stage was lost
entirely**, which is precisely the failure this whole audit exists to prevent.

**R4's version of this test passed, but on timing**, not design: the winner happened to finish before the losers
wrote. It was never correct.

The repair separates *terminal* from *decisive*: `stage_outcome()` returns the **first decisive** terminal state
a stage ever reached. First, not last — reading the last state would let a duplicate marker appended after a
`COMPLETED` make a finished stage look unfinished. The flight now runs five racers and asserts **exactly one
absorption AND a COMPLETED outcome**, since "no duplicate absorption" is trivially satisfied by absorbing zero
times.

---

## 9. The prepared production call graph

```
com.apex.premarket.<stage>.plist  (six, one per stage, each with every local trigger the host needs)
  -> ops/premarket.sh <stage>
  -> scripts/premarket_stage.py --stage <stage>
  -> premarket_stages.run_stage / .finalize      (THE authoritative absorb)
  -> premarket_journal                            (durable, hash-chained)
  -> Captain (before the seal, its instants bound by the digest)
  -> premarket.seal                               (the real sealer, V2)
```

Asserted structurally: production reaches **neither** `scripts/premarket_run.py`, **nor** any audit-harness module
(`fake_morning`, `premarket_fixture`, `legacy_oracle`, the two driver scripts), **nor** any stage-target sleep —
the only three `time.sleep` sites in the whole 24-module closure are provider rate-limit and retry backoffs, and
that **set** is asserted. Production **does** reach `premarket_time` and `market_time`.

---

## 10. What this does NOT establish

* **launchd behaviour on this host.** Untested; the disposable agent proof is next.
* **Live providers, Captain generation, downstream consumption.** All still unproven.
* **Real DST rollover in production.** Tested against both 2026 transition dates on a controlled clock; no
  scheduled morning has yet crossed one.
* Missing sources (COMPANY_NEWS, ANALYST_NEWS, MACRO_CALENDAR, CROSS_ASSET) remain NOT_CONNECTED, and the packet
  says so.
* Stage coverage is still named in the finalization record rather than stamped into the packet.

## 11. Verdict

`PRODUCTION_STAGED_TIME_PATH_SYNTHETICALLY_VERIFIED`

Checkpoint 1A remains **not complete**: the scheduler is unproven and uninstalled.
