"""BTC PAPER EXECUTION + OUTCOME RESOLVER.

The last rung of L3 before the PAPER_EXPLORATORY review. The laws here
were not invented for BTC -- they are the ones the Options sleeve
proved on real data, applied to the L2 book:

SEQUENCE LAW   the BEFORE card is sealed first; entry and resolution
               both refuse without it. Ordering is structural, not
               discipline.

FILL LAW       we CROSS THE BOOK: a long pays the ask, a short hits
               the bid, at the venue's own quoted touch. No midpoint,
               no model price. Fill size is capped by the size that
               was actually resting -- a fill larger than the book is
               fiction.

RISK LAW       1R is the DECLARED loss at the geometry's invalidation,
               never "whatever we lost". capital, max loss and 1R stay
               three different numbers.

FRICTION       pnl = mid_change - entry_friction - exit_friction,
IDENTITY       exactly. A loss satisfying it came from the market; a
               loss violating it came from us. The options replay
               showed friction can BE the entire result -- BTC records
               it from trade one.

The book here is the L2 engine's output, trusted only because L2
passed acceptance and froze.

decision_power: NONE_PAPER -- simulation. No order exists.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

NOT_ESTIMABLE = "NOT_ESTIMABLE"

# Bitnomial BTC perp: 0.01 BTC per contract; book prices are TICKS
# with tick value derived from the product spec ($5/tick equivalent at
# the current multiplier -- carried as a parameter, never hardcoded
# into P&L math silently).
DEFAULT_TICK_VALUE_USD = 5.0


class ExecutionRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class BTCPaperFill:
    subject: str
    direction: str
    T: str
    entry_price: float            # the touch we crossed, in ticks
    contracts: int
    fill_capped_by_book: bool
    side_crossed: str             # ASK for long, BID for short
    entry_mid: float
    entry_friction_ticks: float   # half-spread paid, per contract
    tick_value_usd: float
    # ---- RISK LAW
    invalidation: float | None
    declared_1R_usd: float | str
    risk_basis: str
    capital_note: str = ("perp margin, not premium -- capital consumed "
                         "is venue margin, recorded separately from 1R")
    sealed_card_hash: str = ""
    law: str = ("crossed the venue's own touch; no midpoint, no model "
                "price, size capped by resting liquidity")
    decision_power: str = "NONE_PAPER"

    def as_record(self) -> dict:
        return {"kind": "btc_paper_fill", **asdict(self)}


def simulate_entry(*, geometry, T: str, contracts: int = 1,
                   sealed_card_hash: str | None = None,
                   tick_value_usd: float = DEFAULT_TICK_VALUE_USD
                   ) -> BTCPaperFill:
    """Fill an attackable geometry at the quoted touch."""
    if not sealed_card_hash or len(sealed_card_hash) < 32:
        raise ExecutionRefused(
            "paper execution requires a sealed BEFORE card -- the "
            "decision is sealed before it is filled, never after")
    if not geometry.attackable:
        raise ExecutionRefused(
            f"geometry is not attackable "
            f"(structural: {list(geometry.structural_wounds)}) -- "
            f"refusals are refusals, not suggestions")
    bb, ba = geometry.best_bid, geometry.best_ask
    if bb is None or ba is None or ba <= bb:
        raise ExecutionRefused("no executable two-sided market")

    if geometry.direction == "LONG":
        px, side = ba, "ASK"
    elif geometry.direction == "SHORT":
        px, side = bb, "BID"
    else:
        raise ExecutionRefused(
            f"direction {geometry.direction!r} is not executable")

    avail = geometry.executable_size
    capped = False
    if isinstance(avail, (int, float)) and avail < contracts:
        contracts, capped = int(avail), True
    if contracts <= 0:
        raise ExecutionRefused("zero contracts available at the touch")

    mid = (bb + ba) / 2.0
    inval = geometry.invalidation
    if inval is not None:
        r_usd = round(abs(px - inval) * tick_value_usd * contracts, 2)
        basis = "PLANNED_INVALIDATION"
    else:
        # geometry with no invalidation is structurally unattackable,
        # so this is unreachable in practice -- but never silent
        r_usd, basis = NOT_ESTIMABLE, "NOT_DECLARED"

    return BTCPaperFill(
        subject=geometry.subject, direction=geometry.direction, T=T,
        entry_price=float(px), contracts=contracts,
        fill_capped_by_book=capped, side_crossed=side,
        entry_mid=round(mid, 4),
        entry_friction_ticks=round(abs(px - mid), 4),
        tick_value_usd=tick_value_usd,
        invalidation=inval, declared_1R_usd=r_usd, risk_basis=basis,
        sealed_card_hash=sealed_card_hash)


@dataclass(frozen=True)
class BTCOutcome:
    sealed_card_hash: str
    subject: str
    direction: str
    exit_reason: str              # INVALIDATED / TARGET / HORIZON
    entry_price: float
    exit_price: float | str
    contracts: int
    pnl_usd: float | str
    r_multiple: float | str
    declared_1R_usd: float | str
    risk_basis: str
    mid_change_usd: float | str
    entry_friction_usd: float | str
    exit_friction_usd: float | str
    friction_identity_holds: bool | str
    mfe_ticks: float | str = NOT_ESTIMABLE
    mae_ticks: float | str = NOT_ESTIMABLE
    evidence_class: str = "PROSPECTIVE_PAPER"
    law: str = ("closed at quoted sides: a long exits on the BID, a "
                "short exits on the ASK")
    decision_power: str = "NONE_PAPER"

    def as_record(self) -> dict:
        return {"kind": "btc_paper_outcome", **asdict(self)}


def resolve(*, fill: BTCPaperFill, sealed_card_hash: str,
            path: list, exit_reason_horizon: str = "HORIZON",
            target: float | None = None) -> BTCOutcome:
    """Resolve one sealed paper fill against the observed book path.

    `path` is a chronological list of book tops
    ({best_bid_raw, best_ask_raw, book_quality}). Exit fires on the
    FIRST of: invalidation touched, target touched, or path exhausted
    (the pre-declared horizon). Ties inside one observation resolve
    AGAINST us -- when a single top shows both levels reached, we take
    the invalidation, because favourable ambiguity is how paper systems
    flatter themselves."""
    if not sealed_card_hash or len(sealed_card_hash) < 32:
        raise ExecutionRefused("resolution requires the sealed card")
    if sealed_card_hash != fill.sealed_card_hash:
        raise ExecutionRefused(
            "card mismatch: this outcome does not belong to that fill")

    sign = 1.0 if fill.direction == "LONG" else -1.0
    inval, mfe, mae = fill.invalidation, None, None
    exit_top, reason = None, exit_reason_horizon

    usable = [t for t in path if t.get("book_quality") == "VALID"
              and t.get("best_bid_raw") is not None
              and t.get("best_ask_raw") is not None
              and t["best_ask_raw"] > t["best_bid_raw"]]
    if not usable:
        return BTCOutcome(
            sealed_card_hash=sealed_card_hash, subject=fill.subject,
            direction=fill.direction, exit_reason="NO_VALID_PATH",
            entry_price=fill.entry_price, exit_price=NOT_ESTIMABLE,
            contracts=fill.contracts, pnl_usd=NOT_ESTIMABLE,
            r_multiple=NOT_ESTIMABLE,
            declared_1R_usd=fill.declared_1R_usd,
            risk_basis=fill.risk_basis, mid_change_usd=NOT_ESTIMABLE,
            entry_friction_usd=NOT_ESTIMABLE,
            exit_friction_usd=NOT_ESTIMABLE,
            friction_identity_holds=NOT_ESTIMABLE)

    for top in usable:
        bb, ba = top["best_bid_raw"], top["best_ask_raw"]
        mid = (bb + ba) / 2.0
        exc = sign * (mid - fill.entry_mid)
        mfe = exc if mfe is None else max(mfe, exc)
        mae = exc if mae is None else min(mae, exc)
        # our exit side: long sells the bid, short buys the ask
        exit_px = bb if fill.direction == "LONG" else ba
        hit_inval = (inval is not None and
                     (exit_px <= inval if fill.direction == "LONG"
                      else exit_px >= inval))
        hit_target = (target is not None and
                      (exit_px >= target if fill.direction == "LONG"
                       else exit_px <= target))
        if hit_inval:                    # ties resolve AGAINST us
            exit_top, reason = top, "INVALIDATED"
            break
        if hit_target:
            exit_top, reason = top, "TARGET"
            break
    if exit_top is None:
        exit_top = usable[-1]

    bb, ba = exit_top["best_bid_raw"], exit_top["best_ask_raw"]
    exit_px = bb if fill.direction == "LONG" else ba
    exit_mid = (bb + ba) / 2.0
    mult = fill.tick_value_usd * fill.contracts

    pnl = round(sign * (exit_px - fill.entry_price) * mult, 2)
    mid_ch = round(sign * (exit_mid - fill.entry_mid) * mult, 2)
    ent_f = round(fill.entry_friction_ticks * mult, 2)
    exi_f = round(abs(exit_px - exit_mid) * mult, 2)
    ident = abs(mid_ch - ent_f - exi_f - pnl) < 0.02

    r1 = fill.declared_1R_usd
    r_mult = (round(pnl / r1, 4)
              if isinstance(r1, (int, float)) and r1 > 0
              else NOT_ESTIMABLE)

    return BTCOutcome(
        sealed_card_hash=sealed_card_hash, subject=fill.subject,
        direction=fill.direction, exit_reason=reason,
        entry_price=fill.entry_price, exit_price=float(exit_px),
        contracts=fill.contracts, pnl_usd=pnl, r_multiple=r_mult,
        declared_1R_usd=r1, risk_basis=fill.risk_basis,
        mid_change_usd=mid_ch, entry_friction_usd=ent_f,
        exit_friction_usd=exi_f, friction_identity_holds=ident,
        mfe_ticks=(round(mfe, 4) if mfe is not None else NOT_ESTIMABLE),
        mae_ticks=(round(mae, 4) if mae is not None else NOT_ESTIMABLE))
