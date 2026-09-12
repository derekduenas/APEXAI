"""JOINT_FUNNEL_V1 — the R4 engine against contract blob 902256e3 (§2–§5).

Pure: no ledger, no network, no wall clock. One decision:

    market state (§1) -> pre-generated randomness (§3.2) -> per-comparator option-state paths (§2.4)
    -> anchored pricing and path accounting under ASSUME_AVAILABLE (§2.5, §3) -> ranking
    -> JOINT_DECISION_RULE_V1 with the selected-only MODELLED_SIZE veto (§5.3) -> proposal or WAIT

Selection is BY NAME only; `PILOT_RULE_V1` remains the operational default."""
from __future__ import annotations

import math

import numpy as np

from apex.decision_wb.supervision import SupervisionPolicy, supervise
from apex.multiverse_wb.simulator import ConditionalSimulator, SimulatorRefused
from apex.options_pilot.risk_authority import envelope_for
from apex.worldmodel_wb.contracts import ForecastObject, digest

from . import accounting as ACC
from . import comparators as CMP
from . import decision_rule as DR
from . import sampler as SMP
from .state import StateRefused, predictor_vector

JOINT_RULE_ID = ("FULL_FUNNEL_V1/JOINT_FUNNEL_V1: joint 15-minute forecast of underlying, ATM implied vol, skew, "
                 "spread and size; anchored slice pricing; two accounting scenarios; rank without size then a "
                 "selected-only veto; contract blob 902256e3")
CONTRACT_PIN = "902256e3c3c5025a450a4bb607410933bb0c4b25"
JOINT_POLICY = SupervisionPolicy(max_bar_age_s=120.0, max_disagreement_ratio=1.0, max_spread_rel=0.15,
                                 min_expected_net_pnl=0.0, require_value_established=False)
SEPARATION_STATEMENT = ("a model-conditioned value ranking is not a calibrated probability, not a fill probability, "
                        "and not evidence of positive expectancy")
N_PATHS_DEFAULT = 4000


class JointEngine:
    def __init__(self, *, n_paths: int = N_PATHS_DEFAULT, seed: int = 11, strikes_each_side: int = 4,
                 policy: SupervisionPolicy = JOINT_POLICY, comparator: str = "JOINT"):
        if comparator not in CMP.TABLE:
            raise ValueError("COMPARATOR_UNKNOWN: %r" % (comparator,))
        self.n_paths, self.seed, self.k_side, self.policy, self.comparator = n_paths, seed, strikes_each_side, policy, comparator
        self.fitted: dict | None = None
        self.fit_info: dict = {"status": "NOT_FITTED"}
        self.decisions = 0

    # ------------------------------------------------------------ fitted parameters (walk-forward; caller-timed)
    def attach(self, fitted: dict, *, permission: dict) -> dict:
        self.fitted = fitted
        self.fit_info = {"status": "READY", "n": fitted["n"], "cutoff_epoch": fitted["cutoff_epoch"],
                         "parameters_digest": digest({"A": np.asarray(fitted["A"]).round(12).tolist(),
                                                      "Sigma": np.asarray(fitted["Sigma"]).round(12).tolist()}),
                         "orientation": fitted["orientation"], "permission": permission,
                         "sigma_eigenvalues": fitted["sigma_eigenvalues"], "census": fitted.get("census", {})}
        return self.fit_info

    @property
    def ready(self) -> bool:
        return self.fitted is not None

    def describe(self) -> dict:
        return {"rule_id": JOINT_RULE_ID, "contract_pin": CONTRACT_PIN, "comparator": self.comparator,
                "n_paths": self.n_paths, "seed": self.seed, "strikes_each_side": self.k_side,
                "policy": self.policy.describe(), "fit": self.fit_info, "comparators": CMP.describe()}

    def separation(self) -> dict:
        return {"forecast_model": {"id": "JOINT-V1", "parameters_digest": self.fit_info.get("parameters_digest"),
                                   "fit_cutoff": self.fit_info.get("cutoff_epoch"), "produces": "future STATES"},
                "pricing_model": {"id": "ANCHORED_SLICE_BSM_V1", "digest": digest({"anchor": "K_atm", "formula": "log iv_K = x_iv + x_sk log(K/K_atm)",
                                                                                   "guards": [ACC.LOG_IV_MIN, ACC.LOG_IV_MAX]}),
                                  "produces": "price of a contract GIVEN a state"},
                "statement": SEPARATION_STATEMENT}

    # ------------------------------------------------------------ one decision
    def decide(self, *, market_state: dict, variance_state: dict, v_hat: float, nu: float | None, drift_per_bar: float,
               fee_schedule, book_summary: dict | None, forecast: dict | None = None, prime: bool = True) -> dict:
        self.decisions += 1
        ms = market_state
        tr = {"engine": "JOINT_FUNNEL_V1", "contract_pin": CONTRACT_PIN, "comparator": self.comparator,
              "separation": self.separation(), "fit": self.fit_info, "state_hash": ms.get("state_hash"),
              "market_state": {k: ms.get(k) for k in ("t_d", "x_iv", "x_sk", "x_sp", "x_sz", "iv_atm", "iv_source",
                                                      "spread_rel_atm", "size_atm", "T_entry_years", "T_exit_years",
                                                      "spot_async_gap", "quotes", "skew_quality")},
              "identity": ms["identity"]}
        out = {"decision": "WAIT", "why": None, "proposal": None, "trace": tr, "rule_id": JOINT_RULE_ID}

        def wait(why):
            out["why"] = why; tr["final"] = {"decision": "WAIT", "why": why}; return out

        if not self.ready:
            return wait("PRIME_ABSTAIN: UNSUPPORTED_STATE: %s" % self.fit_info.get("status"))
        if book_summary is None or "integrity_problems" not in (book_summary or {}):
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: book summary is mandatory")
        if book_summary.get("integrity_problems"):
            return wait("PRIME_ABSTAIN: BOOK_INTEGRITY: %s" % list(book_summary["integrity_problems"])[:3])
        if ms.get("x_sk") is None:
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: skew MISSING (%s); the joint state is incomplete" % ms.get("skew_why"))

        # --- underlying paths: 17 bars (15 horizon + 2 execution extension), pre-generated before any candidate
        t_d = ms["t_d"]
        S_0 = ms["S_0"]["value"]
        seed = (self.seed * 100003 + int(t_d) % 100003 + self.decisions) % (2 ** 31)
        try:
            sim = ConditionalSimulator(S0=float(S_0), variance_model=variance_state, nu=nu, iv0=ms["iv_atm"],
                                       spread_bps0=max(1e-6, 1e4 * ms["spread_rel_atm"]), cutoff_epoch=t_d,
                                       drift_per_bar=float(drift_per_bar))
            paths = sim.simulate(horizon_bars=17, n_paths=self.n_paths, seed=seed)
        except SimulatorRefused as e:
            return wait("PRIME_ABSTAIN: UNSUPPORTED_STATE: underlying simulator refused (%s)" % e)
        S = paths["S"]
        lr = np.diff(np.log(S), axis=1)
        r = lr[:, :15].sum(axis=1)
        q = (lr[:, :15] ** 2).sum(axis=1)
        r_ext = lr[:, 15:].sum(axis=1)
        q_ext = (lr[:, 15:] ** 2).sum(axis=1)

        # --- predictor domain BEFORE any log/sqrt
        if not isinstance(v_hat, (int, float)) or isinstance(v_hat, bool) or not math.isfinite(v_hat) or v_hat <= 0:
            return wait("PRIME_ABSTAIN: SCALE_VARIANCE_INVALID: %r (no path simulated for pricing)" % (v_hat,))
        bad_q = ~np.isfinite(q) | (q <= 0)
        tr["predictors"] = {"v_hat": v_hat, "invalid_q_paths": int(bad_q.sum())}
        if bad_q.any():
            return wait("REJECTED: PREDICTOR_INVALID_PATH_PRESENT: %d path(s), first index %d"
                        % (int(bad_q.sum()), int(np.where(bad_q)[0][0])))
        Zp = np.column_stack([np.ones(self.n_paths), r, np.abs(r) / math.sqrt(v_hat), np.log(q) - math.log(v_hat)])
        v_hat_ext = v_hat * (2.0 / 15.0)
        bad_qe = ~np.isfinite(q_ext) | (q_ext <= 0)
        Zx = np.column_stack([np.ones(self.n_paths), r_ext, np.abs(r_ext) / math.sqrt(v_hat_ext),
                              np.log(np.where(bad_qe, 1.0, q_ext)) - math.log(v_hat_ext)])

        # --- option-state randomness, pre-generated (candidate order cannot change it)
        pre = SMP.pregenerate(sigma=np.asarray(self.fitted["Sigma"]), n_paths=self.n_paths, seed=seed ^ 0x5EED)
        A = np.asarray(self.fitted["A"])
        mean_dx = (A @ Zp.T).T
        eps = SMP.innovations(pre, comparator=self.comparator, tag="horizon")
        active = {"MATCHED_FROZEN": (False, False), "C_IV": (True, False), "C_IVSK": (True, False),
                  "C_EXEC": (False, True), "C_DIAG": (True, True), "JOINT": (True, True)}[self.comparator]
        mask = np.array([1.0 if active[0] else 0.0, 1.0 if (active[0] and self.comparator != "C_IV") else 0.0,
                         1.0 if active[1] else 0.0, 1.0 if active[1] else 0.0])
        dx = mean_dx * mask + eps
        st_h = {"x_iv": ms["x_iv"] + dx[:, 0], "x_sk": ms["x_sk"] + dx[:, 1],
                "x_sp": ms["x_sp"] + dx[:, 2], "x_sz": ms["x_sz"] + dx[:, 3]}
        eps_x = SMP.innovations(pre, comparator=self.comparator, tag="extension")
        st_x = ACC.extension_state(A=A * mask[:, None], z_ext=Zx, eps_ext=eps_x * mask, state0=st_h)
        tr["sampler"] = {"law": "BLOCK_SEQUENTIAL_V1", "seed": pre["seed"], "truncation": pre["truncation"],
                         "compound_label": pre["compound_label"], "M_digest": digest(pre["M"].round(12).tolist()),
                         "C_digest": digest(pre["C"].round(12).tolist()),
                         "population_identities": "Cov(e2_joint)=S22, Cov(e1,e2_joint)=S12 exactly; sample covariance is a diagnostic"}
        tr["underlying"] = {"n_paths": self.n_paths, "seed": seed, "bars": 17, "mean_r": float(r.mean()),
                            "var_r": float(r.var()), "extension_undefined_paths": int(bad_qe.sum()),
                            "restrictions": paths["restrictions"], "innovations": paths["innovations"]}

        # --- candidates from the VALID quotes at the frozen expiry
        ident = ms["identity"]
        valid = ms["valid_quotes"]
        strikes = sorted({k for (e, k, _r) in valid if e == ident["expiration"]})
        if ident["K_atm"] not in strikes:
            return wait("PRIME_ABSTAIN: PREREQUISITE_MISSING: the frozen ATM strike has no valid quote")
        i_atm = strikes.index(ident["K_atm"])
        eligible = strikes[max(0, i_atm - self.k_side): i_atm + self.k_side + 1]
        fe, fx = fee_schedule.entry(1)["total"], fee_schedule.exit(1)["total"]
        census: dict = {}
        ranked, table = [], []

        def evaluate(K, right, policy):
            q_ = valid.get((ident["expiration"], K, right))
            if q_ is None:
                return None, "NO_VALID_QUOTE"
            prim = ACC.price_paths(S=S[:, 15], x_iv=st_h["x_iv"], x_sk=st_h["x_sk"], x_sp=st_h["x_sp"], x_sz=st_h["x_sz"],
                                   K=K, K_atm=ident["K_atm"], right=right, expiry_epoch=ident["expiry_epoch"],
                                   t_eval=t_d + ACC.H_S)
            ext = None
            if not prim.get("unpriceable", np.ones(1, dtype=bool)).any():
                ext = ACC.price_paths(S=S[:, 17], x_iv=st_x["x_iv"], x_sk=st_x["x_sk"], x_sp=st_x["x_sp"], x_sz=st_x["x_sz"],
                                      K=K, K_atm=ident["K_atm"], right=right, expiry_epoch=ident["expiry_epoch"],
                                      t_eval=t_d + ACC.H_S + ACC.W_END_S)
                if bad_qe.any():
                    ext = {"undefined": True}
            acct = ACC.account(primary=prim, extension=ext, entry_ask=q_["ask"], fees_in=fe, fees_out=fx, size_policy=policy)
            return acct, None

        for K in eligible:
            for right in ("CALL", "PUT"):
                label = "%s|%s|%s|%s" % (ms["symbol"], ident["expiration"], K, right)
                q_ = valid.get((ident["expiration"], K, right))
                if q_ is None:
                    census["NO_VALID_QUOTE"] = census.get("NO_VALID_QUOTE", 0) + 1; continue
                env = envelope_for(reference_ask=q_["ask"], quantity=1)
                if not env["feasible"] or q_["ask"] > env["max_entry_price"]:
                    census["RISK_ENVELOPE"] = census.get("RISK_ENVELOPE", 0) + 1
                    table.append({"label": label, "status": "REJECTED", "why": "RISK_ENVELOPE", "entry_ask": q_["ask"]})
                    continue
                acct, why = evaluate(K, right, "ASSUME_AVAILABLE")
                if acct is None or acct.get("refused"):
                    reason = why or acct.get("refused")
                    census[reason] = census.get(reason, 0) + 1
                    table.append({"label": label, "status": "REJECTED", "why": reason, "entry_ask": q_["ask"]})
                    continue
                ranked.append({"label": label, "K": K, "right": right, "quote": q_, "acct": acct})
                table.append({"label": label, "status": "ELIGIBLE", "entry_ask": q_["ask"], "E_sel_rank": acct["E_sel"],
                              "mean_S1": acct["mean_S1"], "mean_S2": acct["mean_S2"], "U": acct["U"],
                              "availability_failure_rate": acct["availability_failure_rate"]})
        ranked.sort(key=lambda c: (-c["acct"]["E_sel"], c["label"]))
        tr["candidates"] = {"n_eligible": len(ranked), "table": table, "census": census,
                            "ranking_policy": "ASSUME_AVAILABLE (size plays no part in ranking)",
                            "fees": {"entry": fe, "exit": fx}}

        def veto_eval(label):
            c = next((x for x in ranked if x["label"] == label), None)
            if c is None:
                return None
            acct, _ = evaluate(c["K"], c["right"], "MODELLED_SIZE")
            return acct

        def prime_fn(label):
            c = next((x for x in ranked if x["label"] == label), None)
            comparison = {"candidates": [{"label": t["label"], "status": t["status"],
                                          "expected_net_pnl": t.get("E_sel_rank"), "entry_ask": t.get("entry_ask"),
                                          "entry_spread_rel": (c["quote"]["spread_rel"] if c and t["label"] == label else None),
                                          "expected_value_established": False, "why": t.get("why")} for t in table],
                          "expected_value_note": "UNESTABLISHED: model-conditional under the declared state law"}
            fo = ForecastObject(model_id="JOINT-V1", artifact_digest=str(self.fit_info.get("parameters_digest")),
                                horizon_minutes=15, input_cutoff_epoch=t_d - 60, created_epoch=t_d,
                                supplies=("mean", "variance", "density"), mean=float(r.mean()), variance=float(r.var()),
                                density={"family": "GAUSSIAN", "location": float(r.mean()), "variance": float(r.var())},
                                meta={"p_return_gt_zero": float(np.mean(r > 0)),
                                      "p_meaning": "P(15-minute log return > 0) under the simulated joint paths",
                                      "model_disagreement_ratio": 0.0})
            snap = {"fields": {"last_bar_age_s": {"value": ms["S_0"]["age_s"], "quality": "VALID"}}}
            return supervise(forecast=fo, snapshot=snap, comparison=comparison,
                             risk_decision={"approved": True, "kind": "PRELIMINARY_AFFORDABILITY"},
                             book_summary=book_summary, regime=None, candidate_label=label, policy=self.policy)

        adverse = self._adverse(ranked[0], evaluate) if ranked else {}
        res = DR.decide(ranked=ranked, veto_eval=veto_eval, comparator=self.comparator, eligibility_census=census,
                        adverse=adverse, prime=(prime_fn if prime else None))
        tr["decision_rule"] = res["trace"]
        if res["decision"] != "TRADE":
            return wait(res["why"])
        best = next(x for x in ranked if x["label"] == res["selected"])
        out.update(decision="TRADE", why=res["why"],
                   proposal={"expression": "LONG_CALL" if best["right"] == "CALL" else "LONG_PUT", "action": "BUY",
                             "contract": {"symbol": ms["symbol"], "expiration": ident["expiration"],
                                          "strike": float(best["K"]), "right": best["right"]},
                             "quantity": 1, "expression_rule": JOINT_RULE_ID, "reference_ask": best["quote"]["ask"],
                             "direction_signal": "LONG" if best["right"] == "CALL" else "SHORT",
                             "expected_net_pnl_model": best["acct"]["E_sel"], "expected_value_established": False})
        tr["selected"] = {"label": best["label"], "E_sel_rank": best["acct"]["E_sel"], "U_rank": best["acct"]["U"],
                          "mean_S1": best["acct"]["mean_S1"], "mean_S2": best["acct"]["mean_S2"],
                          "counters": best["acct"]["counters"], "trace_digest": None}
        tr["final"] = {"decision": "TRADE", "why": res["why"]}
        tr["selected"]["trace_digest"] = digest({k: v for k, v in tr.items() if k != "selected"})
        return out

    def _adverse(self, best: dict, evaluate) -> dict:
        """Rule 3: adverse plausible scenarios only. Component ablations are recorded elsewhere, never gates."""
        base = best["acct"]["E_sel"]
        return {"scenarios": {"BASE": base}, "ablations": {"note": "recorded for attribution, never gates"}}
