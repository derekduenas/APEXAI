"""Deterministic expression rules for the options pilot.

No "best option", no mispricing claim, no breakeven ranking. Expiration
breakevens cannot say which 21+ DTE option best monetises a move before
today's close, so the pilot does not pretend to know. The rule exists so the
recording boundary has something deterministic to record.

    direction_signal LONG  -> BUY one CALL
    direction_signal SHORT -> BUY one PUT
    expiration: nearest available with DTE >= 21 (CANDIDATE_RULES.dte_min_days)
    quantity:   1, filled or unfilled

Two versioned strike selectors exist. Every intent seals the version it used.

PILOT_RULE_V1 (frozen 2026-09-04): strike nearest to spot (ties -> lower).
    DEFECT recorded 2026-09-11 under PROFIT_TRANSITION_DIRECTIVE hard law one
    ("0 trades because attacks are structurally impossible = DEFECT"): with a
    $500 per-trade cap (max entry 5.00/share) and SPY ATM 21-DTE asks near 9,
    V1's choice is refused by the risk envelope on every scan, and V1 never
    looks at the next strike. V1 is kept for replay of records that sealed it.

PILOT_RULE_V2 (2026-09-11): among strikes on the SIGNAL'S SIDE of spot
    (CALL: K >= spot; PUT: K <= spot) whose INDICATIVE ask is <= max_entry_price,
    the one nearest to spot (ties -> lower). The cap is a fact about the account
    and enters HERE, in expression, downstream of the signal; candidate
    generation upstream stays blind to capital. A strike selected by V2 says what
    V1 could not express: "the nearest feasible strike is N strikes / p% away".

The forecast distribution is recorded but does NOT drive expression choice:
horizon-consistent option valuation is a separate capability."""
from __future__ import annotations

from datetime import date

DTE_MIN_DAYS = 21
RULE_ID_V1 = "PILOT_RULE_V1: signal->right, nearest expiry >= 21 DTE, nearest-ATM strike, 1 contract"
RULE_ID_V2 = ("PILOT_RULE_V2: signal->right, nearest expiry >= 21 DTE, nearest strike on the signal's side with "
              "indicative ask <= max_entry_price, 1 contract")
RULE_ID = RULE_ID_V1            # the frozen V1 id, kept for records that sealed it
RULE_IDS = {"PILOT_RULE_V1": RULE_ID_V1, "PILOT_RULE_V2": RULE_ID_V2}
DEFAULT_RULE = "PILOT_RULE_V2"
V1_DEFECT = ("DEFECT_PTD_HARD_LAW_ONE: PILOT_RULE_V1 selects nearest-to-spot without consulting the entry cap, so under a "
             "$500 cap on SPY every intent is RISK_ENVELOPE_INFEASIBLE by construction (0 trades because attacks are "
             "structurally impossible). Recorded 2026-09-11; V2 is the repair.")


class RuleRefused(ValueError):
    pass


QUOTE_MAX_AGE_S = 120.0          # §1.1 indicative option-quote age; the executable quote is re-validated at the boundary (15 s)
POLICY_TO_RULE = {"PILOT_RULE_V1": "PILOT_RULE_V1", "PILOT_RULE_V2": "PILOT_RULE_V2"}


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and x not in (float("inf"), float("-inf"))


def validate_rows(available: list, *, right: str, expiration: str, as_of_epoch: float | None) -> tuple:
    """PURE SELECTOR BOUNDARY (independent of the provider boundary): every row for the chosen right and expiry is
    re-validated here. Finite positive strike and ask, finite non-negative bid <= ask when present, correctly typed
    non-negative integer sizes when present, and quote timing under the indicative contract when `as_of_epoch` is
    supplied. Conflicting duplicates of one contract are EXCLUDED as a named refusal (never resolved by arrival order);
    identical duplicates collapse to one. Returns (rows_by_strike, exclusions)."""
    by_k, excl = {}, []
    for i, c in enumerate(available):
        if c.get("right") != right or c.get("expiration") != expiration:
            continue
        k = c.get("strike"); ask = c.get("ask"); bid = c.get("bid"); ts = c.get("timestamp_epoch")
        why = None
        if not _num(k) or k <= 0: why = "STRIKE_INVALID: %r" % (k,)
        elif "ask" in c and (not _num(ask) or ask <= 0): why = "ASK_INVALID: %r" % (ask,)
        elif bid is not None and (not _num(bid) or bid < 0 or (_num(ask) and ask < bid)): why = "BID_INVALID: bid %r ask %r" % (bid, ask)
        else:
            for f in ("bid_size", "ask_size"):
                v = c.get(f)
                if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                    why = "SIZE_INVALID: %s %r" % (f, v); break
        if why is None and as_of_epoch is not None:
            if ts is None or not _num(ts): why = "TIMESTAMP_MISSING: indicative quote carries no timestamp_epoch"
            elif ts > as_of_epoch: why = "QUOTE_FROM_THE_FUTURE: %.3fs" % (ts - as_of_epoch)
            elif as_of_epoch - ts > QUOTE_MAX_AGE_S: why = "INDICATIVE_STALE: %.1fs > %.0fs" % (as_of_epoch - ts, QUOTE_MAX_AGE_S)
        if why:
            excl.append({"row": i, "strike": k, "why": why}); continue
        key = float(k)
        ident = (c.get("ask"), c.get("bid"), c.get("bid_size"), c.get("ask_size"), ts)
        if key in by_k:
            if by_k[key]["_ident"] != ident:
                by_k[key]["_conflict"] = True
            continue
        by_k[key] = {**c, "_ident": ident, "_conflict": False}
    for key in sorted(k for k, v in by_k.items() if v["_conflict"]):
        excl.append({"row": None, "strike": key, "why": "DUPLICATE_CONFLICT: the same contract appears with different quotes; excluded, not resolved by order"})
        del by_k[key]
    return by_k, excl


def _side_and_expiry(*, direction_signal, spot, as_of, available):
    if direction_signal not in ("LONG", "SHORT"):
        raise RuleRefused("NO_DIRECTION_SIGNAL: the heuristic label is %r; the rule needs LONG or SHORT" % direction_signal)
    if not _num(spot) or not spot > 0:
        raise RuleRefused("NO_SPOT: %r" % spot)
    right = "CALL" if direction_signal == "LONG" else "PUT"
    today = date.fromisoformat(as_of[:10])
    exps = sorted({c["expiration"] for c in available if c.get("right") == right})
    eligible = [e for e in exps if (date.fromisoformat(e) - today).days >= DTE_MIN_DAYS]
    if not eligible:
        raise RuleRefused("NO_ELIGIBLE_EXPIRY: none with DTE >= %d among %s" % (DTE_MIN_DAYS, exps[:4]))
    exp = eligible[0]
    rows = [c for c in available if c.get("right") == right and c["expiration"] == exp]
    if not rows:
        raise RuleRefused("NO_STRIKES for %s %s" % (exp, right))
    return right, exp, rows


def _ask_at(rows, strike):
    ref = [c.get("ask") for c in rows if float(c["strike"]) == strike]
    return ref[0] if ref and _num(ref[0]) else None


def choose(*, symbol: str, direction_signal: str | None, spot: float, as_of: str, available: list,
           rule: str = DEFAULT_RULE, max_entry_price: float | None = None, as_of_epoch: float | None = None) -> dict:
    """`available` is a list of contract dicts {expiration, strike, right, [ask, bid, sizes, timestamp_epoch]}. `ask` is
    an INDICATIVE chain-snapshot value, never a fill price. Returns the intent shape (expression, action, contract,
    ...) or refuses. V2 requires `max_entry_price`; V1 ignores it. `as_of_epoch` enables quote-timing validation."""
    if rule not in RULE_IDS:
        raise RuleRefused("RULE_UNKNOWN: %r" % (rule,))
    right, exp, _rows = _side_and_expiry(direction_signal=direction_signal, spot=spot, as_of=as_of, available=available)
    by_k, excl = validate_rows(available, right=right, expiration=exp, as_of_epoch=as_of_epoch)
    provider_excl = list(getattr(available, "exclusions", []) or [])
    if not by_k:
        raise RuleRefused("NO_VALID_ROWS for %s %s: %d excluded (%s)" % (exp, right, len(excl), sorted({e["why"].split(":")[0] for e in excl})[:4]))
    strikes = sorted(by_k)
    atm = min(strikes, key=lambda k: (abs(k - spot), k))

    def ask_at(k):
        a = by_k[k].get("ask")
        return a if _num(a) and a > 0 else None

    def bid_at(k):
        b = by_k[k].get("bid")
        return b if _num(b) and b >= 0 else None

    atm_ask = ask_at(atm)
    base = {"expression": "LONG_CALL" if right == "CALL" else "LONG_PUT", "action": "BUY", "quantity": 1}
    exclusions = {"selector": excl, "provider": provider_excl, "n_selector": len(excl), "n_provider": len(provider_excl)}

    if rule == "PILOT_RULE_V1":
        return {**base, "contract": {"symbol": symbol, "expiration": exp, "strike": atm, "right": right},
                "expression_rule": RULE_ID_V1, "reference_ask": atm_ask, "reference_bid": bid_at(atm),
                "reference_quote": _ref_quote(by_k[atm]),
                "strike_selection": {"rule": "PILOT_RULE_V1", "spot": spot, "strike": atm, "atm_strike": atm,
                                     "distance": round(atm - spot, 4), "distance_pct": round(100.0 * (atm - spot) / spot, 4),
                                     "cap_consulted": False, "defect": V1_DEFECT, "exclusions": exclusions}}

    if not _num(max_entry_price) or not max_entry_price > 0:
        raise RuleRefused("NO_MAX_ENTRY_PRICE: PILOT_RULE_V2 needs the envelope cap; got %r" % (max_entry_price,))
    on_side = [k for k in strikes if (k >= spot if right == "CALL" else k <= spot)]
    priced = [k for k in on_side if ask_at(k) is not None]
    feasible = [k for k in priced if ask_at(k) <= max_entry_price]
    census = {"strikes": len(strikes), "on_signal_side": len(on_side), "with_indicative_ask": len(priced), "feasible": len(feasible),
              "atm_strike": atm, "atm_ask": atm_ask, "max_entry_price": max_entry_price, "excluded_selector": len(excl),
              "excluded_provider": len(provider_excl)}
    if not priced:
        raise RuleRefused("NO_INDICATIVE_ASKS: V2 cannot judge feasibility without chain asks; census %s" % census)
    if not feasible:
        cheapest = min(priced, key=lambda k: ask_at(k))
        raise RuleRefused("NO_FEASIBLE_STRIKE: cheapest on-side ask %.2f at K=%s > cap %.2f; census %s"
                          % (ask_at(cheapest), cheapest, max_entry_price, census))
    strike = min(feasible, key=lambda k: (abs(k - spot), k))
    ask = ask_at(strike)
    idx_atm, idx_k = strikes.index(atm), strikes.index(strike)
    return {**base, "contract": {"symbol": symbol, "expiration": exp, "strike": strike, "right": right},
            "expression_rule": RULE_ID_V2, "reference_ask": ask, "reference_bid": bid_at(strike),      # INDICATIVE only; never a fill price
            "reference_quote": _ref_quote(by_k[strike]),
            "strike_selection": {"rule": "PILOT_RULE_V2", "spot": spot, "strike": strike, "reference_ask": ask,
                                 "distance": round(strike - spot, 4), "distance_pct": round(100.0 * (strike - spot) / spot, 4),
                                 "strikes_from_atm": abs(idx_k - idx_atm), "cap_consulted": True, "census": census, "exclusions": exclusions,
                                 "what_v1_could_not_express": ("V1 would have chosen K=%s (ask %s), which the envelope refuses when ask > "
                                                               "%.2f; V2 states the nearest feasible strike is %d strikes / %.2f%% from spot"
                                                               % (atm, atm_ask, max_entry_price, abs(idx_k - idx_atm),
                                                                  100.0 * (strike - spot) / spot))}}


def _ref_quote(row: dict) -> dict:
    """The INDICATIVE quote the selection was made on, with its identity, sealed for the intent-time cost estimate."""
    return {k: row.get(k) for k in ("bid", "ask", "bid_size", "ask_size", "timestamp_epoch") if row.get(k) is not None}
