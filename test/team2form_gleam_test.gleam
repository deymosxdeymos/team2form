import gleam/option.{None, Some}
import gleam/string
import gleeunit
import team2form_gleam

pub fn main() -> Nil {
  gleeunit.main()
}

pub fn quality_example_test() {
  let payload =
    "{\"taskSkills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1},{\"id\":\"s2\",\"level\":1.0,\"importance\":1}],\"team\":[{\"id\":\"a\",\"gender\":\"MALE\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s1\",\"level\":1.0}],\"preferences\":[{\"personId\":\"a\",\"preference\":1.0},{\"personId\":\"b\",\"preference\":0.5}],\"taskPreference\":1.0},{\"id\":\"b\",\"gender\":\"FEMALE\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s2\",\"level\":1.0}],\"preferences\":[{\"personId\":\"a\",\"preference\":0.5},{\"personId\":\"b\",\"preference\":1.0}],\"taskPreference\":1.0}]}"

  let result =
    team2form_gleam.quality_from_json(
      payload,
      "compat",
      Some("live_compat"),
      False,
    )

  let output = case result {
    Ok(json) -> json
    Error(reason) ->
      panic as { "Expected Ok quality output, got Error: " <> reason }
  }

  assert string.contains(does: output, contain: "\"quality\":0.6725")
  assert string.contains(does: output, contain: "\"skillScore\":1")
}

pub fn form_rejects_duplicate_person_ids_test() {
  let payload =
    "{\"people\":[{\"id\":\"dup\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"dup\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]}],\"tasks\":[{\"id\":\"t1\",\"teamSize\":2,\"skills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1}]}],\"initRandom\":false}"

  let result =
    team2form_gleam.form_from_json(payload, "compat", None, False, None)

  let error = case result {
    Ok(output) ->
      panic as { "Expected duplicate-id validation error, got Ok: " <> output }
    Error(reason) -> reason
  }

  assert string.contains(does: error, contain: "people ids must be unique")
}

pub fn overfull_compat_assignment_test() {
  let payload =
    "{\"taskSkills\":[{\"id\":\"s0\",\"level\":1.0,\"importance\":1},{\"id\":\"s2\",\"level\":1.0,\"importance\":1}],\"team\":[{\"id\":\"a\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s0\",\"level\":0.3}],\"preferences\":[{\"personId\":\"a\",\"preference\":1.0}]},{\"id\":\"b\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s2\",\"level\":0.43}],\"preferences\":[{\"personId\":\"b\",\"preference\":1.0}]},{\"id\":\"c\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s2\",\"level\":0.73}],\"preferences\":[{\"personId\":\"c\",\"preference\":1.0}]}],\"alpha\":1.0,\"beta\":0.0,\"gamma\":0.0,\"delta\":0.0}"

  let result = team2form_gleam.quality_from_json(payload, "compat", None, False)

  let output = case result {
    Ok(json) -> json
    Error(reason) ->
      panic as {
        "Expected overfull compat quality output, got Error: " <> reason
      }
  }

  assert string.contains(does: output, contain: "\"a\":[\"s0\"]")
  assert string.contains(does: output, contain: "\"b\":[\"s2\"]")
  assert string.contains(does: output, contain: "\"c\":[\"s2\"]")
}

pub fn exact_form_keeps_complementary_specialists_test() {
  let payload =
    "{\"people\":[{\"id\":\"p0\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"sA\",\"level\":1.0},{\"id\":\"sB\",\"level\":1.0}]},{\"id\":\"p1\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"sD\",\"level\":1.0}]},{\"id\":\"p2\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"sC\",\"level\":1.0}]},{\"id\":\"p3\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"sA\",\"level\":0.9}]}],\"tasks\":[{\"id\":\"first\",\"teamSize\":2,\"skills\":[{\"id\":\"sA\",\"level\":1.0,\"importance\":1},{\"id\":\"sD\",\"level\":1.0,\"importance\":1}]},{\"id\":\"pair\",\"teamSize\":2,\"skills\":[{\"id\":\"sB\",\"level\":1.0,\"importance\":1},{\"id\":\"sC\",\"level\":1.0,\"importance\":1}]}],\"alpha\":1.0,\"beta\":0.0,\"gamma\":0.0,\"delta\":0.0,\"initRandom\":false}"

  let result =
    team2form_gleam.form_from_json(payload, "compat", None, False, None)

  let output = case result {
    Ok(json) -> json
    Error(reason) ->
      panic as { "Expected complementary formation output, got Error: " <> reason }
  }

  assert string.contains(does: output, contain: "{\"taskId\":\"first\"")
  assert string.contains(does: output, contain: "{\"id\":\"p1\"")
  assert string.contains(does: output, contain: "{\"id\":\"p3\"")
  assert string.contains(does: output, contain: "{\"taskId\":\"pair\"")
  assert string.contains(does: output, contain: "{\"id\":\"p0\"")
  assert string.contains(does: output, contain: "{\"id\":\"p2\"")
}

pub fn capped_form_keeps_late_specialists_test() {
  let payload =
    "{\"people\":[{\"id\":\"p0\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s0\",\"level\":1.0}]},{\"id\":\"p1\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s1\",\"level\":1.0}]},{\"id\":\"p2\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"p3\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"p4\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"p5\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"p6\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"p7\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"p8\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s8\",\"level\":1.0}]},{\"id\":\"p9\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s9\",\"level\":1.0}]}],\"tasks\":[{\"id\":\"late\",\"teamSize\":2,\"skills\":[{\"id\":\"s8\",\"level\":1.0,\"importance\":1},{\"id\":\"s9\",\"level\":1.0,\"importance\":1}]},{\"id\":\"early\",\"teamSize\":2,\"skills\":[{\"id\":\"s0\",\"level\":1.0,\"importance\":1},{\"id\":\"s1\",\"level\":1.0,\"importance\":1}]}],\"alpha\":1.0,\"beta\":0.0,\"gamma\":0.0,\"delta\":0.0,\"initRandom\":false}"

  let result =
    team2form_gleam.form_from_json(payload, "compat", None, False, Some(3))

  let output = case result {
    Ok(json) -> json
    Error(reason) ->
      panic as { "Expected capped formation output, got Error: " <> reason }
  }

  assert string.contains(does: output, contain: "{\"taskId\":\"late\"")
  assert string.contains(does: output, contain: "{\"id\":\"p8\"")
  assert string.contains(does: output, contain: "{\"id\":\"p9\"")
}

pub fn capped_form_reconsiders_unused_people_test() {
  let payload =
    "{\"people\":[{\"id\":\"a\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s1\",\"level\":0.5},{\"id\":\"s4\",\"level\":0.5}]},{\"id\":\"b\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s1\",\"level\":0.75},{\"id\":\"s2\",\"level\":0.5},{\"id\":\"s3\",\"level\":0.75},{\"id\":\"s4\",\"level\":0.75}]},{\"id\":\"c\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s1\",\"level\":1.0},{\"id\":\"s2\",\"level\":0.25},{\"id\":\"s3\",\"level\":1.0},{\"id\":\"s4\",\"level\":0.25}]},{\"id\":\"d\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s1\",\"level\":0.25},{\"id\":\"s2\",\"level\":0.25},{\"id\":\"s4\",\"level\":0.25}]},{\"id\":\"e\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s1\",\"level\":0.5},{\"id\":\"s2\",\"level\":0.25},{\"id\":\"s3\",\"level\":0.25},{\"id\":\"s4\",\"level\":1.0}]}],\"tasks\":[{\"id\":\"t1\",\"teamSize\":2,\"skills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1},{\"id\":\"s2\",\"level\":1.0,\"importance\":1}]},{\"id\":\"t2\",\"teamSize\":2,\"skills\":[{\"id\":\"s3\",\"level\":1.0,\"importance\":1},{\"id\":\"s4\",\"level\":1.0,\"importance\":1}]}],\"alpha\":1.0,\"beta\":0.0,\"gamma\":0.0,\"delta\":0.0,\"initRandom\":false}"

  let result =
    team2form_gleam.form_from_json(payload, "compat", None, False, Some(10))

  let output = case result {
    Ok(json) -> json
    Error(reason) ->
      panic as {
        "Expected capped improved formation output, got Error: " <> reason
      }
  }

  assert string.contains(does: output, contain: "{\"taskId\":\"t1\"")
  assert string.contains(does: output, contain: "{\"id\":\"c\"")
  assert string.contains(does: output, contain: "{\"id\":\"b\"")
  assert string.contains(does: output, contain: "{\"taskId\":\"t2\"")
  assert string.contains(does: output, contain: "{\"id\":\"e\"")
  assert string.contains(does: output, contain: "{\"id\":\"a\"")
}

pub fn quality_rejects_duplicate_team_member_ids_test() {
  let payload =
    "{\"taskSkills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1}],\"team\":[{\"id\":\"dup\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"dup\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]}]}"

  let result = team2form_gleam.quality_from_json(payload, "compat", None, False)

  let error = case result {
    Ok(output) ->
      panic as { "Expected duplicate team member validation error, got Ok: " <> output }
    Error(reason) -> reason
  }

  assert string.contains(does: error, contain: "team member ids must be unique")
}

pub fn quality_rejects_unknown_team_preference_ids_test() {
  let payload =
    "{\"taskSkills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1}],\"team\":[{\"id\":\"a\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[],\"preferences\":[{\"personId\":\"missing\",\"preference\":0.5}]},{\"id\":\"b\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]}]}"

  let result = team2form_gleam.quality_from_json(payload, "compat", None, False)

  let error = case result {
    Ok(output) ->
      panic as { "Expected unknown preference validation error, got Ok: " <> output }
    Error(reason) -> reason
  }

  assert string.contains(does: error, contain: "unknown people ids for a: missing")
}

pub fn form_rejects_unknown_task_preference_ids_test() {
  let payload =
    "{\"people\":[{\"id\":\"a\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"b\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]}],\"tasks\":[{\"id\":\"t1\",\"teamSize\":2,\"skills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1}],\"preferences\":[{\"personId\":\"ghost\",\"preference\":1.0}]}],\"initRandom\":false}"

  let result = team2form_gleam.form_from_json(payload, "compat", None, False, None)

  let error = case result {
    Ok(output) ->
      panic as { "Expected unknown task preference validation error, got Ok: " <> output }
    Error(reason) -> reason
  }

  assert string.contains(does: error, contain: "task preferences reference unknown people ids for t1: ghost")
}

pub fn paper_similarity_contributes_to_skill_score_test() {
  let payload =
    "{\"taskSkills\":[{\"id\":\"python\",\"level\":1.0,\"importance\":1},{\"id\":\"docs\",\"level\":1.0,\"importance\":1}],\"team\":[{\"id\":\"a\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"related_skill\",\"level\":0.8}]},{\"id\":\"b\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"docs\",\"level\":1.0}]}],\"similarities\":[{\"sourceId\":\"related_skill\",\"targetId\":\"python\",\"similarity\":0.5}],\"alpha\":1.0,\"beta\":0.0,\"gamma\":0.0,\"delta\":0.0}"

  let result = team2form_gleam.quality_from_json(payload, "paper", None, False)

  let output = case result {
    Ok(json) -> json
    Error(reason) ->
      panic as { "Expected paper similarity quality output, got Error: " <> reason }
  }

  assert string.contains(does: output, contain: "\"skillScore\":0.632455")
  assert string.contains(does: output, contain: "\"a\":[\"python\"]")
  assert string.contains(does: output, contain: "\"b\":[\"docs\"]")
}

pub fn form_rejects_duplicate_task_ids_test() {
  let payload =
    "{\"people\":[{\"id\":\"a\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"b\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"c\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"d\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]}],\"tasks\":[{\"id\":\"dup\",\"teamSize\":2,\"skills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1}]},{\"id\":\"dup\",\"teamSize\":2,\"skills\":[{\"id\":\"s2\",\"level\":1.0,\"importance\":1}]}],\"initRandom\":false}"

  let result = team2form_gleam.form_from_json(payload, "compat", None, False, None)

  let error = case result {
    Ok(output) ->
      panic as { "Expected duplicate task validation error, got Ok: " <> output }
    Error(reason) -> reason
  }

  assert string.contains(does: error, contain: "task ids must be unique: dup")
}

pub fn quality_rejects_duplicate_preference_ids_test() {
  let payload =
    "{\"taskSkills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1}],\"team\":[{\"id\":\"a\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[],\"preferences\":[{\"personId\":\"b\",\"preference\":0.5},{\"personId\":\"b\",\"preference\":0.75}]},{\"id\":\"b\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]}]}"

  let result = team2form_gleam.quality_from_json(payload, "compat", None, False)

  let error = case result {
    Ok(output) ->
      panic as { "Expected duplicate preference validation error, got Ok: " <> output }
    Error(reason) -> reason
  }

  assert string.contains(does: error, contain: "person preferences must not contain duplicate personIds for a: b")
}

pub fn form_rejects_duplicate_task_preference_ids_test() {
  let payload =
    "{\"people\":[{\"id\":\"a\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"b\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]}],\"tasks\":[{\"id\":\"t1\",\"teamSize\":2,\"skills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1}],\"preferences\":[{\"personId\":\"a\",\"preference\":0.5},{\"personId\":\"a\",\"preference\":1.0}]}],\"initRandom\":false}"

  let result = team2form_gleam.form_from_json(payload, "compat", None, False, None)

  let error = case result {
    Ok(output) ->
      panic as { "Expected duplicate task preference validation error, got Ok: " <> output }
    Error(reason) -> reason
  }

  assert string.contains(does: error, contain: "task preferences must not contain duplicate personIds for t1: a")
}

pub fn form_rejects_non_positive_candidate_cap_test() {
  let payload =
    "{\"people\":[{\"id\":\"a\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"b\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]}],\"tasks\":[{\"id\":\"t1\",\"teamSize\":2,\"skills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1}]}],\"initRandom\":false}"

  let result = team2form_gleam.form_from_json(payload, "compat", None, False, Some(0))

  let error = case result {
    Ok(output) ->
      panic as { "Expected candidate cap validation error, got Ok: " <> output }
    Error(reason) -> reason
  }

  assert string.contains(does: error, contain: "max_candidate_teams must be a positive integer")
}

pub fn form_rejects_insufficient_headcount_test() {
  let payload =
    "{\"people\":[{\"id\":\"a\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]},{\"id\":\"b\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]}],\"tasks\":[{\"id\":\"t1\",\"teamSize\":2,\"skills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1}]},{\"id\":\"t2\",\"teamSize\":2,\"skills\":[{\"id\":\"s2\",\"level\":1.0,\"importance\":1}]}],\"initRandom\":false}"

  let result = team2form_gleam.form_from_json(payload, "compat", None, False, None)

  let error = case result {
    Ok(output) ->
      panic as { "Expected insufficient headcount error, got Ok: " <> output }
    Error(reason) -> reason
  }

  assert string.contains(does: error, contain: "insufficient headcount")
}

pub fn quality_accepts_integer_numbers_like_float_numbers_test() {
  let integer_payload =
    "{\"taskSkills\":[{\"id\":\"s1\",\"level\":1,\"importance\":1}],\"team\":[{\"id\":\"a\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[{\"id\":\"s1\",\"level\":1}]},{\"id\":\"b\",\"personality\":{\"ei\":0,\"sn\":0,\"tf\":0,\"pj\":0},\"skills\":[]}],\"alpha\":1,\"beta\":0,\"gamma\":0,\"delta\":0}"
  let float_payload =
    "{\"taskSkills\":[{\"id\":\"s1\",\"level\":1.0,\"importance\":1.0}],\"team\":[{\"id\":\"a\",\"personality\":{\"ei\":0.0,\"sn\":0.0,\"tf\":0.0,\"pj\":0.0},\"skills\":[{\"id\":\"s1\",\"level\":1.0}]},{\"id\":\"b\",\"personality\":{\"ei\":0.0,\"sn\":0.0,\"tf\":0.0,\"pj\":0.0},\"skills\":[]}],\"alpha\":1.0,\"beta\":0.0,\"gamma\":0.0,\"delta\":0.0}"

  let integer_output = case team2form_gleam.quality_from_json(integer_payload, "compat", None, False) {
    Ok(json) -> json
    Error(reason) ->
      panic as { "Expected integer payload to decode, got Error: " <> reason }
  }
  let float_output = case team2form_gleam.quality_from_json(float_payload, "compat", None, False) {
    Ok(json) -> json
    Error(reason) ->
      panic as { "Expected float payload to decode, got Error: " <> reason }
  }

  assert integer_output == float_output
}
