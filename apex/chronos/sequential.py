"""SEQUENTIAL RESEARCH CONTROL — repeated attempts are not free.

PREDECLARED 2026-08-25, BEFORE ANY CAMPAIGN #002 OUTCOME EXISTS.
The method below was chosen and documented while Campaign #002's
results were unknown, and it is not adjustable in response to them.
Choosing a sequential framework after seeing which one flatters the
data is the exact laundering this module exists to prevent.

THE METHOD: alpha-spending by halving, judged by rank among nulls.

  family attempt k spends  alpha_k = ALPHA_TOTAL * 2^-k
  (k = 1, 2, 3, ...; the series sums to < ALPHA_TOTAL, so the
  family's LIFETIME false-discovery budget is bounded no matter how
  many times the organism returns to the same idea)

  the evidence is an empirical exceedance rank, never a pretended
  precise p-value:
      p_hat = (1 + #nulls >= real_score) / (n_nulls + 1)
  discovery requires p_hat <= alpha_k.

  TAIL RESOLUTION IS A PRECONDITION, not a footnote: the smallest
  p_hat that n nulls can express is 1/(n+1). If 1/(n+1) > alpha_k,
  the null sample CANNOT resolve the tail this attempt requires, and
  the verdict is NULL_TAIL_UNRESOLVED -- no discovery, however large
  the real score. Refusal, not fake precision. The remedy is a larger
  null budget, decided BEFORE scoring, never after.

Later attempts therefore need both a stronger result AND a richer
null sample -- exactly the shape of "every repeated attempt consumes
evidentiary credibility."

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

from apex.chronos.clock import ChronosViolation

ALPHA_TOTAL = 0.05
PREDECLARED = "2026-08-25 before any Campaign #002 outcome existed"

# adaptive null budget (§8): base well above the V0 minimum of 20;
# escalation decided by attempt number BEFORE scoring
NULL_BUDGET_BASE = 100
NULL_BUDGET_ESCALATED = 320
ESCALATE_FROM_ATTEMPT = 3


def alpha_for_attempt(attempt: int) -> float:
    if attempt < 1:
        raise ChronosViolation("attempts are numbered from 1")
    return ALPHA_TOTAL * (0.5 ** attempt)


def null_budget_for_attempt(attempt: int) -> int:
    """The null budget is a function of the attempt number alone --
    fixed before any score exists, so the budget can never be raised
    to rescue a particular candidate."""
    return (NULL_BUDGET_ESCALATED if attempt >= ESCALATE_FROM_ATTEMPT
            else NULL_BUDGET_BASE)


def sequential_test(*, family: str, attempt: int, real_score: float,
                    null_scores: list) -> dict:
    """One family attempt against its spent alpha.

    Returns DISCOVERY / NOT_DISCOVERED / NULL_TAIL_UNRESOLVED, with
    the rank arithmetic shown -- the number must be checkable by
    hand from the record."""
    if not null_scores:
        raise ChronosViolation("no nulls: nothing to rank against")
    alpha_k = alpha_for_attempt(attempt)
    n = len(null_scores)
    floor = 1.0 / (n + 1)
    if floor > alpha_k:
        return {"kind": "sequential_test", "family": family,
                "attempt": attempt, "alpha_k": round(alpha_k, 6),
                "null_n": n,
                "min_expressible_p": round(floor, 6),
                "verdict": "NULL_TAIL_UNRESOLVED",
                "why": f"{n} nulls can express at best p_hat="
                       f"{floor:.4f}, but attempt {attempt} requires "
                       f"p_hat<={alpha_k:.4f}. The tail this attempt "
                       f"needs cannot be resolved -- no discovery, "
                       f"however large the real score. Refusal, not "
                       f"fake precision",
                "decision_power": "NONE_RESEARCH"}
    exceed = sum(1 for s in null_scores if s >= real_score)
    p_hat = (1 + exceed) / (n + 1)
    verdict = "DISCOVERY" if p_hat <= alpha_k else "NOT_DISCOVERED"
    return {"kind": "sequential_test", "family": family,
            "attempt": attempt, "alpha_k": round(alpha_k, 6),
            "null_n": n, "real_score": round(real_score, 6),
            "null_exceedance_rank": exceed,
            "p_hat": round(p_hat, 6),
            "real_rank_among_nulls": n - exceed,
            "null_tail_resolution": round(floor, 6),
            "verdict": verdict,
            "lifetime_budget_note": (
                f"family {family} has spent "
                f"{sum(alpha_for_attempt(i) for i in range(1, attempt + 1)):.4f} "
                f"of its {ALPHA_TOTAL} lifetime alpha; the series is "
                f"bounded, so unlimited fresh chances do not exist"),
            "predeclared": PREDECLARED,
            "decision_power": "NONE_RESEARCH"}
