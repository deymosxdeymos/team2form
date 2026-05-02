import gleam/dict
import team2form_gleam/models

@external(javascript, "./quality_encode_fast_ffi.mjs", "encode_quality_breakdown_fast")
pub fn encode_quality_breakdown_fast(payload: models.QualityBreakdown) -> String

@external(javascript, "./quality_encode_fast_ffi.mjs", "encode_quality_breakdown_fast_with_weights")
pub fn encode_quality_breakdown_fast_with_weights(
  quality: Float,
  skill_score: Float,
  personality_score: Float,
  task_preference_score: Float,
  social_score: Float,
  alpha: Float,
  beta: Float,
  gamma: Float,
  delta: Float,
  assignments: dict.Dict(String, List(String)),
) -> String
