import gleam/dict
import gleam/float
import gleam/int
import gleam/list
import gleam/option.{type Option, None, Some}
import gleam/set
import team2form_gleam/math
import team2form_gleam/models.{
  AssignedPerson,
  Female,
  Male,
  QualityBreakdown,
  TeamMember,
  TeamQualityRequest,
  team_member_to_person,
  type AssignedPerson,
  type Person,
  type PersonPreference,
  type Personality,
  type QualityBreakdown,
  type Similarity,
  type Task,
  type TaskPreference,
  type TaskSkill,
  type TeamMember,
  type TeamQualityRequest,
}
import team2form_gleam/modes.{Compat, Paper, type Mode, type WeightPreset}
import team2form_gleam/weights.{type Weights, resolve_weights}

pub const epsilon = 1.0e-12
const compat_gender_bonus_balanced = 0.075
const compat_gender_bonus_one_unknown = 0.05303300858899106
const pi = 3.141592653589793

pub type AssignmentResult {
  AssignmentResult(assignments: dict.Dict(String, List(String)), skill_score: Float)
}

type TeamQualityComponents {
  TeamQualityComponents(
    quality: Float,
    skill_score: Float,
    personality_score: Float,
    task_preference_score: Float,
    social_score: Float,
    assignments: dict.Dict(String, List(String)),
    weights: Weights,
  )
}

type MemberAssignmentState {
  MemberAssignmentState(member: Person, assigned: List(TaskSkill))
}

type UniqueState {
  UniqueState(score: Float, choice: Int)
}

pub fn geometric_mean(values: List(Float)) -> Float {
  case values {
    [] -> 0.0
    [_, ..] -> {
      let has_non_positive = list.any(values, fn(value) { value <=. 0.0 })
      case has_non_positive {
        True -> 0.0
        False -> {
          let count = list.length(values)
          let log_sum =
            list.fold(values, 0.0, fn(total, value) {
              total +. safe_log(value)
            })

          float.exponential(log_sum /. int.to_float(count))
        }
      }
    }
  }
}

pub fn weighted_geometric_mean(values: List(#(Float, Float))) -> Float {
  let weighted = list.filter(values, fn(item) {
    let #(_, weight) = item
    weight >. 0.0
  })

  case weighted {
    [] -> 0.0
    [_, ..] -> {
      let has_non_positive = list.any(weighted, fn(item) {
        let #(value, _) = item
        value <=. 0.0
      })
      let total_weight =
        list.fold(weighted, 0.0, fn(total, item) {
          let #(_, weight) = item
          total +. weight
        })

      case has_non_positive || total_weight <=. 0.0 {
        True -> 0.0
        False -> {
          let weighted_log_sum =
            list.fold(weighted, 0.0, fn(total, item) {
              let #(value, weight) = item
              let proportion = weight /. total_weight
              total +. proportion *. safe_log(value)
            })

          float.exponential(weighted_log_sum)
        }
      }
    }
  }
}

fn safe_log(value: Float) -> Float {
  case float.logarithm(value) {
    Ok(logged) -> logged
    Error(Nil) -> 0.0
  }
}

pub fn preference_lookup_person(
  preferences: Option(List(PersonPreference)),
) -> dict.Dict(String, Float) {
  case preferences {
    Some(items) ->
      list.fold(items, dict.new(), fn(found, preference) {
        dict.insert(found, preference.person_id, preference.preference)
      })

    None -> dict.new()
  }
}

pub fn preference_lookup_task(
  preferences: Option(List(TaskPreference)),
) -> dict.Dict(String, Float) {
  case preferences {
    Some(items) ->
      list.fold(items, dict.new(), fn(found, preference) {
        dict.insert(found, preference.person_id, preference.preference)
      })

    None -> dict.new()
  }
}

pub fn similarity_lookup(
  similarities: Option(List(Similarity)),
) -> dict.Dict(#(String, String), Float) {
  case similarities {
    Some(items) ->
      list.fold(items, dict.new(), fn(found, similarity) {
        dict.insert(
          found,
          #(similarity.source_id, similarity.target_id),
          similarity.similarity,
        )
      })

    None -> dict.new()
  }
}

pub fn task_preference_for_member(
  member: TeamMember,
  compat_default compat_default: Float,
) -> Float {
  case member.task_preference {
    Some(value) -> value
    None -> compat_default
  }
}

fn calculate_task_preference_score(
  team: List(Person),
  task_preferences: Option(dict.Dict(String, Float)),
  compat_default compat_default: Float,
) -> Float {
  case team {
    [] -> 0.0
    [_, ..] ->
      case task_preferences {
        Some(preferences) ->
          geometric_mean(
            list.map(team, fn(member) {
              dict_get_or(preferences, member.id, compat_default)
            }),
          )

        None -> compat_default
      }
  }
}

pub fn social_preference_for_pair(
  member: Person,
  teammate_id: String,
  compat_default compat_default: Float,
) -> Float {
  case member.id == teammate_id {
    True -> 1.0
    False -> {
      let mapping = preference_lookup_person(member.preferences)
      dict_get_or(mapping, teammate_id, compat_default)
    }
  }
}

pub fn team_task_preferences(
  team: List(TeamMember),
  compat_default compat_default: Float,
) -> Float {
  geometric_mean(
    list.map(team, fn(member) {
      task_preference_for_member(member, compat_default: compat_default)
    }),
  )
}

pub fn team_social_score(
  team: List(Person),
  compat_default compat_default: Float,
) -> Float {
  case team {
    [] -> 0.0
    [_] -> 0.0
    [first_member, second_member] -> {
      let first_pair =
        social_preference_for_pair(
          first_member,
          second_member.id,
          compat_default: compat_default,
        )
      let second_pair =
        social_preference_for_pair(
          second_member,
          first_member.id,
          compat_default: compat_default,
        )
      let first_score = 1.0 +. first_pair
      let second_score = 1.0 +. second_pair
      let product = first_score *. second_score
      math.sqrt(product /. 4.0)
    }

    [_, _, ..] -> {
      let teammate_ids = list.map(team, fn(member) { member.id })
      let member_scores =
        list.map(team, fn(member) {
          let mapping = preference_lookup_person(member.preferences)
          let total =
            list.fold(teammate_ids, 0.0, fn(acc, teammate_id) {
              let value =
                case teammate_id == member.id {
                  True -> 1.0
                  False -> dict_get_or(mapping, teammate_id, compat_default)
                }

              acc +. value
            })

          total /. int.to_float(list.length(team))
        })

      geometric_mean(member_scores)
    }
  }
}

fn population_stddev(values: List(Float)) -> Float {
  case values {
    [] -> 0.0
    [_, ..] -> {
      let count = int.to_float(list.length(values))
      let mean = list.fold(values, 0.0, fn(total, value) { total +. value }) /. count
      let variance =
        list.fold(values, 0.0, fn(total, value) {
          let diff = value -. mean
          total +. diff *. diff
        }) /. count

      math.sqrt(variance)
    }
  }
}

pub fn team_personality_score(team: List(Person), mode mode: Mode) -> Float {
  case team {
    [] -> 0.0
    [_] -> 0.0
    [first_member, second_member] -> {
      let first = first_member.personality
      let second = second_member.personality
      let sn_stddev = float.absolute_value(first.sn -. second.sn) /. 2.0
      let tf_stddev = float.absolute_value(first.tf -. second.tf) /. 2.0

      case mode {
        Compat -> {
          let diversity = 0.75 *. sn_stddev *. tf_stddev
          let best_etj = float.max(compat_etj(first), compat_etj(second))
          let best_introvert =
            float.max(compat_introvert(first), compat_introvert(second))

          diversity
          +. 0.2475 *. best_etj
          +. 0.2475 *. best_introvert
          +. compat_gender_bonus(team)
        }

        Paper -> {
          let diversity = sn_stddev *. tf_stddev
          let best_etj = float.max(paper_etj(first), paper_etj(second))
          let best_introvert =
            float.max(paper_introvert(first), paper_introvert(second))
          let gender_bonus =
            case first_member.gender != None
              && second_member.gender != None
              && first_member.gender != second_member.gender
            {
              True -> 0.1
              False -> 0.0
            }

          diversity +. best_etj +. best_introvert +. gender_bonus
        }
      }
    }

    [_, _, ..] -> {
      let sn_values = list.map(team, fn(member) { member.personality.sn })
      let tf_values = list.map(team, fn(member) { member.personality.tf })
      let best_compat_etj =
        list.fold(team, 0.0, fn(best, member) {
          float.max(best, compat_etj(member.personality))
        })
      let best_paper_etj =
        list.fold(team, 0.0, fn(best, member) {
          float.max(best, paper_etj(member.personality))
        })
      let best_compat_introvert =
        list.fold(team, 0.0, fn(best, member) {
          float.max(best, compat_introvert(member.personality))
        })
      let best_paper_introvert =
        list.fold(team, 0.0, fn(best, member) {
          float.max(best, paper_introvert(member.personality))
        })
      let declared_genders =
        list.fold(team, set.new(), fn(found, member) {
          case member.gender {
            Some(gender) -> set.insert(found, gender)
            None -> found
          }
        })

      let sn_stddev = population_stddev(sn_values)
      let tf_stddev = population_stddev(tf_values)

      case mode {
        Compat ->
          0.75 *. sn_stddev *. tf_stddev
          +. 0.2475 *. best_compat_etj
          +. 0.2475 *. best_compat_introvert
          +. compat_gender_bonus(team)

        Paper -> {
          let gender_bonus =
            case set.size(declared_genders) > 1 {
              True -> 0.1
              False -> 0.0
            }

          sn_stddev *. tf_stddev +. best_paper_etj +. best_paper_introvert +. gender_bonus
        }
      }
    }
  }
}

fn compat_etj(personality: Personality) -> Float {
  case personality.ei >. 0.0 && personality.tf >. 0.0 && personality.pj >. 0.0 {
    True -> personality.ei +. personality.tf +. personality.pj |> divide_by_three
    False -> 0.0
  }
}

fn paper_etj(personality: Personality) -> Float {
  case personality.ei >. 0.0 && personality.tf >. 0.0 && personality.pj >. 0.0 {
    True -> {
      let summed = personality.ei +. personality.tf +. personality.pj
      0.19 *. summed
    }
    False -> 0.0
  }
}

fn divide_by_three(value: Float) -> Float {
  value /. 3.0
}

fn compat_introvert(personality: Personality) -> Float {
  float.max(0.0 -. personality.ei, 0.0)
}

fn paper_introvert(personality: Personality) -> Float {
  let inverted = 0.0 -. personality.ei
  float.max(0.19 *. inverted, 0.0)
}

fn compat_gender_bonus(team: List(Person)) -> Float {
  case team {
    [] -> 0.0
    [_] -> 0.0
    [first_member, second_member] ->
      case first_member.gender, second_member.gender {
        None, None -> compat_gender_bonus_balanced
        Some(first_gender), Some(second_gender) ->
          case first_gender == second_gender {
            True -> 0.0
            False -> compat_gender_bonus_balanced
          }
        _, _ -> compat_gender_bonus_one_unknown
      }

    [_, _, ..] -> {
      let female_count =
        int.to_float(
          list.count(team, where: fn(member) {
            member.gender == Some(Female)
          }),
        )
      let male_count =
        int.to_float(
          list.count(team, where: fn(member) {
            member.gender == Some(Male)
          }),
        )
      let total = int.to_float(list.length(team))
      let missing_count = total -. female_count -. male_count
      let effective_female = female_count +. 0.5 *. missing_count
      let effective_male = male_count +. 0.5 *. missing_count
      let minority_fraction = float.min(effective_female, effective_male) /. total

      0.075 *. math.sin(pi *. minority_fraction)
    }
  }
}

pub fn skill_similarity(
  task_skill_id: String,
  person_skill_id: String,
  mode mode: Mode,
  lookup lookup: dict.Dict(#(String, String), Float),
) -> Float {
  case task_skill_id == person_skill_id {
    True -> 1.0
    False ->
      case mode {
        Compat -> 0.0
        Paper -> dict_get_or_pair(lookup, #(person_skill_id, task_skill_id), 0.0)
      }
  }
}

pub fn coverage_for_person_and_task_skill(
  person: Person,
  task_skill: TaskSkill,
  mode mode: Mode,
  similarity_index similarity_index: dict.Dict(#(String, String), Float),
) -> Float {
  list.fold(person.skills, 0.0, fn(best, person_skill) {
    let similarity =
      skill_similarity(
        task_skill.id,
        person_skill.id,
        mode: mode,
        lookup: similarity_index,
      )

    case similarity <=. 0.0 {
      True -> best
      False -> {
        let candidate =
          case mode {
            Compat -> float.min(person_skill.level *. similarity, 1.0)
            Paper -> {
              let required = float.max(task_skill.level, epsilon)
              float.min(person_skill.level *. similarity /. required, 1.0)
            }
          }

        float.max(best, candidate)
      }
    }
  })
}

pub fn assign_task_skills(
  task_skills: List(TaskSkill),
  team: List(Person),
  mode mode: Mode,
  similarities similarities: Option(List(Similarity)),
) -> AssignmentResult {
  case task_skills, team {
    [], _ ->
      AssignmentResult(
        assignments:
          list.fold(team, dict.new(), fn(found, member) {
            dict.insert(found, member.id, [])
          }),
        skill_score: 0.0,
      )

    _, [] -> AssignmentResult(assignments: dict.new(), skill_score: 0.0)

    _, _ -> {
      let similarity_index = similarity_lookup(similarities)
      let equal_partition = list.length(task_skills) == list.length(team)
      case equal_partition {
        True ->
          assign_task_skills_unique(
            task_skills,
            team,
            mode: mode,
            similarity_index: similarity_index,
          )

        False ->
          case mode == Compat && list.length(team) > list.length(task_skills) {
            True ->
              assign_task_skills_compat_overfull(
                task_skills,
                team,
                similarity_index: similarity_index,
              )

            False -> {
              let states =
                list.map(team, fn(member) {
                  MemberAssignmentState(member: member, assigned: [])
                })
              let max_per_member = ceil_div(list.length(task_skills), list.length(team))
              let require_all_members = list.length(task_skills) >= list.length(team)

              assign_search(
                remaining_skills: task_skills,
                states: states,
                max_per_member: max_per_member,
                require_all_members: require_all_members,
                mode: mode,
                similarity_index: similarity_index,
              )
            }
          }
      }
    }
  }
}

fn assign_task_skills_unique(
  task_skills: List(TaskSkill),
  team: List(Person),
  mode mode: Mode,
  similarity_index similarity_index: dict.Dict(#(String, String), Float),
) -> AssignmentResult {
  let indexed_members =
    list.index_map(team, fn(member, index) { #(index, member) })
  let indexed_task_skills =
    list.index_map(task_skills, fn(task_skill, index) { #(index, task_skill) })
  let member_by_index = dict.from_list(indexed_members)
  let task_skill_by_index = dict.from_list(indexed_task_skills)
  let member_count = list.length(team)
  let task_count = list.length(task_skills)
  let score_matrix =
    list.fold(indexed_members, dict.new(), fn(found_matrix, member_entry) {
      let #(member_index, member) = member_entry

      list.fold(indexed_task_skills, found_matrix, fn(found_inner, task_entry) {
        let #(task_index, task_skill) = task_entry
        let score =
          coverage_for_person_and_task_skill(
            member,
            task_skill,
            mode: mode,
            similarity_index: similarity_index,
          )
        let score_key = unique_score_key(member_index, task_index, task_count)

        dict.insert(found_inner, score_key, score)
      })
    })
  let #(_best_state, memo) =
    unique_best_state(
      member_index: 0,
      member_count: member_count,
      used_mask: 0,
      task_count: task_count,
      score_matrix: score_matrix,
      memo: dict.new(),
    )
  let assignment_pairs =
    unique_assignments_from_choices(
      member_index: 0,
      member_count: member_count,
      used_mask: 0,
      task_count: task_count,
      memo: memo,
    )
  let empty_assignments =
    list.fold(indexed_members, dict.new(), fn(found, member_entry) {
      let #(_index, member) = member_entry
      dict.insert(found, member.id, [])
    })
  let assignments =
    list.fold(assignment_pairs, empty_assignments, fn(found, pair) {
      let #(member_index, task_index) = pair

      case dict.get(member_by_index, member_index), dict.get(task_skill_by_index, task_index) {
        Ok(member), Ok(task_skill) ->
          dict.insert(found, member.id, [task_skill.id])

        Error(Nil), _ -> found
        _, Error(Nil) -> found
      }
    })
  let score_by_member =
    list.fold(assignment_pairs, dict.new(), fn(found, pair) {
      let #(member_index, task_index) = pair
      let score_key = unique_score_key(member_index, task_index, task_count)
      let score = dict_get_or_int_float(score_matrix, score_key, 0.0)
      dict.insert(found, member_index, score)
    })
  let member_scores =
    list.map(indexed_members, fn(member_entry) {
      let #(member_index, _member) = member_entry
      dict_get_or_int_float(score_by_member, member_index, 0.0)
    })

  AssignmentResult(assignments:, skill_score: geometric_mean(member_scores))
}

fn unique_best_state(
  member_index member_index: Int,
  member_count member_count: Int,
  used_mask used_mask: Int,
  task_count task_count: Int,
  score_matrix score_matrix: dict.Dict(Int, Float),
  memo memo: dict.Dict(Int, UniqueState),
) -> #(UniqueState, dict.Dict(Int, UniqueState)) {
  case member_index == member_count {
    True -> #(UniqueState(score: 0.0, choice: -1), memo)

    False -> {
      let memo_key = unique_memo_key(member_index, used_mask, member_count)
      case dict.get(memo, memo_key) {
        Ok(cached) -> #(cached, memo)

        Error(Nil) -> {
          let initial = #(UniqueState(score: -1.0e30, choice: -1), memo)
          let #(best_state, memo_after) =
            int.range(
              from: 0,
              to: task_count,
              with: initial,
              run: fn(state, task_index) {
                let #(current_best, current_memo) = state
                let task_bit = int.bitwise_shift_left(1, task_index)
                let already_used = int.bitwise_and(used_mask, task_bit) != 0

                case already_used {
                  True -> state

                  False -> {
                    let score =
                      dict_get_or_int_float(
                        score_matrix,
                        unique_score_key(member_index, task_index, task_count),
                        0.0,
                      )

                    case score <=. 0.0 {
                      True -> state

                      False -> {
                        let #(next_state, next_memo) =
                          unique_best_state(
                            member_index: member_index + 1,
                            member_count: member_count,
                            used_mask: int.bitwise_or(used_mask, task_bit),
                            task_count: task_count,
                            score_matrix: score_matrix,
                            memo: current_memo,
                          )
                        let candidate_score = safe_log(score) +. next_state.score

                        case candidate_score >. current_best.score {
                          True -> #(UniqueState(score: candidate_score, choice: task_index), next_memo)
                          False -> #(current_best, next_memo)
                        }
                      }
                    }
                  }
                }
              },
            )
          let memo_final =
            dict.insert(memo_after, memo_key, best_state)

          #(best_state, memo_final)
        }
      }
    }
  }
}

fn unique_assignments_from_choices(
  member_index member_index: Int,
  member_count member_count: Int,
  used_mask used_mask: Int,
  task_count task_count: Int,
  memo memo: dict.Dict(Int, UniqueState),
) -> List(#(Int, Int)) {
  case member_index == member_count {
    True -> []

    False -> {
      let state =
        unique_state_from_memo(
          memo,
          unique_memo_key(member_index, used_mask, member_count),
        )

      case state.choice < 0 || state.choice >= task_count {
        True -> []

        False -> {
          let task_bit = int.bitwise_shift_left(1, state.choice)
          [
            #(member_index, state.choice),
            ..unique_assignments_from_choices(
              member_index: member_index + 1,
              member_count: member_count,
              used_mask: int.bitwise_or(used_mask, task_bit),
              task_count: task_count,
              memo: memo,
            ),
          ]
        }
      }
    }
  }
}

fn unique_state_from_memo(
  memo: dict.Dict(Int, UniqueState),
  key: Int,
) -> UniqueState {
  case dict.get(memo, key) {
    Ok(state) -> state
    Error(Nil) -> UniqueState(score: -1.0e30, choice: -1)
  }
}

fn assign_task_skills_compat_overfull(
  task_skills: List(TaskSkill),
  team: List(Person),
  similarity_index similarity_index: dict.Dict(#(String, String), Float),
) -> AssignmentResult {
  let scored =
    list.map(team, fn(member) {
      let best =
        list.fold(task_skills, #(None, 0.0), fn(state, task_skill) {
          let #(best_id, best_score) = state
          let candidate =
            coverage_for_person_and_task_skill(
              member,
              task_skill,
              mode: Compat,
              similarity_index: similarity_index,
            )

          case candidate >. best_score {
            True -> #(Some(task_skill.id), candidate)
            False -> #(best_id, best_score)
          }
        })

      #(member.id, best)
    })

  let assignments =
    list.fold(scored, dict.new(), fn(found, entry) {
      let #(member_id, best) = entry
      let #(best_skill_id, _) = best
      let skill_ids =
        case best_skill_id {
          Some(skill_id) -> [skill_id]
          None -> []
        }

      dict.insert(found, member_id, skill_ids)
    })
  let member_scores =
    list.map(scored, fn(entry) {
      let #(_, best) = entry
      let #(_, score) = best
      score
    })

  AssignmentResult(assignments:, skill_score: geometric_mean(member_scores))
}

fn assign_search(
  remaining_skills remaining_skills: List(TaskSkill),
  states states: List(MemberAssignmentState),
  max_per_member max_per_member: Int,
  require_all_members require_all_members: Bool,
  mode mode: Mode,
  similarity_index similarity_index: dict.Dict(#(String, String), Float),
) -> AssignmentResult {
  case remaining_skills {
    [] -> score_assignment_states(states, mode: mode, similarity_index: similarity_index)

    [next_skill, ..rest_skills] -> {
      let empty_count = list.count(states, where: fn(state) { state.assigned == [] })
      let skills_left_after = list.length(rest_skills)
      let choices =
        enumerate_assignment_choices(
          prefix_reversed: [],
          states: states,
          task_skill: next_skill,
          max_per_member: max_per_member,
          require_all_members: require_all_members,
          empty_count: empty_count,
          skills_left_after: skills_left_after,
        )

      case choices {
        [] -> score_assignment_states(states, mode: mode, similarity_index: similarity_index)

        [first_choice, ..other_choices] -> {
          let initial =
            assign_search(
              remaining_skills: rest_skills,
              states: first_choice,
              max_per_member: max_per_member,
              require_all_members: require_all_members,
              mode: mode,
              similarity_index: similarity_index,
            )

          list.fold(other_choices, initial, fn(best, choice) {
            let candidate =
              assign_search(
                remaining_skills: rest_skills,
                states: choice,
                max_per_member: max_per_member,
                require_all_members: require_all_members,
                mode: mode,
                similarity_index: similarity_index,
              )

            better_assignment(best, candidate)
          })
        }
      }
    }
  }
}

fn enumerate_assignment_choices(
  prefix_reversed prefix_reversed: List(MemberAssignmentState),
  states states: List(MemberAssignmentState),
  task_skill task_skill: TaskSkill,
  max_per_member max_per_member: Int,
  require_all_members require_all_members: Bool,
  empty_count empty_count: Int,
  skills_left_after skills_left_after: Int,
) -> List(List(MemberAssignmentState)) {
  case states {
    [] -> []

    [state, ..rest] -> {
      let later_choices =
        enumerate_assignment_choices(
          prefix_reversed: [state, ..prefix_reversed],
          states: rest,
          task_skill: task_skill,
          max_per_member: max_per_member,
          require_all_members: require_all_members,
          empty_count: empty_count,
          skills_left_after: skills_left_after,
        )

      case can_assign_to_state(
        state: state,
        max_per_member: max_per_member,
        require_all_members: require_all_members,
        empty_count: empty_count,
        skills_left_after: skills_left_after,
      ) {
        False -> later_choices

        True -> {
          let updated =
            MemberAssignmentState(
              member: state.member,
              assigned: [task_skill, ..state.assigned],
            )
          let rebuilt = list.append(list.reverse(prefix_reversed), [updated, ..rest])

          [rebuilt, ..later_choices]
        }
      }
    }
  }
}

fn can_assign_to_state(
  state state: MemberAssignmentState,
  max_per_member max_per_member: Int,
  require_all_members require_all_members: Bool,
  empty_count empty_count: Int,
  skills_left_after skills_left_after: Int,
) -> Bool {
  let current_load = list.length(state.assigned)
  let can_take = current_load < max_per_member
  let was_empty = current_load == 0
  let empty_after =
    case was_empty {
      True -> empty_count - 1
      False -> empty_count
    }
  let keeps_room =
    case require_all_members {
      True -> skills_left_after >= empty_after
      False -> True
    }

  can_take && keeps_room
}

fn score_assignment_states(
  states: List(MemberAssignmentState),
  mode mode: Mode,
  similarity_index similarity_index: dict.Dict(#(String, String), Float),
) -> AssignmentResult {
  let assignments =
    list.fold(states, dict.new(), fn(found, state) {
      let skill_ids =
        list.reverse(state.assigned)
        |> list.map(fn(skill) { skill.id })

      dict.insert(found, state.member.id, skill_ids)
    })

  let has_empty_member = list.any(states, fn(state) { state.assigned == [] })
  let member_scores =
    list.map(states, fn(state) {
      member_assignment_score(
        member: state.member,
        assigned_task_skills: list.reverse(state.assigned),
        mode: mode,
        similarity_index: similarity_index,
      )
    })
  let skill_score =
    case has_empty_member {
      True -> 0.0
      False -> geometric_mean(member_scores)
    }

  AssignmentResult(assignments:, skill_score: skill_score)
}

fn member_assignment_score(
  member member: Person,
  assigned_task_skills assigned_task_skills: List(TaskSkill),
  mode mode: Mode,
  similarity_index similarity_index: dict.Dict(#(String, String), Float),
) -> Float {
  case assigned_task_skills {
    [] -> 0.0

    [_, ..] -> {
      let scored_items =
        list.map(assigned_task_skills, fn(task_skill) {
          #(
            coverage_for_person_and_task_skill(
              member,
              task_skill,
              mode: mode,
              similarity_index: similarity_index,
            ),
            task_skill.importance,
          )
        })

      case mode {
        Paper -> weighted_geometric_mean(scored_items)

        Compat ->
          geometric_mean(
            list.map(scored_items, fn(item) {
              let #(score, _) = item
              score
            }),
          )
      }
    }
  }
}

fn better_assignment(left: AssignmentResult, right: AssignmentResult) -> AssignmentResult {
  case right.skill_score >. left.skill_score {
    True -> right
    False -> left
  }
}

fn ceil_div(left: Int, right: Int) -> Int {
  case int.divide(left + right - 1, by: right) {
    Ok(value) -> value
    Error(Nil) -> 0
  }
}

pub fn build_team_quality_request(
  task task: Task,
  team team: List(Person),
  alpha alpha: Option(Float),
  beta beta: Option(Float),
  gamma gamma: Option(Float),
  delta delta: Option(Float),
  similarities similarities: Option(List(Similarity)),
) -> TeamQualityRequest {
  let teammate_ids = set.from_list(list.map(team, fn(member) { member.id }))
  let task_preferences = preference_lookup_task(task.preferences)
  let members =
    list.map(team, fn(member) {
      TeamMember(
        id: member.id,
        gender: member.gender,
        personality: member.personality,
        skills: member.skills,
        preferences:
          case member.preferences {
            Some(preferences) -> {
              let filtered =
                list.filter(preferences, fn(preference) {
                  set.contains(teammate_ids, preference.person_id)
                })

              case filtered {
                [] -> None
                [_, ..] -> Some(filtered)
              }
            }

            None -> None
          },
        task_preference:
          case dict.get(task_preferences, member.id) {
            Ok(value) -> Some(value)
            Error(Nil) -> None
          },
      )
    })

  TeamQualityRequest(
    task_skills: task.skills,
    team: members,
    alpha: alpha,
    beta: beta,
    gamma: gamma,
    delta: delta,
    similarities: similarities,
  )
}

fn calculate_team_quality_components_for_people(
  task_skills task_skills: List(TaskSkill),
  team team: List(Person),
  alpha alpha: Option(Float),
  beta beta: Option(Float),
  gamma gamma: Option(Float),
  delta delta: Option(Float),
  similarities similarities: Option(List(Similarity)),
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  task_preferences task_preferences: Option(dict.Dict(String, Float)),
  compat_task_preference_default compat_task_preference_default: Option(Float),
  compat_social_preference_default compat_social_preference_default: Option(Float),
  personality_score personality_score: Option(Float),
  social_score social_score: Option(Float),
) -> TeamQualityComponents {
  let weights =
    resolve_weights(
      alpha: alpha,
      beta: beta,
      gamma: gamma,
      delta: delta,
      mode: mode,
      preset: preset,
      normalize: normalize_weights,
    )
  let assignment =
    assign_task_skills(
      task_skills,
      team,
      mode: mode,
      similarities: similarities,
    )
  let task_pref_default = option_float_or(compat_task_preference_default, 0.5)
  let social_pref_default = option_float_or(compat_social_preference_default, 0.5)
  let task_pref_score =
    calculate_task_preference_score(
      team,
      task_preferences,
      compat_default: task_pref_default,
    )
  let resolved_social =
    case social_score {
      Some(value) -> value
      None -> team_social_score(team, compat_default: social_pref_default)
    }
  let resolved_personality =
    case personality_score {
      Some(value) -> value
      None -> team_personality_score(team, mode: mode)
    }
  let quality =
    weights.alpha *. assignment.skill_score
    +. weights.beta *. resolved_personality
    +. weights.gamma *. task_pref_score
    +. weights.delta *. resolved_social

  TeamQualityComponents(
    quality: quality,
    skill_score: assignment.skill_score,
    personality_score: resolved_personality,
    task_preference_score: task_pref_score,
    social_score: resolved_social,
    assignments: assignment.assignments,
    weights: weights,
  )
}

pub fn calculate_team_quality_for_people(
  task_skills task_skills: List(TaskSkill),
  team team: List(Person),
  alpha alpha: Option(Float),
  beta beta: Option(Float),
  gamma gamma: Option(Float),
  delta delta: Option(Float),
  similarities similarities: Option(List(Similarity)),
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  task_preferences task_preferences: Option(dict.Dict(String, Float)),
  compat_task_preference_default compat_task_preference_default: Option(Float),
  compat_social_preference_default compat_social_preference_default: Option(Float),
) -> QualityBreakdown {
  let components =
    calculate_team_quality_components_for_people(
      task_skills: task_skills,
      team: team,
      alpha: alpha,
      beta: beta,
      gamma: gamma,
      delta: delta,
      similarities: similarities,
      mode: mode,
      preset: preset,
      normalize_weights: normalize_weights,
      task_preferences: task_preferences,
      compat_task_preference_default: compat_task_preference_default,
      compat_social_preference_default: compat_social_preference_default,
      personality_score: None,
      social_score: None,
    )

  QualityBreakdown(
    quality: components.quality,
    skill_score: components.skill_score,
    personality_score: components.personality_score,
    task_preference_score: components.task_preference_score,
    social_score: components.social_score,
    weights: dict.from_list([
      #("alpha", components.weights.alpha),
      #("beta", components.weights.beta),
      #("gamma", components.weights.gamma),
      #("delta", components.weights.delta),
    ]),
    assignments: components.assignments,
  )
}

pub fn calculate_team_quality(
  request: TeamQualityRequest,
  mode mode: Mode,
  preset preset: Option(WeightPreset),
  normalize_weights normalize_weights: Bool,
  compat_task_preference_default compat_task_preference_default: Option(Float),
  compat_social_preference_default compat_social_preference_default: Option(Float),
) -> QualityBreakdown {
  let task_preferences =
    list.fold(request.team, dict.new(), fn(found, member) {
      case member.task_preference {
        Some(value) -> dict.insert(found, member.id, value)
        None -> found
      }
    })

  calculate_team_quality_for_people(
    task_skills: request.task_skills,
    team: list.map(request.team, team_member_to_person),
    alpha: request.alpha,
    beta: request.beta,
    gamma: request.gamma,
    delta: request.delta,
    similarities: request.similarities,
    mode: mode,
    preset: preset,
    normalize_weights: normalize_weights,
    task_preferences:
      case dict.is_empty(task_preferences) {
        True -> None
        False -> Some(task_preferences)
      },
    compat_task_preference_default: compat_task_preference_default,
    compat_social_preference_default: compat_social_preference_default,
  )
}

pub fn assigned_people_from_assignments(
  assignments: dict.Dict(String, List(String)),
) -> List(AssignedPerson) {
  assignments
  |> dict.to_list
  |> list.map(fn(entry) {
    let #(person_id, skill_ids) = entry
    AssignedPerson(id: person_id, skill_ids: skill_ids)
  })
}

fn dict_get_or(mapping: dict.Dict(String, Float), key: String, fallback: Float) -> Float {
  case dict.get(mapping, key) {
    Ok(value) -> value
    Error(Nil) -> fallback
  }
}

fn dict_get_or_pair(
  mapping: dict.Dict(#(String, String), Float),
  key: #(String, String),
  fallback: Float,
) -> Float {
  case dict.get(mapping, key) {
    Ok(value) -> value
    Error(Nil) -> fallback
  }
}

fn unique_score_key(member_index: Int, task_index: Int, task_count: Int) -> Int {
  member_index * task_count + task_index
}

fn unique_memo_key(member_index: Int, used_mask: Int, member_count: Int) -> Int {
  used_mask * member_count + member_index
}

fn dict_get_or_int_float(
  mapping: dict.Dict(Int, Float),
  key: Int,
  fallback: Float,
) -> Float {
  case dict.get(mapping, key) {
    Ok(value) -> value
    Error(Nil) -> fallback
  }
}

fn option_float_or(value: Option(Float), fallback: Float) -> Float {
  case value {
    Some(inner) -> inner
    None -> fallback
  }
}
