"""Optional foundation-model benchmarks (M3): Chronos-2 and TimesFM 2.5 adapter interfaces.

Neither model's weights are present in the authorized environment, and no weights are downloaded by
this build. The adapters therefore report BLOCKED_RESOURCE (no checkpoint available offline) and, for
TimesFM 3.0, BLOCKED_LICENSE (default 3.0 weights are restricted to non-commercial, non-production
use per the repository notice and are EXCLUDED from this business build). Interface tests cover the
input transform, output semantics and the block states; they do not count an unavailable benchmark as
an implemented model."""
from __future__ import annotations

import importlib

from .contracts import ForecastObject, ModelRefused, UnsupportedOutput

CHRONOS2 = {"name": "Chronos-2", "checkpoint": "amazon/chronos-2 (to be pinned at review)", "package": "chronos",
            "supplies": ("quantiles",), "license_status": "REVIEW_REQUIRED",
            "training_overlap": "UNKNOWN — a 2025 pretrained checkpoint cannot be presented as available in 2019"}
TIMESFM25 = {"name": "TimesFM 2.5", "checkpoint": "google/timesfm-2.5-200m-pytorch (to be pinned at review)", "package": "timesfm",
             "supplies": ("mean", "quantiles"), "license_status": "Apache-2.0 per repository notice (weights through 2.5)",
             "training_overlap": "UNKNOWN"}
TIMESFM30 = {"name": "TimesFM 3.0", "checkpoint": "google/timesfm-3.0-pytorch", "package": "timesfm",
             "supplies": ("mean", "quantiles"), "license_status": "non-commercial / non-production restriction on default weights",
             "training_overlap": "UNKNOWN"}


class FoundationAdapter:
    def __init__(self, spec: dict, *, excluded: bool = False, why_excluded: str | None = None):
        self.spec, self.excluded, self.why_excluded = spec, excluded, why_excluded

    def availability(self) -> dict:
        if self.excluded:
            return {"state": "BLOCKED_LICENSE", "why": self.why_excluded, "model": self.spec["name"]}
        try:
            importlib.import_module(self.spec["package"])
            pkg = True
        except ImportError:
            pkg = False
        return {"state": "BLOCKED_RESOURCE" if not pkg else "INTERFACE_ONLY_NO_WEIGHTS",
                "why": ("package %r not installed in the authorized environment; no weights downloaded" % self.spec["package"]) if not pkg
                else "package present; checkpoint not pinned/downloaded under this mandate", "model": self.spec["name"]}

    @staticmethod
    def input_transform(closes: list, *, context_len: int) -> dict:
        """The declared transform: log returns of the last `context_len` completed closes, in bar order."""
        import math
        if len(closes) < context_len + 1:
            raise ModelRefused("CONTEXT_TOO_SHORT")
        c = closes[-(context_len + 1):]
        return {"series": [math.log(c[i] / c[i - 1]) for i in range(1, len(c))], "transform": "log_return_1m", "context_len": context_len}

    def forecast(self, *a, **k) -> ForecastObject:
        st = self.availability()
        raise UnsupportedOutput("%s: %s — %s" % (self.spec["name"], st["state"], st["why"]))

    def describe(self) -> dict:
        return {**self.spec, **self.availability(), "counts_as_implemented_model": False}


def adapters() -> dict:
    return {"chronos2": FoundationAdapter(CHRONOS2),
            "timesfm25": FoundationAdapter(TIMESFM25),
            "timesfm30": FoundationAdapter(TIMESFM30, excluded=True,
                                           why_excluded="TimesFM 3.0 default weights are non-commercial/non-production; excluded from this business build")}
