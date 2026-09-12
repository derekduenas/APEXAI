"""WM0E_R1_HOLDOUT_V0 -- fresh, never-inspected acceptance seeds.

The 25 seeds of NULL_COURT_V0 have been observed, three times. They are
now WM_0E_DEVELOPMENT_NULL_SET_V0: usable for diagnosis, regression
reproduction and implementation debugging; NOT usable as acceptance
evidence for the repaired statistic. Nothing here discards them or
pretends they are unseen.

The acceptance seeds are derived deterministically from a precommitted
namespace and an index. Nobody chose them. Indices whose seed collides
with the development set (or with an earlier holdout seed) are SKIPPED
and the skip is recorded, so the derivation stays a pure function of
the namespace.

    seed(i) = int.from_bytes(sha256(namespace + "|" + str(i))[:8], "big")
              mod (2**31 - 1)
"""
from __future__ import annotations

import hashlib

from apex.world_model.canonical import content_hash
from apex.world_model.court import SEED_SET as _V0_SEEDS

HOLDOUT_VERSION = "WM0E_R1_HOLDOUT_V0"
HOLDOUT_NAMESPACE = "WM0E_R1_HOLDOUT_V0"
HOLDOUT_SIZE = 50
SEED_MODULUS = 2 ** 31 - 1

DEVELOPMENT_SET_NAME = "WM_0E_DEVELOPMENT_NULL_SET_V0"
WM_0E_DEVELOPMENT_NULL_SET_V0 = tuple(_V0_SEEDS)      # observed; not acceptance
DEVELOPMENT_SET_ROLE = ("diagnosis, regression reproduction, implementation "
                        "debugging. NOT acceptance evidence for any statistic "
                        "revised after observing it.")


def derive_seed(namespace: str, index: int) -> int:
    h = hashlib.sha256(("%s|%d" % (namespace, index)).encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") % SEED_MODULUS


def derive_holdout(namespace: str = HOLDOUT_NAMESPACE,
                   size: int = HOLDOUT_SIZE,
                   excluded: tuple = WM_0E_DEVELOPMENT_NULL_SET_V0) -> dict:
    """Ordered seeds + every skipped index, as a pure function of inputs."""
    seeds, skipped, i = [], [], 0
    ex = set(excluded)
    while len(seeds) < size:
        s = derive_seed(namespace, i)
        if s in ex or s in seeds:
            skipped.append({"index": i, "seed": s,
                            "reason": "in development set" if s in ex
                            else "duplicate"})
        else:
            seeds.append(s)
        i += 1
    return {"holdout_version": HOLDOUT_VERSION, "namespace": namespace,
            "size": size, "algorithm": "int.from_bytes(sha256(namespace|"
            "index)[:8], big) mod (2**31-1); indices whose seed is in the "
            "excluded set or already drawn are skipped and recorded",
            "indices_consumed": i, "skipped": skipped,
            "seeds": seeds, "seed_set_hash": content_hash(seeds),
            "excluded_set_name": DEVELOPMENT_SET_NAME,
            "excluded_set_hash": content_hash(list(excluded)),
            "excluded_set_size": len(excluded)}


HOLDOUT = derive_holdout()
HOLDOUT_SEEDS = tuple(HOLDOUT["seeds"])
HOLDOUT_SEED_SET_HASH = HOLDOUT["seed_set_hash"]

assert len(HOLDOUT_SEEDS) == HOLDOUT_SIZE
assert not set(HOLDOUT_SEEDS) & set(WM_0E_DEVELOPMENT_NULL_SET_V0)
assert len(set(HOLDOUT_SEEDS)) == HOLDOUT_SIZE
