"""ATTACK LAB — every candidate fights the SAME worlds.

The oldest cheat in strategy research is comparing candidate A on the
worlds where A looks good against candidate B on different worlds. The
lab's one structural law closes it:

    COMMON WORLD LAW. Every attack in a comparison is evaluated across
    the identical world set, keyed by branch_id. An attack that skips a
    world fails the comparison; it does not get a flattering subset.

A candidate attack may be anything worth interrogating: the incumbent's
actual attack, a refused opportunity, a near miss, a WAIT state, a
future discovery candidate, or a synthetic research attack (NO_TRADE is
one, and it is the baseline everything must beat).

Outcome fractions are WORLD FRACTIONS, never probabilities -- the
worlds are unweighted analogs and declared stresses, not a calibrated
distribution.

Execution pedigree is carried per evaluator: an option repriced through
the commissioned BSM stack against a real underlying path is labelled
MODELLED_BSM_REPRICE, because pretending a model reprice is an observed
quote would be the friction lie the Day-1 work exists to prevent.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"

ATTACK_KINDS = ("INCUMBENT", "REFUSED", "NEAR_MISS", "WAIT",
                "DISCOVERY_CANDIDATE", "SYNTHETIC")


class AttackLabViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateAttack:
    attack_id: str
    kind: str
    expression: str
    params: dict
    evaluator_name: str
    execution_pedigree: str
    declared_1R: float | None = None

    def __post_init__(self):
        if self.kind not in ATTACK_KINDS:
            raise AttackLabViolation(f"unknown attack kind {self.kind!r}")

    def as_record(self) -> dict:
        return {"kind_": "candidate_attack", **asdict(self)}


# ---------------------------------------------------------- evaluators
# An evaluator maps (attack, world) -> outcome dict with at least
# pnl, mfe, mae. Everything downstream is derived, never invented.

def no_trade_evaluator(attack: CandidateAttack, world) -> dict:
    return {"pnl": 0.0, "mfe": 0.0, "mae": 0.0,
            "capital_deployed": 0.0, "friction": 0.0,
            "note": "flat is a position"}


def stock_evaluator(attack: CandidateAttack, world) -> dict:
    """Directional stock at declared size, held to the world's end."""
    p = attack.params
    entry = p["entry"]
    shares = p.get("shares", 100)
    sign = 1.0 if p["direction"] == "LONG" else -1.0
    prices = [px for _t, px in world.path]
    exc = [sign * (px - entry) * shares for px in prices]
    return {"pnl": round(exc[-1], 2),
            "mfe": round(max(exc), 2), "mae": round(min(exc), 2),
            "capital_deployed": round(entry * shares, 2),
            "friction": p.get("round_trip_friction", 0.0)}


def long_option_bsm_evaluator(attack: CandidateAttack, world) -> dict:
    """A long option repriced through the COMMISSIONED BSM stack along
    the world's real underlying path.

    pedigree = MODELLED_BSM_REPRICE: the underlying path is real (an
    analog's actual afternoon), the option value is modelled. Honest
    for research; never confusable with an observed quote."""
    from apex.option_analytics.bsm import BSMError, price
    p = attack.params
    entry_prem = p["entry_premium"]
    strike, opt = p["strike"], p["option_type"]
    iv = p["iv"] + p.get("iv_shift", 0.0)
    dte_y = p["dte_days"] / 365.0
    contracts = p.get("contracts", 1)
    horizon_frac = p.get("horizon_day_fraction", 0.27)  # ~0.27 trading yr day
    friction = p.get("exit_friction_per_contract", 0.0) * contracts

    vals = []
    n = len(world.path)
    for i, (_t, px) in enumerate(world.path):
        remaining = max(dte_y - (i / max(n - 1, 1)) * (horizon_frac / 252)
                        * 252 / 365, 1e-4)
        try:
            v = price(option_type=opt, spot=px, strike=strike,
                      time_to_expiry_years=remaining, rate=0.04,
                      sigma=max(iv, 0.01))
        except BSMError:
            return {"pnl": NOT_ESTIMABLE, "mfe": NOT_ESTIMABLE,
                    "mae": NOT_ESTIMABLE, "capital_deployed":
                    entry_prem * 100 * contracts, "friction": friction,
                    "note": "BSM refused; outcome withheld not guessed"}
        vals.append(v * 100 * contracts)
    cost = entry_prem * 100 * contracts
    exc = [v - cost for v in vals]
    return {"pnl": round(exc[-1] - friction, 2),
            "mfe": round(max(exc), 2), "mae": round(min(exc), 2),
            "capital_deployed": round(cost, 2), "friction": friction}


EVALUATORS = {"no_trade": no_trade_evaluator,
              "stock": stock_evaluator,
              "long_option_bsm": long_option_bsm_evaluator}


# ------------------------------------------------------------ the lab

def evaluate_common(*, attacks: list, worlds: list) -> dict:
    """Every attack across every world; identical keys or it fails."""
    if not worlds:
        raise AttackLabViolation("no worlds: nothing to fight in")
    world_ids = [w.branch_id for w in worlds]
    if len(set(world_ids)) != len(world_ids):
        raise AttackLabViolation("duplicate branch_ids poison keying")

    per_attack = {}
    for a in attacks:
        ev = EVALUATORS.get(a.evaluator_name)
        if ev is None:
            raise AttackLabViolation(
                f"{a.attack_id}: evaluator {a.evaluator_name!r} unknown")
        outcomes = {}
        for w in worlds:
            outcomes[w.branch_id] = ev(a, w)
        if set(outcomes) != set(world_ids):
            raise AttackLabViolation(
                f"{a.attack_id} skipped worlds -- a flattering subset "
                f"is not a comparison")
        per_attack[a.attack_id] = outcomes

    return {"kind": "attack_lab_run",
            "world_ids": world_ids,
            "n_worlds": len(world_ids),
            "n_empirical": sum(1 for w in worlds if w.generation_method
                               == "EMPIRICAL_HISTORICAL_ANALOG"),
            "n_adversarial": sum(1 for w in worlds if w.generation_method
                                 == "ADVERSARIAL_STRESS"),
            "outcomes": per_attack,
            "law": "every attack fought the identical world set",
            "decision_power": "NONE_RESEARCH"}


def summarize_attack(run: dict, attack: CandidateAttack,
                     empirical_only_ids: list | None = None) -> dict:
    """Distribution summary. Fractions of WORLDS, not probabilities."""
    outs = run["outcomes"][attack.attack_id]
    ids = empirical_only_ids or list(outs)
    pnls = [outs[i]["pnl"] for i in ids
            if isinstance(outs[i]["pnl"], (int, float))]
    if not pnls:
        return {"attack_id": attack.attack_id,
                "verdict": NOT_ESTIMABLE,
                "why": "no estimable outcomes"}
    r1 = attack.declared_1R
    rs = [p / r1 for p in pnls] if r1 else None
    srt = sorted(pnls)
    lo = srt[max(0, int(0.1 * len(srt)) - 0)]
    hi = srt[min(len(srt) - 1, int(0.9 * len(srt)))]
    mfes = [outs[i]["mfe"] for i in ids
            if isinstance(outs[i]["mfe"], (int, float))]
    maes = [outs[i]["mae"] for i in ids
            if isinstance(outs[i]["mae"], (int, float))]
    return {
        "attack_id": attack.attack_id,
        "execution_pedigree": attack.execution_pedigree,
        "n_worlds": len(pnls),
        "favorable_world_fraction": round(
            sum(1 for p in pnls if p > 0) / len(pnls), 4),
        "median_pnl": round(statistics.median(pnls), 2),
        "mean_pnl": round(sum(pnls) / len(pnls), 2),
        "lower_tail_p10": round(lo, 2),
        "upper_tail_p90": round(hi, 2),
        "median_R": (round(statistics.median(rs), 4) if rs
                     else NOT_ESTIMABLE),
        "median_mfe": (round(statistics.median(mfes), 2) if mfes
                       else NOT_ESTIMABLE),
        "median_mae": (round(statistics.median(maes), 2) if maes
                       else NOT_ESTIMABLE),
        "law": "world fractions are fractions of unweighted worlds, "
               "never probabilities",
    }
