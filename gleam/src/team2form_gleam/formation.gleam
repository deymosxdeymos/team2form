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
  type FormationRequest, type Person, type TeamResult, type TeamsResponse,
  TeamResult, TeamsResponse,
}
import team2form_gleam/modes.{type Mode, type WeightPreset, Compat}
import team2form_gleam/scoring
import team2form_gleam/weights

pub type TeamFormationError {
  TeamFormationError(reason: String)
}

pub const default_max_candidate_teams = 10_000

const shortlist_padding = 6

const swap_rounds = 8

const max_pairwise_swap_moves = 24

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

type RankedPerson {
  RankedPerson(person: Person, score: Float, index: Int)
}

type ScoredCandidate {
  ScoredCandidate(team: List(Person), score: Float, index: Int)
}

type ScoredTeam {
  ScoredTeam(team_result: TeamResult, quality: Float)
}

type FormationContext {
  FormationContext(
    request: FormationRequest,
    mode: Mode,
    preset: Option(WeightPreset),
    normalize_weights: Bool,
    max_candidate_teams: Option(Int),
    task_evals: List(TaskEval),
    task_order: dict.Dict(String, Int),
    task_lookup: dict.Dict(String, models.Task),
    task_preferences_by_id: dict.Dict(String, dict.Dict(String, Float)),
    task_skill_fit_by_task_person: dict.Dict(#(String, String), Float),
    personality_pair_by_people: dict.Dict(#(String, String), Float),
    social_pair_by_people: dict.Dict(#(String, String), Float),
    upper_bound_by_task: dict.Dict(String, Float),
    resolved_weights: weights.Weights,
    similarity_index: dict.Dict(#(String, String), Float),
    request_has_non_self_preferences: Bool,
    people_with_non_self_preferences: set.Set(String),
  )
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
          Error(TeamFormationError(
            "max_candidate_teams must be a positive integer when provided",
          ))
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
    list.fold(request.tasks, 0, fn(total, task) { total + task.team_size })

  case requested_seats > list.length(request.people) {
    True ->
      Error(TeamFormationError(
        "Cannot form teams with the provided data: insufficient headcount.",
      ))

    False -> {
      let context =
        build_formation_context(
          request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          max_candidate_teams: max_candidate_teams,
        )
      let search_outcome = case
        capped_candidate_search_is_exact(request, context.max_candidate_teams)
      {
        True -> {
          let #(outcome, _memo, _score_cache) =
            explore_tasks(
              tasks: context.task_evals,
              remaining_task_count: list.length(context.task_evals),
              people: request.people,
              request: request,
              mode: mode,
              preset: preset,
              normalize_weights: normalize_weights,
              max_candidate_teams: context.max_candidate_teams,
              task_skill_fit_by_task_person: context.task_skill_fit_by_task_person,
              personality_pair_by_people: context.personality_pair_by_people,
              social_pair_by_people: context.social_pair_by_people,
              upper_bound_by_task: context.upper_bound_by_task,
              request_has_non_self_preferences: context.request_has_non_self_preferences,
              people_with_non_self_preferences: context.people_with_non_self_preferences,
              memo: dict.new(),
              score_cache: dict.new(),
            )
          outcome
        }

        False -> {
          let #(greedy_outcome, score_cache) =
            greedy_allocate_tasks(
              tasks: context.task_evals,
              people: request.people,
              request: request,
              mode: mode,
              preset: preset,
              normalize_weights: normalize_weights,
              max_candidate_teams: context.max_candidate_teams,
              task_skill_fit_by_task_person: context.task_skill_fit_by_task_person,
              personality_pair_by_people: context.personality_pair_by_people,
              social_pair_by_people: context.social_pair_by_people,
              request_has_non_self_preferences: context.request_has_non_self_preferences,
              people_with_non_self_preferences: context.people_with_non_self_preferences,
              score_cache: dict.new(),
              allocations_reversed: [],
            )

          case greedy_outcome {
            None -> None
            Some(outcome) ->
              Some(improve_outcome(
                outcome,
                task_evals: context.task_evals,
                request: request,
                mode: mode,
                preset: preset,
                normalize_weights: normalize_weights,
                request_has_non_self_preferences: context.request_has_non_self_preferences,
                people_with_non_self_preferences: context.people_with_non_self_preferences,
                score_cache: score_cache,
                rounds_remaining: swap_rounds,
              ))
          }
        }
      }

      case search_outcome {
        Some(outcome) ->
          Ok(
            TeamsResponse(
              teams: list.sort(outcome.teams_reversed, fn(left, right) {
                int.compare(
                  dict_get_int(context.task_order, left.task_id, 0),
                  dict_get_int(context.task_order, right.task_id, 0),
                )
              }),
            ),
          )

        None ->
          Error(TeamFormationError(
            "Cannot form teams with the provided data: no valid allocation found.",
          ))
      }
    }
  }
}

fn build_formation_context(
  request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  max_candidate_teams max_candidate_teams: Option(Int),
) -> FormationContext {
  let ordered_tasks = case max_candidate_teams {
    None ->
      order_tasks_by_hardness(
        request.tasks,
        request.people,
        request.similarities,
        mode,
      )
    Some(_) -> request.tasks
  }
  let task_evals = build_task_evals(ordered_tasks, mode)
  let task_order =
    list.index_map(request.tasks, fn(task, index) { #(task.id, index) })
    |> dict.from_list
  let task_lookup =
    request.tasks
    |> list.map(fn(task) { #(task.id, task) })
    |> dict.from_list
  let task_preferences_by_id =
    task_evals
    |> list.map(fn(task_eval) {
      let TaskEval(task:, task_preferences:, ..) = task_eval
      let preferences = option.unwrap(task_preferences, dict.new())
      #(task.id, preferences)
    })
    |> dict.from_list
  let request_has_non_self_preferences = case mode {
    Compat -> list.any(request.people, has_non_self_preference)
    _ -> False
  }
  let people_with_non_self_preferences = case mode {
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
  let similarity_index = scoring.similarity_lookup(request.similarities)
  let resolved_weights =
    weights.resolve_weights(
      alpha: request.alpha,
      beta: request.beta,
      gamma: request.gamma,
      delta: request.delta,
      mode: mode,
      preset: preset,
      normalize: normalize_weights,
    )

  FormationContext(
    request: request,
    mode: mode,
    preset: preset,
    normalize_weights: normalize_weights,
    max_candidate_teams: max_candidate_teams,
    task_evals: task_evals,
    task_order: task_order,
    task_lookup: task_lookup,
    task_preferences_by_id: task_preferences_by_id,
    task_skill_fit_by_task_person: build_task_skill_fit_cache(
      task_evals,
      request.people,
      mode: mode,
      similarity_index: similarity_index,
    ),
    personality_pair_by_people: build_personality_pair_cache(
      request.people,
      mode: mode,
    ),
    social_pair_by_people: build_social_pair_cache(request.people, mode: mode),
    upper_bound_by_task: case
      capped_candidate_search_is_exact(request, max_candidate_teams)
    {
      True ->
        build_task_upper_bound_cache(
          task_evals,
          request.people,
          resolved_weights: resolved_weights,
          mode: mode,
          similarity_index: similarity_index,
        )
      False -> dict.new()
    },
    resolved_weights: resolved_weights,
    similarity_index: similarity_index,
    request_has_non_self_preferences: request_has_non_self_preferences,
    people_with_non_self_preferences: people_with_non_self_preferences,
  )
}

fn capped_candidate_search_is_exact(
  request: FormationRequest,
  max_candidate_teams: Option(Int),
) -> Bool {
  case max_candidate_teams {
    None -> True

    Some(cap) ->
      capped_candidate_search_is_exact_loop(
        request.tasks,
        list.length(request.people),
        cap,
        1,
      )
  }
}

fn capped_candidate_search_is_exact_loop(
  tasks: List(models.Task),
  remaining_people: Int,
  cap: Int,
  allocation_count: Int,
) -> Bool {
  case tasks {
    [] -> True

    [task, ..rest] -> {
      let task_candidate_count =
        combination_count(remaining_people, task.team_size)
      case task_candidate_count <= 0 {
        True -> False

        False ->
          case task_candidate_count > cap {
            True -> False
            False -> {
              let exceeds_global_cap =
                allocation_count > cap / task_candidate_count
              case exceeds_global_cap {
                True -> False
                False ->
                  capped_candidate_search_is_exact_loop(
                    rest,
                    remaining_people - task.team_size,
                    cap,
                    allocation_count * task_candidate_count,
                  )
              }
            }
          }
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

fn build_task_skill_fit_cache(
  task_evals: List(TaskEval),
  people: List(Person),
  mode mode: Mode,
  similarity_index similarity_index: dict.Dict(#(String, String), Float),
) -> dict.Dict(#(String, String), Float) {
  list.fold(task_evals, dict.new(), fn(found, task_eval) {
    let TaskEval(task:, ..) = task_eval
    list.fold(people, found, fn(cache, person) {
      dict.insert(
        cache,
        #(task.id, person.id),
        individual_skill_fit(
          person,
          task,
          mode: mode,
          similarity_index: similarity_index,
        ),
      )
    })
  })
}

fn individual_skill_fit(
  person: Person,
  task: models.Task,
  mode mode: Mode,
  similarity_index similarity_index: dict.Dict(#(String, String), Float),
) -> Float {
  let skills_per_person = ceil_div(list.length(task.skills), task.team_size)
  let total_importance =
    list.fold(task.skills, 0.0, fn(total, skill) { total +. skill.importance })
  let best_skill_coverages =
    task.skills
    |> list.map(fn(task_skill) {
      #(
        scoring.coverage_for_person_and_task_skill(
          person,
          task_skill,
          mode: mode,
          similarity_index: similarity_index,
        ),
        task_skill.importance,
      )
    })
    |> list.sort(compare_weighted_coverage)
    |> list.take(up_to: skills_per_person)

  case total_importance >. 0.0 {
    True ->
      list.fold(best_skill_coverages, 0.0, fn(total, item) {
        let #(coverage, importance) = item
        total +. coverage *. importance
      })
      /. total_importance

    False -> 0.0
  }
}

fn build_personality_pair_cache(
  people: List(Person),
  mode mode: Mode,
) -> dict.Dict(#(String, String), Float) {
  build_pair_cache(people, dict.new(), fn(left, right) {
    scoring.team_personality_score([left, right], mode: mode)
  })
}

fn build_social_pair_cache(
  people: List(Person),
  mode mode: Mode,
) -> dict.Dict(#(String, String), Float) {
  build_pair_cache(people, dict.new(), fn(left, right) {
    case
      mode == Compat
      && member_has_explicit_preference_for(left, right.id) == False
      && member_has_explicit_preference_for(right, left.id) == False
    {
      True -> 0.0
      False -> scoring.team_social_score([left, right], compat_default: 0.5)
    }
  })
}

fn build_pair_cache(
  people: List(Person),
  cache: dict.Dict(#(String, String), Float),
  score: fn(Person, Person) -> Float,
) -> dict.Dict(#(String, String), Float) {
  case people {
    [] -> cache
    [_] -> cache

    [person, ..rest] -> {
      let next_cache =
        list.fold(rest, cache, fn(found, teammate) {
          dict.insert(
            found,
            pair_key(person.id, teammate.id),
            score(person, teammate),
          )
        })
      build_pair_cache(rest, next_cache, score)
    }
  }
}

fn build_task_upper_bound_cache(
  task_evals: List(TaskEval),
  people: List(Person),
  resolved_weights resolved_weights: weights.Weights,
  mode mode: Mode,
  similarity_index similarity_index: dict.Dict(#(String, String), Float),
) -> dict.Dict(String, Float) {
  list.fold(task_evals, dict.new(), fn(found, task_eval) {
    let TaskEval(task:, task_preferences:, task_preference_default:) = task_eval
    let best_skill =
      list.fold(people, 0.0, fn(best, person) {
        float.max(
          best,
          individual_skill_fit(
            person,
            task,
            mode: mode,
            similarity_index: similarity_index,
          ),
        )
      })
    let best_task_preference =
      list.fold(people, 0.0, fn(best, person) {
        let preference = case task_preferences {
          Some(preferences) ->
            dict_get_float(
              preferences,
              person.id,
              option_float_or(task_preference_default, 0.5),
            )
          None -> option_float_or(task_preference_default, 0.5)
        }
        float.max(best, preference)
      })
    let upper_bound =
      resolved_weights.alpha
      *. best_skill
      +. resolved_weights.beta
      +. resolved_weights.gamma
      *. best_task_preference
      +. resolved_weights.delta

    dict.insert(found, task.id, upper_bound)
  })
}

fn build_task_evals(tasks: List(models.Task), mode: Mode) -> List(TaskEval) {
  list.map(tasks, fn(task) {
    let task_preferences = scoring.preference_lookup_task(task.preferences)
    let task_preferences_option = case dict.is_empty(task_preferences) {
      True -> None
      False -> Some(task_preferences)
    }
    let task_preference_default = case mode {
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

fn candidate_combinations_for_task(
  people people: List(Person),
  request request: FormationRequest,
  task task: models.Task,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  max_candidate_teams max_candidate_teams: Option(Int),
  task_skill_fit_by_task_person task_skill_fit_by_task_person: dict.Dict(
    #(String, String),
    Float,
  ),
  personality_pair_by_people personality_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  social_pair_by_people social_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  task_preferences task_preferences: Option(dict.Dict(String, Float)),
  task_preference_default task_preference_default: Option(Float),
) -> List(List(Person)) {
  let total = combination_count(list.length(people), task.team_size)

  case max_candidate_teams {
    None -> list.combinations(people, by: task.team_size)

    Some(cap) ->
      case total <= cap {
        True -> list.combinations(people, by: task.team_size)

        False -> {
          let shortlist =
            shortlist_people(
              people: people,
              task: task,
              mode: mode,
              max_candidate_teams: cap,
              task_preferences: task_preferences,
              task_preference_default: task_preference_default,
              task_skill_fit_by_task_person: task_skill_fit_by_task_person,
              personality_pair_by_people: personality_pair_by_people,
              social_pair_by_people: social_pair_by_people,
              resolved_weights: weights.resolve_weights(
                alpha: request.alpha,
                beta: request.beta,
                gamma: request.gamma,
                delta: request.delta,
                mode: mode,
                preset: preset,
                normalize: normalize_weights,
              ),
              similarity_index: scoring.similarity_lookup(request.similarities),
            )
          let scored_combinations =
            bounded_combinations(shortlist, task.team_size, cap * 4)
            |> list.index_map(fn(candidate, index) {
              ScoredCandidate(
                team: candidate,
                score: candidate_quality_score(
                  candidate,
                  request: request,
                  task: task,
                  mode: mode,
                  preset: preset,
                  normalize_weights: normalize_weights,
                  task_preferences: task_preferences,
                  task_preference_default: task_preference_default,
                ),
                index: index,
              )
            })
            |> list.sort(compare_scored_candidate)

          scored_combinations
          |> list.take(up_to: cap)
          |> list.map(fn(candidate) { candidate.team })
        }
      }
  }
}

fn shortlist_people(
  people people: List(Person),
  task task: models.Task,
  mode mode: Mode,
  max_candidate_teams max_candidate_teams: Int,
  task_preferences task_preferences: Option(dict.Dict(String, Float)),
  task_preference_default task_preference_default: Option(Float),
  task_skill_fit_by_task_person task_skill_fit_by_task_person: dict.Dict(
    #(String, String),
    Float,
  ),
  personality_pair_by_people personality_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  social_pair_by_people social_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  resolved_weights resolved_weights: weights.Weights,
  similarity_index similarity_index: dict.Dict(#(String, String), Float),
) -> List(Person) {
  let target_size =
    int.min(
      list.length(people),
      int.max(
        int.max(task.team_size + shortlist_padding, task.team_size * 2),
        minimum_shortlist_size(task.team_size, max_candidate_teams),
      ),
    )
  let scored_combination_budget = max_candidate_teams * 4
  let shortlist_size =
    bounded_shortlist_size(
      team_size: task.team_size,
      target_size: target_size,
      scored_combination_budget: scored_combination_budget,
    )

  let ranked =
    people
    |> list.index_map(fn(person, index) {
      RankedPerson(
        person: person,
        score: individual_shortlist_score(
          person,
          people: people,
          task: task,
          mode: mode,
          task_preferences: task_preferences,
          task_preference_default: task_preference_default,
          task_skill_fit_by_task_person: task_skill_fit_by_task_person,
          personality_pair_by_people: personality_pair_by_people,
          social_pair_by_people: social_pair_by_people,
          resolved_weights: resolved_weights,
          similarity_index: similarity_index,
        ),
        index: index,
      )
    })
    |> list.sort(compare_ranked_person)
    |> list.take(up_to: shortlist_size)

  let selected_ids =
    ranked
    |> list.map(fn(ranked_person) { ranked_person.person.id })
    |> set.from_list

  list.filter(people, fn(person) { set.contains(selected_ids, person.id) })
}

fn individual_shortlist_score(
  person: Person,
  people people: List(Person),
  task task: models.Task,
  mode mode: Mode,
  task_preferences task_preferences: Option(dict.Dict(String, Float)),
  task_preference_default task_preference_default: Option(Float),
  task_skill_fit_by_task_person task_skill_fit_by_task_person: dict.Dict(
    #(String, String),
    Float,
  ),
  personality_pair_by_people personality_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  social_pair_by_people social_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  resolved_weights resolved_weights: weights.Weights,
  similarity_index similarity_index: dict.Dict(#(String, String), Float),
) -> Float {
  let skill_fit =
    dict_get_tuple_float(
      task_skill_fit_by_task_person,
      #(task.id, person.id),
      individual_skill_fit(
        person,
        task,
        mode: mode,
        similarity_index: similarity_index,
      ),
    )
  let task_preference = case task_preferences {
    Some(preferences) ->
      dict_get_float(
        preferences,
        person.id,
        option_float_or(task_preference_default, 0.5),
      )
    None -> option_float_or(task_preference_default, 0.5)
  }
  let personality =
    candidate_personality_potential(
      person,
      people: people,
      team_size: task.team_size,
      mode: mode,
      personality_pair_by_people: personality_pair_by_people,
    )
  let social =
    candidate_social_potential(
      person,
      people: people,
      team_size: task.team_size,
      mode: mode,
      social_pair_by_people: social_pair_by_people,
    )

  resolved_weights.alpha
  *. skill_fit
  +. resolved_weights.gamma
  *. task_preference
  +. resolved_weights.beta
  *. personality
  +. resolved_weights.delta
  *. social
}

fn candidate_quality_score(
  candidate: List(Person),
  request request: FormationRequest,
  task task: models.Task,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  task_preferences task_preferences: Option(dict.Dict(String, Float)),
  task_preference_default task_preference_default: Option(Float),
) -> Float {
  let #(quality_score, social_score, delta_weight, _) =
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
      compat_social_preference_default: Some(0.5),
    )

  case
    mode == Compat
    && candidate_has_explicit_social_preferences(candidate) == False
  {
    True -> quality_score -. delta_weight *. social_score
    False -> quality_score
  }
}

fn candidate_personality_potential(
  person: Person,
  people people: List(Person),
  team_size team_size: Int,
  mode mode: Mode,
  personality_pair_by_people personality_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
) -> Float {
  top_partner_average(
    people
      |> list.filter(fn(teammate) { teammate.id != person.id })
      |> list.map(fn(teammate) {
        dict_get_tuple_float(
          personality_pair_by_people,
          pair_key(person.id, teammate.id),
          scoring.team_personality_score([person, teammate], mode: mode),
        )
      }),
    team_size - 1,
  )
}

fn candidate_social_potential(
  person: Person,
  people people: List(Person),
  team_size team_size: Int,
  mode mode: Mode,
  social_pair_by_people social_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
) -> Float {
  top_partner_average(
    people
      |> list.filter(fn(teammate) { teammate.id != person.id })
      |> list.map(fn(teammate) {
        dict_get_tuple_float(
          social_pair_by_people,
          pair_key(person.id, teammate.id),
          case
            mode == Compat
            && member_has_explicit_preference_for(person, teammate.id) == False
            && member_has_explicit_preference_for(teammate, person.id) == False
          {
            True -> 0.0
            False ->
              scoring.team_social_score([person, teammate], compat_default: 0.5)
          },
        )
      }),
    team_size - 1,
  )
}

fn top_partner_average(scores: List(Float), partner_count: Int) -> Float {
  case partner_count <= 0 {
    True -> 0.0

    False -> {
      let chosen =
        scores
        |> list.sort(compare_float_desc)
        |> list.take(up_to: partner_count)
      case chosen {
        [] -> 0.0
        [_, ..] ->
          list.fold(chosen, 0.0, fn(total, score) { total +. score })
          /. int.to_float(list.length(chosen))
      }
    }
  }
}

fn bounded_combinations(
  people: List(Person),
  team_size: Int,
  cap: Int,
) -> List(List(Person)) {
  bounded_combinations_loop(people, team_size, cap, [], [])
  |> list.reverse
}

fn bounded_combinations_loop(
  people: List(Person),
  remaining: Int,
  cap: Int,
  chosen_reversed: List(Person),
  found_reversed: List(List(Person)),
) -> List(List(Person)) {
  case cap <= 0 {
    True -> found_reversed

    False ->
      case remaining == 0 {
        True -> [list.reverse(chosen_reversed), ..found_reversed]

        False ->
          case people {
            [] -> found_reversed

            [person, ..rest] -> {
              let with_person =
                bounded_combinations_loop(
                  rest,
                  remaining - 1,
                  cap,
                  [person, ..chosen_reversed],
                  found_reversed,
                )
              let remaining_cap =
                cap - list.length(with_person) + list.length(found_reversed)
              bounded_combinations_loop(
                rest,
                remaining,
                remaining_cap,
                chosen_reversed,
                with_person,
              )
            }
          }
      }
  }
}

fn minimum_shortlist_size(team_size: Int, cap: Int) -> Int {
  minimum_shortlist_size_loop(team_size, cap, team_size)
}

fn minimum_shortlist_size_loop(team_size: Int, cap: Int, size: Int) -> Int {
  case combination_count(size, team_size) < cap {
    True -> minimum_shortlist_size_loop(team_size, cap, size + 1)
    False -> size
  }
}

fn bounded_shortlist_size(
  team_size team_size: Int,
  target_size target_size: Int,
  scored_combination_budget scored_combination_budget: Int,
) -> Int {
  case target_size <= team_size {
    True -> target_size

    False ->
      case
        combination_count(target_size, team_size) <= scored_combination_budget
      {
        True -> target_size
        False ->
          bounded_shortlist_size(
            team_size: team_size,
            target_size: target_size - 1,
            scored_combination_budget: scored_combination_budget,
          )
      }
  }
}

fn combination_count(n: Int, k: Int) -> Int {
  case k < 0 || k > n {
    True -> 0
    False -> combination_count_loop(n, int.min(k, n - k), 1, 1)
  }
}

fn combination_count_loop(n: Int, k: Int, step: Int, acc: Int) -> Int {
  case step > k {
    True -> acc
    False ->
      combination_count_loop(n, k, step + 1, acc * { n - k + step } / step)
  }
}

fn ceil_div(left: Int, right: Int) -> Int {
  case right <= 0 {
    True -> 0
    False -> { left + right - 1 } / right
  }
}

fn compare_ranked_person(left: RankedPerson, right: RankedPerson) -> order.Order {
  case left.score >. right.score {
    True -> order.Lt
    False ->
      case left.score <. right.score {
        True -> order.Gt
        False -> int.compare(left.index, right.index)
      }
  }
}

fn compare_scored_candidate(
  left: ScoredCandidate,
  right: ScoredCandidate,
) -> order.Order {
  case left.score >. right.score {
    True -> order.Lt
    False ->
      case left.score <. right.score {
        True -> order.Gt
        False -> int.compare(left.index, right.index)
      }
  }
}

fn compare_float_desc(left: Float, right: Float) -> order.Order {
  case left >. right {
    True -> order.Lt
    False ->
      case left <. right {
        True -> order.Gt
        False -> order.Eq
      }
  }
}

fn compare_weighted_coverage(
  left: #(Float, Float),
  right: #(Float, Float),
) -> order.Order {
  let #(left_coverage, left_importance) = left
  let #(right_coverage, right_importance) = right
  let left_weighted = left_coverage *. left_importance
  let right_weighted = right_coverage *. right_importance

  case left_weighted >. right_weighted {
    True -> order.Lt
    False ->
      case left_weighted <. right_weighted {
        True -> order.Gt
        False ->
          case left_importance >. right_importance {
            True -> order.Lt
            False ->
              case left_importance <. right_importance {
                True -> order.Gt
                False -> compare_float_desc(left_coverage, right_coverage)
              }
          }
      }
  }
}

fn explore_tasks(
  tasks tasks: List(TaskEval),
  remaining_task_count remaining_task_count: Int,
  people people: List(Person),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  max_candidate_teams max_candidate_teams: Option(Int),
  task_skill_fit_by_task_person task_skill_fit_by_task_person: dict.Dict(
    #(String, String),
    Float,
  ),
  personality_pair_by_people personality_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  social_pair_by_people social_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  upper_bound_by_task upper_bound_by_task: dict.Dict(String, Float),
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  memo memo: dict.Dict(#(Int, String), Option(SearchOutcome)),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
) -> #(
  Option(SearchOutcome),
  dict.Dict(#(Int, String), Option(SearchOutcome)),
  dict.Dict(#(String, String), ScoredTeam),
) {
  let cache_key = #(remaining_task_count, people_signature(people))

  case dict.get(memo, cache_key) {
    Ok(cached) -> #(cached, memo, score_cache)

    Error(Nil) -> {
      let #(outcome, memo_after, score_cache_after) = case tasks {
        [] -> #(
          Some(SearchOutcome(objective: 1.0, teams_reversed: [])),
          memo,
          score_cache,
        )

        [task_eval, ..rest_tasks] -> {
          let TaskEval(task:, task_preferences:, task_preference_default:) =
            task_eval
          let candidates =
            candidate_combinations_for_task(
              people: people,
              request: request,
              task: task,
              mode: mode,
              preset: preset,
              normalize_weights: normalize_weights,
              max_candidate_teams: max_candidate_teams,
              task_skill_fit_by_task_person: task_skill_fit_by_task_person,
              personality_pair_by_people: personality_pair_by_people,
              social_pair_by_people: social_pair_by_people,
              task_preferences: task_preferences,
              task_preference_default: task_preference_default,
            )

          choose_best_candidate(
            candidates: candidates,
            rest_tasks: rest_tasks,
            remaining_task_count: remaining_task_count,
            request: request,
            task: task,
            mode: mode,
            preset: preset,
            normalize_weights: normalize_weights,
            max_candidate_teams: max_candidate_teams,
            task_skill_fit_by_task_person: task_skill_fit_by_task_person,
            personality_pair_by_people: personality_pair_by_people,
            social_pair_by_people: social_pair_by_people,
            upper_bound_by_task: upper_bound_by_task,
            request_has_non_self_preferences: request_has_non_self_preferences,
            people_with_non_self_preferences: people_with_non_self_preferences,
            task_preferences: task_preferences,
            task_preference_default: task_preference_default,
            best: None,
            all_people: people,
            memo: memo,
            score_cache: score_cache,
          )
        }
      }

      let memo_final = dict.insert(memo_after, cache_key, outcome)
      #(outcome, memo_final, score_cache_after)
    }
  }
}

fn greedy_allocate_tasks(
  tasks tasks: List(TaskEval),
  people people: List(Person),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  max_candidate_teams max_candidate_teams: Option(Int),
  task_skill_fit_by_task_person task_skill_fit_by_task_person: dict.Dict(
    #(String, String),
    Float,
  ),
  personality_pair_by_people personality_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  social_pair_by_people social_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
  allocations_reversed allocations_reversed: List(TeamResult),
) -> #(Option(SearchOutcome), dict.Dict(#(String, String), ScoredTeam)) {
  case tasks {
    [] -> #(
      Some(SearchOutcome(
        objective: allocation_objective(allocations_reversed),
        teams_reversed: allocations_reversed,
      )),
      score_cache,
    )

    [task_eval, ..rest_tasks] -> {
      let TaskEval(task:, task_preferences:, task_preference_default:) =
        task_eval
      let candidates =
        candidate_combinations_for_task(
          people: people,
          request: request,
          task: task,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          max_candidate_teams: max_candidate_teams,
          task_skill_fit_by_task_person: task_skill_fit_by_task_person,
          personality_pair_by_people: personality_pair_by_people,
          social_pair_by_people: social_pair_by_people,
          task_preferences: task_preferences,
          task_preference_default: task_preference_default,
        )
      let #(best, score_cache_after) =
        best_greedy_candidate(
          candidates: candidates,
          request: request,
          task: task,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          task_preferences: task_preferences,
          task_preference_default: task_preference_default,
          score_cache: score_cache,
          best: None,
        )

      case best {
        None -> #(None, score_cache_after)

        Some(scored_team) -> {
          let ScoredTeam(team_result:, ..) = scored_team
          let remaining_people =
            remove_assigned_people(people, team_result.people)

          greedy_allocate_tasks(
            tasks: rest_tasks,
            people: remaining_people,
            request: request,
            mode: mode,
            preset: preset,
            normalize_weights: normalize_weights,
            max_candidate_teams: max_candidate_teams,
            task_skill_fit_by_task_person: task_skill_fit_by_task_person,
            personality_pair_by_people: personality_pair_by_people,
            social_pair_by_people: social_pair_by_people,
            request_has_non_self_preferences: request_has_non_self_preferences,
            people_with_non_self_preferences: people_with_non_self_preferences,
            score_cache: score_cache_after,
            allocations_reversed: [team_result, ..allocations_reversed],
          )
        }
      }
    }
  }
}

fn best_greedy_candidate(
  candidates candidates: List(List(Person)),
  request request: FormationRequest,
  task task: models.Task,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  task_preferences task_preferences: Option(dict.Dict(String, Float)),
  task_preference_default task_preference_default: Option(Float),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
  best best: Option(ScoredTeam),
) -> #(Option(ScoredTeam), dict.Dict(#(String, String), ScoredTeam)) {
  case candidates {
    [] -> #(best, score_cache)

    [candidate, ..rest] -> {
      let has_team_social_preferences =
        candidate_social_preferences_present(
          candidate,
          mode: mode,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
        )
      let social_preference_default = case mode {
        Compat ->
          case has_team_social_preferences {
            True -> Some(0.5)
            False -> Some(0.0)
          }

        _ -> None
      }
      let #(scored_team, score_cache_after) =
        score_team_cached(
          candidate,
          request: request,
          task: task,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          task_preferences: task_preferences,
          task_preference_default: task_preference_default,
          social_preference_default: social_preference_default,
          has_team_social_preferences: has_team_social_preferences,
          score_cache: score_cache,
        )

      best_greedy_candidate(
        candidates: rest,
        request: request,
        task: task,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        task_preferences: task_preferences,
        task_preference_default: task_preference_default,
        score_cache: score_cache_after,
        best: better_scored_team(best, Some(scored_team)),
      )
    }
  }
}

fn better_scored_team(
  left: Option(ScoredTeam),
  right: Option(ScoredTeam),
) -> Option(ScoredTeam) {
  case left, right {
    None, None -> None
    Some(best), None -> Some(best)
    None, Some(candidate) -> Some(candidate)
    Some(best), Some(candidate) -> {
      let ScoredTeam(quality: best_quality, ..) = best
      let ScoredTeam(quality: candidate_quality, ..) = candidate
      case candidate_quality >. best_quality {
        True -> Some(candidate)
        False -> Some(best)
      }
    }
  }
}

fn allocation_objective(allocations: List(TeamResult)) -> Float {
  list.fold(allocations, 1.0, fn(total, allocation) {
    total *. allocation.quality
  })
}

fn remove_assigned_people(
  people: List(Person),
  assigned: List(models.AssignedPerson),
) -> List(Person) {
  let assigned_ids =
    assigned
    |> list.map(fn(person) { person.id })
    |> set.from_list

  remove_people_with_set(people, assigned_ids)
}

fn improve_outcome(
  outcome: SearchOutcome,
  task_evals task_evals: List(TaskEval),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
  rounds_remaining rounds_remaining: Int,
) -> SearchOutcome {
  case rounds_remaining <= 0 {
    True -> outcome

    False -> {
      let unused_people = unused_people_for_outcome(request.people, outcome)
      let #(best_outcome, score_cache_after) =
        best_improvement(
          current: outcome,
          task_evals: task_evals,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          score_cache: score_cache,
          unused_people: unused_people,
        )

      case best_outcome.objective >. outcome.objective {
        True ->
          improve_outcome(
            best_outcome,
            task_evals: task_evals,
            request: request,
            mode: mode,
            preset: preset,
            normalize_weights: normalize_weights,
            request_has_non_self_preferences: request_has_non_self_preferences,
            people_with_non_self_preferences: people_with_non_self_preferences,
            score_cache: score_cache_after,
            rounds_remaining: rounds_remaining - 1,
          )

        False -> outcome
      }
    }
  }
}

fn best_improvement(
  current current: SearchOutcome,
  task_evals task_evals: List(TaskEval),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
  unused_people unused_people: List(Person),
) -> #(SearchOutcome, dict.Dict(#(String, String), ScoredTeam)) {
  let #(unused_best, cache_after_unused) = case unused_people {
    [] -> #(current, score_cache)

    [_, ..] ->
      best_unused_replacement(
        current.teams_reversed,
        current: current,
        task_evals: task_evals,
        request: request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        score_cache: score_cache,
        unused_people: unused_people,
        best: current,
      )
  }

  case pairwise_swap_count(current.teams_reversed) <= max_pairwise_swap_moves {
    True ->
      best_pairwise_swap(
        current.teams_reversed,
        current: current,
        task_evals: task_evals,
        request: request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        score_cache: cache_after_unused,
        best: unused_best,
      )

    False -> #(unused_best, cache_after_unused)
  }
}

fn best_unused_replacement(
  teams: List(TeamResult),
  current current: SearchOutcome,
  task_evals task_evals: List(TaskEval),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
  unused_people unused_people: List(Person),
  best best: SearchOutcome,
) -> #(SearchOutcome, dict.Dict(#(String, String), ScoredTeam)) {
  case teams {
    [] -> #(best, score_cache)

    [team, ..rest] -> {
      let #(team_best, cache_after_team) =
        best_unused_replacement_for_team(
          team,
          member_ids: assigned_ids(team.people),
          current: current,
          task_evals: task_evals,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          score_cache: score_cache,
          unused_people: unused_people,
          best: best,
        )

      best_unused_replacement(
        rest,
        current: current,
        task_evals: task_evals,
        request: request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        score_cache: cache_after_team,
        unused_people: unused_people,
        best: team_best,
      )
    }
  }
}

fn best_unused_replacement_for_team(
  team: TeamResult,
  member_ids member_ids: List(String),
  current current: SearchOutcome,
  task_evals task_evals: List(TaskEval),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
  unused_people unused_people: List(Person),
  best best: SearchOutcome,
) -> #(SearchOutcome, dict.Dict(#(String, String), ScoredTeam)) {
  case member_ids {
    [] -> #(best, score_cache)

    [member_id, ..rest_members] -> {
      let #(member_best, cache_after_member) =
        best_unused_replacement_for_member(
          team,
          replaced_member_id: member_id,
          current: current,
          task_evals: task_evals,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          score_cache: score_cache,
          unused_people: unused_people,
          best: best,
        )

      best_unused_replacement_for_team(
        team,
        member_ids: rest_members,
        current: current,
        task_evals: task_evals,
        request: request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        score_cache: cache_after_member,
        unused_people: unused_people,
        best: member_best,
      )
    }
  }
}

fn best_unused_replacement_for_member(
  team: TeamResult,
  replaced_member_id replaced_member_id: String,
  current current: SearchOutcome,
  task_evals task_evals: List(TaskEval),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
  unused_people unused_people: List(Person),
  best best: SearchOutcome,
) -> #(SearchOutcome, dict.Dict(#(String, String), ScoredTeam)) {
  case unused_people {
    [] -> #(best, score_cache)

    [replacement, ..rest] -> {
      let replacement_ids =
        replace_id(
          assigned_ids(team.people),
          replaced_member_id,
          replacement.id,
        )
      let #(candidate, cache_after_candidate) =
        rescore_team_ids(
          task_id: team.task_id,
          people_ids: replacement_ids,
          task_evals: task_evals,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          score_cache: score_cache,
        )
      let next_best =
        better_outcome_value(
          best,
          outcome_with_replaced_team(current, candidate),
        )

      best_unused_replacement_for_member(
        team,
        replaced_member_id: replaced_member_id,
        current: current,
        task_evals: task_evals,
        request: request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        score_cache: cache_after_candidate,
        unused_people: rest,
        best: next_best,
      )
    }
  }
}

fn pairwise_swap_count(teams: List(TeamResult)) -> Int {
  case teams {
    [] -> 0
    [_] -> 0

    [team, ..rest] ->
      list.length(team.people)
      * total_member_count(rest)
      + pairwise_swap_count(rest)
  }
}

fn total_member_count(teams: List(TeamResult)) -> Int {
  list.fold(teams, 0, fn(total, team) { total + list.length(team.people) })
}

fn best_pairwise_swap(
  teams: List(TeamResult),
  current current: SearchOutcome,
  task_evals task_evals: List(TaskEval),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
  best best: SearchOutcome,
) -> #(SearchOutcome, dict.Dict(#(String, String), ScoredTeam)) {
  case teams {
    [] -> #(best, score_cache)
    [_] -> #(best, score_cache)

    [team, ..rest] -> {
      let #(best_with_team, cache_after_team) =
        best_pairwise_swap_for_team(
          team,
          rest,
          current: current,
          task_evals: task_evals,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          score_cache: score_cache,
          best: best,
        )

      best_pairwise_swap(
        rest,
        current: current,
        task_evals: task_evals,
        request: request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        score_cache: cache_after_team,
        best: best_with_team,
      )
    }
  }
}

fn best_pairwise_swap_for_team(
  left: TeamResult,
  right_teams: List(TeamResult),
  current current: SearchOutcome,
  task_evals task_evals: List(TaskEval),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
  best best: SearchOutcome,
) -> #(SearchOutcome, dict.Dict(#(String, String), ScoredTeam)) {
  case right_teams {
    [] -> #(best, score_cache)

    [right, ..rest] -> {
      let #(pair_best, cache_after_pair) =
        best_member_swaps(
          left,
          right,
          left_member_ids: assigned_ids(left.people),
          right_member_ids: assigned_ids(right.people),
          current: current,
          task_evals: task_evals,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          score_cache: score_cache,
          best: best,
        )

      best_pairwise_swap_for_team(
        left,
        rest,
        current: current,
        task_evals: task_evals,
        request: request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        score_cache: cache_after_pair,
        best: pair_best,
      )
    }
  }
}

fn best_member_swaps(
  left: TeamResult,
  right: TeamResult,
  left_member_ids left_member_ids: List(String),
  right_member_ids right_member_ids: List(String),
  current current: SearchOutcome,
  task_evals task_evals: List(TaskEval),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
  best best: SearchOutcome,
) -> #(SearchOutcome, dict.Dict(#(String, String), ScoredTeam)) {
  case left_member_ids {
    [] -> #(best, score_cache)

    [left_member_id, ..rest_left] -> {
      let #(member_best, cache_after_member) =
        best_member_swaps_for_left_member(
          left,
          right,
          left_member_id: left_member_id,
          right_member_ids: right_member_ids,
          current: current,
          task_evals: task_evals,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          score_cache: score_cache,
          best: best,
        )

      best_member_swaps(
        left,
        right,
        left_member_ids: rest_left,
        right_member_ids: right_member_ids,
        current: current,
        task_evals: task_evals,
        request: request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        score_cache: cache_after_member,
        best: member_best,
      )
    }
  }
}

fn best_member_swaps_for_left_member(
  left: TeamResult,
  right: TeamResult,
  left_member_id left_member_id: String,
  right_member_ids right_member_ids: List(String),
  current current: SearchOutcome,
  task_evals task_evals: List(TaskEval),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
  best best: SearchOutcome,
) -> #(SearchOutcome, dict.Dict(#(String, String), ScoredTeam)) {
  case right_member_ids {
    [] -> #(best, score_cache)

    [right_member_id, ..rest_right] -> {
      let left_ids =
        replace_id(assigned_ids(left.people), left_member_id, right_member_id)
      let right_ids =
        replace_id(assigned_ids(right.people), right_member_id, left_member_id)
      let #(left_candidate, cache_after_left) =
        rescore_team_ids(
          task_id: left.task_id,
          people_ids: left_ids,
          task_evals: task_evals,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          score_cache: score_cache,
        )
      let #(right_candidate, cache_after_right) =
        rescore_team_ids(
          task_id: right.task_id,
          people_ids: right_ids,
          task_evals: task_evals,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          score_cache: cache_after_left,
        )
      let next_best =
        better_outcome_value(
          best,
          outcome_with_two_replaced_teams(
            current,
            left_candidate,
            right_candidate,
          ),
        )

      best_member_swaps_for_left_member(
        left,
        right,
        left_member_id: left_member_id,
        right_member_ids: rest_right,
        current: current,
        task_evals: task_evals,
        request: request,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        score_cache: cache_after_right,
        best: next_best,
      )
    }
  }
}

fn rescore_team_ids(
  task_id task_id: String,
  people_ids people_ids: List(String),
  task_evals task_evals: List(TaskEval),
  request request: FormationRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
) -> #(TeamResult, dict.Dict(#(String, String), ScoredTeam)) {
  let task_eval = task_eval_by_id(task_evals, task_id)
  let people = people_by_ids(request.people, people_ids)

  case task_eval {
    Some(TaskEval(task:, task_preferences:, task_preference_default:)) -> {
      let has_team_social_preferences =
        candidate_social_preferences_present(
          people,
          mode: mode,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
        )
      let social_preference_default = case mode {
        Compat ->
          case has_team_social_preferences {
            True -> Some(0.5)
            False -> Some(0.0)
          }

        _ -> None
      }
      let #(scored_team, cache_after) =
        score_team_cached(
          people,
          request: request,
          task: task,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          task_preferences: task_preferences,
          task_preference_default: task_preference_default,
          social_preference_default: social_preference_default,
          has_team_social_preferences: has_team_social_preferences,
          score_cache: score_cache,
        )
      let ScoredTeam(team_result:, ..) = scored_team
      #(team_result, cache_after)
    }

    None -> #(
      TeamResult(task_id: task_id, people: [], quality: 0.0),
      score_cache,
    )
  }
}

fn outcome_with_replaced_team(
  current: SearchOutcome,
  replacement: TeamResult,
) -> SearchOutcome {
  let teams =
    list.map(current.teams_reversed, fn(team) {
      case team.task_id == replacement.task_id {
        True -> replacement
        False -> team
      }
    })

  SearchOutcome(objective: allocation_objective(teams), teams_reversed: teams)
}

fn outcome_with_two_replaced_teams(
  current: SearchOutcome,
  left: TeamResult,
  right: TeamResult,
) -> SearchOutcome {
  let teams =
    list.map(current.teams_reversed, fn(team) {
      case team.task_id == left.task_id {
        True -> left
        False ->
          case team.task_id == right.task_id {
            True -> right
            False -> team
          }
      }
    })

  SearchOutcome(objective: allocation_objective(teams), teams_reversed: teams)
}

fn better_outcome_value(
  left: SearchOutcome,
  right: SearchOutcome,
) -> SearchOutcome {
  case right.objective >. left.objective {
    True -> right
    False -> left
  }
}

fn unused_people_for_outcome(
  people: List(Person),
  outcome: SearchOutcome,
) -> List(Person) {
  let assigned_ids_set =
    outcome.teams_reversed
    |> list.flat_map(fn(team) { assigned_ids(team.people) })
    |> set.from_list

  list.filter(people, fn(person) {
    set.contains(assigned_ids_set, person.id) == False
  })
}

fn assigned_ids(assigned: List(models.AssignedPerson)) -> List(String) {
  list.map(assigned, fn(person) { person.id })
}

fn replace_id(
  ids: List(String),
  from old_id: String,
  to new_id: String,
) -> List(String) {
  list.map(ids, fn(id) {
    case id == old_id {
      True -> new_id
      False -> id
    }
  })
}

fn task_eval_by_id(
  task_evals: List(TaskEval),
  task_id: String,
) -> Option(TaskEval) {
  case task_evals {
    [] -> None

    [task_eval, ..rest] -> {
      let TaskEval(task:, ..) = task_eval
      case task.id == task_id {
        True -> Some(task_eval)
        False -> task_eval_by_id(rest, task_id)
      }
    }
  }
}

fn people_by_ids(people: List(Person), ids: List(String)) -> List(Person) {
  case ids {
    [] -> []

    [id, ..rest] ->
      case person_by_id(people, id) {
        Some(person) -> [person, ..people_by_ids(people, rest)]
        None -> people_by_ids(people, rest)
      }
  }
}

fn person_by_id(people: List(Person), id: String) -> Option(Person) {
  case people {
    [] -> None

    [person, ..rest] ->
      case person.id == id {
        True -> Some(person)
        False -> person_by_id(rest, id)
      }
  }
}

fn choose_best_candidate(
  candidates candidates: List(List(Person)),
  rest_tasks rest_tasks: List(TaskEval),
  remaining_task_count remaining_task_count: Int,
  request request: FormationRequest,
  task task: models.Task,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  max_candidate_teams max_candidate_teams: Option(Int),
  task_skill_fit_by_task_person task_skill_fit_by_task_person: dict.Dict(
    #(String, String),
    Float,
  ),
  personality_pair_by_people personality_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  social_pair_by_people social_pair_by_people: dict.Dict(
    #(String, String),
    Float,
  ),
  upper_bound_by_task upper_bound_by_task: dict.Dict(String, Float),
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
  task_preferences task_preferences: Option(dict.Dict(String, Float)),
  task_preference_default task_preference_default: Option(Float),
  best best: Option(SearchOutcome),
  all_people all_people: List(Person),
  memo memo: dict.Dict(#(Int, String), Option(SearchOutcome)),
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
) -> #(
  Option(SearchOutcome),
  dict.Dict(#(Int, String), Option(SearchOutcome)),
  dict.Dict(#(String, String), ScoredTeam),
) {
  case candidates {
    [] -> #(best, memo, score_cache)

    [candidate, ..rest_candidates] -> {
      let has_team_social_preferences = case mode {
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

                True -> candidate_has_explicit_social_preferences(candidate)
              }
            }
          }

        _ -> False
      }

      let social_preference_default = case mode {
        Compat ->
          case has_team_social_preferences {
            True -> Some(0.5)
            False -> Some(0.0)
          }

        _ -> None
      }

      let #(scored_team, score_cache_after_score) =
        score_team_cached(
          candidate,
          request: request,
          task: task,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          task_preferences: task_preferences,
          task_preference_default: task_preference_default,
          social_preference_default: social_preference_default,
          has_team_social_preferences: has_team_social_preferences,
          score_cache: score_cache,
        )
      let ScoredTeam(team_result:, quality: adjusted_quality) = scored_team

      // Do not branch-and-bound here: a task's best team quality can be
      // higher than any single-person shortlist score when members have
      // complementary skills/preferences. Using the old per-person upper
      // bound could prune the globally optimal allocation.
      let remaining_people = remove_people(all_people, candidate)
      let #(child_outcome, memo_after, score_cache_after_child) =
        explore_tasks(
          tasks: rest_tasks,
          remaining_task_count: remaining_task_count - 1,
          people: remaining_people,
          request: request,
          mode: mode,
          preset: preset,
          normalize_weights: normalize_weights,
          max_candidate_teams: max_candidate_teams,
          task_skill_fit_by_task_person: task_skill_fit_by_task_person,
          personality_pair_by_people: personality_pair_by_people,
          social_pair_by_people: social_pair_by_people,
          upper_bound_by_task: upper_bound_by_task,
          request_has_non_self_preferences: request_has_non_self_preferences,
          people_with_non_self_preferences: people_with_non_self_preferences,
          memo: memo,
          score_cache: score_cache_after_score,
        )
      let candidate_outcome = case child_outcome {
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
      let memo_after_child = memo_after

      choose_best_candidate(
        candidates: rest_candidates,
        rest_tasks: rest_tasks,
        remaining_task_count: remaining_task_count,
        request: request,
        task: task,
        mode: mode,
        preset: preset,
        normalize_weights: normalize_weights,
        max_candidate_teams: max_candidate_teams,
        task_skill_fit_by_task_person: task_skill_fit_by_task_person,
        personality_pair_by_people: personality_pair_by_people,
        social_pair_by_people: social_pair_by_people,
        upper_bound_by_task: upper_bound_by_task,
        request_has_non_self_preferences: request_has_non_self_preferences,
        people_with_non_self_preferences: people_with_non_self_preferences,
        task_preferences: task_preferences,
        task_preference_default: task_preference_default,
        best: new_best,
        all_people: all_people,
        memo: memo_after_child,
        score_cache: score_cache_after_child,
      )
    }
  }
}

fn score_team_cached(
  candidate: List(Person),
  request request: FormationRequest,
  task task: models.Task,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  task_preferences task_preferences: Option(dict.Dict(String, Float)),
  task_preference_default task_preference_default: Option(Float),
  social_preference_default social_preference_default: Option(Float),
  has_team_social_preferences has_team_social_preferences: Bool,
  score_cache score_cache: dict.Dict(#(String, String), ScoredTeam),
) -> #(ScoredTeam, dict.Dict(#(String, String), ScoredTeam)) {
  let cache_key = #(task.id, sorted_people_signature(candidate))

  case dict.get(score_cache, cache_key) {
    Ok(scored_team) -> #(scored_team, score_cache)

    Error(Nil) -> {
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
      let adjusted_quality = case
        mode == Compat && has_team_social_preferences == False
      {
        True -> quality_score -. delta_weight *. social_score
        False -> quality_score
      }
      let assigned = scoring.assigned_people_from_assignments(assignments)
      let scored_team =
        ScoredTeam(
          team_result: TeamResult(
            task_id: task.id,
            people: assigned,
            quality: adjusted_quality,
          ),
          quality: adjusted_quality,
        )

      #(scored_team, dict.insert(score_cache, cache_key, scored_team))
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

fn remove_people(
  all_people: List(Person),
  used_people: List(Person),
) -> List(Person) {
  case used_people {
    [] -> all_people

    [first] -> remove_people_with_ids_1(all_people, first.id)

    [first, second] -> remove_people_with_ids_2(all_people, first.id, second.id)

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
      let should_remove =
        person.id == id1 || person.id == id2 || person.id == id3
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

fn candidate_has_explicit_social_preferences(candidate: List(Person)) -> Bool {
  case candidate {
    [first, second] ->
      member_has_explicit_preference_for(first, second.id)
      || member_has_explicit_preference_for(second, first.id)

    _ -> {
      let teammate_ids =
        set.from_list(list.map(candidate, fn(member) { member.id }))

      list.any(candidate, fn(member) {
        has_explicit_social_preferences(member, teammate_ids)
      })
    }
  }
}

fn candidate_social_preferences_present(
  candidate: List(Person),
  mode mode: Mode,
  request_has_non_self_preferences request_has_non_self_preferences: Bool,
  people_with_non_self_preferences people_with_non_self_preferences: set.Set(
    String,
  ),
) -> Bool {
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
            True -> candidate_has_explicit_social_preferences(candidate)
          }
        }
      }

    _ -> False
  }
}

fn member_has_explicit_preference_for(
  member: Person,
  teammate_id: String,
) -> Bool {
  case member.preferences {
    Some(preferences) ->
      list.any(preferences, fn(preference) {
        preference.person_id == teammate_id
      })

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

fn dict_get_int(
  mapping: dict.Dict(String, Int),
  key: String,
  fallback: Int,
) -> Int {
  case dict.get(mapping, key) {
    Ok(value) -> value
    Error(Nil) -> fallback
  }
}

fn dict_get_float(
  mapping: dict.Dict(String, Float),
  key: String,
  fallback: Float,
) -> Float {
  case dict.get(mapping, key) {
    Ok(value) -> value
    Error(Nil) -> fallback
  }
}

fn dict_get_tuple_float(
  mapping: dict.Dict(#(String, String), Float),
  key: #(String, String),
  fallback: Float,
) -> Float {
  case dict.get(mapping, key) {
    Ok(value) -> value
    Error(Nil) -> fallback
  }
}

fn pair_key(left: String, right: String) -> #(String, String) {
  case string.compare(left, right) {
    order.Gt -> #(right, left)
    _ -> #(left, right)
  }
}

fn option_float_or(value: Option(Float), fallback: Float) -> Float {
  case value {
    Some(found) -> found
    None -> fallback
  }
}

fn people_signature(people: List(Person)) -> String {
  case people {
    [] -> ""
    [first] -> first.id
    [first, second] -> first.id <> "," <> second.id
    [first, second, third] -> first.id <> "," <> second.id <> "," <> third.id

    [first, second, third, fourth] ->
      first.id <> "," <> second.id <> "," <> third.id <> "," <> fourth.id

    [first, second, third, fourth, fifth] ->
      first.id
      <> ","
      <> second.id
      <> ","
      <> third.id
      <> ","
      <> fourth.id
      <> ","
      <> fifth.id

    [first, second, third, fourth, fifth, sixth] ->
      first.id
      <> ","
      <> second.id
      <> ","
      <> third.id
      <> ","
      <> fourth.id
      <> ","
      <> fifth.id
      <> ","
      <> sixth.id

    _ ->
      people
      |> list.map(fn(person) { person.id })
      |> string.join(with: ",")
  }
}

fn sorted_people_signature(people: List(Person)) -> String {
  people
  |> list.map(fn(person) { person.id })
  |> list.sort(string.compare)
  |> string.join(with: ",")
}
