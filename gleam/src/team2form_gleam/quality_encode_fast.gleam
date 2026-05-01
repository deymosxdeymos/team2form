import team2form_gleam/models

@external(javascript, "./quality_encode_fast_ffi.mjs", "encode_quality_breakdown_fast")
pub fn encode_quality_breakdown_fast(payload: models.QualityBreakdown) -> String
