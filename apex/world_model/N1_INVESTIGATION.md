# N1 CONTROL_FAILURE — investigation (WM-0E)

Status: **finding, not repair.** The decision rule is NOT modified in
this brick. Per the WM-0E directive: "Do not modify the rule in
response. If observed behavior is materially inconsistent: FAIL the
court and investigate."

## What the court observed (COURT-a4c366b64b0d, controls V0, 25 seeds)

| control | detections / 25 | expected (α=0.023) | tolerated | verdict |
|---|---|---|---|---|
| N0 block-deranged targets | 1 | 0.58 | 3 | PASS |
| **N1 forward time displacement (200)** | **6** | 0.58 | 3 | **CONTROL_FAILURE** |
| N2 noise features | 0 | 0.58 | 3 | PASS |
| N3 row-permuted features | 3 | 0.58 | 3 | PASS (at the limit) |
| N4 random ranker | 0 | 0.58 | 3 | PASS |
| P0 positive control | 24 | ≥20 | — | PASS |

N1 z-scores across the 25 seeds ranged from −17.92 to +7.99. Under a
correctly calibrated rule the null z should behave like N(0,1); a
spread of ±18 is not a sampling accident, it is a variance
miscalibration. Note that the *negative* extremes are the same
symptom as the false positives — an inflated z is inflated in both
directions.

## Mechanism (measured, not hypothesised)

The rule is `SIGNAL_DETECTED iff mean(d) > 0 and mean(d)/stderr(d) > 2.0`
with `d_i = logL_M0(y_i) − logL_null(y_i)` per evaluation sample and
`stderr` computed **as if the d_i were independent**.

The target is a 15-step forward log-return. Consecutive targets share
14 of their 15 price increments. Wherever the temporal structure of
both X and y survives the control transformation, consecutive d_i are
therefore strongly dependent and the iid stderr is far too small.

Measured lag-k autocorrelation of d_i and Bartlett effective sample
size (`n_eff = n / (1 + 2 Σ_k ρ_k⁺)`, k ≤ 30) on actual court cells:

| cell | z (iid rule) | ρ₁ | ρ₅ | ρ₁₄ | n_eff / n | z (dependence-adjusted) |
|---|---|---|---|---|---|---|
| N1 seed 1111 (false positive) | +4.71 | 0.757 | 0.587 | 0.203 | 0.062 | +1.17 |
| N1 seed 1444 (false positive) | +2.49 | 0.802 | 0.651 | 0.234 | 0.060 | +0.61 |
| N1 seed 1000 | +0.51 | 0.921 | 0.664 | 0.092 | 0.066 | +0.13 |
| N2 seed 1000 | +0.09 | 0.056 | 0.000 | 0.005 | 0.444 | +0.06 |
| N3 seed 1000 | −0.59 | 0.024 | −0.016 | −0.031 | 0.529 | −0.43 |
| N0 seed 1000 | −1.14 | 0.526 | 0.308 | 0.134 | 0.086 | −0.33 |

`n_eff/n ≈ 0.06 ≈ 1/16` on N1 — the overlapping-horizon signature
(H=15). The iid stderr is ~4× too small; the z threshold of 2.0 is
effectively ~0.5 in true units, so the realised per-test α on a
temporally-structured null is on the order of 0.3, not 0.023. 6/25
(0.24) is consistent with that.

Why the other controls did not expose it:

- **N2, N3** destroy the temporal structure of X (iid noise / row
  shuffle). M0 fits ≈0 coefficients, so d_i ≈ small white noise
  (ρ₁ ≈ 0.02–0.06). The stderr is approximately right *because there
  is nothing autocorrelated left* — not because the rule is right.
- **N4** always loses to the null by construction; z ≪ 0 regardless.
- **N0** breaks pairing but keeps each 20-step block's internal
  autocorrelation (ρ₁ = 0.53), so it is partially exposed (1 FP).
- **N1** is the only control where **both** sides keep their full
  path dependence while carrying zero information about each other.
  That is the cleanest possible test of within-world calibration, and
  it is exactly the case a real, autocorrelated market null presents.

The adjusted column is shown to demonstrate the mechanism. It is not a
new rule, it has not been tuned, and it is not used anywhere.

## Why WM-0D did not catch this

WM-0D ran the S0 null on a single seed and observed z = −1.03 (and
+0.14 on an earlier configuration). Both are inside the acceptance
region of a rule whose null distribution is actually ~N(0, 4²). One
seed cannot distinguish a calibrated rule from a miscalibrated one
that happened to land near zero. This is precisely the "one seed
looks fine" failure the court was built to prevent, and it prevented
it.

## Consequences

1. `NULL_COURT_V0` verdict: **FAIL** (N1 CONTROL_FAILURE). The
   laboratory's per-test decision rule is not calibrated for
   overlapping-horizon targets. Until it is, any "SIGNAL_DETECTED"
   from this rule on a temporally-structured subject — including P0's
   z ≈ +10.8 median — carries an inflated z and must be read as such.
2. P0 still detects after adjustment (median z ≈ +2.7 under n_eff/n
   ≈ 0.06), so the *positive* control's PASS is not solely an
   artefact — but the court cannot certify that under the current
   rule and does not.
3. The rule fix (block/Newey-West stderr, or non-overlapping
   evaluation, or a permutation-null for z) belongs to a NEW brick
   under a NEW court identity. It is not made here. The rule's hash is
   unchanged.
4. This finding is recorded on RESEARCH_BOARD_V2 as the outcome of
   WM-0E and is immutable.

## Secondary defect found in this brick (N0 implementation)

My own test caught that the first N0 implementation padded a short
trailing block by cycling values from its source block, which
duplicated values and so did not preserve y's multiset. Fixed in
`WM0E_CONTROLS_V0.1`: full blocks only; the ≤19-sample partial block
is truncated consistently across X, y, indices and outcome records.
Because a control's implementation changed after a court had run,
COURT-a4c366b64b0d is preserved exactly as it ran (controls V0) and a
second court is convened under a distinct identity that commits to the
controls version. No rule, seed, tolerance or M0 parameter changed.
