import gleam/option.{type Option}
import team2form_gleam/models

@external(javascript, "./quality_decode_fast_ffi.mjs", "decode_team_quality_request_fast")
pub fn decode_team_quality_request_fast(source: String) -> Option(models.TeamQualityRequest)
