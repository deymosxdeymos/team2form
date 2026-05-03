#!/bin/sh
set -eu

erl -noshell \
  -eval '
    RawPort = os:getenv("PORT"),
    Port = case RawPort of false -> "8000"; "" -> "8000"; _ -> RawPort end,
    Url = "http://127.0.0.1:" ++ Port ++ "/healthz",
    application:ensure_all_started(inets),
    case httpc:request(get, {Url, []}, [], []) of
      {ok, {{_, 200, _}, _, _}} -> halt(0);
      _ -> halt(1)
    end.
  '
