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
def _visible_simulation_bars(bars, *, cutoff_epoch: float, sessions: int = 1):
    """Use Hunter's completed-bar/session rule for BOTH returns and spot.

    Legacy normalized frames do not carry measured receipt times. Bar completion
    is an explicit availability assumption, not evidence of network receipt.
    When available_epoch is supplied it must also precede the cutoff; unknown
    supplied availability is excluded rather than backdated.
    """
    import numpy as np
    import pandas as pd
    from apex.hunter.chartstate import visible_bars
    cutoff = pd.Timestamp(cutoff_epoch, unit="s", tz="UTC")
    frame = visible_bars(bars, cutoff).copy()
    market_date = cutoff.tz_convert("America/New_York").date()
    # `sessions` = how many market dates, ending at the decision's own, may contribute. 1 keeps the original
    # today-only behaviour. More admits prior COMPLETED sessions so the variance model can reach MIN_OBS at the
    # open; nothing from AFTER the decision's market date is ever admitted at any setting.
    dates = frame["event_time_utc"].dt.tz_convert("America/New_York").dt.date
    eligible = sorted({d for d in dates.unique() if d <= market_date})[-max(1, int(sessions)):]
    frame = frame[dates.isin(eligible)]
    if "available_epoch" in frame:
        availability = pd.to_numeric(frame["available_epoch"], errors="coerce")
        frame = frame[np.isfinite(availability) & (availability <= cutoff_epoch)]
    frame = frame.sort_values("event_time_utc", kind="stable")
    if frame["event_time_utc"].duplicated().any():
        raise ValueError("DUPLICATE_SIMULATION_BAR")
    closes = pd.to_numeric(frame["close"], errors="coerce")
    if not (np.isfinite(closes) & (closes > 0)).all():
        raise ValueError("INVALID_SIMULATION_CLOSE")
    return frame


def _return_rows(bars, *, cutoff_epoch: float, sessions: int = 1) -> list:
    """Adjacent completed one-minute returns; gaps are not one-minute returns.

    With `sessions` > 1 the market-date filter no longer separates the sessions, so the adjacency rule below is
    the ONLY thing preventing an overnight junction from being recorded as a one-minute return. It is tested
    directly, with the filter bypassed, for exactly that reason."""
    import math
    frame = _visible_simulation_bars(bars, cutoff_epoch=cutoff_epoch, sessions=sessions)
    closes = [float(c) for c in frame["close"].tolist()]
    times = [float(t.timestamp()) for t in frame["event_time_utc"].tolist()]
    availability = (frame["available_epoch"].astype(float).tolist()
                    if "available_epoch" in frame else [t + 60 for t in times])
    rows = []
    for i in range(1, len(closes)):
        if times[i] - times[i - 1] != 60:
            continue
        known = max(times[i] + 60, availability[i - 1], availability[i])
        rows.append({"ret_1": math.log(closes[i] / closes[i - 1]),
                     "event_time": times[i] + 60, "available": known})
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
                    history=None, history_sessions: int = 1,
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
        # THE MODEL'S SAMPLE AND THE SETUP'S FRAME ARE DIFFERENT INPUTS. `history` (prior completed sessions +
        # today) feeds the variance model; `bars` alone would starve it until midday. Both derive from ONE
        # filtered visible frame, so returns and spot can never come from different views of the tape.
        import pandas as _pd
        frame_source = history if history is not None and len(history) else bars
        sessions = max(1, int(history_sessions)) if history is not None else 1
        visible = _visible_simulation_bars(frame_source, cutoff_epoch=as_of_epoch, sessions=sessions)
        if visible.empty:
            return SimulationView("REFUSED", "NO_VISIBLE_BARS", 0, {},
                                  ("NO_COMPLETED_VISIBLE_BARS",), prov)
        # SPOT MUST BELONG TO THE DECISION'S OWN SESSION. With history admitted, the newest completed bar could
        # otherwise be a PRIOR session's close, and a simulation started from yesterday's price is not a
        # simulation of today's decision.
        decision_date = _pd.Timestamp(as_of_epoch, unit="s", tz="UTC").tz_convert("America/New_York").date()
        last_date = visible["event_time_utc"].iloc[-1].tz_convert("America/New_York").date()
        if last_date != decision_date:
            prov["last_visible_date"] = str(last_date)
            return SimulationView("REFUSED", "SPOT_NOT_FROM_DECISION_SESSION", 0, {},
                                  ("newest completed bar is %s, decision session is %s"
                                   % (last_date, decision_date),), prov)
        rows = _return_rows(visible, cutoff_epoch=as_of_epoch, sessions=sessions)
        prov["return_rows"] = len(rows)
        prov["sessions_used"] = sorted({str(d) for d in
                                        visible["event_time_utc"].dt.tz_convert("America/New_York").dt.date})
        spot = float(visible["close"].iloc[-1])
        prov.update(spot=spot, last_bar_start=str(visible["event_time_utc"].iloc[-1]),
                    availability_basis=("BAR_COMPLETION_AND_SUPPLIED_AVAILABILITY"
                                        if "available_epoch" in visible else
                                        "BAR_COMPLETION_ASSUMED_NOT_MEASURED_RECEIPT"))
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
