"""NEGATIVE CONTROLS N0-N4 and POSITIVE CONTROL P0 for the null court.

THE DESIGN PRINCIPLE
Every negative control starts from S1_CAUSAL_TREND -- a world with a
GENUINELY planted relationship -- and destroys that relationship by a
predeclared transformation. Running nulls on S0 would prove nothing:
there is no signal in S0 to destroy, so NO_SIGNAL there is free. The
demanding test is: given a world where the engine DOES find signal,
does breaking the causal channel make it say nothing?

Each control operates through the single `dataset` seam of the test
stand. None touches the model, the scaler, the sealing step or the
grader. A control that needed to would not be a control.

    N0  BLOCK-DERANGED TARGETS
        y is cut into contiguous blocks of BLOCK_STEPS and the blocks
        are permuted by a DERANGEMENT (no block stays in place), within
        each partition separately.
        DESTROYS  the pairing X_t <-> y_t
        PRESERVES X entirely; each y block's internal autocorrelation
                  (overlapping-horizon structure survives inside a block)
        A fixed point would leave BLOCK_STEPS real pairings intact and
        quietly weaken the null, so a derangement is REQUIRED and tested.

    N1  FORWARD TIME DISPLACEMENT
        X_t is paired with y_{t + SHIFT}, SHIFT = 200 steps.
        DESTROYS  the planted channel z_t -> drift over [t, t+15]. In S1
                  the latent z flips w.p. 0.02/step, so its
                  autocorrelation at lag k is (1 - 2*0.02)^k = 0.96^k;
                  at k = 200 that is ~3e-4. The channel is gone.
        PRESERVES causal ORDER -- the outcome is still known after the
                  forecast, so the grader accepts it -- and each series'
                  own path dependence. The purge is recomputed so no
                  training target reads an evaluation price.
        The REVERSED displacement (features from the target's future)
        is refused by the grader as an outcome knowable before the
        forecast; that refusal is itself tested.

    N2  NOISE FEATURES
        X is replaced row-for-row by iid N(0,1) draws from a PRNG keyed
        by (court, seed, "N2"). Same shape, same count.
        DESTROYS  all information in the features
        PRESERVES y and the outcome records exactly

    N3  ROW-DERANGED FEATURES
        rows of X are permuted by a derangement, within each partition,
        from a PRNG keyed by (court, seed, "N3") -- NEVER by y.
        DESTROYS  the pairing X_t <-> y_t AND X's temporal structure
        PRESERVES X's marginal distribution exactly; y untouched
        Distinct from N0: N0 keeps X's time structure and scrambles y
        in blocks; N3 keeps y and scrambles X row-wise.

    N4  RANDOM RANKER
        a model, not a transform: it ignores x and emits a Gaussian
        whose mean is a random draw scaled by the training sd. Its
        fit() sees (X, y) only to learn the training sd, exactly as the
        null does; predict sees nothing but a PRNG. It represents a
        random ordering of evaluation samples and must receive no
        interpretive credit.

    P0  S1_CAUSAL_TREND, untransformed, same M0. The positive control.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field as _field

from apex.world_model.canonical import strict_float
from apex.world_model.features import WARMUP_STEPS, extract_features
from apex.world_model.forecast import PredictiveDistribution
from apex.world_model.models import (ModelContractViolation, _check_matrix,
                                     gaussian_distribution)
from apex.world_model.targets import (HORIZON_NOT_AVAILABLE,
                                      TARGET_HORIZON_STEPS, OutcomeRecord,
                                      resolve_target)
from apex.world_model.teststand import build_dataset
from apex.world_model.worlds import _stream_rng

CONTROLS_VERSION = "WM0E_CONTROLS_V0.1"   # V0 padded N0 blocks; see _block_derange
N0_BLOCK_STEPS = 20
N1_SHIFT_STEPS = 200
S1_FLIP_PROB = 0.02
N1_RESIDUAL_AUTOCORR = (1.0 - 2.0 * S1_FLIP_PROB) ** N1_SHIFT_STEPS

CONTROL_CONTRACT = {
    "N0": {"name": "BLOCK_DERANGED_TARGETS", "block_steps": N0_BLOCK_STEPS,
           "destroys": "pairing X_t <-> y_t",
           "preserves": "X entirely; each y block's internal autocorrelation",
           "expected": "NO_SIGNAL"},
    "N1": {"name": "FORWARD_TIME_DISPLACEMENT", "shift_steps": N1_SHIFT_STEPS,
           "destroys": "the planted z_t -> drift channel; residual "
                       "autocorrelation 0.96^200 = %.2e" % N1_RESIDUAL_AUTOCORR,
           "preserves": "causal ORDER (grader accepts); each series' own "
                        "path dependence; the purge",
           "expected": "NO_SIGNAL"},
    "N2": {"name": "NOISE_FEATURES",
           "destroys": "all information in X",
           "preserves": "y and outcome records exactly; X shape",
           "expected": "NO_SIGNAL"},
    "N3": {"name": "ROW_DERANGED_FEATURES",
           "destroys": "pairing X_t <-> y_t and X's temporal structure",
           "preserves": "X's marginal distribution exactly; y untouched",
           "expected": "NO_SIGNAL"},
    "N4": {"name": "RANDOM_RANKER",
           "destroys": "any use of features (the model ignores x)",
           "preserves": "the training sd, exactly as the null comparator",
           "expected": "NO_SIGNAL"},
    "P0": {"name": "S1_CAUSAL_TREND_UNTRANSFORMED",
           "expected": "SIGNAL_DETECTED"},
}


class ControlViolation(ValueError):
    pass


def derangement(n: int, rng) -> list:
    """A permutation with NO fixed points. Refuses n < 2."""
    if n < 2:
        raise ControlViolation(
            "a derangement of %d element(s) does not exist; the control "
            "would silently be a no-op" % n)
    idx = list(range(n))
    for _ in range(256):
        rng.shuffle(idx)
        if all(i != j for i, j in enumerate(idx)):
            return idx
    return idx[1:] + idx[:1]                       # guaranteed derangement


def _reoutcome(rec: OutcomeRecord, new_value: float) -> OutcomeRecord:
    """An outcome record carrying a control-assigned target. Timing and
    identity fields are kept so the grader's causal check still applies."""
    return OutcomeRecord(world_id=rec.world_id, world_hash=rec.world_hash,
                         subject=rec.subject, step=rec.step,
                         horizon=rec.horizon, target_value=float(new_value),
                         outcome_known_time=rec.outcome_known_time)


def _block_derange(y: list, block: int, rng) -> tuple:
    """Derange FULL blocks only. Returns (deranged_y, kept_length).

    The first version padded a short trailing block by cycling values
    from its source block. My own test caught it: that DUPLICATES
    values, so y's multiset was not preserved and the null was not the
    null it claimed to be. Now the trailing partial block is TRUNCATED
    (at most block-1 samples) and the caller truncates X and the
    outcome records to match. Cost: a few samples. Benefit: the
    transformation is exactly a permutation of the target sequence."""
    n_full = len(y) // block
    if n_full < 2:
        raise ControlViolation(
            "N0 needs >= 2 full blocks of %d; got %d samples" % (block, len(y)))
    keep = n_full * block
    perm = derangement(n_full, rng)
    blocks = [y[i * block:(i + 1) * block] for i in range(n_full)]
    out = []
    for i in range(n_full):
        out.extend(blocks[perm[i]])
    return out, keep


# ------------------------------------------------------------ builders
def n0_dataset(court_id: str, seed: int):
    def build(world, subject, split):
        Xtr, ytr, _, _ = build_dataset(world, subject, split.train_steps)
        Xev, yev, ev_idx, ev_out = build_dataset(world, subject, split.eval_steps)
        rng_tr = _stream_rng(court_id, "N0", seed, "train")
        rng_ev = _stream_rng(court_id, "N0", seed, "eval")
        ytr2, ktr = _block_derange(ytr, N0_BLOCK_STEPS, rng_tr)
        yev2, kev = _block_derange(yev, N0_BLOCK_STEPS, rng_ev)
        ev_out2 = [_reoutcome(r, v) for r, v in zip(ev_out[:kev], yev2)]
        return Xtr[:ktr], ytr2, Xev[:kev], yev2, ev_idx[:kev], ev_out2
    return build


def n1_dataset(court_id: str, seed: int, shift: int = N1_SHIFT_STEPS):
    def build(world, subject, split):
        H, B, T = split.horizon_steps, split.boundary, split.n_steps
        states = world.observables[subject]

        def rows(steps):
            X, y, idx, out = [], [], [], []
            for s in steps:
                rec = resolve_target(world, subject, s + shift)
                if rec == HORIZON_NOT_AVAILABLE:
                    continue
                X.append(extract_features(states, s))
                y.append(rec.target_value)
                idx.append(s)
                # the outcome is genuinely known at (s+shift+H): later than
                # the forecast at s, so the grader's causal check holds
                out.append(OutcomeRecord(
                    world_id=rec.world_id, world_hash=rec.world_hash,
                    subject=subject, step=s, horizon=rec.horizon,
                    target_value=rec.target_value,
                    outcome_known_time=rec.outcome_known_time))
            return X, y, idx, out

        # PURGE recomputed for the displaced target: a training label
        # at step s reads prices up to s + shift + H, which must be <= B
        train_steps = range(WARMUP_STEPS, B - H - shift + 1)
        eval_steps = range(B, T - H - shift + 1)
        if len(train_steps) < 50 or len(eval_steps) < 50:
            raise ControlViolation(
                "N1 shift=%d leaves train=%d / eval=%d samples; the "
                "displacement is too large for this world"
                % (shift, len(train_steps), len(eval_steps)))
        Xtr, ytr, tr_idx, _ = rows(train_steps)
        assert all(s + shift + H <= B for s in tr_idx), "N1 purge violated"
        Xev, yev, ev_idx, ev_out = rows(eval_steps)
        return Xtr, ytr, Xev, yev, ev_idx, ev_out
    return build


def n2_dataset(court_id: str, seed: int):
    def build(world, subject, split):
        Xtr, ytr, _, _ = build_dataset(world, subject, split.train_steps)
        Xev, yev, ev_idx, ev_out = build_dataset(world, subject, split.eval_steps)
        rng = _stream_rng(court_id, "N2", seed, "noise")
        k = len(Xtr[0])
        Xtr2 = [[rng.gauss(0.0, 1.0) for _ in range(k)] for _ in Xtr]
        Xev2 = [[rng.gauss(0.0, 1.0) for _ in range(k)] for _ in Xev]
        return Xtr2, ytr, Xev2, yev, ev_idx, ev_out
    return build


def n3_dataset(court_id: str, seed: int):
    def build(world, subject, split):
        Xtr, ytr, _, _ = build_dataset(world, subject, split.train_steps)
        Xev, yev, ev_idx, ev_out = build_dataset(world, subject, split.eval_steps)
        # the permutation is keyed by (court, seed) ONLY -- y never
        # enters it, so target ordering cannot leak into the shuffle
        ptr = derangement(len(Xtr), _stream_rng(court_id, "N3", seed, "train"))
        pev = derangement(len(Xev), _stream_rng(court_id, "N3", seed, "eval"))
        return ([Xtr[i] for i in ptr], ytr, [Xev[i] for i in pev], yev,
                ev_idx, ev_out)
    return build


@dataclass
class RandomRanker:
    """N4. A random ordering dressed in the forecast contract."""
    court_id: str
    seed: int
    model_id: str = "N4_RANDOM_RANKER_V0"
    model_family: str = "RANDOM_ORDERING"
    model_version: str = "0.1.0"
    _mu: float = _field(default=None, repr=False)
    _sigma: float = _field(default=None, repr=False)
    _rng: object = _field(default=None, repr=False)

    def capabilities(self) -> dict:
        return {"distribution": "gaussian", "uses_features": False,
                "uses_outcome": False, "random": True}

    def fit(self, X: list, y: list) -> "RandomRanker":
        _check_matrix(X, y, where="fit")
        m = sum(y) / len(y)
        var = sum((v - m) ** 2 for v in y) / max(1, len(y) - 1)
        self._mu, self._sigma = m, math.sqrt(var)
        if self._sigma <= 0:
            raise ModelContractViolation("zero-variance training target")
        self._rng = _stream_rng(self.court_id, "N4", self.seed, "ranker")
        return self

    def predict_distribution(self, x: list) -> PredictiveDistribution:
        if self._rng is None:
            raise ModelContractViolation("predict before fit")
        # x is deliberately unused; the mean is a random draw
        mu = self._mu + self._sigma * self._rng.gauss(0.0, 1.0)
        return gaussian_distribution(mu, self._sigma)

    def model_identity(self) -> dict:
        return {"model_id": self.model_id, "model_family": self.model_family,
                "model_version": self.model_version,
                "configuration": {"uses_features": False, "random": True},
                "fitted": {"mu": self._mu, "sigma": self._sigma}}
