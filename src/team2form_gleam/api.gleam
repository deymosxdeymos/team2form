import gleam/bit_array
import gleam/bytes_tree
import gleam/http.{Get, Post}
import gleam/http/request.{type Request}
import gleam/http/response.{type Response}
import gleam/int
import gleam/erlang/process
import gleam/json
import gleam/option.{None, Some}
import gleam/string
import mist.{type Connection, type ResponseData}
import team2form_gleam
import team2form_gleam/env

const max_body_bytes = 10_485_760
const default_host = "127.0.0.1"
const default_port = 8000
const min_port = 1
const max_port = 65_535

pub fn main() {
  let host = listen_host()
  let port = listen_port()

  let assert Ok(_) =
    handle_request
    |> mist.new
    |> mist.bind(host)
    |> mist.port(port)
    |> mist.start

  process.sleep_forever()
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

fn handle_request(request: Request(Connection)) -> Response(ResponseData) {
  case request.method, request.path_segments(request) {
    Get, ["v1", "help"] -> json_response(200, team2form_gleam.help_info())

    Post, ["v1", "teamQuality"] -> {
      use body <- read_json_body(request)

      team2form_gleam.quality_from_json(
        body,
        "compat",
        None,
        False,
      )
      |> result_response
    }

    Post, ["v1", "teamFormation"] -> {
      use body <- read_json_body(request)

      team2form_gleam.form_from_json_with_search_mode(
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
