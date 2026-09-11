"""THE FUNNEL ENGINE — the intelligence layers wired into ONE decision path (r2: integration repairs).

    PULSE bars ─► Twin snapshot ─► World Model {frozen artifact location, walk-forward GARCH-t variance,
    causal 2-state regime filter} ─► Market-implied {ATM implied vol + relative spread from VALIDATED quotes}
    ─► Multiverse {conditional joint simulation of N paths over the 15-minute horizon, regime mixture,
    declared drift, TRUNCATED-t innovations with finite exponential moments} ─► Expression War {WAIT + every
    eligible contract near ATM, both rights, priced on the COMMON paths at the entry ask / modeled exit bid,
    fees once; the risk envelope inside the candidate set} ─► PRIME supervision ─► proposal or WAIT.

Layers NOT invoked by this engine (explicit): the SVI surface (ATM IV only), learned fusion, enrichment.

The engine is PURE: no ledger, no network, no wall clock. Mandatory inputs (FULL mode): fitted variance model,
fitted regime model with a usable prefix, twin snapshot, forecast, spot, validated quotes, book summary. A
REDUCED_NO_REGIME mode exists and must be selected by name; it is labelled on every trace.
Two clocks are kept apart: option time-to-expiry decays on CALENDAR time (T from timestamps, exit 900 s later);
variance accrues on MARKET time (one-minute bars). The engine's price envelope check is PRELIMINARY
AFFORDABILITY; kernel approval happens at intent commit inside the recording boundary, not here."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np

from apex.multiverse_wb import expression_war as EW
from apex.multiverse_wb.expression_war import CALENDAR_YEAR_S, HORIZON_15M_CALENDAR_YEARS
from apex.multiverse_wb.pricing import PricingRefused, implied_vol, instrument, sanitize_quote
from apex.multiverse_wb.simulator import DEFAULT_TAIL_CAP_SD, ConditionalSimulator, SimulatorRefused
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
MODES = ("FULL", "REDUCED_NO_REGIME")
MIN_TRAIN_BARS = 400
MIN_PREFIX_BARS = 5
UNSUPPORTED_MASS_MAX = 0.20       # declared: filtered probability mass allowed on regime states that were thin in training
QUOTE_MAX_AGE_S = 120.0           # declared: a quote older than this at the decision instant is not market state
TAIL_SENSITIVITY_CAPS = (6.0, 12.0)
LAYERS_NOT_INVOKED = {"svi_surface": "NOT_INVOKED: ATM implied vol only (no surface fit, no skew)", "fusion": "NOT_INVOKED: no learned weights",
                      "enrichment": "NOT_INVOKED", "jumps": "NOT_MODELLED"}
ET = ZoneInfo("America/New_York")


class FunnelEngine:
    def __init__(self, *, policy: SupervisionPolicy = FUNNEL_POLICY, n_paths: int = 2000, seed: int = 11, strikes_each_side: int = 4,
                 fit_budget: int = 400, regime_iters: int = 40, min_train_bars: int = MIN_TRAIN_BARS, mode: str = "FULL",
                 tail_cap_sd: float = DEFAULT_TAIL_CAP_SD, quote_max_age_s: float = QUOTE_MAX_AGE_S):
        if mode not in MODES:
            raise ValueError("MODE_UNKNOWN: %r" % (mode,))
        self.policy, self.n_paths, self.seed, self.k_side = policy, n_paths, seed, strikes_each_side
        self.fit_budget, self.fits, self.regime_iters, self.min_train_bars = fit_budget, 0, regime_iters, min_train_bars
        self.mode, self.tail_cap_sd, self.quote_max_age_s = mode, float(tail_cap_sd), float(quote_max_age_s)
        self.garch: GARCH | None = None
        self.variance = None                       # the variance model in force: GARCH-t, or the EWMA FALLBACK when GARCH-t refuses (declared)
        self.variance_kind: str = "NONE"
        self.regime: MarkovSwitching2 | None = None
        self.fit_info: dict = {"status": "NOT_FITTED"}
        self.fit_log: list = []
        self.decisions = 0

    def describe(self) -> dict:
        return {"rule_id": FUNNEL_RULE_ID, "mode": self.mode, "policy": self.policy.describe(), "policy_note": FUNNEL_POLICY_NOTE, "n_paths": self.n_paths,
                "seed": self.seed, "strikes_each_side": self.k_side, "fit_budget": self.fit_budget, "fits": self.fits, "tail_cap_sd": self.tail_cap_sd,
                "quote_max_age_s": self.quote_max_age_s, "min_train_bars": self.min_train_bars, "layers_not_invoked": LAYERS_NOT_INVOKED,
                "fit": {k: v for k, v in self.fit_info.items() if k != "train_sessions"}}

    # ------------------------------------------------------------ walk-forward fits (caller decides WHEN; rows must precede the cutoff)
    def fit(self, rows: list, *, cutoff_epoch: float, label: str | None = None) -> dict:
        """rows: [{"event_time", "available", "ret_1"}] strictly available <= cutoff_epoch (the models' firewall enforces it)."""
        info = {"label": label, "cutoff_epoch": cutoff_epoch, "n_train": len(rows), "mode": self.mode}
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
                              **({"persistence": m.p["persistence"], "nu": m.p["nu"], "convergence": m.p.get("convergence")} if name == "garch"
                                 else {"support": m.p["support_train"]})}
            except ModelRefused as e:
                info[name] = "REFUSED: %s" % str(e)[:160]
        if self.garch is not None:
            self.variance, self.variance_kind = self.garch, "GARCH-t (walk-forward)"
        elif "FIREWALL" not in str(info.get("garch")) and self.fits < self.fit_budget:
            # DECLARED FALLBACK: GARCH-t refused (NU_AT_BOUND on thin-tailed data, non-stationary, not converged); EWMA variance with
            # GAUSSIAN innovations and no mean reversion carries the simulation instead, and every trace says so
            m = EWMA()
            try:
                self.fits += 1
                m.fit(rows, cutoff_epoch=cutoff_epoch)
                self.variance, self.variance_kind = m, "EWMA_FALLBACK (GARCH-t refused: %s)" % str(info.get("garch"))[:80]
                info["ewma_fallback"] = {"artifact_digest": m.serialize()["artifact_digest"], "h": m.h}
            except ModelRefused as e:
                info["ewma_fallback"] = "REFUSED: %s" % str(e)[:120]
        info["variance_kind"] = self.variance_kind
        if self.variance is None:
            info["status"] = "VARIANCE_UNAVAILABLE"
        elif self.regime is None and self.mode == "FULL":
            info["status"] = "REGIME_UNAVAILABLE (FULL mode requires the regime model; select REDUCED_NO_REGIME by name to proceed without it)"
        else:
            info["status"] = "READY"
        self.fit_info = info; self.fit_log.append(info)
        return info

    @property
    def ready(self) -> bool:
        return self.fit_info.get("status") == "READY"

    # ------------------------------------------------------------ one decision
    def decide(self, *, symbol: str, as_of: float, day: str, snapshot: dict, forecast: dict, spot, quotes: dict, prefix_returns: list,
               fee_schedule, book_summary: dict | None, heuristic_direction: str | None = None) -> dict:
        """quotes: {(expiration, strike, right): {bid, ask, bid_size, ask_size, timestamp_epoch}} as RECEIVED (a missing timestamp stays
        missing and rejects the quote). Returns {"decision": TRADE|WAIT, "why", "proposal" | None, "trace": {...every layer...}}."""
        self.decisions += 1
        tr: dict = {"engine": "FULL_FUNNEL_V1", "mode": self.mode, "fit": {k: v for k, v in self.fit_info.items() if k != "train_sessions"},
                    "heuristic_direction": heuristic_direction, "state_hash": (snapshot or {}).get("state_hash"), "layers_not_invoked": LAYERS_NOT_INVOKED,
                    "mandatory_inputs": {"variance_model": self.variance is not None, "regime_model": self.regime is not None, "snapshot": snapshot is not None,
                                         "forecast": bool(forecast), "book_summary": book_summary is not None, "quotes": bool(quotes)}}
        out = {"decision": "WAIT", "why": None, "proposal": None, "trace": tr, "rule_id": FUNNEL_RULE_ID}

        def wait(why):
            out["why"] = why; tr["final"] = {"decision": "WAIT", "why": why}; return out

        # --- mandatory inputs (FULL mode): nothing is substituted
        if not self.ready:
            return wait("PRIME_ABSTAIN: UNSUPPORTED_STATE: %s" % self.fit_info.get("status"))
        if snapshot is None or not isinstance(snapshot, dict):
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: snapshot")
        if book_summary is None or not isinstance(book_summary, dict) or "integrity_problems" not in book_summary:
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: book summary (with integrity_problems) is mandatory; nothing is substituted")
        if book_summary.get("integrity_problems"):
            return wait("PRIME_ABSTAIN: BOOK_INTEGRITY: %s" % list(book_summary["integrity_problems"])[:3])
        if not isinstance(spot, (int, float)) or isinstance(spot, bool) or not spot > 0:
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: spot %r" % (spot,))
        loc = (forecast or {}).get("location")
        if not isinstance(loc, (int, float)) or not math.isfinite(loc):
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: forecast location %r" % (loc,))
        prefix = [float(r) for r in prefix_returns]
        # --- situation / regime (filtered, causal); FULL mode requires it
        reg = None
        if self.regime is not None:
            if len(prefix) < MIN_PREFIX_BARS:
                if self.mode == "FULL":
                    return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: regime filter needs >= %d prefix bars, have %d" % (MIN_PREFIX_BARS, len(prefix)))
            else:
                try:
                    reg = self.regime.filtered(prefix[-390:], cutoff_epoch=as_of)
                except ModelRefused as e:
                    if self.mode == "FULL":
                        return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: regime filter refused (%s)" % str(e)[:100])
                    tr["regime_error"] = str(e)[:120]
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
                        if reg else {"missing": "REGIME_NOT_USED: mode %s (%s)" % (self.mode, tr.get("regime_error") or self.fit_info.get("regime") or "no prefix")})
        # --- variance rolled forward over the prefix (no refit)
        try:
            gf = self.variance.forecast(cutoff_epoch=as_of, created_epoch=as_of, horizon_bars=15, recent=prefix)
        except ModelRefused as e:
            return wait("PRIME_ABSTAIN: UNSUPPORTED_STATE: variance forecast refused (%s)" % str(e)[:120])
        h1 = float(gf.meta["next_bar_variance"])
        tr["variance"] = {"model": self.variance_kind, "next_bar_variance": h1, "integrated_15": gf.meta["integrated_variance"],
                          "artifact_digest": gf.artifact_digest, "prefix_bars": len(prefix), "innovations": "STUDENT_T" if self.garch is not None else "GAUSSIAN",
                          "clock": "MARKET time (one-minute regular-hours bars)"}
        # --- quotes: validated BEFORE anything reads a price (timestamp present and fresh, sides, sizes, consistency)
        valid, rejected = {}, {}
        for key, q in quotes.items():
            try:
                sq = sanitize_quote(q, now=as_of, max_age_s=self.quote_max_age_s)
            except PricingRefused as e:
                rejected[str(key)] = str(e); continue
            valid[(key[0], float(key[1]), key[2])] = {**sq, "timestamp_epoch": q["timestamp_epoch"]}
        tr["quotes"] = {"received": len(quotes), "valid": len(valid), "rejected": len(rejected), "max_age_s": self.quote_max_age_s,
                        "rejection_reasons": dict(sorted(((k, v) for k, v in rejected.items()), key=lambda kv: kv[0])[:12])}
        if not valid:
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: no valid quote (%d rejected: %s)" % (len(rejected), sorted(set(rejected.values()))[:3]))
        # --- market-implied state on CALENDAR time from timestamps: expiry = 16:00 ET on the expiration date
        today = datetime.fromtimestamp(as_of, tz=timezone.utc).date()
        exps = sorted({e for (e, _k, _r) in valid if (datetime.fromisoformat(e).date() - today).days >= DTE_MIN_DAYS})
        if not exps:
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: no valid quote at an expiry with DTE >= %d" % DTE_MIN_DAYS)
        exp = exps[0]
        expiry_epoch = datetime.fromisoformat(exp + "T16:00:00").replace(tzinfo=ET).timestamp()
        T_entry = (expiry_epoch - as_of) / CALENDAR_YEAR_S
        exit_epoch = as_of + 900.0
        T_exit = (expiry_epoch - exit_epoch) / CALENDAR_YEAR_S
        if T_exit <= 0:
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: expiry inside the horizon")
        trading_minutes_to_expiry = max(1.0, (expiry_epoch - as_of) / 86400.0 * (252.0 / 365.0) * 390.0)
        strikes = sorted({k for (e, k, _r) in valid if e == exp})
        atm = min(strikes, key=lambda k: (abs(k - spot), k))
        ivs, iv_detail = [], {}
        for right in ("CALL", "PUT"):
            q = valid.get((exp, atm, right))
            if q is None:
                iv_detail[right] = "NO_VALID_QUOTE"; continue
            if not q["usable_for_iv"]:
                iv_detail[right] = "NO_BID"; continue
            try:
                r = implied_vol(price=q["mid"], S=spot, K=atm, T=T_entry, right=right)
                ivs.append(r["iv"]); iv_detail[right] = r["iv"]
            except PricingRefused as e:
                iv_detail[right] = "REFUSED: %s" % str(e)[:80]
        if not ivs:
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: ATM implied vol not identified from VALID quotes (%s)" % iv_detail)
        iv0 = float(np.mean(ivs))
        qa = valid.get((exp, atm, "CALL")) or valid.get((exp, atm, "PUT"))
        spread_bps0 = 1e4 * qa["spread"] / qa["mid"] if qa["mid"] > 0 else 0.0
        physical_var_15 = float(gf.meta["integrated_variance"])
        tr["implied"] = {"expiry": exp, "expiry_epoch": expiry_epoch, "T_entry_years": T_entry, "T_exit_years": T_exit, "atm_strike": atm, "iv0": iv0,
                         "by_right": iv_detail, "spread_bps0": spread_bps0, "method": "BSM inversion on the ATM mid of VALID quotes, EUROPEAN_APPROX, r=q=0",
                         "time_conventions": {"expiry_decay": "CALENDAR seconds / (365 d) from timestamps; exit = as_of + 900 s",
                                              "variance": "MARKET minutes (bars)", "trading_minutes_to_expiry": trading_minutes_to_expiry},
                         "physical_vs_implied": EW.physical_vs_implied(physical_var_15m=physical_var_15, implied_iv_annual=iv0, T_years=T_entry,
                                                                       trading_minutes_to_expiry=trading_minutes_to_expiry)}
        # --- multiverse: conditional joint simulation; the FIRST simulated bar uses EXACTLY next_bar_variance (one state convention)
        regime_cfg = None
        if reg and not reg["abstain"]:
            sig = self.regime.p["sigma"]; base_var = sum(p * s * s for p, s in zip(reg["probabilities"], sig))
            if base_var > 0:
                regime_cfg = {"probabilities": reg["probabilities"], "variance_multipliers": [s * s / base_var for s in sig]}
        if self.garch is not None:
            vm = {"kind": "GARCH", **{k: float(self.garch.p[k]) for k in ("omega", "alpha", "beta", "gamma")}, "h_next": h1}
            nu = self.garch.p["nu"]
        else:
            vm, nu = {"kind": "FLAT", "h": h1}, None
        seed = (self.seed * 100003 + int(as_of) % 100003 + self.decisions) % (2 ** 31)

        def simulate(cap):
            sim = ConditionalSimulator(S0=float(spot), variance_model=vm, nu=nu, iv0=iv0, spread_bps0=spread_bps0, regime=regime_cfg,
                                       cutoff_epoch=as_of, drift_per_bar=float(loc) / 15.0, tail_cap_sd=cap)
            return sim.simulate(horizon_bars=15, n_paths=self.n_paths, seed=seed)

        try:
            paths = simulate(self.tail_cap_sd)
        except SimulatorRefused as e:
            return wait("PRIME_ABSTAIN: UNSUPPORTED_STATE: simulator refused (%s)" % e)
        assert float(paths["h_next"]) == h1, "variance handoff: simulator first-bar variance must equal next_bar_variance"
        tr["simulation"] = {"parameter_hash": paths["parameter_hash"], "seed": paths["seed"], "n_paths": self.n_paths, "restrictions": paths["restrictions"],
                            "innovations": paths["innovations"], "h_next": paths["h_next"], "first_bar_variance_equals_forecast": True,
                            "mean_log_return": paths["moments"]["mean_log_return"], "var_log_return": paths["moments"]["var_log_return"],
                            "se_mean": paths["sampling_error"]["se_mean"], "regime_mixture": regime_cfg is not None,
                            "p_return_gt_zero": float(np.mean(np.log(paths["S"][:, -1] / paths["S"][:, 0]) > 0))}
        # --- expression war over the eligible set (WAIT + nearest-ATM +/- k strikes, both rights) on the COMMON paths
        i_atm = strikes.index(atm)
        eligible = strikes[max(0, i_atm - self.k_side): i_atm + self.k_side + 1]
        cands, T_by, key_by_label = [], {}, {}
        for k in eligible:
            for right in ("CALL", "PUT"):
                q = valid.get((exp, k, right))
                if q is None:
                    continue
                label = "%s|%s|%s|%s" % (symbol, exp, k, right)
                cands.append({"label": label, "instrument": instrument(symbol=symbol, expiration=exp, strike=k, right=right, exercise="AMERICAN", settlement="PHYSICAL"),
                              "quote": {"bid": q["bid"], "ask": q["ask"], "bid_size": q["bid_size"], "ask_size": q["ask_size"], "timestamp_epoch": q["timestamp_epoch"]}})
                T_by[label] = T_entry; key_by_label[label] = (exp, k, right)
        fe, fx = fee_schedule.entry(1)["total"], fee_schedule.exit(1)["total"]

        def compare(p):
            return EW.compare(paths=p, candidates=cands, T_years_by_contract=T_by, horizon_years=HORIZON_15M_CALENDAR_YEARS, r=0.0, fees_entry=fe, fees_exit=fx,
                              now=as_of, quote_max_age_s=self.quote_max_age_s, iv_shifts=(-0.1, 0.0, 0.1))

        cmp = compare(paths)
        # --- risk envelope INSIDE the candidate set (PRELIMINARY AFFORDABILITY; kernel approval is at intent commit)
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
        tr["expression_war"] = {"n_candidates": len(cands), "eligible_strikes": eligible, "table": table, "fees": {"entry": fe, "exit": fx},
                                "expected_value_note": cmp["expected_value_note"], "selection_authority": FUNNEL_RULE_ID, "common_paths": cmp["common_paths"],
                                "rejected_by_risk_envelope": n_env_rejected, "horizon_years_calendar": HORIZON_15M_CALENDAR_YEARS,
                                "exit_T_identity": abs((T_entry - HORIZON_15M_CALENDAR_YEARS) - T_exit) < 1e-12}
        elig = [c for c in cmp["candidates"] if c["status"] == "ELIGIBLE" and c["label"] != "WAIT"]
        if not elig:
            whys = [c.get("why") for c in cmp["candidates"] if c["label"] != "WAIT"]
            return wait("NO_ELIGIBLE_CANDIDATE: every contract rejected (%d by the risk envelope): %s" % (n_env_rejected, whys[:2]))
        best = max(elig, key=lambda c: c["expected_net_pnl"])
        # --- tail sensitivity: the selected candidate's expected value under other truncation caps (an explicit model choice, checked)
        sens = {}
        if nu is not None:
            for cap in TAIL_SENSITIVITY_CAPS:
                try:
                    c2 = next((c for c in compare(simulate(cap))["candidates"] if c["label"] == best["label"]), None)
                    sens[str(cap)] = c2.get("expected_net_pnl") if c2 else None
                except SimulatorRefused as e:
                    sens[str(cap)] = "REFUSED: %s" % e
        tr["tail_sensitivity"] = {"cap_sd_used": self.tail_cap_sd, "selected_expected_net_pnl": best["expected_net_pnl"], "by_cap_sd": sens,
                                  "note": "expected payoffs exist only because the t innovations are truncated; sensitivity to the cap is reported, not hidden"}
        # --- PRIME supervision on the best FEASIBLE candidate
        env = envelope_for(reference_ask=best["entry_ask"], quantity=1)
        affordability = {"approved": True, "kind": "PRELIMINARY_AFFORDABILITY: price envelope only; kernel approval happens at intent commit in the boundary",
                         "envelope": {k: env.get(k) for k in ("max_entry_price", "feasible", "why_infeasible")}}
        fo = ForecastObject(model_id="FUNNEL:%s+%s" % (forecast.get("model_id"), self.variance_kind.split(" ")[0]), artifact_digest=str(forecast.get("params_hash")),
                            horizon_minutes=15, input_cutoff_epoch=as_of - 60, created_epoch=as_of, supplies=("mean", "variance", "density"), mean=float(loc),
                            variance=paths["moments"]["var_log_return"],
                            density={"family": "GAUSSIAN", "location": float(loc), "variance": paths["moments"]["var_log_return"]},
                            meta={"p_return_gt_zero": tr["simulation"]["p_return_gt_zero"], "p_meaning": "P(15-minute log return > 0) under the simulated joint paths",
                                  "model_disagreement_ratio": _disagreement(physical_var_15, forecast)})
        sup = supervise(forecast=fo, snapshot=snapshot, comparison=cmp, risk_decision=affordability, book_summary=book_summary,
                        regime=reg, candidate_label=best["label"], policy=self.policy)
        tr["prime"] = {"decision": sup["decision"], "reasons": sup["reasons"], "confidence": sup["confidence"], "policy": self.policy.describe(),
                       "policy_note": FUNNEL_POLICY_NOTE, "candidate": best["label"], "affordability": affordability,
                       "kernel_approval": "NOT_HERE: performed at intent commit (RISK_LIMIT_AT_COMMIT) by the recording boundary",
                       "regime_supplied": reg is not None, "book_summary_supplied": True}
        if sup["decision"] != "ACT":
            return wait("PRIME_ABSTAIN: " + "; ".join(sup["reasons"])[:240])
        exp_, k_, right_ = key_by_label[best["label"]]
        q = valid[(exp_, k_, right_)]
        out.update(decision="TRADE", why="FUNNEL_SELECTED: %s expected net %.2f (model-conditional, IV_FIXED, truncated-t)" % (best["label"], best["expected_net_pnl"]),
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
