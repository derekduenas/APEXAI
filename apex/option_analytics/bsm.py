"""Black-Scholes-Merton — the baseline/cross-check model, never the
sole canonical model for US equity options (which are American-style;
see american_binomial.py). Analytic pricing + Greeks are closed-form
and independently checkable by hand; the IV solver uses scipy's Brent's
method (a generic, well-tested numerical root-finder, not options-
specific software) so that IV solving and American-model pricing stay
methodologically independent of each other.

All inputs here are already dividend-adjusted (spot = raw_spot -
PV(dividends)) -- this module is pure Black-Scholes math and does not
know about discrete dividends itself; see dividends.py for that
adjustment, applied by the caller (canonical_state.py).

Units: vega is per 1.0 (100 vol points) of sigma; theta is per YEAR.
Callers divide by 100 / 365 respectively for the conventional "per 1
vol point" / "per calendar day" quoting convention -- this module
reports the raw calculus derivative, never a pre-scaled number, so the
scaling convention is visible and auditable at the call site.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from scipy.optimize import brentq
from scipy.stats import norm

from apex.option_analytics import OPTION_ANALYTICS_POWER

OPTION_TYPES = ("call", "put")
IV_LOWER_BOUND = 1e-6
IV_UPPER_BOUND = 5.0     # 500% annualized vol -- generous, not infinite


class BSMError(RuntimeError):
    pass


@dataclass(frozen=True)
class BSMGreeks:
    option_type: str
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    decision_power: str = OPTION_ANALYTICS_POWER

    def as_record(self) -> dict:
        return asdict(self)


def _d1_d2(spot, strike, time_to_expiry_years, rate, sigma):
    if spot <= 0 or strike <= 0:
        raise BSMError("spot and strike must be positive")
    if time_to_expiry_years <= 0:
        raise BSMError("time_to_expiry_years must be positive")
    if sigma <= 0:
        raise BSMError("sigma must be positive")
    sqrt_t = math.sqrt(time_to_expiry_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma ** 2) * time_to_expiry_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return d1, d2


def price(*, option_type: str, spot: float, strike: float,
         time_to_expiry_years: float, rate: float, sigma: float) -> float:
    if option_type not in OPTION_TYPES:
        raise BSMError(f"unknown option_type {option_type!r}")
    d1, d2 = _d1_d2(spot, strike, time_to_expiry_years, rate, sigma)
    disc_k = strike * math.exp(-rate * time_to_expiry_years)
    if option_type == "call":
        return spot * norm.cdf(d1) - disc_k * norm.cdf(d2)
    return disc_k * norm.cdf(-d2) - spot * norm.cdf(-d1)


def greeks(*, option_type: str, spot: float, strike: float,
          time_to_expiry_years: float, rate: float, sigma: float) -> BSMGreeks:
    if option_type not in OPTION_TYPES:
        raise BSMError(f"unknown option_type {option_type!r}")
    d1, d2 = _d1_d2(spot, strike, time_to_expiry_years, rate, sigma)
    sqrt_t = math.sqrt(time_to_expiry_years)
    disc_k = strike * math.exp(-rate * time_to_expiry_years)
    pdf_d1 = norm.pdf(d1)

    px = (spot * norm.cdf(d1) - disc_k * norm.cdf(d2) if option_type == "call"
         else disc_k * norm.cdf(-d2) - spot * norm.cdf(-d1))
    delta = norm.cdf(d1) if option_type == "call" else norm.cdf(d1) - 1.0
    gamma = pdf_d1 / (spot * sigma * sqrt_t)
    vega = spot * pdf_d1 * sqrt_t
    if option_type == "call":
        theta = (-(spot * pdf_d1 * sigma) / (2 * sqrt_t)
                 - rate * disc_k * norm.cdf(d2))
        rho = strike * time_to_expiry_years * math.exp(-rate * time_to_expiry_years) * norm.cdf(d2)
    else:
        theta = (-(spot * pdf_d1 * sigma) / (2 * sqrt_t)
                 + rate * disc_k * norm.cdf(-d2))
        rho = -strike * time_to_expiry_years * math.exp(-rate * time_to_expiry_years) * norm.cdf(-d2)

    return BSMGreeks(option_type=option_type, price=px, delta=delta, gamma=gamma,
                     theta=theta, vega=vega, rho=rho)


def implied_volatility(*, option_type: str, market_price: float, spot: float,
                       strike: float, time_to_expiry_years: float,
                       rate: float) -> float | None:
    """Brent's method root-find on sigma. Returns None (UNKNOWN) --
    never a guessed number -- when the market price falls outside what
    ANY volatility in [IV_LOWER_BOUND, IV_UPPER_BOUND] can produce
    (e.g. a price below intrinsic that slipped past the no-arbitrage
    gate, or a price so rich no finite vol reaches it)."""
    if option_type not in OPTION_TYPES:
        raise BSMError(f"unknown option_type {option_type!r}")

    def f(sigma):
        return price(option_type=option_type, spot=spot, strike=strike,
                    time_to_expiry_years=time_to_expiry_years, rate=rate,
                    sigma=sigma) - market_price

    lo, hi = f(IV_LOWER_BOUND), f(IV_UPPER_BOUND)
    if lo * hi > 0:
        return None
    return brentq(f, IV_LOWER_BOUND, IV_UPPER_BOUND, xtol=1e-8, rtol=1e-10, maxiter=200)
