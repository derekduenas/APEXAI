"""WORLD FOUNDRY — a triangulated multiverse, never one oracle.

Phase 4. Five world classes, each keeping its identity forever:

    EMPIRICAL_ANALOG    reality's own afternoons -- the anchor
    CAUSAL_RESAMPLED    reality's statistics, recombined
    LEARNED_GENERATIVE  a fitted conditional model's samples
    ADVERSARIAL_STRESS  declared degradations, not forecasts
    EXTREME_TAIL_STRESS rare-but-real shapes, deliberately oversampled

WHY TRIANGULATION IS THE POINT. A convincing generator is the most
dangerous object a research system can own: it will happily produce ten
thousand beautiful worlds that agree with each other and with nothing
else. Mixing classes without retaining identity would let a model's
private fantasies quietly outvote history. So class membership rides on
every branch, results are reported per class, and a candidate that
survives only in generated worlds is flagged rather than promoted.

ARCHITECTURE JUSTIFICATION (Phase 4C). The learned generator is a
conditional state-space model -- regime-conditioned AR(1) drift with
GARCH-like volatility clustering and empirical residual resampling --
NOT a transformer or diffusion model. That is a data-driven choice, not
a limitation: with a few thousand sessions, a high-capacity sequence
model memorizes, and a memorizing generator is a very expensive way to
resample history while believing you have invented new worlds. The
memorization test below exists to catch exactly that, and the simple
model is chosen partly because it can pass it.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass, field

from apex.edgeforge.multiverse import WorldBranch

NOT_ESTIMABLE = "NOT_ESTIMABLE"

WORLD_CLASSES = ("EMPIRICAL_ANALOG", "CAUSAL_RESAMPLED",
                 "LEARNED_GENERATIVE", "ADVERSARIAL_STRESS",
                 "EXTREME_TAIL_STRESS")

# ==================================================================
# WORLD SOURCE AUTHORITY
#
# THE LAW: a source earns the right to SUPPORT an edge separately from
# its ability to GENERATE worlds. CAN_GENERATE = YES does not imply
# CAN_SUPPORT_EDGE = YES.
#
# Without this, the multiverse degenerates into "84 worlds = 84 votes",
# and a source whose path dynamics are wrong buys a candidate more
# credibility simply by producing more paths. World count is not
# evidence count.
#
# The asymmetry is deliberate and is not a bug: a questionable
# simulator MAY kill a candidate when the stress it applies is
# explicitly adversarial, because surviving a harsh unrealistic world
# was never claimed as proof of anything. The same simulator may NOT
# rescue or strengthen a candidate until its path dynamics are shown
# to be credible. Falsification tolerates a pessimistic error;
# support does not tolerate an optimistic one.
WORLD_SOURCE_AUTHORITY = ("UNVALIDATED", "DIAGNOSTIC_ONLY",
                          "FALSIFICATION_ONLY", "EDGE_SUPPORT_ELIGIBLE",
                          "SUSPENDED")

SOURCE_AUTHORITY = {
    "EMPIRICAL_ANALOG": {
        "authority": "EDGE_SUPPORT_ELIGIBLE",
        "why": "reality's own afternoons; the anchor. Its path "
               "dynamics are not modelled, they are what happened",
        "as_of": "2026-08-25"},
    "CAUSAL_RESAMPLED": {
        "authority": "DIAGNOSTIC_ONLY",
        "why": "UNPROVEN, not proven biased. The global comparison "
               "that prompted this downgrade (40.0% favorable vs "
               "reality's 29.6%, right tail +334) turned out to be "
               "REGIME-CONFOUNDED: the resampler was conditioned on "
               "NORMAL while the empirical pool was 33/44 QUIET. "
               "Stratified within NORMAL the right-tail delta is 0.00, "
               "the left tail is milder not harsher (+16.26), and the "
               "median is WORSE than reality (-44.40). So the "
               "asymmetry was largely an artifact of composition. What "
               "remains is n=11 empirical NORMAL afternoons, which "
               "cannot establish credibility in either direction. A "
               "source supports an edge by demonstrating credible "
               "path dynamics, not by failing to be caught",
        "as_of": "2026-08-25",
        "reinstatement": "a regime-matched comparison at adequate n "
                         "showing favorable-excursion structure "
                         "survives the resampling"},
    "LEARNED_GENERATIVE": {
        "authority": "SUSPENDED",
        "why": "conditional fidelity failed: ACF1(|r|) -0.006 against "
               "reality's +0.346 (gap 0.352 on [-1,1]) and mae_median "
               "3.73x deeper. It reproduces unconditional "
               "distributional properties while failing to reproduce "
               "volatility persistence -- a conditional-dynamics "
               "failure, not a calibration nudge",
        "as_of": "2026-08-25",
        "reinstatement": "pass the validation battery; no deadline, "
                         "and permanent suspension is an acceptable "
                         "outcome"},
    "ADVERSARIAL_STRESS": {
        "authority": "FALSIFICATION_ONLY",
        "why": "declared degradations, not forecasts. It may kill; it "
               "may never support. A candidate surviving a stress "
               "world has not been shown to work -- only not to have "
               "died there",
        "as_of": "2026-08-25"},
    "EXTREME_TAIL_STRESS": {
        "authority": "FALSIFICATION_ONLY",
        "why": "deliberately oversampled rare shapes; the sampling is "
               "chosen, so favorable results in it are an artifact of "
               "the choice",
        "as_of": "2026-08-25"},
}

SUPPORT_ELIGIBLE = tuple(
    c for c, v in SOURCE_AUTHORITY.items()
    if v["authority"] == "EDGE_SUPPORT_ELIGIBLE")

LAW_WORLD_COUNT = ("a source's ability to GENERATE worlds is separate "
                   "from its authority to SUPPORT an edge; world count "
                   "is not evidence count")

COMPUTE_LADDER = {"SMOKE": 20, "RESEARCH": 200, "DEEP_RESEARCH": 2000}

GENERATIVE_ELIGIBILITY = ("ELIGIBLE", "UNCALIBRATED", "SUSPENDED",
                          "UNTRAINED")


class FoundryViolation(RuntimeError):
    pass


def _mk(branch_id, parent, path, cls, pedigree, cond="UNCONDITIONED",
        session=None) -> WorldBranch:
    method = ("EMPIRICAL_HISTORICAL_ANALOG"
              if cls == "EMPIRICAL_ANALOG" else "ADVERSARIAL_STRESS")
    b = WorldBranch(branch_id=branch_id, parent_state_hash=parent,
                    hypothesis_condition=cond, generation_method=method,
                    generation_pedigree=f"[{cls}] {pedigree}",
                    path=tuple(tuple(p) for p in path),
                    branch_weight_status="UNWEIGHTED",
                    source_session=session)
    return b


def world_class_of(branch: WorldBranch) -> str:
    """Class identity, recoverable from any branch, forever."""
    ped = branch.generation_pedigree
    for c in WORLD_CLASSES:
        if ped.startswith(f"[{c}]"):
            return c
    if branch.generation_method == "EMPIRICAL_HISTORICAL_ANALOG":
        return "EMPIRICAL_ANALOG"
    return "ADVERSARIAL_STRESS"


# ==================================================== 4B RESAMPLED

def causal_resampled_worlds(*, returns_pool: list, n_worlds: int,
                            horizon: int, start_price: float,
                            parent_state_hash: str, block: int = 15,
                            seed: int = 0,
                            regime_label: str = "UNCONDITIONED") -> list:
    """Conditional BLOCK bootstrap: reality's statistics, recombined.

    Blocks rather than single returns because minute returns carry
    autocorrelation and volatility clustering that i.i.d. resampling
    destroys -- producing worlds that are statistically smooth in a way
    no market has ever been, and therefore flattering to any
    mean-reverting attack."""
    if not returns_pool:
        raise FoundryViolation("no return pool: nothing to resample")
    if block < 2:
        raise FoundryViolation(
            "single-return resampling destroys autocorrelation and "
            "volatility clustering; use blocks")
    rng = _Rng(seed)
    out = []
    n = len(returns_pool)
    for w in range(n_worlds):
        rets, guard = [], 0
        while len(rets) < horizon and guard < 10_000:
            i = rng.randint(0, max(n - block, 0))
            rets.extend(returns_pool[i:i + block])
            guard += 1
        rets = rets[:horizon]
        px, path = start_price, []
        for t, r in enumerate(rets):
            px *= (1.0 + r)
            path.append((t, round(px, 6)))
        out.append(_mk(f"resampled_{regime_label}_{w}",
                       parent_state_hash, path, "CAUSAL_RESAMPLED",
                       f"block bootstrap (block={block}) of "
                       f"{n} conditioned returns, seed {seed}",
                       cond=regime_label))
    return out


class _Rng:
    """Deterministic, dependency-free -- reproducibility beats
    sophistication for a research seed."""

    def __init__(self, seed: int):
        self.s = (seed * 6364136223846793005 + 1442695040888963407) \
            & ((1 << 64) - 1)

    def _next(self) -> int:
        self.s = (self.s * 6364136223846793005 + 1442695040888963407) \
            & ((1 << 64) - 1)
        return self.s >> 11

    def random(self) -> float:
        return self._next() / float(1 << 53)

    def randint(self, lo: int, hi: int) -> int:
        return lo if hi <= lo else lo + self._next() % (hi - lo + 1)

    def normal(self) -> float:
        u1 = max(self.random(), 1e-12)
        u2 = self.random()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(
            2.0 * math.pi * u2)


# ================================================== 4C LEARNED MODEL

@dataclass
class ConditionalStateSpaceGenerator:
    """A fitted conditional path model. Deliberately small.

    Learned parameters per regime: AR(1) drift persistence, base
    volatility, GARCH-like persistence, and an EMPIRICAL residual pool
    (so fat tails and skew come from the market rather than from a
    Gaussian assumption we would have to defend)."""
    params: dict = field(default_factory=dict)
    trained_on: dict = field(default_factory=dict)
    eligibility: str = "UNTRAINED"
    architecture: str = ("regime-conditioned AR(1)+GARCH-like state "
                         "space with empirical residual resampling")
    architecture_justification: str = (
        "chosen for the data, not for novelty: with a few thousand "
        "sessions a high-capacity sequence model memorizes, and a "
        "memorizing generator resamples history while claiming to "
        "invent worlds")

    def fit(self, *, series_by_regime: dict, min_obs: int = 500
            ) -> dict:
        """Estimate per regime. A regime with too little data is left
        UNTRAINED rather than fitted to noise."""
        fitted, refused = {}, {}
        for regime, series in series_by_regime.items():
            rets = [r for s in series for r in s]
            if len(rets) < min_obs:
                refused[regime] = (f"{len(rets)} returns < {min_obs}: "
                                   f"refused rather than fitted to noise")
                continue
            mu = sum(rets) / len(rets)
            var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
            sd = math.sqrt(var) or 1e-8
            # AR(1) on returns
            num = sum((rets[i] - mu) * (rets[i - 1] - mu)
                      for i in range(1, len(rets)))
            den = sum((r - mu) ** 2 for r in rets) or 1e-12
            phi = max(-0.5, min(0.5, num / den))
            # volatility clustering: AR(1) on |resid|
            resid = [(rets[i] - mu - phi * (rets[i - 1] - mu))
                     for i in range(1, len(rets))]
            absr = [abs(x) for x in resid]
            am = sum(absr) / len(absr)
            n2 = sum((absr[i] - am) * (absr[i - 1] - am)
                     for i in range(1, len(absr)))
            d2 = sum((x - am) ** 2 for x in absr) or 1e-12
            beta = max(0.0, min(0.95, n2 / d2))
            std_resid = [x / sd for x in resid]
            fitted[regime] = {
                "mu": mu, "sd": sd, "phi": phi, "vol_persistence": beta,
                "residual_pool": std_resid[:20000],
                "n_returns": len(rets)}
        self.params = fitted
        self.trained_on = {"regimes_fitted": sorted(fitted),
                           "regimes_refused": refused,
                           "min_obs": min_obs}
        self.eligibility = "UNCALIBRATED" if fitted else "UNTRAINED"
        return {"kind": "generator_fit", "regimes": sorted(fitted),
                "refused": refused, "eligibility": self.eligibility,
                "architecture": self.architecture,
                "justification": self.architecture_justification}

    def sample(self, *, regime: str, n_worlds: int, horizon: int,
               start_price: float, parent_state_hash: str,
               seed: int = 0) -> list:
        if self.eligibility in ("UNTRAINED", "SUSPENDED"):
            raise FoundryViolation(
                f"generator eligibility is {self.eligibility}; it may "
                f"not produce research worlds")
        p = self.params.get(regime)
        if p is None:
            raise FoundryViolation(
                f"regime {regime!r} was never fitted -- sampling it "
                f"would be extrapolation dressed as simulation")
        rng = _Rng(seed)
        pool = p["residual_pool"]
        out = []
        for w in range(n_worlds):
            px, prev, vol = start_price, 0.0, p["sd"]
            path = []
            for t in range(horizon):
                z = pool[rng.randint(0, len(pool) - 1)]
                vol = math.sqrt(
                    max(1e-16,
                        (1 - p["vol_persistence"]) * p["sd"] ** 2
                        + p["vol_persistence"] * (vol ** 2)))
                r = p["mu"] + p["phi"] * prev + vol * z
                prev = r - p["mu"]
                px *= (1.0 + r)
                path.append((t, round(px, 6)))
            out.append(_mk(f"generated_{regime}_{seed}_{w}",
                           parent_state_hash, path,
                           "LEARNED_GENERATIVE",
                           f"conditional state-space sample, regime "
                           f"{regime}, seed {seed}; eligibility "
                           f"{self.eligibility}", cond=regime))
        return out


# ============================================ 4C VALIDATION BATTERY

# METRIC SEMANTICS (audited 2026-08-25). Each validation metric
# declares its definition, range and how two values of it may legally
# be COMPARED. The first version reported every check as a "ratio",
# including one that is a correlation coefficient -- a field name
# implying arithmetic the statistic does not support, which is the same
# error class as an `invalidation` that never invalidated.
#
# A ratio of two correlations is unstable and near-meaningless: with a
# real value of 0.35 and a generated value of -0.006 it reads -0.017,
# which sounds like a small discrepancy when the truth is that one
# series has strong volatility clustering and the other has none at
# all. Bounded statistics are compared by ABSOLUTE DIFFERENCE.
METRIC_SEMANTICS = {
    "ret_sd": {"definition": "standard deviation of per-step returns",
               "range": "[0, inf)", "comparison": "RATIO",
               "tolerance": 0.5},
    "vol_clustering_acf1": {
        "definition": "lag-1 autocorrelation of ABSOLUTE returns "
                      "(volatility clustering)",
        "range": "[-1, 1]", "comparison": "ABSOLUTE_DIFFERENCE",
        "tolerance": 0.15},
    "tail_freq_3sd": {"definition": "fraction of returns beyond 3 sd",
                      "range": "[0, 1]",
                      "comparison": "ABSOLUTE_DIFFERENCE",
                      "tolerance": 0.02},
    "final_sd": {"definition": "dispersion of terminal returns",
                 "range": "[0, inf)", "comparison": "RATIO",
                 "tolerance": 0.5},
    "mfe_median": {"definition": "median maximum favorable excursion",
                   "range": "(-inf, inf)", "comparison": "RATIO",
                   "tolerance": 0.5},
    "mae_median": {"definition": "median maximum adverse excursion",
                   "range": "(-inf, inf)", "comparison": "RATIO",
                   "tolerance": 0.5},
}


def _stats(paths: list) -> dict:
    rets, finals, mfes, maes = [], [], [], []
    for p in paths:
        px = [v for _t, v in p]
        if len(px) < 3:
            continue
        r = [px[i] / px[i - 1] - 1.0 for i in range(1, len(px))]
        rets += r
        finals.append(px[-1] / px[0] - 1.0)
        mfes.append(max(px) / px[0] - 1.0)
        maes.append(min(px) / px[0] - 1.0)
    if not rets:
        return {}
    mu = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / max(len(rets) - 1, 1))
    absr = [abs(x) for x in rets]
    am = sum(absr) / len(absr)
    ac = sum((absr[i] - am) * (absr[i - 1] - am)
             for i in range(1, len(absr))) / \
        (sum((x - am) ** 2 for x in absr) or 1e-12)
    tail = sum(1 for x in rets if abs(x - mu) > 3 * sd) / len(rets)
    return {"ret_mean": mu, "ret_sd": sd,
            "vol_clustering_acf1": ac,
            "tail_freq_3sd": tail,
            "final_median": statistics.median(finals),
            "final_sd": (statistics.pstdev(finals) if len(finals) > 1
                         else 0.0),
            "mfe_median": statistics.median(mfes),
            "mae_median": statistics.median(maes)}


def validate_generated_worlds(*, generated: list, real: list,
                              tolerance: float = 0.5) -> dict:
    """Do generated worlds behave like the real ones they claim to
    model -- CONDITIONAL on the same starting state?

    Looking market-like in general is not the bar. A generator that
    reproduces the unconditional distribution while ignoring the
    condition is a very elaborate way to sample the whole of history."""
    g = _stats([b.path for b in generated])
    r = _stats([b.path for b in real])
    if not g or not r:
        return {"kind": "generative_validation",
                "verdict": "INSUFFICIENT_DATA",
                "eligibility_recommendation": "SUSPENDED"}
    checks, failures = {}, []
    for k, sem in METRIC_SEMANTICS.items():
        gv, rv = g.get(k), r.get(k)
        tol = sem.get("tolerance", tolerance)
        if gv is None or rv is None:
            checks[k] = {"generated": gv, "real": rv,
                         "verdict": NOT_ESTIMABLE,
                         "comparison": sem["comparison"]}
            continue
        if sem["comparison"] == "ABSOLUTE_DIFFERENCE":
            # a bounded statistic: the honest comparison is the gap
            diff = gv - rv
            ok = abs(diff) <= tol
            checks[k] = {"generated": round(gv, 8),
                         "real": round(rv, 8),
                         "absolute_difference": round(diff, 6),
                         "tolerance": tol,
                         "comparison": "ABSOLUTE_DIFFERENCE",
                         "definition": sem["definition"],
                         "range": sem["range"],
                         "verdict": "OK" if ok else "OUT_OF_TOLERANCE"}
        else:
            if rv == 0:
                checks[k] = {"generated": gv, "real": rv,
                             "verdict": NOT_ESTIMABLE,
                             "comparison": "RATIO",
                             "why": "real value is zero; a ratio is "
                                    "undefined and will not be invented"}
                continue
            ratio = gv / rv
            ok = (1 - tol) <= abs(ratio) <= (1 + tol)
            checks[k] = {"generated": round(gv, 8),
                         "real": round(rv, 8),
                         "ratio": round(ratio, 4), "tolerance": tol,
                         "comparison": "RATIO",
                         "definition": sem["definition"],
                         "range": sem["range"],
                         "verdict": "OK" if ok else "OUT_OF_TOLERANCE"}
        if checks[k]["verdict"] == "OUT_OF_TOLERANCE":
            failures.append(k)
    return {"kind": "generative_validation", "checks": checks,
            "failures": failures,
            "verdict": "CONDITIONAL_FIDELITY_OK" if not failures
                       else "CONDITIONAL_FIDELITY_FAILED",
            "eligibility_recommendation": ("UNCALIBRATED" if not failures
                                           else "SUSPENDED"),
            "metric_semantics": METRIC_SEMANTICS,
            "law": "looking market-like in general is not the bar; "
                   "fidelity must hold CONDITIONAL on the start state. "
                   "Each metric is compared by the method its own range "
                   "supports -- a ratio of correlations is not a "
                   "comparison",
            "decision_power": "NONE_RESEARCH"}


def memorization_test(*, generated: list, training_paths: list,
                      max_similarity: float = 0.98) -> dict:
    """Is the generator inventing worlds, or reciting them?

    A generator whose samples sit on top of training paths is an
    expensive lookup table, and every 'novel' world it contributes to a
    multiverse is a duplicate vote for history."""
    if not generated or not training_paths:
        return {"kind": "memorization_test",
                "verdict": "INSUFFICIENT_DATA"}

    def norm(p):
        px = [v for _t, v in p]
        b = px[0] or 1.0
        return [v / b for v in px]

    train = [norm(p) for p in training_paths]
    sims = []
    for b in generated:
        gp = norm(b.path)
        best = 0.0
        for tp in train:
            n = min(len(gp), len(tp))
            if n < 3:
                continue
            d = math.sqrt(sum((gp[i] - tp[i]) ** 2 for i in range(n)) / n)
            best = max(best, 1.0 / (1.0 + d * 100))
        sims.append(best)
    mx = max(sims)
    mean = sum(sims) / len(sims)
    n_dup = sum(1 for s in sims if s >= max_similarity)
    return {"kind": "memorization_test",
            "max_similarity_to_training": round(mx, 4),
            "mean_similarity": round(mean, 4),
            "n_near_duplicates": n_dup,
            "threshold": max_similarity,
            "verdict": ("MEMORIZATION_SUSPECTED" if n_dup
                        else "NO_MEMORIZATION_DETECTED"),
            "law": "a world generator that memorizes history is not a "
                   "multiverse",
            "decision_power": "NONE_RESEARCH"}


# ============================================== PHASE 22 MONITOR

def generative_health(*, validation: dict, memorization: dict,
                      regime_coverage: dict | None = None) -> dict:
    """The world model gets Edge Health too. No single model may become
    a research single point of failure."""
    problems = []
    if validation.get("verdict") == "CONDITIONAL_FIDELITY_FAILED":
        problems.append(f"fidelity failures: {validation['failures']}")
    if memorization.get("verdict") == "MEMORIZATION_SUSPECTED":
        problems.append("memorization suspected")
    missing = [r for r, n in (regime_coverage or {}).items() if not n]
    if missing:
        problems.append(f"regimes with no fitted coverage: {missing}")
    eligible = "UNCALIBRATED" if not problems else "SUSPENDED"
    return {"kind": "generative_world_health",
            "problems": problems,
            "generative_world_eligibility": eligible,
            "fallback": "EMPIRICAL_ANALOG worlds remain available; the "
                        "multiverse degrades rather than stopping",
            "decision_power": "NONE_RESEARCH"}


# ============================================== TRIANGULATION

def triangulate(worlds_by_class: dict) -> dict:
    """Assemble the multiverse while keeping every class identifiable,
    and refuse to let one class silently dominate."""
    total = sum(len(v) for v in worlds_by_class.values())
    if not total:
        raise FoundryViolation("an empty multiverse is not a multiverse")
    shares = {c: round(len(v) / total, 4)
              for c, v in worlds_by_class.items()}
    warnings = []
    gen = shares.get("LEARNED_GENERATIVE", 0.0)
    emp = shares.get("EMPIRICAL_ANALOG", 0.0)
    if gen > 0.5:
        warnings.append(
            f"LEARNED_GENERATIVE holds {gen:.0%} of the multiverse: a "
            f"model is outvoting reality")
    if emp == 0.0:
        warnings.append(
            "no EMPIRICAL_ANALOG worlds: the multiverse has lost its "
            "reality anchor")
    return {"kind": "triangulated_multiverse", "n_worlds": total,
            "class_shares": shares, "warnings": warnings,
            "law": "class identity is retained forever; results are "
                   "reported per class, and a candidate surviving only "
                   "in generated worlds is flagged, never promoted",
            "decision_power": "NONE_RESEARCH"}


def results_by_class(run: dict, worlds: list, attack_id: str) -> dict:
    """Split an attack's outcomes by world class -- the check that
    catches an edge living only inside the model."""
    cls = {w.branch_id: world_class_of(w) for w in worlds}
    outs = run["outcomes"][attack_id]
    per = {}
    for bid, o in outs.items():
        c = cls.get(bid, "UNKNOWN")
        if isinstance(o.get("pnl"), (int, float)):
            per.setdefault(c, []).append(o["pnl"])
    summary = {c: {"n": len(v),
                   "favorable_fraction": round(
                       sum(1 for x in v if x > 0) / len(v), 4),
                   "median": round(statistics.median(v), 2)}
               for c, v in per.items()}
    emp = summary.get("EMPIRICAL_ANALOG", {}).get("favorable_fraction")
    gen = summary.get("LEARNED_GENERATIVE", {}).get("favorable_fraction")
    flag = None
    if isinstance(emp, float) and isinstance(gen, float) and \
            gen - emp >= 0.2:
        flag = ("SURVIVES_MAINLY_IN_GENERATED_WORLDS: the model likes "
                "this candidate considerably more than history does")
    return {"kind": "results_by_world_class", "attack_id": attack_id,
            "per_class": summary, "flag": flag,
            "decision_power": "NONE_RESEARCH"}


def class_authority(world_class: str) -> dict:
    """What a world source is currently permitted to establish."""
    rec = SOURCE_AUTHORITY.get(world_class)
    if rec is None:
        return {"world_class": world_class, "authority": "UNVALIDATED",
                "why": "unregistered source; an unknown generator has "
                       "no standing until it argues for some"}
    return {"world_class": world_class, **rec}


def evidence_verdict(per_class: dict, *, statistic: str = "median") -> dict:
    """Combine per-class results WITHOUT letting a support-ineligible
    source contribute positive evidence.

    THE RULE THIS ENFORCES. If reality says unfavorable and the
    resampler says favorable, the answer is NOT "mixed evidence" --
    that phrasing launders an unqualified source into a tie. The answer
    is: the eligible evidence is unfavorable, and the disagreeing
    source is not currently qualified to support anything.

    Disagreement from an ineligible source is still recorded. It is
    informative about the SOURCE, and may become informative about the
    candidate later if that source earns standing.

    Direction here is descriptive of this sample only. A favorable
    direction is not an edge -- baselines and the adversary decide
    that, and they have their own veto."""
    if statistic not in ("median", "favorable_fraction"):
        raise FoundryViolation(f"unsupported statistic {statistic!r}")
    neutral = 0.0 if statistic == "median" else 0.5

    eligible, ineligible = {}, {}
    for cls, row in per_class.items():
        v = row.get(statistic)
        auth = class_authority(cls)["authority"]
        bucket = (eligible if auth == "EDGE_SUPPORT_ELIGIBLE"
                  else ineligible)
        bucket[cls] = {"authority": auth, statistic: v, "n": row.get("n")}

    if not eligible:
        return {"kind": "evidence_verdict", "statistic": statistic,
                "verdict": "NO_SUPPORT_ELIGIBLE_EVIDENCE",
                "eligible": eligible, "ineligible": ineligible,
                "reasoning": ["no EDGE_SUPPORT_ELIGIBLE world class is "
                              "present; nothing here can support a "
                              "candidate regardless of how favorable "
                              "the other classes look"],
                "law": LAW_WORLD_COUNT,
                "decision_power": "NONE_RESEARCH"}

    vals = [r[statistic] for r in eligible.values()
            if isinstance(r[statistic], (int, float))]
    if not vals:
        direction = "NOT_ESTIMABLE"
    elif statistics.median(vals) > neutral:
        direction = "FAVORABLE"
    elif statistics.median(vals) < neutral:
        direction = "UNFAVORABLE"
    else:
        direction = "NEUTRAL"

    reasoning, disregarded = [], []
    for cls, r in ineligible.items():
        v = r[statistic]
        if isinstance(v, (int, float)) and v > neutral and \
                direction in ("UNFAVORABLE", "NEUTRAL"):
            disregarded.append(cls)
            reasoning.append(
                f"{cls} is favorable ({statistic}={v}) but carries "
                f"authority {r['authority']}: it is NOT counted as "
                f"support, and this is not 'mixed evidence'")

    verdict = {"FAVORABLE": "FAVORABLE_ON_ELIGIBLE_EVIDENCE",
               "UNFAVORABLE": "UNFAVORABLE_ON_ELIGIBLE_EVIDENCE",
               "NEUTRAL": "NEUTRAL_ON_ELIGIBLE_EVIDENCE",
               "NOT_ESTIMABLE": "NOT_ESTIMABLE"}[direction]
    reasoning.insert(0, f"eligible classes {sorted(eligible)} are "
                        f"{direction} on {statistic}")
    if verdict == "FAVORABLE_ON_ELIGIBLE_EVIDENCE":
        reasoning.append("a favorable direction in eligible worlds is "
                         "not an edge; baselines and the adversary "
                         "retain their vetoes")
    return {"kind": "evidence_verdict", "statistic": statistic,
            "verdict": verdict,
            "eligible": eligible, "ineligible": ineligible,
            "disregarded_positive_support": disregarded,
            "reasoning": reasoning,
            "law": LAW_WORLD_COUNT,
            "decision_power": "NONE_RESEARCH"}


OPTIMISM_DELTAS = (
    "favorable_fraction_delta", "median_R_delta", "mfe_delta",
    "mae_delta", "left_tail_delta", "right_tail_delta",
    "invalidation_rate_delta", "time_to_target_delta",
    "time_to_invalidation_delta")


def _optimism_profile(v: dict) -> dict:
    """Nine-dimensional shape of what a world source produced.

    Mean and variance are not enough. The resampler's average looked
    plausible while its left tail was slightly harsher and its right
    tail was massively richer -- a single summary statistic would have
    reported that as 'roughly realistic'."""
    p = v["pnl"]
    srt = sorted(p)

    def med(key):
        return (round(statistics.median(v[key]), 4) if v[key]
                else NOT_ESTIMABLE)

    return {
        "n": len(p),
        "favorable_fraction": round(sum(1 for x in p if x > 0) / len(p), 4),
        "median_R": round(statistics.median(p), 2),
        "left_tail_p10": round(srt[max(0, len(srt) // 10 - 1)], 2),
        "right_tail_p90": round(srt[min(len(srt) - 1,
                                        9 * len(srt) // 10)], 2),
        "mfe_median": med("mfe"), "mae_median": med("mae"),
        "invalidation_rate": round(sum(1 for x in p if x < 0) / len(p), 4),
        "time_to_target_median": med("time_to_target"),
        "time_to_invalidation_median": med("time_to_invalidation"),
    }


def _optimism_delta(prof: dict, ref: dict) -> dict:
    """Every delta, always the full set. A delta that cannot be
    computed is reported NOT_ESTIMABLE rather than omitted, so a
    missing dimension is visible instead of silently absent."""
    pairs = (("favorable_fraction_delta", "favorable_fraction", 4),
             ("median_R_delta", "median_R", 2),
             ("mfe_delta", "mfe_median", 2),
             ("mae_delta", "mae_median", 2),
             ("left_tail_delta", "left_tail_p10", 2),
             ("right_tail_delta", "right_tail_p90", 2),
             ("invalidation_rate_delta", "invalidation_rate", 4),
             ("time_to_target_delta", "time_to_target_median", 4),
             ("time_to_invalidation_delta",
              "time_to_invalidation_median", 4))
    out = {}
    for name, key, nd in pairs:
        a, b = prof.get(key), ref.get(key)
        out[name] = (round(a - b, nd)
                     if isinstance(a, (int, float))
                     and isinstance(b, (int, float))
                     else NOT_ESTIMABLE)
    return out


def generator_optimism(run: dict, worlds: list, attack_id: str,
                       *, reference: str = "EMPIRICAL_ANALOG",
                       regime_by_branch: dict | None = None) -> dict:
    """GENERATOR_OPTIMISM_DIAGNOSTIC — is a world source friendlier
    than reality?

    Synthetic sources are NOT required to match empirical worlds; their
    whole purpose is to supply paths history did not happen to produce.
    What is required is that any systematic kindness be VISIBLE. A
    resampler that quietly grades every candidate more generously than
    reality would inflate confidence across the entire research
    programme, and nobody would see it in a single result.

    On the first full-stack run the resampler scored a candidate 40.0%
    favorable where reality scored it 29.6% -- exactly the drift this
    diagnostic exists to keep in view.

    WHY BY REGIME. A global label is a blunt instrument. A resampler
    may be perfectly serviceable in ordinary trending regimes and
    wildly optimistic during opening transitions, and "invalid" would
    throw away the half that works while "valid" would license the half
    that does not. When regimes are supplied the deltas are reported
    per regime as well as globally; when they are not, that absence is
    stated rather than assumed away."""
    cls = {w.branch_id: world_class_of(w) for w in worlds}
    outs = run["outcomes"][attack_id]
    series = ("mfe", "mae", "time_to_target", "time_to_invalidation")

    def _collect(keep=None):
        per = {}
        for bid, o in outs.items():
            if keep is not None and not keep(bid):
                continue
            c = cls.get(bid, "UNKNOWN")
            if not isinstance(o.get("pnl"), (int, float)):
                continue
            d = per.setdefault(c, {"pnl": [], **{k: [] for k in series}})
            d["pnl"].append(o["pnl"])
            for k in series:
                if isinstance(o.get(k), (int, float)):
                    d[k].append(o[k])
        return {c: _optimism_profile(v) for c, v in per.items()
                if v["pnl"]}

    def _compare(profiles):
        ref = profiles.get(reference)
        deltas, flags = {}, []
        if not ref:
            return deltas, flags, ref
        for c, prof in profiles.items():
            if c == reference:
                continue
            d = _optimism_delta(prof, ref)
            deltas[c] = d
            ff = d["favorable_fraction_delta"]
            if isinstance(ff, (int, float)) and ff >= 0.10:
                flags.append(f"{c} is OPTIMISTIC vs reality: favorable "
                             f"fraction +{ff:.1%}")
            elif isinstance(ff, (int, float)) and ff <= -0.10:
                flags.append(f"{c} is PESSIMISTIC vs reality: favorable "
                             f"fraction {ff:.1%}")
            rt, lt = d["right_tail_delta"], d["left_tail_delta"]
            if isinstance(rt, (int, float)) and isinstance(lt, (int, float)) \
                    and rt > 0 and lt <= 0:
                flags.append(
                    f"{c} shows ASYMMETRIC bias: right tail {rt:+.2f} "
                    f"while left tail {lt:+.2f} -- it manufactures "
                    f"upside it does not manufacture downside, which a "
                    f"mean or variance check would have missed")
        return deltas, flags, ref

    profiles = _collect()
    deltas, flags, ref = _compare(profiles)

    # REGIME COMPOSITION. Comparing a source conditioned on one regime
    # against a reference pool drawn mostly from another is not a test
    # of the source -- it is a comparison of two regimes wearing the
    # source's name. When the compositions differ materially the global
    # numbers are confounded and must say so, loudly, next to
    # themselves.
    confounding = []
    if regime_by_branch:
        def _mix(cls_name):
            m = {}
            for bid in outs:
                if cls.get(bid) != cls_name:
                    continue
                m[regime_by_branch.get(bid, "UNLABELLED")] = 1 + m.get(
                    regime_by_branch.get(bid, "UNLABELLED"), 0)
            tot = sum(m.values()) or 1
            return {k: round(v / tot, 4) for k, v in m.items()}

        ref_mix = _mix(reference)
        for c in {v for v in cls.values() if v != reference}:
            c_mix = _mix(c)
            tvd = 0.5 * sum(
                abs(c_mix.get(k, 0.0) - ref_mix.get(k, 0.0))
                for k in set(c_mix) | set(ref_mix))
            if tvd >= 0.25:
                confounding.append(
                    f"{c} vs {reference} is REGIME-CONFOUNDED: "
                    f"composition differs by {tvd:.0%} "
                    f"({c_mix} vs {ref_mix}). The global deltas below "
                    f"partly measure a regime difference, not a source "
                    f"difference -- read the stratified view")

        by_regime, regimes = {}, sorted(
            {r for b, r in regime_by_branch.items() if b in outs})
        for r in regimes:
            pr = _collect(lambda b, r=r: regime_by_branch.get(b) == r)
            dr, fr, rr = _compare(pr)
            by_regime[r] = {
                "profiles": pr, "generator_optimism_delta": dr,
                "flags": fr,
                "verdict": ("REFERENCE_MISSING" if not rr else
                            "BIAS_DETECTED" if fr else
                            "NO_MATERIAL_BIAS")}
        regime_view = {"stratified": True, "by_regime": by_regime,
                       "confounding": confounding}
    else:
        regime_view = {
            "stratified": False,
            "why": "no regime labels supplied; a source that is sound "
                   "in one regime and optimistic in another would be "
                   "invisible in this global view, and a composition "
                   "mismatch between classes could not be detected at "
                   "all",
            "by_regime": {}, "confounding": []}

    return {"kind": "generator_optimism_diagnostic",
            "attack_id": attack_id, "reference_class": reference,
            "preserved_deltas": list(OPTIMISM_DELTAS),
            "profiles": profiles,
            "generator_optimism_delta": deltas,
            "regime_stratified": regime_view,
            "flags": flags + confounding,
            "verdict": ("REFERENCE_MISSING" if not ref else
                        "CONFOUNDED_GLOBAL_COMPARISON" if confounding
                        else "BIAS_DETECTED" if flags else
                        "NO_MATERIAL_BIAS"),
            "authority_note": {c: class_authority(c)["authority"]
                               for c in profiles},
            "law": "synthetic sources are not required to match reality "
                   "-- supplying unseen paths is their purpose -- but "
                   "systematic kindness must never be invisible, and a "
                   "binary valid/invalid label is less useful than "
                   "knowing WHERE a source drifts",
            "decision_power": "NONE_RESEARCH"}


def world_set_hash(worlds: list) -> str:
    """Immutable identity for a world set, so comparisons reuse
    identical universes and results stay reproducible."""
    h = hashlib.sha256()
    for w in sorted(worlds, key=lambda x: x.branch_id):
        h.update(w.branch_id.encode())
        h.update(json.dumps(w.path, default=str).encode())
    return h.hexdigest()
