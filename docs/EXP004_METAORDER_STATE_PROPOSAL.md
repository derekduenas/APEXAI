# EXP-004 proposal — execution-pressure regime state

**Design only.** Nothing implemented, fitted, scored, registered or admitted. No
sealed-data opening is proposed or implied. One preferred design, as requested.

The previous three experiments all asked what a function of `ret_1` and `ret_5`
can predict. This proposes a genuinely different input: not *how much* price
moved, but *how the move was produced* — with what participation, and with what
intra-bar signature. Two paths with identical `ret_5` are distinguished.

## 1. Mechanism hypothesis

A participant executing a **metaorder** — a parent order worked over minutes
because it is too large to complete at once — leaves two joint traces in bar
data:

1. **Elevated participation** relative to what that minute of the session normally carries; and
2. **Persistently one-sided intra-bar closes**, because the same side repeatedly crosses the spread.

Execution of that kind creates **temporary price impact**: part of the move is
the participant paying for immediacy, not information. When the parent order
completes or pauses, that temporary component partially reverts. This is the
standard temporary/permanent impact decomposition, and it is a *causal*
statement about a market participant's forced or size-constrained behaviour,
not a pattern observed in the price path.

**The prediction is conditional and directional:** when the joint signature is
present, the next 15 minutes should move **against** the signature's direction,
with the effect increasing in the signature's strength; when it is absent,
nothing. This is what makes it a regime state rather than another predictor —
it claims the sign of the return relationship *changes with the state*.

**How it could be wrong** (stated now): the same signature is also produced by
genuinely informed trading, which produces *permanent* impact and hence
continuation, not reversion. SPY is the most liquid US equity instrument, so
metaorders are small relative to available liquidity and temporary impact may
be too small to detect at 15 minutes. Both would show as no effect or a
sign-flipped effect, and either is a real answer.

## 2. The state variable, defined precisely

All inputs come from fields **already admitted** in the existing dataset —
`open`, `high`, `low`, `close`, `volume`, `event_time_utc` for SPY 1-minute bars.
No new data source, no new vendor, no new field is required.

Per bar `t`:

    CLV_t   = (close_t − open_t) / (high_t − low_t)      if high_t > low_t, else 0     ∈ [−1, 1]
    RVOL_t  = volume_t / V̄(minute_of_day(t))

`V̄(·)` is the per-minute-of-session median volume, estimated on the **fit split
only** and carried forward unchanged. Over a trailing window `W = 10` complete
bars, ending at the same bar as the existing features and respecting the same
availability clock:

    flow_W(t)     = Σ CLV_i · volume_i / Σ volume_i              (volume-weighted mean close location)
    pressure_W(t) = Σ volume_i / Σ V̄(minute_of_day(i))           (relative participation)
    S_t           = pressure_W(t) · |flow_W(t)|                   (signature strength, ≥ 0)
    d_t           = sign(flow_W(t))                               (signature direction)

`S_t` is high only when **both** conditions hold — unusual participation *and*
directional persistence — which is the point: either alone is common and
uninformative about metaorder execution.

## 3. Comparator and the term under test

**Strongest relevant comparator: the L arm** — the registered linear conditional
mean in `ret_1`, `ret_5` at the registered Student-t scale law. On EXP-002's
development period the t-family arms dominated the registered Gaussian arms
(L−M1 `t = 6.70`), and the quadratic extension did **not** improve on L
(C−L `t = −2.312`, negative). L is therefore the strongest thing we have, and
the honest comparator.

The challenger adds **one** term to L's mean:

    μ_A1(x) = μ_L(x) + θ · (−d_t · g(S_t))

with `g` a fixed, declared, monotone squashing of `S_t` (registration to fix its
form and any constant, estimated on the fit split only). The minus sign encodes
the reversion hypothesis: the term is *signed against* the execution direction,
so a positive fitted `θ` supports the mechanism and a negative `θ` contradicts
it. Scale and tail law stay exactly as registered.

**Note on the previous mistake.** This is a genuinely new input — `S_t` and
`d_t` are not functions of `ret_1`, `ret_5` — so the FWL equivalence that
defeated EXP-003 does not apply here. I would nevertheless verify that
explicitly before registration, using the same deterministic check.

## 4. Ablation ladder

Each arm removes exactly one ingredient of the mechanism, so a positive result
has to say *which* ingredient carried it. All ablations are fitted on the fit
split under the same budget.

| Arm | Mean | What its failure/success distinguishes |
|---|---|---|
| A0 = L | registered linear | comparator |
| A1 | L + reversion term above | the full mechanism |
| A2 | L + participation only (`pressure_W`, no `CLV`) | is it just unusual volume? |
| A3 | L + direction only (`flow_W`, no volume weighting) | is it just intra-bar close location? |
| A4 | L + `S_t` with `d_t` replaced by a fixed session-level sign assignment declared in advance | does **direction** matter, or only magnitude (a volatility effect in disguise)? |

The mechanism predicts A1 beats A2, A3 and A4. If A2 or A3 matches A1, the
metaorder story is not what is doing the work and should not be claimed.

**A4 is an ablation of a model input, not a control with invalidation
authority.** Given the N0 closure, no randomisation in this design is given
authority to invalidate anything.

## 5. Controls, with authority stated

- **Integrity controls with invalidation authority** — source/code identity, sealed-period exclusion, fit-budget spies, numerical validity. Each is a direct measurement of the artifact, each null stated in the registration, none is a statistical test.
- **Implementation checks on synthetic data** — known-truth recovery (plant a temporary-impact process, verify detection), leakage checks on the availability clock for `V̄` and the window, and forecast-hash reconstruction. These verify the code. Per the correction now on record, they do **not** come with a promise that a later-discovered defect cannot invalidate an artifact already produced.
- **No permutation control with invalidation authority**, for the reasons established in `EXP002_N0_CLOSURE.md`. If review wants one, its invariance argument must be supplied and reviewed first.

## 6. Exposure-aware evaluation plan

2019 **and** 2020–2021 are both exposed, and the evaluation set carries the
disclosed 60-byte metadata read of `SPY_2022-01-03.json`
(`EVALUATION_READ_INCIDENT_001`). Consequences taken up front:

- **Development pool: 2019 + 2020–2021, both declared exposed.** Any result here is a screen, not a finding, and every report must say so. There is no clean out-of-sample period left below 2022.
- **Confirmation: none is proposed in this brick.** Opening any sealed block requires a separate, independently reviewed, explicitly authorised admission — never a threshold crossed in development. If development is unpromising, no such request is made at all.
- The exposure ledger is carried forward and extended by whatever this experiment reads; nothing is described as untouched.

## 7. Budget

| Item | Count |
|---|---|
| Fit-split estimations | `V̄` minute-of-day baselines (1), the `g` constant (1), and 5 arm fits A0–A4 |
| Refits | 0 |
| Development evaluations | 1, over the declared exposed pool |
| Gates with authority | 1: A1 vs A0, both registered inferences must agree |
| Reported without authority | A2, A3, A4 vs A0, Holm-adjusted |
| Sealed openings | **0** |
| Economics | none |

## 8. Limitations, declared now

- The scale and tail law are **assumed**, not tested; if execution pressure also changes the conditional scale — which is likely — a mean-only test at a fixed scale law is misspecified in an unknown direction. This is the most serious weakness and is a candidate first thing to fix.
- `CLV` and minute-of-day relative volume are **crude proxies** for order flow. Real flow inference needs trade-and-quote data, which is not in the admitted dataset. A null result may reflect proxy weakness rather than absent mechanism, and cannot be reported as refuting temporary impact.
- SPY is extremely liquid: the effect may be real and too small to detect at this horizon with these proxies.
- No clean out-of-sample period remains below 2022; the development pool is exposed.
- 15 minutes is inherited from the registered horizon; metaorder completion times are not aligned to it.
- No economic claim of any kind. A density improvement is not an edge.

## 9. What I am asking for

Review of the mechanism and design only. If accepted in principle, the next
bricks would be: a written registration freezing these definitions; the
equivalence and leakage checks; the synthetic implementation checks; then a
separately reviewed request for historical admission covering the development
pool only. No fitting, no historical access, and no sealed data until each of
those is reviewed on its own.
