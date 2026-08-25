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
    return {"ret_mean": mu, "ret_sd": sd, "vol_clustering": ac,
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
    for k in ("ret_sd", "vol_clustering", "tail_freq_3sd",
              "final_sd", "mfe_median", "mae_median"):
        gv, rv = g.get(k), r.get(k)
        if rv in (None, 0):
            checks[k] = {"generated": gv, "real": rv,
                         "verdict": NOT_ESTIMABLE}
            continue
        ratio = gv / rv if rv else float("inf")
        ok = (1 - tolerance) <= abs(ratio) <= (1 + tolerance) if rv > 0 \
            else (1 - tolerance) <= abs(gv / rv) <= (1 + tolerance)
        checks[k] = {"generated": round(gv, 8), "real": round(rv, 8),
                     "ratio": round(ratio, 4),
                     "verdict": "OK" if ok else "OUT_OF_TOLERANCE"}
        if not ok:
            failures.append(k)
    return {"kind": "generative_validation", "checks": checks,
            "failures": failures,
            "verdict": "CONDITIONAL_FIDELITY_OK" if not failures
                       else "CONDITIONAL_FIDELITY_FAILED",
            "eligibility_recommendation": ("UNCALIBRATED" if not failures
                                           else "SUSPENDED"),
            "law": "looking market-like in general is not the bar; "
                   "fidelity must hold CONDITIONAL on the start state",
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


def world_set_hash(worlds: list) -> str:
    """Immutable identity for a world set, so comparisons reuse
    identical universes and results stay reproducible."""
    h = hashlib.sha256()
    for w in sorted(worlds, key=lambda x: x.branch_id):
        h.update(w.branch_id.encode())
        h.update(json.dumps(w.path, default=str).encode())
    return h.hexdigest()
