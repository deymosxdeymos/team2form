-module(team2form_gleam_env_ffi).
-export([get/1]).

get(Name) ->
    case os:getenv(binary_to_list(Name)) of
        false -> none;
        Value -> {some, unicode:characters_to_binary(Value)}
    end.
