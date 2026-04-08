import gleam/dict
import gleam/list
import gleam/option.{type Option, None, Some}
import gleam/result
import gleam/set
import gleam/string

pub type Gender {
  Female
  Male
}

pub type Personality {
  Personality(ei: Float, sn: Float, tf: Float, pj: Float)
}

pub type PersonSkill {
  PersonSkill(id: String, level: Float)
}

pub type PersonPreference {
  PersonPreference(person_id: String, preference: Float)
}

pub type Person {
  Person(
    id: String,
    gender: Option(Gender),
    personality: Personality,
    skills: List(PersonSkill),
    preferences: Option(List(PersonPreference)),
  )
}

pub type TaskSkill {
  TaskSkill(id: String, level: Float, importance: Float)
}

pub type TaskPreference {
  TaskPreference(person_id: String, preference: Float)
}

pub type Task {
  Task(
    id: String,
    team_size: Int,
    skills: List(TaskSkill),
    preferences: Option(List(TaskPreference)),
  )
}

pub type Similarity {
  Similarity(source_id: String, target_id: String, similarity: Float)
}

pub type FormationRequest {
  FormationRequest(
    people: List(Person),
    tasks: List(Task),
    init_random: Bool,
    alpha: Option(Float),
    beta: Option(Float),
    gamma: Option(Float),
    delta: Option(Float),
    similarities: Option(List(Similarity)),
  )
}

pub type TeamMember {
  TeamMember(
    id: String,
    gender: Option(Gender),
    personality: Personality,
    skills: List(PersonSkill),
    preferences: Option(List(PersonPreference)),
    task_preference: Option(Float),
  )
}

pub type TeamQualityRequest {
  TeamQualityRequest(
    task_skills: List(TaskSkill),
    team: List(TeamMember),
    alpha: Option(Float),
    beta: Option(Float),
    gamma: Option(Float),
    delta: Option(Float),
    similarities: Option(List(Similarity)),
  )
}

pub type AssignedPerson {
  AssignedPerson(id: String, skill_ids: List(String))
}

pub type TeamResult {
  TeamResult(task_id: String, people: List(AssignedPerson), quality: Float)
}

pub type TeamsResponse {
  TeamsResponse(teams: List(TeamResult))
}

pub type QualityBreakdown {
  QualityBreakdown(
    quality: Float,
    skill_score: Float,
    personality_score: Float,
    task_preference_score: Float,
    social_score: Float,
    weights: dict.Dict(String, Float),
    assignments: dict.Dict(String, List(String)),
  )
}

pub type ValidationError {
  DuplicatePersonIds(List(String))
  DuplicateTaskIds(List(String))
  DuplicateTeamMemberIds(List(String))
  DuplicatePersonPreferenceIds(person_id: String, person_ids: List(String))
  DuplicateTaskPreferenceIds(task_id: String, person_ids: List(String))
  UnknownPersonPreferencePersonIds(person_id: String, person_ids: List(String))
  UnknownTaskPreferencePersonIds(task_id: String, person_ids: List(String))
}

pub fn gender_to_string(gender: Gender) -> String {
  case gender {
    Female -> "FEMALE"
    Male -> "MALE"
  }
}

pub fn gender_from_string(value: String) -> Result(Gender, String) {
  case value {
    "FEMALE" -> Ok(Female)
    "MALE" -> Ok(Male)
    _ -> Error("Unknown gender: " <> value)
  }
}

pub fn team_member_to_person(member: TeamMember) -> Person {
  Person(
    id: member.id,
    gender: member.gender,
    personality: member.personality,
    skills: member.skills,
    preferences: member.preferences,
  )
}

pub fn duplicate_ids(ids: List(String)) -> List(String) {
  ids
  |> list.fold(dict.new(), fn(counts, id) {
    let current =
      case dict.get(counts, id) {
        Ok(count) -> count
        Error(Nil) -> 0
      }

    dict.insert(counts, id, current + 1)
  })
  |> dict.to_list
  |> list.fold([], fn(found, entry) {
    let #(id, count) = entry

    case count > 1 {
      True -> [id, ..found]
      False -> found
    }
  })
  |> list.sort(string.compare)
}

pub fn duplicate_person_preference_person_ids(
  preferences: Option(List(PersonPreference)),
) -> List(String) {
  case preferences {
    Some(entries) -> {
      let ids = list.map(entries, fn(preference: PersonPreference) { preference.person_id })
      duplicate_ids(ids)
    }
    None -> []
  }
}

pub fn duplicate_task_preference_person_ids(
  preferences: Option(List(TaskPreference)),
) -> List(String) {
  case preferences {
    Some(entries) -> {
      let ids = list.map(entries, fn(preference: TaskPreference) { preference.person_id })
      duplicate_ids(ids)
    }
    None -> []
  }
}

pub fn unknown_person_preference_person_ids(
  preferences: Option(List(PersonPreference)),
  known_person_ids: set.Set(String),
) -> List(String) {
  case preferences {
    Some(entries) ->
      entries
      |> list.fold(set.new(), fn(found, preference: PersonPreference) {
        case set.contains(known_person_ids, preference.person_id) {
          True -> found
          False -> set.insert(found, preference.person_id)
        }
      })
      |> set.to_list
      |> list.sort(string.compare)

    None -> []
  }
}

pub fn unknown_task_preference_person_ids(
  preferences: Option(List(TaskPreference)),
  known_person_ids: set.Set(String),
) -> List(String) {
  case preferences {
    Some(entries) ->
      entries
      |> list.fold(set.new(), fn(found, preference: TaskPreference) {
        case set.contains(known_person_ids, preference.person_id) {
          True -> found
          False -> set.insert(found, preference.person_id)
        }
      })
      |> set.to_list
      |> list.sort(string.compare)

    None -> []
  }
}

pub fn total_requested_seats(request: FormationRequest) -> Int {
  let FormationRequest(tasks:, ..) = request
  list.fold(tasks, 0, fn(total, task) { total + task.team_size })
}

pub fn validate_person(person: Person) -> Result(Person, ValidationError) {
  let duplicate_preferences = duplicate_person_preference_person_ids(person.preferences)

  case duplicate_preferences {
    [] -> Ok(person)
    [_, ..] -> Error(DuplicatePersonPreferenceIds(person_id: person.id, person_ids: duplicate_preferences))
  }
}

pub fn validate_task(task: Task) -> Result(Task, ValidationError) {
  let duplicate_preferences = duplicate_task_preference_person_ids(task.preferences)

  case duplicate_preferences {
    [] -> Ok(task)
    [_, ..] -> Error(DuplicateTaskPreferenceIds(task_id: task.id, person_ids: duplicate_preferences))
  }
}

pub fn validate_formation_request(
  request: FormationRequest,
) -> Result(FormationRequest, ValidationError) {
  let FormationRequest(people:, tasks:, ..) = request
  use Nil <- result.try(validate_people(people))
  use Nil <- result.try(validate_tasks(tasks))

  let duplicate_people = duplicate_ids(list.map(people, fn(person: Person) { person.id }))
  case duplicate_people {
    [_, ..] -> Error(DuplicatePersonIds(duplicate_people))
    [] -> {
      let duplicate_tasks = duplicate_ids(list.map(tasks, fn(task: Task) { task.id }))
      case duplicate_tasks {
        [_, ..] -> Error(DuplicateTaskIds(duplicate_tasks))
        [] -> {
          let person_ids = set.from_list(list.map(people, fn(person: Person) { person.id }))
          use Nil <- result.try(validate_people_preferences(people, person_ids))
          use Nil <- result.try(validate_task_preferences(tasks, person_ids))
          Ok(request)
        }
      }
    }
  }
}

fn validate_people(people: List(Person)) -> Result(Nil, ValidationError) {
  list.fold(people, Ok(Nil), fn(current, person) {
    use Nil <- result.try(current)
    use _person <- result.try(validate_person(person))
    Ok(Nil)
  })
}

fn validate_tasks(tasks: List(Task)) -> Result(Nil, ValidationError) {
  list.fold(tasks, Ok(Nil), fn(current, task) {
    use Nil <- result.try(current)
    use _task <- result.try(validate_task(task))
    Ok(Nil)
  })
}

fn validate_people_preferences(
  people: List(Person),
  person_ids: set.Set(String),
) -> Result(Nil, ValidationError) {
  list.fold(people, Ok(Nil), fn(current, person) {
    use Nil <- result.try(current)
    let unknown_preferences = unknown_person_preference_person_ids(person.preferences, person_ids)
    case unknown_preferences {
      [] -> Ok(Nil)
      [_, ..] -> Error(UnknownPersonPreferencePersonIds(person_id: person.id, person_ids: unknown_preferences))
    }
  })
}

fn validate_task_preferences(
  tasks: List(Task),
  person_ids: set.Set(String),
) -> Result(Nil, ValidationError) {
  list.fold(tasks, Ok(Nil), fn(current, task) {
    use Nil <- result.try(current)
    let unknown_preferences = unknown_task_preference_person_ids(task.preferences, person_ids)
    case unknown_preferences {
      [] -> Ok(Nil)
      [_, ..] -> Error(UnknownTaskPreferencePersonIds(task_id: task.id, person_ids: unknown_preferences))
    }
  })
}

pub fn validate_team_quality_request(
  request: TeamQualityRequest,
) -> Result(TeamQualityRequest, ValidationError) {
  let TeamQualityRequest(team:, ..) = request
  let duplicate_members = duplicate_ids(list.map(team, fn(member: TeamMember) { member.id }))
  case duplicate_members {
    [_, ..] -> Error(DuplicateTeamMemberIds(duplicate_members))
    [] -> {
      let member_ids = set.from_list(list.map(team, fn(member: TeamMember) { member.id }))
      use Nil <- result.try(validate_team_members(team, member_ids))
      Ok(request)
    }
  }
}

fn validate_team_members(
  team: List(TeamMember),
  member_ids: set.Set(String),
) -> Result(Nil, ValidationError) {
  list.fold(team, Ok(Nil), fn(current, member) {
    use Nil <- result.try(current)
    let duplicate_preferences = duplicate_person_preference_person_ids(member.preferences)
    case duplicate_preferences {
      [_, ..] -> Error(DuplicatePersonPreferenceIds(person_id: member.id, person_ids: duplicate_preferences))
      [] -> {
        let unknown_preferences = unknown_person_preference_person_ids(member.preferences, member_ids)
        case unknown_preferences {
          [] -> Ok(Nil)
          [_, ..] -> Error(UnknownPersonPreferencePersonIds(person_id: member.id, person_ids: unknown_preferences))
        }
      }
    }
  })
}

pub fn validation_error_to_string(error: ValidationError) -> String {
  case error {
    DuplicatePersonIds(ids) -> "people ids must be unique: " <> string.join(ids, with: ", ")
    DuplicateTaskIds(ids) -> "task ids must be unique: " <> string.join(ids, with: ", ")
    DuplicateTeamMemberIds(ids) -> "team member ids must be unique: " <> string.join(ids, with: ", ")
    DuplicatePersonPreferenceIds(person_id:, person_ids:) ->
      "person preferences must not contain duplicate personIds for "
      <> person_id
      <> ": "
      <> string.join(person_ids, with: ", ")
    DuplicateTaskPreferenceIds(task_id:, person_ids:) ->
      "task preferences must not contain duplicate personIds for "
      <> task_id
      <> ": "
      <> string.join(person_ids, with: ", ")
    UnknownPersonPreferencePersonIds(person_id:, person_ids:) ->
      "person preferences reference unknown people ids for "
      <> person_id
      <> ": "
      <> string.join(person_ids, with: ", ")
    UnknownTaskPreferencePersonIds(task_id:, person_ids:) ->
      "task preferences reference unknown people ids for "
      <> task_id
      <> ": "
      <> string.join(person_ids, with: ", ")
  }
}
