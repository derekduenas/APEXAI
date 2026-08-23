"""OPTIONS CAUSAL HISTORICAL REPLAY -- combat rehearsal, not evidence.

The Options Predator can fight thousands of historical moments at
machine speed on a Sunday. What it CANNOT do is call the results
prospective evidence:

    HISTORICAL_DEVELOPMENT_REPLAY  the system is being DEVELOPED using
                                   this data; research feedback and
                                   overfitting are live risks even with
                                   perfect causality
    PROSPECTIVE                    the future literally did not exist
                                   when the decision was sealed

Every record this module emits carries evidence_class=
HISTORICAL_DEVELOPMENT_REPLAY. Nothing here may ever be counted in a
prospective cohort, and no threshold may be fitted against its
outcomes.

THE TEMPORAL FIREWALL (structural, not a promise):
`ReplayWorld.at(T)` returns a frozen view exposing ONLY rows with
timestamp <= T. The future is not filtered at read time -- it is not
in the object. `reveal_after(T)` is a SEPARATE call that the harness
refuses until a BEFORE card has been sealed for that decision.

SAMPLE-INDEPENDENCE LAW: a scanner that fires every minute for 90
minutes has not produced 90 trades. Every replay batch reports
n_raw, n_effective_lower_bound (distinct symbol-sessions),
unique_sessions, setup families, regimes and symbols. Overlapping
observations are never counted as independent evidence.

decision_power: NONE_REPLAY -- rehearsal only. Authority OBSERVE.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

EVIDENCE_CLASS = "HISTORICAL_DEVELOPMENT_REPLAY"
REPLAY_POWER = "NONE_REPLAY"

# fills use quoted sides only -- never a midpoint that never traded
LONG_LEG_FILL = "ASK"
SHORT_LEG_FILL = "BID"


class ReplayViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class FrozenState:
    """What the Predator may see at instant T. Constructed by slicing;
    the future is absent from the object, not merely hidden."""
    symbol: str
    session: str
    T: str
    underlying_bars: tuple          # bars with label+1min <= T
    option_quotes: tuple            # quote rows with timestamp <= T
    oi_rows: tuple                  # OI rows with known_from <= T
    spot_ref: float | None
    spot_ref_source_label: str | None
    spot_ref_age_s: float | None

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(
            {"symbol": self.symbol, "T": self.T,
             "n_bars": len(self.underlying_bars),
             "n_quotes": len(self.option_quotes),
             "spot": self.spot_ref}, sort_keys=True).encode()).hexdigest()


@dataclass
class ReplayWorld:
    """One symbol-session loaded from the validated history store."""
    symbol: str
    session: str
    _bars: list = field(default_factory=list)
    _quotes: list = field(default_factory=list)
    _oi: list = field(default_factory=list)

    @classmethod
    def load(cls, root: Path, symbol: str, session: str) -> "ReplayWorld":
        import pandas as pd
        d8 = session.replace("-", "")
        base = Path(root) / symbol
        w = cls(symbol=symbol, session=session)
        up = base / f"underlying_{d8}.json.gz"
        if up.exists():
            w._bars = json.loads(gzip.open(up).read())["bars"]
        qp = base / f"quotes_{d8}.csv.gz"
        if qp.exists():
            with gzip.open(qp, "rt") as fh:
                w._quotes = [r for r in csv.DictReader(fh)
                             # ELIGIBILITY LAW: only causally-priced
                             # rows may teach the Predator anything
                             if r.get("moneyness_status") == "CAUSAL"]
        op = base / f"oi_{d8}.csv.gz"
        if op.exists():
            with gzip.open(op, "rt") as fh:
                w._oi = list(csv.DictReader(fh))
        w._bars.sort(key=lambda b: b["t"])
        w._quotes.sort(key=lambda r: r["timestamp"])
        return w

    def instants(self) -> list:
        """Distinct option-quote instants -- the only moments at which
        an options state legitimately exists."""
        return sorted({r["timestamp"] for r in self._quotes})

    def at(self, T: str) -> FrozenState:
        """THE TEMPORAL FIREWALL. Everything after T is excluded from
        the returned object entirely."""
        import pandas as pd
        Tt = pd.Timestamp(T)
        bars, ref, ref_lbl, ref_age = [], None, None, None
        for b in self._bars:
            lbl = pd.Timestamp(b["t"]).tz_convert("America/New_York") \
                .tz_localize(None)
            # START_OF_BAR: knowable only at label + 1 minute
            if lbl + pd.Timedelta(minutes=1) <= Tt:
                bars.append(b)
                ref, ref_lbl = b["c"], str(lbl)
                ref_age = (Tt - (lbl + pd.Timedelta(minutes=1))
                           ).total_seconds()
        quotes = [r for r in self._quotes
                  if pd.Timestamp(r["timestamp"]) <= Tt]
        oi = [r for r in self._oi
              if pd.Timestamp(r["timestamp"]).tz_localize(None) <= Tt]
        return FrozenState(
            symbol=self.symbol, session=self.session, T=str(T),
            underlying_bars=tuple(bars), option_quotes=tuple(quotes),
            oi_rows=tuple(oi), spot_ref=ref,
            spot_ref_source_label=ref_lbl, spot_ref_age_s=ref_age)

    def reveal_after(self, T: str, sealed_card_hash: str) -> tuple:
        """The future -- available ONLY against a sealed BEFORE card."""
        import pandas as pd
        if not sealed_card_hash or len(sealed_card_hash) < 32:
            raise ReplayViolation(
                "reveal_after requires a sealed BEFORE card hash -- the "
                "future may not be read before the decision is sealed")
        Tt = pd.Timestamp(T)
        fq = tuple(r for r in self._quotes
                   if pd.Timestamp(r["timestamp"]) > Tt)
        fb = tuple(b for b in self._bars
                   if pd.Timestamp(b["t"]).tz_convert("America/New_York")
                   .tz_localize(None) > Tt)
        return fq, fb


def seal_before_card(decision: dict) -> dict:
    """Hash-seal a replay decision BEFORE any future is revealed."""
    body = {**decision, "evidence_class": EVIDENCE_CLASS,
            "decision_power": REPLAY_POWER,
            "live_promotion_eligible": False,
            "law": "HISTORICAL_DEVELOPMENT_REPLAY -- never prospective "
                   "evidence; no threshold may be fitted to its outcomes"}
    body["card_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body


def sample_accounting(records: list) -> dict:
    """SAMPLE-INDEPENDENCE LAW: overlapping observations are never
    independent evidence."""
    sessions = {(r.get("symbol"), r.get("session")) for r in records}
    return {"n_raw": len(records),
            "n_effective_lower_bound": len(sessions),
            "unique_symbol_sessions": len(sessions),
            "unique_symbols": len({r.get("symbol") for r in records}),
            "unique_sessions": len({r.get("session") for r in records}),
            "setup_families": sorted(
                {r.get("setup_family") for r in records if
                 r.get("setup_family")}),
            "law": "n_raw NEVER implies independence; a scanner firing "
                   "every minute for 90 minutes produced ONE episode, "
                   "not 90",
            "evidence_class": EVIDENCE_CLASS}
