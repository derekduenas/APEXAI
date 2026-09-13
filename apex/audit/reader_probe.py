"""CONSUMED evidence — instrumentation at the ACTUAL reader.

`usable_value(snapshot, name)` is the one accessor production code uses to read a Twin field. Its callers on this
line are `TwinSources.signal_fn` (ret_15), `TwinSources.spot_fn` (last_bar_close) and `TwinSources.funnel_fn`
(last_bar_close). Wrapping it records WHICH FIELD of WHICH SNAPSHOT was read BY WHICH OPERATION.

That is a genuine read, not a reference: the value crossed the boundary into a caller. It still says nothing about
whether the read changed any decision -- that is BEHAVIORAL_EFFECT, established separately by perturbation."""
from __future__ import annotations

import contextlib
import inspect


class ReaderProbe:
    def __init__(self):
        self.reads: list = []

    @contextlib.contextmanager
    def instrument(self):
        from apex.pulse_options import snapshot as SN
        from apex.pulse_options import sources as SRC
        original = SN.usable_value

        def probed(snap, name):
            value = original(snap, name)
            caller = "unknown"
            fr = inspect.currentframe()
            try:
                outer = fr.f_back
                caller = "%s.%s" % (outer.f_globals.get("__name__", "?"), outer.f_code.co_name)
            finally:
                del fr
            self.reads.append({"snapshot_id": (snap or {}).get("snapshot_id"),
                               "field": name, "value": value,
                               "quality": ((snap or {}).get("fields", {}).get(name) or {}).get("quality"),
                               "read_by_operation": caller})
            return value
        SN.usable_value = probed
        SRC.usable_value = probed
        try:
            yield self
        finally:
            SN.usable_value = original
            SRC.usable_value = original

    def consumed_fields(self, snapshot_id=None) -> dict:
        out = {}
        for r in self.reads:
            if snapshot_id and r["snapshot_id"] != snapshot_id:
                continue
            out.setdefault(r["field"], set()).add(r["read_by_operation"])
        return {k: sorted(v) for k, v in out.items()}
