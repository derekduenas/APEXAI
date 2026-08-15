# APEX PROFIT MACHINE — HISTORICAL DISCOVERY EXERCISE

Spec: `APEX-PROFIT-MACHINE-EXERCISE-SPEC.md`, frozen 589c6d92… BEFORE any
realized return flowed. DEVELOPMENT/EXPLORATION: in-sample small-cap band,
28 systematic formation dates 2005–2017, 13 mechanism-backed candidates,
stock-only, all distributions HISTORICAL_EMPIRICAL (paper grade). Nothing
here is confirmatory evidence. Ledger untouched; Credit 5 SEALED.

    FULL SYSTEM EXECUTED:      YES (swarm BLOCKED_EXTERNAL_AUTH,
                               ML NOT_ACTIVE, options STOCK_ONLY — declared)

    CANDIDATES CONSIDERED:     364 (13 x 28; +2 refused at generation:
                               unsigned direction. Denominator complete;
                               model fits: 0; horizons considered: 1)
    REFUSED:                   78   (insufficient evidence, mostly early dates)
    NO-TRADE:                  81
    WATCH:                     15
    TRADE:                     190
    EXCEPTIONAL (TIER A):      9

    REALIZED NET (TRADE):      +0.370%/20d mean (~+4.7%/yr/slot), sd 1.85%
    HIT RATE:                  55.3%
    REFUSED cohort realized:   +0.002%/20d — the gates separated edge from ZERO
    WATCH cohort realized:     +0.560%/20d (n=15 — near-bar candidates did fine)
    COST DRAG:                 30bp spread x 1.6 turnover, in every net number

    NO-TRADE VALUE ADD:        67 negative-outcome candidates refused;
                               56 good (>1%/20d) opportunities also refused —
                               the refusal layer removed NOISE (mean ~0), it
                               did not dodge disasters
    BAD TRADES PREVENTED:      67
    GOOD OPPORTUNITIES MISSED: 56

    CALIBRATION STATUS:        UNCALIBRATED magnitudes, ORDERED ranks — Tier A
                               realized +0.56%/20d (best cohort) but stated
                               expected nets of 10–39%/yr vs realized ~7%/yr:
                               the trailing-empirical estimator is overconfident
                               after rebounds, exactly as the calibration
                               scorecard predicted
    REGIME DETECTION:          participated via bar-raising only; TRADE mean
                               +0.46% in CALM_UP vs −0.07% in VOL_DOWN
                               (descriptive, NOT a conditioning rule)
    SWARM: BLOCKED_EXTERNAL_AUTH   ML: NOT_ACTIVE   OPTIONS: STOCK_ONLY

    FULL APEX VS NAIVE (raw-signal ablation, always-trade):
        FULL +0.370%/20d per selected trade vs +0.217% trading everything —
        SELECTION IMPROVED PER-TRADE NET ~70%. That is the machine's
        demonstrated value in this exercise.
    FULL VS PASSIVE/CASH:      TRADE cohort beat the universe (excess by
                               construction) and cash; magnitudes paper-grade.

    TOP HISTORICAL OPPORTUNITIES (Tier A, audited per Part 28):
        val_sales_to_price and val_earnings_yield in 2005-2012 CALM_UP
        states with 700-5,700 conditional observations. No name/year
        concentration. WHAT THE MACHINE SAW: deep-value top deciles after
        drawdowns with large trailing conditional means. WHAT HAPPENED:
        positive but far smaller than stated (+0.56%/20d cohort mean) —
        ordering right, magnitudes overconfident.
    TOP FALSE POSITIVES:       cap_net_buyback_yield (-0.24%) and
                               val_book_to_market (-0.94% on 11 trades) —
                               value-alone AGAIN fails monetization, the
                               third independent confirmation. No layer
                               caught these: the trailing-empirical estimator
                               endorsed them. THE calibration gap, named.
    TOP MISSED:                56 refused candidates >1%/20d — mostly early
                               dates refused on <100 observations (the
                               evidence gate being conservative, correctly).

    ORNAMENTAL (at this scale): risk engine, portfolio-context, cost gate —
        ablations F/H/J ~identical to FULL because 3% weights and 30bp costs
        never bind at $15k notionals. They exist for the scale where they DO.
    VALUABLE: the evidence gate + edge bar (the whole selection uplift),
        the tiering (ordered), the denominator/memory (364 decisions chained).
    BOTTLENECK: distribution CALIBRATION — every wrong magnitude traces to
        the uncalibrated trailing-empirical estimator; second: intraday/event
        data absence for anything faster than 20 days.

    DOES THE MACHINE ADD ECONOMIC VALUE?   YES — modestly, at paper grade,
        via SELECTION (+70% per-trade net over trading everything), with
        honest refusal of a zero-edge cohort and correctly ORDERED tiers.
        Not yet established: magnitude trustworthiness, out-of-sample.

    DOES ANY CURRENT OPPORTUNITY DESERVE CREDIT 5?   NO.
        Nothing meets Part 35: every distribution is HISTORICAL_EMPIRICAL,
        every decision in-sample, calibration unproven forward. The
        machine's own stamps say so on every row.

## Part 36 answers

1. MVPM complete? Functionally YES for paper grade (this run IS the
   real-data end-to-end artifact); the registry keeps discovery_exercise_
   runner pending promotion until this run's script is registered as the
   component. 2. "What should I trade today?" — the machine can now answer
   with stamped, paper-grade output (and would say its confidence out loud).
   3. FULL vs naive: yes, +70% per-trade net via selection. 4. Valuable:
   evidence gates, edge bar, tiering, memory. 5. Ornamental at this scale:
   risk/portfolio/cost gates (they bind at real scale). 6. Highest-value
   missing data: intraday bars + timestamped events (the Hunter gap), then
   options chains. 7. Highest-value missing architecture: forward
   calibration of the estimator (CLI login starts that clock). 8. Highest-
   leverage next build: Hunter P1 replay once intraday data exists; until
   then, let the paper track + reality loop accrue against frozen criteria.
   9. Credit 5: NO — and the refusal is printed by the machine itself.
