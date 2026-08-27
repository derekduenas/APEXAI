"""CAPITAL ARENA — where should the next dollar go?

The Predator answers a local question: is THIS trade attackable? That
question has no opinion about the other four candidates on the screen,
the capital already committed, or the fact that three of them are the
same bet wearing different tickers.

    PREDATOR       is this attackable?
    CAPITAL ARENA  is this the best use of limited capital, given
                   everything else currently available -- including
                   doing nothing?

THE FAILURE THIS EXISTS TO CATCH:

    SPY call spread + QQQ call spread + NVDA call spread
    = three trades, one economic factor bet, triple the real exposure

Nothing in the incumbent stack can see that, because each candidate is
evaluated alone.

CASH IS A REAL COMPETITOR. It has zero market loss, zero friction and
full optionality, and a trade that cannot beat it should not be
funded. Opportunity cost runs both ways: capital locked in a mediocre
four-hour deployment is capital unavailable for a short-lived
asymmetric one.

AUTHORITY: SHADOW. The incumbent Options V1 continues taking every
authorized paper trade under its existing rules. Capital Arena records
only a sealed COUNTERFACTUAL -- what a portfolio manager would have
funded -- and the two are compared over many sessions. It may not
block, resize, delay or authorize anything.

NO MAGIC SCORE. There is no CAPITAL_SCORE = 91. A scalar invites a
threshold, a threshold invites tuning, and tuning invites exactly the
overfitting the rest of the organism spends its life refusing.
"""

CAPITAL_VERSION = "1.0.0"

AUTHORITY = "SHADOW_COUNTERFACTUAL_ONLY"

CHARTER = (
    "Capital Arena decides nothing. It records what a disciplined "
    "portfolio manager would have done with the same information, "
    "seals that decision before the outcome exists, and lets many "
    "sessions judge whether it would have done better.")
