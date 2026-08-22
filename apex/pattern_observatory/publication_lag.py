"""PUBLICATION-LAG INTEGRITY LAW -- when was it TRUE vs when could we KNOW.

THE FAILURE THIS PREVENTS, stated concretely. CFTC Traders in Financial
Futures measures positions as of TUESDAY and publishes them on FRIDAY at
15:30 ET. If a sequence study stamps the Tuesday report date as
`known_from`, APEX gets to "observe" institutional positioning three days
before any human could have. Every downstream lead-time measurement,
every conjunction ordering, every outcome attribution built on top of
that is then silently wrong -- and wrong in the flattering direction,
because the system appears to have seen things early.

This is not a hypothetical. The NQ leveraged-fund extreme measured
tonight (net -96,727, 1.6th percentile, z -2.27) carries a report date of
2026-08-11 and a publication time of 2026-08-14 15:30 ET. Those are three
days apart. Using the wrong one is the difference between research and
self-deception.

THE LAW, in two lines:

    event_time  = when the observation was TRUE   (report / as-of date)
    known_from  = when APEX could actually have OBTAINED it (publication)

    known_from >= event_time,  ALWAYS, for every lagged source.

`visible_at(as_of)` is the only sanctioned way to ask whether a fact may
be used at a point in time. Historical replay that bypasses it can see
the future.

SOURCE STATES are separated from FAILURES, because expected publication
latency is not an error and must never reach an error ledger:

    NOT_YET_PUBLISHED     expected -- today's file does not exist yet
    STALE_WITHIN_POLICY   acceptable -- older than ideal, inside the
                          source's own declared cadence
    STALE_BEYOND_POLICY   degraded -- the source has missed its cadence
    FETCH_FAILED          an actual failure
    PARSE_FAILED          an actual failure
    SOURCE_UNAVAILABLE    an actual failure

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass

from apex.pattern_observatory import OBSERVATORY_POWER

NOT_YET_PUBLISHED = "NOT_YET_PUBLISHED"
STALE_WITHIN_POLICY = "STALE_WITHIN_POLICY"
STALE_BEYOND_POLICY = "STALE_BEYOND_POLICY"
FETCH_FAILED = "FETCH_FAILED"
PARSE_FAILED = "PARSE_FAILED"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
PUBLISHED = "PUBLISHED"

SOURCE_STATES = (PUBLISHED, NOT_YET_PUBLISHED, STALE_WITHIN_POLICY,
                 STALE_BEYOND_POLICY, FETCH_FAILED, PARSE_FAILED,
                 SOURCE_UNAVAILABLE)

# States that are EXPECTED and must never be written to an error ledger.
EXPECTED_STATES = (PUBLISHED, NOT_YET_PUBLISHED, STALE_WITHIN_POLICY)
FAILURE_STATES = (FETCH_FAILED, PARSE_FAILED, SOURCE_UNAVAILABLE)
DEGRADED_STATES = (STALE_BEYOND_POLICY,)


class PublicationLagViolation(RuntimeError):
    """Raised when a fact claims to have been knowable before it existed."""


@dataclass(frozen=True)
class PublicationPolicy:
    """How a source publishes. DECLARED from the publisher's own stated
    schedule; where a schedule is approximate the policy is deliberately
    CONSERVATIVE -- assuming later availability can only ever make APEX
    look worse, never better."""

    source: str
    cadence: str
    lag_description: str
    max_expected_staleness_days: float
    publication_time_et: str | None = None
    conservative: bool = True

    def as_dict(self) -> dict:
        return {"kind": "publication_policy", **self.__dict__,
                "decision_power": OBSERVATORY_POWER}


POLICIES = {
    "CFTC_TFF": PublicationPolicy(
        source="CFTC_TFF", cadence="weekly",
        lag_description="positions as of Tuesday close, released the "
                        "following Friday 15:30 ET",
        max_expected_staleness_days=11.0,      # Tue data still current the
                                               # following Wed before release
        publication_time_et="15:30"),
    "FINRA_SHORT_VOLUME": PublicationPolicy(
        source="FINRA_SHORT_VOLUME", cadence="daily",
        lag_description="daily off-exchange file for session D becomes "
                        "available after the close of D; CONSERVATIVELY "
                        "treated as available from 20:00 ET on D",
        max_expected_staleness_days=4.0,       # covers a long weekend
        publication_time_et="20:00"),
    "FORM_13F": PublicationPolicy(
        source="FORM_13F", cadence="quarterly",
        lag_description="holdings as of quarter end, filed up to 45 days "
                        "later",
        max_expected_staleness_days=135.0),
    "INSIDER_FORM4": PublicationPolicy(
        source="INSIDER_FORM4", cadence="event",
        lag_description="transaction reported within 2 business days",
        max_expected_staleness_days=5.0),
    "SHORT_INTEREST": PublicationPolicy(
        source="SHORT_INTEREST", cadence="bi-monthly",
        lag_description="settlement-date positions published ~8 business "
                        "days later",
        max_expected_staleness_days=25.0),
    "ETF_FLOWS": PublicationPolicy(
        source="ETF_FLOWS", cadence="daily",
        lag_description="prior-session flows published next morning",
        max_expected_staleness_days=4.0),
    "MACRO_RELEASE": PublicationPolicy(
        source="MACRO_RELEASE", cadence="event",
        lag_description="reference period precedes release, often by weeks",
        max_expected_staleness_days=60.0),
}


def _et(ts):
    import pandas as pd
    t = pd.Timestamp(ts)
    if t.tz is None:
        t = t.tz_localize("America/New_York")
    return t.tz_convert("America/New_York")


def publication_time(source: str, event_date) -> "object":
    """When the observation for `event_date` actually became public.

    For CFTC this is the Friday after the Tuesday report; for a daily
    source it is the declared hour on the session date itself.
    """
    import pandas as pd
    pol = POLICIES.get(source)
    if pol is None:
        raise PublicationLagViolation(
            f"{source!r} has no declared publication policy -- a lagged "
            "source without a policy cannot have an honest known_from")
    d = _et(pd.Timestamp(event_date).normalize())
    hh, mm = (pol.publication_time_et or "23:59").split(":")
    if source == "CFTC_TFF":
        # Tuesday report -> Friday release. weekday(): Mon=0 ... Fri=4
        days_ahead = (4 - d.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7          # a Friday report date releases next Fri
        d = d + pd.Timedelta(days=days_ahead)
    return d.replace(hour=int(hh), minute=int(mm))


@dataclass(frozen=True)
class LaggedObservation:
    """A fact that was TRUE at one time and KNOWABLE at another.

    Construction enforces the law: known_from may never precede
    event_time. There is no flag to disable the check, because the only
    reason to disable it would be to permit lookahead.
    """

    source: str
    subject: str
    event_time: str
    known_from: str
    value: object
    source_state: str
    staleness_days: float | None
    policy: dict

    def __post_init__(self):
        import pandas as pd
        if self.source_state not in SOURCE_STATES:
            raise PublicationLagViolation(
                f"unknown source_state {self.source_state!r}")
        e, k = pd.Timestamp(self.event_time), pd.Timestamp(self.known_from)
        if e.tz is None:
            e = e.tz_localize("UTC")
        if k.tz is None:
            k = k.tz_localize("UTC")
        if k < e:
            raise PublicationLagViolation(
                f"{self.source}/{self.subject}: known_from {k} PRECEDES "
                f"event_time {e}. APEX cannot have known a thing before it "
                f"was true -- this is publication lookahead.")

    def visible_at(self, as_of) -> bool:
        """The ONLY sanctioned way to ask whether this fact may be used."""
        import pandas as pd
        a, k = pd.Timestamp(as_of), pd.Timestamp(self.known_from)
        if a.tz is None:
            a = a.tz_localize("UTC")
        if k.tz is None:
            k = k.tz_localize("UTC")
        return a >= k

    def as_dict(self) -> dict:
        return {"kind": "lagged_observation", **self.__dict__,
                "policy": dict(self.policy),
                "law": "event_time = when it was TRUE; known_from = when "
                       "APEX could have OBTAINED it",
                "decision_power": OBSERVATORY_POWER}


def classify_source_state(source: str, *, latest_event_date, as_of,
                          requested_date=None) -> dict:
    """Publication state WITHOUT calling anything an error.

    `requested_date` is the session APEX wanted. If that session's file
    has not published yet, the answer is NOT_YET_PUBLISHED -- expected,
    not a failure -- and the caller should use the latest legitimately
    published observation instead.
    """
    import pandas as pd
    pol = POLICIES.get(source)
    if pol is None:
        return {"source_state": SOURCE_UNAVAILABLE,
                "reason": f"no declared policy for {source!r}",
                "is_expected": False}

    a = _et(as_of)
    if requested_date is not None:
        pub = publication_time(source, requested_date)
        if a < pub:
            return {
                "kind": "source_state", "source": source,
                "source_state": NOT_YET_PUBLISHED, "is_expected": True,
                "requested_market_date": str(pd.Timestamp(requested_date).date()),
                "publishes_at": str(pub),
                "last_available_market_date": (
                    str(pd.Timestamp(latest_event_date).date())
                    if latest_event_date is not None else None),
                "reason": f"{source} for that session publishes at {pub}; "
                          f"it is {a}. Use the latest published file.",
                "policy": pol.as_dict(),
                "decision_power": OBSERVATORY_POWER}

    if latest_event_date is None:
        return {"kind": "source_state", "source": source,
                "source_state": SOURCE_UNAVAILABLE, "is_expected": False,
                "reason": "no observation of any date is held",
                "policy": pol.as_dict()}

    stale_days = (a.normalize()
                  - _et(pd.Timestamp(latest_event_date).normalize())).days
    state = (STALE_WITHIN_POLICY
             if stale_days <= pol.max_expected_staleness_days
             else STALE_BEYOND_POLICY)
    if stale_days <= 0:
        state = PUBLISHED
    return {"kind": "source_state", "source": source, "source_state": state,
            "is_expected": state in EXPECTED_STATES,
            "last_available_market_date": str(
                pd.Timestamp(latest_event_date).date()),
            "current_session_market_date": str(a.date()),
            "staleness_days": float(stale_days),
            "max_expected_staleness_days": pol.max_expected_staleness_days,
            "policy": pol.as_dict(),
            "decision_power": OBSERVATORY_POWER}


def is_error(source_state: str) -> bool:
    """The predicate that keeps expected latency out of the error ledger."""
    return source_state in FAILURE_STATES
