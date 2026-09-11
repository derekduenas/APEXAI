"""THE FUNNEL ENGINE — every intelligence layer wired into ONE decision path (the organism deciding together).

    PULSE bars ─► Twin snapshot ─► World Model {frozen artifact location, walk-forward GARCH-t variance,
    causal 2-state regime filter} ─► Market-implied {ATM implied vol + relative spread from the live quotes}
    ─► Multiverse {conditional joint simulation of N paths over the 15-minute horizon, regime mixture,
    declared drift} ─► Expression War {WAIT + every eligible contract near ATM, both rights, priced on the
    COMMON paths at the entry ask / modeled exit bid, fees once} ─► PRIME supervision {stale data,
    unsupported state, disagreement, quote uncertainty, margin, risk envelope} ─► proposal (intent shape)
    or WAIT.

The engine is PURE: no ledger, no network, no wall clock. The caller supplies the snapshot, the frozen-
artifact forecast, the quotes, the causal prefix of returns and the training rows; the engine returns the
decision and a `trace` naming what every layer used, so the recording boundary can persist it verbatim.
Selection authority is DECLARED on every proposal (FUNNEL_RULE_ID): the expected values that drive it are
model-conditional under IV_FIXED and are labelled UNESTABLISHED in the economics sense; the sensitivity
table over IV shifts travels with the trace. Fits happen only when the caller says so (walk-forward)."""
from __future__ import annotations

import math
from datetime import date

import numpy as np

from apex.multiverse_wb import expression_war as EW
from apex.multiverse_wb.pricing import PricingRefused, implied_vol, instrument
from apex.multiverse_wb.simulator import ConditionalSimulator, SimulatorRefused
from apex.options_pilot.expression_rule import DTE_MIN_DAYS
from apex.options_pilot.risk_authority import envelope_for
from apex.worldmodel_wb.contracts import ForecastObject, ModelRefused, digest
from apex.worldmodel_wb.regime import MarkovSwitching2
from apex.worldmodel_wb.vol_models import EWMA, GARCH

from .supervision import SupervisionPolicy, supervise

FUNNEL_RULE_ID = ("FULL_FUNNEL_V1: artifact location + walk-forward GARCH-t variance + causal regime mixture + ATM implied vol -> joint "
                  "simulation -> expression comparison (WAIT + nearest-ATM +/-k strikes, both rights) -> PRIME supervision; best expected "
                  "net P&L > 0 buys one contract, else WAIT")
FUNNEL_POLICY = SupervisionPolicy(max_bar_age_s=120.0, max_disagreement_ratio=1.0, max_spread_rel=0.15, min_expected_net_pnl=0.0,
                                  require_value_established=False)
FUNNEL_POLICY_NOTE = ("require_value_established=False is a DECLARED deviation: the funnel acts on the model-conditional expected value under "
                      "IV_FIXED (labelled UNESTABLISHED as an economic claim); the IV sensitivity table is recorded with every decision. "
                      "max_disagreement_ratio=1.0 is |log(artifact variance / GARCH integrated variance)| at the 15-minute horizon")
MINUTES_PER_YEAR = 252.0 * 390.0
MIN_TRAIN_BARS = 400
UNSUPPORTED_MASS_MAX = 0.20       # declared: filtered probability mass allowed on regime states that were thin in training


class FunnelEngine:
    def __init__(self, *, policy: SupervisionPolicy = FUNNEL_POLICY, n_paths: int = 2000, seed: int = 11, strikes_each_side: int = 4,
                 fit_budget: int = 400, regime_iters: int = 40, min_train_bars: int = MIN_TRAIN_BARS):
        self.policy, self.n_paths, self.seed, self.k_side = policy, n_paths, seed, strikes_each_side
        self.fit_budget, self.fits, self.regime_iters, self.min_train_bars = fit_budget, 0, regime_iters, min_train_bars
        self.garch: GARCH | None = None
        self.variance = None                       # the variance model in force: GARCH-t, or the EWMA FALLBACK when GARCH-t refuses (declared)
        self.variance_kind: str = "NONE"
        self.regime: MarkovSwitching2 | None = None
        self.fit_info: dict = {"status": "NOT_FITTED"}
        self.fit_log: list = []
        self.decisions = 0

    def describe(self) -> dict:
        return {"rule_id": FUNNEL_RULE_ID, "policy": self.policy.describe(), "policy_note": FUNNEL_POLICY_NOTE, "n_paths": self.n_paths,
                "seed": self.seed, "strikes_each_side": self.k_side, "fit_budget": self.fit_budget, "fits": self.fits,
                "min_train_bars": self.min_train_bars, "fit": {k: v for k, v in self.fit_info.items() if k != "train_sessions"}}

    # ------------------------------------------------------------ walk-forward fits (caller decides WHEN; rows must precede the cutoff)
    def fit(self, rows: list, *, cutoff_epoch: float, label: str | None = None) -> dict:
        """rows: [{"event_time", "available", "ret_1"}] strictly available <= cutoff_epoch (the models' firewall enforces it)."""
        info = {"label": label, "cutoff_epoch": cutoff_epoch, "n_train": len(rows)}
        self.garch = self.regime = self.variance = None; self.variance_kind = "NONE"
        if len(rows) < self.min_train_bars:
            info["status"] = "INSUFFICIENT_HISTORY: %d < %d bars" % (len(rows), self.min_train_bars)
            self.fit_info = info; self.fit_log.append(info); return info
        for name, mk in (("garch", lambda: GARCH()), ("regime", lambda: MarkovSwitching2(iters=self.regime_iters))):
            if self.fits >= self.fit_budget:
                info[name] = "FIT_BUDGET_EXHAUSTED"; continue
            m = mk()
            try:
                self.fits += 1
                m.fit(rows, cutoff_epoch=cutoff_epoch)
                setattr(self, name, m)
                info[name] = {"artifact_digest": m.serialize()["artifact_digest"],
                              **({"persistence": m.p["persistence"], "nu": m.p["nu"]} if name == "garch" else {"support": m.p["support_train"]})}
            except ModelRefused as e:
                info[name] = "REFUSED: %s" % str(e)[:160]
        if self.garch is not None:
            self.variance, self.variance_kind = self.garch, "GARCH-t (walk-forward)"
        elif "FIREWALL" not in str(info.get("garch")) and self.fits < self.fit_budget:
            # DECLARED FALLBACK: GARCH-t refused (e.g. NU_AT_BOUND on thin-tailed data, non-stationary fit); EWMA variance with GAUSSIAN
            # innovations and no mean reversion carries the simulation instead, and every trace says so
            m = EWMA()
            try:
                self.fits += 1
                m.fit(rows, cutoff_epoch=cutoff_epoch)
                self.variance, self.variance_kind = m, "EWMA_FALLBACK (GARCH-t refused: %s)" % str(info.get("garch"))[:80]
                info["ewma_fallback"] = {"artifact_digest": m.serialize()["artifact_digest"], "h": m.h}
            except ModelRefused as e:
                info["ewma_fallback"] = "REFUSED: %s" % str(e)[:120]
        info["variance_kind"] = self.variance_kind
        info["status"] = "READY" if self.variance is not None else "VARIANCE_UNAVAILABLE"
        self.fit_info = info; self.fit_log.append(info)
        return info

    @property
    def ready(self) -> bool:
        return self.variance is not None

    # ------------------------------------------------------------ one decision
    def decide(self, *, symbol: str, as_of: float, day: str, snapshot: dict, forecast: dict, spot, quotes: dict, prefix_returns: list,
               fee_schedule, book_summary: dict | None = None, heuristic_direction: str | None = None) -> dict:
        """quotes: {(expiration, strike, right): {bid, ask, bid_size, ask_size[, timestamp_epoch]}} — indicative, at as_of.
        Returns {"decision": TRADE|WAIT, "why", "proposal" (intent shape) | None, "trace": {...every layer...}}."""
        self.decisions += 1
        tr: dict = {"engine": "FULL_FUNNEL_V1", "fit": {k: v for k, v in self.fit_info.items() if k != "train_sessions"},
                    "heuristic_direction": heuristic_direction, "state_hash": (snapshot or {}).get("state_hash")}
        out = {"decision": "WAIT", "why": None, "proposal": None, "trace": tr, "rule_id": FUNNEL_RULE_ID}

        def wait(why):
            out["why"] = why; tr["final"] = {"decision": "WAIT", "why": why}; return out

        if not self.ready:
            return wait("PRIME_ABSTAIN: UNSUPPORTED_STATE: variance model %s" % self.fit_info.get("status"))
        if not isinstance(spot, (int, float)) or isinstance(spot, bool) or not spot > 0:
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: spot %r" % (spot,))
        loc = (forecast or {}).get("location")
        if not isinstance(loc, (int, float)) or not math.isfinite(loc):
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: forecast location %r" % (loc,))
        prefix = [float(r) for r in prefix_returns]
        # --- situation / regime (filtered, causal) and variance (rolled forward over the prefix, no refit)
        reg = None
        if self.regime is not None and len(prefix) >= 5:
            try:
                reg = self.regime.filtered(prefix[-390:], cutoff_epoch=as_of)
            except ModelRefused as e:
                reg = None; tr["regime_error"] = str(e)[:120]
        if reg:
            # the model abstains whenever ANY state was thin in training; the funnel abstains only when the CURRENT filtered mass on
            # thin states is material (declared threshold), or entropy is high: a well-supported state we are almost surely in is supported
            unsupported = [k for k in range(len(reg["probabilities"])) if reg["support_train"][k] < self.regime.min_support]
            mass = float(sum(reg["probabilities"][k] for k in unsupported))
            ent_bad = "HIGH_ENTROPY" in (reg.get("abstain_why") or "")
            reg = {**reg, "model_abstain": reg["abstain"], "model_abstain_why": reg["abstain_why"], "unsupported_states": unsupported,
                   "unsupported_state_mass": mass, "abstain": bool(ent_bad or mass > UNSUPPORTED_MASS_MAX),
                   "abstain_why": (reg["abstain_why"] if ent_bad else
                                   ("UNSUPPORTED_STATE: filtered mass %.2f on thin states %s > %.2f" % (mass, unsupported, UNSUPPORTED_MASS_MAX) if mass > UNSUPPORTED_MASS_MAX else None))}
        tr["regime"] = ({k: reg[k] for k in ("probabilities", "entropy_bits", "abstain", "abstain_why", "model_abstain", "unsupported_state_mass",
                                             "bars_since_last_transition", "parameter_version")}
                        if reg else {"missing": "REGIME_UNAVAILABLE: %s" % (tr.get("regime_error") or self.fit_info.get("regime") or "no prefix")})
        try:
            gf = self.variance.forecast(cutoff_epoch=as_of, created_epoch=as_of, horizon_bars=15, recent=prefix)
        except ModelRefused as e:
            return wait("PRIME_ABSTAIN: UNSUPPORTED_STATE: variance forecast refused (%s)" % str(e)[:120])
        h1 = gf.meta["next_bar_variance"]
        tr["variance"] = {"model": self.variance_kind, "next_bar_variance": h1, "integrated_15": gf.meta["integrated_variance"],
                          "artifact_digest": gf.artifact_digest, "prefix_bars": len(prefix), "innovations": "STUDENT_T" if self.garch is not None else "GAUSSIAN"}
        # --- market-implied state from the quotes at the decision minute
        today = date.fromisoformat(day[:10])
        exps = sorted({e for (e, _k, _r) in quotes if (date.fromisoformat(e) - today).days >= DTE_MIN_DAYS})
        if not exps:
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: no expiry with DTE >= %d among the quotes" % DTE_MIN_DAYS)
        exp = exps[0]
        T = (date.fromisoformat(exp) - today).days / 365.0
        strikes = sorted({float(k) for (e, k, _r) in quotes if e == exp})
        atm = min(strikes, key=lambda k: (abs(k - spot), k))
        ivs, iv_detail = [], {}
        for right in ("CALL", "PUT"):
            q = quotes.get((exp, atm, right))
            if q and _pos(q.get("bid")) and _pos(q.get("ask")):
                try:
                    r = implied_vol(price=0.5 * (q["bid"] + q["ask"]), S=spot, K=atm, T=T, right=right)
                    ivs.append(r["iv"]); iv_detail[right] = r["iv"]
                except PricingRefused as e:
                    iv_detail[right] = "REFUSED: %s" % str(e)[:80]
        if not ivs:
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: ATM implied vol not identified (%s)" % iv_detail)
        iv0 = float(np.mean(ivs))
        qa = quotes.get((exp, atm, "CALL")) or quotes.get((exp, atm, "PUT"))
        spread_bps0 = 1e4 * (qa["ask"] - qa["bid"]) / (0.5 * (qa["ask"] + qa["bid"]))
        physical_var_15 = float(gf.meta["integrated_variance"])
        tr["implied"] = {"expiry": exp, "T_years": T, "atm_strike": atm, "iv0": iv0, "by_right": iv_detail, "spread_bps0": spread_bps0,
                         "method": "BSM inversion on the ATM mid, EUROPEAN_APPROX, r=q=0",
                         "physical_vs_implied": EW.physical_vs_implied(physical_var_15m=physical_var_15, implied_iv_annual=iv0)}
        # --- multiverse: conditional joint simulation on the fitted state with the artifact's location as declared drift
        regime_cfg = None
        if reg and not reg["abstain"]:
            sig = self.regime.p["sigma"]; base_var = sum(p * s * s for p, s in zip(reg["probabilities"], sig))
            if base_var > 0:
                regime_cfg = {"probabilities": reg["probabilities"], "variance_multipliers": [s * s / base_var for s in sig]}
        if self.garch is not None:
            vm = {"kind": "GARCH", **{k: float(self.garch.p[k]) for k in ("omega", "alpha", "beta", "gamma")}, "h_last": float(h1),
                  "e_last": prefix[-1] if prefix else 0.0}
            nu = self.garch.p["nu"]
        else:
            vm, nu = {"kind": "FLAT", "h": float(h1)}, None
        try:
            sim = ConditionalSimulator(S0=float(spot), variance_model=vm, nu=nu, iv0=iv0, spread_bps0=spread_bps0, regime=regime_cfg,
                                       cutoff_epoch=as_of, drift_per_bar=float(loc) / 15.0)
            paths = sim.simulate(horizon_bars=15, n_paths=self.n_paths, seed=(self.seed * 100003 + int(as_of) % 100003 + self.decisions) % (2 ** 31))
        except SimulatorRefused as e:
            return wait("PRIME_ABSTAIN: UNSUPPORTED_STATE: simulator refused (%s)" % e)
        tr["simulation"] = {"parameter_hash": paths["parameter_hash"], "seed": paths["seed"], "n_paths": self.n_paths, "restrictions": paths["restrictions"],
                            "mean_log_return": paths["moments"]["mean_log_return"], "var_log_return": paths["moments"]["var_log_return"],
                            "se_mean": paths["sampling_error"]["se_mean"], "regime_mixture": regime_cfg is not None,
                            "p_return_gt_zero": float(np.mean(np.log(paths["S"][:, -1] / paths["S"][:, 0]) > 0))}
        # --- expression war over the eligible set (WAIT + nearest-ATM +/- k strikes, both rights) on the COMMON paths
        i_atm = strikes.index(atm)
        eligible = strikes[max(0, i_atm - self.k_side): i_atm + self.k_side + 1]
        cands, T_by, key_by_label = [], {}, {}
        for k in eligible:
            for right in ("CALL", "PUT"):
                q = quotes.get((exp, k, right))
                if not q or not _pos(q.get("ask")):
                    continue
                label = "%s|%s|%s|%s" % (symbol, exp, k, right)
                cands.append({"label": label, "instrument": instrument(symbol=symbol, expiration=exp, strike=k, right=right, exercise="AMERICAN", settlement="PHYSICAL"),
                              "quote": {"bid": q.get("bid", 0.0), "ask": q["ask"], "bid_size": q.get("bid_size", 0), "ask_size": q.get("ask_size", 0),
                                        "timestamp_epoch": q.get("timestamp_epoch", as_of)}})
                T_by[label] = T; key_by_label[label] = (exp, k, right)
        fe, fx = fee_schedule.entry(1)["total"], fee_schedule.exit(1)["total"]
        cmp = EW.compare(paths=paths, candidates=cands, T_years_by_contract=T_by, horizon_years=15.0 / MINUTES_PER_YEAR, r=0.0, fees_entry=fe, fees_exit=fx,
                         now=as_of, quote_max_age_s=120.0, iv_shifts=(-0.1, 0.0, 0.1))
        tr["expression_war"] = {"n_candidates": len(cands), "eligible_strikes": eligible, "table": None, "fees": {"entry": fe, "exit": fx},
                                "expected_value_note": cmp["expected_value_note"], "selection_authority": FUNNEL_RULE_ID,
                                "common_paths": cmp["common_paths"]}
        # --- risk envelope INSIDE the candidate set: a contract whose ask cannot fit the kernel cap is a rejected candidate, so the
        #     comparison ranks only expressions the book could actually hold (the kernel re-checks at intent commit)
        n_env_rejected = 0
        for c in cmp["candidates"]:
            if c["label"] == "WAIT" or c["status"] != "ELIGIBLE":
                continue
            env = envelope_for(reference_ask=c["entry_ask"], quantity=1)
            if not env["feasible"] or c["entry_ask"] > env["max_entry_price"]:
                c["status"], c["why"] = "REJECTED", "RISK_ENVELOPE: %s" % (env.get("why_infeasible") or "ask %.2f > max entry %.2f" % (c["entry_ask"], env["max_entry_price"]))
                c["expected_net_pnl_if_unconstrained"] = c.pop("expected_net_pnl", None)
                n_env_rejected += 1
        table = [{k: c.get(k) for k in ("label", "status", "expected_net_pnl", "p_loss", "q05", "q50", "entry_ask", "entry_spread_rel", "mc_se_mean",
                                        "iv_sensitivity_of_expected_pnl", "why", "expected_net_pnl_if_unconstrained")} for c in cmp["candidates"]]
        tr["expression_war"]["table"] = table
        tr["expression_war"]["rejected_by_risk_envelope"] = n_env_rejected
        elig = [c for c in cmp["candidates"] if c["status"] == "ELIGIBLE" and c["label"] != "WAIT"]
        if not elig:
            whys = [c.get("why") for c in cmp["candidates"] if c["label"] != "WAIT"]
            return wait("NO_ELIGIBLE_CANDIDATE: every contract rejected (%d by the risk envelope): %s" % (n_env_rejected, whys[:2]))
        best = max(elig, key=lambda c: c["expected_net_pnl"])
        # --- PRIME supervision on the best FEASIBLE candidate
        env = envelope_for(reference_ask=best["entry_ask"], quantity=1)
        risk = {"approved": True, "why": None, "envelope": {k: env.get(k) for k in ("max_entry_price", "feasible", "why_infeasible")}}
        fo = ForecastObject(model_id="FUNNEL:%s+GARCH+REGIME" % forecast.get("model_id"), artifact_digest=str(forecast.get("params_hash")), horizon_minutes=15,
                            input_cutoff_epoch=as_of - 60, created_epoch=as_of, supplies=("mean", "variance", "density"), mean=float(loc),
                            variance=paths["moments"]["var_log_return"],
                            density={"family": "GAUSSIAN", "location": float(loc), "variance": paths["moments"]["var_log_return"]},
                            meta={"p_return_gt_zero": tr["simulation"]["p_return_gt_zero"], "p_meaning": "P(15-minute log return > 0) under the simulated joint paths",
                                  "model_disagreement_ratio": _disagreement(physical_var_15, forecast)})
        sup = supervise(forecast=fo, snapshot=snapshot, comparison=cmp, risk_decision=risk, book_summary=book_summary or {"integrity_problems": []},
                        regime=reg, candidate_label=best["label"], policy=self.policy)
        tr["prime"] = {"decision": sup["decision"], "reasons": sup["reasons"], "confidence": sup["confidence"], "policy": self.policy.describe(),
                       "policy_note": FUNNEL_POLICY_NOTE, "candidate": best["label"], "risk": risk}
        if sup["decision"] != "ACT":
            return wait("PRIME_ABSTAIN: " + "; ".join(sup["reasons"])[:240])
        exp_, k_, right_ = key_by_label[best["label"]]
        q = quotes[(exp_, k_, right_)]
        out.update(decision="TRADE", why="FUNNEL_SELECTED: %s expected net %.2f (model-conditional, IV_FIXED)" % (best["label"], best["expected_net_pnl"]),
                   proposal={"expression": "LONG_CALL" if right_ == "CALL" else "LONG_PUT", "action": "BUY",
                             "contract": {"symbol": symbol, "expiration": exp_, "strike": float(k_), "right": right_}, "quantity": 1,
                             "expression_rule": FUNNEL_RULE_ID, "reference_ask": q["ask"],
                             "direction_signal": "LONG" if right_ == "CALL" else "SHORT",
                             "expected_net_pnl_model": best["expected_net_pnl"], "expected_value_established": False})
        tr["selected"] = {"label": best["label"], "expected_net_pnl": best["expected_net_pnl"], "p_loss": best["p_loss"], "q05": best["q05"],
                          "entry_ask": best["entry_ask"], "iv_sensitivity": best["iv_sensitivity_of_expected_pnl"], "trace_digest": None}
        tr["final"] = {"decision": "TRADE", "why": out["why"]}
        tr["selected"]["trace_digest"] = digest({k: v for k, v in tr.items() if k != "selected"})
        return out


def _pos(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def _disagreement(physical_var_15: float, forecast: dict) -> float | None:
    """Ratio of disagreement between the artifact's scale and the GARCH integrated variance at the same horizon: |log(v_art / v_garch)|."""
    sc, nu = forecast.get("scale"), forecast.get("nu")
    if not _pos(sc) or not _pos(physical_var_15):
        return None
    v_art = sc * sc * (nu / (nu - 2.0)) if _pos(nu) and nu > 2 else sc * sc
    return abs(math.log(v_art / physical_var_15))
