import { to_list } from "../../gleam_stdlib/gleam/dict.mjs"

function listToArray(list) {
  const array = []
  for (const item of list) {
    array.push(item)
  }
  return array
}

function dictToFloatObject(dict) {
  const object = {}
  for (const entry of to_list(dict)) {
    object[entry[0]] = entry[1]
  }
  return object
}

function dictAssignmentsToObject(dict) {
  const object = {}
  for (const entry of to_list(dict)) {
    object[entry[0]] = listToArray(entry[1])
  }
  return object
}

export function encode_quality_breakdown_fast(payload) {
  const jsonObject = {
    quality: payload.quality,
    skillScore: payload.skill_score,
    personalityScore: payload.personality_score,
    taskPreferenceScore: payload.task_preference_score,
    socialScore: payload.social_score,
    weights: dictToFloatObject(payload.weights),
    assignments: dictAssignmentsToObject(payload.assignments),
  }

  return JSON.stringify(jsonObject)
}
