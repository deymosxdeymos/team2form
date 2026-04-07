from __future__ import annotations

import heapq
import itertools
import math
import random
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from typing import overload

from .models import FormationRequest, Person, Task, TeamsResponse
from .modes import Mode, WeightPreset
from .scoring import (
    _calculate_team_quality_components_for_people,
    _compat_member_task_values,
    _task_preference_score,
    coverage_for_person_and_task_skill,
    geometric_mean,
    preference_lookup,
    similarity_lookup,
    team_personality_score,
    team_social_score,
)
from .weights import resolve_weights


@dataclass(slots=True)
class ScoredAllocation:
    task_id: str
    people: tuple[Person, ...]
    quality: float
    assignments: dict[str, list[str]]
    team_signature: tuple[str, ...] | None = None


class TeamFormationError(ValueError):
    pass


ScoreCacheKey = tuple[str, tuple[str, ...]]

DEFAULT_MAX_CANDIDATE_TEAMS = 10_000
MAX_SCORED_COMBINATION_EXPANSION = 4
OBJECTIVE_REL_TOL = 1e-12
OBJECTIVE_ABS_TOL = 1e-15


def _unused_member_scorer(_person: Person) -> tuple[float, float, float, float, float]:
    return (0.0, 0.0, 0.0, 0.0, 0.0)

_REQUEST_TEAM_COMPONENT_CACHES: dict[
    int,
    tuple[
        FormationRequest,
        dict[tuple[Mode, tuple[str, ...]], float],
        dict[tuple[float, tuple[str, ...]], float],
        dict[tuple[str, ...], bool],
    ],
] = {}

_REQUEST_TASKS_BY_ID: dict[int, tuple[FormationRequest, dict[str, Task]]] = {}

_REQUEST_TASK_PREFERENCES_BY_TASK_ID: dict[
    int,
    tuple[FormationRequest, dict[str, dict[str, float]]],
] = {}

_REQUEST_RESOLVED_WEIGHTS: dict[
    tuple[int, Mode, WeightPreset | None, bool],
    tuple[FormationRequest, object],
] = {}

_REQUEST_SHORTLIST_POTENTIALS: dict[
    tuple[
        int,
        tuple[str, ...],
        int,
        Mode,
        bool,
        bool,
    ],
    tuple[
        FormationRequest,
        dict[str, float],
        dict[str, float],
    ],
] = {}

_REQUEST_COMPAT_SHORTLIST_CHEAP_BOUNDED_CANDIDATES: dict[
    tuple[
        int,
        str,
        tuple[str, ...],
        Mode,
        WeightPreset | None,
        bool,
    ],
    tuple[
        FormationRequest,
        list[
            tuple[
                float,
                int,
                tuple[Person, ...],
            ]
        ],
    ],
] = {}

_REQUEST_COMPAT_GREEDY_CHEAP_BOUNDED_CANDIDATES: dict[
    tuple[
        int,
        str,
        tuple[str, ...],
        Mode,
        WeightPreset | None,
        bool,
    ],
    tuple[
        FormationRequest,
        list[
            tuple[
                float,
                int,
                tuple[Person, ...],
            ]
        ],
    ],
] = {}

_REQUEST_COMPAT_SWAP_UPPER_BOUND_CACHES: dict[
    tuple[int, Mode, WeightPreset | None, bool],
    tuple[
        FormationRequest,
        dict[str, dict[tuple[str, ...], float]],
    ],
] = {}

_REQUEST_COMPAT_SWAP_BOUND_DATA_BY_TASK_ID: dict[
    int,
    tuple[
        FormationRequest,
        dict[
            str,
            tuple[
                dict[str, float],
                float,
                dict[str, float | None],
                dict[str, tuple[float, ...]],
            ],
        ],
    ],
] = {}

_REQUEST_COMPAT_SHORTLISTS: dict[
    tuple[
        int,
        str,
        tuple[str, ...],
        Mode,
        WeightPreset | None,
        bool,
        int,
        int,
    ],
    tuple[FormationRequest, tuple[Person, ...]],
] = {}

_REQUEST_FORM_SCORE_CACHES: dict[
    tuple[int, Mode, WeightPreset | None, bool],
    tuple[FormationRequest, dict[ScoreCacheKey, ScoredAllocation]],
] = {}

_REQUEST_GREEDY_ALLOCATIONS: dict[
    tuple[
        int,
        tuple[str, ...],
        Mode,
        WeightPreset | None,
        bool,
        int | None,
        int,
    ],
    tuple[
        FormationRequest,
        tuple[ScoredAllocation, ...],
        tuple[Person, ...],
    ],
] = {}

_REQUEST_IMPROVED_ALLOCATIONS: dict[
    tuple[
        int,
        tuple[tuple[str, tuple[str, ...]], ...],
        tuple[str, ...],
        Mode,
        WeightPreset | None,
        bool,
        int,
    ],
    tuple[
        FormationRequest,
        tuple[ScoredAllocation, ...],
    ],
] = {}

_REQUEST_TASK_ORDER_BY_HARDNESS: dict[
    tuple[int, Mode],
    tuple[FormationRequest, tuple[Task, ...]],
] = {}

_REQUEST_TASK_ORIGINAL_ORDER: dict[
    int,
    tuple[FormationRequest, dict[str, int]],
] = {}

_REQUEST_TASK_ORDER_BY_ORIGINAL_INDICES: dict[
    tuple[int, Mode],
    tuple[FormationRequest, tuple[int, ...]],
] = {}


def _request_tasks_by_id(request: FormationRequest) -> dict[str, Task]:
    cache_key = id(request)
    cached = _REQUEST_TASKS_BY_ID.get(cache_key)
    if cached is not None and cached[0] is request:
        return cached[1]

    tasks_by_id = {task.id: task for task in request.tasks}
    _REQUEST_TASKS_BY_ID[cache_key] = (request, tasks_by_id)
    return tasks_by_id


def _request_task_original_order(
    request: FormationRequest,
) -> dict[str, int]:
    cache_key = id(request)
    cached = _REQUEST_TASK_ORIGINAL_ORDER.get(cache_key)
    if cached is not None and cached[0] is request:
        return cached[1]

    task_original_order = {
        task.id: index for index, task in enumerate(request.tasks)
    }
    _REQUEST_TASK_ORIGINAL_ORDER[cache_key] = (request, task_original_order)
    return task_original_order


def _request_task_preferences_by_task_id(
    request: FormationRequest,
) -> dict[str, dict[str, float]]:
    cache_key = id(request)
    cached = _REQUEST_TASK_PREFERENCES_BY_TASK_ID.get(cache_key)
    if cached is not None and cached[0] is request:
        return cached[1]

    valid_person_ids = {candidate.id for candidate in request.people}
    task_preferences_by_task_id = {
        task.id: preference_lookup(
            task.preferences,
            valid_person_ids=valid_person_ids,
        )
        for task in request.tasks
    }
    _REQUEST_TASK_PREFERENCES_BY_TASK_ID[cache_key] = (
        request,
        task_preferences_by_task_id,
    )
    return task_preferences_by_task_id



def _request_resolved_weights(
    request: FormationRequest,
    *,
    mode: Mode,
    preset: WeightPreset | None,
    normalize_weights: bool,
):
    cache_key = (id(request), mode, preset, normalize_weights)
    cached = _REQUEST_RESOLVED_WEIGHTS.get(cache_key)
    if cached is not None and cached[0] is request:
        return cached[1]

    weights = resolve_weights(
        alpha=request.alpha,
        beta=request.beta,
        gamma=request.gamma,
        delta=request.delta,
        mode=mode,
        preset=preset,
        normalize=normalize_weights,
    )
    _REQUEST_RESOLVED_WEIGHTS[cache_key] = (request, weights)
    return weights



def _request_team_component_caches(
    request: FormationRequest,
) -> tuple[
    dict[tuple[Mode, tuple[str, ...]], float],
    dict[tuple[float, tuple[str, ...]], float],
    dict[tuple[str, ...], bool],
]:
    cache_key = id(request)
    cached = _REQUEST_TEAM_COMPONENT_CACHES.get(cache_key)
    if cached is not None and cached[0] is request:
        return cached[1], cached[2], cached[3]

    personality_cache: dict[tuple[Mode, tuple[str, ...]], float] = {}
    social_cache: dict[tuple[float, tuple[str, ...]], float] = {}
    social_preference_presence_cache: dict[tuple[str, ...], bool] = {}
    _REQUEST_TEAM_COMPONENT_CACHES[cache_key] = (
        request,
        personality_cache,
        social_cache,
        social_preference_presence_cache,
    )
    return personality_cache, social_cache, social_preference_presence_cache



def validate_max_candidate_teams(max_candidate_teams: int | None) -> None:
    if max_candidate_teams is not None and max_candidate_teams <= 0:
        raise TeamFormationError('max_candidate_teams must be a positive integer.')


def capped_candidate_search_is_exact(
    request: FormationRequest,
    *,
    max_candidate_teams: int | None,
) -> bool:
    if max_candidate_teams is None:
        return True
    remaining_people = len(request.people)
    allocation_count = 1
    for task in request.tasks:
        task_candidate_count = math.comb(remaining_people, task.team_size)
        if task_candidate_count > max_candidate_teams:
            return False
        if allocation_count > max_candidate_teams // task_candidate_count:
            return False
        allocation_count *= task_candidate_count
        remaining_people -= task.team_size
    return True


def task_hardness(task_id: str, request: FormationRequest, *, mode: Mode) -> float:
    task = next(task for task in request.tasks if task.id == task_id)
    similarity_index = similarity_lookup(request.similarities)
    hardness = float(task.team_size)
    for task_skill in task.skills:
        best_coverage = max(
            (
                coverage_for_person_and_task_skill(
                    person,
                    task_skill,
                    mode=mode,
                    similarity_index=similarity_index,
                )
                for person in request.people
            ),
            default=0.0,
        )
        hardness += task_skill.level * (1.0 - best_coverage)
    return hardness


def individual_fit(
    person: Person,
    request: FormationRequest,
    task_id: str,
    *,
    mode: Mode,
    preset: WeightPreset | None,
    normalize_weights: bool,
) -> tuple[float, float, float]:
    task = next(task for task in request.tasks if task.id == task_id)
    similarity_index = similarity_lookup(request.similarities)
    valid_person_ids = {candidate.id for candidate in request.people}
    task_preferences = preference_lookup(
        task.preferences,
        valid_person_ids=valid_person_ids,
    )
    weights = resolve_weights(
        alpha=request.alpha,
        beta=request.beta,
        gamma=request.gamma,
        delta=request.delta,
        mode=mode,
        preset=preset,
        normalize=normalize_weights,
    )
    skills_per_person = max(1, math.ceil(len(task.skills) / task.team_size))

    weighted_coverages = [
        (
            coverage_for_person_and_task_skill(
                person,
                task_skill,
                mode=mode,
                similarity_index=similarity_index,
            ),
            task_skill.importance,
        )
        for task_skill in task.skills
    ]
    # Candidate pruning needs to preserve specialists for the most important
    # skills, not just the skills with the highest raw coverage.
    best_coverages = sorted(
        weighted_coverages,
        key=lambda item: (item[0] * item[1], item[1], item[0]),
        reverse=True,
    )[:skills_per_person]
    total_importance = sum(task_skill.importance for task_skill in task.skills)
    skill_fit = (
        sum(coverage * importance for coverage, importance in best_coverages)
        / total_importance
        if total_importance > 0
        else 0.0
    )
    task_preference_default = 0.5
    if mode == Mode.COMPAT:
        task_preference_default = 0.0 if not task_preferences else 0.5
    task_preference = task_preferences.get(person.id, task_preference_default)

    weighted_fit = weights.alpha * skill_fit + weights.gamma * task_preference
    return (weighted_fit, skill_fit, task_preference)


def has_explicit_social_preferences(
    member: Person,
    teammate_ids: set[str],
) -> bool:
    if not member.preferences:
        return False
    return any(
        preference.person_id in teammate_ids and preference.person_id != member.id
        for preference in member.preferences
    )


def candidate_social_potential(
    person: Person,
    people: list[Person],
    *,
    team_size: int,
    mode: Mode,
) -> float:
    if team_size <= 1:
        return 0.0

    pair_scores = []
    for teammate in people:
        if teammate.id == person.id:
            continue
        if mode == Mode.COMPAT and not (
            has_explicit_social_preferences(person, {teammate.id})
            or has_explicit_social_preferences(teammate, {person.id})
        ):
            pair_scores.append(0.0)
            continue
        pair_scores.append(team_social_score((person, teammate), compat_default=0.5))

    partner_count = min(team_size - 1, len(pair_scores))
    if partner_count <= 0:
        return 0.0
    return sum(sorted(pair_scores, reverse=True)[:partner_count]) / partner_count


def candidate_personality_potential(
    person: Person,
    people: list[Person],
    *,
    team_size: int,
    mode: Mode,
) -> float:
    if team_size <= 1:
        return 0.0

    pair_scores = [
        team_personality_score((person, teammate), mode=mode)
        for teammate in people
        if teammate.id != person.id
    ]
    partner_count = min(team_size - 1, len(pair_scores))
    if partner_count <= 0:
        return 0.0
    return sum(sorted(pair_scores, reverse=True)[:partner_count]) / partner_count


def shortlist_scorers(
    request: FormationRequest,
    *,
    people: list[Person],
    task_id: str,
    team_size: int,
    mode: Mode,
    preset: WeightPreset | None,
    normalize_weights: bool,
) -> tuple[
    Callable[[Person], tuple[float, float, float, float, float]],
    list[Callable[[Person], float]],
]:
    weights = _request_resolved_weights(
        request,
        mode=mode,
        preset=preset,
        normalize_weights=normalize_weights,
    )
    social_potentials: dict[str, float] = {}
    personality_potentials: dict[str, float] = {}

    personality_required = weights.beta > 0
    social_required = weights.delta > 0
    if (
        team_size > 1
        and len(people) > 1
        and (personality_required or social_required)
    ):
        shortlist_cache_key = (
            id(request),
            tuple(person.id for person in people),
            team_size,
            mode,
            personality_required,
            social_required,
        )
        cached_shortlist_potentials = _REQUEST_SHORTLIST_POTENTIALS.get(
            shortlist_cache_key
        )
        if (
            cached_shortlist_potentials is not None
            and cached_shortlist_potentials[0] is request
        ):
            personality_potentials = cached_shortlist_potentials[1]
            social_potentials = cached_shortlist_potentials[2]
        else:
            partner_count = min(team_size - 1, len(people) - 1)

            personality_pair_scores_by_person_id: dict[str, list[float]] | None = (
                None
            )
            if personality_required:
                personality_pair_scores_by_person_id = {
                    person.id: [] for person in people
                }

            social_pair_scores_by_person_id: dict[str, list[float]] | None = None
            explicit_preference_ids_by_person_id: dict[str, set[str]] | None = None
            if social_required:
                social_pair_scores_by_person_id = {
                    person.id: [] for person in people
                }
                explicit_preference_ids_by_person_id = {
                    person.id: {
                        preference.person_id
                        for preference in (person.preferences or [])
                        if preference.person_id != person.id
                    }
                    for person in people
                }

            if (
                personality_pair_scores_by_person_id is not None
                or social_pair_scores_by_person_id is not None
            ):
                for left_index, left_member in enumerate(people):
                    for right_member in people[left_index + 1 :]:
                        if personality_pair_scores_by_person_id is not None:
                            personality_pair_score = team_personality_score(
                                (left_member, right_member),
                                mode=mode,
                            )
                            personality_pair_scores_by_person_id[
                                left_member.id
                            ].append(personality_pair_score)
                            personality_pair_scores_by_person_id[
                                right_member.id
                            ].append(personality_pair_score)

                        if social_pair_scores_by_person_id is not None:
                            assert explicit_preference_ids_by_person_id is not None
                            social_pair_score = 0.0
                            if (
                                mode != Mode.COMPAT
                                or right_member.id
                                in explicit_preference_ids_by_person_id[
                                    left_member.id
                                ]
                                or left_member.id
                                in explicit_preference_ids_by_person_id[
                                    right_member.id
                                ]
                            ):
                                social_pair_score = team_social_score(
                                    (left_member, right_member),
                                    compat_default=0.5,
                                )
                            social_pair_scores_by_person_id[left_member.id].append(
                                social_pair_score
                            )
                            social_pair_scores_by_person_id[right_member.id].append(
                                social_pair_score
                            )

                def top_partner_average(pair_scores: list[float]) -> float:
                    if partner_count == 1:
                        return max(pair_scores)

                    if partner_count == 2:
                        top_1 = float('-inf')
                        top_2 = float('-inf')
                        for score in pair_scores:
                            if score > top_1:
                                top_2 = top_1
                                top_1 = score
                            elif score > top_2:
                                top_2 = score
                        return (top_1 + top_2) / 2.0

                    if partner_count == 3:
                        top_1 = float('-inf')
                        top_2 = float('-inf')
                        top_3 = float('-inf')
                        for score in pair_scores:
                            if score > top_1:
                                top_3 = top_2
                                top_2 = top_1
                                top_1 = score
                            elif score > top_2:
                                top_3 = top_2
                                top_2 = score
                            elif score > top_3:
                                top_3 = score
                        return (top_1 + top_2 + top_3) / 3.0

                    return (
                        sum(sorted(pair_scores, reverse=True)[:partner_count])
                        / partner_count
                    )

                if personality_pair_scores_by_person_id is not None:
                    for person_id, pair_scores in (
                        personality_pair_scores_by_person_id.items()
                    ):
                        personality_potentials[person_id] = (
                            top_partner_average(pair_scores)
                        )

                if social_pair_scores_by_person_id is not None:
                    for (
                        person_id,
                        pair_scores,
                    ) in social_pair_scores_by_person_id.items():
                        social_potentials[person_id] = top_partner_average(
                            pair_scores
                        )

            _REQUEST_SHORTLIST_POTENTIALS[shortlist_cache_key] = (
                request,
                personality_potentials,
                social_potentials,
            )

    def social_potential(person: Person) -> float:
        if weights.delta <= 0:
            return 0.0
        if person.id not in social_potentials:
            social_potentials[person.id] = candidate_social_potential(
                person,
                people,
                team_size=team_size,
                mode=mode,
            )
        return social_potentials[person.id]

    def personality_potential(person: Person) -> float:
        if weights.beta <= 0:
            return 0.0
        if person.id not in personality_potentials:
            personality_potentials[person.id] = candidate_personality_potential(
                person,
                people,
                team_size=team_size,
                mode=mode,
            )
        return personality_potentials[person.id]

    def scorer(person: Person) -> tuple[float, float, float, float, float]:
        weighted_fit, skill_fit, task_preference = individual_fit(
            person,
            request,
            task_id,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
        )
        personality = personality_potential(person)
        social = social_potential(person)
        return (
            weighted_fit + weights.beta * personality + weights.delta * social,
            skill_fit,
            task_preference,
            personality,
            social,
        )

    alternate_scorers: list[Callable[[Person], float]] = []
    if weights.beta > 0:
        alternate_scorers.append(personality_potential)
    if weights.delta > 0:
        alternate_scorers.append(social_potential)

    return scorer, alternate_scorers


@overload
def candidate_combinations(
    *,
    people: list[Person],
    team_size: int,
    max_candidate_teams: None,
    shortlist_padding: int,
    scorer,
    alternate_scorers: list[Callable[[Person], float]] | None = None,
    combination_scorer: Callable[[tuple[Person, ...]], float] | None = None,
    scored_combinations: list[tuple[tuple[Person, ...], float]] | None = None,
) -> Iterator[tuple[Person, ...]]: ...


@overload
def candidate_combinations(
    *,
    people: list[Person],
    team_size: int,
    max_candidate_teams: int,
    shortlist_padding: int,
    scorer,
    alternate_scorers: list[Callable[[Person], float]] | None = None,
    combination_scorer: Callable[[tuple[Person, ...]], float] | None = None,
    scored_combinations: list[tuple[tuple[Person, ...], float]] | None = None,
) -> list[tuple[Person, ...]]: ...


def candidate_combinations(
    *,
    people: list[Person],
    team_size: int,
    max_candidate_teams: int | None,
    shortlist_padding: int,
    scorer,
    alternate_scorers: list[Callable[[Person], float]] | None = None,
    combination_scorer: Callable[[tuple[Person, ...]], float] | None = None,
    scored_combinations: list[tuple[tuple[Person, ...], float]] | None = None,
) -> Iterable[tuple[Person, ...]]:
    validate_max_candidate_teams(max_candidate_teams)
    total = math.comb(len(people), team_size)
    if max_candidate_teams is None:
        return itertools.combinations(people, team_size)
    if total <= max_candidate_teams:
        return list(itertools.combinations(people, team_size))

    minimum_shortlist_size = team_size
    while math.comb(minimum_shortlist_size, team_size) < max_candidate_teams:
        minimum_shortlist_size += 1

    target_size = min(
        len(people),
        max(
            team_size + shortlist_padding,
            team_size * 2,
            minimum_shortlist_size,
        ),
    )
    shortlist_size = target_size
    if combination_scorer is None:
        shortlist_size = team_size
        while shortlist_size < target_size:
            if math.comb(shortlist_size, team_size) >= max_candidate_teams:
                break
            shortlist_size += 1
    else:
        scored_combination_budget = (
            max_candidate_teams * MAX_SCORED_COMBINATION_EXPANSION
        )
        shortlist_size = team_size
        while (
            shortlist_size < target_size
            and math.comb(
                shortlist_size + 1,
                team_size,
            )
            <= scored_combination_budget
        ):
            shortlist_size += 1

    shortlist = []
    seen_ids: set[str] = set()
    ranked_lists = [sorted(people, key=scorer, reverse=True)]
    if alternate_scorers:
        ranked_lists.extend(
            sorted(people, key=alternate_scorer, reverse=True)
            for alternate_scorer in alternate_scorers
        )

    positions = [0] * len(ranked_lists)
    while len(shortlist) < shortlist_size:
        added = False
        for ranking_index, ranking in enumerate(ranked_lists):
            while positions[ranking_index] < len(ranking):
                person = ranking[positions[ranking_index]]
                positions[ranking_index] += 1
                if person.id in seen_ids:
                    continue
                seen_ids.add(person.id)
                shortlist.append(person)
                added = True
                break
            if len(shortlist) >= shortlist_size:
                break
        if not added:
            break

    shortlist = [person for person in people if person.id in seen_ids]

    if combination_scorer is None:
        combinations = list(itertools.combinations(shortlist, team_size))
        return combinations[:max_candidate_teams]

    ranked: list[tuple[float, int, tuple[Person, ...]]] = []
    for index, combination in enumerate(itertools.combinations(shortlist, team_size)):
        entry = (combination_scorer(combination), -index, combination)
        if len(ranked) < max_candidate_teams:
            heapq.heappush(ranked, entry)
            continue
        if entry > ranked[0]:
            heapq.heapreplace(ranked, entry)

    ranked.sort(reverse=True)
    if scored_combinations is not None:
        scored_combinations.extend(
            (combination, score)
            for score, _, combination in ranked
        )
    return [combination for _, _, combination in ranked]



def _best_scored_shortlist_candidate_with_compat_pruning(
    *,
    request: FormationRequest,
    people: list[Person],
    task: Task,
    scorer,
    alternate_scorers: list[Callable[[Person], float]] | None,
    mode: Mode,
    preset: WeightPreset | None,
    normalize_weights: bool,
    max_candidate_teams: int,
    shortlist_padding: int,
    score_cache: dict[ScoreCacheKey, ScoredAllocation],
) -> ScoredAllocation | None:
    if mode != Mode.COMPAT:
        return None

    total = math.comb(len(people), task.team_size)
    if total <= max_candidate_teams:
        return None

    minimum_shortlist_size = task.team_size
    while math.comb(minimum_shortlist_size, task.team_size) < max_candidate_teams:
        minimum_shortlist_size += 1

    target_size = min(
        len(people),
        max(
            task.team_size + shortlist_padding,
            task.team_size * 2,
            minimum_shortlist_size,
        ),
    )

    scored_combination_budget = max_candidate_teams * MAX_SCORED_COMBINATION_EXPANSION
    shortlist_size = task.team_size
    while (
        shortlist_size < target_size
        and math.comb(shortlist_size + 1, task.team_size)
        <= scored_combination_budget
    ):
        shortlist_size += 1

    shortlist_cache_key = (
        id(request),
        task.id,
        tuple(person.id for person in people),
        mode,
        preset,
        normalize_weights,
        max_candidate_teams,
        shortlist_padding,
    )
    cached_shortlist = _REQUEST_COMPAT_SHORTLISTS.get(shortlist_cache_key)
    if cached_shortlist is not None and cached_shortlist[0] is request:
        shortlist = [*cached_shortlist[1]]
    else:
        shortlist: list[Person] = []
        seen_ids: set[str] = set()
        ranked_lists = [sorted(people, key=scorer, reverse=True)]
        if alternate_scorers:
            ranked_lists.extend(
                sorted(people, key=alternate_scorer, reverse=True)
                for alternate_scorer in alternate_scorers
            )

        positions = [0] * len(ranked_lists)
        while len(shortlist) < shortlist_size:
            added = False
            for ranking_index, ranking in enumerate(ranked_lists):
                while positions[ranking_index] < len(ranking):
                    person = ranking[positions[ranking_index]]
                    positions[ranking_index] += 1
                    if person.id in seen_ids:
                        continue
                    seen_ids.add(person.id)
                    shortlist.append(person)
                    added = True
                    break
                if len(shortlist) >= shortlist_size:
                    break
            if not added:
                break

        shortlist = [person for person in people if person.id in seen_ids]
        _REQUEST_COMPAT_SHORTLISTS[shortlist_cache_key] = (
            request,
            tuple(shortlist),
        )
    shortlist_total = math.comb(len(shortlist), task.team_size)
    if shortlist_total != max_candidate_teams + 1:
        return None

    (
        personality_cache,
        social_cache,
        social_preference_presence_cache,
    ) = _request_team_component_caches(request)
    resolved_weights = _request_resolved_weights(
        request,
        mode=mode,
        preset=preset,
        normalize_weights=normalize_weights,
    )

    best: ScoredAllocation | None = None
    best_quality = float('-inf')
    best_ids: tuple[str, ...] | None = None

    best_first_k: ScoredAllocation | None = None
    best_first_k_quality = float('-inf')
    best_first_k_ids: tuple[str, ...] | None = None

    first_quality: float | None = None
    all_equal = True
    scored_count = 0

    shortlist_signature = tuple(person.id for person in shortlist)
    cheap_bounded_candidates_cache_key = (
        id(request),
        task.id,
        shortlist_signature,
        mode,
        preset,
        normalize_weights,
    )
    cached_cheap_bounded_candidates = (
        _REQUEST_COMPAT_SHORTLIST_CHEAP_BOUNDED_CANDIDATES.get(
            cheap_bounded_candidates_cache_key
        )
    )

    cheap_bounded_candidates: list[
        tuple[float, int, tuple[Person, ...]]
    ]
    if (
        cached_cheap_bounded_candidates is not None
        and cached_cheap_bounded_candidates[0] is request
    ):
        cheap_bounded_candidates = cached_cheap_bounded_candidates[1]
    else:
        task_preferences = _request_task_preferences_by_task_id(request)[task.id]
        task_preference_default = 0.0 if not task_preferences else 0.5
        task_preference_logs_by_person_id: dict[str, float | None] = {}
        for person in people:
            task_preference = task_preferences.get(
                person.id,
                task_preference_default,
            )
            if task_preference <= 0:
                task_preference_logs_by_person_id[person.id] = None
                continue
            task_preference_logs_by_person_id[person.id] = math.log(
                task_preference
            )

        task_skill_ids = tuple(skill.id for skill in task.skills)
        task_skill_values_by_person_id = {
            person.id: _compat_member_task_values(
                person,
                task.skills,
                task_skill_ids=task_skill_ids,
            )
            for person in people
        }

        cheap_bounded_candidates = []
        combinations = itertools.combinations(shortlist, task.team_size)
        for index, candidate in enumerate(combinations):
            if len(candidate) == 4:
                team_signature = (
                    candidate[0].id,
                    candidate[1].id,
                    candidate[2].id,
                    candidate[3].id,
                )
            else:
                team_signature = tuple(member.id for member in candidate)

            personality_cache_key = (Mode.COMPAT, team_signature)
            personality_score = personality_cache.get(personality_cache_key)
            if personality_score is None:
                personality_score = team_personality_score(
                    candidate,
                    mode=Mode.COMPAT,
                )
                personality_cache[personality_cache_key] = personality_score
            task_preference_log_sum = 0.0
            for member in candidate:
                task_preference_log = task_preference_logs_by_person_id[
                    member.id
                ]
                if task_preference_log is None:
                    task_preference_score = 0.0
                    break
                task_preference_log_sum += task_preference_log
            else:
                task_preference_score = math.exp(
                    task_preference_log_sum / len(candidate)
                )

            first_task_skill_values = task_skill_values_by_person_id[
                team_signature[0]
            ]
            if len(candidate) == 4 and len(first_task_skill_values) == 4:
                second_task_skill_values = task_skill_values_by_person_id[
                    team_signature[1]
                ]
                third_task_skill_values = task_skill_values_by_person_id[
                    team_signature[2]
                ]
                fourth_task_skill_values = task_skill_values_by_person_id[
                    team_signature[3]
                ]
                max_value = max
                task_skill_bests = [
                    max_value(
                        first_task_skill_values[0],
                        second_task_skill_values[0],
                        third_task_skill_values[0],
                        fourth_task_skill_values[0],
                    ),
                    max_value(
                        first_task_skill_values[1],
                        second_task_skill_values[1],
                        third_task_skill_values[1],
                        fourth_task_skill_values[1],
                    ),
                    max_value(
                        first_task_skill_values[2],
                        second_task_skill_values[2],
                        third_task_skill_values[2],
                        fourth_task_skill_values[2],
                    ),
                    max_value(
                        first_task_skill_values[3],
                        second_task_skill_values[3],
                        third_task_skill_values[3],
                        fourth_task_skill_values[3],
                    ),
                ]
            else:
                task_skill_bests = [*first_task_skill_values]
                for member in candidate[1:]:
                    task_skill_values = task_skill_values_by_person_id[
                        member.id
                    ]
                    for task_index, value in enumerate(task_skill_values):
                        if value > task_skill_bests[task_index]:
                            task_skill_bests[task_index] = value
            skill_score_upper = geometric_mean(task_skill_bests)

            non_social_upper_bound = (
                resolved_weights.alpha * skill_score_upper
                + resolved_weights.beta * personality_score
                + resolved_weights.gamma * task_preference_score
            )
            social_score_upper = _compat_candidate_social_upper_bound(
                people=candidate,
                team_signature=team_signature,
                social_cache=social_cache,
                social_preference_presence_cache=social_preference_presence_cache,
            )
            exact_upper_bound = (
                non_social_upper_bound
                + (resolved_weights.delta * social_score_upper)
            )
            cheap_bounded_candidates.append(
                (
                    exact_upper_bound,
                    index,
                    candidate,
                )
            )

        cheap_bounded_candidates.sort(
            key=lambda entry: (
                entry[0],
                -entry[1],
            ),
            reverse=True,
        )
        _REQUEST_COMPAT_SHORTLIST_CHEAP_BOUNDED_CANDIDATES[
            cheap_bounded_candidates_cache_key
        ] = (
            request,
            cheap_bounded_candidates,
        )

    for (
        exact_upper_bound,
        index,
        candidate,
    ) in cheap_bounded_candidates:
        if _objective_component_less(exact_upper_bound, best_quality):
            break

        scored_allocation = cached_score_team(
            request,
            task_id=task.id,
            people=candidate,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
            score_cache=score_cache,
        )
        scored_count += 1

        quality = scored_allocation.quality
        if first_quality is None:
            first_quality = quality
        elif not _objective_component_close(quality, first_quality):
            all_equal = False

        if best is None or quality > best_quality:
            best = scored_allocation
            best_quality = quality
            best_ids = None
        elif quality == best_quality:
            candidate_ids = tuple(sorted(member.id for member in candidate))
            if best_ids is None and best is not None:
                best_ids = tuple(sorted(member.id for member in best.people))
            if best_ids is None or candidate_ids > best_ids:
                best = scored_allocation
                best_ids = candidate_ids

        if index < max_candidate_teams:
            if best_first_k is None or quality > best_first_k_quality:
                best_first_k = scored_allocation
                best_first_k_quality = quality
                best_first_k_ids = None
            elif quality == best_first_k_quality:
                candidate_ids = tuple(sorted(member.id for member in candidate))
                if best_first_k_ids is None and best_first_k is not None:
                    best_first_k_ids = tuple(
                        sorted(member.id for member in best_first_k.people)
                    )
                if best_first_k_ids is None or candidate_ids > best_first_k_ids:
                    best_first_k = scored_allocation
                    best_first_k_ids = candidate_ids

    if best is None:
        return None

    if scored_count == shortlist_total and all_equal and best_first_k is not None:
        return best_first_k
    return best



def allocation_objective(
    allocations: list[ScoredAllocation],
) -> tuple[float, float, float]:
    qualities = [allocation.quality for allocation in allocations]
    if not qualities:
        return (0.0, 0.0, 0.0)
    product = 1.0
    for quality in qualities:
        product *= max(quality, 1e-12)
    return (product, min(qualities), sum(qualities))


def _objective_component_close(left: float, right: float) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=OBJECTIVE_REL_TOL,
        abs_tol=OBJECTIVE_ABS_TOL,
    )


def _objective_component_less(left: float, right: float) -> bool:
    if left >= right:
        return False
    tolerance = OBJECTIVE_REL_TOL * right
    if tolerance < OBJECTIVE_ABS_TOL:
        tolerance = OBJECTIVE_ABS_TOL
    return (right - left) > tolerance


def _objective_component_greater(left: float, right: float) -> bool:
    if left <= right:
        return False
    tolerance = OBJECTIVE_REL_TOL * left
    if tolerance < OBJECTIVE_ABS_TOL:
        tolerance = OBJECTIVE_ABS_TOL
    return (left - right) > tolerance


def _objective_better(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> bool:
    left_product, left_minimum, left_sum = left
    right_product, right_minimum, right_sum = right

    if _objective_component_greater(left_product, right_product):
        return True
    if _objective_component_less(left_product, right_product):
        return False

    if _objective_component_greater(left_minimum, right_minimum):
        return True
    if _objective_component_less(left_minimum, right_minimum):
        return False

    return _objective_component_greater(left_sum, right_sum)


def _objective_dominates(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> bool:
    left_minimum = left[1]
    left_sum = left[2]
    right_minimum = right[1]
    right_sum = right[2]

    if _objective_component_less(left_minimum, right_minimum):
        return False
    if _objective_component_less(left_sum, right_sum):
        return False

    return (
        _objective_component_greater(left_minimum, right_minimum)
        or _objective_component_greater(left_sum, right_sum)
    )


def score_team(
    request: FormationRequest,
    *,
    task_id: str,
    people: tuple[Person, ...],
    mode: Mode,
    preset: WeightPreset | None,
    normalize_weights: bool,
    team_signature: tuple[str, ...] | None = None,
) -> ScoredAllocation:
    task = _request_tasks_by_id(request)[task_id]
    if team_signature is None:
        team_signature = tuple(sorted(member.id for member in people))
    (
        personality_cache,
        social_cache,
        social_preference_presence_cache,
    ) = _request_team_component_caches(request)

    compat_task_preference_default = None
    compat_social_preference_default = None
    compat_zero_social_without_preferences = False
    valid_task_preferences: dict[str, float] | None = None
    if mode == Mode.COMPAT:
        valid_task_preferences = _request_task_preferences_by_task_id(request)[
            task_id
        ]
        has_team_social_preferences = social_preference_presence_cache.get(
            team_signature
        )
        if has_team_social_preferences is None:
            teammate_ids = {member.id for member in people}
            has_team_social_preferences = any(
                has_explicit_social_preferences(member, teammate_ids)
                for member in people
            )
            social_preference_presence_cache[team_signature] = (
                has_team_social_preferences
            )
        compat_task_preference_default = 0.0 if not valid_task_preferences else 0.5
        compat_social_preference_default = (
            0.0 if not has_team_social_preferences else 0.5
        )
        compat_zero_social_without_preferences = not has_team_social_preferences

    personality_cache_key = (mode, team_signature)
    personality_score = personality_cache.get(personality_cache_key)
    if personality_score is None:
        personality_score = team_personality_score(people, mode=mode)
        personality_cache[personality_cache_key] = personality_score

    social_score = 0.0
    if not compat_zero_social_without_preferences:
        social_preference_default = (
            0.5
            if compat_social_preference_default is None
            else compat_social_preference_default
        )
        social_cache_key = (social_preference_default, team_signature)
        social_score = social_cache.get(social_cache_key)
        if social_score is None:
            social_score = team_social_score(
                people,
                compat_default=social_preference_default,
            )
            social_cache[social_cache_key] = social_score

    components = _calculate_team_quality_components_for_people(
        task_skills=task.skills,
        team=people,
        alpha=request.alpha,
        beta=request.beta,
        gamma=request.gamma,
        delta=request.delta,
        similarities=request.similarities,
        mode=mode,
        preset=preset,
        normalize_weights=normalize_weights,
        task_preferences=valid_task_preferences,
        compat_task_preference_default=compat_task_preference_default,
        compat_social_preference_default=compat_social_preference_default,
        compat_zero_social_without_preferences=compat_zero_social_without_preferences,
        personality_score=personality_score,
        social_score=social_score,
        resolved_weights=_request_resolved_weights(
            request,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
        ),
    )
    return ScoredAllocation(
        task_id=task_id,
        people=people,
        quality=components.quality,
        assignments=components.assignments,
        team_signature=team_signature,
    )



_ORIGINAL_SCORE_TEAM = score_team



def cached_score_team(
    request: FormationRequest,
    *,
    task_id: str,
    people: tuple[Person, ...],
    mode: Mode,
    preset: WeightPreset | None,
    normalize_weights: bool,
    score_cache: dict[ScoreCacheKey, ScoredAllocation],
) -> ScoredAllocation:
    if len(people) == 4:
        first_id = people[0].id
        second_id = people[1].id
        third_id = people[2].id
        fourth_id = people[3].id

        if second_id < first_id:
            first_id, second_id = second_id, first_id
        if fourth_id < third_id:
            third_id, fourth_id = fourth_id, third_id
        if third_id < first_id:
            first_id, third_id = third_id, first_id
        if fourth_id < second_id:
            second_id, fourth_id = fourth_id, second_id
        if third_id < second_id:
            second_id, third_id = third_id, second_id

        team_signature = (first_id, second_id, third_id, fourth_id)
    else:
        team_signature = tuple(sorted(person.id for person in people))
    candidate_key = (task_id, team_signature)
    cached = score_cache.get(candidate_key)
    if cached is not None:
        return cached

    if score_team is _ORIGINAL_SCORE_TEAM:
        scored = score_team(
            request,
            task_id=task_id,
            people=people,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
            team_signature=team_signature,
        )
    else:
        scored = score_team(
            request,
            task_id=task_id,
            people=people,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
        )
    score_cache[candidate_key] = scored
    return scored


def _compat_candidate_social_upper_bound(
    *,
    people: tuple[Person, ...],
    team_signature: tuple[str, ...] | None,
    social_cache: dict[tuple[float, tuple[str, ...]], float],
    social_preference_presence_cache: dict[tuple[str, ...], bool],
) -> float:
    if team_signature is None:
        team_signature = tuple(sorted(member.id for member in people))

    has_team_social_preferences = social_preference_presence_cache.get(team_signature)
    if has_team_social_preferences is None:
        teammate_ids = {member.id for member in people}
        has_team_social_preferences = any(
            has_explicit_social_preferences(member, teammate_ids)
            for member in people
        )
        social_preference_presence_cache[team_signature] = (
            has_team_social_preferences
        )

    if not has_team_social_preferences:
        return 0.0

    social_cache_key = (0.5, team_signature)
    social_score_upper = social_cache.get(social_cache_key)
    if social_score_upper is None:
        social_score_upper = team_social_score(people, compat_default=0.5)
        social_cache[social_cache_key] = social_score_upper
    return social_score_upper


def _compat_candidate_quality_upper_bound(
    *,
    people: tuple[Person, ...],
    task_preferences: dict[str, float],
    task_preference_default: float,
    task_preference_logs_by_person_id: dict[str, float | None] | None,
    task_skill_values_by_person_id: dict[str, tuple[float, ...]],
    team_signature: tuple[str, ...] | None,
    resolved_weights,
    personality_cache: dict[tuple[Mode, tuple[str, ...]], float],
    social_cache: dict[tuple[float, tuple[str, ...]], float],
    social_preference_presence_cache: dict[tuple[str, ...], bool],
) -> float:
    if team_signature is None:
        team_signature = tuple(sorted(member.id for member in people))

    personality_cache_key = (Mode.COMPAT, team_signature)
    personality_score = personality_cache.get(personality_cache_key)
    if personality_score is None:
        personality_score = team_personality_score(people, mode=Mode.COMPAT)
        personality_cache[personality_cache_key] = personality_score

    social_score_upper = _compat_candidate_social_upper_bound(
        people=people,
        team_signature=team_signature,
        social_cache=social_cache,
        social_preference_presence_cache=social_preference_presence_cache,
    )

    if task_preference_logs_by_person_id is None:
        task_preference_score = _task_preference_score(
            people,
            task_preferences=task_preferences,
            compat_default=task_preference_default,
        )
    else:
        task_preference_log_sum = 0.0
        for member in people:
            task_preference_log = task_preference_logs_by_person_id[member.id]
            if task_preference_log is None:
                task_preference_score = 0.0
                break
            task_preference_log_sum += task_preference_log
        else:
            task_preference_score = math.exp(
                task_preference_log_sum / len(people)
            )

    first_task_skill_values = task_skill_values_by_person_id[people[0].id]
    if len(people) == 4 and len(first_task_skill_values) == 4:
        second_task_skill_values = task_skill_values_by_person_id[people[1].id]
        third_task_skill_values = task_skill_values_by_person_id[people[2].id]
        fourth_task_skill_values = task_skill_values_by_person_id[people[3].id]
        max_value = max
        task_skill_bests = [
            max_value(
                first_task_skill_values[0],
                second_task_skill_values[0],
                third_task_skill_values[0],
                fourth_task_skill_values[0],
            ),
            max_value(
                first_task_skill_values[1],
                second_task_skill_values[1],
                third_task_skill_values[1],
                fourth_task_skill_values[1],
            ),
            max_value(
                first_task_skill_values[2],
                second_task_skill_values[2],
                third_task_skill_values[2],
                fourth_task_skill_values[2],
            ),
            max_value(
                first_task_skill_values[3],
                second_task_skill_values[3],
                third_task_skill_values[3],
                fourth_task_skill_values[3],
            ),
        ]
    else:
        task_skill_bests = [*first_task_skill_values]
        for member in people[1:]:
            task_skill_values = task_skill_values_by_person_id[member.id]
            for task_index, value in enumerate(task_skill_values):
                if value > task_skill_bests[task_index]:
                    task_skill_bests[task_index] = value
    skill_score_upper = geometric_mean(task_skill_bests)

    return (
        resolved_weights.alpha * skill_score_upper
        + resolved_weights.beta * personality_score
        + resolved_weights.gamma * task_preference_score
        + resolved_weights.delta * social_score_upper
    )


def build_scored_candidates(
    request: FormationRequest,
    *,
    task_order,
    mode: Mode,
    preset: WeightPreset | None,
    normalize_weights: bool,
    max_candidate_teams: int | None,
    shortlist_padding: int,
    randomizer: random.Random | None,
    score_cache: dict[ScoreCacheKey, ScoredAllocation],
) -> list[list[tuple[int, ScoredAllocation]]]:
    person_index = {person.id: index for index, person in enumerate(request.people)}
    task_candidates: list[list[tuple[int, ScoredAllocation]]] = []

    for task in task_order:
        member_scorer, alternate_scorers = shortlist_scorers(
            request,
            people=request.people,
            task_id=task.id,
            team_size=task.team_size,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
        )
        def scored_candidate(
            candidate: tuple[Person, ...],
            *,
            task_id: str = task.id,
        ) -> ScoredAllocation:
            return cached_score_team(
                request,
                task_id=task_id,
                people=candidate,
                mode=mode,
                preset=preset,
                normalize_weights=normalize_weights,
                score_cache=score_cache,
            )

        candidates = candidate_combinations(
            people=request.people,
            team_size=task.team_size,
            max_candidate_teams=max_candidate_teams,
            shortlist_padding=shortlist_padding,
            scorer=member_scorer,
            alternate_scorers=alternate_scorers,
            combination_scorer=lambda candidate: scored_candidate(candidate).quality,
        )
        if request.init_random:
            assert randomizer is not None
            candidates = list(candidates)
            randomizer.shuffle(candidates)

        scored = []
        for candidate in candidates:
            mask = 0
            for person in candidate:
                mask |= 1 << person_index[person.id]
            scored.append(
                (
                    mask,
                    scored_candidate(candidate),
                )
            )
        task_candidates.append(scored)

    return task_candidates


def greedy_allocations(
    request: FormationRequest,
    *,
    task_order,
    mode: Mode,
    preset: WeightPreset | None,
    normalize_weights: bool,
    max_candidate_teams: int | None,
    shortlist_padding: int,
    randomizer: random.Random | None,
    score_cache: dict[ScoreCacheKey, ScoredAllocation],
) -> tuple[list[ScoredAllocation], list[Person]]:
    greedy_cache_key: tuple[
        int,
        tuple[str, ...],
        Mode,
        WeightPreset | None,
        bool,
        int | None,
        int,
    ] | None = None
    if score_team is _ORIGINAL_SCORE_TEAM and not request.init_random:
        greedy_cache_key = (
            id(request),
            tuple(task.id for task in task_order),
            mode,
            preset,
            normalize_weights,
            max_candidate_teams,
            shortlist_padding,
        )
        cached_greedy = _REQUEST_GREEDY_ALLOCATIONS.get(greedy_cache_key)
        if cached_greedy is not None and cached_greedy[0] is request:
            return [*cached_greedy[1]], [*cached_greedy[2]]

    remaining_people = list(request.people)
    allocations: list[ScoredAllocation] = []

    for task in task_order:
        task_id = task.id
        task_total = math.comb(len(remaining_people), task.team_size)

        member_scorer = _unused_member_scorer
        alternate_scorers: list[Callable[[Person], float]] = []
        if max_candidate_teams is not None and task_total > max_candidate_teams:
            member_scorer, alternate_scorers = shortlist_scorers(
                request,
                people=remaining_people,
                task_id=task_id,
                team_size=task.team_size,
                mode=mode,
                preset=preset,
                normalize_weights=normalize_weights,
            )

        use_upper_bound_pruning = (
            not request.init_random
            and mode == Mode.COMPAT
            and max_candidate_teams is not None
            and task_total <= max_candidate_teams
        )
        task_preferences: dict[str, float] = {}
        task_preference_default = 0.5
        task_preference_logs_by_person_id: dict[str, float | None] | None = None
        task_skill_values_by_person_id: dict[str, tuple[float, ...]] = {}
        personality_cache: dict[tuple[Mode, tuple[str, ...]], float] = {}
        social_cache: dict[tuple[float, tuple[str, ...]], float] = {}
        social_preference_presence_cache: dict[tuple[str, ...], bool] = {}
        resolved_weights = None
        compat_greedy_cheap_bounded_candidates: list[
            tuple[
                float,
                int,
                tuple[Person, ...],
            ]
        ] | None = None
        compat_greedy_cheap_bounded_candidates_cache_key: tuple[
            int,
            str,
            tuple[str, ...],
            Mode,
            WeightPreset | None,
            bool,
        ] | None = None

        if use_upper_bound_pruning:
            task_preferences = _request_task_preferences_by_task_id(request)[task_id]
            task_preference_default = 0.0 if not task_preferences else 0.5
            task_preference_logs_by_person_id = {}
            for person in remaining_people:
                task_preference = task_preferences.get(
                    person.id,
                    task_preference_default,
                )
                if task_preference <= 0:
                    task_preference_logs_by_person_id[person.id] = None
                    continue
                task_preference_logs_by_person_id[person.id] = math.log(
                    task_preference
                )

            task_skill_ids = tuple(skill.id for skill in task.skills)
            task_skill_values_by_person_id = {
                person.id: _compat_member_task_values(
                    person,
                    task.skills,
                    task_skill_ids=task_skill_ids,
                )
                for person in remaining_people
            }
            (
                personality_cache,
                social_cache,
                social_preference_presence_cache,
            ) = _request_team_component_caches(request)
            resolved_weights = _request_resolved_weights(
                request,
                mode=mode,
                preset=preset,
                normalize_weights=normalize_weights,
            )

            compat_greedy_cheap_bounded_candidates_cache_key = (
                id(request),
                task_id,
                tuple(person.id for person in remaining_people),
                mode,
                preset,
                normalize_weights,
            )
            cached_compat_greedy_cheap_bounded_candidates = (
                _REQUEST_COMPAT_GREEDY_CHEAP_BOUNDED_CANDIDATES.get(
                    compat_greedy_cheap_bounded_candidates_cache_key
                )
            )
            if (
                cached_compat_greedy_cheap_bounded_candidates is not None
                and cached_compat_greedy_cheap_bounded_candidates[0] is request
            ):
                compat_greedy_cheap_bounded_candidates = (
                    cached_compat_greedy_cheap_bounded_candidates[1]
                )

        def scored_candidate(
            candidate: tuple[Person, ...],
            *,
            task_id: str = task_id,
        ) -> ScoredAllocation:
            return cached_score_team(
                request,
                task_id=task_id,
                people=candidate,
                mode=mode,
                preset=preset,
                normalize_weights=normalize_weights,
                score_cache=score_cache,
            )

        best: ScoredAllocation | None = None
        if (
            not request.init_random
            and mode == Mode.COMPAT
            and max_candidate_teams is not None
            and task_total > max_candidate_teams
            and score_team is _ORIGINAL_SCORE_TEAM
        ):
            best = _best_scored_shortlist_candidate_with_compat_pruning(
                request=request,
                people=remaining_people,
                task=task,
                scorer=member_scorer,
                alternate_scorers=alternate_scorers,
                mode=mode,
                preset=preset,
                normalize_weights=normalize_weights,
                max_candidate_teams=max_candidate_teams,
                shortlist_padding=shortlist_padding,
                score_cache=score_cache,
            )

        if best is None:
            pre_scored_candidates: list[tuple[tuple[Person, ...], float]] = []
            if use_upper_bound_pruning:
                candidates: Iterable[tuple[Person, ...]] = itertools.combinations(
                    remaining_people,
                    task.team_size,
                )
            else:
                candidates = candidate_combinations(
                    people=remaining_people,
                    team_size=task.team_size,
                    max_candidate_teams=max_candidate_teams,
                    shortlist_padding=shortlist_padding,
                    scorer=member_scorer,
                    alternate_scorers=alternate_scorers,
                    combination_scorer=(
                        lambda candidate: scored_candidate(candidate).quality
                    ),
                    scored_combinations=pre_scored_candidates,
                )
                if request.init_random:
                    assert randomizer is not None
                    candidates = list(candidates)
                    randomizer.shuffle(candidates)

            if use_upper_bound_pruning and resolved_weights is not None:
                assert task_preference_logs_by_person_id is not None
                task_preference_logs = task_preference_logs_by_person_id

                best_quality = float('-inf')
                best_ids: tuple[str, ...] | None = None

                if compat_greedy_cheap_bounded_candidates is None:
                    cheap_bounded_candidates: list[
                        tuple[
                            float,
                            int,
                            tuple[Person, ...],
                        ]
                    ] = []
                    for index, candidate in enumerate(candidates):
                        if len(candidate) == 4:
                            team_signature = (
                                candidate[0].id,
                                candidate[1].id,
                                candidate[2].id,
                                candidate[3].id,
                            )
                        else:
                            team_signature = tuple(
                                member.id for member in candidate
                            )

                        personality_cache_key = (Mode.COMPAT, team_signature)
                        personality_score = personality_cache.get(
                            personality_cache_key
                        )
                        if personality_score is None:
                            personality_score = team_personality_score(
                                candidate,
                                mode=Mode.COMPAT,
                            )
                            personality_cache[personality_cache_key] = (
                                personality_score
                            )

                        task_preference_log_sum = 0.0
                        for member in candidate:
                            task_preference_log = task_preference_logs[member.id]
                            if task_preference_log is None:
                                task_preference_score = 0.0
                                break
                            task_preference_log_sum += task_preference_log
                        else:
                            task_preference_score = math.exp(
                                task_preference_log_sum / len(candidate)
                            )

                        first_task_skill_values = task_skill_values_by_person_id[
                            team_signature[0]
                        ]
                        if (
                            len(candidate) == 4
                            and len(first_task_skill_values) == 4
                        ):
                            second_task_skill_values = (
                                task_skill_values_by_person_id[
                                    team_signature[1]
                                ]
                            )
                            third_task_skill_values = (
                                task_skill_values_by_person_id[
                                    team_signature[2]
                                ]
                            )
                            fourth_task_skill_values = (
                                task_skill_values_by_person_id[
                                    team_signature[3]
                                ]
                            )
                            max_value = max
                            task_skill_bests = [
                                max_value(
                                    first_task_skill_values[0],
                                    second_task_skill_values[0],
                                    third_task_skill_values[0],
                                    fourth_task_skill_values[0],
                                ),
                                max_value(
                                    first_task_skill_values[1],
                                    second_task_skill_values[1],
                                    third_task_skill_values[1],
                                    fourth_task_skill_values[1],
                                ),
                                max_value(
                                    first_task_skill_values[2],
                                    second_task_skill_values[2],
                                    third_task_skill_values[2],
                                    fourth_task_skill_values[2],
                                ),
                                max_value(
                                    first_task_skill_values[3],
                                    second_task_skill_values[3],
                                    third_task_skill_values[3],
                                    fourth_task_skill_values[3],
                                ),
                            ]
                        else:
                            task_skill_bests = [*first_task_skill_values]
                            for member in candidate[1:]:
                                task_skill_values = (
                                    task_skill_values_by_person_id[member.id]
                                )
                                for task_index, value in enumerate(
                                    task_skill_values
                                ):
                                    if value > task_skill_bests[task_index]:
                                        task_skill_bests[task_index] = value
                        skill_score_upper = geometric_mean(task_skill_bests)

                        non_social_upper_bound = (
                            resolved_weights.alpha * skill_score_upper
                            + resolved_weights.beta * personality_score
                            + resolved_weights.gamma * task_preference_score
                        )
                        social_score_upper = (
                            _compat_candidate_social_upper_bound(
                                people=candidate,
                                team_signature=team_signature,
                                social_cache=social_cache,
                                social_preference_presence_cache=(
                                    social_preference_presence_cache
                                ),
                            )
                        )
                        exact_upper_bound = (
                            non_social_upper_bound
                            + (resolved_weights.delta * social_score_upper)
                        )
                        cheap_bounded_candidates.append(
                            (
                                exact_upper_bound,
                                index,
                                candidate,
                            )
                        )

                    cheap_bounded_candidates.sort(
                        key=lambda entry: (
                            entry[0],
                            -entry[1],
                        ),
                        reverse=True,
                    )
                    compat_greedy_cheap_bounded_candidates = (
                        cheap_bounded_candidates
                    )
                    if (
                        compat_greedy_cheap_bounded_candidates_cache_key
                        is not None
                    ):
                        _REQUEST_COMPAT_GREEDY_CHEAP_BOUNDED_CANDIDATES[
                            compat_greedy_cheap_bounded_candidates_cache_key
                        ] = (
                            request,
                            compat_greedy_cheap_bounded_candidates,
                        )

                assert compat_greedy_cheap_bounded_candidates is not None
                for (
                    exact_upper_bound,
                    _index,
                    candidate,
                ) in compat_greedy_cheap_bounded_candidates:
                    if _objective_component_less(
                        exact_upper_bound,
                        best_quality,
                    ):
                        break

                    scored_allocation = scored_candidate(candidate)
                    quality = scored_allocation.quality
                    if best is None or quality > best_quality:
                        best = scored_allocation
                        best_quality = quality
                        best_ids = None
                        continue
                    if quality == best_quality:
                        candidate_ids = tuple(
                            sorted(member.id for member in scored_allocation.people)
                        )
                        if best_ids is None and best is not None:
                            best_ids = tuple(
                                sorted(member.id for member in best.people)
                            )
                        if best_ids is None or candidate_ids > best_ids:
                            best = scored_allocation
                            best_ids = candidate_ids

                if best is None:
                    if compat_greedy_cheap_bounded_candidates:
                        best = scored_candidate(
                            compat_greedy_cheap_bounded_candidates[0][2]
                        )
                    else:
                        best = scored_candidate(next(iter(candidates)))
            else:
                if not request.init_random and pre_scored_candidates:
                    best_candidate_people: tuple[Person, ...] | None = None
                    best_quality = float('-inf')
                    best_ids: tuple[str, ...] | None = None
                    for candidate_people, quality in pre_scored_candidates:
                        if best_candidate_people is None or quality > best_quality:
                            best_candidate_people = candidate_people
                            best_quality = quality
                            best_ids = None
                            continue
                        if quality == best_quality:
                            candidate_ids = tuple(
                                sorted(member.id for member in candidate_people)
                            )
                            if best_ids is None and best_candidate_people is not None:
                                best_ids = tuple(
                                    sorted(
                                        member.id
                                        for member in best_candidate_people
                                    )
                                )
                            if best_ids is None or candidate_ids > best_ids:
                                best_candidate_people = candidate_people
                                best_ids = candidate_ids

                    assert best_candidate_people is not None
                    best = scored_candidate(best_candidate_people)
                else:
                    scored_candidates = [
                        scored_candidate(candidate)
                        for candidate in candidates
                    ]
                    if request.init_random:
                        best = max(
                            scored_candidates,
                            key=lambda candidate: candidate.quality,
                        )
                    else:
                        best = scored_candidates[0]
                        best_quality = best.quality
                        best_ids = None
                        for candidate in scored_candidates[1:]:
                            quality = candidate.quality
                            if quality > best_quality:
                                best = candidate
                                best_quality = quality
                                best_ids = None
                                continue
                            if quality == best_quality:
                                candidate_ids = tuple(
                                    sorted(member.id for member in candidate.people)
                                )
                                if best_ids is None:
                                    best_ids = tuple(
                                        sorted(member.id for member in best.people)
                                    )
                                if candidate_ids > best_ids:
                                    best = candidate
                                    best_ids = candidate_ids

        assert best is not None
        allocations.append(best)
        chosen_ids = {member.id for member in best.people}
        remaining_people = [
            person for person in remaining_people if person.id not in chosen_ids
        ]

    if greedy_cache_key is not None:
        _REQUEST_GREEDY_ALLOCATIONS[greedy_cache_key] = (
            request,
            tuple(allocations),
            tuple(remaining_people),
        )

    return allocations, remaining_people


def exact_allocations(
    request: FormationRequest,
    *,
    task_order,
    mode: Mode,
    preset: WeightPreset | None,
    normalize_weights: bool,
    max_candidate_teams: int | None,
    shortlist_padding: int,
    randomizer: random.Random | None,
    score_cache: dict[ScoreCacheKey, ScoredAllocation],
) -> tuple[list[ScoredAllocation], list[Person]] | None:
    task_candidates = [
        list(candidates)
        for candidates in build_scored_candidates(
            request,
            task_order=task_order,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
            max_candidate_teams=max_candidate_teams,
            shortlist_padding=shortlist_padding,
            randomizer=randomizer,
            score_cache=score_cache,
        )
    ]
    seats_needed = [0] * (len(task_order) + 1)
    for index in range(len(task_order) - 1, -1, -1):
        seats_needed[index] = seats_needed[index + 1] + task_order[index].team_size

    full_mask = (1 << len(request.people)) - 1
    ranked_candidate_indices: list[tuple[int, ...]] = []
    person_candidate_positions: list[tuple[int, ...]] = []
    all_candidate_positions: list[int] = []
    best_quality_suffix = [1.0] * (len(task_order) + 1)

    for task_index in range(len(task_order) - 1, -1, -1):
        best_quality = max(
            (candidate.quality for _, candidate in task_candidates[task_index]),
            default=0.0,
        )
        best_quality_suffix[task_index] = (
            best_quality_suffix[task_index + 1] * best_quality
        )

    for candidates in task_candidates:
        ranked_indices = tuple(
            sorted(
                range(len(candidates)),
                key=lambda candidate_index: (
                    -candidates[candidate_index][1].quality,
                    candidate_index,
                ),
            )
        )
        ranked_candidate_indices.append(ranked_indices)
        all_candidate_positions.append((1 << len(ranked_indices)) - 1)

        positions_by_person = [0] * len(request.people)
        for rank_position, candidate_index in enumerate(ranked_indices):
            candidate_mask, _ = candidates[candidate_index]
            position_mask = 1 << rank_position
            mask = candidate_mask
            while mask:
                person_bit = mask & -mask
                positions_by_person[person_bit.bit_length() - 1] |= position_mask
                mask ^= person_bit
        person_candidate_positions.append(tuple(positions_by_person))

    @dataclass(frozen=True, slots=True)
    class SuffixSolution:
        objective: tuple[float, float, float]
        indices: tuple[int, ...]

    @cache
    def compatible_candidate_positions(task_index: int, remaining_mask: int) -> int:
        invalid_positions = 0
        excluded_mask = full_mask ^ remaining_mask
        while excluded_mask:
            person_bit = excluded_mask & -excluded_mask
            invalid_positions |= person_candidate_positions[task_index][
                person_bit.bit_length() - 1
            ]
            excluded_mask ^= person_bit
        return all_candidate_positions[task_index] & ~invalid_positions

    @cache
    def solve(task_index: int, remaining_mask: int) -> tuple[SuffixSolution, ...]:
        if remaining_mask.bit_count() < seats_needed[task_index]:
            return ()
        if task_index == len(task_order):
            return (SuffixSolution((1.0, float('inf'), 0.0), ()),)

        candidate_positions = compatible_candidate_positions(task_index, remaining_mask)
        if candidate_positions == 0:
            return ()

        if task_index == len(task_order) - 1:
            best_position = candidate_positions & -candidate_positions
            rank_position = best_position.bit_length() - 1
            candidate_index = ranked_candidate_indices[task_index][rank_position]
            _, candidate = task_candidates[task_index][candidate_index]
            return (
                SuffixSolution(
                    (candidate.quality, candidate.quality, candidate.quality),
                    (candidate_index,),
                ),
            )

        best_product: float | None = None
        frontier: list[SuffixSolution] = []
        remaining_quality_upper = best_quality_suffix[task_index + 1]
        while candidate_positions:
            best_position = candidate_positions & -candidate_positions
            candidate_positions ^= best_position
            rank_position = best_position.bit_length() - 1
            candidate_index = ranked_candidate_indices[task_index][rank_position]
            candidate_mask, candidate = task_candidates[task_index][candidate_index]

            if (
                best_product is not None
                and _objective_component_less(
                    candidate.quality * remaining_quality_upper,
                    best_product,
                )
            ):
                break

            for rest in solve(task_index + 1, remaining_mask ^ candidate_mask):
                objective = (
                    candidate.quality * rest.objective[0],
                    min(candidate.quality, rest.objective[1]),
                    candidate.quality + rest.objective[2],
                )
                solution = SuffixSolution(objective, (candidate_index, *rest.indices))
                if best_product is None or _objective_component_greater(
                    objective[0],
                    best_product,
                ):
                    best_product = objective[0]
                    frontier = [solution]
                    continue
                if _objective_component_less(objective[0], best_product):
                    continue
                if any(
                    _objective_component_close(existing.objective[1], objective[1])
                    and _objective_component_close(
                        existing.objective[2],
                        objective[2],
                    )
                    for existing in frontier
                ):
                    continue
                frontier = [
                    existing
                    for existing in frontier
                    if not _objective_dominates(objective, existing.objective)
                ]
                if any(
                    _objective_dominates(existing.objective, objective)
                    for existing in frontier
                ):
                    continue
                frontier.append(solution)

        return tuple(frontier)

    solutions = solve(0, full_mask)
    if not solutions:
        return None
    solution = solutions[0]
    for candidate in solutions[1:]:
        if _objective_better(candidate.objective, solution.objective):
            solution = candidate

    chosen_indices = solution.indices
    allocations = [
        task_candidates[task_index][candidate_index][1]
        for task_index, candidate_index in enumerate(chosen_indices)
    ]
    used_mask = 0
    for task_index, candidate_index in enumerate(chosen_indices):
        used_mask |= task_candidates[task_index][candidate_index][0]
    unused_people = [
        person
        for index, person in enumerate(request.people)
        if not ((used_mask >> index) & 1)
    ]
    return allocations, unused_people


def improve_allocations(
    request: FormationRequest,
    *,
    allocations: list[ScoredAllocation],
    unused_people: list[Person],
    mode: Mode,
    preset: WeightPreset | None,
    normalize_weights: bool,
    swap_rounds: int,
    score_cache: dict[ScoreCacheKey, ScoredAllocation],
) -> list[ScoredAllocation]:
    improve_cache_key: tuple[
        int,
        tuple[tuple[str, tuple[str, ...]], ...],
        tuple[str, ...],
        Mode,
        WeightPreset | None,
        bool,
        int,
    ] | None = None
    if score_team is _ORIGINAL_SCORE_TEAM:
        improve_cache_key = (
            id(request),
            tuple(
                (
                    allocation.task_id,
                    (
                        allocation.team_signature
                        or tuple(member.id for member in allocation.people)
                    ),
                )
                for allocation in allocations
            ),
            tuple(person.id for person in unused_people),
            mode,
            preset,
            normalize_weights,
            swap_rounds,
        )
        cached_improved_allocations = _REQUEST_IMPROVED_ALLOCATIONS.get(
            improve_cache_key
        )
        if (
            cached_improved_allocations is not None
            and cached_improved_allocations[0] is request
        ):
            return [*cached_improved_allocations[1]]

    compat_swap_bound_data_by_task_id: dict[
        str,
        tuple[
            dict[str, float],
            float,
            dict[str, float | None],
            dict[str, tuple[float, ...]],
        ],
    ] = {}
    compat_swap_upper_bound_cache_by_task_id: dict[
        str,
        dict[tuple[str, ...], float],
    ] = {}
    compat_bound_resolved_weights = None
    compat_bound_personality_cache: dict[tuple[Mode, tuple[str, ...]], float] = {}
    compat_bound_social_cache: dict[tuple[float, tuple[str, ...]], float] = {}
    compat_bound_social_presence_cache: dict[tuple[str, ...], bool] = {}
    if mode == Mode.COMPAT and score_team is _ORIGINAL_SCORE_TEAM:
        compat_bound_resolved_weights = _request_resolved_weights(
            request,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
        )
        (
            compat_bound_personality_cache,
            compat_bound_social_cache,
            compat_bound_social_presence_cache,
        ) = _request_team_component_caches(request)

        swap_upper_bound_cache_key = (
            id(request),
            mode,
            preset,
            normalize_weights,
        )
        cached_swap_upper_bound_caches = (
            _REQUEST_COMPAT_SWAP_UPPER_BOUND_CACHES.get(
                swap_upper_bound_cache_key
            )
        )
        if (
            cached_swap_upper_bound_caches is not None
            and cached_swap_upper_bound_caches[0] is request
        ):
            compat_swap_upper_bound_cache_by_task_id = (
                cached_swap_upper_bound_caches[1]
            )
        else:
            compat_swap_upper_bound_cache_by_task_id = {}
            _REQUEST_COMPAT_SWAP_UPPER_BOUND_CACHES[
                swap_upper_bound_cache_key
            ] = (
                request,
                compat_swap_upper_bound_cache_by_task_id,
            )

        tasks_by_id = _request_tasks_by_id(request)
        task_preferences_by_task_id = _request_task_preferences_by_task_id(request)

        request_bound_data_cache_key = id(request)
        cached_request_bound_data_by_task_id = (
            _REQUEST_COMPAT_SWAP_BOUND_DATA_BY_TASK_ID.get(
                request_bound_data_cache_key
            )
        )
        if (
            cached_request_bound_data_by_task_id is not None
            and cached_request_bound_data_by_task_id[0] is request
        ):
            request_bound_data_by_task_id = (
                cached_request_bound_data_by_task_id[1]
            )
        else:
            request_bound_data_by_task_id: dict[
                str,
                tuple[
                    dict[str, float],
                    float,
                    dict[str, float | None],
                    dict[str, tuple[float, ...]],
                ],
            ] = {}
            _REQUEST_COMPAT_SWAP_BOUND_DATA_BY_TASK_ID[
                request_bound_data_cache_key
            ] = (
                request,
                request_bound_data_by_task_id,
            )

        for task_id in {allocation.task_id for allocation in allocations}:
            task_bound_data = request_bound_data_by_task_id.get(task_id)
            if task_bound_data is None:
                task = tasks_by_id[task_id]
                task_preferences = task_preferences_by_task_id[task_id]
                task_preference_default = 0.0 if not task_preferences else 0.5
                task_preference_logs_by_person_id: dict[str, float | None] = {}
                for person in request.people:
                    task_preference = task_preferences.get(
                        person.id,
                        task_preference_default,
                    )
                    if task_preference <= 0:
                        task_preference_logs_by_person_id[person.id] = None
                        continue
                    task_preference_logs_by_person_id[person.id] = math.log(
                        task_preference
                    )

                task_skill_ids = tuple(skill.id for skill in task.skills)
                task_skill_values_by_person_id = {
                    person.id: _compat_member_task_values(
                        person,
                        task.skills,
                        task_skill_ids=task_skill_ids,
                    )
                    for person in request.people
                }
                task_bound_data = (
                    task_preferences,
                    task_preference_default,
                    task_preference_logs_by_person_id,
                    task_skill_values_by_person_id,
                )
                request_bound_data_by_task_id[task_id] = task_bound_data

            compat_swap_bound_data_by_task_id[task_id] = task_bound_data
            compat_swap_upper_bound_cache_by_task_id.setdefault(task_id, {})

    use_compat_upper_bounds = (
        compat_bound_resolved_weights is not None
        and bool(compat_swap_bound_data_by_task_id)
    )

    improved = True
    rounds = 0
    while improved and rounds < swap_rounds:
        improved = False
        rounds += 1

        qualities = [allocation.quality for allocation in allocations]
        clamped_qualities = [max(quality, 1e-12) for quality in qualities]
        current_product = 1.0
        for quality in clamped_qualities:
            current_product *= quality
        current_min = min(qualities) if qualities else 0.0
        current_sum = sum(qualities)
        if unused_people:
            min_without_index = [
                min(
                    (
                        quality
                        for quality_index, quality in enumerate(qualities)
                        if quality_index != allocation_index
                    ),
                    default=0.0,
                )
                for allocation_index in range(len(qualities))
            ]

            for allocation_index, allocation in enumerate(allocations):
                old_quality = qualities[allocation_index]
                old_quality_for_product = clamped_qualities[allocation_index]
                for member in allocation.people:
                    for unused_person in list(unused_people):
                        replacement_team = tuple(
                            unused_person
                            if candidate.id == member.id
                            else candidate
                            for candidate in allocation.people
                        )
                        rescored_allocation = cached_score_team(
                            request,
                            task_id=allocation.task_id,
                            people=replacement_team,
                            mode=mode,
                            preset=preset,
                            normalize_weights=normalize_weights,
                            score_cache=score_cache,
                        )
                        replacement_quality = rescored_allocation.quality
                        trial_product = (
                            current_product
                            / old_quality_for_product
                            * max(replacement_quality, 1e-12)
                        )
                        if trial_product > current_product:
                            better_replacement = True
                        elif trial_product < current_product:
                            better_replacement = False
                        else:
                            if old_quality == current_min:
                                trial_min = min(
                                    replacement_quality,
                                    min_without_index[allocation_index],
                                )
                            else:
                                trial_min = min(
                                    current_min,
                                    replacement_quality,
                                )

                            if trial_min > current_min:
                                better_replacement = True
                            elif trial_min < current_min:
                                better_replacement = False
                            else:
                                trial_sum = (
                                    current_sum
                                    - old_quality
                                    + replacement_quality
                                )
                                better_replacement = (
                                    trial_sum > current_sum
                                )

                        if better_replacement:
                            allocations = allocations.copy()
                            allocations[allocation_index] = (
                                rescored_allocation
                            )
                            unused_people.remove(unused_person)
                            unused_people.append(member)
                            improved = True
                            break
                    if improved:
                        break
                if improved:
                    break

            if improved:
                continue

        for left_index, right_index in itertools.combinations(
            range(len(allocations)), 2
        ):
            left = allocations[left_index]
            right = allocations[right_index]
            old_left_quality = qualities[left_index]
            old_right_quality = qualities[right_index]
            pair_product_factor = (
                current_product
                / clamped_qualities[left_index]
                / clamped_qualities[right_index]
            )
            pair_sum_base = current_sum - old_left_quality - old_right_quality
            other_min = min(
                (
                    quality
                    for quality_index, quality in enumerate(qualities)
                    if quality_index not in (left_index, right_index)
                ),
                default=float('inf'),
            )
            left_people = left.people
            right_people = right.people
            signatures_are_fixed_len_four = (
                len(left_people) == 4 and len(right_people) == 4
            )
            left_swap_templates = [
                (
                    member_index,
                    left_people[member_index],
                    left_people[:member_index],
                    left_people[member_index + 1 :],
                )
                for member_index in range(len(left_people))
            ]
            right_swap_templates = [
                (
                    member_index,
                    right_people[member_index],
                    right_people[:member_index],
                    right_people[member_index + 1 :],
                )
                for member_index in range(len(right_people))
            ]
            if signatures_are_fixed_len_four:
                left_id0 = left_people[0].id
                left_id1 = left_people[1].id
                left_id2 = left_people[2].id
                left_id3 = left_people[3].id
                right_id0 = right_people[0].id
                right_id1 = right_people[1].id
                right_id2 = right_people[2].id
                right_id3 = right_people[3].id
            for (
                left_member_index,
                left_member,
                left_prefix,
                left_suffix,
            ) in left_swap_templates:
                for (
                    right_member_index,
                    right_member,
                    right_prefix,
                    right_suffix,
                ) in right_swap_templates:
                    swapped_left: tuple[Person, ...] | None = None
                    swapped_right: tuple[Person, ...] | None = None

                    if signatures_are_fixed_len_four:
                        right_member_id = right_member.id
                        if left_member_index == 0:
                            swapped_left_signature = (
                                right_member_id,
                                left_id1,
                                left_id2,
                                left_id3,
                            )
                        elif left_member_index == 1:
                            swapped_left_signature = (
                                left_id0,
                                right_member_id,
                                left_id2,
                                left_id3,
                            )
                        elif left_member_index == 2:
                            swapped_left_signature = (
                                left_id0,
                                left_id1,
                                right_member_id,
                                left_id3,
                            )
                        else:
                            swapped_left_signature = (
                                left_id0,
                                left_id1,
                                left_id2,
                                right_member_id,
                            )

                        left_member_id = left_member.id
                        if right_member_index == 0:
                            swapped_right_signature = (
                                left_member_id,
                                right_id1,
                                right_id2,
                                right_id3,
                            )
                        elif right_member_index == 1:
                            swapped_right_signature = (
                                right_id0,
                                left_member_id,
                                right_id2,
                                right_id3,
                            )
                        elif right_member_index == 2:
                            swapped_right_signature = (
                                right_id0,
                                right_id1,
                                left_member_id,
                                right_id3,
                            )
                        else:
                            swapped_right_signature = (
                                right_id0,
                                right_id1,
                                right_id2,
                                left_member_id,
                            )
                    else:
                        swapped_left = left_prefix + (right_member,) + left_suffix
                        swapped_right = right_prefix + (left_member,) + right_suffix
                        swapped_left_signature = tuple(
                            member.id for member in swapped_left
                        )
                        swapped_right_signature = tuple(
                            member.id for member in swapped_right
                        )

                    if use_compat_upper_bounds:
                        (
                            left_task_preferences,
                            left_task_preference_default,
                            left_task_preference_logs_by_person_id,
                            left_task_skill_values_by_person_id,
                        ) = compat_swap_bound_data_by_task_id[left.task_id]
                        (
                            right_task_preferences,
                            right_task_preference_default,
                            right_task_preference_logs_by_person_id,
                            right_task_skill_values_by_person_id,
                        ) = compat_swap_bound_data_by_task_id[right.task_id]

                        left_upper_bound_cache = (
                            compat_swap_upper_bound_cache_by_task_id[left.task_id]
                        )
                        left_upper_bound = left_upper_bound_cache.get(
                            swapped_left_signature
                        )
                        if left_upper_bound is None:
                            if swapped_left is None:
                                swapped_left = (
                                    left_prefix
                                    + (right_member,)
                                    + left_suffix
                                )
                            left_upper_bound = _compat_candidate_quality_upper_bound(
                                people=swapped_left,
                                task_preferences=left_task_preferences,
                                task_preference_default=(
                                    left_task_preference_default
                                ),
                                task_preference_logs_by_person_id=(
                                    left_task_preference_logs_by_person_id
                                ),
                                task_skill_values_by_person_id=(
                                    left_task_skill_values_by_person_id
                                ),
                                team_signature=swapped_left_signature,
                                resolved_weights=compat_bound_resolved_weights,
                                personality_cache=compat_bound_personality_cache,
                                social_cache=compat_bound_social_cache,
                                social_preference_presence_cache=(
                                    compat_bound_social_presence_cache
                                ),
                            )
                            left_upper_bound_cache[
                                swapped_left_signature
                            ] = left_upper_bound

                        right_upper_bound_cache = (
                            compat_swap_upper_bound_cache_by_task_id[right.task_id]
                        )
                        right_upper_bound = right_upper_bound_cache.get(
                            swapped_right_signature
                        )
                        if right_upper_bound is None:
                            if swapped_right is None:
                                swapped_right = (
                                    right_prefix
                                    + (left_member,)
                                    + right_suffix
                                )
                            right_upper_bound = (
                                _compat_candidate_quality_upper_bound(
                                    people=swapped_right,
                                    task_preferences=right_task_preferences,
                                    task_preference_default=(
                                        right_task_preference_default
                                    ),
                                    task_preference_logs_by_person_id=(
                                        right_task_preference_logs_by_person_id
                                    ),
                                    task_skill_values_by_person_id=(
                                        right_task_skill_values_by_person_id
                                    ),
                                    team_signature=swapped_right_signature,
                                    resolved_weights=(
                                        compat_bound_resolved_weights
                                    ),
                                    personality_cache=(
                                        compat_bound_personality_cache
                                    ),
                                    social_cache=compat_bound_social_cache,
                                    social_preference_presence_cache=(
                                        compat_bound_social_presence_cache
                                    ),
                                )
                            )
                            right_upper_bound_cache[
                                swapped_right_signature
                            ] = right_upper_bound
                        upper_trial_product = (
                            pair_product_factor
                            * max(left_upper_bound, 1e-12)
                            * max(right_upper_bound, 1e-12)
                        )
                        if _objective_component_less(
                            upper_trial_product,
                            current_product,
                        ):
                            continue
                        if _objective_component_close(
                            upper_trial_product,
                            current_product,
                        ):
                            upper_trial_min = min(
                                other_min,
                                left_upper_bound,
                                right_upper_bound,
                            )
                            if _objective_component_less(
                                upper_trial_min,
                                current_min,
                            ):
                                continue
                            if _objective_component_close(
                                upper_trial_min,
                                current_min,
                            ):
                                upper_trial_sum = (
                                    pair_sum_base
                                    + left_upper_bound
                                    + right_upper_bound
                                )
                                if _objective_component_less(
                                    upper_trial_sum,
                                    current_sum,
                                ):
                                    continue

                    rescored_left: ScoredAllocation | None = None
                    rescored_right: ScoredAllocation | None = None
                    if signatures_are_fixed_len_four:
                        left_sig0, left_sig1, left_sig2, left_sig3 = (
                            swapped_left_signature
                        )
                        if left_sig1 < left_sig0:
                            left_sig0, left_sig1 = left_sig1, left_sig0
                        if left_sig3 < left_sig2:
                            left_sig2, left_sig3 = left_sig3, left_sig2
                        if left_sig2 < left_sig0:
                            left_sig0, left_sig2 = left_sig2, left_sig0
                        if left_sig3 < left_sig1:
                            left_sig1, left_sig3 = left_sig3, left_sig1
                        if left_sig2 < left_sig1:
                            left_sig1, left_sig2 = left_sig2, left_sig1
                        rescored_left = score_cache.get(
                            (
                                left.task_id,
                                (
                                    left_sig0,
                                    left_sig1,
                                    left_sig2,
                                    left_sig3,
                                ),
                            )
                        )

                        right_sig0, right_sig1, right_sig2, right_sig3 = (
                            swapped_right_signature
                        )
                        if right_sig1 < right_sig0:
                            right_sig0, right_sig1 = right_sig1, right_sig0
                        if right_sig3 < right_sig2:
                            right_sig2, right_sig3 = right_sig3, right_sig2
                        if right_sig2 < right_sig0:
                            right_sig0, right_sig2 = right_sig2, right_sig0
                        if right_sig3 < right_sig1:
                            right_sig1, right_sig3 = right_sig3, right_sig1
                        if right_sig2 < right_sig1:
                            right_sig1, right_sig2 = right_sig2, right_sig1
                        rescored_right = score_cache.get(
                            (
                                right.task_id,
                                (
                                    right_sig0,
                                    right_sig1,
                                    right_sig2,
                                    right_sig3,
                                ),
                            )
                        )

                    if rescored_left is None:
                        if swapped_left is None:
                            swapped_left = (
                                left_prefix + (right_member,) + left_suffix
                            )
                        rescored_left = cached_score_team(
                            request,
                            task_id=left.task_id,
                            people=swapped_left,
                            mode=mode,
                            preset=preset,
                            normalize_weights=normalize_weights,
                            score_cache=score_cache,
                        )
                    if rescored_right is None:
                        if swapped_right is None:
                            swapped_right = (
                                right_prefix + (left_member,) + right_suffix
                            )
                        rescored_right = cached_score_team(
                            request,
                            task_id=right.task_id,
                            people=swapped_right,
                            mode=mode,
                            preset=preset,
                            normalize_weights=normalize_weights,
                            score_cache=score_cache,
                        )

                    trial_product = (
                        pair_product_factor
                        * max(rescored_left.quality, 1e-12)
                        * max(rescored_right.quality, 1e-12)
                    )
                    if trial_product > current_product:
                        better_swap = True
                    elif trial_product < current_product:
                        better_swap = False
                    else:
                        trial_min = min(
                            other_min,
                            rescored_left.quality,
                            rescored_right.quality,
                        )
                        if trial_min > current_min:
                            better_swap = True
                        elif trial_min < current_min:
                            better_swap = False
                        else:
                            trial_sum = (
                                pair_sum_base
                                + rescored_left.quality
                                + rescored_right.quality
                            )
                            better_swap = trial_sum > current_sum

                    if better_swap:
                        allocations = allocations.copy()
                        allocations[left_index] = rescored_left
                        allocations[right_index] = rescored_right
                        improved = True
                        break
                if improved:
                    break
            if improved:
                break

    if improve_cache_key is not None:
        _REQUEST_IMPROVED_ALLOCATIONS[improve_cache_key] = (
            request,
            tuple(allocations),
        )

    return allocations


def form_teams(
    request: FormationRequest,
    *,
    mode: Mode = Mode.COMPAT,
    preset: WeightPreset | None = None,
    normalize_weights: bool = False,
    max_candidate_teams: int | None = None,
    shortlist_padding: int = 6,
    swap_rounds: int = 8,
    seed: int | None = None,
) -> TeamsResponse:
    validate_max_candidate_teams(max_candidate_teams)
    if sum(task.team_size for task in request.tasks) > len(request.people):
        raise TeamFormationError(
            'Cannot form teams with the provided data: insufficient headcount.'
        )

    randomizer: random.Random | None = None
    if request.init_random:
        randomizer = random.Random(seed)
    score_cache: dict[ScoreCacheKey, ScoredAllocation] = {}
    if score_team is _ORIGINAL_SCORE_TEAM:
        form_score_cache_key = (
            id(request),
            mode,
            preset,
            normalize_weights,
        )
        cached_form_score_cache = _REQUEST_FORM_SCORE_CACHES.get(
            form_score_cache_key
        )
        if (
            cached_form_score_cache is not None
            and cached_form_score_cache[0] is request
        ):
            score_cache = cached_form_score_cache[1]
        else:
            _REQUEST_FORM_SCORE_CACHES[form_score_cache_key] = (
                request,
                score_cache,
            )

    task_order_cache_key = (id(request), mode)
    cached_task_order = _REQUEST_TASK_ORDER_BY_HARDNESS.get(
        task_order_cache_key
    )
    if cached_task_order is not None and cached_task_order[0] is request:
        task_order = [*cached_task_order[1]]
    else:
        task_order = list(request.tasks)
        task_order.sort(
            key=lambda task: (
                -task_hardness(task.id, request, mode=mode),
                task.id,
            )
        )
        _REQUEST_TASK_ORDER_BY_HARDNESS[task_order_cache_key] = (
            request,
            tuple(task_order),
        )

    task_order_original_indices: tuple[int, ...] | None = None
    if not request.init_random:
        cached_task_order_original_indices = (
            _REQUEST_TASK_ORDER_BY_ORIGINAL_INDICES.get(task_order_cache_key)
        )
        if (
            cached_task_order_original_indices is not None
            and cached_task_order_original_indices[0] is request
        ):
            task_order_original_indices = (
                cached_task_order_original_indices[1]
            )
        else:
            original_order = _request_task_original_order(request)
            task_order_original_indices = tuple(
                sorted(
                    range(len(task_order)),
                    key=lambda task_index: (
                        original_order[task_order[task_index].id]
                    ),
                )
            )
            _REQUEST_TASK_ORDER_BY_ORIGINAL_INDICES[task_order_cache_key] = (
                request,
                task_order_original_indices,
            )

    if request.init_random:
        assert randomizer is not None
        randomizer.shuffle(task_order)

    exact = None
    if capped_candidate_search_is_exact(
        request,
        max_candidate_teams=max_candidate_teams,
    ):
        exact = exact_allocations(
            request,
            task_order=task_order,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
            max_candidate_teams=max_candidate_teams,
            shortlist_padding=shortlist_padding,
            randomizer=randomizer,
            score_cache=score_cache,
        )
    if exact is None:
        allocations, unused_people = greedy_allocations(
            request,
            task_order=task_order,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
            max_candidate_teams=max_candidate_teams,
            shortlist_padding=shortlist_padding,
            randomizer=randomizer,
            score_cache=score_cache,
        )
    else:
        allocations, unused_people = exact

    if swap_rounds > 0:
        allocations = improve_allocations(
            request,
            allocations=allocations,
            unused_people=unused_people,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
            swap_rounds=swap_rounds,
            score_cache=score_cache,
        )

    if task_order_original_indices is None:
        original_order = _request_task_original_order(request)
        ordered_allocations = sorted(
            allocations,
            key=lambda allocation: original_order[allocation.task_id],
        )
    else:
        ordered_allocations = [
            allocations[task_index]
            for task_index in task_order_original_indices
        ]

    teams_payload: list[dict[str, object]] = []
    for allocation in ordered_allocations:
        people_payload: list[dict[str, object]] = []
        for person_id, skill_ids in allocation.assignments.items():
            people_payload.append(
                {
                    'id': person_id,
                    'skillIds': skill_ids,
                }
            )
        teams_payload.append(
            {
                'taskId': allocation.task_id,
                'people': people_payload,
                'quality': allocation.quality,
            }
        )

    return TeamsResponse.model_validate({'teams': teams_payload})
