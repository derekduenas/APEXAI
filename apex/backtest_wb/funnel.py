"""FULL_FUNNEL variant for PILOT-REPLAY-002: the ONE decision engine (apex.decision_wb.engine.FunnelEngine) run inside the
replay on the same population as the deterministic pilot rule and WAIT.

Walk-forward: per session the engine is re-fitted on pooled 1-minute regular-hours returns of the trailing `window_sessions`
COMPLETED sessions (strictly before the day). Per scan: causal prefix of the day's returns + the corpus quotes at the decision
minute -> engine.decide -> the SAME fill/exit accounting as every other variant (entry ask at m, exit bid at m+15, fees once)."""
from __future__ import annotations

import math
from datetime import datetime

from apex.decision_wb.engine import FunnelEngine

REPLAY_BOOK = {"kind": "REPLAY_SYNTHETIC_BOOK: one contract per scan, no carried positions; declared, not a live book", "integrity_problems": [],
               "n_positions": 0, "n_reservations": 0}


class FunnelRunner:
    def __init__(self, *, window_sessions: int = 20, n_paths: int = 2000, seed: int = 11, strikes_each_side: int = 2, fit_budget: int = 400):
        self.window_sessions = window_sessions
        self.engine = FunnelEngine(n_paths=n_paths, seed=seed, strikes_each_side=strikes_each_side, fit_budget=fit_budget)
        self.history: list = []                   # [(day, [ret_1 ...])] of completed sessions, chronological
        self.fitted_for: str | None = None

    @property
    def fit_log(self):
        return self.engine.fit_log

    @property
    def fits(self):
        return self.engine.fits

    def _train_rows(self):
        rows = []
        for day, rets in self.history[-self.window_sessions:]:
            t0 = datetime.fromisoformat(day).timestamp()
            rows.extend({"event_time": t0 + 60 * i, "available": t0 + 60 * i + 60, "ret_1": r} for i, r in enumerate(rets))
        return rows

    def prepare(self, day: str) -> dict:
        if self.fitted_for == day:
            return self.engine.fit_info
        self.fitted_for = day
        return self.engine.fit(self._train_rows(), cutoff_epoch=datetime.fromisoformat(day).timestamp() - 1.0,
                               label="%s <- %s" % (day, [d for d, _ in self.history[-self.window_sessions:]]))

    def end_session(self, *, day: str, bars: list) -> None:
        self.history.append((day, [math.log(bars[i]["close"] / bars[i - 1]["close"]) for i in range(1, len(bars))]))

    def decide(self, *, day: str, m: float, snapshot: dict, forecast: dict, q_now: dict, q_exit: dict, spot, bars_prefix: list, fee_schedule) -> dict:
        self.prepare(day)
        prefix = [math.log(bars_prefix[i]["close"] / bars_prefix[i - 1]["close"]) for i in range(1, len(bars_prefix))]
        quotes = {(e, float(k), r): dict(q) for (e, k, r), q in q_now.items()}          # corpus quotes carry their OWN timestamps
        res = self.engine.decide(symbol="SPY", as_of=m, day=day, snapshot=snapshot, forecast=forecast, spot=spot, quotes=quotes, prefix_returns=prefix,
                                 fee_schedule=fee_schedule, book_summary=REPLAY_BOOK, heuristic_direction=forecast.get("direction_signal"))
        v = {"direction": None, "decision": res["decision"], "why": res["why"], "trace": res["trace"], "rule_id": res["rule_id"]}
        if res["decision"] != "TRADE":
            return v
        c = res["proposal"]["contract"]
        key = (c["expiration"], float(c["strike"]), c["right"])
        q = q_now[key]
        v.update(direction=res["proposal"]["direction_signal"], contract=c, contract_id="SPY|%s|%s|%s" % key,
                 entry_quote={k3: q[k3] for k3 in ("bid", "ask", "bid_size", "ask_size")}, expected_net_pnl_model=res["proposal"]["expected_net_pnl_model"])
        from .replay import fill_and_exit
        fx = fill_and_exit(q, q_exit.get(key), fee_schedule)
        v.update(exit=fx["exit"], pnl=fx["pnl"])
        if fx["pnl"] is None:
            v["decision"], v["why"] = "TRADE_UNRESOLVED", "position filled; exit not estimable at +15"
        return v
