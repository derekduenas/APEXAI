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
           "make_null", "NullTransformViolation"]
