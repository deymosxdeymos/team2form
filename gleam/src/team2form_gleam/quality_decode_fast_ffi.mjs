import { toList } from "../gleam.mjs"
import { None, Some } from "../../gleam_stdlib/gleam/option.mjs"
import {
  Female,
  Male,
  Personality,
  PersonSkill,
  PersonPreference,
  Person,
  TeamMember,
  TaskSkill,
  TaskPreference,
  Task,
  Similarity,
  FormationRequest,
  TeamQualityRequest,
} from "./models.mjs"

const NONE = new None()

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value)
}

function inRange(value, min, max) {
  return isFiniteNumber(value) && value >= min && value <= max
}

function nonEmptyString(value) {
  return typeof value === "string" && value.length > 0
}

function optionalBounded01(value) {
  if (value === undefined || value === null) {
    return NONE
  }
  if (!inRange(value, 0, 1)) {
    return null
  }
  return new Some(value)
}

function parseGender(value) {
  if (value === undefined || value === null) {
    return NONE
  }
  if (value === "FEMALE") {
    return new Some(new Female())
  }
  if (value === "MALE") {
    return new Some(new Male())
  }
  return null
}

function parsePersonality(raw) {
  if (raw === null || typeof raw !== "object") {
    return null
  }

  if (!inRange(raw.ei, -1, 1) || !inRange(raw.sn, -1, 1) || !inRange(raw.tf, -1, 1) || !inRange(raw.pj, -1, 1)) {
    return null
  }

  return new Personality(raw.ei, raw.sn, raw.tf, raw.pj)
}

function parsePersonSkills(rawSkills) {
  const source = rawSkills === undefined ? [] : rawSkills
  if (!Array.isArray(source)) {
    return null
  }

  const parsed = []
  for (let i = 0; i < source.length; i += 1) {
    const skill = source[i]
    if (skill === null || typeof skill !== "object") {
      return null
    }
    if (!nonEmptyString(skill.id) || !inRange(skill.level, 0, 1)) {
      return null
    }

    parsed.push(new PersonSkill(skill.id, skill.level))
  }

  return toList(parsed)
}

function parsePersonPreferences(rawPreferences) {
  if (rawPreferences === undefined || rawPreferences === null) {
    return NONE
  }
  if (!Array.isArray(rawPreferences)) {
    return null
  }

  const parsed = []
  for (let i = 0; i < rawPreferences.length; i += 1) {
    const preference = rawPreferences[i]
    if (preference === null || typeof preference !== "object") {
      return null
    }
    if (!nonEmptyString(preference.personId) || !inRange(preference.preference, 0, 1)) {
      return null
    }

    parsed.push(new PersonPreference(preference.personId, preference.preference))
  }

  return new Some(toList(parsed))
}

function parseTaskSkills(rawTaskSkills) {
  if (!Array.isArray(rawTaskSkills) || rawTaskSkills.length < 1) {
    return null
  }

  const parsed = []
  for (let i = 0; i < rawTaskSkills.length; i += 1) {
    const taskSkill = rawTaskSkills[i]
    if (taskSkill === null || typeof taskSkill !== "object") {
      return null
    }
    if (!nonEmptyString(taskSkill.id) || !inRange(taskSkill.level, 0, 1)) {
      return null
    }
    if (!isFiniteNumber(taskSkill.importance) || taskSkill.importance < 1) {
      return null
    }

    parsed.push(new TaskSkill(taskSkill.id, taskSkill.level, taskSkill.importance))
  }

  return toList(parsed)
}

function parseTeamMembers(rawTeam) {
  if (!Array.isArray(rawTeam) || rawTeam.length < 2) {
    return null
  }

  const parsed = []
  for (let i = 0; i < rawTeam.length; i += 1) {
    const member = rawTeam[i]
    if (member === null || typeof member !== "object") {
      return null
    }
    if (!nonEmptyString(member.id)) {
      return null
    }

    const gender = parseGender(member.gender)
    if (gender === null) {
      return null
    }

    const personality = parsePersonality(member.personality)
    if (personality === null) {
      return null
    }

    const skills = parsePersonSkills(member.skills)
    if (skills === null) {
      return null
    }

    const preferences = parsePersonPreferences(member.preferences)
    if (preferences === null) {
      return null
    }

    const taskPreference = optionalBounded01(member.taskPreference)
    if (taskPreference === null) {
      return null
    }

    parsed.push(
      new TeamMember(
        member.id,
        gender,
        personality,
        skills,
        preferences,
        taskPreference,
      ),
    )
  }

  return toList(parsed)
}

function parseSimilarities(rawSimilarities) {
  if (rawSimilarities === undefined || rawSimilarities === null) {
    return NONE
  }
  if (!Array.isArray(rawSimilarities)) {
    return null
  }

  const parsed = []
  for (let i = 0; i < rawSimilarities.length; i += 1) {
    const similarity = rawSimilarities[i]
    if (similarity === null || typeof similarity !== "object") {
      return null
    }
    if (
      !nonEmptyString(similarity.sourceId)
      || !nonEmptyString(similarity.targetId)
      || !inRange(similarity.similarity, 0, 1)
    ) {
      return null
    }

    parsed.push(
      new Similarity(
        similarity.sourceId,
        similarity.targetId,
        similarity.similarity,
      ),
    )
  }

  return new Some(toList(parsed))
}

function parseTeamQualityRequest(raw) {
  if (raw === null || typeof raw !== "object") {
    return null
  }

  const taskSkills = parseTaskSkills(raw.taskSkills)
  if (taskSkills === null) {
    return null
  }

  const team = parseTeamMembers(raw.team)
  if (team === null) {
    return null
  }

  const alpha = optionalBounded01(raw.alpha)
  if (alpha === null) {
    return null
  }
  const beta = optionalBounded01(raw.beta)
  if (beta === null) {
    return null
  }
  const gamma = optionalBounded01(raw.gamma)
  if (gamma === null) {
    return null
  }
  const delta = optionalBounded01(raw.delta)
  if (delta === null) {
    return null
  }

  const similarities = parseSimilarities(raw.similarities)
  if (similarities === null) {
    return null
  }

  return new TeamQualityRequest(
    taskSkills,
    team,
    alpha,
    beta,
    gamma,
    delta,
    similarities,
  )
}

export function decode_team_quality_request_fast(source) {
  let raw
  try {
    raw = JSON.parse(source)
  } catch {
    return NONE
  }

  const parsed = parseTeamQualityRequest(raw)
  if (parsed === null) {
    return NONE
  }

  return new Some(parsed)
}

function integerAtLeast(value, minimum) {
  return Number.isInteger(value) && value >= minimum
}

function parseTaskPreferences(rawPreferences) {
  if (rawPreferences === undefined || rawPreferences === null) {
    return NONE
  }
  if (!Array.isArray(rawPreferences)) {
    return null
  }

  const parsed = []
  for (let i = 0; i < rawPreferences.length; i += 1) {
    const preference = rawPreferences[i]
    if (preference === null || typeof preference !== "object") {
      return null
    }
    if (!nonEmptyString(preference.personId) || !inRange(preference.preference, 0, 1)) {
      return null
    }

    parsed.push(new TaskPreference(preference.personId, preference.preference))
  }

  return new Some(toList(parsed))
}

function parsePeople(rawPeople) {
  if (!Array.isArray(rawPeople) || rawPeople.length < 2) {
    return null
  }

  const parsed = []
  for (let i = 0; i < rawPeople.length; i += 1) {
    const person = rawPeople[i]
    if (person === null || typeof person !== "object") {
      return null
    }
    if (!nonEmptyString(person.id)) {
      return null
    }

    const gender = parseGender(person.gender)
    if (gender === null) {
      return null
    }

    const personality = parsePersonality(person.personality)
    if (personality === null) {
      return null
    }

    const skills = parsePersonSkills(person.skills)
    if (skills === null) {
      return null
    }

    const preferences = parsePersonPreferences(person.preferences)
    if (preferences === null) {
      return null
    }

    parsed.push(new Person(person.id, gender, personality, skills, preferences))
  }

  return toList(parsed)
}

function parseTasks(rawTasks) {
  if (!Array.isArray(rawTasks) || rawTasks.length < 1) {
    return null
  }

  const parsed = []
  for (let i = 0; i < rawTasks.length; i += 1) {
    const task = rawTasks[i]
    if (task === null || typeof task !== "object") {
      return null
    }
    if (!nonEmptyString(task.id)) {
      return null
    }
    if (!integerAtLeast(task.teamSize, 2)) {
      return null
    }

    const skills = parseTaskSkills(task.skills)
    if (skills === null) {
      return null
    }

    const preferences = parseTaskPreferences(task.preferences)
    if (preferences === null) {
      return null
    }

    parsed.push(new Task(task.id, task.teamSize, skills, preferences))
  }

  return toList(parsed)
}

function parseInitRandom(value) {
  if (value === undefined) {
    return false
  }
  return value === true || value === false ? value : null
}

function parseFormationRequest(raw) {
  if (raw === null || typeof raw !== "object") {
    return null
  }

  const people = parsePeople(raw.people)
  if (people === null) {
    return null
  }

  const tasks = parseTasks(raw.tasks)
  if (tasks === null) {
    return null
  }

  const initRandom = parseInitRandom(raw.initRandom)
  if (initRandom === null) {
    return null
  }

  const alpha = optionalBounded01(raw.alpha)
  if (alpha === null) {
    return null
  }
  const beta = optionalBounded01(raw.beta)
  if (beta === null) {
    return null
  }
  const gamma = optionalBounded01(raw.gamma)
  if (gamma === null) {
    return null
  }
  const delta = optionalBounded01(raw.delta)
  if (delta === null) {
    return null
  }

  const similarities = parseSimilarities(raw.similarities)
  if (similarities === null) {
    return null
  }

  return new FormationRequest(
    people,
    tasks,
    initRandom,
    alpha,
    beta,
    gamma,
    delta,
    similarities,
  )
}

export function decode_formation_request_fast(source) {
  let raw
  try {
    raw = JSON.parse(source)
  } catch {
    return NONE
  }

  const parsed = parseFormationRequest(raw)
  if (parsed === null) {
    return NONE
  }

  return new Some(parsed)
}
