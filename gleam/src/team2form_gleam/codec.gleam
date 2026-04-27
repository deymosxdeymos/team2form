import gleam/dict
import gleam/dynamic/decode
import gleam/int
import gleam/json
import gleam/list
import gleam/option.{None, Some}
import gleam/result
import gleam/string
import team2form_gleam/models
import team2form_gleam/quality_decode_fast

fn number_decoder() -> decode.Decoder(Float) {
  decode.one_of(
    decode.float,
    or: [decode.map(decode.int, int.to_float)],
  )
}

fn bounded_float_decoder(
  minimum: Float,
  maximum: Float,
  expected: String,
) -> decode.Decoder(Float) {
  decode.then(number_decoder(), fn(value) {
    case value >=. minimum && value <=. maximum {
      True -> decode.success(value)
      False -> decode.failure(0.0, expected: expected)
    }
  })
}

fn at_least_float_decoder(
  minimum: Float,
  expected: String,
) -> decode.Decoder(Float) {
  decode.then(number_decoder(), fn(value) {
    case value >=. minimum {
      True -> decode.success(value)
      False -> decode.failure(0.0, expected: expected)
    }
  })
}

fn non_empty_string_decoder(expected: String) -> decode.Decoder(String) {
  decode.then(decode.string, fn(value) {
    case value {
      "" -> decode.failure("", expected: expected)
      _ -> decode.success(value)
    }
  })
}

fn list_min_length_decoder(
  of inner: decode.Decoder(a),
  min_length min_length: Int,
  expected expected: String,
) -> decode.Decoder(List(a)) {
  decode.then(decode.list(of: inner), fn(values) {
    case list_has_min_length(values, min_length) {
      True -> decode.success(values)
      False -> decode.failure([], expected: expected)
    }
  })
}

fn list_has_min_length(values: List(a), min_length: Int) -> Bool {
  case min_length <= 0 {
    True -> True

    False ->
      case values {
        [] -> False
        [_, ..rest] -> list_has_min_length(rest, min_length - 1)
      }
  }
}

fn positive_int_decoder(minimum: Int, expected: String) -> decode.Decoder(Int) {
  decode.then(decode.int, fn(value) {
    case value >= minimum {
      True -> decode.success(value)
      False -> decode.failure(0, expected: expected)
    }
  })
}

fn gender_decoder() -> decode.Decoder(models.Gender) {
  decode.then(decode.string, fn(value) {
    case models.gender_from_string(value) {
      Ok(gender) -> decode.success(gender)
      Error(message) -> decode.failure(models.Female, expected: message)
    }
  })
}

fn personality_decoder() -> decode.Decoder(models.Personality) {
  use ei <- decode.field("ei", bounded_float_decoder(-1.0, 1.0, "Personality.ei"))
  use sn <- decode.field("sn", bounded_float_decoder(-1.0, 1.0, "Personality.sn"))
  use tf <- decode.field("tf", bounded_float_decoder(-1.0, 1.0, "Personality.tf"))
  use pj <- decode.field("pj", bounded_float_decoder(-1.0, 1.0, "Personality.pj"))
  decode.success(models.Personality(ei: ei, sn: sn, tf: tf, pj: pj))
}

fn person_skill_decoder() -> decode.Decoder(models.PersonSkill) {
  use id <- decode.field("id", non_empty_string_decoder("PersonSkill.id"))
  use level <- decode.field("level", bounded_float_decoder(0.0, 1.0, "PersonSkill.level"))
  decode.success(models.PersonSkill(id: id, level: level))
}

fn person_preference_decoder() -> decode.Decoder(models.PersonPreference) {
  use person_id <- decode.field("personId", non_empty_string_decoder("PersonPreference.personId"))
  use preference <-
    decode.field(
      "preference",
      bounded_float_decoder(0.0, 1.0, "PersonPreference.preference"),
    )
  decode.success(models.PersonPreference(person_id: person_id, preference: preference))
}

fn person_decoder() -> decode.Decoder(models.Person) {
  use id <- decode.field("id", non_empty_string_decoder("Person.id"))
  use gender <- decode.optional_field("gender", None, decode.optional(gender_decoder()))
  use personality <- decode.field("personality", personality_decoder())
  use skills <- decode.optional_field("skills", [], decode.list(of: person_skill_decoder()))
  use preferences <-
    decode.optional_field(
      "preferences",
      None,
      decode.optional(decode.list(of: person_preference_decoder())),
    )

  decode.success(
    models.Person(
      id: id,
      gender: gender,
      personality: personality,
      skills: skills,
      preferences: preferences,
    ),
  )
}

fn task_skill_decoder() -> decode.Decoder(models.TaskSkill) {
  use id <- decode.field("id", non_empty_string_decoder("TaskSkill.id"))
  use level <- decode.field("level", bounded_float_decoder(0.0, 1.0, "TaskSkill.level"))
  use importance <- decode.field("importance", at_least_float_decoder(1.0, "TaskSkill.importance"))
  decode.success(models.TaskSkill(id: id, level: level, importance: importance))
}

fn task_preference_decoder() -> decode.Decoder(models.TaskPreference) {
  use person_id <- decode.field("personId", non_empty_string_decoder("TaskPreference.personId"))
  use preference <-
    decode.field(
      "preference",
      bounded_float_decoder(0.0, 1.0, "TaskPreference.preference"),
    )
  decode.success(models.TaskPreference(person_id: person_id, preference: preference))
}

fn task_decoder() -> decode.Decoder(models.Task) {
  use id <- decode.field("id", non_empty_string_decoder("Task.id"))
  use team_size <- decode.field("teamSize", positive_int_decoder(2, "Task.teamSize"))
  use skills <- decode.field("skills", list_min_length_decoder(of: task_skill_decoder(), min_length: 1, expected: "Task.skills"))
  use preferences <-
    decode.optional_field(
      "preferences",
      None,
      decode.optional(decode.list(of: task_preference_decoder())),
    )

  decode.success(
    models.Task(
      id: id,
      team_size: team_size,
      skills: skills,
      preferences: preferences,
    ),
  )
}

fn similarity_decoder() -> decode.Decoder(models.Similarity) {
  use source_id <- decode.field("sourceId", non_empty_string_decoder("Similarity.sourceId"))
  use target_id <- decode.field("targetId", non_empty_string_decoder("Similarity.targetId"))
  use similarity <-
    decode.field(
      "similarity",
      bounded_float_decoder(0.0, 1.0, "Similarity.similarity"),
    )

  decode.success(
    models.Similarity(
      source_id: source_id,
      target_id: target_id,
      similarity: similarity,
    ),
  )
}

fn team_member_decoder() -> decode.Decoder(models.TeamMember) {
  use id <- decode.field("id", non_empty_string_decoder("TeamMember.id"))
  use gender <- decode.optional_field("gender", None, decode.optional(gender_decoder()))
  use personality <- decode.field("personality", personality_decoder())
  use skills <- decode.optional_field("skills", [], decode.list(of: person_skill_decoder()))
  use preferences <-
    decode.optional_field(
      "preferences",
      None,
      decode.optional(decode.list(of: person_preference_decoder())),
    )
  use task_preference <-
    decode.optional_field(
      "taskPreference",
      None,
      decode.optional(bounded_float_decoder(0.0, 1.0, "TeamMember.taskPreference")),
    )

  decode.success(
    models.TeamMember(
      id: id,
      gender: gender,
      personality: personality,
      skills: skills,
      preferences: preferences,
      task_preference: task_preference,
    ),
  )
}

fn formation_request_decoder() -> decode.Decoder(models.FormationRequest) {
  use people <- decode.field("people", list_min_length_decoder(of: person_decoder(), min_length: 2, expected: "FormationRequest.people"))
  use tasks <- decode.field("tasks", list_min_length_decoder(of: task_decoder(), min_length: 1, expected: "FormationRequest.tasks"))
  use init_random <- decode.optional_field("initRandom", False, decode.bool)
  use alpha <- decode.optional_field("alpha", None, decode.optional(bounded_float_decoder(0.0, 1.0, "FormationRequest.alpha")))
  use beta <- decode.optional_field("beta", None, decode.optional(bounded_float_decoder(0.0, 1.0, "FormationRequest.beta")))
  use gamma <- decode.optional_field("gamma", None, decode.optional(bounded_float_decoder(0.0, 1.0, "FormationRequest.gamma")))
  use delta <- decode.optional_field("delta", None, decode.optional(bounded_float_decoder(0.0, 1.0, "FormationRequest.delta")))
  use similarities <-
    decode.optional_field(
      "similarities",
      None,
      decode.optional(decode.list(of: similarity_decoder())),
    )

  decode.success(
    models.FormationRequest(
      people: people,
      tasks: tasks,
      init_random: init_random,
      alpha: alpha,
      beta: beta,
      gamma: gamma,
      delta: delta,
      similarities: similarities,
    ),
  )
}

fn team_quality_request_decoder() -> decode.Decoder(models.TeamQualityRequest) {
  use task_skills <- decode.field("taskSkills", list_min_length_decoder(of: task_skill_decoder(), min_length: 1, expected: "TeamQualityRequest.taskSkills"))
  use team <- decode.field("team", list_min_length_decoder(of: team_member_decoder(), min_length: 2, expected: "TeamQualityRequest.team"))
  use alpha <- decode.optional_field("alpha", None, decode.optional(bounded_float_decoder(0.0, 1.0, "TeamQualityRequest.alpha")))
  use beta <- decode.optional_field("beta", None, decode.optional(bounded_float_decoder(0.0, 1.0, "TeamQualityRequest.beta")))
  use gamma <- decode.optional_field("gamma", None, decode.optional(bounded_float_decoder(0.0, 1.0, "TeamQualityRequest.gamma")))
  use delta <- decode.optional_field("delta", None, decode.optional(bounded_float_decoder(0.0, 1.0, "TeamQualityRequest.delta")))
  use similarities <-
    decode.optional_field(
      "similarities",
      None,
      decode.optional(decode.list(of: similarity_decoder())),
    )

  decode.success(
    models.TeamQualityRequest(
      task_skills: task_skills,
      team: team,
      alpha: alpha,
      beta: beta,
      gamma: gamma,
      delta: delta,
      similarities: similarities,
    ),
  )
}

fn parse_json(source: String, decoder: decode.Decoder(a)) -> Result(a, String) {
  case json.parse(from: source, using: decoder) {
    Ok(value) -> Ok(value)
    Error(error) -> Error("Invalid JSON payload: " <> string.inspect(error))
  }
}

pub fn decode_formation_request(source: String) -> Result(models.FormationRequest, String) {
  use request <- result.try(parse_json(source, formation_request_decoder()))
  case models.validate_formation_request(request) {
    Ok(valid) -> Ok(valid)
    Error(validation_error) ->
      Error(models.validation_error_to_string(validation_error))
  }
}

pub fn decode_team_quality_request(source: String) -> Result(models.TeamQualityRequest, String) {
  let decoded_request =
    case quality_decode_fast.decode_team_quality_request_fast(source) {
      Some(request) -> Ok(request)
      None -> parse_json(source, team_quality_request_decoder())
    }

  use request <- result.try(decoded_request)
  case models.validate_team_quality_request(request) {
    Ok(valid) -> Ok(valid)
    Error(validation_error) ->
      Error(models.validation_error_to_string(validation_error))
  }
}

fn encode_string_list(values: List(String)) -> json.Json {
  json.array(from: values, of: json.string)
}

fn encode_assignments(assignments: dict.Dict(String, List(String))) -> json.Json {
  assignments
  |> dict.to_list
  |> list.map(fn(entry) {
    let #(person_id, skill_ids) = entry
    #(person_id, encode_string_list(skill_ids))
  })
  |> json.object
}

pub fn encode_quality_breakdown(payload: models.QualityBreakdown) -> String {
  json.object([
    #("quality", json.float(payload.quality)),
    #("skillScore", json.float(payload.skill_score)),
    #("personalityScore", json.float(payload.personality_score)),
    #("taskPreferenceScore", json.float(payload.task_preference_score)),
    #("socialScore", json.float(payload.social_score)),
    #(
      "weights",
      payload.weights
      |> dict.to_list
      |> list.map(fn(entry) {
        let #(name, value) = entry
        #(name, json.float(value))
      })
      |> json.object,
    ),
    #("assignments", encode_assignments(payload.assignments)),
  ])
  |> json.to_string
}

fn encode_assigned_person(person: models.AssignedPerson) -> json.Json {
  json.object([
    #("id", json.string(person.id)),
    #("skillIds", encode_string_list(person.skill_ids)),
  ])
}

fn encode_team_result(team: models.TeamResult) -> json.Json {
  json.object([
    #("taskId", json.string(team.task_id)),
    #("people", json.array(from: team.people, of: encode_assigned_person)),
    #("quality", json.float(team.quality)),
  ])
}

pub fn encode_teams_response(payload: models.TeamsResponse) -> String {
  json.object([
    #("teams", json.array(from: payload.teams, of: encode_team_result)),
  ])
  |> json.to_string
}

pub fn encode_help_info() -> String {
  json.object([
    #("name", json.string("Edu2com")),
    #("version", json.string("0.1.0")),
  ])
  |> json.to_string
}
