"""WORLD_MODEL_SHADOW_ENGINE_V0 -- research isolation only.

WHAT EXISTS HERE TODAY: an authority contract and a fail-closed data
source boundary. Nothing else. There is no model, no corpus, no
generator, no adapter and no Multiverse, and this package holds no
order, trading or capital authority of any kind.

It is built BEFORE any research capability on purpose. A firewall added
after the first experiment protects nothing -- by then the question is
already whether the result was contaminated, and that question cannot be
answered retrospectively.

Phase 2 is BLOCKED and World Model TRAINING remains FORBIDDEN. This
package is the enforcement of that prohibition, not an exception to it.
"""
from __future__ import annotations

from apex.world_model.authority import (AUTHORITY_DIGEST,
                                        AUTHORITY_VERSION,
                                        WORLD_MODEL_RESEARCH_AUTHORITY_V0,
                                        WorldModelAuthorityViolation,
                                        assert_authority)
from apex.world_model.canonical import (CANONICAL_VERSION,
                                        NumericContractViolation,
                                        canonical_json, content_hash,
                                        strict_float, strict_probability)
from apex.world_model.forecast import (FORECAST_SCHEMA_VERSION, HORIZONS,
                                       ForecastContractViolation,
                                       PredictiveDistribution,
                                       WorldModelForecast)
from apex.world_model.inputs import (INFORMATION_TIERS,
                                     INPUT_SCHEMA_VERSION, Component,
                                     InputContractViolation,
                                     WorldModelInput)
from apex.world_model.nulls import (NULL_CONTRACT, NULL_TYPES,
                                    NullTransformViolation, make_null)
from apex.world_model.worlds import (GENERATOR_VERSION, WORLD_SCHEMA_VERSION,
                                     WORLD_TYPES, GroundTruthLeak,
                                     SyntheticWorld, WorldConfig,
                                     WorldConfigViolation, generate_world)
from apex.world_model.grader import (GRADER_VERSION, NULL_RULE, Z_RULE,
                                     Grade, GradingViolation, grade,
                                     null_rule)
from apex.world_model.models import (M0SyntheticBaseline,
                                     ModelContractViolation, NullBaseline)
from apex.world_model.runs import (RUN_AUTHORITY, ChronologicalSplit,
                                   ModelRun, RunContractViolation)
from apex.world_model.targets import (TARGET_HORIZON, OutcomeRecord,
                                      resolve_target)
from apex.world_model.teststand import (TESTSTAND_VERSION,
                                        control_experiment, run_pipeline)
from apex.world_model.budget import (BUDGET_VERSION, BudgetViolation,
                                     ResearchBudget, wm0d_truth)
from apex.world_model.controls import CONTROL_CONTRACT, ControlViolation
from apex.world_model.inference import (INFERENCE_VERSION, WM_STAT_001,
                                        HAC_LAG, HAC_KERNEL, DM_THRESHOLD,
                                        NON_OVERLAP_VERSION, InferenceViolation,
                                        dm_hac_rule, non_overlap_rule)
from apex.world_model.holdout import (HOLDOUT_VERSION, HOLDOUT_SEEDS,
                                      HOLDOUT_SEED_SET_HASH,
                                      WM_0E_DEVELOPMENT_NULL_SET_V0)
from apex.world_model.bootstrap import (BOOTSTRAP_VERSION, B_REPLICATIONS,
                                        IMPLEMENTATION_HISTORY, required_autocov_lags,
                                        ALPHA, BLOCK_RULE, CALIBRATION_ENVELOPE,
                                        BootstrapViolation, bootstrap_test,
                                        block_length)
from apex.world_model.court_v2 import (COURT_VERSION_V2, MAX_FALSE_POSITIVES_V2,
                                       CourtDefinitionV2, convene_v2,
                                       error_control_v2)
from apex.world_model.controls_r3 import (N3_V1, N3_V1_CONTRACT, N3_V0_STATUS,
                                          P0_V0_STATUS, P0_POWER_LADDER,
                                          P0_V1_SELECTION, n3_v1_dataset,
                                          shadow_world, predeclaration)
from apex.world_model.controls_r4 import (R4_VERSION, EVAL_LADDER, T_MAX,
                                          QUALIFICATION as R4_QUALIFICATION,
                                          r4_world, r4_dataset)
from apex.world_model.controls_r5 import (R5_VERSION, R5_CONTROLS, R5_DEV_SEEDS,
                                          R5_MAX_FP, r5_dataset)
from apex.world_model.teststand import EXECUTED_SPLIT_CONTRACT, executed_split_record
from apex.world_model.court_v1 import (COURT_VERSION_V1, MAX_FALSE_POSITIVES_V1,
                                       CourtDefinitionV1, convene_v1,
                                       error_control_v1)
from apex.world_model.court import (COURT_VERSION, MAX_FALSE_POSITIVES,
                                    NOMINAL_ALPHA, SEED_SET, CourtDefinition,
                                    CourtViolation, convene)
from apex.world_model.quality import (QUALITY_STATES,
                                      QualityContractViolation)
from apex.world_model.sources import (FORBIDDEN_SOURCE_CLASSES,
                                      PERMITTED_SOURCE_CLASSES,
                                      SOURCE_CONTRACT,
                                      SourceAdmissionRefused, admit)

WORLD_MODEL_SHADOW_ENGINE = "WORLD_MODEL_SHADOW_ENGINE_V0"
DECISION_POWER = "NONE_RESEARCH_ISOLATION"
TRAINING_AUTHORIZED = False

__all__ = ["WORLD_MODEL_SHADOW_ENGINE", "DECISION_POWER",
           "BOOTSTRAP_VERSION", "B_REPLICATIONS", "ALPHA", "BLOCK_RULE",
           "IMPLEMENTATION_HISTORY", "required_autocov_lags",
           "N3_V1", "N3_V1_CONTRACT", "N3_V0_STATUS", "P0_V0_STATUS",
           "P0_POWER_LADDER", "P0_V1_SELECTION", "n3_v1_dataset", "shadow_world",
           "R4_VERSION", "EVAL_LADDER", "T_MAX", "R4_QUALIFICATION", "r4_world",
           "R5_VERSION", "R5_CONTROLS", "R5_DEV_SEEDS", "R5_MAX_FP", "r5_dataset",
           "EXECUTED_SPLIT_CONTRACT", "executed_split_record",
           "r4_dataset",
           "predeclaration",
           "CALIBRATION_ENVELOPE", "BootstrapViolation", "bootstrap_test",
           "block_length", "COURT_VERSION_V2", "MAX_FALSE_POSITIVES_V2",
           "CourtDefinitionV2", "convene_v2", "error_control_v2",
           "INFERENCE_VERSION", "WM_STAT_001", "HAC_LAG", "HAC_KERNEL",
           "DM_THRESHOLD", "NON_OVERLAP_VERSION", "InferenceViolation",
           "dm_hac_rule", "non_overlap_rule", "HOLDOUT_VERSION",
           "HOLDOUT_SEEDS", "HOLDOUT_SEED_SET_HASH",
           "WM_0E_DEVELOPMENT_NULL_SET_V0", "COURT_VERSION_V1",
           "MAX_FALSE_POSITIVES_V1", "CourtDefinitionV1", "convene_v1",
           "error_control_v1",
           "TRAINING_AUTHORIZED", "AUTHORITY_VERSION", "AUTHORITY_DIGEST",
           "WORLD_MODEL_RESEARCH_AUTHORITY_V0", "assert_authority",
           "WorldModelAuthorityViolation", "SOURCE_CONTRACT", "admit",
           "SourceAdmissionRefused", "PERMITTED_SOURCE_CLASSES",
           "FORBIDDEN_SOURCE_CLASSES", "CANONICAL_VERSION",
           "canonical_json", "content_hash", "strict_float",
           "strict_probability", "NumericContractViolation",
           "QUALITY_STATES", "QualityContractViolation",
           "INPUT_SCHEMA_VERSION", "INFORMATION_TIERS", "Component",
           "WorldModelInput", "InputContractViolation",
           "FORECAST_SCHEMA_VERSION", "HORIZONS",
           "PredictiveDistribution", "WorldModelForecast",
           "ForecastContractViolation", "WORLD_SCHEMA_VERSION",
           "GENERATOR_VERSION", "WORLD_TYPES", "WorldConfig",
           "WorldConfigViolation", "SyntheticWorld", "generate_world",
           "GroundTruthLeak", "NULL_TYPES", "NULL_CONTRACT",
           "make_null", "NullTransformViolation", "GRADER_VERSION",
           "NULL_RULE", "Z_RULE", "Grade", "GradingViolation", "grade",
           "null_rule", "M0SyntheticBaseline", "NullBaseline",
           "ModelContractViolation", "RUN_AUTHORITY", "ChronologicalSplit",
           "ModelRun", "RunContractViolation", "TARGET_HORIZON",
           "OutcomeRecord", "resolve_target", "TESTSTAND_VERSION",
           "control_experiment", "run_pipeline", "BUDGET_VERSION",
           "BudgetViolation", "ResearchBudget", "wm0d_truth",
           "CONTROL_CONTRACT", "ControlViolation", "COURT_VERSION",
           "MAX_FALSE_POSITIVES", "NOMINAL_ALPHA", "SEED_SET",
           "CourtDefinition", "CourtViolation", "convene"]
