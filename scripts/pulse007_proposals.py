"""PULSE-007 -- PROPOSED declaration changes and dispositions. NOT APPLIED.

Everything in this file is a proposal for Astra. No declaration in
apex/pulse/parity.py was changed by PULSE-007, no tolerance in
apex/pulse/mirror.py was relaxed, and the mirror status reported by
MIRROR_RUN_V2 is computed under the ORIGINAL declarations. A proposed
downgrade does not close the original gate.

Writes results/pulse/pulse007/DECLARATION_PROPOSALS_V1.json
"""
import json
import os
import sys

sys.path.insert(0, "/opt/apex-repo")
from apex.pulse.mirror import TOLERANCE_BPS, TOLERANCE_REL     # noqa: E402
from apex.pulse.parity import MATRIX                           # noqa: E402

OUT = "/opt/apex-repo/results/pulse/pulse007/DECLARATION_PROPOSALS_V1.json"

DOC = {
    "kind": "pulse007_declaration_proposals",
    "version": "DECLARATION_PROPOSALS_V1",
    "status": "PROPOSED_ONLY -- nothing here is applied; the mirror status is computed "
              "under the original declarations and the original tolerances",
    "original_tolerances_unchanged": {"TOLERANCE_BPS": TOLERANCE_BPS, "TOLERANCE_REL": TOLERANCE_REL},

    "anchors_repaired_not_redeclared": {
        "fields": ["prior_close", "prior_close_return_bps", "cash_open_return_bps", "overnight_gap_bps"],
        "declaration_before": {f: MATRIX[f]["status"] for f in
                               ("prior_close", "prior_close_return_bps", "cash_open_return_bps", "overnight_gap_bps")},
        "declaration_after": "UNCHANGED -- SEMANTICALLY_EQUIVALENT",
        "why": "these four were not mis-declared. The declaration was right and the historical "
               "feeder was wrong: it selected the previous session's daily bar (ANCHOR-001) and "
               "an extended-hours bar as the cash open (ANCHOR-002). Repairing the selector "
               "made the declaration true rather than moving it."},

    "proposal_1": {
        "id": "MIRROR-TIME-ANCHOR-V2",
        "target": "the mirror comparison method, not a parity declaration",
        "source_level_explanation":
            "a live PULSE packet is stamped with its SCHEDULED slot but composed from the "
            "provider snapshot current at CAPTURE. On 2026-09-01 the quote inside each packet "
            "carries an as_of 1.275-1.669 s after the slot (TDOC: -0.007 s). MIRROR_RUN_V2 "
            "reconstructs at the scheduled slot exactly, so the two sides read the NBBO at two "
            "different instants and the tape moved between them.",
        "measured_discrepancy": {
            "SPY": {"lag_s": 1.669, "nbbo_updates_between": 473},
            "AAOI": {"lag_s": 1.275, "nbbo_updates_between": 36},
            "AAPL": {"lag_s": 1.298, "nbbo_updates_between": 30},
            "AAL": {"lag_s": 1.405, "nbbo_updates_between": 7},
            "TDOC": {"lag_s": -0.007, "nbbo_updates_between": 0},
            "natural_control": "TDOC is the only subject with zero NBBO updates between the two "
                               "instants, and TDOC is the only subject whose full mirror passes."},
        "intended_semantics":
            "reconstruct at the moment the live packet actually observed -- the packet's own "
            "state_complete_time or the as_of of the field being compared -- so the mirror "
            "measures FEEDER parity rather than the composition lag.",
        "evidence_that_it_would_resolve_the_residual":
            "the tape quote at each live packet's own as_of reproduces the live mid, spread_bps, "
            "nbbo_size_imbalance and touch_size EXACTLY on 5 of 5 subjects that had a quote "
            "(QUOTE_RESIDUAL_V1). Same source, same convention, different event: category (a).",
        "consequence_for_historical_feature_eligibility":
            "none by itself. It changes what the mirror measures, not what a historical corpus "
            "may contain. If adopted, the mirror would still have to be re-run and would still "
            "have to pass under the ORIGINAL declarations.",
        "risk_to_state_plainly":
            "moving the comparison instant is exactly the kind of change that can be used to "
            "manufacture a green result. It is offered as a measurement, and the residual it "
            "explains is reported as an OPEN violation until Astra rules.",
        "not_applied": True},

    "proposal_2": {
        "id": "LIVE-ANCHOR-STALENESS-V1",
        "target": "apex/pulse/compose.py -- prior_close quality, a NEW defect found by this brick",
        "source_level_explanation":
            "the composer applies the freshness policy to quotes and trades but not to the "
            "anchor. NKLA's sealed live packet carries prior_close with as_of 2025-02-24 -- a "
            "daily bar over six months old -- flagged VALID, and prior_close_return_bps of "
            "-2869.94 bps derived from it. The vendor snapshot for an inactive name keeps "
            "returning its last known daily bar; PULSE has no rule that says an anchor can be "
            "too old to mean anything.",
        "measured_discrepancy": {"NKLA": {"live_prior_close_as_of": "2025-02-24",
                                          "live_prior_close": 0.2568,
                                          "live_prior_close_return_bps": -2869.94,
                                          "quality_recorded": "VALID"}},
        "intended_semantics":
            "an anchor whose session is not the immediately preceding trading session should be "
            "STALE, with the gap recorded -- the same treatment quotes already get.",
        "consequence_for_historical_feature_eligibility":
            "material. A corpus built from packets like this would contain thousands-of-bps "
            "returns computed against a year-old price, presented as VALID.",
        "scope_note": "this is a LIVE-feeder defect. PULSE-007 repaired the historical feeder; "
                      "changing live composition is outside this brick and is reported, not done.",
        "not_applied": True},

    "live_only_disposition": {
        "status": "DISPOSITION ONLY -- no World Model source permission changed, no corpus built",
        "fields": {
            "ret_1m_bps / ret_5m_bps / ret_10m_bps / ret_15m_bps / ret_30m_bps / ret_60m_bps": {
                "declared": "LIVE_ONLY",
                "observed_in_the_mirror": "LIVE_ONLY on every subject -- the declaration held",
                "why": "these are computed from PULSE's own rolling observation history, which "
                       "exists only where PULSE was running. They are not vendor quantities.",
                "disposition": "EXCLUDE from any A0 historical corpus. They could be rebuilt from "
                               "the minute tape, but that would be a DIFFERENT quantity from the "
                               "live feature, and manufacturing parity is the thing the parity "
                               "matrix exists to prevent."},
            "micro_net_signed_volume / micro_spread_bps_median": {
                "declared": "UNDECLARED in the matrix; observed LIVE_ONLY",
                "disposition": "declare explicitly before any corpus decision; the historical "
                               "factory does not populate deep microstructure today."},
            "catalyst_fact_events_known": {
                "declared": "APPROXIMATE (catalyst_*)",
                "observed": "LIVE_ONLY -- the historical factory passes catalyst=None",
                "disposition": "either wire the catalyst known_from filter into the factory or "
                               "re-declare; today the declaration overstates what history supplies."},
            "opt_state": {
                "declared": "APPROXIMATE (opt_*)",
                "observed": "LIVE_ONLY -- quality differs (live VALID, replay UNKNOWN)",
                "disposition": "same as catalyst: wire or re-declare, do not assume."}},
    },

    "quote_residual_classification": {
        "nbbo_size_imbalance": {"subjects": ["SPY", "AAL", "AAOI", "AAPL"], "category": "a",
                                "declaration_change_proposed": "NONE -- the field is not "
                                "mis-declared; the comparison instants differ (proposal_1)"},
        "spread_bps": {"subjects": ["AAOI"], "category": "a",
                       "declaration_change_proposed": "NONE"},
        "prior_close_return_bps / cash_open_return_bps on AAOI": {
            "category": "a", "why": "both embed the live mid; AAOI's mid moved 7 bps across the "
            "1.275 s composition lag. prior_close itself and overnight_gap_bps -- the two anchor "
            "fields that contain no mid -- match EXACTLY on AAOI.",
            "declaration_change_proposed": "NONE"},
        "NKLA": {"category": "c", "why": "no live two-sided NBBO and no vendor history in the "
                 "lookback; nothing to compare in either direction",
                 "declaration_change_proposed": "NONE -- this is a coverage hole, reported as "
                 "INCOMPLETE by MIRROR_RUN_V2 where the V0 runner reported MIRROR_CONSISTENT"}},
}


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(DOC, open(OUT, "w"), indent=1)
    print("PROPOSED ONLY -- nothing applied. Wrote", OUT)
    for k in ("proposal_1", "proposal_2"):
        print(" ", DOC[k]["id"], "->", DOC[k]["target"])


if __name__ == "__main__":
    main()
