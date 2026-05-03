import gleam/bit_array
import gleam/bytes_tree
import gleam/http.{Get, Post}
import gleam/http/request.{type Request}
import gleam/http/response.{type Response}
import gleam/int
import gleam/erlang/process
import gleam/json
import gleam/option.{type Option, None, Some}
import gleam/result
import gleam/string
import mist.{type Connection, type ResponseData}
import team2form_gleam/codec
import team2form_gleam/env
import team2form_gleam/formation
import team2form_gleam/modes
import team2form_gleam/scoring

const max_body_bytes = 10_485_760
const default_host = "127.0.0.1"
const default_port = 8000
const min_port = 1
const max_port = 65_535

pub fn main() {
  let host = listen_host()
  let port = listen_port()
  let api_key = api_key()

  let assert Ok(_) =
    fn(request) { handle_request(request, api_key) }
    |> mist.new
    |> mist.bind(host)
    |> mist.port(port)
    |> mist.start

  process.sleep_forever()
}

fn api_key() {
  case env.get("API_KEY") {
    Some("") -> panic as "API_KEY must not be empty when set"
    Some(key) -> Some(key)
    None -> None
  }
}

fn listen_host() -> String {
  case env.get("HOST") {
    Some("") -> panic as "HOST must not be empty"
    Some(host) -> host
    None -> default_host
  }
}

fn listen_port() -> Int {
  case env.get("PORT") {
    Some(raw_port) -> parse_port_or_panic(raw_port)
    None -> default_port
  }
}

fn parse_port_or_panic(raw_port: String) -> Int {
  case int.parse(raw_port) {
    Ok(port) -> validate_port_or_panic(port, raw_port)
    Error(Nil) ->
      panic as {
        "PORT must be an integer between "
        <> int.to_string(min_port)
        <> " and "
        <> int.to_string(max_port)
        <> ", got "
        <> string.inspect(raw_port)
      }
  }
}

fn validate_port_or_panic(port: Int, raw_port: String) -> Int {
  let in_range = port >= min_port && port <= max_port

  case in_range {
    True -> port
    False ->
      panic as {
        "PORT must be between "
        <> int.to_string(min_port)
        <> " and "
        <> int.to_string(max_port)
        <> ", got "
        <> string.inspect(raw_port)
      }
  }
}

fn handle_request(
  request: Request(Connection),
  api_key: option.Option(String),
) -> Response(ResponseData) {
  case request.method, request.path_segments(request) {
    Get, ["healthz"] -> health_response()
    _, ["v1", ..] -> handle_api_request(request, api_key)
    _, _ -> error_response(404, "Not found")
  }
}

fn handle_api_request(
  request: Request(Connection),
  api_key: option.Option(String),
) -> Response(ResponseData) {
  case is_authorized(request, api_key) {
    True -> route_api_request(request)
    False -> unauthorized_response()
  }
}

fn route_api_request(request: Request(Connection)) -> Response(ResponseData) {
  case request.method, request.path_segments(request) {
    Get, ["v1", "help"] -> json_response(200, codec.encode_help_info())

    Post, ["v1", "teamQuality"] -> {
      use body <- read_json_body(request)

      quality_from_json(
        body,
        "compat",
        None,
        False,
      )
      |> result_response
    }

    Post, ["v1", "teamFormation"] -> {
      use body <- read_json_body(request)

      form_from_json_with_search_mode(
        body,
        "compat",
        None,
        False,
        "interactive",
        None,
      )
      |> result_response
    }

    _, _ -> error_response(404, "Not found")
  }
}

fn quality_from_json(
  input_json: String,
  mode_name: String,
  preset_name: Option(String),
  normalize_weights: Bool,
) -> Result(String, String) {
  use request <- result.try(codec.decode_team_quality_request(input_json))
  use mode <- result.try(modes.mode_from_string(mode_name))
  use preset <- result.try(parse_preset(preset_name))

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

fn form_from_json_with_search_mode(
  input_json: String,
  mode_name: String,
  preset_name: Option(String),
  normalize_weights: Bool,
  search_mode_name: String,
  max_candidate_teams: Option(Int),
) -> Result(String, String) {
  use request <- result.try(codec.decode_formation_request(input_json))
  use mode <- result.try(modes.mode_from_string(mode_name))
  use preset <- result.try(parse_preset(preset_name))
  use search_mode <-
    result.try(
      formation.parse_search_mode(search_mode_name)
      |> result.map_error(formation.team_formation_error_to_string),
    )
  use response <-
    result.try(
      formation.form_teams_with_search_mode(
        request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        search_mode: search_mode,
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

fn is_authorized(
  request: Request(Connection),
  api_key: option.Option(String),
) -> Bool {
  case api_key {
    None -> True
    Some(key) -> {
      let expected = "Bearer " <> key

      request.get_header(request, "authorization")
      |> result.map(fn(header) { header == expected })
      |> result.unwrap(False)
    }
  }
}

fn read_json_body(
  request: Request(Connection),
  next: fn(String) -> Response(ResponseData),
) -> Response(ResponseData) {
  case mist.read_body(request, max_body_bytes) {
    Ok(read_request) ->
      case bit_array.to_string(read_request.body) {
        Ok(body) -> next(body)
        Error(Nil) -> error_response(400, "Request body must be valid UTF-8")
      }

    Error(mist.ExcessBody) -> error_response(413, "Request body too large")
    Error(mist.MalformedBody) -> error_response(400, "Malformed request body")
  }
}

fn result_response(result: Result(String, String)) -> Response(ResponseData) {
  case result {
    Ok(body) -> json_response(200, body)
    Error(error) -> error_response(400, error)
  }
}

fn health_response() -> Response(ResponseData) {
  let body =
    json.object([#("status", json.string("ok"))])
    |> json.to_string

  json_response(200, body)
}

fn unauthorized_response() -> Response(ResponseData) {
  error_response(401, "Unauthorized")
  |> response.set_header("www-authenticate", "Bearer")
}

fn error_response(status: Int, detail: String) -> Response(ResponseData) {
  let body =
    json.object([#("detail", json.string(detail))])
    |> json.to_string

  json_response(status, body)
}

fn json_response(status: Int, body: String) -> Response(ResponseData) {
  response.new(status)
  |> response.set_header("content-type", "application/json; charset=utf-8")
  |> response.set_body(mist.Bytes(bytes_tree.from_string(body)))
}
