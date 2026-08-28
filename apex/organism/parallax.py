"""PARALLAX — Market Expectation Violation Observatory. SHADOW ONLY.

    WHAT SHOULD HAVE HAPPENED  vs  WHAT ACTUALLY HAPPENED
    -> was the difference material?
    -> how did the dislocation resolve?

PARALLAX does not predict the market. It records what APEX expected
BEFORE the market moved, measures the violation, and remembers it. The
violation is not alpha; it is a question. Capital does not see it, the
sleeves do not see it, the trader does not change.

A THIN DERIVED LAYER, by recon: the sealed pre-reaction expectation
already exists (CatalystEvent.directional_expectation with
expectation_known_from, hindsight-fenced by the CAT-RXN repair);
reaction measurement, disagreement, the cross-predator echo law and
AS_KNOWN_AT are all commissioned. This module adds only what was
missing: the relative/propagation dimensions, the violation-debt-
resolution taxonomy, and episode accounting.

THE HINDSIGHT FIREWALL IS ONE CHECK, APPLIED EVERYWHERE: a PARALLAX
observation exists only where expectation_known_from precedes the first
measured reaction bar. A huge move without a sealed prior expectation
is NOT_PARALLAX_ELIGIBLE -- neither success nor failure, just absent.

decision_power: PARALLAX_SHADOW_OBSERVATORY -- observation only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apex.capital.arena import INDEX_FAMILY, SECTOR
from apex.governance.chain_ledger import chain_append

AUTHORITY = "PARALLAX_SHADOW_OBSERVATORY"

EXPECTATIONS = Path("results/parallax/expectations.jsonl")
VIOLATIONS = Path("results/parallax/violations.jsonl")

# structural relationship map -- INCUMBENT relationships only (the
# arena's beta/sector maps + the fabric's sector ETFs). Nothing
# speculative is hardcoded because it "sounds reasonable".
SECTOR_ETF = {"TECH": "XLK", "SEMIS": "XLK", "BROAD": "SPY",
              "BROAD_TECH": "QQQ", "BROAD_SMALL": "IWM"}
INDEX_ETF = {"US_LARGE_BETA": "SPY", "US_SMALL_BETA": "IWM"}

VIOLATION_CLASSES = (
    "EXPECTED_REACTION", "FAILED_POSITIVE_REACTION",
    "FAILED_NEGATIVE_REACTION", "UNDERREACTION", "OVERREACTION",
    "DELAYED_REACTION", "REVERSAL", "RELATIVE_DISLOCATION",
    "CROSS_ASSET_PROPAGATION_FAILURE", "VOLATILITY_DISLOCATION",
    "LIQUIDITY_CONTRADICTION", "NO_IDENTIFIABLE_REACTION", "UNKNOWN")

DEBT_LEVELS = ("NONE", "LOW", "MODERATE", "HIGH", "EXTREME",
               "NOT_ESTIMABLE")
# predeclared deterministic bands, in ATR units of |expected-vs-
# realized| price disagreement at the primary horizon. NOT tuned, and
# never a trading score.
DEBT_BANDS = ((0.25, "NONE"), (0.75, "LOW"), (1.5, "MODERATE"),
              (3.0, "HIGH"))

RESOLUTIONS = (
    "PRICE_CATCHES_UP", "EXPECTATION_PROVEN_WRONG",
    "OPPOSING_FORCE_DOMINATES", "ALREADY_PRICED",
    "REACTION_MIGRATES_TO_RELATED_ASSET",
    "VOLATILITY_EXPRESSES_INSTEAD_OF_DIRECTION",
    "TEMPORARY_LIQUIDITY_SUPPRESSION", "REVERSAL_CONTINUES",
    "DISLOCATION_PERSISTS", "UNKNOWN")

RELATIVE_FLOOR_ATR = 0.25       # incumbent reaction floor, reused


def taxonomy_sha() -> str:
    """Fingerprint of the rules doing the classifying. Stamped on
    every row so 'what did PARALLAX classify this as under the rules
    actually running that day?' stays answerable forever."""
    import hashlib
    return hashlib.sha256(json.dumps(
        [VIOLATION_CLASSES, DEBT_BANDS, RESOLUTIONS,
         RELATIVE_FLOOR_ATR]).encode()).hexdigest()[:16]


# THE EVIDENTIARY VERSIONING LAW (operator-sealed 2026-08-29):
#   CURRENT_ANALYTICAL_VIEW      may use legitimate corrections
#   ORIGINAL_PROSPECTIVE_RECORD  never disappears
#   NEW TAXONOMY VERSION         cannot retroactively become
#                                prospective evidence
#   OLD SESSION + NEW RULES      = RETROSPECTIVE_RECLASSIFICATION
# Improved logic replayed over old sessions is tomorrow's knowledge
# wearing yesterday's timestamps; the prospective path therefore
# refuses any session that is not the current one.
EVIDENTIARY_VERSIONING_LAW = (
    "an unlabeled (prospective) pass may only classify the CURRENT "
    "session; any other session is RETROSPECTIVE_RECLASSIFICATION and "
    "must say so")


class ParallaxViolation(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -------------------------------------------------------- expectation

def expectation_from_event(ev: dict) -> dict | None:
    """Project a sealed catalyst expectation into a PARALLAX vector.

    DERIVED, not created: every causal field comes from an artifact
    that was sealed BEFORE any reaction (expectation_known_from is
    enforced upstream by the CAT-RXN repair). If the event carries no
    pre-reaction directional expectation it is NOT_PARALLAX_ELIGIBLE --
    there is nothing to be violated.

    Accepts the governed CatalystEvent dataclass or its dict form --
    the live ledger produces the former; assuming dicts is exactly the
    schema-guessing defect class that cost two candidates on Thursday.
    """
    import dataclasses
    if dataclasses.is_dataclass(ev) and not isinstance(ev, dict):
        ev = dataclasses.asdict(ev)
    de = ev.get("directional_expectation", "UNKNOWN")
    ekf = ev.get("expectation_known_from", "NONE")
    # ONLY a directional expectation can be directionally violated.
    # The governed vocabulary also holds AMBIGUOUS -- the first live
    # playback caught an AMBIGUOUS event being silently signed as
    # NEGATIVE, which is a fabricated expectation. Whitelist, never
    # blocklist, a vocabulary.
    if de not in ("POSITIVE", "NEGATIVE") or ekf in ("NONE", None):
        return None
    syms = [s for s in (ev.get("affected_symbols") or [])
            if s in INDEX_FAMILY]
    if not syms:
        return None
    sym = syms[0]
    fam = INDEX_FAMILY.get(sym, "UNKNOWN")
    sec = SECTOR.get(sym, "UNKNOWN")
    vec = {"PRICE_DIRECTION": ("EXPECTED_UP" if de == "POSITIVE"
                               else "EXPECTED_DOWN" if de == "NEGATIVE"
                               else "UNKNOWN"),
           "SECTOR_CONFIRMATION": ("EXPECTED_CONFIRMATION"
                                   if SECTOR_ETF.get(sec) else "UNKNOWN"),
           "INDEX_CONFIRMATION": ("EXPECTED_CONFIRMATION"
                                  if INDEX_ETF.get(fam) else "UNKNOWN"),
           "RELATIVE_STRENGTH": ("EXPECTED_UP" if de == "POSITIVE"
                                 else "EXPECTED_DOWN"),
           "VOLATILITY_RESPONSE": ("EXPECTED_EXPANSION"
                                   if ev.get("importance") in
                                   ("CRITICAL", "HIGH") else "UNKNOWN")}
    return {"kind": "parallax_expectation",
            "parallax_id": f"PX_{ev['event_id']}",
            "episode_id": ev["event_id"],
            "symbol": sym,
            "sector_etf": SECTOR_ETF.get(sec),
            "index_etf": INDEX_ETF.get(fam),
            "beta_family": fam,
            "event_time": ev.get("event_time"),
            "known_from": ev.get("known_from"),
            "expectation_created_at": ekf,
            "expected_direction": de,
            "expectation_vector": vec,
            "mechanism_basis": list(ev.get("mechanism_hypotheses")
                                    or [])[:3],
            "uncertainty": list(ev.get("uncertainty") or [])[:3],
            "inputs_used": ["catalyst_directional_expectation",
                            "structural_beta_sector_maps"],
            "support_independence": "CORRELATED_SUPPORT" if
            SECTOR_ETF.get(sec) else "UNKNOWN",
            "expectation_contract_sha": ev.get(
                "expectation_contract_sha", "NONE"),
            "sealed_pre_reaction": True,
            "decision_power": AUTHORITY}


# ---------------------------------------------------------- violation

def _signed(bars, kf, mins, close, sign=1.0):
    """Signed return over the window after kf; None if unmeasurable."""
    from datetime import timedelta
    fut = []
    for b in bars:
        t = datetime.fromisoformat(
            b["event_time_utc"].replace("Z", "+00:00"))
        if t > kf and t <= close:
            fut.append((t, b))
    fut.sort()
    if not fut:
        return None, None, None
    ref = fut[0][1]["open"]
    if not ref:
        return None, None, None
    end = min(kf + timedelta(minutes=mins), close)
    w = [(t, b) for t, b in fut if t <= end]
    if not w:
        return None, None, None
    ret = sign * (w[-1][1]["close"] - ref) / ref
    hi = max(sign * (b["high"] - ref) / ref for _, b in w)
    lo = min(sign * (b["low"] - ref) / ref for _, b in w)
    return ret, hi, lo


def measure_violation(exp: dict, *, bars_by_symbol: dict,
                      close_utc, atr: float,
                      horizon_min: int = 60,
                      ledger: Path | None = None) -> dict:
    """Expectation vs reality, every dimension measurable from bars.

    THE FIREWALL: refuses when the expectation was created after the
    measurement window opens -- an expectation formed mid-reaction is
    hindsight wearing a seal.
    """
    kf = datetime.fromisoformat(
        str(exp["known_from"]).replace("Z", "+00:00"))
    if kf.tzinfo is None:
        kf = kf.replace(tzinfo=timezone.utc)
    ekf = str(exp["expectation_created_at"])
    if ekf not in ("NONE",) and ekf > str(exp["known_from"]):
        raise ParallaxViolation(
            "expectation_created_at postdates known_from: an "
            "expectation formed mid-reaction is hindsight wearing a "
            "seal -- NOT_PARALLAX_ELIGIBLE")
    close = (datetime.fromisoformat(str(close_utc)
                                    .replace("Z", "+00:00"))
             if isinstance(close_utc, str) else close_utc)
    if not isinstance(atr, (int, float)) or atr <= 0:
        return {"kind": "parallax_violation",
                "parallax_id": exp["parallax_id"],
                "eligible": False, "why": "ATR NOT_ESTIMABLE"}

    sym = exp["symbol"]
    sret, mfe, mae = _signed(bars_by_symbol.get(sym, []), kf,
                             horizon_min, close)
    if sret is None:
        return {"kind": "parallax_violation",
                "parallax_id": exp["parallax_id"],
                "eligible": False, "why": "no measurable path"}

    de = exp["expected_direction"]
    sign_exp = 1.0 if de == "POSITIVE" else -1.0
    agree_atr = (sign_exp * sret) * (bars_by_symbol[sym][0].get(
        "close", 1) or 1) / atr if atr else 0.0
    # in ATR units of the underlying move relative to expectation
    price0 = next((b["open"] for b in bars_by_symbol[sym]
                   if b.get("open")), None)
    move_atr = (sret * price0 / atr) if price0 else 0.0
    aligned_atr = sign_exp * move_atr

    if aligned_atr >= RELATIVE_FLOOR_ATR:
        vclass = "EXPECTED_REACTION"
    elif aligned_atr <= -RELATIVE_FLOOR_ATR:
        vclass = ("FAILED_POSITIVE_REACTION" if de == "POSITIVE"
                  else "FAILED_NEGATIVE_REACTION")
    else:
        vclass = "NO_IDENTIFIABLE_REACTION"

    # relative / propagation dimensions -- measured, else UNKNOWN
    rel = {}
    for label, etf in (("SECTOR", exp.get("sector_etf")),
                       ("INDEX", exp.get("index_etf"))):
        if not etf or etf == sym:
            rel[label] = "UNKNOWN"
            continue
        eret, _, _ = _signed(bars_by_symbol.get(etf, []), kf,
                             horizon_min, close)
        if eret is None:
            rel[label] = "UNKNOWN"
            continue
        spread = sret - eret
        spread_atr = (spread * price0 / atr) if price0 else 0.0
        if sign_exp * spread_atr <= -RELATIVE_FLOOR_ATR and \
                sign_exp * eret > 0:
            rel[label] = ("NEGATIVE_RELATIVE_DISLOCATION"
                          if de == "POSITIVE"
                          else "POSITIVE_RELATIVE_DISLOCATION")
            if vclass == "EXPECTED_REACTION":
                pass
            else:
                vclass = "RELATIVE_DISLOCATION"
        elif abs(spread_atr) < RELATIVE_FLOOR_ATR:
            rel[label] = "PROPAGATION_CONFIRMED"
        else:
            rel[label] = "PROPAGATION_DIVERGED"

    disagreement_atr = abs(aligned_atr - RELATIVE_FLOOR_ATR) \
        if aligned_atr < RELATIVE_FLOOR_ATR else 0.0
    debt = "NOT_ESTIMABLE"
    if isinstance(disagreement_atr, float):
        debt = "EXTREME"
        for band, name in DEBT_BANDS:
            if disagreement_atr <= band:
                debt = name
                break

    rec = {"kind": "parallax_violation",
           "parallax_id": exp["parallax_id"],
           "episode_id": exp["episode_id"],
           "known_from": exp["known_from"],
           "taxonomy_sha": taxonomy_sha(),
           "symbol": sym, "eligible": True,
           "expected_direction": de,
           "horizon_min": horizon_min,
           "signed_return": round(sret, 6),
           "aligned_move_atr": round(aligned_atr, 4),
           "mfe": round(mfe, 6), "mae": round(mae, 6),
           "violation_class": vclass,
           "relative": rel,
           "expectation_debt": debt,
           "informational_vs_expressible": "INFORMATIONAL_VIOLATION"
           if vclass != "EXPECTED_REACTION" else "NOT_A_VIOLATION",
           "measured_utc": _now(),
           "law": "the violation is a question, not alpha",
           "decision_power": AUTHORITY}
    # write ONLY when a ledger is named: playback and live previews
    # measure without sealing, and a default-write here would let a
    # replay contaminate the canonical prospective record
    if ledger is not None:
        chain_append(ledger, rec)
    return rec


def resolve_debt(violation: dict, *, later_signed_return: float | None,
                 atr: float, price0: float) -> dict:
    """How the dislocation resolved, from LATER path only."""
    if violation.get("violation_class") == "EXPECTED_REACTION":
        res = "ALREADY_PRICED"
    elif later_signed_return is None or not price0:
        res = "UNKNOWN"
    else:
        de = violation["expected_direction"]
        sign_exp = 1.0 if de == "POSITIVE" else -1.0
        later_atr = sign_exp * later_signed_return * price0 / atr
        if later_atr >= RELATIVE_FLOOR_ATR:
            res = "PRICE_CATCHES_UP"
        elif later_atr <= -RELATIVE_FLOOR_ATR:
            res = "EXPECTATION_PROVEN_WRONG"
        else:
            res = "DISLOCATION_PERSISTS"
    return {"kind": "parallax_resolution",
            "parallax_id": violation["parallax_id"],
            "episode_id": violation["episode_id"],
            "resolution_class": res,
            "resolved_utc": _now(),
            "decision_power": AUTHORITY}


# ------------------------------------------------------------ episodes

def episode_accounting(violations: list) -> dict:
    """One event is one episode however many horizons it spans, and a
    same-family cluster in one time bucket is correlated, not five
    experiments.

    THE VOCABULARY IS DELIBERATELY WEAK: event-hour clustering reduces
    obvious pseudoreplication -- an earnings shock at 10:00 and its
    continued reaction at 11:00 can still be ONE information episode,
    so no independence count is reported. Anything stronger than
    NOT_ESTIMABLE would let PARALLAX manufacture sample size, the
    exact defect it exists to prevent.
    """
    episodes = {}
    for v in violations:
        if not v.get("eligible"):
            continue
        episodes.setdefault(v["episode_id"], []).append(v)
    fams = {}
    for eid, vs in episodes.items():
        fam = INDEX_FAMILY.get(vs[0]["symbol"], "UNKNOWN")
        # bucket by EVENT hour, never by measurement hour: a batch
        # post-close pass measures everything in the same minute, and
        # bucketing on that collapsed 29 all-day episodes into one
        # cluster on the first real run -- conservative, but measuring
        # the wrong dimension entirely
        bucket = str(vs[0].get("known_from",
                               vs[0].get("measured_utc", "")))[:13]
        fams.setdefault((fam, bucket), []).append(eid)
    return {"raw_observations": len(violations),
            "episodes": len(episodes),
            "event_hour_clusters": len(fams),
            "independent_episodes": "NOT_ESTIMABLE",
            "law": "event-hour clustering reduces obvious "
                   "pseudoreplication; it does not prove "
                   "independence -- no machinery here can earn an "
                   "independence count yet"}


# ------------------------------------------------------ session pass

def observe_session(*, session: str, close_utc, events: list,
                    load_bars, atr_fn, label: str | None = None,
                    expectations_ledger: Path | None = None,
                    violations_ledger: Path | None = None) -> dict:
    """One full observation pass over a session's sealed events.

    ONE code path for both the prospective post-close pass and
    retrospective commissioning -- the only difference is the label,
    and labeled rows never enter a prospective evidence count.
    Seals THE FULL DENOMINATOR: considered / ineligible-with-why /
    eligible / measured / unmeasurable.
    """
    if label is None:
        # THE EVIDENTIARY VERSIONING FENCE: only today's session may
        # be classified prospectively. Rerunning an old session under
        # current (possibly improved) rules is tomorrow's knowledge
        # wearing yesterday's timestamps -- label it or be refused.
        from apex.ops.timebase import ET
        today = datetime.now(timezone.utc).astimezone(ET) \
            .strftime("%Y-%m-%d")
        if session != today:
            raise ParallaxViolation(
                f"unlabeled pass over {session} on {today}: "
                f"OLD SESSION + CURRENT RULES = "
                f"RETROSPECTIVE_RECLASSIFICATION -- pass an explicit "
                f"label; it can never become prospective evidence")
    exp_led = expectations_ledger or EXPECTATIONS
    vio_led = violations_ledger or VIOLATIONS
    considered = eligible = measured = unmeasurable = 0
    ineligible: dict[str, int] = {}
    violations, classes, debts = [], {}, {}

    import dataclasses
    for ev in events:
        if dataclasses.is_dataclass(ev) and not isinstance(ev, dict):
            ev = dataclasses.asdict(ev)
        considered += 1
        exp = expectation_from_event(ev)
        if exp is None:
            de = ev.get("directional_expectation")
            if de in ("UNKNOWN", None) or \
                    ev.get("expectation_known_from") in ("NONE", None):
                why = "NO_PRE_REACTION_EXPECTATION"
            elif de not in ("POSITIVE", "NEGATIVE"):
                why = "NON_DIRECTIONAL_EXPECTATION"
            else:
                why = "NO_UNIVERSE_SYMBOL"
            ineligible[why] = ineligible.get(why, 0) + 1
            continue
        eligible += 1
        if label:
            exp["commissioning_label"] = label
        chain_append(exp_led, exp)

        syms = {exp["symbol"], exp.get("sector_etf"),
                exp.get("index_etf")} - {None}
        bars = {s: load_bars(s) for s in syms}
        atr = atr_fn(bars.get(exp["symbol"], []))
        v = measure_violation(
            exp, bars_by_symbol=bars, close_utc=close_utc,
            atr=atr if isinstance(atr, (int, float)) else -1,
            ledger=vio_led)
        if not v.get("eligible"):
            unmeasurable += 1
            continue
        measured += 1
        violations.append(v)
        classes[v["violation_class"]] = \
            classes.get(v["violation_class"], 0) + 1
        debts[v["expectation_debt"]] = \
            debts.get(v["expectation_debt"], 0) + 1

    return {"kind": "parallax_session_pass", "session": session,
            "label": label or "PROSPECTIVE",
            "taxonomy_sha": taxonomy_sha(),
            "versioning_law": EVIDENTIARY_VERSIONING_LAW,
            "denominator": {"events_considered": considered,
                            "ineligible": ineligible,
                            "eligible": eligible,
                            "measured": measured,
                            "unmeasurable": unmeasurable},
            "violation_classes": classes,
            "expectation_debt": debts,
            "episode_accounting": episode_accounting(violations),
            "parallax_edge": "NOT_ESTIMABLE",
            "decision_power": AUTHORITY}
