# Full model-path verification

Base: `354eda01b52d7b3812f51fb741999001b90996df` (premarket handoff candidate).
Synthetic execution only. No historical market data, provider calls, deployment,
fee authorization or operational activation.

## What actually ran

The premarket fixture first runs the real staged CLI in five separate processes.
Its sealed packet is consumed by the configured Twin reader and persisted as
prior context. The 09:35 ET decision then runs the real FULL_FUNNEL lifecycle.
Audit wrappers call the original methods and return their outputs unchanged.

| Layer | Observed evidence and independently checked property |
|---|---|
| Premarket | Production-built synthetic packet attached to the forecast; shadow authority retained |
| Twin | ret_1, ret_5, ret_15 and rv_30 checked against the synthetic closing-price sequence |
| Location forecast | Real frozen artifact called; returned location / 15 reaches simulated drift unchanged |
| GARCH-t | Successful actual fit on 2,000 causal returns; no EWMA substitution in this flight |
| Regime | Real filtered probabilities and fitted state variances reach the simulation mixture |
| Variance forecast | Next-bar and integrated 15-bar variance independently recomputed from fitted parameters and actual prefix |
| Market-implied | Actual implied-vol inversion outputs reach the simulator's IV state |
| Multiverse | 2,000 paths x 15 future steps; actual price, variance, IV and spread arrays fingerprinted |
| Simulation math | GARCH recurrence reconstructed from simulated price shocks; mean and variance recomputed from terminal prices |
| Expression comparison | Identical array fingerprints at simulation output and pricing input; candidate net values independently repriced under the same declared BSM assumptions |
| Sensitivity | Main truncation cap 8 plus caps 6 and 12: three actual simulation/comparison calls |
| PRIME | Real supervision receives the regime, selected candidate and simulated variance; returns ACT |
| Risk / entry / exit / Book | Actual court boundary and authority path; persisted single-trade accounting independently reconstructs, no open position |

The synthetic realized net is $19.91. The exit quote is a fixture, so this is
accounting evidence and never an expectancy or profitability observation.

The existing deterministic training recipe is standardized Student-t(6), seed 3,
sigma 0.00025. There was no seed search, model-output stub, lowered fit threshold,
or relaxed selection policy to obtain GARCH. The previously tested EWMA fallback
remains available and is not renamed GARCH. This flight uses symmetric GARCH-t;
it does not claim the GJR variant ran in this decision.

## Failure behavior and the defect found

Two deliberately separate failure flights prove downstream stops:

* Insufficient training history: WAIT, no GARCH fitting or simulation, no fill.
* Injected simulator refusal: WAIT, pricing never called, no intent or fill.

The broader model suite exposed a production defect in `_nll`: extreme optimizer
trial coordinates overflowed `exp`, and very negative nu coordinates rounded nu
to 2 and caused a log-domain exception. The existing explosive-world test leaked
`OverflowError` instead of the model's declared refusal. Eight new direct cases
reproduced these faults before repair (five additional controls already passed).

The fix returns the existing infeasibility penalty for nonfinite/unrepresentable
trial parameters, nu <= 2, nonpositive omega and nonfinite likelihood values.
It does not clamp fitted parameters or relax optimizer convergence, stationarity,
fit budget or fallback policy. The existing explosive-world test now passes.

## Validation and reproduction

142 passed across seven suites, on Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0:

```sh
python -m pytest -q tests/test_garch_objective_bounds.py \
  tests/test_full_model_path.py tests/test_premarket_twin_handoff.py \
  tests/test_court_execution_reconstruction.py tests/test_organism_court_001.py \
  tests/test_funnel_engine.py tests/test_worldmodel_wb.py
```

The new flight leaves `model_observations.json`, the real ledger and court report
under pytest's temporary run directory. A compact retained summary is committed
at `docs/evidence/full_model_path_001/summary.json`, including call order,
parameters, array fingerprints and numeric checks. It binds the test and model
source digests; it is audit-generated evidence, not an external attestation.
No full-tree regression was run.

## What this does not establish

This verifies the active FULL_FUNNEL path on one declared synthetic world. It
does not certify the entire north-star architecture. SVI surface fitting, learned
fusion, enrichment and jumps remain explicitly not invoked by this engine.
JOINT_FUNNEL is a separate route; this flight does not commission it. Strategy
Lab promotion, stock/spread competition and Experience/challenger learning are
not established by this flight.

Premarket is attached context, not a model feature; `model_consumed` stays false.
The location artifact remains unvalidated. Fixed future IV, fixed spread and
European approximation are model assumptions, not validated option forecasts.
More correct plumbing does not establish predictive edge. Chronological
walk-forward evidence and exact-release operational commissioning remain gates.
