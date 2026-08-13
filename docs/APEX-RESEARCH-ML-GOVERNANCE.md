# APEX ML Governance — required before the first `.fit()`

**Status:** governance text. No ML code exists; none may be written until this
is ratified and its interface obeys `apex.governance.firewalls` contract `ml`.

The single sentence this document exists to enforce:

> **A machine-learned signal is a hypothesis. It consumes a credit. It obeys
> every rule a single-factor hypothesis obeys, plus stricter leakage controls.
> An unconstrained model IS a hyperparameter search, and the credit system
> exists to price search.**

## The twelve specifications (firewall contract `ml`)

| | |
|---|---|
| **1. Purpose** | Discover nonlinear / interaction relationships among registry features that a linear cross-sectional rank cannot express. |
| **2. Inputs** | Registry features (in-sample only), the Digital Twin state, a registered ML dossier declaring model family, feature set, and CV scheme. |
| **3. Outputs** | Out-of-fold predictions and a fitted model artifact — both *inside* a registered experiment. Never a "best model" chosen after seeing validation. |
| **4. Allowed dependencies** | `apex.features`, `apex.research.twin`, `apex.evaluate` (for its own in-sample scoring). |
| **5. Forbidden dependencies** | `apex.governance.screening`, `apex.research.{swarm,novelty,hypothesis,gate}`, and — until registered — the validation/holdout data. Enforced by firewall contract `ml.forbidden`. |
| **6. Governance boundary** | A model is a **new hypothesis**. It cannot be trained on, selected by, or tuned against validation or holdout results. |
| **7. Provenance** | Every run records: dataset fingerprint, protocol hash, config hash, feature signature, model family + version, hyperparameter grid, CV scheme, seed, repo SHA. |
| **8. What is a new hypothesis** | Any materially different model family, feature set, target, or CV design. Changing any after seeing a result is a new dossier (Part 9 iteration rule). |
| **9. What consumes a credit** | Registering an ML experiment for validation. In-sample nested CV is free; the validation look is the credit. |
| **10. What can never access the holdout** | The model, its CV, its feature selection, its hyperparameter search — all in-sample only. The holdout is the one post-validation look, gated by registration. |
| **11. What can never optimize** | Nothing may optimize *against validation or holdout*. In-sample nested walk-forward CV may select hyperparameters, and that search is itself logged. |
| **12. Tests before activation** | leakage auditors (temporal + cross-sectional, reusing `lookahead.py`/`cross_sectional.py`); a model-family counter test; a "no validation data in training fold" test; a reproducibility (same seed → same OOF) test. All must exist and pass before the first `.fit()`. |

## The controls in detail

**Temporal boundary.** Train only on in-sample. Validation and holdout are as
locked for a model as for a factor. Enforced by the firewall (`ml` cannot reach
the locked periods before registration) and by a purged/embargoed walk-forward
CV that never lets a fold train on data after its test window.

**Nested walk-forward inside in-sample.** All hyperparameter and model selection
happens in an inner CV loop that never touches the outer validation period.
Purge and embargo around each fold boundary remove the autocorrelation-driven
leakage that overlapping 20-day forward windows create (the same MA(19)
structure the HAC null already accounts for).

**Model selection IS multiple testing.** Every model family and materially
different specification tried is recorded, exactly as screen rejections are
(file-drawer rule). The **model-search denominator is always visible.** A run
that tries 50 models and keeps the winner must show all 50, or it is a hidden
search and is refused.

**A fixed pre-registered spec per credit.** The registered dossier names the
model class, feature set, target, and CV scheme *before* validation. The first
`.fit()` is impossible unless the experiment carries an explicit ML governance
declaration naming these.

**Leakage detection is mandatory.** Cross-sectional leakage (a feature peeking
across names on the same date) and temporal leakage (a feature knowable only
later) both get auditors before any model runs.

**Interpretability is a gate, not a nicety.** Permutation importance and, only
where the model class supports it honestly, SHAP-style attribution. An
uninterpretable model that validates is a *result*, but the human gate must
record why its nonlinearity is economically defensible, or it is contamination
waiting to be deployed.

## What must NOT be built with this document

No `sklearn`/`xgboost`/`lightgbm`/`torch` import may enter the research path
until the interface above exists and `tests/test_architecture_firewalls.py`
enforces contract `ml`. `tests/test_architecture_claims.py` currently asserts
these libraries are absent; that test flips to enforcing the boundary the day
the `ml` package appears.
