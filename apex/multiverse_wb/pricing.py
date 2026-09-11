"""Reference pricing, IV inversion, Greeks, American engine, instrument conventions (M4).

European reference: Black-Scholes-Merton with continuous dividend yield q and rate r.
    d1 = [ln(S/K) + (r - q + sigma^2/2) T] / (sigma sqrt T),  d2 = d1 - sigma sqrt T
    C = S e^{-qT} N(d1) - K e^{-rT} N(d2);   P = K e^{-rT} N(-d2) - S e^{-qT} N(-d1)
American: Cox-Ross-Rubinstein binomial with early exercise at every node (its own engine; the
European formula is refused for AMERICAN instruments unless an approximation is DECLARED).
Quotes: crossed, non-positive, zero-size or stale quotes are refused with a reason; nothing is
'cleaned' into a usable price. Instrument metadata must state exercise style, settlement,
multiplier (100) and whether the contract is adjusted (adjusted contracts refuse)."""
from __future__ import annotations

import math

from scipy import optimize, stats

N = stats.norm.cdf
n = stats.norm.pdf


class PricingRefused(ValueError):
    pass


def _pos(x, what):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0:
        raise PricingRefused("%s must be a positive finite real, got %r" % (what, x))
    return float(x)


# ---------------------------------------------------------------- instruments

EXERCISE = ("EUROPEAN", "AMERICAN")
SETTLEMENT = ("PHYSICAL", "CASH")


def instrument(*, symbol: str, expiration: str, strike: float, right: str, exercise: str, settlement: str,
               multiplier: float = 100.0, adjusted: bool = False, dividend_yield: float = 0.0) -> dict:
    if right not in ("CALL", "PUT") or exercise not in EXERCISE or settlement not in SETTLEMENT:
        raise PricingRefused("INSTRUMENT_CONVENTION_INVALID")
    if adjusted:
        raise PricingRefused("ADJUSTED_CONTRACT_REFUSED: non-standard deliverable; not priced by this engine")
    if multiplier != 100.0:
        raise PricingRefused("MULTIPLIER_NOT_100: %r" % multiplier)
    _pos(strike, "strike")
    return {"symbol": symbol, "expiration": expiration, "strike": float(strike), "right": right, "exercise": exercise,
            "settlement": settlement, "multiplier": 100.0, "adjusted": False, "dividend_yield": float(dividend_yield),
            "early_exercise_note": ("AMERICAN: exercise/assignment can occur before expiration (dividend-related cases included); "
                                    "the pilot's long-only rule can be assigned nothing but may be exercised early only by choice")
                                   if exercise == "AMERICAN" else "EUROPEAN: exercise at expiration only"}


# ---------------------------------------------------------------- quotes

def sanitize_quote(q: dict, *, now: float, max_age_s: float = 15.0) -> dict:
    for k in ("bid", "ask", "bid_size", "ask_size", "timestamp_epoch"):
        if k not in q:
            raise PricingRefused("QUOTE_FIELD_MISSING: %s" % k)
    bid, ask = q["bid"], q["ask"]
    for v, k in ((bid, "bid"), (ask, "ask")):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise PricingRefused("QUOTE_NONFINITE: %s" % k)
    if ask <= 0:
        raise PricingRefused("QUOTE_NO_ASK")
    if bid < 0 or ask < bid:
        raise PricingRefused("QUOTE_CROSSED_OR_NEGATIVE: bid %r ask %r" % (bid, ask))
    if type(q["bid_size"]) is not int or type(q["ask_size"]) is not int or q["ask_size"] < 1:
        raise PricingRefused("QUOTE_SIZE_INVALID")
    age = now - q["timestamp_epoch"]
    if age < 0 or age > max_age_s:
        raise PricingRefused("QUOTE_STALE_OR_FUTURE: age %.1fs" % age)
    mid = 0.5 * (bid + ask)
    return {"bid": float(bid), "ask": float(ask), "mid": mid, "spread": float(ask - bid), "spread_rel": (ask - bid) / mid if mid > 0 else None,
            "bid_size": q["bid_size"], "ask_size": q["ask_size"], "age_s": age, "usable_for_iv": bid > 0}


# ---------------------------------------------------------------- European reference

def bsm_price(*, S, K, T, sigma, r=0.0, q=0.0, right="CALL") -> float:
    S, K, T, sigma = _pos(S, "S"), _pos(K, "K"), _pos(T, "T"), _pos(sigma, "sigma")
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / sq
    d2 = d1 - sq
    if right == "CALL":
        return S * math.exp(-q * T) * N(d1) - K * math.exp(-r * T) * N(d2)
    return K * math.exp(-r * T) * N(-d2) - S * math.exp(-q * T) * N(-d1)


def bsm_greeks(*, S, K, T, sigma, r=0.0, q=0.0, right="CALL") -> dict:
    S, K, T, sigma = _pos(S, "S"), _pos(K, "K"), _pos(T, "T"), _pos(sigma, "sigma")
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / sq
    d2 = d1 - sq
    eq, er = math.exp(-q * T), math.exp(-r * T)
    delta = eq * N(d1) if right == "CALL" else -eq * N(-d1)
    gamma = eq * n(d1) / (S * sq)
    vega = S * eq * n(d1) * math.sqrt(T)
    theta_common = -S * eq * n(d1) * sigma / (2 * math.sqrt(T))
    theta = (theta_common - r * K * er * N(d2) + q * S * eq * N(d1)) if right == "CALL" else (theta_common + r * K * er * N(-d2) - q * S * eq * N(-d1))
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta_per_year": theta, "convention": "per unit underlying; vega per 1.00 vol; theta per year"}


def no_arb_bounds(*, S, K, T, r=0.0, q=0.0, right="CALL") -> tuple:
    if right == "CALL":
        return max(0.0, S * math.exp(-q * T) - K * math.exp(-r * T)), S * math.exp(-q * T)
    return max(0.0, K * math.exp(-r * T) - S * math.exp(-q * T)), K * math.exp(-r * T)


def implied_vol(*, price, S, K, T, r=0.0, q=0.0, right="CALL", lo=1e-4, hi=5.0) -> dict:
    lb, ub = no_arb_bounds(S=S, K=K, T=T, r=r, q=q, right=right)
    if not (lb - 1e-12 <= price <= ub + 1e-12):
        raise PricingRefused("PRICE_OUTSIDE_NO_ARBITRAGE_BOUNDS: %.4f not in [%.4f, %.4f]" % (price, lb, ub))
    if price <= lb + 1e-10:
        raise PricingRefused("PRICE_AT_INTRINSIC: implied volatility is not identified")
    f = lambda s: bsm_price(S=S, K=K, T=T, sigma=s, r=r, q=q, right=right) - price
    try:
        iv = optimize.brentq(f, lo, hi, xtol=1e-10, maxiter=200)
    except ValueError as e:
        raise PricingRefused("IV_INVERSION_FAILED: %s" % e)
    return {"iv": iv, "method": "brentq on BSM price", "bounds": [lo, hi], "residual": f(iv)}


# ---------------------------------------------------------------- American (CRR)

def crr_american(*, S, K, T, sigma, r=0.0, q=0.0, right="CALL", steps: int = 400) -> float:
    S, K, T, sigma = _pos(S, "S"), _pos(K, "K"), _pos(T, "T"), _pos(sigma, "sigma")
    dt = T / steps
    u = math.exp(sigma * math.sqrt(dt)); d = 1 / u
    p = (math.exp((r - q) * dt) - d) / (u - d)
    if not (0 < p < 1):
        raise PricingRefused("CRR_PROBABILITY_OUT_OF_RANGE: increase steps")
    disc = math.exp(-r * dt)
    ST = [S * u ** j * d ** (steps - j) for j in range(steps + 1)]
    V = [max(0.0, (s - K) if right == "CALL" else (K - s)) for s in ST]
    for i in range(steps - 1, -1, -1):
        for j in range(i + 1):
            s = S * u ** j * d ** (i - j)
            cont = disc * (p * V[j + 1] + (1 - p) * V[j])
            ex = max(0.0, (s - K) if right == "CALL" else (K - s))
            V[j] = max(cont, ex)
    return V[0]


def price(inst: dict, *, S, T, sigma, r=0.0, approximation: str | None = None, steps: int = 400) -> dict:
    """The engine matching the instrument's exercise style. European formula on an AMERICAN instrument only
    with a DECLARED approximation, and the record says so."""
    q = inst.get("dividend_yield", 0.0)
    if inst["exercise"] == "EUROPEAN":
        return {"price": bsm_price(S=S, K=inst["strike"], T=T, sigma=sigma, r=r, q=q, right=inst["right"]), "engine": "BSM_EUROPEAN", "approximation": None}
    if approximation == "EUROPEAN_APPROX":
        return {"price": bsm_price(S=S, K=inst["strike"], T=T, sigma=sigma, r=r, q=q, right=inst["right"]), "engine": "BSM_EUROPEAN",
                "approximation": "EUROPEAN_APPROX declared: early-exercise premium ignored; justified only for long calls on non-dividend names or far-from-exercise puts"}
    if approximation is not None:
        raise PricingRefused("UNKNOWN_APPROXIMATION: %r" % approximation)
    return {"price": crr_american(S=S, K=inst["strike"], T=T, sigma=sigma, r=r, q=q, right=inst["right"], steps=steps), "engine": "CRR_AMERICAN_%d" % steps,
            "approximation": None}
