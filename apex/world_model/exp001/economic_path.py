"""EXP-001 ECONOMIC PATH -- the smallest complete chain, engineering mode.

  forecast -> market/pricing benchmark -> feasible expression or CASH
  -> cost/fill -> PRIME -> ARENA -> independent RISK -> isolated paper BOOK
  -> outcome -> attribution

Every stage is an EXISTING component where one exists; this module wires
them and adds exactly one new piece, the deterministic PRIME selector.
Authority is preserved at every hand-off:

  * the forecast carries no direction to act on; the expression stage reads it
  * the benchmark is the executable range under a DECLARED spread; an
    option-implied benchmark at 15 minutes is NOT_ESTIMABLE and is said so
  * PRIME is a versioned rule set, not a model; it may only select or abstain
  * ARENA is apex.capital.arena.compete, unchanged
  * RISK is apex.organism.risk_certificate.certify, unchanged, and it is the
    authority: a STOP is not a bound, so a stock-with-stop is research
    observation only and CANNOT be funded with certified authority
  * the BOOK is apex.organism.book with an ISOLATED ledger under the run's
    directory; it never touches results/organism/paper_book.jsonl
  * fills are SIMULATED and labelled so; nothing here can reach a broker

A named refusal at any stage is a completed result and is accounted for in
the isolated book as a refusal, never as an empty success.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from apex.capital import arena as ARENA
from apex.capital import counterfactual as CF
from apex.organism import book as BOOK
from apex.organism import calibration as CAL
from apex.organism import risk_certificate as RISK
from apex.predators.equities import day_trader as DT
from .registration import HORIZON_STEPS, MODELLED_SPREAD_BPS

PATH_VERSION = "EXP001_ECONOMIC_PATH_V0"
PRIME_RULES_VERSION = "PRIME_RULES_V0"
FILL_CLASS = "SIMULATED"                    # never PAPER, never ACTUAL
SLEEVE = "EXP001_SHADOW"
STAGES = ("FORECAST", "BENCHMARK", "EXPRESSION", "COST_FILL", "PRIME",
          "ARENA", "RISK", "BOOK", "OUTCOME", "ATTRIBUTION")


class PathViolation(RuntimeError):
    """A stage was handed something it must not accept."""


def _refusal(stage: str, status: str, why: str, **extra) -> dict:
    return {"stage": stage, "status": status, "why": why, **extra}


# --------------------------------------------------------------- 1. forecast
def _forecast_view(fc) -> dict:
    """Read the laboratory forecast. It carries a distribution, not an order."""
    d = fc.distribution
    mu, sig = d.expected_return, d.total_uncertainty
    for name, v in (("expected_return", mu), ("total_uncertainty", sig),
                    ("prob_return_gt_zero", d.prob_return_gt_zero)):
        if v is None or not math.isfinite(v):
            raise PathViolation("FORECAST: %s is %r" % (name, v))
    if sig <= 0:
        raise PathViolation("FORECAST: non-positive uncertainty")
    return {"forecast_id": fc.forecast_id, "forecast_hash": fc.forecast_hash,
            "model_id": fc.model_id, "horizon": fc.forecast_horizon,
            "known_from": fc.known_from, "mu": mu, "sigma": sig,
            "p_up": d.prob_return_gt_zero,
            "maturity": fc.information_tier}


# --------------------------------------------------------------- 2. benchmark
def benchmark(close: float) -> dict:
    half = close * MODELLED_SPREAD_BPS / 1e4
    return {"executable_range": {"bid": close - half, "ask": close + half,
                                 "spread_bps": MODELLED_SPREAD_BPS,
                                 "source": "DECLARED_MODEL, not observed"},
            "option_implied_15m": "NOT_ESTIMABLE",
            "why_not_estimable": "no option quote history at 15-minute "
                                 "alignment on box; not claimed"}


# --------------------------------------------------------------- 3. expression
def expressions(view: dict, close: float) -> list:
    """CASH and two stock expressions. Expected after-cost return is the
    forecast mean minus the ROUND-TRIP modelled spread; nothing about the
    forecast's tail is used here, PRIME and RISK see the whole view."""
    rt = 2 * MODELLED_SPREAD_BPS / 1e4
    out = [{"expression": "CASH", "direction": "FLAT",
            "expected_after_cost": 0.0, "feasible": True}]
    for name, direction, sign in (("LONG_15M", "LONG", 1.0), ("SHORT_15M", "SHORT", -1.0)):
        out.append({"expression": name, "direction": direction,
                    "expected_after_cost": sign * view["mu"] - rt,
                    "feasible": True, "structure": "STOCK"})
    return out


# --------------------------------------------------------------- 4. cost / fill
def _declared_risk(sized: dict, entry: float, stop: float, qty: float, friction: float) -> float:
    """The 1R denominator: the EXECUTABLE loss at the stop. Read from the
    sizer under whichever name it uses; otherwise computed the same way it
    would be -- price distance plus the round-trip spread, per share, times
    quantity. Never zero for a sized position."""
    for k in ("modelled_total_loss_at_stop", "planned_risk", "risk_amount", "executable_risk", "risk"):
        v = sized.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return float((abs(entry - stop) + 2 * friction) * max(qty, 0))


def cost_fill(expr: dict, close: float, rv_30: float, *, fill_policy=None) -> dict:
    """Marketable fill through the modelled spread, sized from the
    EXECUTABLE loss at the stop. `fill_policy` lets a test inject
    rejection or a partial fill; the default is a full simulated fill."""
    if expr["expression"] == "CASH":
        return {"fill_class": FILL_CLASS, "state": "NO_FILL_CASH"}
    ref = DT.marketable_fill(close, expr["direction"])
    entry = ref["fill"]
    stop = entry - rv_30 * close if expr["direction"] == "LONG" else entry + rv_30 * close
    sized = DT.size_shadow(entry=entry, stop=stop, direction=expr["direction"])
    qty = sized.get("quantity", 0)
    state = "FILLED"
    if fill_policy:
        pol = fill_policy(expr, qty)
        state, qty = pol.get("state", state), pol.get("quantity", qty)
    return {"fill_class": FILL_CLASS, "state": state, "entry_fill": entry,
            "stop": stop, "quantity": qty,
            "friction_per_share": ref["friction_per_share"],
            "spread_bps": ref["spread_bps"], "model": ref["model"],
            "declared_risk": _declared_risk(sized, entry, stop, qty, ref["friction_per_share"]),
            "sizer": {k: sized[k] for k in sized if k not in ("kind", "law")}}


# --------------------------------------------------------------- 5. PRIME
def prime_select(view: dict, exprs: list, fills: dict) -> dict:
    """Deterministic, auditable eligibility rules. Consumes forecast
    maturity, economics, uncertainty and expression feasibility. It may
    select one expression or abstain to CASH; it cannot size, and it has no
    view of the book. Every rule that fired is named."""
    fired = []
    if not view["maturity"] or "ENGINEERING" in view["maturity"].upper():
        fired.append("R1_MATURITY_ENGINEERING_ONLY_NO_LIVE_ELIGIBILITY")
    if view["sigma"] <= 0 or not math.isfinite(view["sigma"]):
        fired.append("R2_UNCERTAINTY_INVALID")
    ranked = sorted((e for e in exprs if e["feasible"]),
                    key=lambda e: e["expected_after_cost"], reverse=True)
    best = ranked[0]
    if best["expression"] == "CASH" or best["expected_after_cost"] <= 0:
        fired.append("R3_NO_EXPRESSION_CLEARS_COST")
        return {"rules": PRIME_RULES_VERSION, "selection": "CASH", "fired": fired,
                "considered": [e["expression"] for e in ranked]}
    f = fills.get(best["expression"], {})
    if f.get("state") not in ("FILLED", "PARTIAL"):
        fired.append("R4_NO_FILL")
        return {"rules": PRIME_RULES_VERSION, "selection": "CASH", "fired": fired,
                "considered": [e["expression"] for e in ranked]}
    if (f.get("quantity") or 0) <= 0:
        fired.append("R5_ZERO_QUANTITY")
        return {"rules": PRIME_RULES_VERSION, "selection": "CASH", "fired": fired,
                "considered": [e["expression"] for e in ranked]}
    # edge-to-cost ratio must exceed 1: the expected gain must be at least
    # the round trip it already paid, or the selection is noise-chasing
    rt = 2 * MODELLED_SPREAD_BPS / 1e4
    if best["expected_after_cost"] < rt:
        fired.append("R6_EDGE_BELOW_ONE_ROUND_TRIP")
        return {"rules": PRIME_RULES_VERSION, "selection": "CASH", "fired": fired,
                "considered": [e["expression"] for e in ranked]}
    return {"rules": PRIME_RULES_VERSION, "selection": best["expression"],
            "direction": best["direction"], "fired": fired,
            "considered": [e["expression"] for e in ranked]}


# --------------------------------------------------------------- the path
def run_path(fc, row: dict, *, session: str, ledger_dir, available_capital: float,
             outcome_y: float | None = None, outcome_known_time: float | None = None,
             fill_policy=None, release_sha: str = "ENGINEERING") -> dict:
    """One forecast through the whole chain. Returns a trace keyed by stage.
    `outcome_y` (the 15-bar forward log return) may be attached afterwards
    by a second call to attach(); passing it here runs the whole path."""
    led = Path(ledger_dir); led.mkdir(parents=True, exist_ok=True)
    book_ledger = led / "paper_book.jsonl"
    cal_ledger = led / "calibration.jsonl"
    cf_ledger = led / "shadow_ledger.jsonl"
    t0 = time.time()
    trace = {"path_version": PATH_VERSION, "session": session, "stages": {},
             "fill_class": FILL_CLASS, "book_ledger": str(book_ledger)}

    def refuse(stage, status, why, **extra):
        # MERGE into whatever the stage already recorded (e.g. the full risk
        # certificate summary); a refusal adds a verdict, it never erases evidence
        trace["stages"][stage] = {**trace["stages"].get(stage, {}),
                                  **_refusal(stage, status, why, **extra)}
        trace["status"] = status; trace["terminal_stage"] = stage
        trace["elapsed_s"] = round(time.time() - t0, 3)
        if outcome_y is not None:
            trace["stages"]["OUTCOME"] = {"stage": "OUTCOME", "status": "NOT_APPLICABLE", "why": "no funded position"}
        if stage not in ("FORECAST",):
            env = trace.get("env") or {"candidate_id": trace.get("candidate_id", "NONE"),
                                       "symbol": row.get("symbol", "SPY"), "sleeve": SLEEVE}
            try:
                BOOK.refuse(env, stage=stage, reasons=[why], session=session, ledger=book_ledger)
                trace["stages"]["BOOK"] = {"stage": "BOOK", "status": "REFUSAL_ACCOUNTED"}
            except Exception as e:                           # noqa: BLE001
                trace["stages"]["BOOK"] = {"stage": "BOOK", "status": "REFUSAL_NOT_ACCOUNTED",
                                           "why": repr(e)[:200]}
        return trace

    # 1. FORECAST
    try:
        view = _forecast_view(fc)
    except PathViolation as e:
        return refuse("FORECAST", "INVALID_INPUT", str(e))
    if row.get("features") is None:
        return refuse("FORECAST", "INVALID_INPUT", "state has no features: %s" % row.get("why"))
    close, rv = row["close"], row["features"]["rv_30"]
    cid = "EXP001_" + hashlib.sha256(("%s|%s" % (view["forecast_id"], session)).encode()).hexdigest()[:12]
    trace["candidate_id"] = cid
    trace["stages"]["FORECAST"] = {"stage": "FORECAST", "status": "READY", **view}

    # 2. BENCHMARK
    trace["stages"]["BENCHMARK"] = {"stage": "BENCHMARK", "status": "READY", **benchmark(close)}

    # 3. EXPRESSION
    exprs = expressions(view, close)
    trace["stages"]["EXPRESSION"] = {"stage": "EXPRESSION", "status": "READY",
                                     "engine": "EXP001_STOCK_ONLY_V0",
                                     "options_structures": "NOT_IMPLEMENTED in this path "
                                     "(apex.expression.engine exists; needs a quote chain)",
                                     "candidates": exprs}

    # 4. COST / FILL
    fills = {e["expression"]: cost_fill(e, close, rv, fill_policy=fill_policy) for e in exprs}
    trace["stages"]["COST_FILL"] = {"stage": "COST_FILL", "status": "READY", "fills": fills}

    # 5. PRIME
    sel = prime_select(view, exprs, fills)
    trace["stages"]["PRIME"] = {"stage": "PRIME", "status": "READY", **sel}
    if sel["selection"] == "CASH":
        trace["status"] = "NO_SIGNAL"; trace["terminal_stage"] = "PRIME"
        trace["stages"]["BOOK"] = {"stage": "BOOK", "status": "CASH_NO_POSITION"}
        if outcome_y is not None:
            trace["stages"]["OUTCOME"] = {"stage": "OUTCOME", "status": "NOT_APPLICABLE", "why": "no funded position"}
        trace["elapsed_s"] = round(time.time() - t0, 3)
        return trace
    fill = fills[sel["selection"]]
    env = {"candidate_id": cid, "symbol": row.get("symbol", "SPY"),
           "direction": sel["direction"], "expression": "STOCK",
           "declared_risk": fill["declared_risk"],
           "declared_risk_repr": "EXECUTABLE_LOSS_AT_STOP_INCL_SPREAD",
           "funded_risk": None, "known_from": view["known_from"],
           "refused_utc": None, "sleeve": SLEEVE,
           "sleeve_payload": {"entry_fill": fill["entry_fill"], "stop": fill["stop"],
                              "quantity": fill["quantity"],
                              "entry_cost_per_share": fill["friction_per_share"],
                              "stop_exit_cost_per_share": fill["friction_per_share"]}}
    trace["env"] = env

    # 6. ARENA
    cand = ARENA.Candidate(candidate_id=cid, symbol=env["symbol"], direction=env["direction"],
                           expression="STOCK", declared_risk=env["declared_risk"],
                           edge_pedigree="UNPROVEN", entry_quality="MODELLED")
    port = ARENA.PortfolioState(available_capital=available_capital)
    ar = ARENA.compete(candidates=[cand], portfolio=port, session_minutes_left=390)
    mine = next((d for d in ar.get("decisions", []) if d.get("candidate_id") == cid), None) or ar
    trace["stages"]["ARENA"] = {"stage": "ARENA", "status": "READY",
                                "action": mine.get("action"), "reasons": mine.get("reasons"),
                                "cash_preferred": ar.get("cash_preferred"), "law": ar.get("law")}
    if mine.get("action") not in ("FUND", "PARTIALLY_FUND"):
        return refuse("ARENA", "NO_OPPORTUNITY", "arena: %s %s" % (mine.get("action"), mine.get("reasons")))

    # 7. RISK -- the authority. Not bypassable: the book is only written
    #    with a certificate, and a stop is not a bound.
    cert = RISK.certify(expression="STOCK", direction=env["direction"],
                        declared_risk=env["declared_risk"], sleeve_payload=env["sleeve_payload"])
    trace["stages"]["RISK"] = {"stage": "RISK", "status": "READY",
                               "risk_class": cert.get("risk_class"),
                               "certified_risk_authority": cert.get("certified_risk_authority"),
                               "prime_v0_eligible": cert.get("prime_v0_eligible"),
                               "research_observation_only": cert.get("research_observation_only"),
                               "certificate_hash": RISK.certificate_hash(cert)}
    if not cert.get("certified_risk_authority"):
        return refuse("RISK", "BLOCKED",
                      "risk_class=%s: a stop is not a bound; research observation only, "
                      "not fundable with certified authority" % cert.get("risk_class"),
                      risk_class=cert.get("risk_class"))

    # 8. BOOK (isolated ledger)
    CF.seal_decision(session=session, candidate_id=cid, symbol=env["symbol"],
                     baseline_action="CASH", shadow_action=sel["selection"],
                     reasons=sel["fired"] or ["PRIME_SELECTED"], declared_risk=env["declared_risk"],
                     portfolio_snapshot={"available_capital": available_capital}, ledger=cf_ledger)
    kernel = {"approved": True, "economic_risk": cert.get("certified_max_loss", env["declared_risk"]),
              "risk_kernel": cert, "risk_warnings": [], "threshold_set": PRIME_RULES_VERSION,
              "warnings": []}
    fund = BOOK.fund(env, arena_action=mine["action"], arena_reasons=mine.get("reasons") or [],
                     kernel=kernel, session=session, release_sha=release_sha, ledger=book_ledger)
    CAL.register(cal_ledger, claim_id=cid, p=view["p_up"], event="RET_15M_GT_0",
                 sleeve=SLEEVE, pedigree="ENGINEERING_SYNTHETIC", session=session)
    trace["stages"]["BOOK"] = {"stage": "BOOK", "status": "FUNDED", "funded_risk": fund.get("funded_risk"),
                               "entry_hash": fund.get("entry_hash")}
    trace["status"] = "READY"; trace["terminal_stage"] = "BOOK"
    trace["elapsed_s"] = round(time.time() - t0, 3)
    if outcome_y is not None:
        return attach(trace, outcome_y=outcome_y, outcome_known_time=outcome_known_time,
                      ledger_dir=led, session=session)
    return trace


def attach(trace: dict, *, outcome_y: float, outcome_known_time, ledger_dir, session: str) -> dict:
    """Outcome first, forecast unchanged; then attribution."""
    led = Path(ledger_dir)
    kf = ((trace.get("stages") or {}).get("FORECAST") or {}).get("known_from")
    if outcome_known_time is not None and kf is not None and outcome_known_time <= kf:
        raise PathViolation("OUTCOME known before the forecast: refusing to attach")
    if trace.get("status") != "READY":
        trace["stages"]["OUTCOME"] = {"stage": "OUTCOME", "status": "NOT_APPLICABLE",
                                      "why": "no funded position"}
        return trace
    env, fill = trace["env"], trace["stages"]["COST_FILL"]["fills"][trace["stages"]["PRIME"]["selection"]]
    sign = 1.0 if env["direction"] == "LONG" else -1.0
    gross = sign * outcome_y * fill["entry_fill"] * fill["quantity"]
    friction = 2 * fill["friction_per_share"] * fill["quantity"]
    pnl = gross - friction
    BOOK.attach_outcome(candidate_id=env["candidate_id"], session=session, executable_pnl=round(pnl, 4),
                        outcome_class="SIMULATED_15M_HOLD", detail={"y": outcome_y, "friction": friction},
                        ledger=led / "paper_book.jsonl")
    CF.append_outcome(session=session, candidate_id=env["candidate_id"], baseline_pnl=0.0,
                      shadow_pnl=round(pnl, 4), ledger=led / "shadow_ledger.jsonl") \
        if hasattr(CF, "append_outcome") else None
    CAL.resolve(led / "calibration.jsonl", claim_id=env["candidate_id"], occurred=outcome_y > 0)
    trace["stages"]["OUTCOME"] = {"stage": "OUTCOME", "status": "ATTACHED", "y": outcome_y,
                                  "executable_pnl": round(pnl, 4), "gross": round(gross, 4),
                                  "friction": round(friction, 4), "fill_class": FILL_CLASS}
    # attribution: only what the evidence identifies
    f = trace["stages"]["FORECAST"]
    z = (outcome_y - f["mu"]) / f["sigma"]
    attr = {"forecast_error_z": round(z, 3),
            "direction_correct": (outcome_y > 0) == (env["direction"] == "LONG"),
            "cost_fraction_of_gross": round(friction / abs(gross), 3) if gross else None,
            "classes": []}
    if abs(z) > 2.5:
        attr["classes"].append("FORECAST_DISTRIBUTION_ERROR_CANDIDATE")
    if not attr["direction_correct"] and abs(z) <= 2.5:
        attr["classes"].append("WITHIN_DISTRIBUTION_ADVERSE_DRAW")
    if gross and friction / abs(gross) > 0.5:
        attr["classes"].append("EXECUTION_COST_DOMINATED")
    if not attr["classes"]:
        attr["classes"].append("NOT_IDENTIFIABLE_FROM_ONE_OUTCOME")
    trace["stages"]["ATTRIBUTION"] = {"stage": "ATTRIBUTION", "status": "READY", **attr}
    return trace
