"""FRICTION ATTRIBUTION — why did this attack win or lose?

The 105-symbol-day replay showed the Options Predator's real problem is
not direction. Aggregate mid P&L was −338 while friction was 15,318,
and 75 of 304 trades were RIGHT ON MID and still lost. A system that
only records "won/lost" cannot see that, and would respond by trying to
forecast harder — the wrong repair.

So every resolved attack is decomposed with the exact identity

    executable_pnl = mid_change − entry_friction − exit_friction

and then diagnosed. The diagnosis distinguishes the four failures that
demand completely different responses:

    THESIS_WRONG              the move never came        -> forecast
    THESIS_RIGHT_OPTION_LOST  move came, wrong instrument-> expression
    THESIS_RIGHT_FRICTION_KILLED  move came, spread ate it -> execution
    EXECUTION_FAILURE         could not transact at all  -> venue/liquidity

CAUSALITY: every input here is either sealed in the BEFORE card or
observed after the fact. Nothing computed here may flow back into a
BEFORE card, and no threshold below was fitted to replay outcomes --
they are structural sign tests plus pre-declared exploratory priors.

decision_power: NONE -- a diagnostic.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"

# Pre-declared exploratory priors. NOT learned thresholds: each is a
# statement about what a word MEANS, not about what is profitable.
MATERIAL_MID_MOVE = 0.0      # a sign test: did mid value rise at all
IV_CRUSH_DROP = -0.02        # 2 vol points, the conventional reading
THETA_HEAVY_DTE = 7.0        # inside a week, decay dominates the day

CLASSES = (
    "THESIS_WRONG",
    "THESIS_RIGHT_OPTION_LOST",
    "THESIS_RIGHT_FRICTION_KILLED",
    "IV_CRUSH",
    "THETA_BURDEN",
    "BAD_ENTRY",
    "BAD_EXPRESSION",
    "EXECUTION_FAILURE",
    "THESIS_RIGHT_FRICTION_SURVIVED",
)


@dataclass(frozen=True)
class FrictionAttribution:
    expression: str
    # ---- the identity, term by term
    underlying_move_pct: float | str = NOT_ESTIMABLE
    mid_change: float | str = NOT_ESTIMABLE
    entry_friction: float | str = NOT_ESTIMABLE
    exit_friction: float | str = NOT_ESTIMABLE
    total_friction: float | str = NOT_ESTIMABLE
    executable_pnl: float | str = NOT_ESTIMABLE
    friction_cost_share: float | str = NOT_ESTIMABLE
    r_multiple: float | str = NOT_ESTIMABLE
    mfe: float | str = NOT_ESTIMABLE
    mae: float | str = NOT_ESTIMABLE
    iv_change: float | str = NOT_ESTIMABLE
    dte_at_entry: float | str = NOT_ESTIMABLE
    # ---- the diagnosis
    primary_class: str = NOT_ESTIMABLE
    contributing: tuple = ()
    friction_verdict: str = NOT_ESTIMABLE
    reasoning: tuple = ()
    identity_holds: bool | str = NOT_ESTIMABLE
    evidence_class: str = "PROSPECTIVE_PAPER"
    decision_power: str = "NONE"
    notes: tuple = field(default_factory=tuple)

    def as_record(self) -> dict:
        return {"kind": "options_friction_attribution", **asdict(self)}


def _num(x):
    return x if isinstance(x, (int, float)) else None


def attribute(*, outcome, candidate=None, dte_at_entry=None,
              evidence_class: str = "PROSPECTIVE_PAPER"
              ) -> FrictionAttribution:
    """Diagnose one resolved attack.

    `outcome` is a paper_execution.Outcome. Anything the outcome could
    not estimate stays NOT_ESTIMABLE -- a diagnosis built on a guess is
    worse than no diagnosis."""
    pnl = _num(outcome.pnl)
    mid = _num(outcome.mid_change)
    exf = _num(outcome.exit_friction)
    ur = _num(outcome.underlying_return_pct)
    ivc = _num(outcome.iv_change)
    reasons, contributing = [], []

    if pnl is None:
        return FrictionAttribution(
            expression=outcome.expression,
            primary_class="EXECUTION_FAILURE",
            underlying_move_pct=outcome.underlying_return_pct,
            evidence_class=evidence_class,
            reasoning=("no executable round trip existed -- the "
                       "position could not be marked out at quoted "
                       "sides, so no P&L may be claimed",),
            notes=("EXECUTION_FAILURE is not a loss of zero; it is the "
                   "absence of a tradeable market",))

    entf = tot = share = NOT_ESTIMABLE
    if mid is not None and exf is not None:
        entf = round(mid - exf - pnl, 2)
        tot = round(mid - pnl, 2)
        denom = abs(mid) if abs(mid) > 1e-9 else None
        share = round(tot / denom, 3) if denom else NOT_ESTIMABLE

    # ---------------- the primary diagnosis
    if mid is None:
        primary = NOT_ESTIMABLE
        reasons.append("mid value unavailable; the loss cannot be split "
                       "into thesis and friction")
    elif mid > MATERIAL_MID_MOVE and pnl > 0:
        primary = "THESIS_RIGHT_FRICTION_SURVIVED"
        reasons.append("the expression gained on mid AND survived the "
                       "round trip -- this is the only outcome that "
                       "proves an edge cleared its own execution cost")
    elif mid > MATERIAL_MID_MOVE and pnl <= 0:
        primary = "THESIS_RIGHT_FRICTION_KILLED"
        reasons.append(
            f"the expression gained {mid:.0f} on mid and still lost "
            f"{abs(pnl):.0f} after paying {tot} to get in and out -- "
            f"the edge was real and the spread took all of it")
    else:
        # mid fell: was the UNDERLYING wrong, or only the instrument?
        thesis_right = (ur is not None and
                        ((outcome.expression.startswith("CALL")
                          or outcome.expression == "LONG_CALL")
                         and ur > 0
                         or (outcome.expression.startswith("PUT")
                             or outcome.expression == "LONG_PUT")
                         and ur < 0))
        if thesis_right:
            primary = "THESIS_RIGHT_OPTION_LOST"
            reasons.append(
                f"the underlying moved {ur:+.2f}% in the intended "
                f"direction yet the expression lost value on mid -- the "
                f"forecast was right and the instrument was wrong")
        else:
            primary = "THESIS_WRONG"
            reasons.append("the underlying did not deliver the move; "
                           "no execution improvement would have saved "
                           "this")

    # ---------------- contributing causes (never the headline alone)
    if ivc is not None and ivc <= IV_CRUSH_DROP:
        contributing.append("IV_CRUSH")
        reasons.append(f"implied vol fell {ivc:+.3f} while we were long "
                       f"premium -- a headwind stock cannot suffer")
    if isinstance(dte_at_entry, (int, float)) and \
            dte_at_entry <= THETA_HEAVY_DTE:
        contributing.append("THETA_BURDEN")
        reasons.append(f"{dte_at_entry:.0f} DTE at entry: decay is a "
                       f"daily headwind, weighed against gamma rather "
                       f"than assumed fatal")
    if candidate is not None:
        sp = getattr(candidate, "quoted_spread_cost", None)
        deb = getattr(candidate, "debit", None)
        if sp and deb and abs(deb) > 0 and sp / abs(deb) > 0.25:
            contributing.append("BAD_ENTRY")
            reasons.append(
                f"entered across a spread worth {100 * sp / abs(deb):.0f}% "
                f"of the premium -- the round trip started underwater")
    if primary == "THESIS_RIGHT_OPTION_LOST":
        contributing.append("BAD_EXPRESSION")

    # ---------------- friction verdict
    if isinstance(share, (int, float)):
        fv = ("FRICTION_DOMINANT" if share >= 1.0 else
              "FRICTION_MATERIAL" if share >= 0.5 else
              "FRICTION_MINOR")
    else:
        fv = NOT_ESTIMABLE

    ident = outcome.friction_identity_holds
    return FrictionAttribution(
        expression=outcome.expression,
        underlying_move_pct=outcome.underlying_return_pct,
        mid_change=outcome.mid_change,
        entry_friction=entf, exit_friction=outcome.exit_friction,
        total_friction=tot, executable_pnl=outcome.pnl,
        friction_cost_share=share, r_multiple=outcome.r_multiple,
        mfe=outcome.mfe, mae=outcome.mae, iv_change=outcome.iv_change,
        dte_at_entry=(dte_at_entry if dte_at_entry is not None
                      else NOT_ESTIMABLE),
        primary_class=primary, contributing=tuple(contributing),
        friction_verdict=fv, reasoning=tuple(reasons),
        identity_holds=ident, evidence_class=evidence_class,
        notes=("diagnosis uses only post-hoc observation; none of it "
               "may flow back into a BEFORE card",))


def summarize(attributions: list) -> dict:
    """Roll up a session. The headline the operator asked for is the
    THESIS_RIGHT_FRICTION_KILLED count -- it is the number that says
    whether to work on forecasting or on execution."""
    by_class, fric_survived, fric_killed = {}, 0, 0
    mid_tot = fri_tot = net_tot = 0.0
    n_est = 0
    for a in attributions:
        by_class[a.primary_class] = by_class.get(a.primary_class, 0) + 1
        if a.primary_class == "THESIS_RIGHT_FRICTION_SURVIVED":
            fric_survived += 1
        if a.primary_class == "THESIS_RIGHT_FRICTION_KILLED":
            fric_killed += 1
        if all(isinstance(x, (int, float)) for x in
               (a.mid_change, a.total_friction, a.executable_pnl)):
            mid_tot += a.mid_change
            fri_tot += a.total_friction
            net_tot += a.executable_pnl
            n_est += 1
    right = fric_survived + fric_killed
    return {
        "kind": "options_friction_summary",
        "n": len(attributions), "n_decomposed": n_est,
        "by_primary_class": by_class,
        "mid_pnl": round(mid_tot, 2), "friction": round(fri_tot, 2),
        "executable_pnl": round(net_tot, 2),
        "right_on_mid": right,
        "friction_survived": fric_survived,
        "friction_killed": fric_killed,
        "friction_kill_rate": (round(fric_killed / right, 3)
                               if right else NOT_ESTIMABLE),
        "headline": (
            f"{fric_killed} of {right} attacks were right on mid and "
            f"lost to the round trip" if right else
            "no attack gained on mid this session"),
        "law": "if friction_kill_rate is high the repair is EXECUTION, "
               "not forecasting -- a better forecast cannot outrun a "
               "spread it must cross four times",
    }
