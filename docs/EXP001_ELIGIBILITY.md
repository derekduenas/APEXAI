# ALPHA-EXP-001 — source and feature eligibility (read-only assessment)

Assessed per source, per field, and per intended forecast cutoff. Nothing here
admits data. Admission is decided separately, through the World Model
laboratory's fail-closed source boundary, and the decision is recorded in the
registration. Existing real-data admission restrictions stand.

Vocabulary, kept apart throughout:
- **event time** — when the market fact occurred (bar close, quote, print)
- **receipt time** — when APEX possessed the payload (`acquired_at`)
- **publication time** — when the source made the fact available
- **revision time** — when the source changed a previously published value

A receipt timestamp establishes possession at receipt. It does not prove
earlier publication, and it does not prove that later revisions were absent
at that time. Historical event timestamps alone establish nothing about
point-in-time correctness.

## Sources on box

### S1 — `history-b/etf_continuous` (Alpaca historical REST, SIP feed, `adjustment=raw`)
| | |
|---|---|
| Symbols | SPY, QQQ, IWM, XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY (from 2016-01-04); XLC (2018-06-19); XLRE |
| Span | 2016-01-04 → 2026-08-28, 1-minute OHLCV, ~575 bars/session incl. extended hours |
| Integrity | chain-appended `integrity.jsonl`, `corpus_version 5c0d768b7ee2ea14`, duplicates 0, non-monotonic 0, missing sessions per symbol recorded (SPY 0, IWM 1, QQQ 1, XLB 51, XLC 676, XLRE 55, …) |
| Builder | `scripts/etf_corpus_fetch.py`: `/v2/stocks/{sym}/bars`, `timeframe=1Min`, `feed=sip`, `adjustment=raw` |
| Law on the corpus | "no economic use until PASS; every experiment cites corpus_version" |

Per field:

| Field | Event time | Receipt | Publication / revision | Classification |
|---|---|---|---|---|
| `event_time_utc` | bar start, UTC, from the vendor | fetch date (2026-08-29 GO) recorded in git history, **not per bar** | consolidated SIP bars; vendor serves history as it stands at retrieval | ELIGIBLE_WITH_EXPLICIT_LIMITATIONS |
| `open/high/low/close` | at bar | as above | SIP aggregates; late prints and corrections after bar close are folded into the bar as retrieved, invisibly | ELIGIBLE_WITH_EXPLICIT_LIMITATIONS |
| `volume` | at bar | as above | same; late-reported volume is the most revision-prone bar field | ELIGIBLE_WITH_EXPLICIT_LIMITATIONS |
| bid/ask, spread, depth | — | — | **not in the corpus** | NOT_AVAILABLE |
| trade_count | — | — | not fetched | NOT_AVAILABLE |

**Limitations that bind the experiment design.**
1. No per-bar receipt or publication time. Bars were retrieved in one bulk
   fetch in 2026-08 and represent the vendor's view *then*. A bar that was
   corrected between its event time and 2026-08 is present only in corrected
   form. For a **15-minute forward-return target on SPY**, the material
   exposure is late-print volume and small OHLC corrections; the direction of
   bias is unknown and is recorded as an unmodelled limitation, not assumed
   away.
2. `adjustment=raw`: corporate actions are explicit, not silently
   back-adjusted. SPY's dividends are cash and do not adjust price history; no
   splits in span. This is the safe convention for a causal corpus.
3. Extended-hours bars are present. The experiment restricts to regular
   session bars 13:30–20:00Z and states the cutoff as bar **close**.
4. Executable prices are not observable. Any cost assumption is an
   assumption, cited as such.

### S2 — `history-b/pit_singlename` (300 names, monthly point-in-time membership)
| | |
|---|---|
| Span | 2016-05-02 → , 259,856 session files, 300 symbols incl. delisted (e.g. AABA) |
| Membership | `membership_v1.jsonl`, 125 monthly rows, rule `top100_trailing63d_median_dollar_volume`, `decided_asof` = end of prior month, so each month's membership was decidable **before** the month it governs |
| Recorded defect | `membership_v1_defective_etf_dupe.jsonl` — an earlier version that admitted ETFs into a single-name universe; superseded, retained |
| Classification | ELIGIBLE_WITH_EXPLICIT_LIMITATIONS for a **later** cross-sectional experiment; same bar-field limitations as S1; membership causality is by construction. **Not used in EXP-001**, which is single-instrument. |

### S3 — `history-a/options_history` (ThetaData, 6 underlyings, 2018→)
| | |
|---|---|
| Manifest | 829 rows with `acquired_at` (receipt, e.g. 2026-08-23T14:40:39Z), per-file sha256, row-retention accounting (crossed quotes rejected, expiry filtered), `future_underlying_joins: 0` |
| Availability law recorded at acquisition | "per-row source timestamp IS the publication instant; never a hardcoded clock"; moneyness computed from a causal per-minute underlying reference |
| Classification | ELIGIBLE_WITH_EXPLICIT_LIMITATIONS for a **daily or longer** horizon on SPY/QQQ/IWM/AAPL/MSFT/NVDA, where option-implied distributions are a meaningful benchmark. **NOT_ESTIMABLE as a benchmark at a 15-minute horizon**: the quote history is not at the resolution or alignment that a 15-minute physical-vs-implied comparison requires, and no such comparison is claimed in EXP-001. |

### S4 — `data/historical/bars` (ThetaData pilot, 6 symbols, 85 sampled days)
BLOCKED for EXP-001. It is a stratified pilot sample (44 days in Jan–Feb
2018, then ~14 per year), so it supports conditional claims only and no
time-integrated claim. S1 supersedes it for the same symbols with continuous
coverage.

### S5 — `data/live/alpaca_fabric/bars` (own capture, 2026-08-26 → 2026-09-03)
Tier A by construction, with receipt time and coverage status. Seven sessions
is too short for any historical claim. It is the **prospective** substrate for
sealed forecasts, not a historical input.

### S6 — `historical/continuous/decisions.jsonl` + `outcomes.jsonl` (428,158 / 53,058)
The hunter's own walk-forward, produced FROM S1 under
`CONTINUOUS_ECONOMIC_WALK_FORWARD`. **BLOCKED as an input** to any forecast:
it contains resolved outcomes and would contaminate a model that saw it. Its
execution model and friction accounting are reused as the **cost model**, not
as data.

## Decision for EXP-001

Input: **S1, SPY only, regular session, 2016-01-04 → 2026-08-28, corpus
5c0d768b7ee2ea14.** Classification
ELIGIBLE_WITH_EXPLICIT_LIMITATIONS, with limitations 1–4 above carried into
the registration as declared, unmodelled risks.

This assessment does not admit S1. Admission is requested through the
laboratory's `sources.admit` boundary at run time; if that boundary refuses,
the experiment returns BLOCKED with the exact refusal, and a ready-to-run
configuration.
