from __future__ import annotations

import heapq
import itertools
import math
import random
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from typing import overload

from .models import FormationRequest, Person, Task, TeamResult, TeamsResponse
from .modes import Mode, WeightPreset
from .scoring import (
    _calculate_team_quality_components_for_people,
    _compat_member_task_values,
    _task_preference_score,
    assigned_people_from_assignments,
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


class TeamFormationError(ValueError):
    pass


ScoreCacheKey = tuple[str, tuple[str, ...]]

DEFAULT_MAX_CANDIDATE_TEAMS = 10_000
MAX_SCORED_COMBINATION_EXPANSION = 4
OBJECTIVE_REL_TOL = 1e-12
OBJECTIVE_ABS_TOL = 1e-15

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


def _request_tasks_by_id(request: FormationRequest) -> dict[str, Task]:
    cache_key = id(request)
    cached = _REQUEST_TASKS_BY_ID.get(cache_key)
    if cached is not None and cached[0] is request:
        return cached[1]

    tasks_by_id = {task.id: task for task in request.tasks}
    _REQUEST_TASKS_BY_ID[cache_key] = (request, tasks_by_id)
    return tasks_by_id


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
    shortlist_total = math.comb(len(shortlist), task.team_size)
    if shortlist_total != max_candidate_teams + 1:
        return None

    task_preferences = _request_task_preferences_by_task_id(request)[task.id]
    task_preference_default = 0.0 if not task_preferences else 0.5
    task_preference_logs_by_person_id: dict[str, float | None] = {}
    for person in request.people:
        task_preference = task_preferences.get(person.id, task_preference_default)
        if task_preference <= 0:
            task_preference_logs_by_person_id[person.id] = None
            continue
        task_preference_logs_by_person_id[person.id] = math.log(task_preference)

    task_skill_ids = tuple(skill.id for skill in task.skills)
    task_skill_values_by_person_id = {
        person.id: _compat_member_task_values(
            person,
            task.skills,
            task_skill_ids=task_skill_ids,
        )
        for person in request.people
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

    best: ScoredAllocation | None = None
    best_quality = float('-inf')
    best_ids: tuple[str, ...] | None = None

    best_first_k: ScoredAllocation | None = None
    best_first_k_quality = float('-inf')
    best_first_k_ids: tuple[str, ...] | None = None

    first_quality: float | None = None
    all_equal = True
    scored_count = 0

    bounded_candidates: list[tuple[float, int, tuple[Person, ...]]] = []
    combinations = itertools.combinations(shortlist, task.team_size)
    for index, candidate in enumerate(combinations):
        upper_bound = _compat_candidate_quality_upper_bound(
            people=candidate,
            task_preferences=task_preferences,
            task_preference_default=task_preference_default,
            task_preference_logs_by_person_id=(
                task_preference_logs_by_person_id
            ),
            task_skill_values_by_person_id=task_skill_values_by_person_id,
            resolved_weights=resolved_weights,
            personality_cache=personality_cache,
            social_cache=social_cache,
            social_preference_presence_cache=social_preference_presence_cache,
        )
        bounded_candidates.append((upper_bound, index, candidate))

    bounded_candidates.sort(
        key=lambda entry: (
            entry[0],
            -entry[1],
        ),
        reverse=True,
    )

    for upper_bound, index, candidate in bounded_candidates:
        if best is not None and _objective_component_less(upper_bound, best_quality):
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
    return left < right and not _objective_component_close(left, right)


def _objective_component_greater(left: float, right: float) -> bool:
    return left > right and not _objective_component_close(left, right)


def _objective_better(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> bool:
    for left_value, right_value in zip(left, right, strict=True):
        if _objective_component_greater(left_value, right_value):
            return True
        if _objective_component_less(left_value, right_value):
            return False
    return False


def _objective_dominates(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> bool:
    comparisons = zip(left[1:], right[1:], strict=True)
    if not all(
        left_value > right_value
        or _objective_component_close(left_value, right_value)
        for left_value, right_value in comparisons
    ):
        return False
    return any(
        _objective_component_greater(left_value, right_value)
        for left_value, right_value in zip(left[1:], right[1:], strict=True)
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


def _compat_candidate_quality_upper_bound(
    *,
    people: tuple[Person, ...],
    task_preferences: dict[str, float],
    task_preference_default: float,
    task_preference_logs_by_person_id: dict[str, float | None] | None,
    task_skill_values_by_person_id: dict[str, tuple[float, ...]],
    resolved_weights,
    personality_cache: dict[tuple[Mode, tuple[str, ...]], float],
    social_cache: dict[tuple[float, tuple[str, ...]], float],
    social_preference_presence_cache: dict[tuple[str, ...], bool],
) -> float:
    team_signature = tuple(sorted(member.id for member in people))

    personality_cache_key = (Mode.COMPAT, team_signature)
    personality_score = personality_cache.get(personality_cache_key)
    if personality_score is None:
        personality_score = team_personality_score(people, mode=Mode.COMPAT)
        personality_cache[personality_cache_key] = personality_score

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

    social_score_upper = 0.0
    if has_team_social_preferences:
        social_cache_key = (0.5, team_signature)
        social_score_upper = social_cache.get(social_cache_key)
        if social_score_upper is None:
            social_score_upper = team_social_score(people, compat_default=0.5)
            social_cache[social_cache_key] = social_score_upper

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

    task_skill_rows = [task_skill_values_by_person_id[member.id] for member in people]
    task_skill_bests = [0.0] * len(task_skill_rows[0])
    for task_skill_values in task_skill_rows:
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
    randomizer: random.Random,
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
    randomizer: random.Random,
    score_cache: dict[ScoreCacheKey, ScoredAllocation],
) -> tuple[list[ScoredAllocation], list[Person]]:
    remaining_people = list(request.people)
    allocations: list[ScoredAllocation] = []

    for task in task_order:
        task_id = task.id
        member_scorer, alternate_scorers = shortlist_scorers(
            request,
            people=remaining_people,
            task_id=task_id,
            team_size=task.team_size,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
        )

        task_total = math.comb(len(remaining_people), task.team_size)
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
        if use_upper_bound_pruning:
            task_preferences = _request_task_preferences_by_task_id(request)[task_id]
            task_preference_default = 0.0 if not task_preferences else 0.5
            task_preference_logs_by_person_id = {}
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
                candidates = list(candidates)
                randomizer.shuffle(candidates)

            if use_upper_bound_pruning and resolved_weights is not None:
                best_quality = float('-inf')
                best_ids: tuple[str, ...] | None = None
                for candidate in candidates:
                    upper_bound = _compat_candidate_quality_upper_bound(
                        people=candidate,
                        task_preferences=task_preferences,
                        task_preference_default=task_preference_default,
                        task_preference_logs_by_person_id=(
                            task_preference_logs_by_person_id
                        ),
                        task_skill_values_by_person_id=(
                            task_skill_values_by_person_id
                        ),
                        resolved_weights=resolved_weights,
                        personality_cache=personality_cache,
                        social_cache=social_cache,
                        social_preference_presence_cache=(
                            social_preference_presence_cache
                        ),
                    )
                    if (
                        best is not None
                        and _objective_component_less(upper_bound, best_quality)
                    ):
                        continue

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
    randomizer: random.Random,
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
        current_objective = (current_product, current_min, current_sum)
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
                        unused_person if candidate.id == member.id else candidate
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
                    trial_sum = current_sum - old_quality + replacement_quality
                    if old_quality == current_min:
                        trial_min = min(
                            replacement_quality,
                            min_without_index[allocation_index],
                        )
                    else:
                        trial_min = min(current_min, replacement_quality)

                    if (trial_product, trial_min, trial_sum) > current_objective:
                        allocations = allocations.copy()
                        allocations[allocation_index] = rescored_allocation
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
            other_min = min(
                (
                    quality
                    for quality_index, quality in enumerate(qualities)
                    if quality_index not in (left_index, right_index)
                ),
                default=float('inf'),
            )
            for left_member in left.people:
                for right_member in right.people:
                    swapped_left = tuple(
                        right_member if member.id == left_member.id else member
                        for member in left.people
                    )
                    swapped_right = tuple(
                        left_member if member.id == right_member.id else member
                        for member in right.people
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
                        current_product
                        / clamped_qualities[left_index]
                        / clamped_qualities[right_index]
                        * max(rescored_left.quality, 1e-12)
                        * max(rescored_right.quality, 1e-12)
                    )
                    trial_sum = (
                        current_sum
                        - old_left_quality
                        - old_right_quality
                        + rescored_left.quality
                        + rescored_right.quality
                    )
                    trial_min = min(
                        other_min,
                        rescored_left.quality,
                        rescored_right.quality,
                    )

                    if (trial_product, trial_min, trial_sum) > current_objective:
                        allocations = allocations.copy()
                        allocations[left_index] = rescored_left
                        allocations[right_index] = rescored_right
                        improved = True
                        break
                if improved:
                    break
            if improved:
                break

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
    if request.total_requested_seats > len(request.people):
        raise TeamFormationError(
            'Cannot form teams with the provided data: insufficient headcount.'
        )

    randomizer = random.Random(seed)
    score_cache: dict[ScoreCacheKey, ScoredAllocation] = {}
    task_order = list(request.tasks)
    task_order.sort(
        key=lambda task: (-task_hardness(task.id, request, mode=mode), task.id)
    )
    if request.init_random:
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

    original_order = {task.id: index for index, task in enumerate(request.tasks)}
    teams = [
        TeamResult(
            taskId=allocation.task_id,
            people=assigned_people_from_assignments(allocation.assignments),
            quality=allocation.quality,
        )
        for allocation in sorted(
            allocations,
            key=lambda allocation: original_order[allocation.task_id],
        )
    ]
    return TeamsResponse(teams=teams)
