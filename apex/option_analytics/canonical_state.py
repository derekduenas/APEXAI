"""OptionAnalyticsState — the assembled CANONICAL ANALYTICS STATE.
Wires no-arbitrage gates, rate curve, dividends, exact time-to-expiry,
BSM, American binomial, model disagreement, and the IV_BID/MID/ASK
triple into one object. This is what apex.options_research consumes
(read-only) as its own computed alternative to a vendor Greek field --
it never overwrites OptionMarketState's raw vendor fields, it is a
separate, explicitly APEX-COMPUTED state so the two are never
conflated.

Very short-dated contracts (< SHORT_DATED_THRESHOLD_DAYS) are flagged
`short_dated=True` and get `quality` capped at MODERATE regardless of
how clean the numbers look -- theta/gamma blow up near expiry and a
model that "looks confident" there is exactly the failure mode this
package exists to prevent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.option_analytics import OPTION_ANALYTICS_POWER
from apex.option_analytics import american_binomial as american_mod
from apex.option_analytics import bsm as bsm_mod
from apex.option_analytics.dividends import DividendSchedule, pv_of_dividends
from apex.option_analytics.iv_triple import IVTriple, solve_iv_triple
from apex.option_analytics.live_quality import classify_live_quality
from apex.option_analytics.live_quality import rank as quality_rank
from apex.option_analytics.model_disagreement import GreekModelRange, build_range
from apex.option_analytics.no_arbitrage import PriceSanityVerdict, check_price_sanity
from apex.option_analytics.rate_curve import RiskFreeCurve, rate_for_tenor
from apex.option_analytics.time_to_expiry import year_fraction

SHORT_DATED_THRESHOLD_DAYS = 2.0
STATE_QUALITY_LEVELS = ("HIGH", "MODERATE", "LOW", "REFUSED")


class CanonicalStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class OptionAnalyticsState:
    symbol: str
    option_type: str
    spot: float
    strike: float
    expiry_date: str
    time_to_expiry_years: float
    short_dated: bool
    rate: float | None
    dividend_pv: float | None
    price_sanity: dict            # PriceSanityVerdict.as_record()
    iv: dict | None                # IVTriple.as_record(), None if REFUSED before solving
    delta: dict | None             # GreekModelRange.as_record()
    gamma: dict | None
    theta: dict | None
    vega: dict | None
    rho: dict | None
    state_quality: str
    refusal_reason: str | None
    known_from: str
    as_of: str
    live_quality: dict | None = None   # LiveQuoteQuality.as_record(), None when not measured
    schema_version: str = "OPTION_ANALYTICS_SCHEMA_V1"
    decision_power: str = OPTION_ANALYTICS_POWER

    def __post_init__(self):
        if self.state_quality not in STATE_QUALITY_LEVELS:
            raise CanonicalStateError(f"unknown state_quality {self.state_quality!r}")
        if self.state_quality == "REFUSED" and self.refusal_reason is None:
            raise CanonicalStateError("a REFUSED state must carry a refusal_reason")

    def as_record(self) -> dict:
        return {"kind": "option_analytics_state", **asdict(self)}


def _refused(*, symbol, option_type, spot, strike, expiry_date, known_from, now,
            reason, time_to_expiry_years=None, price_sanity=None) -> OptionAnalyticsState:
    import pandas as pd
    return OptionAnalyticsState(
        symbol=symbol, option_type=option_type, spot=spot, strike=strike,
        expiry_date=expiry_date, time_to_expiry_years=(time_to_expiry_years or 0.0),
        short_dated=False, rate=None, dividend_pv=None,
        price_sanity=(price_sanity.as_record() if price_sanity else {}),
        iv=None, delta=None, gamma=None, theta=None, vega=None, rho=None,
        state_quality="REFUSED", refusal_reason=reason,
        known_from=str(pd.Timestamp(known_from)), as_of=str(pd.Timestamp(now)))


def build_canonical_state(*, symbol: str, option_type: str, spot: float, strike: float,
                          expiry_date: str, bid: float | None, ask: float | None,
                          last_trade: float | None, quote_is_current: bool,
                          curve: RiskFreeCurve | None,
                          dividend_schedule: DividendSchedule | None,
                          known_from, now, n_american_steps: int = 300,
                          quote_age_s: float | None = None,
                          underlying_age_s: float | None = None,
                          rate_source_age_days: float | None = None,
                          bid_size: int | None = None, ask_size: int | None = None,
                          dividend_confidence: str = "UNKNOWN") -> OptionAnalyticsState:
    """The `quote_age_s`/`underlying_age_s`/`rate_source_age_days`/
    `bid_size`/`ask_size`/`dividend_confidence` inputs are all optional
    and default to "not measured" (no state_quality cap imposed) -- a
    synthetic/test-driven call is unaffected; the live runtime always
    supplies real values here, which is where this degrades a
    precise-looking-but-input-poor state down to LOW/MODERATE."""
    import pandas as pd
    now = pd.Timestamp(now)
    live_quality = classify_live_quality(
        known_from=known_from, quote_age_s=quote_age_s, underlying_age_s=underlying_age_s,
        rate_source_age_days=rate_source_age_days, bid_size=bid_size, ask_size=ask_size,
        dividend_confidence=dividend_confidence)

    try:
        T = year_fraction(now, expiry_date)
    except Exception as e:  # noqa: BLE001
        return _refused(symbol=symbol, option_type=option_type, spot=spot, strike=strike,
                        expiry_date=expiry_date, known_from=known_from, now=now,
                        reason=f"TIME_TO_EXPIRY_ERROR: {e}")

    rate = rate_for_tenor(curve, T)
    if rate is None:
        return _refused(symbol=symbol, option_type=option_type, spot=spot, strike=strike,
                        expiry_date=expiry_date, known_from=known_from, now=now,
                        reason="NO_RATE_CURVE_COVERAGE_FOR_TENOR", time_to_expiry_years=T)

    div_pv = pv_of_dividends(dividend_schedule, now=now, expiry=expiry_date, rate=rate)
    if div_pv is None:
        return _refused(symbol=symbol, option_type=option_type, spot=spot, strike=strike,
                        expiry_date=expiry_date, known_from=known_from, now=now,
                        reason="NO_DIVIDEND_SCHEDULE_SUPPLIED", time_to_expiry_years=T)

    sanity = check_price_sanity(option_type=option_type, spot=spot, strike=strike,
                                time_to_expiry_years=T, rate=rate, bid=bid, ask=ask,
                                known_from=known_from)
    if not sanity.passed:
        return _refused(symbol=symbol, option_type=option_type, spot=spot, strike=strike,
                        expiry_date=expiry_date, known_from=known_from, now=now,
                        reason=f"PRICE_SANITY_VIOLATION: {sanity.violations}",
                        time_to_expiry_years=T, price_sanity=sanity)

    adjusted_spot = spot - div_pv
    short_dated = T * 365.0 < SHORT_DATED_THRESHOLD_DAYS

    iv_triple = solve_iv_triple(option_type=option_type, bid=bid, ask=ask,
                                last_trade=last_trade, quote_is_current=quote_is_current,
                                spot=adjusted_spot, strike=strike, time_to_expiry_years=T,
                                rate=rate)

    sigma_for_greeks = iv_triple.iv_mid
    if sigma_for_greeks is None:
        return OptionAnalyticsState(
            symbol=symbol, option_type=option_type, spot=spot, strike=strike,
            expiry_date=expiry_date, time_to_expiry_years=T, short_dated=short_dated,
            rate=rate, dividend_pv=div_pv, price_sanity=sanity.as_record(),
            iv=iv_triple.as_record(), delta=None, gamma=None, theta=None, vega=None,
            rho=None, state_quality="LOW", refusal_reason=None,
            known_from=str(pd.Timestamp(known_from)), as_of=str(now),
            live_quality=live_quality.as_record())

    bsm_g = bsm_mod.greeks(option_type=option_type, spot=adjusted_spot, strike=strike,
                           time_to_expiry_years=T, rate=rate, sigma=sigma_for_greeks)
    am_g = american_mod.american_greeks(option_type=option_type, spot=adjusted_spot,
                                        strike=strike, time_to_expiry_years=T, rate=rate,
                                        sigma=sigma_for_greeks, n_steps=n_american_steps)

    ranges = {
        "delta": build_range("delta", bsm_value=bsm_g.delta, american_value=am_g.delta),
        "gamma": build_range("gamma", bsm_value=bsm_g.gamma, american_value=am_g.gamma),
        "theta": build_range("theta", bsm_value=bsm_g.theta, american_value=am_g.theta),
        "vega": build_range("vega", bsm_value=bsm_g.vega, american_value=am_g.vega),
        "rho": build_range("rho", bsm_value=bsm_g.rho, american_value=am_g.rho),
    }

    worst_quality = min((r.quality for r in ranges.values()),
                        key=lambda q: {"HIGH": 3, "MODERATE": 2, "LOW": 1, "UNKNOWN": 0}[q])
    iv_quality_rank = {"HIGH": 3, "MODERATE": 2, "LOW": 1, "UNKNOWN": 0}[iv_triple.quality]
    overall_rank = min({"HIGH": 3, "MODERATE": 2, "LOW": 1, "UNKNOWN": 0}[worst_quality],
                       iv_quality_rank)
    if short_dated:
        overall_rank = min(overall_rank, 2)   # cap at MODERATE near expiry
    if live_quality.cap is not None:
        overall_rank = min(overall_rank, quality_rank(live_quality.cap))
    state_quality = {3: "HIGH", 2: "MODERATE", 1: "LOW", 0: "LOW"}[overall_rank]

    return OptionAnalyticsState(
        symbol=symbol, option_type=option_type, spot=spot, strike=strike,
        expiry_date=expiry_date, time_to_expiry_years=T, short_dated=short_dated,
        rate=rate, dividend_pv=div_pv, price_sanity=sanity.as_record(),
        iv=iv_triple.as_record(), delta=ranges["delta"].as_record(),
        gamma=ranges["gamma"].as_record(), theta=ranges["theta"].as_record(),
        vega=ranges["vega"].as_record(), rho=ranges["rho"].as_record(),
        state_quality=state_quality, refusal_reason=None,
        known_from=str(pd.Timestamp(known_from)), as_of=str(now),
        live_quality=live_quality.as_record())
