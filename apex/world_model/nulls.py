"""NULL WORLD BATTERY -- infrastructure worlds where the answer is "nothing".

These are NOT the Phase-3 real-data null rig. That rig remains BLOCKED
and its test is still skipped. These are synthetic controls, built so
the future harness can be checked against a world where the correct
finding is known to be "no relationship" -- before it is ever pointed at
real data.

WHY EACH NULL SAYS EXACTLY WHAT IT DESTROYS AND WHAT IT KEEPS
A null that destroys everything is useless: if you shuffle away the
autocorrelation, the volatility clustering AND the relationship, then a
method failing on it tells you nothing about which property it needed.
So each transformation names its target precisely.

    N0  ASSOCIATION_DESTROYED_BLOCK_PRESERVED
        DESTROYS: the pairing between a subject's observable state and
                  its own future path.
        PRESERVES: each path's internal structure -- autocorrelation,
                  volatility clustering, jumps -- because whole blocks
                  are permuted between subjects, never resampled.
        Correct finding: no cross-subject predictive relationship.

    N1  TIME_SHIFTED_NONCAUSAL
        DESTROYS: causality, by pairing observables with a path segment
                  from a LATER window, so the "state" post-dates what it
                  supposedly predicts.
        PRESERVES: the marginal distribution of both sides, and the
                  within-series structure of each.
        Correct finding: no edge -- and a method that finds one is
        reading the future, which is the single most expensive bug a
        research system can have.

    N2  PURE_NOISE_FEATURES
        DESTROYS: any informational content in the features.
        PRESERVES: their shape, scale and column count, so a method
                  cannot pass merely by noticing the features look odd.
        Correct finding: no feature importance anywhere.

DELIBERATE NON-GOAL: none of these prove a model is correct. They can
only ever falsify. A method that passes all three has earned the right
to be tested on something harder, not a certificate.
"""
from __future__ import annotations

from dataclasses import dataclass

from apex.world_model.canonical import content_hash
from apex.world_model.worlds import (NULL_FIXTURE, SyntheticWorld,
                                     WorldConfig, _stream_rng,
                                     generate_world)

N0_ASSOCIATION_DESTROYED = "N0_ASSOCIATION_DESTROYED_BLOCK_PRESERVED"
N1_TIME_SHIFTED = "N1_TIME_SHIFTED_NONCAUSAL"
N2_PURE_NOISE = "N2_PURE_NOISE_FEATURES"
NULL_TYPES = (N0_ASSOCIATION_DESTROYED, N1_TIME_SHIFTED, N2_PURE_NOISE)

NULL_CONTRACT = {
    N0_ASSOCIATION_DESTROYED: {
        "destroys": "pairing between a subject's observable state and "
                    "its own future path",
        "preserves": "each path's internal autocorrelation, volatility "
                     "clustering and jumps (whole blocks permuted, never "
                     "resampled)",
        "correct_finding": "no cross-subject predictive relationship"},
    N1_TIME_SHIFTED: {
        "destroys": "causality -- observables are paired with a LATER "
                    "path window, so the state post-dates what it "
                    "supposedly predicts",
        "preserves": "marginal distributions and within-series structure "
                     "on both sides",
        "correct_finding": "no edge; an edge here means the method is "
                           "reading the future"},
    N2_PURE_NOISE: {
        "destroys": "all informational content in the features",
        "preserves": "feature shape, scale and column count",
        "correct_finding": "no feature importance anywhere"},
}


class NullTransformViolation(ValueError):
    pass


@dataclass(frozen=True)
class NullWorld:
    null_type: str
    source_world_id: str
    source_world_hash: str
    fixture_class: str
    world: SyntheticWorld
    transform_parameters: dict

    def manifest(self) -> dict:
        m = self.world.manifest()
        m["fixture_class"] = NULL_FIXTURE
        m["null_type"] = self.null_type
        m["source_world_id"] = self.source_world_id
        m["source_world_hash"] = self.source_world_hash
        m["destroys"] = NULL_CONTRACT[self.null_type]["destroys"]
        m["preserves"] = NULL_CONTRACT[self.null_type]["preserves"]
        m["correct_finding"] = NULL_CONTRACT[self.null_type]["correct_finding"]
        m["transform_parameters"] = dict(self.transform_parameters)
        m["null_hash"] = content_hash(
            {"src": self.source_world_hash, "type": self.null_type,
             "params": dict(self.transform_parameters)})
        return m


def make_null(config: WorldConfig, null_type: str, *,
              block_steps: int = 20, shift_steps: int = 30) -> NullWorld:
    """Build a null from a deterministic source world.

    The source world is regenerated from the same config/seed, so a null
    is reproducible from its declared inputs exactly like a synthetic
    world is.
    """
    if null_type not in NULL_TYPES:
        raise NullTransformViolation(
            "unknown null_type %r; permitted %s" % (null_type,
                                                    list(NULL_TYPES)))
    src = generate_world(config)
    if null_type == N0_ASSOCIATION_DESTROYED:
        if config.n_subjects < 2:
            raise NullTransformViolation(
                "N0 permutes blocks BETWEEN subjects and needs >= 2; with "
                "one subject it would silently become a no-op, which is "
                "worse than refusing")
        if not (1 <= block_steps <= config.n_steps):
            raise NullTransformViolation(
                "block_steps=%d outside [1, %d]" % (block_steps,
                                                    config.n_steps))
        params = {"block_steps": block_steps,
                  "n_blocks": -(-config.n_steps // block_steps)}
    elif null_type == N1_TIME_SHIFTED:
        if not (1 <= shift_steps < config.n_steps):
            raise NullTransformViolation(
                "shift_steps=%d must be in [1, n_steps)" % shift_steps)
        params = {"shift_steps": shift_steps}
    else:
        params = {"noise_stream": "N2"}
    return NullWorld(null_type=null_type, source_world_id=src.world_id,
                     source_world_hash=src.world_hash,
                     fixture_class=NULL_FIXTURE, world=src,
                     transform_parameters=params)


def n0_block_permutation(config: WorldConfig, block_steps: int = 20) -> dict:
    """Which source block each (subject, block) slot draws its FUTURE
    from. Deterministic, and never maps a subject back onto itself for
    a given block -- a permutation with fixed points would leave some
    real associations intact and quietly weaken the null."""
    nw = make_null(config, N0_ASSOCIATION_DESTROYED, block_steps=block_steps)
    n_blocks = nw.transform_parameters["n_blocks"]
    rng = _stream_rng("N0", nw.source_world_hash, config.seed, "perm")
    subs = list(nw.world.subjects)
    mapping = {}
    for b in range(n_blocks):
        order = subs[:]
        for _ in range(64):
            rng.shuffle(order)
            if all(a != c for a, c in zip(subs, order)):
                break
        else:
            order = subs[1:] + subs[:1]      # guaranteed derangement
        mapping[b] = dict(zip(subs, order))
    return mapping


__all__ = ["NULL_TYPES", "N0_ASSOCIATION_DESTROYED", "N1_TIME_SHIFTED",
           "N2_PURE_NOISE", "NULL_CONTRACT", "NullWorld",
           "NullTransformViolation", "make_null", "n0_block_permutation"]
