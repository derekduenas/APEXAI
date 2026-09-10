"""EXPLICITLY SYNTHETIC harness for OPTIONS-PILOT-001.

Everything here is a fixture: the clock is controlled, the forecast
provider computes a distribution from SYNTHETIC parameters that are NOT the
EXP-002 artifact (their digest says so), quotes are generated on demand, and
the risk authority is the SyntheticRiskAuthority. Records produced through
this harness carry data_provenance=SYNTHETIC_FIXTURE and
execution_mode=PROSPECTIVE_ORCHESTRATION: they prove ORCHESTRATION, never
edge, feed behaviour or risk certification.

The forecast provider proves the PROVIDER CONTRACT: given a parameter
artifact of the retained SHAPE (beta over standardised [ret_1, ret_5] with
intercept, Student-t scale law rv_30 * s), it produces a record the boundary
accepts, with the causal time fields filled from the controlled clock."""
from __future__ import annotations

import math

from . import boundary as B
from .clock import Clock, to_utc_string
from .records import FORECAST_TARGET, FORECAST_UNITS, canonical_hash
from .risk_gate import SyntheticRiskAuthority

HARNESS_TOKEN = "I_AM_A_SYNTHETIC_HARNESS"
T0 = 1_789_000_000.0                                  # 2026-09-10T00:26:40Z on the ONE synthetic timeline

# SYNTHETIC parameters of the retained artifact's SHAPE. Not EXP-002's values.
SYNTHETIC_PARAMS = {"model_id": "SYNTHETIC_FIXTURE_MODEL", "features": ["ret_1", "ret_5"], "intercept": True,
                    "beta": [1.0e-5, 2.0e-5, -3.0e-5], "mean": [0.0, 0.0], "sd": [3.0e-4, 7.0e-4],
                    "family": "STUDENT_T", "s": 3.0, "nu": 6.0, "scale_law": "rv_30 * s",
                    "note": "SYNTHETIC: numbers chosen for the fixture; no relation to any experiment"}
SYNTHETIC_ARTIFACT_DIGEST = "SYNTHETIC:" + canonical_hash(SYNTHETIC_PARAMS)[:40]
SYNTHETIC_MODEL_HASH = "SYNTHETIC:" + canonical_hash({"code": "synthetic_harness.forecast_from_params"})[:40]


def forecast_from_params(params: dict, *, ret_1: float, ret_5: float, rv_30: float) -> tuple:
    """location = b0 + b1*z1 + b2*z2 with z = (x - mean) / sd; scale = rv_30 * s.
    This is the SHAPE of the retained artifact's inference formula, applied to
    synthetic inputs. It is not a claim about the artifact's statistical merit."""
    z1 = (ret_1 - params["mean"][0]) / params["sd"][0]
    z2 = (ret_5 - params["mean"][1]) / params["sd"][1]
    b = params["beta"]
    loc = b[0] + b[1] * z1 + b[2] * z2
    scale = rv_30 * params["s"]
    return loc, scale


class SyntheticQuotes:
    """Quote provider with knobs: age (s), sizes, failure, slowness (the
    provider advances the controlled clock while 'working'), override."""

    def __init__(self, harness):
        self.h = harness
        self.age = 1.0
        self.ask, self.bid = 2.50, 2.40
        self.ask_size, self.bid_size = 12, 9
        self.fail_with: Exception | None = None
        self.slow_s = 0.0
        self.override = None                       # callable(contract) -> raw quote, or a constant
        self.calls: list = []

    def __call__(self, contract):
        self.calls.append(dict(contract))
        if self.slow_s:
            self.h.advance(self.slow_s)
        if self.fail_with is not None:
            raise self.fail_with
        if self.override is not None:
            return self.override(contract) if callable(self.override) else self.override
        return {"symbol": contract["symbol"], "expiration": contract["expiration"], "strike": contract["strike"],
                "right": contract["right"], "bid": self.bid, "ask": self.ask, "bid_size": self.bid_size,
                "ask_size": self.ask_size, "timestamp_epoch": self.h.now() - self.age}


class SyntheticHarness:
    def __init__(self, ledger, *, session_id: str = "SYN-SESSION-1", release: str = "synthetic-release", t0: float = T0,
                 risk_refuse_with: str | None = None, symbols=("SPY",)):
        self.t = float(t0)
        self.clock = Clock(lambda: self.t)
        self.ledger = ledger
        self.session_id, self.release = session_id, release
        self.risk = SyntheticRiskAuthority(harness_token=HARNESS_TOKEN, refuse_with=risk_refuse_with)
        self.bd = B.Boundary(ledger, clock=self.clock, provenance="SYNTHETIC_FIXTURE", risk_authority=self.risk,
                             session_id=session_id, release=release)
        self.quotes = SyntheticQuotes(self)
        self.exit_quotes = SyntheticQuotes(self)
        self.exit_quotes.bid, self.exit_quotes.ask = 2.70, 2.80
        self.signal = "LONG"
        self.spot = 646.3
        self.inputs = {"ret_1": 1.0e-4, "ret_5": -2.0e-4, "rv_30": 1.0e-4}
        self.chain = [{"expiration": "2026-10-09", "strike": k, "right": r} for k in (640.0, 645.0, 650.0, 655.0)
                      for r in ("CALL", "PUT")] + [{"expiration": "2026-09-18", "strike": 645.0, "right": "CALL"}]
        self.forecast_override = None
        self.symbols = list(symbols)

    # controlled clock
    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)

    # providers
    def forecast_fn(self, symbol: str, as_of: float) -> dict:
        if self.forecast_override is not None:
            return self.forecast_override(symbol, as_of) if callable(self.forecast_override) else self.forecast_override
        return self.base_forecast(symbol, as_of)

    def base_forecast(self, symbol: str, as_of: float) -> dict:
        """The synthetic provider proper (ignores forecast_override)."""
        loc, scale = forecast_from_params(SYNTHETIC_PARAMS, **self.inputs)
        reference = math.floor(as_of / 60.0) * 60.0 - 60.0          # the last COMPLETED 1-min bar
        available = reference + 60.0                                  # bar_complete instant
        return {"symbol": symbol, "target": FORECAST_TARGET, "units": FORECAST_UNITS, "horizon_minutes": 15,
                "family": "STUDENT_T", "location": loc, "scale": scale, "nu": SYNTHETIC_PARAMS["nu"],
                "model_id": SYNTHETIC_PARAMS["model_id"], "model_hash": SYNTHETIC_MODEL_HASH,
                "params_hash": "SYNTHETIC:" + canonical_hash(SYNTHETIC_PARAMS)[:16],
                "artifact_digest": SYNTHETIC_ARTIFACT_DIGEST,
                "reference_time_utc": to_utc_string(reference), "target_end_utc": to_utc_string(reference + 900.0),
                "input_event_time_utc": to_utc_string(reference), "input_available_utc": to_utc_string(available),
                "input_cutoff_utc": to_utc_string(available), "created_utc": to_utc_string(as_of),
                "direction_signal": self.signal, "validation_status": "SYNTHETIC_FIXTURE: no validation claim",
                "inputs": dict(self.inputs)}

    def signal_fn(self, symbol: str, as_of: float):
        return self.signal

    def chain_fn(self, symbol: str, as_of: float):
        return self.chain

    def spot_fn(self, symbol: str, as_of: float):
        return self.spot

    def sources(self) -> dict:
        return {"forecast_fn": self.forecast_fn, "signal_fn": self.signal_fn, "chain_fn": self.chain_fn,
                "spot_fn": self.spot_fn, "quote_fn": self.quotes, "exit_quote_fn": self.exit_quotes}


def make_harness(ledger, **kw) -> SyntheticHarness:
    return SyntheticHarness(ledger, **kw)
