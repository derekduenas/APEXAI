"""Track 5: exploration/ML governance (v4.0 section 3; North Star aligned).

WHERE THIS SITS in the machine:

    WORLD STATE (apex/world: online labels, vintages, uncertainty)
         |
    DISCOVERY (apex/research: dossiers, novelty, contamination)
         |
    HYPOTHESIS (screened, registered -- or exploration candidates, here)
         |
    EXPLORATION / ML  <-- THIS PACKAGE: purged CV, embargo, trial
         |                accounting, deflated Sharpe, PBO. An EVALUATOR,
         |                never an optimizer: no select_best exists.
         |
    CONDITIONAL FORECAST -> DISTRIBUTION (MISSING LAYER, named in the
         |                  MVPM reconciliation: nothing yet turns signal +
         |                  state into the pmf the expression engine eats)
         |
    EXPRESSION (apex/expression) -> PORTFOLIO (apex/portfolio) -> RISK
         |
    COST / CAPACITY -> OPPORTUNITY EVALUATION -> RANKING
         |
    NO-TRADE / PAPER (live) / CONFIRMATION (credits, frozen)

THE HARD RULE: ML output is a hypothesis, never a signal. Every candidate
carries its full trial denominator, its purged-CV and walk-forward results,
its deflated Sharpe and PBO, its correlation to existing validated signals,
and evidence_class='exploration_candidate'. Exploration reads IN-SAMPLE
ONLY: the window guard refuses validation and holdout dates structurally.
A regime-conditioned model, a new expression, a changed mechanism -- each is
a NEW hypothesis for the registration machinery.
"""
