"""OPTIONS EXPRESSION ENGINE V2 — a downstream consumer, never an alpha
engine.

Direction is fixed and one-way:

    qualified underlying opportunity
      -> underlying distribution / scenario branches
      -> live option chain
      -> expression comparison
      -> STOCK | option structure | NO_TRADE

NEVER: scan chains -> find something exciting -> invent an underlying
thesis. `evaluate()` refuses without an underlying decision id.

THE CENTRAL HONESTY: an UNCALIBRATED underlying distribution cannot
produce a calibrated expected option return. When forecast probabilities
are not commissioned the engine returns EXPRESSION_DIAGNOSTIC_ONLY with
scenario-conditioned payoffs — a payoff table, explicitly not an EV.
Multiplying scenario frequencies by payoffs to manufacture "expected
value" is precisely the laundering this project exists to prevent.

The engine is allowed — and expected — to conclude STOCK (options
destroy the edge via spread/IV) or NO_TRADE (every expression is
inferior). Those are features.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

EXPRESSION_V2_VERSION = "apex_expression_v2"
EXPRESSIONS = ("NO_TRADE", "STOCK", "LONG_CALL", "LONG_PUT",
               "CALL_DEBIT_SPREAD", "PUT_DEBIT_SPREAD")
SCENARIO_GRID = (-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03, 0.05)
CONTRACT_MULTIPLIER = 100


@dataclass(frozen=True)
class OptionSnapshot:
    """Every field UNKNOWN stays None. Greeks are never invented from
    insufficient data; a derived value carries a derived status."""
    symbol: str
    underlying: str
    expiration: str
    strike: float
    call_put: str
    bid: float | None = None
    ask: float | None = None
    timestamp: str | None = None
    quote_age_s: float | None = None
    open_interest: int | None = None
    volume: int | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    greeks_status: str = "UNKNOWN_NOT_SOURCED"
    multiplier: int = CONTRACT_MULTIPLIER
    tradability: str = "UNKNOWN"
    broker_capability: str = "UNKNOWN"

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return None

    @property
    def spread(self) -> float | None:
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None

    @property
    def spread_bps(self) -> float | None:
        m, s = self.mid, self.spread
        return round(s / m * 1e4, 1) if m and s is not None and m > 0 else None

    def quality(self) -> tuple:
        problems = []
        if self.bid is None or self.ask is None:
            problems.append("NO_TWO_SIDED_QUOTE")
        elif self.spread_bps and self.spread_bps > 1500:
            problems.append("SPREAD_WIDER_THAN_15PCT")
        if self.open_interest is not None and self.open_interest < 50:
            problems.append("THIN_OPEN_INTEREST")
        if self.quote_age_s is not None and self.quote_age_s > 60:
            problems.append("STALE_QUOTE")
        if self.tradability != "TRADABLE":
            problems.append(f"TRADABILITY_{self.tradability}")
        return (not problems), tuple(problems)


@dataclass(frozen=True)
class PayoffRow:
    underlying_return: float
    underlying_price: float
    net_payoff_usd: float
    return_on_risk: float | None


@dataclass(frozen=True)
class ExpressionCandidate:
    expression_type: str
    instrument_ids: tuple
    entry_cost_usd: float | None
    spread_paid_usd: float | None
    max_loss_usd: float | None
    max_gain_usd: float | None          # None = uncapped
    break_even: float | None
    payoff_grid: tuple
    liquidity_status: str
    data_quality: tuple
    notes: tuple = ()

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ExpressionDecision:
    underlying_decision_id: str
    expression_type: str
    instrument_ids: tuple
    rationale: str
    data_quality: str
    forecast_status: str
    cost_status: str
    liquidity_status: str
    payoff_summary: dict
    maximum_loss: float | None
    broker_capability: str
    broker_review_status: str
    candidates_considered: tuple
    authorization_power: str = "NONE"      # ERD-1: always NONE
    mode: str = "EXPRESSION_DIAGNOSTIC_ONLY"
    version: str = field(default=EXPRESSION_V2_VERSION)

    def __post_init__(self):
        if self.authorization_power != "NONE":
            raise ValueError("ERD-1: expression carries no authorization")
        if self.expression_type not in EXPRESSIONS:
            raise ValueError(f"undeclared expression {self.expression_type}")

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "expression_decision"
        return d


# ------------------------------------------------------------ payoff engine
def _leg_value(kind: str, strike: float, spot: float) -> float:
    return max(0.0, spot - strike) if kind == "CALL" else max(0.0,
                                                              strike - spot)


def payoff_grid(expression: str, legs: list, entry_cost: float,
                spot: float, qty: int = 1,
                grid=SCENARIO_GRID) -> tuple:
    """Deterministic terminal-value payoff. Explicitly AT EXPIRATION or
    at the declared horizon under intrinsic-value assumptions — no
    black-box math, no model IV surface, no LLM arithmetic. Early-exit
    (extrinsic) value is NOT modeled and that limitation is recorded."""
    rows = []
    risk = abs(entry_cost) if entry_cost else None
    for r in grid:
        s_t = spot * (1 + r)
        if expression == "STOCK":
            gross = (s_t - spot) * qty
        else:
            gross = 0.0
            for leg in legs:
                sign = 1 if leg["action"] == "BUY" else -1
                gross += (sign * _leg_value(leg["call_put"], leg["strike"],
                                            s_t) * CONTRACT_MULTIPLIER * qty)
        net = gross - (entry_cost or 0.0) if expression != "STOCK" else gross
        rows.append(PayoffRow(
            underlying_return=r, underlying_price=round(s_t, 4),
            net_payoff_usd=round(net, 2),
            return_on_risk=(round(net / risk, 4) if risk else None)))
    return tuple(rows)


def _build_candidates(spot: float, direction: str, chain: list,
                      shares: int, caps) -> list:
    """Bounded-risk structures only, and only those the venue supports."""
    out = []
    stock_notional = spot * shares
    out.append(ExpressionCandidate(
        expression_type="STOCK", instrument_ids=("UNDERLYING",),
        entry_cost_usd=round(stock_notional, 2), spread_paid_usd=None,
        max_loss_usd=round(stock_notional, 2),   # to zero, unstopped
        max_gain_usd=None, break_even=spot,
        payoff_grid=payoff_grid("STOCK", [], 0.0, spot, shares),
        liquidity_status="EQUITY_ASSUMED_LIQUID",
        data_quality=("OK",)))

    want = "CALL" if direction == "LONG" else "PUT"
    single_cap = ("options_long_call" if want == "CALL"
                  else "options_long_put")
    ok_single, why_single = (caps.supports(single_cap) if caps
                             else (False, "no capabilities"))
    ok_spread, why_spread = (caps.supports("options_debit_spread") if caps
                             else (False, "no capabilities"))
    same = [c for c in chain if c.call_put == want]
    if not same:
        return out
    atm = min(same, key=lambda c: abs(c.strike - spot))
    otm = sorted([c for c in same
                  if (c.strike > atm.strike if want == "CALL"
                      else c.strike < atm.strike)],
                 key=lambda c: abs(c.strike - atm.strike))

    if ok_single and atm.ask is not None:
        good, problems = atm.quality()
        cost = atm.ask * CONTRACT_MULTIPLIER
        out.append(ExpressionCandidate(
            expression_type=f"LONG_{want}",
            instrument_ids=(atm.symbol,),
            entry_cost_usd=round(cost, 2),
            spread_paid_usd=(round((atm.spread or 0) / 2
                                   * CONTRACT_MULTIPLIER, 2)),
            max_loss_usd=round(cost, 2), max_gain_usd=None,
            break_even=(atm.strike + atm.ask if want == "CALL"
                        else atm.strike - atm.ask),
            payoff_grid=payoff_grid(
                f"LONG_{want}",
                [{"action": "BUY", "call_put": want, "strike": atm.strike}],
                cost, spot),
            liquidity_status="OK" if good else "IMPAIRED",
            data_quality=problems or ("OK",)))
    elif not ok_single:
        out.append(_unavailable(f"LONG_{want}", why_single))

    if ok_spread and otm and atm.ask is not None and otm[0].bid is not None:
        short = otm[0]
        net = (atm.ask - short.bid) * CONTRACT_MULTIPLIER
        width = abs(short.strike - atm.strike) * CONTRACT_MULTIPLIER
        good_a, pa = atm.quality()
        good_b, pb = short.quality()
        etype = f"{want}_DEBIT_SPREAD"
        out.append(ExpressionCandidate(
            expression_type=etype,
            instrument_ids=(atm.symbol, short.symbol),
            entry_cost_usd=round(net, 2),
            spread_paid_usd=round(((atm.spread or 0) + (short.spread or 0))
                                  / 2 * CONTRACT_MULTIPLIER, 2),
            max_loss_usd=round(net, 2),
            max_gain_usd=round(width - net, 2),
            break_even=(atm.strike + net / CONTRACT_MULTIPLIER
                        if want == "CALL"
                        else atm.strike - net / CONTRACT_MULTIPLIER),
            payoff_grid=payoff_grid(
                etype,
                [{"action": "BUY", "call_put": want, "strike": atm.strike},
                 {"action": "SELL", "call_put": want,
                  "strike": short.strike}], net, spot),
            liquidity_status="OK" if (good_a and good_b) else "IMPAIRED",
            data_quality=tuple(set(pa + pb)) or ("OK",)))
    elif not ok_spread:
        out.append(_unavailable(f"{want}_DEBIT_SPREAD", why_spread))
    return out


def _unavailable(etype: str, why: str) -> ExpressionCandidate:
    return ExpressionCandidate(
        expression_type=etype, instrument_ids=(), entry_cost_usd=None,
        spread_paid_usd=None, max_loss_usd=None, max_gain_usd=None,
        break_even=None, payoff_grid=(), liquidity_status="UNAVAILABLE",
        data_quality=("BROKER_CAPABILITY_UNAVAILABLE",), notes=(why,))


def evaluate(decision: dict, spot: float, chain: list, capabilities,
             forecast_status: str, shares: int = 100,
             cost_status: str = "UNKNOWN") -> ExpressionDecision:
    """Compare expressions for an ALREADY-QUALIFIED underlying decision."""
    if not decision.get("decision_id"):
        raise ValueError("EXPRESSION V2 refuses to evaluate without an "
                         "underlying decision: chains never originate a "
                         "thesis")
    direction = decision.get("direction", "LONG")
    cands = _build_candidates(spot, direction, chain, shares, capabilities)
    usable = [c for c in cands if c.entry_cost_usd is not None
              and c.liquidity_status != "UNAVAILABLE"]

    calibrated = forecast_status in ("ML_CALIBRATED", "HYBRID_CALIBRATED")
    if not calibrated:
        # DIAGNOSTIC ONLY: rank by cost/liquidity honesty, never by a
        # manufactured expected value
        impaired = [c for c in usable if c.liquidity_status == "IMPAIRED"]
        options = [c for c in usable if c.expression_type != "STOCK"]
        clean_options = [c for c in options
                         if c.liquidity_status == "OK"]
        if not options:
            chosen, why = "STOCK", ("no option expression available "
                                    "(capability/chain); stock is the only "
                                    "expressible form")
        elif not clean_options:
            chosen, why = "STOCK", ("every option expression is liquidity-"
                                    "impaired; the spread would consume the "
                                    "underlying edge")
        else:
            chosen, why = "STOCK", ("forecast is UNCALIBRATED: an option "
                                    "structure cannot be justified without "
                                    "a calibrated distribution — stock is "
                                    "the honest default expression")
        del impaired
    else:
        chosen, why = "STOCK", ("calibrated selection path is not "
                                "commissioned in ERD-1")

    picked = next((c for c in cands if c.expression_type == chosen), None)
    return ExpressionDecision(
        underlying_decision_id=decision["decision_id"],
        expression_type=chosen,
        instrument_ids=(picked.instrument_ids if picked else ()),
        rationale=why,
        data_quality=("OK" if picked and picked.data_quality == ("OK",)
                      else "IMPAIRED_OR_UNKNOWN"),
        forecast_status=forecast_status,
        cost_status=cost_status,
        liquidity_status=(picked.liquidity_status if picked else "UNKNOWN"),
        payoff_summary={
            "grid_returns": list(SCENARIO_GRID),
            "chosen_payoff": [asdict(r) for r in
                              (picked.payoff_grid if picked else ())],
            "note": ("scenario-conditioned payoffs, NOT an expected value: "
                     "an uncalibrated distribution cannot produce a "
                     "calibrated expected option return")},
        maximum_loss=(picked.max_loss_usd if picked else None),
        broker_capability=(getattr(capabilities, "source", "UNKNOWN")),
        broker_review_status="NOT_REQUESTED",
        candidates_considered=tuple(c.as_record() for c in cands))
