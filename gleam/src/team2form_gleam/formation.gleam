import gleam/dict
import gleam/list
import gleam/option.{type Option, None, Some}
import gleam/result
import gleam/set
import team2form_gleam/models.{
  TeamResult,
  TeamsResponse,
  type FormationRequest,
  type Person,
  type TeamResult,
  type TeamsResponse,
}
import team2form_gleam/modes.{Compat, type Mode, type WeightPreset}
import team2form_gleam/scoring

pub type TeamFormationError {
  TeamFormationError(reason: String)
}

pub const default_max_candidate_teams = 10_000

type SearchOutcome {
  SearchOutcome(objective: Float, teams_reversed: List(TeamResult))
}

pub fn team_formation_error_to_string(error: TeamFormationError) -> String {
  case error {
    TeamFormationError(reason) -> reason
  }
}

pub fn validate_max_candidate_teams(
  max_candidate_teams: Option(Int),
) -> Result(Nil, TeamFormationError) {
  case max_candidate_teams {
    Some(value) ->
      case value > 0 {
        True -> Ok(Nil)
        False ->
          Error(
            TeamFormationError(
              "max_candidate_teams must be a positive integer when provided",
            ),
          )
      }

    None -> Ok(Nil)
  }
}

pub fn form_teams(
  request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  max_candidate_teams max_candidate_teams: Option(Int),
) -> Result(TeamsResponse, TeamFormationError) {
  use Nil <- result.try(validate_max_candidate_teams(max_candidate_teams))

  let requested_seats =
    list.fold(request.tasks, 0, fn(total, task) {
      total + task.team_size
    })

  case requested_seats > list.length(request.people) {
    True ->
      Error(
        TeamFormationError(
          "Cannot form teams with the provided data: insufficient headcount.",
        ),
      )

    False ->
      case explore_tasks(
        tasks: request.tasks,
        people: request.people,
        request: request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        max_candidate_teams: max_candidate_teams,
      ) {
        Some(outcome) -> Ok(TeamsResponse(teams: outcome.teams_reversed))
        None ->
          Error(
            TeamFormationError(
              "Cannot form teams with the provided data: no valid allocation found.",
            ),
          )
      }
  }
}

fn explore_tasks(
  tasks tasks: List(models.Task),
  people people: List(Person),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  max_candidate_teams max_candidate_teams: Option(Int),
) -> Option(SearchOutcome) {
  case tasks {
    [] -> Some(SearchOutcome(objective: 1.0, teams_reversed: []))

    [task, ..rest_tasks] -> {
      let base_candidates = list.combinations(people, by: task.team_size)
      let candidates =
        case max_candidate_teams {
          Some(cap) -> list.take(base_candidates, up_to: cap)
          None -> base_candidates
        }

      choose_best_candidate(
        candidates: candidates,
        rest_tasks: rest_tasks,
        request: request,
        task: task,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        max_candidate_teams: max_candidate_teams,
        best: None,
        all_people: people,
      )
    }
  }
}

fn choose_best_candidate(
  candidates candidates: List(List(Person)),
  rest_tasks rest_tasks: List(models.Task),
  request request: FormationRequest,
  task task: models.Task,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  max_candidate_teams max_candidate_teams: Option(Int),
  best best: Option(SearchOutcome),
  all_people all_people: List(Person),
) -> Option(SearchOutcome) {
  case candidates {
    [] -> best

    [candidate, ..rest_candidates] -> {
      let remaining_people = remove_people(all_people, candidate)
      let task_preferences = scoring.preference_lookup_task(task.preferences)
      let task_preferences_option =
        case dict.is_empty(task_preferences) {
          True -> None
          False -> Some(task_preferences)
        }

      let teammate_ids =
        set.from_list(list.map(candidate, fn(member) { member.id }))
      let has_team_social_preferences =
        list.any(candidate, fn(member) {
          has_explicit_social_preferences(member, teammate_ids)
        })

      let task_preference_default =
        case mode {
          Compat ->
            case dict.is_empty(task_preferences) {
              True -> Some(0.0)
              False -> Some(0.5)
            }

          _ -> None
        }
      let social_preference_default =
        case mode {
          Compat ->
            case has_team_social_preferences {
              True -> Some(0.5)
              False -> Some(0.0)
            }

          _ -> None
        }

      let quality =
        scoring.calculate_team_quality_for_people(
          task_skills: task.skills,
          team: candidate,
          alpha: request.alpha,
          beta: request.beta,
          gamma: request.gamma,
          delta: request.delta,
          similarities: request.similarities,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          task_preferences: task_preferences_option,
          compat_task_preference_default: task_preference_default,
          compat_social_preference_default: social_preference_default,
        )
      let adjusted_quality =
        case mode == Compat && has_team_social_preferences == False {
          True ->
            quality.quality
            -. dict_get_float(quality.weights, "delta", 0.0) *. quality.social_score

          False -> quality.quality
        }
      let assigned =
        scoring.assigned_people_from_assignments(quality.assignments)
      let team_result =
        TeamResult(task_id: task.id, people: assigned, quality: adjusted_quality)

      let candidate_outcome =
        case explore_tasks(
          tasks: rest_tasks,
          people: remaining_people,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          max_candidate_teams: max_candidate_teams,
        ) {
          Some(child) ->
            Some(
              SearchOutcome(
                objective: adjusted_quality *. child.objective,
                teams_reversed: [team_result, ..child.teams_reversed],
              ),
            )

          None -> None
        }

      let new_best = better_outcome(best, candidate_outcome)

      choose_best_candidate(
        candidates: rest_candidates,
        rest_tasks: rest_tasks,
        request: request,
        task: task,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        max_candidate_teams: max_candidate_teams,
        best: new_best,
        all_people: all_people,
      )
    }
  }
}

fn better_outcome(
  left: Option(SearchOutcome),
  right: Option(SearchOutcome),
) -> Option(SearchOutcome) {
  case left, right {
    None, None -> None
    Some(best), None -> Some(best)
    None, Some(candidate) -> Some(candidate)
    Some(best), Some(candidate) ->
      case candidate.objective >. best.objective {
        True -> Some(candidate)
        False -> Some(best)
      }
  }
}

fn remove_people(all_people: List(Person), used_people: List(Person)) -> List(Person) {
  let used_ids =
    list.fold(used_people, set.new(), fn(found, person) {
      set.insert(found, person.id)
    })

  list.filter(all_people, fn(person) {
    case set.contains(used_ids, person.id) {
      True -> False
      False -> True
    }
  })
}

fn has_explicit_social_preferences(
  member: Person,
  teammate_ids: set.Set(String),
) -> Bool {
  case member.preferences {
    Some(preferences) ->
      list.any(preferences, fn(preference) {
        preference.person_id != member.id
        && set.contains(teammate_ids, preference.person_id)
      })

    None -> False
  }
}

fn dict_get_float(mapping: dict.Dict(String, Float), key: String, fallback: Float) -> Float {
  case dict.get(mapping, key) {
    Ok(value) -> value
    Error(Nil) -> fallback
  }
}
