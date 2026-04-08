import gleam/option.{type Option, None, Some}
import gleam/result
import team2form_gleam/codec
import team2form_gleam/formation
import team2form_gleam/modes
import team2form_gleam/scoring

pub fn help_info() -> String {
  codec.encode_help_info()
}

pub fn quality_from_json(
  input_json: String,
  mode_name: String,
  preset_name: Option(String),
  normalize_weights: Bool,
) -> Result(String, String) {
  use mode <- result.try(modes.mode_from_string(mode_name))
  use preset <- result.try(parse_preset(preset_name))
  use request <- result.try(codec.decode_team_quality_request(input_json))

  let quality =
    scoring.calculate_team_quality(
      request,
      mode: mode,
      preset: preset,
      normalize_weights: normalize_weights,
      compat_task_preference_default: None,
      compat_social_preference_default: None,
    )

  Ok(codec.encode_quality_breakdown(quality))
}

pub fn form_from_json(
  input_json: String,
  mode_name: String,
  preset_name: Option(String),
  normalize_weights: Bool,
  max_candidate_teams: Option(Int),
) -> Result(String, String) {
  use mode <- result.try(modes.mode_from_string(mode_name))
  use preset <- result.try(parse_preset(preset_name))
  use request <- result.try(codec.decode_formation_request(input_json))
  use response <-
    result.try(
      formation.form_teams(
        request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        max_candidate_teams: max_candidate_teams,
      )
      |> result.map_error(formation.team_formation_error_to_string),
    )

  Ok(codec.encode_teams_response(response))
}

fn parse_preset(name: Option(String)) -> Result(Option(modes.WeightPreset), String) {
  case name {
    Some(raw) -> modes.weight_preset_from_string(raw) |> result.map(Some)
    None -> Ok(None)
  }
}
