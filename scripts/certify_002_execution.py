#!/usr/bin/env python
"""APEX-002 Step 3 -- execution-path certification. Fourteen registered items.

MEASUREMENT AND INSPECTION ONLY. No forward returns, no IC, no spreads, no
t-statistics, no holdout, no credit, no unlock token, no ledger write.

Each item reports one of:

  CERTIFIED  the production execution path implements the frozen requirement
  MODULE     the signal module conforms, but the gated path does not run it,
             so the requirement is unproven WHERE IT MATTERS
  BLOCKED    cannot be certified because the mechanism does not exist yet
  FAILED     the path contradicts the frozen specification

The MODULE verdict exists because of what this certification found. A test that
examines `apex.features.nsi` proves something about that module. It proves
nothing about `scripts/run_validation.py` unless the pipeline reaches it.
"""

from __future__ import annotations

import ast
import inspect
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apex.audit.execution_path import certify_signal_wiring, module_closure  # noqa: E402
from apex.calendar import build_calendar  # noqa: E402
from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.features import nsi as nsi_mod  # noqa: E402
from apex.universe import build_universe  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
ROOT = Path("data/snapshots/sharadar/current")
OUT = Path("results/002_step3_certification.txt")
B1 = Path("results/002_b1_measurement.json")

NSI_MODULE = "apex.features.nsi"
COMPOSITE_MODULE = "apex.features.composite"
ENTRY = "apex.pipeline"


class Certification:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.items: dict[str, dict] = {}

    def say(self, line: str = "") -> None:
        self.log.append(line)
        print(line, flush=True)

    def item(self, n: int, title: str, verdict: str, evidence: list[str]) -> None:
        self.say(f"--- ITEM {n:>2}. {title}")
        self.say(f"    VERDICT: {verdict}")
        for e in evidence:
            self.say(f"      {e}")
        self.say("")
        self.items[f"item_{n:02d}"] = {
            "title": title, "verdict": verdict, "evidence": evidence,
        }


def main() -> int:  # noqa: C901
    t0 = time.time()
    c = Certification()
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")

    c.say("=" * 78)
    c.say("APEX-002 -- STEP 3 EXECUTION-PATH CERTIFICATION")
    c.say("=" * 78)
    c.say(f"registered experiment : {cfg.get('experiment.id')}")
    c.say(f"protocol              : {cfg.get('experiment.protocol_file')}")
    c.say("scope                 : inspection + measurement only")
    c.say("does NOT              : forward returns, IC, spreads, t-stats,")
    c.say("                        holdout, credit spend, ledger write")
    c.say("")

    src = inspect.getsource(nsi_mod)

    # EXECUTABLE-ONLY view. Scanning raw source matches this module's own
    # docstrings, which state the prohibitions in prose -- ".last()" and
    # "winsorisation" both appear there as explanations of what is forbidden.
    # An earlier version of item 1 read the docstring and reported .last()
    # as present in the code.
    _tree = ast.parse(src)
    _docs = {ast.get_docstring(n, clean=False) for n in ast.walk(_tree)
             if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))}
    import io as _io
    import tokenize as _tk
    executable = "".join(
        tok.string for tok in _tk.generate_tokens(_io.StringIO(src).readline)
        if tok.type != _tk.COMMENT
        and not (tok.type == _tk.STRING and tok.string.strip("\"'") in _docs)
    )

    closure = module_closure(REPO, ENTRY)
    wiring = certify_signal_wiring(closure, NSI_MODULE, COMPOSITE_MODULE)
    wired = not wiring

    # ------------------------------------------------------------------
    # THE GATING QUESTION. Everything else is conditioned on this.
    # ------------------------------------------------------------------
    c.say("=" * 78)
    c.say("GATE -- does the gated path compute the registered signal?")
    c.say("=" * 78)
    c.say(f"  entry point                     : {ENTRY}.build_panel_pipeline")
    c.say(f"  modules reachable               : {len(closure)}")
    c.say(f"  reaches {NSI_MODULE:<24}: {NSI_MODULE in closure}")
    c.say(f"  reaches {COMPOSITE_MODULE:<24}: {COMPOSITE_MODULE in closure}")
    for f in wiring:
        c.say(f"  FINDING: {f}")
    c.say("")
    if not wired:
        c.say("  The signal modules the gated path DOES reach:")
        for m in sorted(x for x in closure if x.startswith("apex.features")):
            c.say(f"    {m}")
        c.say("")

    # === REAL-DATA CONSTRUCTION (same as B1) ==============================
    panel, _ = build_production_panel(
        ROOT, cfg, cfg.get("calendar.lake_start"), cfg.period("in_sample")["end"]
    )
    universe = build_universe(panel, cfg)
    calendar = build_calendar(panel.dates, cfg)
    grid = calendar.grid_formation_dates(
        cfg.period("in_sample")["start"], cfg.period("in_sample")["end"]
    )
    eligible = universe.eligible.loc[grid]

    report = nsi_mod.NSIReport()
    as_filed = nsi_mod.load_as_filed(ROOT, report)
    exclusions = nsi_mod.load_exclusions(ROOT)
    t2s = dict(zip(panel.meta["ticker"], panel.meta.index))
    known_from = pd.DataFrame(pd.NaT, index=grid, columns=panel.securities,
                              dtype="datetime64[ns]")
    nsi = nsi_mod.build_nsi_panel(as_filed, exclusions, t2s, grid,
                                  panel.securities, report,
                                  known_from_out=known_from)
    ranks = nsi_mod.rank_ascending(nsi, eligible,
                                   cfg.get("evaluation.rank_tie_method"))
    c.say(f"[{time.time()-t0:6.0f}s] real-data construction complete")
    c.say("")
    c.say("=" * 78)
    c.say("REGISTERED ITEMS")
    c.say("=" * 78)

    def mod_or(v: str) -> str:
        """A module-level pass is not a path-level pass when nothing runs it.

        Downgrades CERTIFIED to MODULE only. A FAILED verdict must survive:
        an earlier version returned "MODULE" for every item when the path was
        unwired, which would have masked genuine conformance failures behind
        the wiring finding.
        """
        return v if (wired or v != "CERTIFIED") else "MODULE"

    # --- 1. as-filed earliest filing ------------------------------------
    tree = _tree
    calls_first = ".first()" in executable
    calls_last = ".last()" in executable
    dupes = as_filed.duplicated(["ticker", "reportperiod"]).sum()
    c.item(1, "SF1 as-filed, earliest filing per (ticker, reportperiod)",
           mod_or("CERTIFIED" if calls_first and not calls_last and dupes == 0 else "FAILED"),
           [f".first() present (executable code) : {calls_first}",
            f".last() absent  (executable code) : {not calls_last}",
            f".last() appears in prose only     : "
            f"{'.last()' in src and '.last()' not in executable}",
            f"ARQ rows in             : {report.raw_arq_rows:,}",
            f"revisions dropped       : {report.dropped_revisions:,}",
            f"as-filed rows out       : {report.as_filed_rows:,}",
            f"duplicate (ticker,period): {int(dupes)}   (must be 0)"])

    # --- 2. filing_date <= formation_date -------------------------------
    present = eligible & nsi.notna()
    pop = present.to_numpy()
    kf = known_from.to_numpy()
    formation = np.repeat(known_from.index.to_numpy()[:, None], known_from.shape[1], axis=1)
    violations = int((kf[pop] > formation[pop]).sum())
    missing_kf = int(pd.isna(kf[pop]).sum())
    total = int(pop.sum())
    c.item(2, "Admission only where filing_date <= formation_date",
           mod_or("CERTIFIED" if violations == 0 and missing_kf == 0 else "FAILED"),
           [f"populated observations  : {total:,}",
            f"PIT violations          : {violations}   (must be 0)",
            f"missing knowability date: {missing_kf}   (must be 0)",
            f"impossible filings dropped at load: {report.dropped_impossible_filing:,}"])

    # --- 3. the formula --------------------------------------------------
    # The tokenizer join drops original whitespace, so the literal must be
    # matched whitespace-normalised. Comparing the spaced form directly
    # reported a false FAILED.
    _squeeze = lambda t: "".join(t.split())  # noqa: E731
    log_ratio = _squeeze("np.log(shares[i] / shares[j])") in _squeeze(executable)
    c.item(3, "NSI = ln(S_t / S_t-4q)", mod_or("CERTIFIED" if log_ratio else "FAILED"),
           [f"literal log-ratio in executable code : {log_ratio}",
            f"shares column              : {nsi_mod.SHARES!r}",
            f"dimension filter           : {nsi_mod.ARQ!r}"])

    # --- 4. twelve-month window -----------------------------------------
    c.item(4, "Twelve-month window exactly as registered",
           mod_or("CERTIFIED" if (nsi_mod.WINDOW_QUARTERS == 4
                                  and nsi_mod.MIN_WINDOW_DAYS == 270
                                  and nsi_mod.MAX_WINDOW_DAYS == 460) else "FAILED"),
           [f"WINDOW_QUARTERS  : {nsi_mod.WINDOW_QUARTERS}   (registered 4)",
            f"MIN_WINDOW_DAYS  : {nsi_mod.MIN_WINDOW_DAYS} (registered 270)",
            f"MAX_WINDOW_DAYS  : {nsi_mod.MAX_WINDOW_DAYS} (registered 460)"])

    # --- 5. frozen exclusion set ----------------------------------------
    expected = {"spinoff", "spunofffrom", "spinoffdividend", "acquisitionby",
                "acquisitionof", "mergerto", "mergerfrom", "conversion",
                "recapitalization", "recapitalisation"}
    actual = set(nsi_mod.EXCLUDING_ACTIONS)
    splits = {a for a in actual if "split" in a}
    c.item(5, "Frozen corporate-action exclusion set",
           mod_or("CERTIFIED" if actual == expected and not splits else "FAILED"),
           [f"set matches frozen      : {actual == expected}",
            f"split actions absent    : {not splits}  (rebasing already removed them)",
            f"pairs excluded          : {report.excluded_corporate_action:,}",
            f"exclusion rate          : {report.excluded_corporate_action/(report.excluded_corporate_action+report.computed_observations):.4%}"]
           + ([f"UNEXPECTED: {sorted(actual ^ expected)}"] if actual != expected else []))

    # --- 6. no transformation -------------------------------------------
    banned = ("clip(", "winsor", "rolling(", "ewm(", ".quantile(", "fillna(",
              "zscore", "z_score", "standardi")
    code = executable
    found = [b for b in banned if b in code]
    path_transforms = []
    if COMPOSITE_MODULE in closure:
        comp = (REPO / "apex/features/composite.py").read_text()
        path_transforms = [b for b in ("winsorise", "zscore", "percentile_rank")
                           if f"def {b}" in comp]
    c.item(6, "No winsorization, clipping, smoothing, z-scoring, transformation",
           "FAILED" if path_transforms else mod_or("CERTIFIED"),
           [f"banned constructs in {NSI_MODULE}: {found or 'none'}"]
           + ([f"BUT the gated path runs {COMPOSITE_MODULE}, which defines: "
               f"{path_transforms}",
               f"  config composite.winsorize_lower = {cfg.get('composite.winsorize_lower')}",
               f"  config composite.winsorize_upper = {cfg.get('composite.winsorize_upper')}",
               "  the executed path therefore DOES winsorise and z-score"]
              if path_transforms else []))

    # --- 7. eligibility before ranking ----------------------------------
    rank_src = inspect.getsource(nsi_mod.rank_ascending)
    ranked_ineligible = int((ranks.notna() & ~eligible).to_numpy().sum())
    c.item(7, "Eligibility applied before ranking",
           mod_or("CERTIFIED" if ranked_ineligible == 0 else "FAILED"),
           [f"nsi.where(eligible) precedes rank : {'nsi.where(eligible)' in rank_src}",
            f"ranked-but-ineligible cells       : {ranked_ineligible}   (must be 0)"])

    # --- 8. missing NSI excluded, never filled --------------------------
    missing_but_ranked = int((ranks.notna() & nsi.isna()).to_numpy().sum())
    c.item(8, "Missing NSI = exclude, never fill",
           mod_or("CERTIFIED" if missing_but_ranked == 0 and "fillna" not in code else "FAILED"),
           [f"fillna/interpolate absent  : {'fillna(' not in code}",
            f"ranked with missing NSI    : {missing_but_ranked}   (must be 0)",
            f"eligible without NSI (excluded, not filled): "
            f"{int((eligible & nsi.isna()).to_numpy().sum()):,}"])

    # --- 9. ascending rank, deterministic ties --------------------------
    tie_method = cfg.get("evaluation.rank_tie_method")
    stacked_n = nsi.where(present).stack()
    lo, hi = stacked_n.idxmin(), stacked_n.idxmax()
    rank_lo, rank_hi = ranks.loc[lo], ranks.loc[hi]
    ranks_b = nsi_mod.rank_ascending(nsi, eligible, tie_method)
    identical = ranks.equals(ranks_b)
    c.item(9, "Ascending NSI ranking with deterministic C10 tie handling",
           mod_or("CERTIFIED" if rank_lo < rank_hi and identical
                  and tie_method == "first" else "FAILED"),
           [f"ascending=True in source : {'ascending=True' in rank_src}",
            f"tie method (C10)         : {tie_method!r}",
            f"lowest NSI  {stacked_n.min():+.6f} -> pct rank {rank_lo:.8f}",
            f"highest NSI {stacked_n.max():+.6f} -> pct rank {rank_hi:.8f}",
            f"lowest ranks first       : {rank_lo < rank_hi}",
            f"recomputation identical  : {identical}"])

    # --- 10. equal-count deciles ----------------------------------------
    has_decile = any("decile" in n.name for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef))
    c.item(10, "Mechanical percentile conversion only as registered deciles",
           "BLOCKED",
           [f"decile mechanism in {NSI_MODULE}: {has_decile}",
            "the only equal-count decile mechanism in the repo is",
            f"  {COMPOSITE_MODULE}.assign_deciles -- APEX-001 machinery",
            "using it would satisfy item 10 and violate item 11;",
            "#002 has no decile mechanism of its own to certify"])

    # --- 11. no APEX-001 machinery --------------------------------------
    refs = [b for b in ("APEX-001", "Experiment-001", "build_scores", "composite")
            if b in executable]
    c.item(11, "No calls into APEX-001 scoring/composite machinery",
           "FAILED" if COMPOSITE_MODULE in closure else "CERTIFIED",
           [f"references in {NSI_MODULE} : {refs or 'none'}  (module is clean)",
            f"but {ENTRY} reaches {COMPOSITE_MODULE}: {COMPOSITE_MODULE in closure}",
            f"and calls build_scores    : "
            f"{'build_scores(' in (REPO/'apex/pipeline.py').read_text()}"])

    # --- 12. per-date set equality --------------------------------------
    try:
        align = nsi_mod.assert_cross_section_alignment(ranks, nsi, eligible)
        v12, ev12 = mod_or("CERTIFIED"), [
            f"dates checked        : {align['dates_checked']:,}",
            f"ranked security-dates: {align['ranked_security_dates']:,}",
            f"alignment            : {align['alignment']}"]
    except nsi_mod.CrossSectionMisaligned as exc:
        v12, ev12 = "FAILED", [str(exc)]
    c.item(12, "Per-date ranked set == {eligible AND NSI-present}", v12, ev12)

    # --- 13. no duplicate (security_id, date) ---------------------------
    dup_cols = int(nsi.columns.duplicated().sum())
    dup_rows = int(nsi.index.duplicated().sum())
    c.item(13, "No duplicate (security_id, date) observations",
           mod_or("CERTIFIED" if dup_cols == 0 and dup_rows == 0 else "FAILED"),
           [f"duplicate security_id columns : {dup_cols}   (must be 0)",
            f"duplicate date rows           : {dup_rows}   (must be 0)",
            f"panel shape                   : {nsi.shape[0]:,} x {nsi.shape[1]:,}",
            f"index unique+monotonic        : {nsi.index.is_unique and nsi.index.is_monotonic_increasing}"])

    # --- 14. deterministic serialization --------------------------------
    dec = int(cfg.get("determinism.float_output_decimals"))
    b1 = json.loads(B1.read_text()) if B1.exists() else {}
    keys_sorted = list(b1.keys()) == sorted(b1.keys())
    cols_sorted = bool(nsi.columns.is_monotonic_increasing)
    c.item(14, "Deterministic serialization: 12 decimals, explicit column order, sorted keys",
           mod_or("CERTIFIED" if dec == 12 and keys_sorted and cols_sorted else "FAILED"),
           [f"determinism.float_output_decimals : {dec}   (registered 12)",
            f"B1 JSON keys sorted               : {keys_sorted}",
            f"security columns sorted           : {cols_sorted}",
            f"date index sorted                 : {nsi.index.is_monotonic_increasing}",
            "NOTE: certifies the B1/module surface. The gated path emits no",
            "      #002 artifact to serialize."])

    # === B1 CROSS-CHECK ==================================================
    c.say("=" * 78)
    c.say("B1 ANCHOR CROSS-CHECK (reproduction, not reinterpretation)")
    c.say("=" * 78)
    vals = nsi.where(present).stack().dropna()
    if b1:
        prior = b1.get("nsi_distribution", {})
        for k, now in (("p1", vals.quantile(.01)), ("p25", vals.quantile(.25)),
                       ("p50", vals.quantile(.50)), ("p75", vals.quantile(.75)),
                       ("p99", vals.quantile(.99))):
            was = prior.get(k)
            match = was is not None and abs(was - now) < 1e-12
            c.say(f"  {k:<4} B1 {was:+.6f}   now {now:+.6f}   {'MATCH' if match else 'DIFFERS'}")
        c.say(f"  observations  B1 {prior.get('observations'):,}   now {len(vals):,}")
    c.say("")

    # === SUMMARY =========================================================
    tally: dict[str, int] = {}
    for v in c.items.values():
        tally[v["verdict"]] = tally.get(v["verdict"], 0) + 1
    c.say("=" * 78)
    c.say("CERTIFICATION SUMMARY")
    c.say("=" * 78)
    for verdict in ("CERTIFIED", "MODULE", "BLOCKED", "FAILED"):
        if verdict in tally:
            c.say(f"  {verdict:<10} {tally[verdict]:>2}")
    c.say("")
    blocking = [k for k, v in c.items.items() if v["verdict"] == "FAILED"]
    if blocking or not wired:
        c.say("  RESULT: NOT CERTIFIED")
        c.say("  The gated execution path does not implement APEX-002.")
        c.say("  No validation unlock. Credit 2 must not be spent.")
    else:
        c.say("  RESULT: CERTIFIED")
    c.say("=" * 78)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(c.log) + "\n")
    Path("results/002_step3_certification.json").write_text(
        json.dumps({"wired": wired, "wiring_findings": wiring, **c.items},
                   sort_keys=True, indent=2) + "\n")
    print(f"\n[{time.time()-t0:6.0f}s] wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
