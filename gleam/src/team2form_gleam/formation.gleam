import gleam/dict
import gleam/float
import gleam/int
import gleam/list
import gleam/option.{type Option, None, Some}
import gleam/order
import gleam/result
import gleam/set
import gleam/string
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

type TaskEval {
  TaskEval(
    task: models.Task,
    task_preferences: Option(dict.Dict(String, Float)),
    task_preference_default: Option(Float),
  )
}

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

    False -> {
      let ordered_tasks =
        case max_candidate_teams {
          None -> order_tasks_by_hardness(request.tasks, request.people, request.similarities, mode)
          Some(_) -> request.tasks
        }
      let task_evals = build_task_evals(ordered_tasks, mode)
      let task_order =
        list.index_map(request.tasks, fn(task, index) { #(task.id, index) })
        |> dict.from_list
      let request_has_non_self_preferences =
        case mode {
          Compat -> list.any(request.people, has_non_self_preference)
          _ -> False
        }
      let people_with_non_self_preferences =
        case mode {
          Compat ->
            request.people
            |> list.fold(set.new(), fn(found, person) {
              case has_non_self_preference(person) {
                True -> set.insert(found, person.id)
                False -> found
              }
            })

          _ -> set.new()
        }
      let #(search_outcome, _memo) =
        explore_tasks(
          tasks: task_evals,
          people: request.people,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          max_candidate_teams: max_candidate_teams,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          memo: dict.new(),
        )

      case search_outcome {
        Some(outcome) ->
          Ok(
            TeamsResponse(
              teams:
                list.sort(outcome.teams_reversed, fn(left, right) {
                  int.compare(
                    dict_get_int(task_order, left.task_id, 0),
                    dict_get_int(task_order, right.task_id, 0),
                  )
                }),
            ),
          )

        None ->
          Error(
            TeamFormationError(
              "Cannot form teams with the provided data: no valid allocation found.",
            ),
          )
      }
    }
  }
}

fn order_tasks_by_hardness(
  tasks: List(models.Task),
  people: List(Person),
  similarities: Option(List(models.Similarity)),
  mode: Mode,
) -> List(models.Task) {
  let similarity_index = scoring.similarity_lookup(similarities)

  list.sort(tasks, fn(left, right) {
    let left_hardness = task_hardness(left, people, mode, similarity_index)
    let right_hardness = task_hardness(right, people, mode, similarity_index)

    case left_hardness >. right_hardness {
      True -> order.Lt

      False ->
        case left_hardness <. right_hardness {
          True -> order.Gt
          False -> string.compare(left.id, right.id)
        }
    }
  })
}

fn task_hardness(
  task: models.Task,
  people: List(Person),
  mode: Mode,
  similarity_index: dict.Dict(#(String, String), Float),
) -> Float {
  let base = int.to_float(task.team_size)

  let skill_hardness =
    list.fold(task.skills, 0.0, fn(total, task_skill) {
      let best_coverage =
        list.fold(people, 0.0, fn(best, person) {
          let coverage =
            scoring.coverage_for_person_and_task_skill(
              person,
              task_skill,
              mode: mode,
              similarity_index: similarity_index,
            )

          float.max(best, coverage)
        })

      total +. task_skill.level *. { 1.0 -. best_coverage }
    })

  base +. skill_hardness
}

fn build_task_evals(tasks: List(models.Task), mode: Mode) -> List(TaskEval) {
  list.map(tasks, fn(task) {
    let task_preferences = scoring.preference_lookup_task(task.preferences)
    let task_preferences_option =
      case dict.is_empty(task_preferences) {
        True -> None
        False -> Some(task_preferences)
      }
    let task_preference_default =
      case mode {
        Compat ->
          case task_preferences_option {
            Some(_) -> Some(0.5)
            None -> Some(0.0)
          }

        _ -> None
      }

    TaskEval(
      task: task,
      task_preferences: task_preferences_option,
      task_preference_default: task_preference_default,
    )
  })
}

fn explore_tasks(
  tasks tasks: List(TaskEval),
  people people: List(Person),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  max_candidate_teams max_candidate_teams: Option(Int),
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(String),
  memo memo: dict.Dict(#(String, String), Option(SearchOutcome)),
) -> #(
  Option(SearchOutcome),
  dict.Dict(#(String, String), Option(SearchOutcome)),
) {
  let cache_key = #(tasks_signature(tasks), people_signature(people))

  case dict.get(memo, cache_key) {
    Ok(cached) -> #(cached, memo)

    Error(Nil) -> {
      let #(outcome, memo_after) =
        case tasks {
          [] -> #(Some(SearchOutcome(objective: 1.0, teams_reversed: [])), memo)

          [task_eval, ..rest_tasks] -> {
            let TaskEval(task:, task_preferences:, task_preference_default:) = task_eval
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
              request_has_non_self_preferences: request_has_non_self_preferences,
              people_with_non_self_preferences: people_with_non_self_preferences,
              task_preferences: task_preferences,
              task_preference_default: task_preference_default,
              best: None,
              all_people: people,
              memo: memo,
            )
          }
        }

      let memo_final = dict.insert(memo_after, cache_key, outcome)
      #(outcome, memo_final)
    }
  }
}

fn choose_best_candidate(
  candidates candidates: List(List(Person)),
  rest_tasks rest_tasks: List(TaskEval),
  request request: FormationRequest,
  task task: models.Task,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  max_candidate_teams max_candidate_teams: Option(Int),
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(String),
  task_preferences task_preferences: Option(dict.Dict(String, Float)),
  task_preference_default task_preference_default: Option(Float),
  best best: Option(SearchOutcome),
  all_people all_people: List(Person),
  memo memo: dict.Dict(#(String, String), Option(SearchOutcome)),
) -> #(
  Option(SearchOutcome),
  dict.Dict(#(String, String), Option(SearchOutcome)),
) {
  case candidates {
    [] -> #(best, memo)

    [candidate, ..rest_candidates] -> {
      let has_team_social_preferences =
        case mode {
          Compat ->
            case request_has_non_self_preferences {
              False -> False

              True -> {
                let candidate_has_non_self_source =
                  list.any(candidate, fn(member) {
                    set.contains(people_with_non_self_preferences, member.id)
                  })

                case candidate_has_non_self_source {
                  False -> False

                  True -> {
                    let teammate_ids =
                      set.from_list(list.map(candidate, fn(member) { member.id }))

                    list.any(candidate, fn(member) {
                      has_explicit_social_preferences(member, teammate_ids)
                    })
                  }
                }
              }
            }

          _ -> False
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

      let #(quality_score, social_score, delta_weight, assignments) =
        scoring.calculate_team_quality_summary_for_people(
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
          task_preferences: task_preferences,
          compat_task_preference_default: task_preference_default,
          compat_social_preference_default: social_preference_default,
        )
      let adjusted_quality =
        case mode == Compat && has_team_social_preferences == False {
          True -> quality_score -. delta_weight *. social_score
          False -> quality_score
        }
      let assigned =
        scoring.assigned_people_from_assignments(assignments)
      let team_result =
        TeamResult(task_id: task.id, people: assigned, quality: adjusted_quality)

      let should_prune =
        case best {
          Some(current_best) -> adjusted_quality <=. current_best.objective
          None -> False
        }

      let #(new_best, memo_after_child) =
        case should_prune {
          True -> #(best, memo)

          False -> {
            let remaining_people = remove_people(all_people, candidate)
            let #(child_outcome, memo_after) =
              explore_tasks(
                tasks: rest_tasks,
                people: remaining_people,
                request: request,
                mode: mode,
                preset: preset,
                normalize_weights: normalize_weights,
                max_candidate_teams: max_candidate_teams,
                request_has_non_self_preferences: request_has_non_self_preferences,
                people_with_non_self_preferences: people_with_non_self_preferences,
                memo: memo,
              )
            let candidate_outcome =
              case child_outcome {
                Some(child) ->
                  Some(
                    SearchOutcome(
                      objective: adjusted_quality *. child.objective,
                      teams_reversed: [team_result, ..child.teams_reversed],
                    ),
                  )

                None -> None
              }

            #(better_outcome(best, candidate_outcome), memo_after)
          }
        }

      choose_best_candidate(
        candidates: rest_candidates,
        rest_tasks: rest_tasks,
        request: request,
        task: task,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        max_candidate_teams: max_candidate_teams,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        task_preferences: task_preferences,
        task_preference_default: task_preference_default,
        best: new_best,
        all_people: all_people,
        memo: memo_after_child,
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
  case used_people {
    [] -> all_people

    [first] -> remove_people_with_ids_1(all_people, first.id)

    [first, second] ->
      remove_people_with_ids_2(all_people, first.id, second.id)

    [first, second, third] ->
      remove_people_with_ids_3(all_people, first.id, second.id, third.id)

    _ -> {
      let used_ids =
        list.fold(used_people, set.new(), fn(found, person) {
          set.insert(found, person.id)
        })

      remove_people_with_set(all_people, used_ids)
    }
  }
}

fn remove_people_with_ids_1(people: List(Person), id1: String) -> List(Person) {
  case people {
    [] -> []

    [person, ..rest] ->
      case person.id == id1 {
        True -> remove_people_with_ids_1(rest, id1)
        False -> [person, ..remove_people_with_ids_1(rest, id1)]
      }
  }
}

fn remove_people_with_ids_2(
  people: List(Person),
  id1: String,
  id2: String,
) -> List(Person) {
  case people {
    [] -> []

    [person, ..rest] -> {
      let should_remove = person.id == id1 || person.id == id2
      case should_remove {
        True -> remove_people_with_ids_2(rest, id1, id2)
        False -> [person, ..remove_people_with_ids_2(rest, id1, id2)]
      }
    }
  }
}

fn remove_people_with_ids_3(
  people: List(Person),
  id1: String,
  id2: String,
  id3: String,
) -> List(Person) {
  case people {
    [] -> []

    [person, ..rest] -> {
      let should_remove = person.id == id1 || person.id == id2 || person.id == id3
      case should_remove {
        True -> remove_people_with_ids_3(rest, id1, id2, id3)
        False -> [person, ..remove_people_with_ids_3(rest, id1, id2, id3)]
      }
    }
  }
}

fn remove_people_with_set(
  people: List(Person),
  used_ids: set.Set(String),
) -> List(Person) {
  case people {
    [] -> []

    [person, ..rest] ->
      case set.contains(used_ids, person.id) {
        True -> remove_people_with_set(rest, used_ids)
        False -> [person, ..remove_people_with_set(rest, used_ids)]
      }
  }
}

fn has_non_self_preference(member: Person) -> Bool {
  case member.preferences {
    Some(preferences) ->
      list.any(preferences, fn(preference) { preference.person_id != member.id })

    None -> False
  }
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

fn dict_get_int(mapping: dict.Dict(String, Int), key: String, fallback: Int) -> Int {
  case dict.get(mapping, key) {
    Ok(value) -> value
    Error(Nil) -> fallback
  }
}

fn people_signature(people: List(Person)) -> String {
  people
  |> list.map(fn(person) { person.id })
  |> string.join(with: ",")
}

fn tasks_signature(tasks: List(TaskEval)) -> String {
  tasks
  |> list.map(fn(task_eval) {
    let TaskEval(task:, ..) = task_eval
    task.id
  })
  |> string.join(with: ",")
}
