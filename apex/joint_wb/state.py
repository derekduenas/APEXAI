"""MarketState: the frozen identity and the four option-state coordinates (contract §1.2, §1.4, §2.1, §2.2).

Positivity is built in: `x_iv` is log IV at the FROZEN strike, `x_sk` is an anchor-free slope of log IV in
log-moneyness, `x_sp` is a floored log relative spread, `x_sz` is `log(1 + size)`. Predictor-domain refusals are
checked BEFORE any `log` or `sqrt`."""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from apex.multiverse_wb.pricing import PricingRefused, implied_vol, sanitize_quote
from apex.options_pilot.expression_rule import DTE_MIN_DAYS
from apex.options_pilot.records import canonical_hash

ET = ZoneInfo("America/New_York")
CALENDAR_YEAR_S = 365.0 * 86400.0
SPREAD_FLOOR = 1e-4
SKEW_MONEYNESS = 0.02
UNDERLYING_PAIR_MAX_S = 5.0          # contemporaneous underlying reference for IV inversion
SPOT_ASYNC_GAP_MAX = 0.002
BAR_MAX_AGE_S = 120.0
NBBO_MAX_AGE_S = 15.0
QUOTE_MAX_AGE_S = 120.0              # INDICATIVE age (ranking, reporting)
EXECUTION_MAX_AGE_S = 15.0           # EXECUTABLE age at the decision boundary: only these may produce an intent
CONTRACT_PIN = "a0228fac4a2dab4c455c9fc8a41d1378522a27de"


class StateRefused(ValueError):
    pass


def expiry_epoch_of(expiration: str) -> float:
    return datetime.fromisoformat(expiration + "T16:00:00").replace(tzinfo=ET).timestamp()


def check_input_contract(name: str, rec: dict) -> None:
    for f in ("event_time", "available_time", "source", "revision_policy", "max_age_s", "quality"):
        if f not in rec:
            raise StateRefused("INPUT_CONTRACT_MISSING:%s (%s)" % (f, name))


def check_availability(name: str, rec: dict, *, t_d: float) -> None:
    """The FIREWALL: nothing may be visible before it was available. Applied to EVERY input."""
    if rec["available_time"] > t_d:
        raise StateRefused("FUTURE_INPUT:%s (available %.3f > t_d %.3f)" % (name, rec["available_time"], t_d))
    if rec["event_time"] > t_d:
        raise StateRefused("FUTURE_INPUT:%s (event %.3f > t_d %.3f)" % (name, rec["event_time"], t_d))


def check_stale(name: str, rec: dict, *, t_d: float) -> None:
    """Staleness applies to the input actually USED (the last bar, the reference quote) — an older bar inside a
    warm-up window is not stale, it is history."""
    age = t_d - rec["event_time"]
    if age > rec["max_age_s"]:
        raise StateRefused("INPUT_STALE:%s (age %.1fs > %.1fs)" % (name, age, rec["max_age_s"]))


def underlying_reference(underlyings: list, *, at: float, max_gap_s: float = UNDERLYING_PAIR_MAX_S):
    """The reference with `event_time <= at` and gap <= max_gap_s, else None (§1.2)."""
    cands = [u for u in underlyings if u["event_time"] <= at and at - u["event_time"] <= max_gap_s]
    return max(cands, key=lambda u: u["event_time"]) if cands else None


def frozen_identity(*, symbol: str, t_d: float, spot: float, chain: list) -> dict:
    """E*, K_atm, K_-, K_+ chosen ONCE at t_d; ties -> LOWER strike (§1.4)."""
    today = datetime.fromtimestamp(t_d, tz=timezone.utc).date()
    exps = sorted({c["expiration"] for c in chain if (date.fromisoformat(c["expiration"]) - today).days >= DTE_MIN_DAYS})
    if not exps:
        raise StateRefused("NO_ELIGIBLE_EXPIRY: none with DTE >= %d" % DTE_MIN_DAYS)
    exp = exps[0]
    strikes = sorted({float(c["strike"]) for c in chain if c["expiration"] == exp})
    if not strikes:
        raise StateRefused("NO_STRIKES for %s" % exp)
    k_atm = min(strikes, key=lambda k: (abs(k - spot), k))
    k_lo = min(strikes, key=lambda k: (abs(k - spot * math.exp(-SKEW_MONEYNESS)), k))
    k_hi = min(strikes, key=lambda k: (abs(k - spot * math.exp(+SKEW_MONEYNESS)), k))
    return {"symbol": symbol, "expiration": exp, "expiry_epoch": expiry_epoch_of(exp), "strikes": strikes,
            "K_atm": k_atm, "K_minus": k_lo, "K_plus": k_hi, "skew_available": k_lo != k_hi,
            "rule": "E* = first DTE >= 21 at t_d; K_atm nearest spot (ties LOWER); K_-/K_+ nearest spot*exp(-+0.02) (ties LOWER)"}


def atm_iv(*, quotes: dict, identity: dict, underlyings: list, T_years: float, iv_source: str | None = None) -> dict:
    """iv_atm from CALL/PUT at the frozen strike, each inverted with its OWN contemporaneous underlying (§1.2)."""
    out, per = {}, {}
    for right in ("CALL", "PUT"):
        q = quotes.get((identity["expiration"], identity["K_atm"], right))
        if q is None:
            per[right] = "NO_VALID_QUOTE"; continue
        ref = underlying_reference(underlyings, at=q["timestamp_epoch"])
        if ref is None:
            per[right] = "IV_UNUSABLE: NO_CONTEMPORANEOUS_UNDERLYING"; continue
        if not q.get("usable_for_iv", q["bid"] > 0):
            per[right] = "NO_BID"; continue
        try:
            per[right] = implied_vol(price=q["mid"], S=ref["value"], K=identity["K_atm"], T=T_years, right=right)["iv"]
            out[right] = per[right]
        except PricingRefused as e:
            per[right] = "REFUSED: %s" % str(e)[:70]
    src = iv_source or ("BOTH" if len(out) == 2 else "CALL_ONLY" if "CALL" in out else "PUT_ONLY" if "PUT" in out else None)
    if src is None:
        return {"iv": None, "iv_source": None, "by_right": per, "why": "ATM_IV_UNAVAILABLE"}
    need = {"BOTH": ("CALL", "PUT"), "CALL_ONLY": ("CALL",), "PUT_ONLY": ("PUT",)}[src]
    if any(r not in out for r in need):
        return {"iv": None, "iv_source": src, "by_right": per, "why": "IV_SOURCE_CHANGED: %s unavailable" % (need,)}
    return {"iv": sum(out[r] for r in need) / len(need), "iv_source": src, "by_right": per, "why": None}


def slice_skew(*, quotes: dict, identity: dict, underlyings: list, T_years: float, iv_source: str) -> dict:
    """x_sk = [log iv(K_-) - log iv(K_+)] / log(K_-/K_+), anchor-free (§2.1), computed with the FROZEN aggregation
    source. A leg that cannot supply exactly those rights is IV_SOURCE_CHANGED, never silently averaged over a
    different set — a call-to-put switch is not a market move (§1.4)."""
    if not identity["skew_available"]:
        return {"x_sk": None, "why": "SKEW_STRIKES_NOT_DISTINCT"}
    need = {"BOTH": ("CALL", "PUT"), "CALL_ONLY": ("CALL",), "PUT_ONLY": ("PUT",)}.get(iv_source)
    if need is None:
        return {"x_sk": None, "why": "IV_SOURCE_UNDECLARED"}
    ivs = {}
    for label, k in (("minus", identity["K_minus"]), ("plus", identity["K_plus"])):
        vals = []
        for right in need:
            q = quotes.get((identity["expiration"], k, right))
            if q is None or not q.get("usable_for_iv", q["bid"] > 0):
                return {"x_sk": None, "why": "IV_SOURCE_CHANGED: leg %s cannot supply %s under frozen source %s"
                                             % (label, right, iv_source)}
            ref = underlying_reference(underlyings, at=q["timestamp_epoch"])
            if ref is None:
                return {"x_sk": None, "why": "IV_SOURCE_CHANGED: leg %s %s has NO_CONTEMPORANEOUS_UNDERLYING" % (label, right)}
            try:
                vals.append(implied_vol(price=q["mid"], S=ref["value"], K=k, T=T_years, right=right)["iv"])
            except PricingRefused as e:
                return {"x_sk": None, "why": "SKEW_LEG_REFUSED:%s %s (%s)" % (label, right, str(e)[:50])}
        if len(vals) != len(need):
            return {"x_sk": None, "why": "SKEW_LEG_MISSING:%s" % label}
        ivs[label] = sum(vals) / len(vals)
    denom = math.log(identity["K_minus"] / identity["K_plus"])
    if not math.isfinite(denom) or denom == 0:
        return {"x_sk": None, "why": "SKEW_DENOMINATOR_INVALID"}
    return {"x_sk": (math.log(ivs["minus"]) - math.log(ivs["plus"])) / denom, "iv_minus": ivs["minus"],
            "iv_plus": ivs["plus"], "iv_source": iv_source, "why": None}


def compose(*, symbol: str, t_d: float, bars: list, underlyings: list, chain: list, raw_quotes: dict,
            identity: dict | None = None, iv_source: str | None = None, quote_max_age_s: float = QUOTE_MAX_AGE_S) -> dict:
    """The `market_state` record (§1). Every input must satisfy the contract and availability first."""
    for b in bars:
        check_input_contract("bar", b); check_availability("bar", b, t_d=t_d)
    for u in underlyings:
        check_input_contract("underlying", u); check_availability("underlying", u, t_d=t_d)
    if not bars:
        raise StateRefused("NO_BARS")
    last = max(bars, key=lambda b: b["event_time"])
    check_stale("bar", last, t_d=t_d)
    S_0 = last["close"]
    nb = [u for u in underlyings if u.get("kind") == "NBBO"]
    S_nbbo = None
    if nb:
        newest = max(nb, key=lambda u: u["event_time"])
        check_stale("underlying_nbbo", newest, t_d=t_d)
        S_nbbo = newest["value"]
    gap = math.log(S_nbbo / S_0) if (S_nbbo and S_0 > 0) else None
    if gap is not None and abs(gap) >= SPOT_ASYNC_GAP_MAX:
        raise StateRefused("SPOT_ASYNC_GAP_EXCEEDED: %.5f" % gap)

    valid, rejected = {}, {}
    for key, q in raw_quotes.items():
        if q.get("available_time", q.get("timestamp_epoch", t_d + 1)) > t_d:
            rejected[str(key)] = "FUTURE_INPUT:quote"; continue
        try:
            sq = sanitize_quote(q, now=t_d, max_age_s=quote_max_age_s)
        except PricingRefused as e:
            rejected[str(key)] = str(e); continue
        age = t_d - q["timestamp_epoch"]
        valid[(key[0], float(key[1]), key[2])] = {
            **sq, "timestamp_epoch": q["timestamp_epoch"], "available_time": q.get("available_time", q["timestamp_epoch"]),
            "age_s": age, "indicative_ok": True,
            "executable": bool(age <= EXECUTION_MAX_AGE_S),
            "freshness_decision": ("EXECUTABLE: age %.3fs <= %.0fs" % (age, EXECUTION_MAX_AGE_S) if age <= EXECUTION_MAX_AGE_S
                                   else "INDICATIVE_ONLY: age %.3fs > %.0fs execution limit; may be ranked, may NOT produce an intent"
                                        % (age, EXECUTION_MAX_AGE_S))}
    if not valid:
        raise StateRefused("NO_VALID_QUOTE: %d rejected (%s)" % (len(rejected), sorted(set(rejected.values()))[:3]))

    ident = identity or frozen_identity(symbol=symbol, t_d=t_d, spot=S_0, chain=chain)
    T_entry = (ident["expiry_epoch"] - t_d) / CALENDAR_YEAR_S
    if T_entry <= 0:
        raise StateRefused("EXPIRY_NOT_IN_FUTURE")
    a = atm_iv(quotes=valid, identity=ident, underlyings=underlyings, T_years=T_entry, iv_source=iv_source)
    if a["iv"] is None:
        raise StateRefused("ATM_IV_UNAVAILABLE: %s" % (a.get("why") or a["by_right"]))
    ident = {**ident, "iv_source": a["iv_source"]}          # the aggregation source is FROZEN on the identity
    sk = slice_skew(quotes=valid, identity=ident, underlyings=underlyings, T_years=T_entry, iv_source=ident["iv_source"])
    qa = valid.get((ident["expiration"], ident["K_atm"], "CALL")) or valid.get((ident["expiration"], ident["K_atm"], "PUT"))
    sp_obs = qa["spread"] / qa["mid"] if qa["mid"] > 0 else None
    if sp_obs is None or not math.isfinite(sp_obs) or sp_obs < 0:
        raise StateRefused("SPREAD_INVALID: %r" % (sp_obs,))
    floored = sp_obs < SPREAD_FLOOR
    sz = float(min(qa["bid_size"], qa["ask_size"]))
    body = {"kind": "market_state", "symbol": symbol, "t_d": t_d, "contract_pin": CONTRACT_PIN,
            "S_0": {"value": S_0, "event_time": last["event_time"], "available_time": last["available_time"],
                    "source": last["source"], "age_s": t_d - last["event_time"], "quality": last["quality"]},
            "S_nbbo": ({"value": S_nbbo} if S_nbbo else None), "spot_async_gap": gap,
            "identity": {k: ident[k] for k in ("expiration", "expiry_epoch", "K_atm", "K_minus", "K_plus", "skew_available", "rule", "iv_source")},
            "T_entry_years": T_entry, "T_exit_years": (ident["expiry_epoch"] - (t_d + 900.0)) / CALENDAR_YEAR_S,
            "x_iv": math.log(a["iv"]), "iv_atm": a["iv"], "iv_source": a["iv_source"], "iv_by_right": a["by_right"],
            "x_sk": sk["x_sk"], "skew_why": sk.get("why"), "skew_quality": ("VALID" if sk["x_sk"] is not None else "MISSING"),
            "x_sp": math.log(max(sp_obs, SPREAD_FLOOR)), "spread_rel_atm": sp_obs, "spread_floored": floored,
            "x_sz": math.log(1.0 + sz), "size_atm": sz,
            "quotes": {"received": len(raw_quotes), "valid": len(valid), "rejected": len(rejected),
                       "rejection_reasons": dict(sorted(rejected.items())[:12])},
            "time_conventions": {"expiry_decay": "CALENDAR seconds / (365 d) from timestamps",
                                 "variance": "MARKET minutes (bars)"}}
    body["state_hash"] = canonical_hash({k: body[k] for k in ("symbol", "t_d", "identity", "x_iv", "x_sk", "x_sp", "x_sz")})
    body["valid_quotes"] = valid
    return body


def predictor_vector(*, r: float, q: float, v_hat: float):
    """z = (1, r, |r|/sqrt(v_hat), log q - log v_hat). Domain checked BEFORE any log/sqrt (§2.2)."""
    if not isinstance(v_hat, (int, float)) or isinstance(v_hat, bool) or not math.isfinite(v_hat) or v_hat <= 0:
        raise StateRefused("SCALE_VARIANCE_INVALID: %r" % (v_hat,))
    if not isinstance(q, (int, float)) or isinstance(q, bool) or not math.isfinite(q) or q <= 0:
        raise StateRefused("PREDICTOR_INVALID: q=%r" % (q,))
    if not isinstance(r, (int, float)) or not math.isfinite(r):
        raise StateRefused("PREDICTOR_INVALID: r=%r" % (r,))
    return (1.0, float(r), abs(r) / math.sqrt(v_hat), math.log(q) - math.log(v_hat))
