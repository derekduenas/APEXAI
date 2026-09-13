"""WHO ACTUALLY READS AN EXTERNAL OBSERVATION — the registry that makes `USED` mean something.

THE PROBLEM THIS SOLVES. The seam used to mark an observation `USED` whenever the caller passed a non-empty
`feeds` list. That is a label, not a read. It proved that somebody intended the observation to matter; it proved
nothing about whether any model, setup detector or scorer ever looked at it. A decision record claiming `USED` on
that basis overstates what the eyes contributed, and an overstated contribution is worse than none: it is the
exact input a later "was TradingView any use?" review would be built on.

WHAT A CONSUMER IS. A named, implemented, DETERMINISTIC function that takes one normalized observation and returns
a derived value, or `None` for "I read it and it told me nothing". Registering one asserts that the function
exists and runs; the read record it produces carries the consumer's name, its actual implementation path, the
value it derived and a digest of that value, so a reviewer can re-run the same function on the same observation
and get the same answer. That is what "reproducible evidence of the read" means here.

**THE PRODUCTION REGISTRY IS EMPTY, AND THAT IS THE CORRECT STATE.**

TradingView context is EXTERNAL_CONTEXT_ONLY. Nothing in APEX may act on it -- not the forecast, not the variance
model, not the expression rule, not the funnel, not risk. So there is no legitimate production consumer to
register, and consequently **no production decision record can report `USED`**. They report ATTACHED_CONTEXT or
RETRIEVED_UNUSED, which is the honest description of what is actually happening: the observation is recorded
against the decision, and nothing read it.

That is not a gap to be quietly closed. A consumer may only be registered when a real model or detector is
genuinely wired to read the value AND that wiring has been reviewed against the authority law -- because the
moment something reads external context and changes its output, the question of whether TradingView has become a
signal stops being rhetorical. `assert_no_unreviewed_production_consumer()` fails the build if one appears without
being named in `REVIEWED_PRODUCTION_CONSUMERS`."""
from __future__ import annotations

import hashlib
import json

from . import normalize as N


class ConsumerRefused(ValueError):
    """A consumer that cannot be trusted to have read what it claims. Named, never silent."""


# name -> record. EMPTY in production, by design and by test.
_REGISTRY: dict = {}

# A consumer may only appear in the live registry if it is named here, i.e. a person has reviewed the wiring
# against the authority law. The tuple is empty because nothing reads TradingView context today.
REVIEWED_PRODUCTION_CONSUMERS: tuple = ()

LAW = (
    "A consumer READS an observation and returns a derived value. Registering one is a claim that a real, "
    "reviewed reader exists. No production consumer of TradingView context is registered, because nothing in "
    "APEX may act on external context; production decision records therefore report ATTACHED_CONTEXT, never USED.")


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def register(name: str, *, tool: str, fn, purpose: str, production: bool = False) -> None:
    """Register a reader. `production=True` requires the name to have been reviewed into
    REVIEWED_PRODUCTION_CONSUMERS first, so a consumer cannot be added to the live path by import alone."""
    if not callable(fn):
        raise ConsumerRefused("CONSUMER_NOT_CALLABLE: %r" % (name,))
    canonical_tool = N.canonical(tool)
    if production and name not in REVIEWED_PRODUCTION_CONSUMERS:
        raise ConsumerRefused(
            "CONSUMER_NOT_REVIEWED: %r is not in REVIEWED_PRODUCTION_CONSUMERS. A reader that changes what a "
            "decision sees must be reviewed against the authority law before it can run on the live path." % (name,))
    _REGISTRY[name] = {"name": name, "tool": canonical_tool, "fn": fn, "purpose": purpose,
                       "implementation": "%s:%s" % (getattr(fn, "__module__", "?"), getattr(fn, "__qualname__", "?")),
                       "production": bool(production)}


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)


def registered(tool: str | None = None) -> list:
    t = N.canonical(tool) if tool else None
    return [dict(r, fn=None) for r in _REGISTRY.values() if t is None or r["tool"] == t]


def run(obs: dict) -> list:
    """Run every consumer registered for this observation's tool and return their READ RECORDS.

    A consumer that returns None read the observation and derived nothing -- that is recorded as a read with a
    null value, not dropped, because "looked and found nothing" is a different fact from "never looked". A
    consumer that RAISES did not read it: the failure is recorded and produces no USED."""
    out = []
    for r in _REGISTRY.values():
        if r["tool"] != N.canonical(obs.get("tool") or ""):
            continue
        try:
            value = r["fn"](obs)
        except Exception as e:                                   # noqa: BLE001 - a failed read is not a read
            out.append({"consumer": r["name"], "implementation": r["implementation"], "tool": r["tool"],
                        "read_ok": False, "value": None, "value_digest": None,
                        "why": "CONSUMER_RAISED: %s: %s" % (type(e).__name__, str(e)[:160])})
            continue
        out.append({"consumer": r["name"], "implementation": r["implementation"], "tool": r["tool"],
                    "read_ok": True, "value": value, "value_digest": _digest(value),
                    "observation_key": N.observation_key(obs),
                    "reproducible": ("re-run %s on the observation with this observation_key to obtain the same "
                                     "value_digest" % r["implementation"])})
    return out


def successful_reads(records: list) -> list:
    """Only a read that SUCCEEDED counts toward USED."""
    return [r for r in (records or []) if r.get("read_ok")]


def assert_no_unreviewed_production_consumer() -> None:
    """Fails the build if a production consumer appears without review. Called by a test."""
    rogue = [n for n, r in _REGISTRY.items() if r["production"] and n not in REVIEWED_PRODUCTION_CONSUMERS]
    if rogue:
        raise ConsumerRefused("UNREVIEWED_PRODUCTION_CONSUMERS: %s" % sorted(rogue))


def describe() -> dict:
    return {"law": LAW, "n_registered": len(_REGISTRY),
            "reviewed_production_consumers": list(REVIEWED_PRODUCTION_CONSUMERS),
            "registered": registered(),
            "production_registry_is_empty": not any(r["production"] for r in _REGISTRY.values())}
