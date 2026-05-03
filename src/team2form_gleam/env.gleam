import gleam/option.{type Option}

pub fn get(name: String) -> Option(String) {
  get_env(name)
}

@external(erlang, "team2form_gleam_env_ffi", "get")
fn get_env(name: String) -> Option(String)
