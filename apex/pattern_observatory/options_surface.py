"""OPTIONS SURFACE AS A WORLD SENSOR -- the first reader of surfaces.jsonl.

`results/option_analytics/live/surfaces.jsonl` accumulated 21,354 rows on
2026-08-19 and had EXACTLY ZERO readers -- the only file in the repo
mentioning it was the runtime that writes it. A 60MB orphan. The whole
APEX_OPTION_ANALYTICS_V1 build produced a measurement layer with nobody
downstream.

This module is that reader. It treats the surface as a WORLD SENSOR --
what are options prices saying about expected distribution -- and not as
an expression venue. It has no path to OptionExpressionEngine and cannot
recommend an option.

CLOCK INTEGRITY IS LOAD-BEARING HERE. 89.4% of 2026-08-19's option states
carried a NEGATIVE quote_age_s, one at -1081s, and the quality model
treated them as maximally fresh. Any surface observation built on a
clock-violating quote is SUPPRESSED, not merely down-weighted.

THE 2026-08-19 MATURITY-MIXING BUG, FOUND AND FIXED THE FOLLOWING EVENING.
The first version of this module sorted every usable contract by
moneyness ACROSS ALL EXPIRIES and called whichever one landed closest to
spot "the ATM contract" -- regardless of maturity. Proven on real SPY
data: the identical strike (759, identical moneyness 0.01336) showed
IV 0.17581 in the 1-2 DTE bucket and IV 0.11127 in the 3-7 DTE bucket.
A cycle that happened to pick one bucket's contract as "nearest" and the
next cycle picked the other would have registered a 6.5-vol-point
`VOL_REPRICING` event that was 100% a maturity-selection artifact -- a
textbook case of comparing contracts with incompatible maturities.

THE LAW NOW ENFORCED: there are two ORTHOGONAL axes, and they are never
collapsed into one computation.

    STRIKE axis (skew/smile)   -- computed WITHIN one real expiry_date
    TIME axis (term structure) -- computed ACROSS expiries' own ATMs

ATM and skew are computed separately for EVERY real `expiry_date` present
in the sample. The "primary" (reported top-level) ATM/skew is the
front-month expiry among those with enough contracts to be trustworthy --
a stable, deterministic choice, not "whichever strike happened to sort
first." `iv_change`/`skew_change` compare the SAME expiry's value to its
OWN prior cycle, never a different expiry's value to this one's -- and
if the front-month expiry itself rolls to a new date, the change is
correctly reported as NOT_ESTIMABLE across that boundary rather than
silently diffed. Term structure is then built FROM these already-correct
per-expiry ATMs, which is what "compare ATM across expiries" actually
requires.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from apex.pattern_observatory import OBSERVATORY_POWER

STATES = ("VOL_REPRICING_UP", "VOL_REPRICING_DOWN", "SKEW_STEEPENING",
          "SKEW_FLATTENING", "FRONT_VOL_BID", "BACK_VOL_BID",
          "SURFACE_DISLOCATION", "OPTION_PRICE_DISCOVERY_LEADING",
          "STABLE", "UNKNOWN")

# DECLARED, pre-registered. Never fitted to outcomes.
VOL_MOVE_MATERIAL = 0.01        # 1 vol point
SKEW_MOVE_MATERIAL = 0.01
TERM_INVERSION_MATERIAL = 0.02
MIN_CONTRACTS = 8               # whole-sample floor before attempting anything
# A per-expiry floor is DELIBERATELY SMALLER than MIN_CONTRACTS: splitting
# 72 contracts across 4 DTE buckets leaves roughly a dozen per bucket, and
# reusing the whole-surface threshold per expiry would starve every
# expiry simultaneously. Declared the same evening as this fix, not
# tuned against any outcome.
MIN_CONTRACTS_PER_EXPIRY = 3
SUPPRESSED = "SUPPRESSED_CLOCK_INTEGRITY"


@dataclass(frozen=True)
class OptionsSurfacePatternState:
    subject: str
    as_of: str
    known_from: str
    state: str
    atm_iv: float | None
    iv_change: float | None
    skew: float | None
    skew_change: float | None
    term_slope: float | None
    primary_expiry: str | None
    per_expiry: dict
    contracts_used: int
    contracts_suppressed: int
    model_disagreement: dict
    quality: str
    estimable: bool
    reasoning: tuple

    def as_dict(self) -> dict:
        return {"kind": "options_surface_pattern_state", **self.__dict__,
                "per_expiry": dict(self.per_expiry),
                "model_disagreement": dict(self.model_disagreement),
                "reasoning": list(self.reasoning),
                "is_expression_recommendation": False,
                "decision_power": OBSERVATORY_POWER}


def _clock_ok(state: dict) -> bool:
    lq = state.get("live_quality") or {}
    age = lq.get("quote_age_s")
    return age is not None and age >= 0


def _moneyness(s: dict) -> float:
    sp, k = s.get("spot"), s.get("strike")
    return abs(k / sp - 1.0) if (sp and k) else 9.9


def _by_expiry(contracts: list) -> dict:
    """Partition by the REAL expiry_date, not the coarser dte_bucket --
    two different actual expiries can share a bucket (e.g. '8-30' spans
    many dates), and the strike-axis computation must never mix them."""
    out: dict = defaultdict(list)
    for s in contracts:
        exp = s.get("expiry_date")
        if exp:
            out[exp].append(s)
    return dict(out)


def _expiry_smile(contracts: list) -> dict | None:
    """ATM + skew computed WITHIN one real expiry only. Returns None if
    that expiry does not have enough contracts to trust -- an expiry with
    2 strikes does not get to report a skew."""
    if len(contracts) < MIN_CONTRACTS_PER_EXPIRY:
        return None
    near = sorted(contracts, key=_moneyness)
    atm = near[0]["iv"]["iv_mid"]
    far = near[len(near) // 2:]
    skew = (sum(c["iv"]["iv_mid"] for c in far) / len(far) - atm) if far else None
    return {"atm_iv": atm, "skew": skew, "n": len(contracts),
            "dte_bucket": contracts[0].get("dte_bucket")}


def observe(subject: str, states: list, *, prior=None, as_of, known_from
            ) -> OptionsSurfacePatternState:
    """`states`: raw option_analytics state records for ONE underlying."""
    total = len(states)
    clean = [s for s in states if _clock_ok(s)]
    suppressed = total - len(clean)

    usable = [s for s in clean
              if isinstance(s.get("iv"), dict)
              and s["iv"].get("iv_mid") is not None
              and s.get("state_quality") in ("HIGH", "MODERATE")]

    def _unknown(why: str, quality: str) -> OptionsSurfacePatternState:
        return OptionsSurfacePatternState(
            subject=subject, as_of=str(as_of), known_from=str(known_from),
            state="UNKNOWN", atm_iv=None, iv_change=None, skew=None,
            skew_change=None, term_slope=None, primary_expiry=None,
            per_expiry={}, contracts_used=len(usable),
            contracts_suppressed=suppressed, model_disagreement={},
            quality=quality, estimable=False, reasoning=(why,))

    if len(usable) < MIN_CONTRACTS:
        why = (f"{suppressed}/{total} contracts suppressed for clock "
               f"integrity" if suppressed else
               f"only {len(usable)} usable contracts, need {MIN_CONTRACTS}")
        return _unknown(why, SUPPRESSED if suppressed >= total / 2
                        else "INSUFFICIENT")

    # ---- STRIKE AXIS: one smile per real expiry, never mixed ----------
    by_expiry_raw = _by_expiry(usable)
    per_expiry = {exp: sm for exp, sm in
                 ((e, _expiry_smile(cs)) for e, cs in by_expiry_raw.items())
                 if sm is not None}

    if not per_expiry:
        return _unknown(
            f"{len(by_expiry_raw)} expiries present but none reached "
            f"{MIN_CONTRACTS_PER_EXPIRY} contracts", "INSUFFICIENT")

    # front-month convention: expiry_date strings sort chronologically
    primary_expiry = min(per_expiry)
    primary = per_expiry[primary_expiry]
    atm, skew = primary["atm_iv"], primary["skew"]

    # ---- TIME AXIS: term structure built FROM the per-expiry ATMs -----
    front_atms = [v["atm_iv"] for v in per_expiry.values()
                 if v["dte_bucket"] in ("1-2", "3-7")]
    back_atms = [v["atm_iv"] for v in per_expiry.values()
                if v["dte_bucket"] == ">30"]
    term = ((sum(front_atms) / len(front_atms))
            - (sum(back_atms) / len(back_atms))
            if front_atms and back_atms else None)

    dis = {}
    for g in ("delta", "gamma", "vega", "theta", "rho"):
        lv = [s[g].get("disagreement_level") for s in usable
              if isinstance(s.get(g), dict)]
        if lv:
            dis[g] = {"HIGH": lv.count("HIGH"), "MODERATE": lv.count("MODERATE"),
                      "LOW": lv.count("LOW")}

    reasoning = []
    iv_ch = skew_ch = None
    if prior is not None and prior.primary_expiry == primary_expiry:
        # SAME expiry as last cycle -- the only case a diff is meaningful
        prior_smile = (prior.per_expiry or {}).get(primary_expiry)
        if prior_smile:
            if prior_smile.get("atm_iv") is not None:
                iv_ch = atm - prior_smile["atm_iv"]
            if prior_smile.get("skew") is not None and skew is not None:
                skew_ch = skew - prior_smile["skew"]
    elif prior is not None and prior.primary_expiry is not None:
        reasoning.append(
            f"primary expiry rolled {prior.primary_expiry} -> "
            f"{primary_expiry}; iv_change/skew_change NOT computed across "
            f"a maturity change")

    state = "STABLE"
    if iv_ch is not None and abs(iv_ch) >= VOL_MOVE_MATERIAL:
        state = "VOL_REPRICING_UP" if iv_ch > 0 else "VOL_REPRICING_DOWN"
        reasoning.append(f"ATM IV ({primary_expiry}) moved {iv_ch:+.4f}")
    if skew_ch is not None and abs(skew_ch) >= SKEW_MOVE_MATERIAL:
        s2 = "SKEW_STEEPENING" if skew_ch > 0 else "SKEW_FLATTENING"
        reasoning.append(f"skew ({primary_expiry}) moved {skew_ch:+.4f}")
        if state == "STABLE":
            state = s2
    if term is not None and term >= TERM_INVERSION_MATERIAL:
        reasoning.append(f"front-expiry ATM over back-expiry ATM by "
                         f"{term:.4f}")
        if state == "STABLE":
            state = "FRONT_VOL_BID"
    if dis.get("delta", {}).get("HIGH", 0) > 0:
        reasoning.append("BSM/American delta disagreement present")
    if not reasoning:
        reasoning.append("no surface move exceeded the declared threshold")
    if suppressed:
        reasoning.append(f"{suppressed}/{total} contracts suppressed "
                         f"(negative quote age)")

    return OptionsSurfacePatternState(
        subject=subject, as_of=str(as_of), known_from=str(known_from),
        state=state, atm_iv=atm, iv_change=iv_ch, skew=skew,
        skew_change=skew_ch, term_slope=term, primary_expiry=primary_expiry,
        per_expiry=per_expiry, contracts_used=len(usable),
        contracts_suppressed=suppressed, model_disagreement=dis,
        quality=("DEGRADED" if suppressed else "OK"), estimable=True,
        reasoning=tuple(reasoning))
