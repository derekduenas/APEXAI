"""TRACE REPLAY — PART 1: one trade, full lineage, through the REAL path (mechanism validation, NOT a backtest).

    python scripts/trace_replay_one.py <collection_dir> <out_dir> [--index N]

Real `TwinSources`, real `Boundary`, real `records` validators, real `CertifiedRiskAuthority` + kernel, real ledger,
real `Book`, real exit policy. ONLY the data and clock adapters are recorded: bars, NBBO, chain and per-contract
quotes come from the 2026-09-11 collection instead of from the network.

LABEL DEFECT, DECLARED: `records.assert_prospective` refuses `HISTORICAL_DEVELOPMENT_REPLAY`, so the boundary CANNOT
label a replay. Records written by this driver therefore carry `execution_mode: PROSPECTIVE_ORCHESTRATION`, which is
FALSE for a replay. The ledger is written to an ISOLATED path outside `/apex-data` and outside `results/`, is
registered as QUARANTINED_REPLAY, and must never be merged into a pilot ledger. Reported as a Part 4 finding.

No tuning. No threshold touched. Nothing here may inform a parameter choice."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from apex.options_pilot import boundary as B, ledger as L, session as S  # noqa: E402
from apex.options_pilot.clock import Clock, to_utc_string  # noqa: E402
from apex.options_pilot.fees import ROBINHOOD_RHF_2026  # noqa: E402
from apex.options_pilot.risk_authority import CertifiedRiskAuthority  # noqa: E402
from apex.pulse_options import sources as SRC  # noqa: E402

HOLD_S = 900.0


def load(d: Path):
    def rows(name):
        for line in open(d / name):
            line = line.strip()
            if line:
                yield json.loads(line)
    chains = [(r["receipt_epoch"], r["payload"]) for r in rows("chain_SPY.jsonl") if r.get("kind") == "pilot_collection_chain"]
    nbbo = sorted((r["payload"]["as_of"], r["payload"]) for r in rows("nbbo_SPY.jsonl") if r.get("kind") == "pilot_collection_nbbo")
    bars = {}
    for r in rows("bars_SPY.jsonl"):
        if r.get("kind") == "pilot_collection_bars":
            for b in r["payload"]:
                # EARLIEST receipt wins: a bar was knowable from the FIRST fetch that returned it. The collector's
                # 5-minute request window returns each bar ~5 times; keeping the last receipt would make every bar
                # look 262 s stale and refuse every forecast.
                prev = bars.get(b["event_time"])
                if prev is None or b["receipt_time"] < prev["receipt_time"]:
                    bars[b["event_time"]] = b
    return sorted(chains), nbbo, sorted(bars.values(), key=lambda b: b["event_time"])


class Recorded:
    """The recorded session as data+clock adapters. Nothing is interpolated; a missing observation is missing."""

    def __init__(self, chains, nbbo, bars):
        self.chains, self.nbbo, self.bars = chains, nbbo, bars
        self.t = chains[0][0]
        self.provider = "ALPACA_DATA_V2"
        self.reads = []

    # clock
    def now(self):
        return self.t

    def advance(self, s):
        self.t += float(s)

    # bars (the twin asks for [as_of - warmup, as_of])
    def bars_fn(self, symbol, *, start_epoch, end_epoch):
        out = [{"symbol": symbol, "event_time": b["event_time"], "available_time": b["receipt_time"], "receipt_time": b["receipt_time"],
                "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "volume": b["volume"],
                "publication_time": b.get("publication_time"), "vwap": b.get("vwap"), "trades": b.get("trades"), "provider": "ALPACA_DATA_V2"}
               for b in self.bars if start_epoch <= b["event_time"] < end_epoch and b["receipt_time"] <= self.t]
        self.reads.append({"read": "bars", "t": self.t, "n": len(out)})
        return out

    def nbbo_fn(self, symbol, t):
        prev = [p for (ts, p) in self.nbbo if ts <= self.t]
        if not prev:
            return None
        p = prev[-1]
        self.reads.append({"read": "nbbo", "t": self.t, "as_of": p["as_of"]})
        return {"bid": p["bid"], "ask": p["ask"], "bid_size": p["bid_size"], "ask_size": p["ask_size"], "t": p["as_of"], "source": p["source"]}

    def _snapshot_at(self, t):
        """The latest chain snapshot whose receipt <= t. Never a future snapshot."""
        prior = [(ts, p) for (ts, p) in self.chains if ts <= t]
        return prior[-1] if prior else None

    def chain_fn(self, symbol, as_of):
        snap = self._snapshot_at(self.t)
        if snap is None:
            from apex.pulse_options.providers import ProviderUnavailable
            raise ProviderUnavailable("NO_RECORDED_CHAIN_SNAPSHOT at %s" % to_utc_string(self.t))
        ts, payload = snap
        self.reads.append({"read": "chain", "t": self.t, "snapshot_receipt": ts, "n_quotes": len(payload["quotes"])})
        rows = SRC.live_chain_rows([{**q, "expiration": q.get("expiration", payload["expiration"]), "symbol": symbol} for q in payload["quotes"]],
                                   symbol=symbol, receipt_time=ts)
        self.last_chain = (ts, payload, rows)
        return rows

    def quote_fn(self, contract):
        snap = self._snapshot_at(self.t)
        if snap is None:
            from apex.pulse_options.providers import ProviderUnavailable
            raise ProviderUnavailable("NO_RECORDED_CHAIN_SNAPSHOT at %s" % to_utc_string(self.t))
        ts, payload = snap
        rows = SRC.live_chain_rows([{**q, "expiration": q.get("expiration", payload["expiration"]), "symbol": contract["symbol"]} for q in payload["quotes"]],
                                   symbol=contract["symbol"], receipt_time=ts)
        want = (contract["expiration"], float(contract["strike"]), contract["right"])
        if want in rows.conflicted:
            from apex.pulse_options.providers import ProviderUnavailable
            raise ProviderUnavailable("QUOTE_CONFLICTED_IN_SNAPSHOT: %s" % (want,))
        for r in rows:
            if (r["expiration"], r["strike"], r["right"]) == want:
                self.reads.append({"read": "quote", "t": self.t, "snapshot_receipt": ts, "contract": str(want), "bid": r["bid"], "ask": r["ask"]})
                return r
        from apex.pulse_options.providers import ProviderUnavailable
        raise ProviderUnavailable("QUOTE_NOT_IN_RECORDED_SNAPSHOT: %s at %s" % (want, to_utc_string(self.t)))


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("collection"); ap.add_argument("out")
    ap.add_argument("--index", type=int, default=None, help="chain-snapshot index to enter at; default = first that certifies")
    a = ap.parse_args()
    d, out = Path(a.collection), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    chains, nbbo, bars = load(d)
    rec = Recorded(chains, nbbo, bars)
    led = out / "REPLAY_QUARANTINED_ledger.jsonl"
    if led.exists():
        led.unlink()
    clock = Clock(rec.now)
    twin = SRC.TwinSources(provenance="LIVE_FEED", clock=clock, bar_source=type("BS", (), {"provider": "ALPACA_DATA_V2", "bars": staticmethod(rec.bars_fn)})(),
                           chain_fn=rec.chain_fn, quote_fn=rec.quote_fn, exit_quote_fn=rec.quote_fn, fee_schedule=ROBINHOOD_RHF_2026,
                           sleep_fn=rec.advance, book_fn=rec.nbbo_fn, selection_policy="PILOT_RULE_V2")
    # the boundary MUST carry the same schedule as the authority: the first run of this driver passed it only to the
    # authority and the boundary defaulted to UNVERIFIED, producing an APPROVED intent whose own record said the cost
    # was unknown. That is finding A in docs/TRACE_ONE_TRADE.md; nothing cross-checks the two today.
    bd = B.Boundary(led, clock=clock, provenance="LIVE_FEED", risk_authority=CertifiedRiskAuthority(fee_schedule=ROBINHOOD_RHF_2026, provenance="LIVE_FEED"),
                    session_id="TRACE-REPLAY-2026-09-11", release="TRACE_REPLAY_NOT_A_RELEASE", fee_schedule=ROBINHOOD_RHF_2026)
    from apex.options_pilot.runtime_identity import runtime_identity
    bd.runtime_identity = runtime_identity()
    S.open_session(bd, symbols=["SPY"])
    src = twin.sources(); src.pop("exit_quote_fn")
    trace = {"kind": "TRACE_REPLAY_PART1", "session": "2026-09-11", "ledger": str(led), "attempts": []}
    chosen = None
    start = a.index if a.index is not None else 0
    for i in range(start, len(chains)):
        rec.t = chains[i][0]
        rec.reads = []
        seq = S.next_seq(led, session_id=bd.session_id)
        d0 = S.scan(bd, symbol="SPY", seq=seq, **src)
        trace["attempts"].append({"index": i, "t_utc": to_utc_string(rec.t), "decision": d0["decision"], "why": (d0.get("why") or "")[:160]})
        if d0["decision"] == "TRADE":
            chosen = (i, d0, list(rec.reads))
            break
        if a.index is not None:
            break
    if chosen is None:
        trace["outcome"] = "NO_TRADE_IN_SESSION"
        (out / "trace_part1.json").write_text(json.dumps(trace, indent=1, default=str) + "\n")
        print(json.dumps({"outcome": "NO_TRADE", "attempts": len(trace["attempts"]), "last": trace["attempts"][-1] if trace["attempts"] else None}, indent=1))
        return 0
    i, d0, reads = chosen
    entry_t = rec.t
    # ---- exit at +15 min against the ACTUAL recorded quote at that instant
    rec.t = entry_t + HOLD_S
    rec.reads = []
    exits = S.attempt_exits(bd, exit_quote_fn=twin._exit_quote_fn, sleep_fn=rec.advance, wait_for_due=False)
    exit_reads = list(rec.reads)
    rows = L.read_all(led)
    book = bd.book()
    trace.update(entry_index=i, entry_t_utc=to_utc_string(entry_t), exit_t_utc=to_utc_string(entry_t + HOLD_S),
                 chain_reads=reads, exit_reads=exit_reads, exits=exits,
                 records=[{"seq": n + 1, "kind": r["kind"], "entry_hash": r.get("entry_hash"), "txn_id": r.get("txn_id")} for n, r in enumerate(rows)],
                 book={"positions": len(book.positions), "closed": len(book.closed), "session_realized_pnl": book.session_realized_pnl,
                       "integrity_problems": book.summary()["integrity_problems"]},
                 chain_verified=L.verify_chain(led))
    (out / "trace_part1.json").write_text(json.dumps(trace, indent=1, default=str) + "\n")
    (out / "records.json").write_text(json.dumps(rows, indent=1, default=str) + "\n")
    print(json.dumps({"entry_index": i, "entry": trace["entry_t_utc"], "exit": trace["exit_t_utc"],
                      "kinds": [r["kind"] for r in rows], "book": trace["book"], "exits": exits}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
