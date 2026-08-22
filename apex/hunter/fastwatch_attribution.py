"""FastWatch -> Hunter attribution — OBSERVATIONAL LINKAGE ONLY.

On 2026-08-18 FastWatch emitted 3,160 events across 29 symbols, 421 of
them carrying condition tags, and ZERO became a Hunter playbook match.
Whether that means FastWatch provides useful candidate-evolution lead
time, or is simply noise the frozen playbook correctly ignores, is
unanswerable without measuring the linkage over many sessions. This
module builds the measurement.

FASTWATCH HAS NO AUTHORITY. Nothing here can promote a FastWatch event
into a Hunter candidate, and the linkage is computed strictly forward in
time: a Hunter event can only be attributed to a FastWatch event that
happened STRICTLY BEFORE it. `NO_LATER_HUNTER_WATCHLIST` and
`NO_LATER_MATCH` are first-class outcomes, not missing data.

LEAD TIME IS NOT EDGE. `lead_minutes` measures when two subsystems
noticed something, nothing about whether noticing was profitable.

decision_power: NONE_OBSERVABILITY.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

LEDGER = Path("results/hunter/fastwatch_attribution.jsonl")

OUTCOMES = ("MATCHED", "NO_LATER_MATCH", "NO_LATER_HUNTER_WATCHLIST")


class FastWatchAttributionError(RuntimeError):
    pass


@dataclass(frozen=True)
class FastWatchAttribution:
    fastwatch_event_id: str
    symbol: str
    condition: str
    fastwatch_event_time: str

    hunter_first_watchlist_time: str | None
    hunter_match_time: str | None
    eventual_playbook: str | None
    lead_minutes: float | None
    eventual_match: str
    outcome_ref: str | None

    session_date: str
    known_from: str
    decision_power: str = "NONE_OBSERVABILITY"

    def __post_init__(self):
        if self.eventual_match not in OUTCOMES:
            raise FastWatchAttributionError(
                f"unknown outcome {self.eventual_match!r}")
        if self.eventual_match == "MATCHED" and self.hunter_match_time is None:
            raise FastWatchAttributionError(
                "MATCHED requires a hunter_match_time")

    def as_record(self) -> dict:
        return {"kind": "fastwatch_attribution", **asdict(self)}


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def build(*, session_date: str, fastwatch_ledger: Path, forward_ledger: Path,
          known_from) -> list:
    """Join FastWatch events to Hunter's own ledger, strictly forward in
    time. Reads both canonical ledgers; recomputes nothing."""
    import pandas as pd

    fw = [r for r in _read_jsonl(Path(fastwatch_ledger))
          if str(r.get("observed_at", "")).startswith(session_date)
          and r.get("fastwatch_condition_observed")]

    hunter = _read_jsonl(Path(forward_ledger))
    # first time each symbol appeared on a Hunter watchlist today
    first_watchlist: dict = {}
    for r in hunter:
        if r.get("kind") != "scan":
            continue
        t = r.get("t_utc")
        if not t or not str(t).startswith(session_date):
            continue
        for w in (r.get("watchlist") or []):
            sym = w.get("symbol") if isinstance(w, dict) else w
            if sym and sym not in first_watchlist:
                first_watchlist[sym] = t

    # real (non-baseline) playbook matches today
    matches: dict = {}
    for r in hunter:
        if r.get("kind") != "decision":
            continue
        pb = str(r.get("playbook_id", ""))
        if pb.startswith("BASELINE-"):
            continue
        t = r.get("t_utc")
        if not t or not str(t).startswith(session_date):
            continue
        sym = r.get("symbol")
        if sym and sym not in matches:
            matches[sym] = {"time": t, "playbook": pb,
                            "decision_id": r.get("decision_id")}

    out = []
    for e in fw:
        sym = e.get("symbol")
        ev_t = pd.Timestamp(e["observed_at"])
        conds = e.get("fastwatch_condition_observed") or []
        condition = ",".join(conds) if isinstance(conds, list) else str(conds)

        wl_t = first_watchlist.get(sym)
        m = matches.get(sym)

        # STRICTLY FORWARD: only a Hunter event AFTER this FastWatch
        # event can be attributed to it.
        wl_after = (wl_t if wl_t is not None
                    and pd.Timestamp(wl_t) > ev_t else None)
        m_after = (m if m is not None
                   and pd.Timestamp(m["time"]) > ev_t else None)

        if m_after is not None:
            outcome = "MATCHED"
            lead = round((pd.Timestamp(m_after["time"]) - ev_t).total_seconds() / 60.0, 3)
        elif wl_after is not None:
            outcome = "NO_LATER_MATCH"
            lead = round((pd.Timestamp(wl_after) - ev_t).total_seconds() / 60.0, 3)
        else:
            outcome = "NO_LATER_HUNTER_WATCHLIST"
            lead = None

        out.append(FastWatchAttribution(
            fastwatch_event_id=f"{sym}@{e['observed_at']}", symbol=sym,
            condition=condition, fastwatch_event_time=str(ev_t),
            hunter_first_watchlist_time=(str(wl_after) if wl_after else None),
            hunter_match_time=(str(m_after["time"]) if m_after else None),
            eventual_playbook=(m_after["playbook"] if m_after else None),
            lead_minutes=lead, eventual_match=outcome,
            outcome_ref=(m_after["decision_id"] if m_after else None),
            session_date=session_date,
            known_from=str(pd.Timestamp(known_from))))
    return out


def persist_all(records: list) -> int:
    from apex.governance.chain_ledger import chain_append as _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    for r in records:
        _chain_append(LEDGER, r.as_record())
    return len(records)


def summarize(records: list) -> dict:
    leads = [r.lead_minutes for r in records if r.lead_minutes is not None]
    by_outcome: dict = {}
    for r in records:
        by_outcome[r.eventual_match] = by_outcome.get(r.eventual_match, 0) + 1
    return {
        "kind": "fastwatch_attribution_summary",
        "events_linked": len(records),
        "by_outcome": dict(sorted(by_outcome.items())),
        "distinct_symbols": len({r.symbol for r in records}),
        "mean_lead_minutes": (round(sum(leads) / len(leads), 3) if leads else None),
        "max_lead_minutes": (max(leads) if leads else None),
        "note": ("lead time measures when two subsystems noticed something; "
                "it is not evidence of edge"),
        "decision_power": "NONE_OBSERVABILITY",
    }
