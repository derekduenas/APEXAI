# Model history integrity repair

Base: 3a1c58d81464f3030349ed136316679751052ab0.

Two source-level reproductions preceded this repair: reversing conflicting historical rows changed the retained close from 200 to 100; concatenating history without availability and live bars with availability gave history NaN values, which the simulation excluded.

The builder now tags each input before concatenation. Missing timing columns use the existing, explicit bar-completion assumption; supplied null, invalid or future timing is never replaced by that assumption. Optional historical availability survives the normalizer through its preserved source index. Each row carries its basis and provenance aggregates counts, including MIXED_PER_ROW.

Exactly identical rows collapse. Conflicting observations exclude their entire timestamp and are retained in provenance under CONFLICTING_MODEL_HISTORY_BAR. A missing minute does not become an adjacent return. This deliberately treats disagreements in availability as conflicts too. No conflict is resolved by input order.

Validation: 60 passed across test_model_history_integrity, test_hunter_causal_handoff, test_intelligence_wiring, test_multiverse_wb and test_holdout_capacity. Nine new cases include the real simulation on 390 historical bars plus five receipt-stamped current bars: 393 adjacent returns, SIMULATED_UNCALIBRATED. Transport is synthetic in the new tests. No claim of calibration or profitability follows.

No deployment, paper activation, fee authorization or capital-policy change. CI smoke repair and the commissioned forecast/capital acceptance path remain separate work. This is focused regression evidence, not a full-suite result or a live-host verification.
