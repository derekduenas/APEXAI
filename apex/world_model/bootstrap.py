"""DEPENDENT_BLOCK_BOOTSTRAP_V0 -- the primary inference engine for
NULL_COURT_V2_BLOCK_BOOTSTRAP.

WHY NOT R1
R1 (DEPENDENCE_AWARE_DM_HAC_V0) studentised the loss differential with a
Bartlett HAC variance at L = H-1 and compared to N(0,1). Measured before
any acceptance seed: one-sided rejection 0.063 on the exact MA(14)
overlap null (Bartlett at the MA order recovers 67% of the long-run
variance) and 0.096 on AR(1) phi=0.9, i.e. dependence beyond the
deterministic overlap is real. R1 was stopped at §10 and is preserved
as a DIAGNOSTIC. It is not the court.

WHAT THIS DOES
  H0: the informative model has no positive expected out-of-sample loss
      advantage over the null comparator.
  H1: it has a positive expected loss advantage.

  d_t = loss_null_t - loss_M0_t = logL_M0(y_t) - logL_null(y_t)
        (Gaussian log-likelihood loss = -logL). POSITIVE mean(d) means M0
        improves on the null. This is the WM-0D/R1 orientation; it is
        asserted by a test and never reversed.

  Observed statistic: t_obs = mean(d) / sqrt(LRV_HAC(d) / n), the SAME
  studentiser as R1 (Bartlett, L = H-1). Its null distribution is NOT
  assumed normal. It is obtained by a CIRCULAR MOVING-BLOCK BOOTSTRAP-t:
    1. centre under H0: c_t = d_t - mean(d)
    2. draw ceil(n/l) block starts uniformly on [0, n); blocks of length l
       wrap circularly; concatenate; truncate to n  -> c*
    3. t* = mean(c*) / sqrt(LRV_HAC(c*) / n)  (same studentiser)
    4. p = (1 + #{t*_b >= t_obs}) / (B + 1)   one-sided, +1 correction
  SIGNAL_DETECTED iff mean(d) > 0 and p <= ALPHA.
  Studentising inside the bootstrap makes the test bootstrap-t: the HAC
  estimator's finite-sample bias appears identically in t_obs and t*,
  and cancels to first order. Blocks preserve dependence up to l; the
  block-length law below is what makes l respond to dependence beyond
  the deterministic overlap.

BLOCK-LENGTH LAW (predeclared; may read d's dependence structure, may
NOT read whether M0 beats the null)
  l = clamp( round(b_PPW), lower = H, upper = floor(n / MIN_BLOCKS) )
  b_PPW = Politis-White (2004) automatic block length with the Patton-
  Politis-White (2009) correction, circular-bootstrap variant, computed
  on the CENTRED differential (so it is invariant to the sign and size
  of mean(d)). Rationale, written before execution:
    * lower bound H: the deterministic overlap of H-step targets is a
      known minimum dependence scale; no selector may go below it.
    * PPW: a recognised automatic selector that grows with the
      estimated long-run dependence, so dependence beyond H-1 (latent
      state, path structure) lengthens the blocks without anyone
      choosing a number.
    * upper bound n/MIN_BLOCKS: a bootstrap that resamples fewer than
      MIN_BLOCKS = 6 distinct blocks has too little to resample.
  The selector's inputs and outputs are persisted for every cell.

REPLICATIONS: B = 1999, fixed. RNG: numpy PCG64 seeded from
sha256(BOOT_NAMESPACE | court_id | control | seed). No re-draw.

ALPHA = 0.025 one-sided, fixed: the closest coherent equivalent of the
retained z ~ 2 rule (1 - Phi(2) = 0.02275) at the resolution a finite
bootstrap can express. Not tuned from any development result.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

from apex.world_model.canonical import content_hash
from apex.world_model.inference import (HAC_KERNEL, HAC_LAG,
                                        paired_differentials)
from apex.world_model.targets import TARGET_HORIZON, TARGET_HORIZON_STEPS

BOOTSTRAP_VERSION = "DEPENDENT_BLOCK_BOOTSTRAP_V0.1"
IMPLEMENTATION_HISTORY = {
    "V0": "declared method; the executable could not run the declared "
          "Politis-White selector on long-memory input: autocovariances were "
          "computed only through lag m_max + K_N while the flat-top window "
          "legally reads lags up to M = 2*m_hat <= 2*m_max (WM-IMPL-001; "
          "IndexError on the first dependent calibration fixture, "
          "2026-09-04T20:12Z). No number was produced.",
    "V0.1": "SAME declared statistical method; autocovariance support "
            "extended to cover every lag the declared formula may access "
            "(max(2*m_max, m_max + K_N)). No semantic change; no clamping "
            "added. IMPLEMENTATION_REPAIR, not a methodology revision."}
BOOT_NAMESPACE = "WM0E_R2_BOOT_V0"
B_REPLICATIONS = 1999
ALPHA = 0.025
MIN_BLOCKS = 6
BLOCK_LOWER = TARGET_HORIZON_STEPS                # >= H, by law
BLOCK_RULE = ("l = clamp(round(b_PPW), H, floor(n/%d)); b_PPW = Politis-White "
              "2004 / Patton-Politis-White 2009 automatic block length, "
              "circular variant, on the centred differential" % MIN_BLOCKS)
STATISTIC_ORIENTATION = ("d_t = loss_null_t - loss_M0_t = logL_M0 - logL_null; "
                         "positive mean(d) = M0 improves on the null")
DECISION_CONVENTION = ("p = (1 + #{t* >= t_obs}) / (B + 1); SIGNAL_DETECTED "
                       "iff mean(d) > 0 and p <= ALPHA")
BOOTSTRAP_KIND = "circular moving-block bootstrap-t, centred under H0"

# ---- calibration envelope (§7), DEFINED BEFORE ANY SIMULATION ----------
CALIBRATION_ENVELOPE = {
    "alpha": ALPHA,
    "null_fixture_type1_max": 0.050,     # ~2x nominal; Wilson half-width ~0.015 at R=400
    "null_fixture_type1_min": 0.005,     # a test that never rejects is broken too
    "pooled_dependent_null_type1_max": 0.040,
    "power_fixture_min": 0.80,
    "replications_per_fixture": 400,
    "rule": "STOP if ANY null fixture exceeds type1_max or falls below "
            "type1_min, or the pooled dependent-null rate exceeds "
            "pooled max, or power is below min. No block-rule or alpha "
            "change; a failure is sealed."}


class BootstrapViolation(ValueError):
    pass


def _weights(lag: int) -> np.ndarray:
    return np.array([1.0 - k / (lag + 1.0) for k in range(1, lag + 1)])


def hac_t_rows(X: np.ndarray, lag: int = HAC_LAG) -> np.ndarray:
    """t = mean / sqrt(LRV/n) for every row of X, Bartlett HAC at `lag`,
    autocovariances about each row's own mean (1/n convention)."""
    X = np.asarray(X, dtype=float)
    n = X.shape[1]
    m = X.mean(axis=1, keepdims=True)
    C = X - m
    g0 = (C * C).sum(axis=1) / n
    lrv = g0.copy()
    w = _weights(lag)
    for k in range(1, lag + 1):
        gk = (C[:, k:] * C[:, :n - k]).sum(axis=1) / n
        lrv += 2.0 * w[k - 1] * gk
    if np.any(lrv <= 0):
        raise BootstrapViolation("non-positive long-run variance in a row")
    return m[:, 0] / np.sqrt(lrv / n)


def selector_constants(n: int) -> dict:
    K_N = max(5, int(math.ceil(math.sqrt(math.log10(n)))))
    m_max = int(math.ceil(math.sqrt(n))) + K_N
    return {"K_N": K_N, "m_max": m_max,
            "v0_buffer_lags": m_max + K_N,            # what V0 computed
            "required_lags": max(2 * m_max, m_max + K_N)}


def required_autocov_lags(n: int) -> int:
    """Highest lag the DECLARED selector may legally read for series
    length n. V0.1 computes autocovariances through exactly this lag."""
    return selector_constants(n)["required_lags"]


def _flat_top(t: np.ndarray) -> np.ndarray:
    a = np.abs(t)
    return np.where(a <= 0.5, 1.0, np.where(a <= 1.0, 2.0 * (1.0 - a), 0.0))


def politis_white_block_length(d, *, circular: bool = True) -> dict:
    """Automatic block length (Politis & White 2004; Patton, Politis &
    White 2009 correction). Uses only the autocovariance structure of the
    CENTRED series; blind to the sign of the mean."""
    x = np.asarray(d, dtype=float)
    n = len(x)
    c = x - x.mean()
    K_N = max(5, int(math.ceil(math.sqrt(math.log10(n)))))
    m_max = int(math.ceil(math.sqrt(n))) + K_N
    band = 2.0 * math.sqrt(math.log10(n) / n)
    # WM-IMPL-001 (V0.1): support must cover BOTH the significance scan
    # (lags <= m_max + K_N) and the flat-top window (lags <= 2*m_hat, and
    # m_hat <= m_max). V0 stopped at m_max + K_N and raised IndexError.
    max_lag = required_autocov_lags(n)
    R = np.array([(c[k:] * c[:n - k]).sum() / n for k in range(max_lag + 1)])
    rho = R / R[0] if R[0] > 0 else np.zeros_like(R)
    m_hat = None
    for m in range(0, m_max + 1):
        if np.all(np.abs(rho[m + 1:m + K_N + 1]) < band):
            m_hat = m
            break
    if m_hat is None:
        m_hat = m_max
    M = max(1, 2 * m_hat)
    ks = np.arange(-M, M + 1)
    lam = _flat_top(ks / M)
    Rk = R[np.abs(ks)]
    G = float((lam * np.abs(ks) * Rk).sum())
    S = float((lam * Rk).sum())
    D = (4.0 / 3.0) * S * S if circular else 2.0 * S * S
    b = ((2.0 * G * G / D) ** (1.0 / 3.0)) * (n ** (1.0 / 3.0)) if D > 0 else 0.0
    return {"selector": "POLITIS_WHITE_2004_PPW_2009",
            "variant": "circular" if circular else "stationary",
            "n": n, "K_N": K_N, "m_max": m_max, "band": band,
            "autocov_lags_available": int(len(R) - 1),
            "max_lag_read": int(max(M, m_hat + K_N)),
            "m_hat": int(m_hat), "M": int(M), "G_hat": G, "D_hat": D,
            "b_opt": float(b)}


def block_length(d) -> dict:
    """THE LAW. Returns the chosen l and everything behind it."""
    n = len(d)
    upper = n // MIN_BLOCKS
    if upper < BLOCK_LOWER:
        raise BootstrapViolation(
            "n=%d cannot hold %d blocks of >= %d" % (n, MIN_BLOCKS, BLOCK_LOWER))
    pw = politis_white_block_length(d)
    proposed = int(round(pw["b_opt"]))
    chosen = min(max(BLOCK_LOWER, proposed), upper)
    return {"rule": BLOCK_RULE, "lower": BLOCK_LOWER, "upper": upper,
            "selector_output": pw, "proposed": proposed, "block_length": chosen,
            "clamped": "lower" if proposed < BLOCK_LOWER else
                       ("upper" if proposed > upper else "none")}


def _rng(court_id: str, control: str, seed: int) -> np.random.Generator:
    h = hashlib.sha256(("%s|%s|%s|%d" % (BOOT_NAMESPACE, court_id, control,
                                          seed)).encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "big"))


def circular_block_indices(n: int, l: int, B: int, rng) -> np.ndarray:
    k = -(-n // l)                                    # ceil(n / l)
    starts = rng.integers(0, n, size=(B, k))
    offs = np.arange(l)
    idx = (starts[:, :, None] + offs[None, None, :]).reshape(B, k * l) % n
    return idx[:, :n]


def bootstrap_test(d, *, court_id: str, control: str, seed: int,
                   B: int = B_REPLICATIONS, alpha: float = ALPHA) -> dict:
    """The primary test on one differential sequence."""
    if B != B_REPLICATIONS or alpha != ALPHA:
        raise BootstrapViolation("B and alpha are fixed (%d, %.3f)"
                                 % (B_REPLICATIONS, ALPHA))
    x = np.asarray(d, dtype=float)
    n = len(x)
    if n < MIN_BLOCKS * BLOCK_LOWER:
        raise BootstrapViolation("n=%d too small" % n)
    bl = block_length(x)
    l = bl["block_length"]
    t_obs = float(hac_t_rows(x[None, :])[0])
    c = x - x.mean()                                  # centred under H0
    rng = _rng(court_id, control, seed)
    idx = circular_block_indices(n, l, B, rng)
    t_star = hac_t_rows(c[idx])
    ge = int((t_star >= t_obs).sum())
    p = (1.0 + ge) / (B + 1.0)
    mean = float(x.mean())
    verdict = "SIGNAL_DETECTED" if (mean > 0 and p <= alpha) else "NO_SIGNAL"
    return {"rule": BOOTSTRAP_VERSION, "kind": BOOTSTRAP_KIND,
            "n": n, "mean_loglik_gain": mean, "t_obs": t_obs,
            "block": bl, "B": B, "alpha": alpha, "p_bootstrap": p,
            "n_ge": ge, "t_star_q": {"q50": float(np.quantile(t_star, 0.5)),
                                     "q975": float(np.quantile(t_star, 0.975)),
                                     "q99": float(np.quantile(t_star, 0.99))},
            "rng": "PCG64(sha256(%s|court_id|control|seed)[:8])" % BOOT_NAMESPACE,
            "verdict": verdict}


def bootstrap_rule(model_grades, null_grades, **kw) -> dict:
    return bootstrap_test(paired_differentials(model_grades, null_grades), **kw)


def bootstrap_contract() -> dict:
    return {"bootstrap_version": BOOTSTRAP_VERSION, "kind": BOOTSTRAP_KIND,
            "implementation_history": IMPLEMENTATION_HISTORY,
            "hypotheses": {"H0": "no positive expected OOS loss advantage of "
                                 "M0 over the null", "H1": "positive advantage"},
            "orientation": STATISTIC_ORIENTATION,
            "studentiser": "Bartlett HAC, L = %d (= H-1), 1/n autocovariances"
                           % HAC_LAG,
            "hac_kernel": HAC_KERNEL, "hac_lag": HAC_LAG,
            "horizon": TARGET_HORIZON, "horizon_steps": TARGET_HORIZON_STEPS,
            "block_length_rule": BLOCK_RULE, "block_lower": BLOCK_LOWER,
            "min_blocks": MIN_BLOCKS,
            "selector": "POLITIS_WHITE_2004_PPW_2009 (circular)",
            "B": B_REPLICATIONS, "alpha_one_sided": ALPHA,
            "decision": DECISION_CONVENTION,
            "rng_namespace": BOOT_NAMESPACE,
            "calibration_envelope": CALIBRATION_ENVELOPE,
            "numpy": np.__version__,
            "implementation_sha256":
                hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def content_identity() -> str:
    return content_hash(bootstrap_contract())
