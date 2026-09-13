"""TRADINGVIEW-CONNECTOR-001 — run the bounded smoke test from RECORDED tool responses.

    python scripts/tradingview_smoke.py <calls.json> <out.json>

WHY A FILE AND NOT A DIRECT CALL. The MCP tools live in the Claude Code client, not in this process; the adapter is
built to take an INJECTED transport precisely so it never needs a credential of its own. The agent holding the
authorized session calls each allowed tool, records the request instant, the response instant and the payload, and
hands them here. This script then drives the REAL adapter over those recordings, so the allowlist, the budget, the
cache and the whole normalization contract are exercised on live data without this process ever touching an OAuth
session.

`calls.json` is a list, in the order the calls were actually made:

    [{"tool": "search_symbols",
      "args": {"query": "SPY"},
      "request_start": 1789000019.5,        # epoch seconds, when the request was ISSUED
      "response_receipt": 1789000020.1,     # epoch seconds, when the response ARRIVED
      "payload": { ... the tool's response, verbatim ... }},
     ...]

THE INSTANTS MUST BE THE REAL ONES. `known_from` is taken from `response_receipt`, and everything the connector
claims about availability rests on it. A fabricated receipt would manufacture exactly the hindsight the
normalization contract exists to prevent, so the script refuses a receipt that precedes its request, refuses a
receipt in the future of the wall clock, and refuses calls that are not in non-decreasing receipt order.

It refuses more than ten calls, refuses any tool off the allowlist, and refuses to overwrite an existing output."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from apex.tradingview import adapter as A  # noqa: E402
from apex.tradingview import allowlist as AL  # noqa: E402
from apex.tradingview import normalize as N  # noqa: E402

MAX_CALLS = 10


class SmokeRefused(RuntimeError):
    """The recording does not support an honest run. Named, never silent."""


def load_calls(path: Path, *, now: float) -> list:
    calls = json.loads(Path(path).read_text())
    if not isinstance(calls, list) or not calls:
        raise SmokeRefused("CALLS_EMPTY_OR_NOT_A_LIST")
    if len(calls) > MAX_CALLS:
        raise SmokeRefused("BUDGET_EXCEEDED_IN_THE_RECORDING: %d calls, the brick bounds the smoke test at %d"
                           % (len(calls), MAX_CALLS))
    last = None
    for i, c in enumerate(calls):
        for k in ("tool", "args", "request_start", "response_receipt", "payload"):
            if k not in c:
                raise SmokeRefused("CALL_%d_MISSING_FIELD: %s" % (i, k))
        AL.permit(c["tool"])                                  # off-allowlist recordings are refused too
        rs, rr = float(c["request_start"]), float(c["response_receipt"])
        if rr < rs:
            raise SmokeRefused("CALL_%d_RECEIPT_BEFORE_REQUEST: %.6f < %.6f" % (i, rr, rs))
        if rr > now + 1.0:
            raise SmokeRefused("CALL_%d_RECEIPT_IN_THE_FUTURE: %.6f > clock %.6f; a fabricated receipt would "
                               "manufacture availability that never happened" % (i, rr, now))
        if last is not None and rr < last:
            raise SmokeRefused("CALL_%d_OUT_OF_ORDER: receipt %.6f precedes the previous call's %.6f" % (i, rr, last))
        last = rr
    return calls


def run(calls: list) -> dict:
    """Drive the real adapter over the recordings, one call at a time, on a clock that follows the recording."""
    state = {"i": 0, "t": float(calls[0]["request_start"])}

    def now():
        return state["t"]

    a = A.TradingViewAdapter(None, now_fn=now, sleep_fn=lambda s: None,
                             budget=A.Budget(max_calls=MAX_CALLS, now_fn=now))
    results = []
    for c in calls:
        state["t"] = float(c["request_start"])
        payload = c["payload"]

        def transport(name, args, _p=payload, _c=c):
            state["t"] = float(_c["response_receipt"])        # time advances to the real receipt, never backwards
            return _p
        a._call = transport
        env = a.call(c["tool"], **c["args"])
        obs = None
        if env["state"] == A.STATE_OK:
            obs = N.observation(tool=c["tool"], args=c["args"], payload=payload,
                                request_start=env["request_start_epoch"],
                                response_receipt=env["response_receipt_epoch"],
                                symbol=c.get("symbol"), interval=c.get("interval"), units=c.get("units"),
                                source_event_time=c.get("source_event_time"),
                                source_publication_time=c.get("source_publication_time"),
                                entitlement=c.get("entitlement", N.ENTITLEMENT_UNKNOWN))
            a.observations.append(obs)
        results.append({"tool": c["tool"], "args": c["args"], "state": env["state"], "why": env.get("why"),
                        "from_cache": env["from_cache"],
                        "observation": ({k: v for k, v in obs.items() if k != "payload"} if obs else None),
                        "payload_digest": (obs["response_digest"] if obs else None)})
    return {"kind": "TRADINGVIEW_SMOKE", "provider": AL.PROVIDER, "allowlist": AL.describe(),
            "n_calls": len(calls), "results": results, "report": a.report(),
            "observations_deduped": [
                {k: v for k, v in o.items() if k != "payload"}
                for o in _dedupe([o for o in a.observations])],
            "law": ("recorded live responses replayed through the real adapter; known_from is the recorded response "
                    "receipt, historical availability is NOT_ESTABLISHED, entitlement is whatever the server stated "
                    "or UNKNOWN")}


def _dedupe(observations: list) -> list:
    out: list = []
    for o in observations:
        out = N.merge(out, o)["observations"]
    return out


def main() -> int:
    calls_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    if out_path.exists():
        raise SmokeRefused("OUTPUT_EXISTS: %s; this script never overwrites a previous run's evidence" % out_path)
    calls = load_calls(calls_path, now=time.time())
    res = run(calls)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({"out": str(out_path), "n_calls": res["n_calls"],
                      "states": [r["state"] for r in res["results"]],
                      "entitlements": sorted({(r["observation"] or {}).get("entitlement")
                                              for r in res["results"] if r["observation"]}),
                      "budget": res["report"]["budget"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
