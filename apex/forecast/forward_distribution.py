"""ForwardDistribution -- the empirical forecast object.

Shape per the operator's 2026-08-20 specification: direction
probabilities, expected return / MAE / MFE, quantiles q05..q95, horizon,
and the full evidence pedigree (support_n, sessions, regimes, OOD,
calibration_status, uncertainty). Built from the known_from-filtered
outcome corpus and NOTHING else.

GATES (all pre-registered, none fitted):
  * support gate: the Observatory's own probability-gate thresholds
    (prospective_n>=30, sessions>=10, subjects>=5, regimes>=2) --
    imported, not duplicated, so the two layers can never drift apart
  * corpus floor: MIN_CORPUS_N resolved outcomes at THIS horizon
  * calibration: numbers may exist UNCALIBRATED (clearly labeled) once
    the support+corpus gates pass; the CALIBRATED status additionally
    requires a demonstrated out-of-sample Brier skill vs base rate
    (probability.brier), which cannot exist before enough
    prediction/outcome pairs accumulate

Capital's contract: only a CALIBRATED forecast may ever reach a
ForecastSlot with a status other than NOT_YET_AVAILABLE. An
ESTIMABLE_UNCALIBRATED forecast is research output -- visible in
ledgers, never an authorization input.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from apex.forecast import (
    FORECAST_CALIBRATED, FORECAST_ESTIMABLE_UNCALIBRATED,
    FORECAST_NOT_ESTIMABLE, FORECAST_POWER,
)
from apex.pattern_observatory.pattern_state import (
    MIN_DISTINCT_REGIMES, MIN_DISTINCT_SESSIONS, MIN_DISTINCT_SYMBOLS,
    MIN_PROSPECTIVE_N,
)

MIN_CORPUS_N = 30


class ForecastError(RuntimeError):
    pass


@dataclass(frozen=True)
class ForwardDistribution:
    family_id: str
    subject: str
    horizon_minutes: int
    status: str                        # FORECAST_* constants

    p_up: float | None
    p_down: float | None
    expected_return: float | None
    expected_adverse_excursion: float | None
    expected_favorable_excursion: float | None
    q05: float | None
    q25: float | None
    q50: float | None
    q75: float | None
    q95: float | None

    support_n: int
    distinct_sessions: int
    distinct_regimes: int
    distinct_subjects: int
    corpus_n: int
    n_raw: int = 0
    n_effective_lower_bound: int = 0
    clustering: dict = field(default_factory=dict)
    ood: str = "NOT_ESTIMABLE"
    calibration_status: str = "UNCALIBRATED"
    uncertainty: str = "MAXIMUM"
    blockers: tuple = ()
    as_of: str = ""
    known_from: str = ""
    decision_power: str = FORECAST_POWER

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "forward_distribution"
        d["blockers"] = list(self.blockers)
        d["is_authorization_input"] = self.status == FORECAST_CALIBRATED
        return d


def build(*, family_id: str, subject: str, horizon_minutes: int,
          corpus: dict, support: dict, ood: str = "NOT_ESTIMABLE",
          calibration: dict | None = None, as_of, known_from
          ) -> ForwardDistribution:
    """`corpus`: resolution.outcome_corpus() output for this family+
    horizon. `support`: support.aggregate() output. `calibration`:
    probability.brier() output when prediction/outcome pairs exist.

    Refuses in every direction it can; when it does emit numbers they
    are pure empirical statistics of the corpus, no model, no fit."""
    import statistics

    blockers = []
    if support.get("prospective_n", 0) < MIN_PROSPECTIVE_N:
        blockers.append(f"prospective_n {support.get('prospective_n', 0)}"
                        f"/{MIN_PROSPECTIVE_N}")
    if support.get("distinct_sessions", 0) < MIN_DISTINCT_SESSIONS:
        blockers.append(f"distinct_sessions "
                        f"{support.get('distinct_sessions', 0)}"
                        f"/{MIN_DISTINCT_SESSIONS}")
    if support.get("distinct_symbols", 0) < MIN_DISTINCT_SYMBOLS:
        blockers.append(f"distinct_subjects "
                        f"{support.get('distinct_symbols', 0)}"
                        f"/{MIN_DISTINCT_SYMBOLS}")
    if support.get("distinct_regimes", 0) < MIN_DISTINCT_REGIMES:
        blockers.append(f"distinct_regimes "
                        f"{support.get('distinct_regimes', 0)}"
                        f"/{MIN_DISTINCT_REGIMES}")
    rets = corpus.get("returns") or []
    if len(rets) < MIN_CORPUS_N:
        blockers.append(f"corpus_n {len(rets)}/{MIN_CORPUS_N}")
    if ood == "OOD":
        blockers.append("current state is out of distribution")

    cal_status = "UNCALIBRATED"
    if calibration and calibration.get("status") == "COMPUTED":
        cal_status = ("CALIBRATED" if calibration.get("beats_base_rate")
                      else "UNCALIBRATED")

    def _empty(status):
        return ForwardDistribution(
            family_id=family_id, subject=subject,
            horizon_minutes=horizon_minutes, status=status,
            p_up=None, p_down=None, expected_return=None,
            expected_adverse_excursion=None,
            expected_favorable_excursion=None,
            q05=None, q25=None, q50=None, q75=None, q95=None,
            support_n=support.get("prospective_n", 0),
            distinct_sessions=support.get("distinct_sessions", 0),
            distinct_regimes=support.get("distinct_regimes", 0),
            distinct_subjects=support.get("distinct_symbols", 0),
            corpus_n=len(rets),
            n_raw=corpus.get("n_raw", len(rets)),
            n_effective_lower_bound=corpus.get(
                "n_effective_lower_bound", 0),
            clustering=dict(corpus.get("clustering", {})),
            ood=ood, calibration_status=cal_status,
            uncertainty="MAXIMUM", blockers=tuple(blockers),
            as_of=str(as_of), known_from=str(known_from))

    if blockers:
        return _empty(FORECAST_NOT_ESTIMABLE)

    # gates passed: pure empirical statistics of the earned corpus
    srt = sorted(rets)
    n = len(srt)

    def q(p):
        return srt[min(n - 1, max(0, int(p * n)))]

    mfe = corpus.get("mfe") or []
    mae = corpus.get("mae") or []
    ups = sum(1 for r in rets if r > 0)
    status = (FORECAST_CALIBRATED if cal_status == "CALIBRATED"
              else FORECAST_ESTIMABLE_UNCALIBRATED)
    return ForwardDistribution(
        family_id=family_id, subject=subject,
        horizon_minutes=horizon_minutes, status=status,
        p_up=round(ups / n, 4), p_down=round((n - ups) / n, 4),
        expected_return=round(statistics.fmean(rets), 6),
        expected_adverse_excursion=(round(statistics.fmean(mae), 6)
                                    if mae else None),
        expected_favorable_excursion=(round(statistics.fmean(mfe), 6)
                                      if mfe else None),
        q05=round(q(0.05), 6), q25=round(q(0.25), 6),
        q50=round(q(0.50), 6), q75=round(q(0.75), 6),
        q95=round(q(0.95), 6),
        support_n=support.get("prospective_n", 0),
        distinct_sessions=support.get("distinct_sessions", 0),
        distinct_regimes=support.get("distinct_regimes", 0),
        distinct_subjects=support.get("distinct_symbols", 0),
        corpus_n=n,
        n_raw=corpus.get("n_raw", n),
        n_effective_lower_bound=corpus.get("n_effective_lower_bound", 0),
        clustering=dict(corpus.get("clustering", {})),
        ood=ood, calibration_status=cal_status,
        uncertainty=("HIGH" if status == FORECAST_ESTIMABLE_UNCALIBRATED
                     else "MODERATE"),
        blockers=(), as_of=str(as_of), known_from=str(known_from))
