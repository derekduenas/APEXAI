"""InternalModelMarket — F7: independent intelligence engines submit a
stance on a defined proposition, with prospective scorekeeping.

THE LAW: no engine's SUPPORT/OPPOSE stance is ever combined into a
weighted consensus (that would be exactly the "optimize engine weights"
the directive forbids). `snapshot()` reports plain vote TALLIES --
arithmetic counting, not a fitted or learned combination -- and past
`Scorecard` accuracy is a diagnostic dead end: nothing in this module
reads a scorecard back INTO a submission's weight or a proposition's
resolution. Every scorecard starts at zero (F16's "0 valid prospective
observations at birth" applies here identically) and the counting
machinery is proven correct with synthetic resolution sequences,
because real ones do not exist yet.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/model_market_ledger.jsonl")

SEATS = ("CURVE", "MOMENTUM", "REVERSION", "RELATIVE_STRENGTH", "ANALOG",
        "EXPECTATION_VIOLATION", "PARTICIPANT_PRESSURE", "PROPAGATION",
        "VISUAL", "EVENT", "MICROSTRUCTURE", "WORLD_LAB", "ASSASSIN")

STANCES = ("SUPPORT", "OPPOSE", "ABSTAIN", "UNKNOWN")

# no-position stances -- distinct semantics (ABSTAIN = assessed and
# declined; UNKNOWN = could not even assess) but both count identically
# toward the scorecard's `abstentions` field, per the directive's fixed
# field list (no separate counter was specified for UNKNOWN).
NO_POSITION_STANCES = ("ABSTAIN", "UNKNOWN")

MIN_RESOLVED_FOR_DRIFT = 20


class ModelMarketError(RuntimeError):
    pass


@dataclass(frozen=True)
class Submission:
    engine: str
    proposition: str
    stance: str
    reason: str
    support: tuple
    quality: str
    coverage: str
    birth: str | None
    known_from: str
    as_of: str
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        if self.engine not in SEATS:
            raise ModelMarketError(f"unknown seat {self.engine!r}")
        if self.stance not in STANCES:
            raise ModelMarketError(f"unknown stance {self.stance!r}")

    def as_record(self) -> dict:
        return {"kind": "model_market_submission", **asdict(self)}


@dataclass(frozen=True)
class Scorecard:
    engine: str
    proposition_class: str
    attempts: int = 0
    resolved: int = 0
    correct: int = 0
    incorrect: int = 0
    abstentions: int = 0
    abstention_quality: str = "UNKNOWN"
    false_positive: int = 0
    false_negative: int = 0
    regime: str = "UNSPECIFIED"
    sample_size: int = 0
    drift: str | None = None
    known_from: str | None = None
    as_of: str | None = None
    decision_power: str = FRONTIER2_POWER

    def as_record(self) -> dict:
        return {"kind": "model_market_scorecard", **asdict(self)}


def submit(engine: str, proposition: str, stance: str, *, reason: str,
          known_from, now, support: tuple = (), quality: str = "UNKNOWN",
          coverage: str = "UNKNOWN", birth: str | None = None) -> Submission:
    import pandas as pd
    now = pd.Timestamp(now)
    return Submission(engine=engine, proposition=proposition, stance=stance,
                      reason=reason, support=tuple(support), quality=quality,
                      coverage=coverage, birth=birth,
                      known_from=str(pd.Timestamp(known_from)), as_of=str(now))


def snapshot(proposition: str, submissions: tuple) -> dict:
    """A plain vote TALLY -- never a weighted consensus. `submissions`
    must all share the same `proposition` (checked, not assumed)."""
    bad = [s.proposition for s in submissions if s.proposition != proposition]
    if bad:
        raise ModelMarketError(
            f"submission(s) for a different proposition mixed in: {bad}")
    tally = {st: 0 for st in STANCES}
    by_engine = {}
    for s in submissions:
        tally[s.stance] += 1
        by_engine[s.engine] = s.stance
    return {"kind": "model_market_snapshot", "proposition": proposition,
           "n_submissions": len(submissions), "tally": tally,
           "by_engine": by_engine, "seats_heard_from": sorted(by_engine),
           "seats_silent": sorted(set(SEATS) - set(by_engine)),
           "decision_power": FRONTIER2_POWER}


def update_scorecard(prior: Scorecard, submission: Submission,
                     outcome: bool | None, *, now) -> Scorecard:
    """Pure counting arithmetic -- `outcome`: True/False if the
    proposition has resolved, None if still open (in which case only
    `attempts` and possibly `abstentions` move)."""
    import pandas as pd
    if submission.engine != prior.engine:
        raise ModelMarketError("submission engine does not match scorecard")
    now = pd.Timestamp(now)

    attempts = prior.attempts + 1
    resolved, correct, incorrect = prior.resolved, prior.correct, prior.incorrect
    abstentions = prior.abstentions
    fp, fn = prior.false_positive, prior.false_negative

    if submission.stance in NO_POSITION_STANCES:
        abstentions += 1
    elif outcome is not None:
        resolved += 1
        took_support = submission.stance == "SUPPORT"
        hit = took_support == outcome
        if hit:
            correct += 1
        else:
            incorrect += 1
            if took_support and not outcome:
                fp += 1
            elif not took_support and outcome:
                fn += 1

    sample_size = prior.sample_size + 1
    drift = prior.drift
    if resolved >= MIN_RESOLVED_FOR_DRIFT:
        # DIAGNOSTIC ONLY: compares the most recent MIN_RESOLVED_FOR_DRIFT
        # accuracy against the all-time accuracy; never fed back into a
        # weight anywhere in this module.
        drift = "MEASURABLE_NOT_YET_COMPUTED_HERE"

    return Scorecard(engine=prior.engine, proposition_class=prior.proposition_class,
                     attempts=attempts, resolved=resolved, correct=correct,
                     incorrect=incorrect, abstentions=abstentions,
                     abstention_quality=prior.abstention_quality,
                     false_positive=fp, false_negative=fn, regime=prior.regime,
                     sample_size=sample_size, drift=drift,
                     known_from=str(now), as_of=str(now))


def new_scorecard(engine: str, proposition_class: str, *, regime="UNSPECIFIED"
                  ) -> Scorecard:
    if engine not in SEATS:
        raise ModelMarketError(f"unknown seat {engine!r}")
    return Scorecard(engine=engine, proposition_class=proposition_class,
                     regime=regime)


def persist_submission(s: Submission) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, s.as_record())
