"""JOINT_FUNNEL_V1 — the R4 engine against contract blob a0228fac (Amendment A1; §2–§5).

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
from apex.options_pilot.risk_authority import CERTIFIED_PROVENANCE, envelope_for
from apex.worldmodel_wb.contracts import ForecastObject, digest

from . import accounting as ACC
from . import comparators as CMP
from . import decision_rule as DR
from . import sampler as SMP
from . import permissions as PRM
from .state import EXECUTION_MAX_AGE_S, StateRefused, predictor_vector


class AuthorizationRefused(PermissionError):
    pass

JOINT_RULE_ID = ("FULL_FUNNEL_V1/JOINT_FUNNEL_V1: joint 15-minute forecast of underlying, ATM implied vol, skew, "
                 "spread and size; anchored slice pricing; two accounting scenarios; rank without size then a "
                 "selected-only veto; contract blob a0228fac4a2dab4c455c9fc8a41d1378522a27de")
CONTRACT_PIN = "a0228fac4a2dab4c455c9fc8a41d1378522a27de"
ADVERSE_SCENARIOS = ("truncation_q_0.999", "truncation_q_0.99999", "spread_innovation_x1.5",
                     "extension_innovation_x1.5", "a_iv_minus_1_cluster_robust_se", "size_floor_removed")
JOINT_POLICY = SupervisionPolicy(max_bar_age_s=120.0, max_disagreement_ratio=1.0, max_spread_rel=0.15,
                                 min_expected_net_pnl=0.0, require_value_established=False)
SEPARATION_STATEMENT = ("a model-conditioned value ranking is not a calibrated probability, not a fill probability, "
                        "and not evidence of positive expectancy")
N_PATHS_DEFAULT = 4000


def _ensemble_density(sample: np.ndarray, paths: dict, comparator: str) -> dict:
    """The forecast's density is the SIMULATED ENSEMBLE, declared as such. It is NOT relabelled Gaussian because a
    sample mean and variance happen to exist: the underlying innovations are truncated-t under GARCH and the option
    state adds its own law. Recorded: the family, the empirical quantiles, the ensemble digest and the generating
    restrictions. This is a sample distribution, not a calibrated density and not a fill probability."""
    qs = [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]
    return {"family": "EMPIRICAL_ENSEMBLE", "n": int(len(sample)), "comparator": comparator,
            "quantiles": {str(q): float(np.quantile(sample, q)) for q in qs},
            "mean": float(sample.mean()), "variance": float(sample.var()),
            "ensemble_digest": digest([round(float(x), 12) for x in np.sort(sample)[:: max(1, len(sample) // 64)]]),
            "underlying_innovations": paths.get("innovations"), "restrictions": paths.get("restrictions"),
            "interpretation": ("a SIMULATED SAMPLE distribution under the declared model; it is not a calibrated "
                               "probability, not a fill probability and not evidence of expectancy")}


def _seed_from(base_seed: int, scan_id: str) -> int:
    """Deterministic, order-independent: seed = H(base_seed, scan_id). No mutable counter participates."""
    return int(digest({"base_seed": int(base_seed), "scan_id": scan_id})[:8], 16) % (2 ** 31)


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
    REQUIRED_PERMISSION_FIELDS = ("contract_pin", "dataset_id", "role", "use", "authorization")

    @classmethod
    def validate_permission(cls, permission, *, fitted: dict) -> dict:
        """R4 fitting provenance is CHECKED, not assumed. A truthy dict is not an authorization."""
        if not isinstance(permission, dict):
            raise AuthorizationRefused("PERMISSION_NOT_A_RECORD: %r" % type(permission).__name__)
        missing = [f for f in cls.REQUIRED_PERMISSION_FIELDS if f not in permission]
        if missing:
            raise AuthorizationRefused("PERMISSION_FIELDS_MISSING: %s" % missing)
        if permission["contract_pin"] != CONTRACT_PIN:
            raise AuthorizationRefused("PERMISSION_CONTRACT_PIN_MISMATCH: %r vs %r" % (permission["contract_pin"], CONTRACT_PIN))
        if permission["use"] != "FIT":
            raise AuthorizationRefused("PERMISSION_USE_NOT_FIT: %r" % (permission["use"],))
        if permission["dataset_id"] not in PRM.REGISTRY:
            raise AuthorizationRefused("PERMISSION_DATASET_NOT_REGISTERED: %r" % (permission["dataset_id"],))
        ds = PRM.REGISTRY[permission["dataset_id"]]
        if permission["role"] != ds.role:
            raise AuthorizationRefused("PERMISSION_ROLE_MISMATCH: %r vs registry %r" % (permission["role"], ds.role))
        if ds.role != "SYNTHETIC":
            for f in ("session_range", "fit_cutoff", "evaluation_population"):
                if not permission.get(f):
                    raise AuthorizationRefused("PERMISSION_RUN_FIELDS_MISSING:%s (role approval is not run authorization)" % f)
            if permission["authorization"] != ds.authorization_required:
                raise AuthorizationRefused("PERMISSION_ARTEFACT_MISMATCH: need %r, got %r"
                                           % (ds.authorization_required, permission["authorization"]))
        for f in ("A", "Sigma", "n", "cutoff_epoch", "row_ids"):
            if f not in fitted:
                raise AuthorizationRefused("PARAMETER_PROVENANCE_MISSING:%s" % f)
        if not isinstance(fitted["cutoff_epoch"], (int, float)) or not math.isfinite(fitted["cutoff_epoch"]):
            raise AuthorizationRefused("PARAMETER_PROVENANCE_INVALID: fit_cutoff %r" % (fitted["cutoff_epoch"],))
        return {**permission, "validated": True, "n_training_rows": fitted["n"], "fit_cutoff": fitted["cutoff_epoch"]}

    def attach(self, fitted: dict, *, permission: dict) -> dict:
        permission = self.validate_permission(permission, fitted=fitted)
        self.fitted = fitted
        self.fit_info = {"status": "READY", "n": fitted["n"], "cutoff_epoch": fitted["cutoff_epoch"],
                         "parameters_digest": digest({"A": np.asarray(fitted["A"]).round(12).tolist(),
                                                      "Sigma": np.asarray(fitted["Sigma"]).round(12).tolist()}),
                         "orientation": fitted["orientation"], "permission": permission,
                         "sigma_eigenvalues": fitted["sigma_eigenvalues"], "census": fitted.get("census", {})}
        try:                                                     # CR1 SE of the IV equation's intercept (rule 3)
            from . import inference as INF
            cl = INF._cluster_index(fitted["sessions"])
            self.fit_info["se_a_iv_intercept"] = INF.cr1_se(fitted["Z"], fitted["E"][:, 0], cl, 0)
            self.fit_info["G_clusters"] = len(cl)
        except Exception as e:                                   # noqa: BLE001 - recorded, and rule 3 then refuses
            self.fit_info["se_a_iv_intercept"] = None
            self.fit_info["se_a_iv_intercept_why"] = "%s: %s" % (type(e).__name__, str(e)[:100])
        return self.fit_info

    @property
    def ready(self) -> bool:
        return self.fitted is not None

    def describe(self) -> dict:
        return {"rule_id": JOINT_RULE_ID, "contract_pin": CONTRACT_PIN, "comparator": self.comparator,
                "adverse_scenarios_registered": list(ADVERSE_SCENARIOS),
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
               fee_schedule, book_summary: dict | None, scan_id: str, certified_risk_fn=None,
               forecast: dict | None = None, prime: bool = True) -> dict:
        """`scan_id` is the IMMUTABLE decision key: the seed derives from (base seed, scan_id) only, so repeated
        identical scans are bit-identical and call order changes nothing (§6.1 T17)."""
        self.decisions += 1
        if not isinstance(scan_id, str) or not scan_id:
            raise ValueError("SCAN_ID_REQUIRED: the simulation seed must not depend on call order")
        ms = market_state
        tr = {"engine": "JOINT_FUNNEL_V1", "contract_pin": CONTRACT_PIN, "comparator": self.comparator,
              "separation": self.separation(), "fit": self.fit_info, "state_hash": ms.get("state_hash"),
              "scan_id": scan_id,
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
        seed = _seed_from(self.seed, scan_id)
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
        A = np.asarray(self.fitted["A"])
        active = {"MATCHED_FROZEN": (False, False), "C_IV": (True, False), "C_IVSK": (True, False),
                  "C_EXEC": (False, True), "C_DIAG": (True, True), "JOINT": (True, True)}[self.comparator]
        mask = np.array([1.0 if active[0] else 0.0, 1.0 if (active[0] and self.comparator != "C_IV") else 0.0,
                         1.0 if active[1] else 0.0, 1.0 if active[1] else 0.0])

        def build(*, trunc_q=SMP.TRUNCATION_Q, spread_scale=1.0, ext_scale=1.0, a_iv_shift=0.0):
            """State paths under a declared parameterization. Common randomness: the same seed everywhere; a
            different truncation quantile necessarily redraws, which is recorded with the scenario."""
            p = SMP.pregenerate(sigma=np.asarray(self.fitted["Sigma"]), n_paths=self.n_paths, seed=seed ^ 0x5EED,
                                trunc_q=trunc_q)
            eh = SMP.innovations(p, comparator=self.comparator, tag="horizon").copy()
            eh[:, 2] *= spread_scale
            A2 = A.copy()
            A2[0, 0] += a_iv_shift                                    # the IV equation's intercept
            dxh = (A2 @ Zp.T).T * mask + eh
            sh = {"x_iv": ms["x_iv"] + dxh[:, 0], "x_sk": ms["x_sk"] + dxh[:, 1],
                  "x_sp": ms["x_sp"] + dxh[:, 2], "x_sz": ms["x_sz"] + dxh[:, 3]}
            ex = SMP.innovations(p, comparator=self.comparator, tag="extension").copy() * ext_scale
            sx = ACC.extension_state(A=(A2 * mask[:, None]), z_ext=Zx, eps_ext=ex * mask, state0=sh)
            return p, sh, sx

        pre, st_h, st_x = build()
        tr["sampler"] = {"law": "BLOCK_SEQUENTIAL_V1", "seed": pre["seed"], "seed_source": "H(base_seed, scan_id)",
                         "truncation": pre["truncation"], "trunc_q": pre["trunc_q"],
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

        def evaluate(K, right, policy, *, states=None, size_floor=True):
            sh, sx = states or (st_h, st_x)
            q_ = valid.get((ident["expiration"], K, right))
            if q_ is None:
                return None, "NO_VALID_QUOTE"
            prim = ACC.price_paths(S=S[:, 15], x_iv=sh["x_iv"], x_sk=sh["x_sk"], x_sp=sh["x_sp"], x_sz=sh["x_sz"],
                                   K=K, K_atm=ident["K_atm"], right=right, expiry_epoch=ident["expiry_epoch"],
                                   t_eval=t_d + ACC.H_S, size_floor=size_floor)
            ext = None
            if not prim.get("unpriceable", np.ones(1, dtype=bool)).any():
                ext = ACC.price_paths(S=S[:, 17], x_iv=sx["x_iv"], x_sk=sx["x_sk"], x_sp=sx["x_sp"], x_sz=sx["x_sz"],
                                      K=K, K_atm=ident["K_atm"], right=right, expiry_epoch=ident["expiry_epoch"],
                                      t_eval=t_d + ACC.H_S + ACC.W_END_S, size_floor=size_floor)
                if bad_qe.any():
                    ext = {"undefined": True}
            return ACC.account(primary=prim, extension=ext, entry_ask=q_["ask"], fees_in=fe, fees_out=fx, size_policy=policy), None

        for K in eligible:
            for right in ("CALL", "PUT"):
                label = "%s|%s|%s|%s" % (ms["symbol"], ident["expiration"], K, right)
                q_ = valid.get((ident["expiration"], K, right))
                if q_ is None:
                    census["NO_VALID_QUOTE"] = census.get("NO_VALID_QUOTE", 0) + 1; continue
                fresh = {"event_time": q_["timestamp_epoch"], "receipt_time": q_.get("available_time"),
                         "age_s": q_["age_s"], "executable": q_["executable"], "decision": q_["freshness_decision"],
                         "execution_limit_s": EXECUTION_MAX_AGE_S}
                env = envelope_for(reference_ask=q_["ask"], quantity=1)
                if not env["feasible"] or q_["ask"] > env["max_entry_price"]:
                    census["RISK_ENVELOPE"] = census.get("RISK_ENVELOPE", 0) + 1
                    table.append({"label": label, "status": "REJECTED", "why": "RISK_ENVELOPE", "entry_ask": q_["ask"], "freshness": fresh})
                    continue
                acct, why = evaluate(K, right, "ASSUME_AVAILABLE")
                if acct is None or acct.get("refused"):
                    reason = why or acct.get("refused")
                    census[reason] = census.get(reason, 0) + 1
                    table.append({"label": label, "status": "REJECTED", "why": reason, "entry_ask": q_["ask"], "freshness": fresh})
                    continue
                row = {"label": label, "status": "ELIGIBLE", "entry_ask": q_["ask"], "E_sel_rank": acct["E_sel"],
                       "mean_S1": acct["mean_S1"], "mean_S2": acct["mean_S2"], "U": acct["U"],
                       "availability_failure_rate": acct["availability_failure_rate"], "freshness": fresh}
                if not q_["executable"]:
                    # an indicative quote may be RANKED and REPORTED; it may never produce an intent (§1.1 execution age)
                    row["status"] = "INDICATIVE_ONLY"
                    census["EXECUTION_QUOTE_STALE"] = census.get("EXECUTION_QUOTE_STALE", 0) + 1
                    table.append(row); continue
                ranked.append({"label": label, "K": K, "right": right, "quote": q_, "acct": acct})
                table.append(row)
        ranked.sort(key=lambda c: (-c["acct"]["E_sel"], c["label"]))
        tr["candidates"] = {"n_eligible": len(ranked), "table": table, "census": census,
                            "ranking_policy": "ASSUME_AVAILABLE (size plays no part in ranking)",
                            "execution_freshness_rule": "only a quote no older than %.0f s at the decision boundary may produce an intent"
                                                        % EXECUTION_MAX_AGE_S,
                            "fees": {"entry": fe, "exit": fx}}

        def veto_eval(label):
            c = next((x for x in ranked if x["label"] == label), None)
            if c is None:
                return None
            acct, _ = evaluate(c["K"], c["right"], "MODELLED_SIZE")
            return acct

        # --- certified risk: supplied by the BOUNDARY, never asserted here (§5.3 rule 5 / PRIME input)
        def risk_for(label):
            c = next((x for x in ranked if x["label"] == label), None)
            if c is None:
                return {"approved": False, "why": "CANDIDATE_NOT_FOUND"}
            if certified_risk_fn is None:
                return None
            proposal = {"expression": "LONG_CALL" if c["right"] == "CALL" else "LONG_PUT",
                        "contract": {"symbol": ms["symbol"], "expiration": ident["expiration"],
                                     "strike": float(c["K"]), "right": c["right"]},
                        "quantity": 1, "reference_ask": c["quote"]["ask"]}
            got = certified_risk_fn(proposal)
            if not isinstance(got, dict):
                return {"approved": False, "why": "RISK_DECISION_MALFORMED"}
            if got.get("risk_provenance") != CERTIFIED_PROVENANCE or not got.get("authority_id"):
                return {"approved": False, "why": "RISK_DECISION_NOT_CERTIFIED: provenance %r authority %r"
                                                  % (got.get("risk_provenance"), got.get("authority_id"))}
            return got

        def prime_fn(label):
            risk = risk_for(label)
            if risk is None:
                return {"decision": "ABSTAIN", "reasons": ["PREREQUISITE_MISSING: no certified risk decision was supplied; "
                                                           "the engine does not attest its own risk approval"], "confidence": None}
            if not risk.get("approved"):
                return {"decision": "ABSTAIN", "reasons": ["RISK_LIMIT: %s" % (risk.get("why") or "certified authority refused")],
                        "confidence": None, "risk": {k: risk.get(k) for k in ("risk_provenance", "authority_id", "why", "approved")}}
            comparison = {"candidates": [{"label": t["label"], "status": ("ELIGIBLE" if t["status"] == "ELIGIBLE" else "REJECTED"),
                                          "expected_net_pnl": t.get("E_sel_rank"), "entry_ask": t.get("entry_ask"),
                                          "entry_spread_rel": None, "expected_value_established": False,
                                          "why": t.get("why")} for t in table],
                          "expected_value_note": "UNESTABLISHED: model-conditional under the declared state law"}
            sample = np.log(S[:, 15] / S[:, 0])
            fo = ForecastObject(model_id="JOINT-V1", artifact_digest=str(self.fit_info.get("parameters_digest")),
                                horizon_minutes=15, input_cutoff_epoch=t_d - 60, created_epoch=t_d,
                                supplies=("mean", "variance", "density"), mean=float(sample.mean()),
                                variance=float(sample.var()), density=_ensemble_density(sample, paths, self.comparator),
                                meta={"p_return_gt_zero": float(np.mean(sample > 0)),
                                      "p_meaning": "empirical frequency in the SIMULATED ensemble; not a calibrated probability",
                                      "model_disagreement_ratio": 0.0})
            snap = {"fields": {"last_bar_age_s": {"value": ms["S_0"]["age_s"], "quality": "VALID"}}}
            out_ = supervise(forecast=fo, snapshot=snap, comparison=comparison, risk_decision=risk,
                             book_summary=book_summary, regime=None, candidate_label=label, policy=self.policy)
            out_["risk"] = {k: risk.get(k) for k in ("risk_provenance", "authority_id", "approved")}
            return out_

        adverse = self._adverse(ranked[0], evaluate, build) if ranked else {}
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
                             "expected_net_pnl_model": best["acct"]["E_sel"], "expected_value_established": False,
                             "contract_pin": CONTRACT_PIN})
        tr["selected"] = {"label": best["label"], "E_sel_rank": best["acct"]["E_sel"], "U_rank": best["acct"]["U"],
                          "mean_S1": best["acct"]["mean_S1"], "mean_S2": best["acct"]["mean_S2"],
                          "counters": best["acct"]["counters"], "freshness": next(t["freshness"] for t in table if t["label"] == best["label"]),
                          "trace_digest": None}
        tr["final"] = {"decision": "TRADE", "why": res["why"]}
        tr["selected"]["trace_digest"] = digest({k: v for k, v in tr.items() if k != "selected"})
        return out

    def _adverse(self, best: dict, evaluate, build) -> dict:
        """Rule 3: EVERY registered adverse scenario, each independently evaluated on the selected candidate and
        recorded with its exact parameters. A BASE-only record is forbidden; the gate reads these values."""
        right = best["right"]
        se_iv = self.fit_info.get("se_a_iv_intercept")
        shift = None
        if se_iv is not None:
            shift = -se_iv if right == "CALL" else +se_iv          # against the position
        out = {"scenarios": {}, "parameters": {}, "ablations": {"note": "recorded for attribution, never gates"}}

        def val(name, params, *, states=None, policy="ASSUME_AVAILABLE", size_floor=True):
            acct, why = evaluate(best["K"], right, policy, states=states, size_floor=size_floor)
            out["parameters"][name] = params
            out["scenarios"][name] = (None if (acct is None or acct.get("refused")) else acct["E_sel"])
            if acct is not None and acct.get("refused"):
                out["parameters"][name] = {**params, "refused": acct["refused"]}

        val("BASE", {"note": "the ranking value, recorded for comparison"})

        # THE REGISTRY DRIVES THE EVALUATION. Each name in ADVERSE_SCENARIOS maps to exactly one builder here;
        # a registered name with no builder is a registry-integrity failure (never silently skipped), and a builder
        # that is not registered is never run. One list, one edit site.
        def _trunc(q):
            def run(name):
                _, sh, sx = build(trunc_q=q)
                val(name, {"trunc_q": q, "redraw": "a different acceptance region necessarily redraws; declared"}, states=(sh, sx))
            return run

        def _spread(name):
            _, sh, sx = build(spread_scale=1.5)
            val(name, {"spread_innovation_scale": 1.5}, states=(sh, sx))

        def _ext(name):
            _, sh, sx = build(ext_scale=1.5)
            val(name, {"extension_innovation_scale": 1.5}, states=(sh, sx))

        def _a_iv(name):
            if shift is None:
                out["scenarios"][name] = None
                out["parameters"][name] = {"unavailable": "no cluster-robust SE attached to the fit"}
                return
            _, sh, sx = build(a_iv_shift=shift)
            val(name, {"cluster_robust_se": se_iv, "shift": shift, "direction": "against the position"}, states=(sh, sx))

        def _size_floor(name):
            val(name, {"size_policy": "MODELLED_SIZE", "size_floor": False,
                       "rule": "a negative implied size means UNAVAILABLE, never a negative executable size"},
                policy="MODELLED_SIZE", size_floor=False)

        builders = {"truncation_q_0.999": _trunc(0.999), "truncation_q_0.99999": _trunc(0.99999),
                    "spread_innovation_x1.5": _spread, "extension_innovation_x1.5": _ext,
                    "a_iv_minus_1_cluster_robust_se": _a_iv, "size_floor_removed": _size_floor}
        for name in ADVERSE_SCENARIOS:
            if name not in builders:
                raise RuntimeError("ADVERSE_REGISTRY_INTEGRITY: %r is registered but has no builder" % (name,))
            builders[name](name)
        missing = [n for n in ADVERSE_SCENARIOS if n not in out["scenarios"]]
        out["registered"] = list(ADVERSE_SCENARIOS)
        out["complete"] = not missing
        if missing:
            out["scenarios"]["REGISTRY_INCOMPLETE"] = None                # a missing scenario fails the gate
            out["missing"] = missing
        return out
