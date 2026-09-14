"""PREMARKET_RUNTIME_V1 -- the ONE place where the premarket path can be redirected, and the one place that
reports it.

WHY THIS EXISTS AT ALL. R4 requires the synthetic morning to run through the REAL production entry point. A
synthetic morning needs a controlled clock, a frozen provider transport, a recorded Captain response and a
scratch output root. Every previous audit obtained those by building a parallel harness -- and every time, the
harness proved something the production path did not do.

So the seams live in production, in one module, and they are LOUD. `substitutions()` returns exactly which of
them are active, it is embedded in every journal event and every stage record, and it is empty on a clean
environment. A synthetic packet therefore cannot masquerade as a real one: the record says what was replaced.

THE STANDING RISK, stated rather than hidden: a test hook in production code is a hook an operator could set by
accident. The mitigations are (a) `substitutions()` is recorded everywhere, (b) the prepared production shell is
asserted to export none of these names, and (c) a test asserts the clean-environment path is fully real.
"""
from __future__ import annotations

import os
import pathlib

SCHEMA = "PREMARKET_RUNTIME_V1"

ENV_ROOT = "APEX_PREMARKET_ROOT"            # output root for packets, runs and the journal
ENV_CLOCK_FILE = "APEX_PREMARKET_CLOCK_FILE"  # a file holding one float epoch; re-read on every call
ENV_NOW = "APEX_PREMARKET_NOW"              # a fixed ISO-8601 instant
ENV_TRANSPORT = "APEX_PREMARKET_TRANSPORT"  # "module:callable" replacing the EODHD network call
ENV_CAPTAIN = "APEX_PREMARKET_CAPTAIN"      # "module:callable" replacing the Captain model transport
ENV_CRASH = "APEX_PREMARKET_CRASH_AFTER"    # kill THIS process at a named phase boundary; never alters output
ENV_TZ_BINDING = "APEX_PREMARKET_TZ_BINDING"  # path to the installed timezone binding to check against

ENV_NAMES = (ENV_ROOT, ENV_CLOCK_FILE, ENV_NOW, ENV_TRANSPORT, ENV_CAPTAIN, ENV_CRASH, ENV_TZ_BINDING)

DEFAULT_ROOT = "results/frontier/premarket"


def root() -> pathlib.Path:
    return pathlib.Path(os.environ.get(ENV_ROOT) or DEFAULT_ROOT)


def now_utc():
    """The premarket path's single clock reading. Real unless a substitution is declared."""
    import pandas as pd
    f = os.environ.get(ENV_CLOCK_FILE)
    if f:
        return pd.Timestamp(float(pathlib.Path(f).read_text().strip()), unit="s", tz="UTC")
    fixed = os.environ.get(ENV_NOW)
    if fixed:
        ts = pd.Timestamp(fixed)
        return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
    return pd.Timestamp.now(tz="UTC")


def now_et():
    return now_utc().tz_convert("America/New_York")


def _resolve(spec: str):
    mod, _, fn = spec.partition(":")
    if not fn:
        raise ValueError("BAD_CALLABLE_SPEC: %r -- expected 'module:callable'" % spec)
    import importlib
    return getattr(importlib.import_module(mod), fn)


def transport():
    """The EODHD chunk fetch actually used. None means 'the real one, resolved at call site'."""
    spec = os.environ.get(ENV_TRANSPORT)
    return _resolve(spec) if spec else None


def captain():
    spec = os.environ.get(ENV_CAPTAIN)
    return _resolve(spec) if spec else None


def substitutions() -> dict:
    """Exactly which seams are redirected right now. EMPTY dict == fully real."""
    out = {}
    for name in ENV_NAMES:
        v = os.environ.get(name)
        if v:
            out[name] = v
    return out


def realism() -> str:
    return "FULLY_REAL" if not substitutions() else "SUBSTITUTED"
