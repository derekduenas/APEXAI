# EXP-004 historical result — NOT_SELECTED

One authorised run. **The registered comparison was not adjusted, and nothing
was re-run.** Evaluation and reserve were never requested.

| | |
|---|---|
| run | `20260910T145642Z-exp004-a8ac65ed` |
| terminal exit | **0**, `process_outcome: SCIENTIFIC_COMPLETE` |
| **status** | **`NOT_SELECTED`** |
| wrapper outcome | `COMPLETED_WITH_RESULT`, `result_sealed: true`, counted |
| started / finished | 2026-09-10T14:56:41Z → 15:08:35Z (11 min 54 s) |

## Decision and source binding

| | |
|---|---|
| decision sha256 | `2919dba0e94d5c6428abeac2768b7cb21abbbf0fb7e8d56a067f09328d0edc2a` |
| code commit | `ea87faa42537a14678bb6fc5cb1e9aacc83cf40f` (the approved pin) |
| registration | `9155024f…45bf9` |
| adapter entry point | `apex.world_model.exp004.run.tournament` |
| run mode / inference | **`HISTORICAL`**; `registered_values: true`, `B = 10,000`, seed `20260909`, `historical_path_valid: true` |
| imports match admitted commit | **true** |
| source identity at completion | **unchanged**; `acceptance_qualification: VALID` |
| periods opened | fit 754 sessions (2016-01-04 → 2018-12-31); development 757 (2019-01-02 → 2021-12-31) |
| evaluation / reserve | `SEALED: never requested by this run` |

## Fit accounting and eligible rows

**10 estimations, enforced by counting wrappers on the real fitters:** 1
baseline set, 3 clipping constants, 4 location fits, 2 dispersion fits. **Zero
refits.**

- fit: **247,692** eligible rows from 754 sessions. Refusals — WARMUP 22,620, EMBARGO 22,620, MISSING_FEATURE_BARS 30, MISSING_TARGET_BAR 9, RV_FLOOR 0, MISSING_PRESSURE_BARS 0, INVALID_OHLC 0, NO_BASELINE_SUPPORT 0, ZERO_BASELINE 0; 10 zero-range bars inside windows.
- development: **248,563** eligible rows from 757 sessions. Refusals — WARMUP 22,668, EMBARGO 22,680, MISSING_FEATURE_BARS 115, MISSING_TARGET_BAR 33, all pressure-specific refusals 0.
- row-key identity **computed**: 1 key set, 248,563 keys, identical across every comparison.
- clipping at the fit-split 0.99 quantile: `q_B 0.4178`, `q_P 6.4231`, `q_F 1.8598`; 2,476 rows clipped per feature (1.0%).
- D0: `s₀ = 3.29178`, `ν₀ = 6.41323`, 58 iterations, not at a bound. D1: `s₁ = 3.33974`, **`λ = −0.00922`**, `ν` frozen at `ν₀`, 64 iterations.

## Primary gate P1 (C vs A×) — all four decisions

| | mean | t / p | 95% interval | pass |
|---|---|---|---|---|
| **HAC D0** | −3.948e-05 | t = **−1.0308** | [−1.145e-04, 3.559e-05] | **false** |
| **BOOT D0** | −3.948e-05 | p = **0.81672** (k = 8,167) | [−1.265e-04, 4.638e-05] | **false** |
| **HAC D1** | −4.051e-05 | t = **−1.0483** | [−1.162e-04, 3.523e-05] | **false** |
| **BOOT D1** | −4.051e-05 | p = **0.81992** (k = 8,199) | [−1.284e-04, 4.577e-05] | **false** |

`SELECTED` requires all four. **Outcome `NOT_SELECTED`**, with all three flags
false: no inference disagreement under either specification, and **not**
specification-sensitive — the two dispersion specifications agree.

The fitted coefficient on `F̃` in arm C is `θ = +1.23e-05`. Per the
registration this is a **partial association** holding the other regressors
fixed, not a directional finding, and `μ_C − μ_A×` is not `θ·F̃`.

## Registered secondary comparisons (no authority) and Holm

| | pair | D0 mean / t | D1 mean / t | pass |
|---|---|---|---|---|
| S1 | A× − A | −1.640e-04 / −3.2382 | −1.612e-04 / −3.2042 | false |
| S2 | A − L | −1.422e-04 / −2.8901 | −1.412e-04 / −2.8927 | false |
| S3 | C − A | −2.035e-04 / −3.3838 | −2.017e-04 / −3.3593 | false |
| ctx | C − L | −3.458e-04 / −3.5087 | −3.430e-04 / −3.5069 | false |

Holm over the six secondary hypotheses, computed **separately per method**: all
adjusted values **1.0**, HAC and bootstrap alike. Every secondary differential
is **negative** — each added layer scored worse than the one below it on this
pool.

## Annual summaries (descriptive, declared in advance)

| year | rows | P1 t (D0) | p (D0) | P1 t (D1) | p (D1) |
|---|---|---|---|---|---|
| 2019 | 82,605 | −1.1894 | 0.8714 | −1.2096 | 0.8764 |
| 2020 | 83,018 | −0.8281 | 0.7405 | −0.8276 | 0.7403 |
| 2021 | 82,940 | +0.4004 | 0.3554 | +0.3975 | 0.3568 |

All three years reported, none selected. No year is chosen or emphasised.

## Dispersion improvement (contextual, no authority)

A× under D1 vs A× under D0 — same location, same `ν`: mean **+3.233e-04**,
t = **5.6209**, HAC pass, bootstrap p = **0.00010**, percentile interval
[1.831e-04, 4.489e-04].

Read carefully: this is the **scale specification** improving the score, with
`λ = −0.00922` — a *small negative* coefficient on clipped relative volume,
i.e. slightly **narrower** predicted scale when relative volume is high. It
carries **no selection authority**, it is not the registered question, and it
is a single contextual comparison on exposed data. It is reported because the
registration requires reporting it whatever P1 does — not as a finding.

## Telemetry, captured live from the experiment unit

Unit `run-u51975.service`, invocation `7fd6652a3f834697bea96531a62a31cc`,
cgroup `/sys/fs/cgroup/wmresearch.slice/run-u51975.service` (readable at
discovery). 707 samples, 704 with counters, over 719 s.

| | |
|---|---|
| observed max `memory.current` | 770,904,064 B (735.2 MiB) |
| last observed `memory.peak` | 778,956,800 B (742.9 MiB) |
| cap | 1,468,006,400 B (1,400 MiB) — unchanged |
| `memory.events` | `low 0, high 0, max 0, oom 0, oom_kill 0, oom_group_kill 0` |
| nothing unavailable | the watcher reported no missing measurement |

The unit's own summary line again read `Memory peak: 23.3M`, irreconcilable
with the live cgroup observation of 778,956,800 B. Excluded from evidence, as
before; no general claim is made about it.

## What this establishes

On the **exposed** 2019–2021 development pool, adding the clipped signed
body-volume feature `F̃` to a location forecast that already contains the legacy
price features, both ingredients and their product **did not improve** the
predictive density — under either registered dispersion specification, by
either inference method. The answer to the registered question is **no**, on
this pool, by this measure.

It does not establish that the feature is worthless in other constructions, at
other horizons, or with genuine order-flow data rather than OHLCV proxies; nor
does it say anything about alpha, options profitability, or tradability.
Evaluation and reserve remain closed. No confirmation was sought and none is
warranted: there is nothing to confirm.
