"""SYNTHETIC_WORLD_V0 -- deterministic artificial markets with a known answer key.

WHY BUILD UNIVERSES BEFORE BUILDING A MODEL
Because on real data you cannot tell a working detector from a broken
one. A method that reports edge everywhere and a method that reports
edge correctly look identical until you own a world where you already
know the answer. So the first thing the laboratory needs is not a model
-- it is a world where "no edge exists" is a FACT rather than a
hypothesis, and a world where a planted relationship is known by
construction.

THE ANSWER KEY IS PHYSICALLY SEPARATE
`ObservableState` is what a model may see. `GeneratorGroundTruth` is
what actually caused it. They are different objects, and the observable
one does not hold a reference to the truth -- you cannot reach the
answer key from the student's desk by any attribute path. This is
structural, not a naming convention, because a naming convention is
exactly what fails at 2am when someone needs "just one more feature".

THE GENERATING EQUATIONS ARE STATED, NOT HIDDEN
Every world writes down its own process. A future researcher must be
able to read exactly what causal structure was placed into the world,
because a synthetic result is worthless if the synthesis is a black box.

    S0  NO_SIGNAL_RANDOM_WALK
        p_{t+1} = p_t * exp(sigma * e_t)          e_t ~ N(0,1) iid
        Nothing observable predicts e_t. By construction there is NO
        edge. A method that finds one here is broken.

    S1  CAUSAL_TREND
        z_t  ~ persistent latent state, P(flip) = flip_prob per step
        p_{t+1} = p_t * exp(mu * z_t + sigma * e_t)
        z_t genuinely drives subsequent drift. Whether z_t is visible
        is a CONFIG choice (observe_latent), so the same world can be
        run as solvable or as an unfair test.

    S2  CAUSAL_MEAN_REVERSION   (Ornstein-Uhlenbeck on log price)
        x_{t+1} = x_t + theta * (anchor - x_t) * dt + sigma * sqrt(dt) * e_t
        Known path dependence with a different causal shape from S1:
        the state that matters is the DISPLACEMENT, not a hidden flag.

    S3  REGIME_TRANSITION_JUMP
        regime r_t in {CALM, STRESS} via a 2x2 transition matrix
        p_{t+1} = p_t * exp(sigma_{r_t} * e_t + J_t)
        J_t = jump_size * s_t with prob lambda_{r_t}, else 0
        Discontinuity and latent-state change, for distributional
        machinery that must not assume smoothness.

    MULTI-SUBJECT
        e_{i,t} = beta_i * F_t + sqrt(1 - beta_i^2) * u_{i,t}
        F_t is the shared market factor, u idiosyncratic. Written this
        way so total variance stays ~1 regardless of beta, which keeps
        beta a pure dependence knob rather than a hidden vol knob.

DETERMINISM
Every draw comes from a PRNG seeded by
sha256(generator_version | config_hash | seed | stream_name). No global
RNG, no wall clock, no os.urandom. Same version + config + seed gives a
byte-identical world; any material change to any of the three gives a
different world_hash.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field as _field

from apex.world_model.canonical import (NumericContractViolation,
                                        content_hash, strict_float)
from apex.world_model.inputs import (A0_CORE, Component, WorldModelInput)
from apex.world_model.quality import VALID

WORLD_SCHEMA_VERSION = "SYNTHETIC_WORLD_V0"
GENERATOR_VERSION = "apex.world_model.worlds/0.1.0"

S0_NO_SIGNAL_RANDOM_WALK = "S0_NO_SIGNAL_RANDOM_WALK"
S1_CAUSAL_TREND = "S1_CAUSAL_TREND"
S2_CAUSAL_MEAN_REVERSION = "S2_CAUSAL_MEAN_REVERSION"
S3_REGIME_TRANSITION_JUMP = "S3_REGIME_TRANSITION_JUMP"
WORLD_TYPES = (S0_NO_SIGNAL_RANDOM_WALK, S1_CAUSAL_TREND,
               S2_CAUSAL_MEAN_REVERSION, S3_REGIME_TRANSITION_JUMP)

SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
NULL_FIXTURE = "NULL_FIXTURE"

HORIZON_NOT_AVAILABLE = "HORIZON_NOT_AVAILABLE"
HORIZON_STEPS = {"H_5M": 5, "H_15M": 15, "H_30M": 30, "H_60M": 60}

# ---------------------------------------------------- RESOURCE BOUNDS
# APEX has now demonstrated the whole-history/unbounded-state failure
# THREE times (MIRROR-003, PULSE-006, BTC-RESOLVER). A research engine
# that quietly generates a 40 GB fixture would be the fourth. Bounds are
# declared, enforced at config time, and refused rather than truncated.
MAX_SUBJECTS = 32
MAX_STEPS = 5_000
MAX_TOTAL_POINTS = 100_000

# Vocabulary that must NEVER appear in an observable component: these
# are answer-key names. See GROUND_TRUTH FIREWALL below.
LATENT_TRUTH_TOKENS = frozenset({
    "latent", "regime", "ground_truth", "truth", "future", "forward",
    "mfe", "mae", "answer", "oracle", "generator_state", "seed",
    "realized", "outcome", "label"})


class WorldConfigViolation(ValueError):
    """A malformed generator configuration. Refused, never repaired:
    silently fixing a bad sigma produces a world whose stated equation
    is not the one that ran."""


class GroundTruthLeak(Exception):
    """Something tried to move the answer key onto the student's desk."""


def _stream_rng(generator_version: str, config_hash: str, seed: int,
                stream: str) -> random.Random:
    """A dedicated PRNG per logical stream.

    Per-stream derivation (rather than one shared generator) means
    adding a subject or a new draw site cannot shift the numbers every
    OTHER stream produces -- otherwise 'same seed' would be true only
    until the next code change.
    """
    h = hashlib.sha256(
        ("%s|%s|%d|%s" % (generator_version, config_hash, seed, stream)
         ).encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


@dataclass(frozen=True)
class WorldConfig:
    world_type: str
    seed: int
    n_subjects: int = 2
    n_steps: int = 120
    step_seconds: float = 60.0
    session_start: float = 1_756_800_000.0
    start_price: float = 100.0
    sigma: float = 0.001
    betas: tuple = ()               # shared-factor loading per subject
    observe_latent: bool = False    # is the causal state visible?
    params: dict = _field(default_factory=dict)

    def __post_init__(self):
        if self.world_type not in WORLD_TYPES:
            raise WorldConfigViolation(
                "unknown world_type %r; permitted %s"
                % (self.world_type, list(WORLD_TYPES)))
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise WorldConfigViolation(
                "seed must be an int, got %r" % (self.seed,))
        if self.seed < 0:
            raise WorldConfigViolation("seed must be >= 0")
        for name, v, lo, hi in (("n_subjects", self.n_subjects, 1, MAX_SUBJECTS),
                                ("n_steps", self.n_steps, 2, MAX_STEPS)):
            if not isinstance(v, int) or isinstance(v, bool):
                raise WorldConfigViolation("%s must be an int" % name)
            if not (lo <= v <= hi):
                raise WorldConfigViolation(
                    "%s=%d outside [%d, %d]. Bounds are refused, not "
                    "truncated: a silently shrunk world is not the world "
                    "whose config was recorded." % (name, v, lo, hi))
        if self.n_subjects * self.n_steps > MAX_TOTAL_POINTS:
            raise WorldConfigViolation(
                "n_subjects*n_steps = %d exceeds MAX_TOTAL_POINTS=%d"
                % (self.n_subjects * self.n_steps, MAX_TOTAL_POINTS))
        for name, v in (("step_seconds", self.step_seconds),
                        ("session_start", self.session_start),
                        ("start_price", self.start_price),
                        ("sigma", self.sigma)):
            strict_float(v, field=name)
        if self.sigma <= 0:
            raise WorldConfigViolation(
                "sigma=%r; volatility must be strictly positive" % self.sigma)
        if self.step_seconds <= 0:
            raise WorldConfigViolation("step_seconds must be > 0")
        if self.start_price <= 0:
            raise WorldConfigViolation("start_price must be > 0")
        if self.betas:
            if len(self.betas) != self.n_subjects:
                raise WorldConfigViolation(
                    "betas has %d entries for %d subjects"
                    % (len(self.betas), self.n_subjects))
            for b in self.betas:
                bb = strict_float(b, field="beta")
                if not (-1.0 <= bb <= 1.0):
                    raise WorldConfigViolation(
                        "beta=%r outside [-1,1]; the decomposition "
                        "sqrt(1-beta^2) would be imaginary" % bb)
        self._validate_params()

    def _validate_params(self):
        p = self.params
        if self.world_type == S1_CAUSAL_TREND:
            mu = strict_float(p.get("mu", 0.0005), field="mu")
            fp = strict_float(p.get("flip_prob", 0.02), field="flip_prob")
            if not (0.0 <= fp <= 1.0):
                raise WorldConfigViolation(
                    "flip_prob=%r is not a probability" % fp)
            if mu == 0.0:
                raise WorldConfigViolation(
                    "S1_CAUSAL_TREND with mu=0 plants NO relationship; "
                    "use S0 if that is what you want")
        elif self.world_type == S2_CAUSAL_MEAN_REVERSION:
            th = strict_float(p.get("theta", 0.05), field="theta")
            strict_float(p.get("anchor_log", math.log(self.start_price)),
                         field="anchor_log")
            if th <= 0:
                raise WorldConfigViolation(
                    "theta=%r; mean reversion requires theta > 0" % th)
            if th * 1.0 > 2.0:
                raise WorldConfigViolation(
                    "theta=%r with dt=1 overshoots and oscillates; the "
                    "discretisation is not valid" % th)
        elif self.world_type == S3_REGIME_TRANSITION_JUMP:
            m = p.get("transition", ((0.98, 0.02), (0.10, 0.90)))
            if len(m) != 2 or any(len(r) != 2 for r in m):
                raise WorldConfigViolation("transition must be 2x2")
            for i, row in enumerate(m):
                s = 0.0
                for v in row:
                    pv = strict_float(v, field="transition")
                    if not (0.0 <= pv <= 1.0):
                        raise WorldConfigViolation(
                            "transition entry %r is not a probability" % pv)
                    s += pv
                if abs(s - 1.0) > 1e-9:
                    raise WorldConfigViolation(
                        "transition row %d sums to %r, not 1" % (i, s))
            for k, d in (("sigma_calm", self.sigma),
                         ("sigma_stress", self.sigma * 4)):
                sv = strict_float(p.get(k, d), field=k)
                if sv <= 0:
                    raise WorldConfigViolation("%s must be > 0" % k)
            for k in ("lambda_calm", "lambda_stress"):
                lv = strict_float(p.get(k, 0.0 if "calm" in k else 0.05),
                                  field=k)
                if not (0.0 <= lv <= 1.0):
                    raise WorldConfigViolation(
                        "%s=%r is not a probability" % (k, lv))

    def canonical(self) -> dict:
        return {"world_type": self.world_type, "seed": self.seed,
                "n_subjects": self.n_subjects, "n_steps": self.n_steps,
                "step_seconds": float(self.step_seconds),
                "session_start": float(self.session_start),
                "start_price": float(self.start_price),
                "sigma": float(self.sigma),
                "betas": [float(b) for b in self.betas],
                "observe_latent": bool(self.observe_latent),
                "params": {k: (list(map(list, v))
                               if k == "transition" else v)
                           for k, v in sorted(self.params.items())}}

    @property
    def config_hash(self) -> str:
        return content_hash(self.canonical())


@dataclass(frozen=True)
class ObservableState:
    """What a model may see. It holds NO reference to the truth object,
    so there is no attribute path from here to the answer key."""
    subject: str
    step: int
    t: float
    price: float
    spread: float
    volume: float
    trade_count: int
    observable_latent: float | None = None   # only if config permits

    def components(self) -> list:
        c = [Component("close", "price_path", self.t, self.t, VALID,
                       self.price, "SYNTHETIC_WORLD_V0"),
             Component("spread_bps", "microstructure", self.t, self.t,
                       VALID, self.spread, "SYNTHETIC_WORLD_V0"),
             Component("volume", "volume", self.t, self.t, VALID,
                       self.volume, "SYNTHETIC_WORLD_V0"),
             Component("trade_count", "sip_trades", self.t, self.t, VALID,
                       float(self.trade_count), "SYNTHETIC_WORLD_V0")]
        if self.observable_latent is not None:
            # Named as a STATE, never as the answer and never as an
            # instruction. The first name tried here was
            # "declared_state_signal" and WM-0B correctly refused it:
            # "signal" is decision vocabulary. The guard caught a real
            # naming mistake in its own laboratory, which is the best
            # evidence it works.
            c.append(Component("declared_observable_state", "market_relative",
                               self.t, self.t, VALID,
                               self.observable_latent,
                               "SYNTHETIC_WORLD_V0"))
        return c


@dataclass(frozen=True)
class GeneratorGroundTruth:
    """THE ANSWER KEY. Reachable only from the world object, never from
    an ObservableState, and never placed into a WorldModelInput."""
    world_id: str
    latent_path: dict          # subject -> tuple latent state per step
    regime_path: dict          # subject -> tuple regime label per step
    jump_steps: dict           # subject -> tuple of steps that jumped
    shared_factor: tuple       # F_t
    full_price_path: dict      # subject -> tuple price per step
    causal_features: tuple     # names that GENUINELY drive the path
    noise_features: tuple      # names planted to be pure noise
    definition: str


def _forward_truth(path, step, h_steps):
    """Forward return / MFE / MAE from `step` over `h_steps`."""
    end = step + h_steps
    if end >= len(path):
        return HORIZON_NOT_AVAILABLE
    p0 = path[step]
    window = path[step + 1:end + 1]
    hi, lo = max(window), min(window)
    return {
        "forward_return": (path[end] / p0) - 1.0,
        "mfe": (hi / p0) - 1.0,
        "mae": (lo / p0) - 1.0,
        "time_to_mfe_steps": window.index(hi) + 1,
        "time_to_mae_steps": window.index(lo) + 1,
    }


@dataclass(frozen=True)
class SyntheticWorld:
    world_id: str
    world_type: str
    fixture_class: str
    config: WorldConfig
    subjects: tuple
    observables: dict            # subject -> tuple[ObservableState]
    birth_time: float
    latent_state_definition: str
    ground_truth_definition: str
    generating_equation: str
    _truth: GeneratorGroundTruth
    generator_version: str = GENERATOR_VERSION
    generator_commit: str = "UNCOMMITTED"
    schema_version: str = WORLD_SCHEMA_VERSION

    # -------------------------------------------------- observable face
    def observable_canonical(self) -> dict:
        """Everything a model may see, and nothing else."""
        return {
            "schema_version": self.schema_version,
            "world_type": self.world_type,
            "fixture_class": self.fixture_class,
            "generator_version": self.generator_version,
            "generator_commit": self.generator_commit,
            "seed": self.config.seed,
            "configuration": self.config.canonical(),
            "configuration_hash": self.config.config_hash,
            "subjects": list(self.subjects),
            "session": {"start": float(self.config.session_start),
                        "step_seconds": float(self.config.step_seconds),
                        "n_steps": self.config.n_steps},
            "observables": {
                s: [{"step": o.step, "t": o.t, "price": o.price,
                     "spread": o.spread, "volume": o.volume,
                     "trade_count": o.trade_count,
                     "observable_latent": o.observable_latent}
                    for o in self.observables[s]]
                for s in self.subjects},
        }

    @property
    def world_hash(self) -> str:
        return content_hash(self.observable_canonical())

    def manifest(self) -> dict:
        m = self.observable_canonical()
        m["world_id"] = self.world_id
        m["birth_time"] = float(self.birth_time)
        m["world_hash"] = self.world_hash
        m["latent_state_definition"] = self.latent_state_definition
        m["ground_truth_definition"] = self.ground_truth_definition
        m["generating_equation"] = self.generating_equation
        m["TRADING_AUTHORITY"] = "NONE"
        m["CAPITAL_AUTHORITY"] = "NONE"
        m["ORDER_AUTHORITY"] = "NONE"
        m["PREDICTION_AUTHORITY"] = "NONE"
        return m

    # ------------------------------------------------- the answer key
    def ground_truth(self) -> GeneratorGroundTruth:
        """Explicit, named, and deliberately awkward to reach by
        accident. Test harnesses call this; model-input construction
        must not."""
        return self._truth

    def forward_truth(self, subject: str, step: int, horizon: str):
        if horizon == "H_SESSION_CLOSE":
            path = self._truth.full_price_path[subject]
            if step >= len(path) - 1:
                return HORIZON_NOT_AVAILABLE
            return _forward_truth(path, step, len(path) - 1 - step)
        if horizon not in HORIZON_STEPS:
            raise WorldConfigViolation("unknown horizon %r" % horizon)
        return _forward_truth(self._truth.full_price_path[subject], step,
                              HORIZON_STEPS[horizon])

    # ------------------------------------ the ONE path world -> input
    def to_world_model_input(self, subject: str, step: int, *,
                             input_id: str | None = None) -> WorldModelInput:
        """Build a model-visible input. GROUND TRUTH FIREWALL lives here.

        The observable state physically lacks the truth, and this method
        additionally refuses any component whose name is answer-key
        vocabulary -- belt and braces, because the expensive failure is
        a helpful future contributor adding `latent_regime` to
        ObservableState.components() and nothing noticing.
        """
        o = self.observables[subject][step]
        comps = o.components()
        for c in comps:
            low = c.name.lower()
            for tok in LATENT_TRUTH_TOKENS:
                if tok in low:
                    raise GroundTruthLeak(
                        "component %r carries answer-key vocabulary (%r). "
                        "The laboratory must not hand the student the "
                        "answer key." % (c.name, tok))
        return WorldModelInput(
            input_id=input_id or "%s:%s:%d" % (self.world_id, subject, step),
            information_tier=A0_CORE, subject=subject,
            state_time=o.t, state_complete_time=o.t, known_from=o.t,
            source_state_id="%s:%s:%d" % (self.world_id, subject, step),
            source_state_hash=self.world_hash,
            feature_family_versions={"price_path": self.generator_version},
            components=tuple(comps),
            provenance={"fixture_class": self.fixture_class,
                        "world_type": self.world_type,
                        "generator_version": self.generator_version,
                        "configuration_hash": self.config.config_hash,
                        "seed": self.config.seed})


# =========================================================== generator
def generate_world(config: WorldConfig, *, fixture_class=SYNTHETIC_FIXTURE,
                   generator_commit: str = "UNCOMMITTED") -> SyntheticWorld:
    n, T = config.n_subjects, config.n_steps
    subjects = tuple("SYN_%s" % chr(ord("A") + i) for i in range(n))
    betas = (config.betas if config.betas else tuple(0.0 for _ in range(n)))
    ch = config.config_hash

    f_rng = _stream_rng(GENERATOR_VERSION, ch, config.seed, "shared_factor")
    shared = tuple(f_rng.gauss(0.0, 1.0) for _ in range(T))

    p = config.params
    obs, latent_path, regime_path, jump_steps, price_path = {}, {}, {}, {}, {}

    for i, sub in enumerate(subjects):
        beta = float(betas[i])
        idio = _stream_rng(GENERATOR_VERSION, ch, config.seed, "idio:%s" % sub)
        aux = _stream_rng(GENERATOR_VERSION, ch, config.seed, "aux:%s" % sub)
        mix = math.sqrt(max(0.0, 1.0 - beta * beta))

        price = config.start_price
        x = math.log(price)
        lat, reg, jumps, path, states = [], [], [], [], []
        regime = "CALM"
        z = 1.0 if aux.random() < 0.5 else -1.0

        for step in range(T):
            e = beta * shared[step] + mix * idio.gauss(0.0, 1.0)
            if config.world_type == S0_NO_SIGNAL_RANDOM_WALK:
                x += config.sigma * e
                lat.append(0.0); reg.append("NONE")
            elif config.world_type == S1_CAUSAL_TREND:
                mu = float(p.get("mu", 0.0005))
                if aux.random() < float(p.get("flip_prob", 0.02)):
                    z = -z
                x += mu * z + config.sigma * e
                lat.append(z); reg.append("NONE")
            elif config.world_type == S2_CAUSAL_MEAN_REVERSION:
                theta = float(p.get("theta", 0.05))
                anchor = float(p.get("anchor_log", math.log(config.start_price)))
                x += theta * (anchor - x) + config.sigma * e
                lat.append(anchor - x); reg.append("NONE")
            else:  # S3
                tm = p.get("transition", ((0.98, 0.02), (0.10, 0.90)))
                row = tm[0] if regime == "CALM" else tm[1]
                regime = ("CALM" if aux.random() < row[0] else "STRESS")
                sig = float(p.get("sigma_calm", config.sigma)) if regime == "CALM" \
                    else float(p.get("sigma_stress", config.sigma * 4))
                lam = float(p.get("lambda_calm", 0.0)) if regime == "CALM" \
                    else float(p.get("lambda_stress", 0.05))
                j = 0.0
                if aux.random() < lam:
                    j = float(p.get("jump_size", 0.01)) * (1 if aux.random() < 0.5 else -1)
                    jumps.append(step)
                x += sig * e + j
                lat.append(j); reg.append(regime)

            price = math.exp(x)
            path.append(price)
            states.append(ObservableState(
                subject=sub, step=step,
                t=config.session_start + step * config.step_seconds,
                price=price,
                spread=abs(config.sigma * price * (1.0 + 0.5 * aux.random())),
                volume=1000.0 + 500.0 * aux.random(),
                trade_count=int(10 + 20 * aux.random()),
                observable_latent=(lat[-1] if config.observe_latent else None)))

        obs[sub] = tuple(states)
        latent_path[sub] = tuple(lat)
        regime_path[sub] = tuple(reg)
        jump_steps[sub] = tuple(jumps)
        price_path[sub] = tuple(path)

    eq = {
        S0_NO_SIGNAL_RANDOM_WALK:
            "p_{t+1} = p_t * exp(sigma * e_t); e iid N(0,1); NO observable predicts e",
        S1_CAUSAL_TREND:
            "p_{t+1} = p_t * exp(mu*z_t + sigma*e_t); z flips w.p. flip_prob",
        S2_CAUSAL_MEAN_REVERSION:
            "x_{t+1} = x_t + theta*(anchor - x_t) + sigma*e_t   (OU, dt=1)",
        S3_REGIME_TRANSITION_JUMP:
            "r_t via 2x2 transition; x_{t+1} = x_t + sigma_{r}*e_t + J_t",
    }[config.world_type]

    world_id = "W-%s-%s" % (config.world_type.split("_")[0],
                            content_hash({"c": config.canonical(),
                                          "g": GENERATOR_VERSION})[:12])
    truth = GeneratorGroundTruth(
        world_id=world_id, latent_path=latent_path, regime_path=regime_path,
        jump_steps=jump_steps, shared_factor=shared,
        full_price_path=price_path,
        causal_features=(() if config.world_type == S0_NO_SIGNAL_RANDOM_WALK
                         else ("latent_state",)),
        noise_features=("spread_bps", "volume", "trade_count"),
        definition="latent_path/regime_path/jump_steps/shared_factor/"
                   "full_price_path are GENERATOR-ONLY")
    return SyntheticWorld(
        world_id=world_id, world_type=config.world_type,
        fixture_class=fixture_class, config=config, subjects=subjects,
        observables=obs,
        birth_time=config.session_start,
        latent_state_definition=(
            "S0: none. S1: persistent sign z_t. S2: displacement from "
            "anchor. S3: regime in {CALM,STRESS} plus jump indicator."),
        ground_truth_definition=truth.definition,
        generating_equation=eq, _truth=truth,
        generator_commit=generator_commit)


__all__ = ["WORLD_SCHEMA_VERSION", "GENERATOR_VERSION", "WORLD_TYPES",
           "S0_NO_SIGNAL_RANDOM_WALK", "S1_CAUSAL_TREND",
           "S2_CAUSAL_MEAN_REVERSION", "S3_REGIME_TRANSITION_JUMP",
           "SYNTHETIC_FIXTURE", "NULL_FIXTURE", "HORIZON_NOT_AVAILABLE",
           "HORIZON_STEPS", "MAX_SUBJECTS", "MAX_STEPS",
           "MAX_TOTAL_POINTS", "LATENT_TRUTH_TOKENS", "WorldConfig",
           "WorldConfigViolation", "ObservableState",
           "GeneratorGroundTruth", "SyntheticWorld", "GroundTruthLeak",
           "generate_world"]
