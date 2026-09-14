"""HUNTER_INTELLIGENCE_WIRING_V1 — ask every intelligence layer, and let the absence be MEASURED.

THE DEFECT THIS EXISTS FOR, observed on the live 2026-09-14 session. `forward_pass.decision_pass` assembled its
forecast bundle as:

    bundle = assemble_bundle(d, analog_result=analog, swarm=swarm)

No `ml_prediction`. No `simulation`. `assemble_bundle` then supplies its documented defaults -- ml_view becomes
the literal `{"status": "UNTRAINED", "reasons": ["INSUFFICIENT_FORWARD_DATA"]}` and simulation_view becomes
`None` -- and the resulting record is indistinguishable from one where the model was actually consulted and
actually had nothing to say.

That is not a typed absence. A typed absence is an answer; this was an unasked question wearing the costume of
one. Every capital decision ever recorded (10 of 10) carries `forecast = NOT_YET_AVAILABLE`, and nobody could
tell from the record whether the forecast layer was starved, broken, or simply never called.

So this module CALLS them. What comes back may still be a refusal -- the ML model genuinely needs 40 effective
cells and the variance model genuinely needs a minimum number of observations -- but it will be a refusal with a
NUMBER in it, produced by the layer itself, and a later reader can tell "starved" from "never asked".

WHAT IT DOES NOT DO: it does not lower a threshold, soften a refusal, or invent a probability. A layer that
cannot speak still says nothing; it just says nothing *for a stated reason, on the record*.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA = "HUNTER_INTELLIGENCE_WIRING_V1"

DEFAULT_N_PATHS = 2000
DEFAULT_HORIZON_BARS = 60
MIN_BARS_FOR_VARIANCE = 60          # below this the variance model refuses; we ask anyway and record the refusal


@dataclass(frozen=True)
class SimulationView:
    """Exactly the shape `assemble_bundle` reads, plus the reasons a refusal needs to carry."""
    calibration_status: str
    source: str
    n_paths: int
    branch_scenario_frequencies: dict
    reasons: tuple = ()
    provenance: dict = field(default_factory=dict)


# ------------------------------------------------------------------ the ML layer
def ml_view(candidate: dict, ledger_rows: list, *, evidence_class,
            horizon_minutes: int = 60) -> dict:
    """Ask the ML layer for this candidate. Returns `predict_p_positive()`'s own typed output.

    The dataset is built from the SAME ledger rows the forward pass already reads for half-life estimation, so
    this adds no new data dependency -- only the question nobody was asking.

    `evidence_class` is REQUIRED, mirroring `build_dataset`'s own contract ("a training set whose provenance is
    assumed is not a training set"). Defaulting it to None would turn a caller's omission into a REFUSED_ERROR
    record -- a wrapper quietly converting a programming mistake into what reads like a measured refusal, which
    is the very confusion this module exists to remove."""
    out = {"asked": True, "wiring": SCHEMA}
    try:
        from apex.ml.hunter_models import MIN_EFFECTIVE_TO_TRAIN, build_dataset, train
        realized = {r["decision_id"]: r for r in ledger_rows
                    if r.get("kind") == "realization" and r.get("resolvable")}
        decisions = [r for r in ledger_rows if r.get("kind") == "decision"]
        ds = build_dataset(decisions, realized, horizon_minutes, evidence_class=evidence_class)
        model = train(ds)
        pred = model.predict_p_positive(candidate)
        out.update(pred)
        out.update(n_raw=ds.n_raw, n_effective=ds.n_effective,
                   min_effective_to_train=MIN_EFFECTIVE_TO_TRAIN,
                   model_status=model.status, engine_version=model.engine_version)
        return out
    except Exception as e:                                          # noqa: BLE001
        # A layer that BLEW UP is not a layer that had nothing to say, and the record must not blur them.
        out.update(status="REFUSED_ERROR", p_positive=None,
                   reasons=["%s: %s" % (type(e).__name__, str(e)[:200])])
        return out


# ------------------------------------------------------------------ the variance + multiverse layer
def _return_rows(bars, *, cutoff_epoch: float) -> list:
    """One-minute log returns in the row shape the variance models consume.

    EACH ROW CARRIES WHEN IT BECAME KNOWABLE. The variance model enforces a point-in-time firewall and refuses a
    fit offered any row available after the cutoff -- correctly, and it caught this adapter's first version, which
    supplied bare returns with no availability stamp at all. A return from bar[i] to bar[i+1] is knowable at
    bar[i+1]'s close, so that is its `event_time`."""
    import numpy as np
    closes = [float(c) for c in bars["close"].tolist()]
    times = [float(t.timestamp()) for t in bars["event_time_utc"].tolist()]
    rows = []
    for (a, b, tb) in zip(closes, closes[1:], times[1:]):
        if a > 0 and b > 0 and tb <= cutoff_epoch:
            rows.append({"ret_1": float(np.log(b / a)), "event_time": tb, "available": tb})
    return rows


def _branch_frequencies(S, s0: float, sd: float) -> dict:
    """Scenario FREQUENCY over simulated terminals -- never a calibrated probability, and named so."""
    import numpy as np
    term = np.asarray(S)[:, -1]
    r = np.log(term / s0)
    n = float(len(r))
    return {"UP_BEYOND_1SD": round(float((r > sd).sum() / n), 4),
            "UP": round(float(((r > 0) & (r <= sd)).sum() / n), 4),
            "DOWN": round(float(((r <= 0) & (r >= -sd)).sum() / n), 4),
            "DOWN_BEYOND_1SD": round(float((r < -sd).sum() / n), 4),
            "note": "scenario frequency under the FIXED fitted model, NOT a calibrated probability"}


def simulation_view(candidate: dict, bars, *, as_of_epoch: float,
                    horizon_bars: int = DEFAULT_HORIZON_BARS,
                    n_paths: int = DEFAULT_N_PATHS, seed: int = 0,
                    prefer_garch: bool = True) -> SimulationView:
    """Fit a conditional variance model to the visible bars and run the multiverse simulator.

    Every failure path returns a SimulationView with calibration_status REFUSED and a reason that names what was
    missing. `None` is never returned, because `None` is what the bundle already recorded and it is precisely
    what could not be distinguished from 'not wired'."""
    prov = {"wiring": SCHEMA, "horizon_bars": horizon_bars, "requested_paths": n_paths}
    try:
        if bars is None or not len(bars):
            return SimulationView("REFUSED", "NO_BARS", 0, {}, ("NO_BARS_FOR_SYMBOL",), prov)
        rows = _return_rows(bars, cutoff_epoch=as_of_epoch)
        prov["return_rows"] = len(rows)
        spot = float(bars["close"].iloc[-1])
        if not (spot > 0):
            return SimulationView("REFUSED", "SPOT_INVALID", 0, {}, ("SPOT_NOT_POSITIVE",), prov)

        from apex.worldmodel_wb.contracts import ModelRefused
        from apex.worldmodel_wb.vol_models import GARCH, RollingVariance

        model, nu, vm_kind = None, None, None
        if prefer_garch and len(rows) >= MIN_BARS_FOR_VARIANCE:
            try:
                g = GARCH(gjr=False)
                g.fit(rows, cutoff_epoch=as_of_epoch)
                model, nu, vm_kind = g, float(g.p.get("nu")) if g.p.get("nu") else None, "GARCH"
            except ModelRefused as e:
                # GARCH REFUSING IS AN ANSWER AND IT GOES ON THE RECORD. Its multi-start convergence guard
                # legitimately declines many one-minute samples ("NOT_CONVERGED: multi-start NLL disagreement").
                # The first version of this adapter swallowed that into a bare fallback, which would have left
                # the record saying ROLLING_VAR with no hint that GARCH had been asked at all -- the exact
                # failure this module exists to end.
                prov["garch_refused"] = str(e)[:220]
            except Exception as e:                                  # noqa: BLE001
                prov["garch_error"] = "%s: %s" % (type(e).__name__, str(e)[:180])
        else:
            prov["garch_not_attempted"] = ("need >= %d return rows, have %d"
                                           % (MIN_BARS_FOR_VARIANCE, len(rows)))
        if model is None:
            try:
                rv = RollingVariance(window=30)
                rv.fit(rows, cutoff_epoch=as_of_epoch)
                model, vm_kind = rv, "FLAT"
            except ModelRefused as e:
                return SimulationView("REFUSED", "VARIANCE_MODEL_REFUSED", 0, {},
                                      ("VARIANCE_REFUSED: %s" % str(e)[:160],), prov)
            except Exception as e:                                  # noqa: BLE001
                return SimulationView("REFUSED", "VARIANCE_MODEL_ERROR", 0, {},
                                      ("%s: %s" % (type(e).__name__, str(e)[:160]),), prov)

        fc = model.forecast(cutoff_epoch=as_of_epoch, created_epoch=as_of_epoch,
                            horizon_bars=horizon_bars, recent=[r["ret_1"] for r in rows])
        h_next = float(fc.meta["next_bar_variance"])
        prov.update(variance_model=model.model_id, next_bar_variance=h_next,
                    artifact_digest=getattr(fc, "artifact_digest", None))

        if vm_kind == "GARCH":
            vm = {"kind": "GARCH", **{k: float(model.p[k]) for k in ("omega", "alpha", "beta", "gamma")},
                  "h_next": h_next}
        else:
            vm, nu = {"kind": "FLAT", "h": h_next}, None

        from apex.multiverse_wb.simulator import ConditionalSimulator, SimulatorRefused
        try:
            sim = ConditionalSimulator(S0=spot, variance_model=vm, nu=nu, iv0=0.20,
                                       spread_bps0=1.0, cutoff_epoch=as_of_epoch)
            paths = sim.simulate(horizon_bars=horizon_bars, n_paths=n_paths, seed=seed)
        except SimulatorRefused as e:
            return SimulationView("REFUSED", "SIMULATOR_REFUSED", 0, {},
                                  ("SIMULATOR_REFUSED: %s" % str(e)[:160],), prov)

        # The one state convention, asserted here as it is in decision_wb: the first simulated bar's variance IS
        # the variance model's next-bar forecast. A silent mismatch would make every branch frequency a fiction.
        if float(paths["h_next"]) != h_next:
            return SimulationView("REFUSED", "VARIANCE_HANDOFF_MISMATCH", 0, {},
                                  ("simulator first-bar variance %r != forecast %r"
                                   % (paths["h_next"], h_next),), prov)

        import math
        sd = math.sqrt(max(float(paths["moments"]["var_log_return"]), 0.0))
        prov.update(parameter_hash=paths["parameter_hash"], seed=paths["seed"],
                    innovations=paths["innovations"], restrictions=paths["restrictions"],
                    moments=paths["moments"], sampling_error=paths["sampling_error"],
                    model_uncertainty=paths["model_uncertainty"])
        return SimulationView(
            calibration_status="SIMULATED_UNCALIBRATED",
            source="%s->MULTIVERSE_CONDITIONAL" % model.model_id,
            n_paths=int(paths["n_paths"]),
            branch_scenario_frequencies=_branch_frequencies(paths["S"], spot, sd),
            reasons=(), provenance=prov)
    except Exception as e:                                          # noqa: BLE001
        return SimulationView("REFUSED", "WIRING_ERROR", 0, {},
                              ("%s: %s" % (type(e).__name__, str(e)[:200]),), prov)
