"""BTC-L3 — PARTICIPANT STATE INTELLIGENCE.

Authorized 2026-08-23 after L2 passed and froze. L0-L2 answered "is the
state we record true?". L3 asks the first profit-facing question: "what
are the participants in this market doing, and which of them is
trapped?"

THE IDENTIFICATION PROBLEM COMES FIRST
Every futures contract has a long AND a short. Open interest rising
means contracts were CREATED -- it does not say who wanted them, who
was aggressive, or who will be hurt. The folk law

    price up + OI up = new longs

is therefore not a law. It is one reading among several, and the
others are not exotic: an aggressive seller absorbed by a willing
buyer produces the same print. This module is built so that reading
can never be stated as fact. Every interpretation carries its
COMPETING EXPLANATIONS, and an interpretation with no competitor is a
bug, not a certainty.

WHY NO CALIBRATED PROBABILITIES YET
"Probabilistic" here means ORDINAL support with named alternatives, not
a number like 0.73. We have no resolved outcome data linking these
states to what followed, so any probability would be invented. When
prospective evidence exists, calibration can be fitted -- against
outcomes, by a governed process, never by an author's intuition. Until
then `calibration: NONE_FITTED` is stamped on every reading.

QUALITY AWARENESS IS NOT DECORATION
An interpretation is only as good as the cadence of its inputs. Daily-
published open interest cannot support a five-minute claim about
positioning. Where the inputs cannot carry the inference, the reading
is NOT_ESTIMABLE -- never a weaker version of the same claim.

decision_power: NONE -- L3 is interpretation. It sizes nothing, and it
authorizes nothing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"

# The interpretations L3 is authorized to emit (operator list).
INTERPRETATIONS = (
    "LEVERAGE_EXPANSION",
    "LEVERAGE_CONTRACTION",
    "POSSIBLE_LONG_BUILD",
    "POSSIBLE_SHORT_BUILD",
    "LONG_TRAP",
    "SHORT_TRAP",
    "COVERING",
    "SPOT_LED",
    "PERP_LED",
    "FUNDING_CROWDING",
    "BOOK_WITHDRAWAL",
    "CASCADE_SUSCEPTIBILITY",
    "DELEVERAGING_EXHAUSTION",
)

# Ordinal support. Deliberately coarse: a finer scale would imply a
# precision the evidence does not have.
SUPPORT_LEVELS = ("CONSISTENT", "WEAKLY_CONSISTENT", "INCONSISTENT",
                  NOT_ESTIMABLE)

# Input cadence required before an interpretation may be attempted at
# an intraday horizon. Pre-declared, structural, not fitted.
REQUIRES_REALTIME_OI = ("LEVERAGE_EXPANSION", "LEVERAGE_CONTRACTION",
                        "POSSIBLE_LONG_BUILD", "POSSIBLE_SHORT_BUILD",
                        "COVERING", "DELEVERAGING_EXHAUSTION")

# Materiality floors: below these a "change" is indistinguishable from
# noise and must not be read as a signal. Structural sign tests, not
# profitability thresholds.
MIN_PRICE_MOVE_PCT = 0.10
MIN_OI_CHANGE_PCT = 0.25
MIN_BOOK_CHANGE_PCT = 10.0


@dataclass(frozen=True)
class Reading:
    """One interpretation, with everything needed to argue against it."""
    interpretation: str
    support: str
    because: tuple = ()
    competing_explanations: tuple = ()
    inputs_used: tuple = ()
    limiting_factor: str | None = None
    calibration: str = "NONE_FITTED"
    decision_power: str = "NONE"

    def as_record(self) -> dict:
        return {"kind": "btc_participant_reading", **asdict(self)}


@dataclass(frozen=True)
class ParticipantState:
    symbol: str
    T: str
    readings: tuple = ()
    input_quality: dict = field(default_factory=dict)
    data_quality: str = "UNKNOWN"
    identification_law: str = (
        "open interest identifies CONTRACTS CREATED, never WHO wanted "
        "them; every reading below has a competing explanation and none "
        "may be reported as fact")
    calibration: str = "NONE_FITTED"
    evidence_class: str = "PROSPECTIVE_LIVE_CAPTURE"
    decision_power: str = "NONE"

    def as_record(self) -> dict:
        return {"kind": "btc_participant_state", **asdict(self)}

    def by_name(self, name: str) -> Reading | None:
        return next((r for r in self.readings
                     if r.interpretation == name), None)

    def supported(self, level: str = "CONSISTENT") -> list:
        return [r for r in self.readings if r.support == level]


@dataclass(frozen=True)
class Inputs:
    """Everything L3 may look at, each with its own pedigree.

    Anything absent is absent -- there is no default value, because a
    default is a guess wearing a number's clothes."""
    price_change_pct: float | None = None
    oi_change_pct: float | None = None
    oi_cadence: str = "OI_UNKNOWN_CADENCE"
    oi_age_s: float | None = None
    funding_rate_annualized: float | None = None
    funding_change: float | None = None
    spot_change_pct: float | None = None
    perp_change_pct: float | None = None
    book_depth_change_pct: float | None = None
    book_quality: str = "UNKNOWN"
    dvol: float | None = None
    dvol_change: float | None = None
    realized_vol: float | None = None
    horizon_minutes: float | None = None

    def quality(self) -> dict:
        return {
            "oi_cadence": self.oi_cadence,
            "oi_age_s": self.oi_age_s,
            "book_quality": self.book_quality,
            "has_price": self.price_change_pct is not None,
            "has_oi": self.oi_change_pct is not None,
            "has_funding": self.funding_rate_annualized is not None,
            "has_spot_and_perp": (self.spot_change_pct is not None
                                  and self.perp_change_pct is not None),
            "has_book": self.book_depth_change_pct is not None,
            "has_vol": self.dvol is not None,
        }


def _oi_supports_intraday(inp: Inputs) -> tuple:
    """Can this OI feed carry an intraday positioning claim?"""
    from apex.btc_sleeve.semantics import (
        OI_DAILY_PUBLISHED, OI_DELAYED, OI_NOT_AVAILABLE, OI_REALTIME,
        OI_UNKNOWN_CADENCE)
    if inp.oi_change_pct is None:
        return False, "no open-interest observation"
    if inp.oi_cadence == OI_REALTIME:
        return True, None
    if inp.oi_cadence == OI_DELAYED:
        h = inp.horizon_minutes
        if h is not None and inp.oi_age_s is not None \
                and inp.oi_age_s <= h * 60:
            return True, None
        return False, ("delayed open interest is older than the "
                       "horizon it would be used to describe")
    if inp.oi_cadence == OI_DAILY_PUBLISHED:
        return False, ("daily-published open interest cannot support an "
                       "intraday positioning claim -- it describes "
                       "yesterday's book, not this hour's")
    if inp.oi_cadence in (OI_NOT_AVAILABLE, OI_UNKNOWN_CADENCE):
        return False, f"open-interest cadence is {inp.oi_cadence}"
    return False, f"unrecognized OI cadence {inp.oi_cadence!r}"


def _material(x: float | None, floor: float) -> bool:
    return x is not None and abs(x) >= floor


def _ne(name: str, why: str, used=()) -> Reading:
    return Reading(interpretation=name, support=NOT_ESTIMABLE,
                   because=(why,), limiting_factor=why,
                   inputs_used=tuple(used))


# ---------------------------------------------------------------------
# The readings. Each is a small, arguable claim -- never a law.

def _leverage(inp: Inputs, oi_ok: bool, oi_why) -> list:
    if not oi_ok:
        return [_ne("LEVERAGE_EXPANSION", oi_why),
                _ne("LEVERAGE_CONTRACTION", oi_why)]
    if not _material(inp.oi_change_pct, MIN_OI_CHANGE_PCT):
        why = (f"open interest moved {inp.oi_change_pct:+.2f}%, inside "
               f"the {MIN_OI_CHANGE_PCT}% noise floor")
        return [Reading("LEVERAGE_EXPANSION", "INCONSISTENT", (why,),
                        ("flat positioning",), ("oi_change_pct",)),
                Reading("LEVERAGE_CONTRACTION", "INCONSISTENT", (why,),
                        ("flat positioning",), ("oi_change_pct",))]
    up = inp.oi_change_pct > 0
    grew = Reading(
        "LEVERAGE_EXPANSION",
        "CONSISTENT" if up else "INCONSISTENT",
        (f"open interest {'rose' if up else 'fell'} "
         f"{inp.oi_change_pct:+.2f}%: contracts were "
         f"{'created' if up else 'destroyed'}",),
        ("contract creation alone does not say which side sought it, "
         "nor whether either side is leveraged -- a fully collateralised "
         "buyer expands OI exactly as a levered one does",),
        ("oi_change_pct", "oi_cadence"))
    shrank = Reading(
        "LEVERAGE_CONTRACTION",
        "CONSISTENT" if not up else "INCONSISTENT",
        (f"open interest {'fell' if not up else 'rose'} "
         f"{inp.oi_change_pct:+.2f}%",),
        ("positions can close for reasons unrelated to stress: "
         "expiry, rolls, and profit-taking all reduce OI",),
        ("oi_change_pct", "oi_cadence"))
    return [grew, shrank]


def _builds(inp: Inputs, oi_ok: bool, oi_why) -> list:
    """The folk law lives here, and is refused the status of a law."""
    if not oi_ok:
        return [_ne("POSSIBLE_LONG_BUILD", oi_why),
                _ne("POSSIBLE_SHORT_BUILD", oi_why)]
    if inp.price_change_pct is None:
        w = "no price change observed alongside open interest"
        return [_ne("POSSIBLE_LONG_BUILD", w),
                _ne("POSSIBLE_SHORT_BUILD", w)]
    if not (_material(inp.oi_change_pct, MIN_OI_CHANGE_PCT)
            and _material(inp.price_change_pct, MIN_PRICE_MOVE_PCT)):
        w = "price or open-interest change is inside the noise floor"
        return [Reading("POSSIBLE_LONG_BUILD", "INCONSISTENT", (w,),
                        ("noise",), ("price_change_pct",)),
                Reading("POSSIBLE_SHORT_BUILD", "INCONSISTENT", (w,),
                        ("noise",), ("price_change_pct",))]

    oi_up = inp.oi_change_pct > 0
    px_up = inp.price_change_pct > 0
    used = ("price_change_pct", "oi_change_pct", "funding_rate_annualized")

    # The ALWAYS-PRESENT competitor: the other side of every contract.
    mirror = ("every created contract has a short on the other side, so "
              "this print is equally consistent with shorts being "
              "willingly supplied into demand")
    aggressor = ("price direction indicates which side was more "
                 "AGGRESSIVE, not which side is larger or more "
                 "vulnerable")

    long_build, short_build = "INCONSISTENT", "INCONSISTENT"
    why_long, why_short = [], []
    if oi_up and px_up:
        long_build = "WEAKLY_CONSISTENT"
        why_long.append(
            f"price {inp.price_change_pct:+.2f}% with open interest "
            f"{inp.oi_change_pct:+.2f}%: new contracts created while "
            f"buyers were the aggressors")
        why_short.append("price rose while contracts were created, "
                         "which cuts against fresh short initiation "
                         "being the aggressive side")
    elif oi_up and not px_up:
        short_build = "WEAKLY_CONSISTENT"
        why_short.append(
            f"price {inp.price_change_pct:+.2f}% with open interest "
            f"{inp.oi_change_pct:+.2f}%: contracts created while "
            f"sellers were the aggressors")
        why_long.append("price fell while contracts were created")
    else:
        why_long.append("open interest fell: this is closing, not "
                        "building")
        why_short.append("open interest fell: this is closing, not "
                         "building")

    # Funding can corroborate, and is itself ambiguous.
    f = inp.funding_rate_annualized
    if f is not None:
        if f > 0 and long_build == "WEAKLY_CONSISTENT":
            long_build = "CONSISTENT"
            why_long.append(
                f"funding {f:+.2%} annualized: longs are PAYING, which "
                f"corroborates crowded long positioning")
        elif f < 0 and short_build == "WEAKLY_CONSISTENT":
            short_build = "CONSISTENT"
            why_short.append(
                f"funding {f:+.2%} annualized: shorts are PAYING")

    return [
        Reading("POSSIBLE_LONG_BUILD", long_build, tuple(why_long),
                (mirror, aggressor,
                 "hedgers and basis traders create OI with no "
                 "directional view at all"), used),
        Reading("POSSIBLE_SHORT_BUILD", short_build, tuple(why_short),
                (mirror, aggressor,
                 "short OI may be a delta hedge against spot held "
                 "elsewhere, which is not a bearish participant"), used),
    ]


def _traps(inp: Inputs, oi_ok: bool, oi_why) -> list:
    """A trap is a POSITION BUILT then IMMEDIATELY UNDERWATER. It needs
    both halves; a price move alone traps nobody."""
    if not oi_ok:
        return [_ne("LONG_TRAP", oi_why), _ne("SHORT_TRAP", oi_why)]
    if inp.price_change_pct is None:
        w = "no price change observed"
        return [_ne("LONG_TRAP", w), _ne("SHORT_TRAP", w)]

    f = inp.funding_rate_annualized
    oi_up = (inp.oi_change_pct or 0) > 0
    px = inp.price_change_pct
    long_trap = short_trap = "INCONSISTENT"
    wl, ws = [], []

    if oi_up and f is not None and f > 0 and px < -MIN_PRICE_MOVE_PCT:
        long_trap = "WEAKLY_CONSISTENT"
        wl.append(f"contracts were created while longs paid funding "
                  f"({f:+.2%}), and price then fell {px:+.2f}% -- "
                  f"positioning added into a move against it")
    if oi_up and f is not None and f < 0 and px > MIN_PRICE_MOVE_PCT:
        short_trap = "WEAKLY_CONSISTENT"
        ws.append(f"contracts were created while shorts paid funding "
                  f"({f:+.2%}), and price then rose {px:+.2f}%")

    common = (
        "underwater is not the same as forced: an unlevered or hedged "
        "participant can sit indefinitely",
        "we observe aggregate open interest, not the entry price of any "
        "position, so 'underwater' is inferred rather than measured")
    return [
        Reading("LONG_TRAP", long_trap, tuple(wl), common,
                ("oi_change_pct", "funding_rate_annualized",
                 "price_change_pct")),
        Reading("SHORT_TRAP", short_trap, tuple(ws), common,
                ("oi_change_pct", "funding_rate_annualized",
                 "price_change_pct")),
    ]


def _covering(inp: Inputs, oi_ok: bool, oi_why) -> Reading:
    if not oi_ok:
        return _ne("COVERING", oi_why)
    if inp.price_change_pct is None:
        return _ne("COVERING", "no price change observed")
    oi_dn = (inp.oi_change_pct or 0) < -MIN_OI_CHANGE_PCT
    px_up = inp.price_change_pct > MIN_PRICE_MOVE_PCT
    sup = "WEAKLY_CONSISTENT" if (oi_dn and px_up) else "INCONSISTENT"
    return Reading(
        "COVERING", sup,
        ((f"open interest fell {inp.oi_change_pct:+.2f}% while price "
          f"rose {inp.price_change_pct:+.2f}%: contracts destroyed "
          f"into strength",) if sup != "INCONSISTENT" else
         ("the pattern of falling OI into rising price is absent",)),
        ("longs taking profit destroy open interest into strength in "
         "exactly the same way shorts covering do",
         "expiry and roll activity reduce OI without any participant "
         "being pressured"),
        ("oi_change_pct", "price_change_pct"))


def _leadership(inp: Inputs) -> list:
    if inp.spot_change_pct is None or inp.perp_change_pct is None:
        w = "spot and perpetual moves are not both observed"
        return [_ne("SPOT_LED", w), _ne("PERP_LED", w)]
    d = inp.perp_change_pct - inp.spot_change_pct
    if abs(d) < MIN_PRICE_MOVE_PCT / 2:
        w = f"spot and perp moved together (gap {d:+.3f}%)"
        return [Reading("SPOT_LED", "INCONSISTENT", (w,),
                        ("no divergence to attribute",),
                        ("spot_change_pct", "perp_change_pct")),
                Reading("PERP_LED", "INCONSISTENT", (w,),
                        ("no divergence to attribute",),
                        ("spot_change_pct", "perp_change_pct"))]
    perp_led = d > 0 if inp.perp_change_pct > 0 else d < 0
    caution = ("a contemporaneous gap is not lead-lag: without "
               "timestamped cross-venue sequencing this is a "
               "divergence measurement, not proof of causation",
               "venue-specific liquidity can open a gap with no "
               "informational content at all")
    return [
        Reading("PERP_LED", "WEAKLY_CONSISTENT" if perp_led
                else "INCONSISTENT",
                (f"perp moved {inp.perp_change_pct:+.2f}% vs spot "
                 f"{inp.spot_change_pct:+.2f}% (gap {d:+.3f}%)",),
                caution, ("spot_change_pct", "perp_change_pct")),
        Reading("SPOT_LED", "WEAKLY_CONSISTENT" if not perp_led
                else "INCONSISTENT",
                (f"spot moved {inp.spot_change_pct:+.2f}% vs perp "
                 f"{inp.perp_change_pct:+.2f}% (gap {d:+.3f}%)",),
                caution, ("spot_change_pct", "perp_change_pct")),
    ]


def _funding_crowding(inp: Inputs) -> Reading:
    f = inp.funding_rate_annualized
    if f is None:
        return _ne("FUNDING_CROWDING", "no funding observation")
    extreme = abs(f) >= 0.30           # 30%/yr: a large carry to pay
    elevated = abs(f) >= 0.10
    sup = ("CONSISTENT" if extreme else
           "WEAKLY_CONSISTENT" if elevated else "INCONSISTENT")
    side = "longs" if f > 0 else "shorts"
    return Reading(
        "FUNDING_CROWDING", sup,
        (f"funding {f:+.2%} annualized: {side} are paying to hold, "
         f"which is what crowding costs",),
        ("funding is a price, and a high price can reflect scarce "
         "balance-sheet rather than crowded conviction",
         "a persistent carry trade pays funding by design and is not "
         "a crowded directional bet"),
        ("funding_rate_annualized",))


def _book_withdrawal(inp: Inputs) -> Reading:
    if inp.book_depth_change_pct is None:
        return _ne("BOOK_WITHDRAWAL", "no book depth observation")
    if inp.book_quality != "VALID":
        return _ne("BOOK_WITHDRAWAL",
                   f"book quality is {inp.book_quality}: an invalid "
                   f"book cannot measure its own thinning")
    gone = inp.book_depth_change_pct <= -MIN_BOOK_CHANGE_PCT
    return Reading(
        "BOOK_WITHDRAWAL", "CONSISTENT" if gone else "INCONSISTENT",
        (f"resting depth changed {inp.book_depth_change_pct:+.1f}%",),
        ("makers widen for scheduled events without any view on "
         "direction",
         "depth measured at a fixed distance falls automatically when "
         "volatility rises, without anyone withdrawing"),
        ("book_depth_change_pct", "book_quality"))


def _cascade(inp: Inputs, readings: list) -> Reading:
    """Susceptibility is a CONJUNCTION: crowded positioning AND a thin
    book. Either alone is ordinary."""
    def sup(name):
        r = next((x for x in readings if x.interpretation == name), None)
        return r.support if r else NOT_ESTIMABLE

    crowd = sup("FUNDING_CROWDING")
    thin = sup("BOOK_WITHDRAWAL")
    if NOT_ESTIMABLE in (crowd, thin):
        return _ne("CASCADE_SUSCEPTIBILITY",
                   "needs both crowding and book depth; one is not "
                   "estimable")
    both = (crowd in ("CONSISTENT", "WEAKLY_CONSISTENT")
            and thin == "CONSISTENT")
    return Reading(
        "CASCADE_SUSCEPTIBILITY",
        "CONSISTENT" if both else "INCONSISTENT",
        ((f"crowding {crowd} AND book withdrawal {thin}: positions that "
          f"must be closed into a book that has thinned",) if both else
         (f"conjunction absent (crowding {crowd}, book {thin})",)),
        ("susceptibility is not prediction -- most thin books with "
         "crowded funding never cascade",
         "we cannot see stop placement or margin buffers, which is what "
         "actually determines forced selling"),
        ("funding_rate_annualized", "book_depth_change_pct"))


def _exhaustion(inp: Inputs, oi_ok: bool, oi_why) -> Reading:
    if not oi_ok:
        return _ne("DELEVERAGING_EXHAUSTION", oi_why)
    if inp.price_change_pct is None:
        return _ne("DELEVERAGING_EXHAUSTION", "no price change observed")
    big_unwind = (inp.oi_change_pct or 0) <= -2.0
    price_steady = abs(inp.price_change_pct) < MIN_PRICE_MOVE_PCT * 2
    both = big_unwind and price_steady
    return Reading(
        "DELEVERAGING_EXHAUSTION",
        "WEAKLY_CONSISTENT" if both else "INCONSISTENT",
        ((f"open interest fell {inp.oi_change_pct:+.2f}% while price "
          f"held ({inp.price_change_pct:+.2f}%): size left without "
          f"moving the market",) if both else
         ("the pattern of heavy unwind against a steady price is "
          "absent",)),
        ("a steady price during unwind may simply mean a patient buyer "
         "was present, which says nothing about exhaustion",
         "exhaustion is only visible afterwards; in the moment it is "
         "indistinguishable from a pause"),
        ("oi_change_pct", "price_change_pct"))


def interpret(*, symbol: str, T: str, inputs: Inputs) -> ParticipantState:
    """Read participant state. Never asserts; always argues."""
    oi_ok, oi_why = _oi_supports_intraday(inputs)
    readings = []
    readings += _leverage(inputs, oi_ok, oi_why)
    readings += _builds(inputs, oi_ok, oi_why)
    readings += _traps(inputs, oi_ok, oi_why)
    readings.append(_covering(inputs, oi_ok, oi_why))
    readings += _leadership(inputs)
    readings.append(_funding_crowding(inputs))
    readings.append(_book_withdrawal(inputs))
    readings.append(_cascade(inputs, readings))
    readings.append(_exhaustion(inputs, oi_ok, oi_why))

    q = inputs.quality()
    estimable = sum(1 for r in readings if r.support != NOT_ESTIMABLE)
    dq = ("FULL" if estimable == len(readings) else
          "PARTIAL" if estimable else "INSUFFICIENT")
    return ParticipantState(symbol=symbol, T=T, readings=tuple(readings),
                            input_quality=q, data_quality=dq)
