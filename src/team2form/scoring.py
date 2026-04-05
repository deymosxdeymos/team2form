from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass

from .models import (
    AssignedPerson,
    Person,
    PersonPreference,
    PersonSkill,
    QualityBreakdown,
    Similarity,
    Task,
    TaskPreference,
    TaskSkill,
    TeamMember,
    TeamQualityRequest,
)
from .modes import Mode, WeightPreset
from .weights import Weights, resolve_weights

EPSILON = 1e-12
MAX_EXACT_PARTITIONED_TASK_SKILLS = 12
_COMPAT_GENDER_BONUS_BALANCED = 0.075
_COMPAT_GENDER_BONUS_ONE_UNKNOWN = 0.075 * math.sin(math.pi * 0.25)

_COMPAT_MEMBER_TASK_VALUES_CACHE: dict[
    tuple[int, tuple[str, ...]],
    tuple[Person, tuple[float, ...]],
] = {}

_COMPAT_RICH_PRIORITY_TASKS_CACHE: dict[
    tuple[tuple[str, ...], tuple[int, ...], tuple[float, ...]],
    tuple[tuple[float, int, str, int], ...],
] = {}


@dataclass(slots=True)
class AssignmentResult:
    assignments: dict[str, list[str]]
    skill_score: float


@dataclass(slots=True)
class _TeamQualityComponents:
    quality: float
    skill_score: float
    personality_score: float
    task_preference_score: float
    social_score: float
    assignments: dict[str, list[str]]
    weights: Weights


def geometric_mean(values: Iterable[float]) -> float:
    log = math.log
    exp = math.exp

    if isinstance(values, list) and len(values) == 4:
        first, second, third, fourth = values
        if first <= 0 or second <= 0 or third <= 0 or fourth <= 0:
            return 0.0
        return exp(
            (
                log(first)
                + log(second)
                + log(third)
                + log(fourth)
            )
            / 4.0
        )

    count = 0
    log_sum = 0.0
    for value in values:
        if value <= 0:
            return 0.0
        log_sum += log(value)
        count += 1

    if count == 0:
        return 0.0
    return exp(log_sum / count)


def weighted_geometric_mean(values: Iterable[tuple[float, float]]) -> float:
    collected = [(value, weight) for value, weight in values if weight > 0]
    if not collected:
        return 0.0
    total_weight = sum(weight for _, weight in collected)
    if total_weight <= 0:
        return 0.0
    if any(value <= 0 for value, _ in collected):
        return 0.0
    return math.exp(
        sum((weight / total_weight) * math.log(value) for value, weight in collected)
    )


def preference_lookup(
    preferences: list[PersonPreference] | list[TaskPreference] | None,
    *,
    valid_person_ids: Collection[str] | None = None,
) -> dict[str, float]:
    if not preferences:
        return {}
    return {
        preference.person_id: preference.preference
        for preference in preferences
        if valid_person_ids is None or preference.person_id in valid_person_ids
    }


def similarity_lookup(
    similarities: list[Similarity] | None,
) -> dict[tuple[str, str], float]:
    if not similarities:
        return {}
    return {
        (similarity.source_id, similarity.target_id): similarity.similarity
        for similarity in similarities
    }


def task_preference_for_member(
    member: TeamMember,
    *,
    compat_default: float,
) -> float:
    if member.task_preference is not None:
        return member.task_preference
    return compat_default



def _task_preference_score(
    team: Sequence[Person],
    *,
    task_preferences: dict[str, float] | None,
    compat_default: float,
) -> float:
    if not team:
        return 0.0
    if not task_preferences:
        return compat_default

    log_sum = 0.0
    count = 0
    for member in team:
        value = task_preferences.get(member.id, compat_default)
        if value <= 0:
            return 0.0
        log_sum += math.log(value)
        count += 1
    if count == 0:
        return 0.0
    return math.exp(log_sum / count)



def social_preference_for_pair(
    member: Person,
    teammate_id: str,
    *,
    compat_default: float,
) -> float:
    if member.id == teammate_id:
        return 1.0
    mapping = preference_lookup(member.preferences)
    return mapping.get(teammate_id, compat_default)


def team_task_preferences(
    team: list[TeamMember],
    *,
    compat_default: float,
) -> float:
    return geometric_mean(
        task_preference_for_member(member, compat_default=compat_default)
        for member in team
    )



def team_social_score(
    team: Sequence[Person],
    *,
    compat_default: float,
) -> float:
    if not team:
        return 0.0

    if len(team) == 2:
        first_member, second_member = team

        first_pair_preference = compat_default
        if first_member.preferences:
            for preference in first_member.preferences:
                if preference.person_id == second_member.id:
                    first_pair_preference = preference.preference
                    break

        second_pair_preference = compat_default
        if second_member.preferences:
            for preference in second_member.preferences:
                if preference.person_id == first_member.id:
                    second_pair_preference = preference.preference
                    break

        first_member_score = (1.0 + first_pair_preference) / 2.0
        second_member_score = (1.0 + second_pair_preference) / 2.0
        if first_member_score <= 0 or second_member_score <= 0:
            return 0.0
        return math.sqrt(first_member_score * second_member_score)

    preference_mappings = {
        member.id: preference_lookup(member.preferences)
        for member in team
    }
    teammate_ids = tuple(member.id for member in team)
    member_scores: list[float] = []
    for member in team:
        mapping = preference_mappings[member.id]
        member_scores.append(
            sum(
                1.0
                if member.id == teammate_id
                else mapping.get(teammate_id, compat_default)
                for teammate_id in teammate_ids
            )
            / len(team)
        )
    return geometric_mean(member_scores)


def _population_stddev(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)



def team_personality_score(team: Sequence[Person], *, mode: Mode) -> float:
    if not team:
        return 0.0

    if len(team) == 2:
        first_member, second_member = team
        first_personality = first_member.personality
        second_personality = second_member.personality

        first_ei = first_personality.ei
        first_sn = first_personality.sn
        first_tf = first_personality.tf
        first_pj = first_personality.pj

        second_ei = second_personality.ei
        second_sn = second_personality.sn
        second_tf = second_personality.tf
        second_pj = second_personality.pj

        sn_stddev = abs(first_sn - second_sn) / 2.0
        tf_stddev = abs(first_tf - second_tf) / 2.0

        if mode == Mode.COMPAT:
            diversity = 0.75 * sn_stddev * tf_stddev

            first_compat_etj = 0.0
            if first_ei > 0 and first_tf > 0 and first_pj > 0:
                first_compat_etj = (first_ei + first_tf + first_pj) / 3.0

            second_compat_etj = 0.0
            if second_ei > 0 and second_tf > 0 and second_pj > 0:
                second_compat_etj = (second_ei + second_tf + second_pj) / 3.0

            best_compat_etj = (
                first_compat_etj
                if first_compat_etj >= second_compat_etj
                else second_compat_etj
            )

            first_compat_introvert = max(-first_ei, 0.0)
            second_compat_introvert = max(-second_ei, 0.0)
            best_compat_introvert = (
                first_compat_introvert
                if first_compat_introvert >= second_compat_introvert
                else second_compat_introvert
            )

            gender_bonus = _compat_gender_bonus(team)
            return (
                diversity
                + (0.2475 * best_compat_etj)
                + (0.2475 * best_compat_introvert)
                + gender_bonus
            )

        diversity = sn_stddev * tf_stddev

        first_paper_etj = 0.0
        if first_ei > 0 and first_tf > 0 and first_pj > 0:
            first_paper_etj = 0.19 * (first_tf + first_ei + first_pj)

        second_paper_etj = 0.0
        if second_ei > 0 and second_tf > 0 and second_pj > 0:
            second_paper_etj = 0.19 * (second_tf + second_ei + second_pj)

        best_paper_etj = (
            first_paper_etj
            if first_paper_etj >= second_paper_etj
            else second_paper_etj
        )

        first_paper_introvert = max(0.0, 0.19 * (-first_ei))
        second_paper_introvert = max(0.0, 0.19 * (-second_ei))
        best_paper_introvert = (
            first_paper_introvert
            if first_paper_introvert >= second_paper_introvert
            else second_paper_introvert
        )

        gender_bonus = (
            0.1
            if first_member.gender is not None
            and second_member.gender is not None
            and first_member.gender != second_member.gender
            else 0.0
        )
        return diversity + best_paper_etj + best_paper_introvert + gender_bonus

    if mode == Mode.COMPAT and len(team) == 4:
        first_member, second_member, third_member, fourth_member = team
        first_personality = first_member.personality
        second_personality = second_member.personality
        third_personality = third_member.personality
        fourth_personality = fourth_member.personality

        best_compat_etj = 0.0
        best_compat_introvert = 0.0
        for personality in (
            first_personality,
            second_personality,
            third_personality,
            fourth_personality,
        ):
            if (
                personality.ei > 0
                and personality.tf > 0
                and personality.pj > 0
            ):
                compat_etj = (
                    personality.ei + personality.tf + personality.pj
                ) / 3.0
                if compat_etj > best_compat_etj:
                    best_compat_etj = compat_etj

            introvert_component = (
                -personality.ei
                if personality.ei < 0
                else 0.0
            )
            if introvert_component > best_compat_introvert:
                best_compat_introvert = introvert_component

        first_sn = first_personality.sn
        second_sn = second_personality.sn
        third_sn = third_personality.sn
        fourth_sn = fourth_personality.sn
        sn_mean = (
            first_sn + second_sn + third_sn + fourth_sn
        ) / 4.0
        sn_stddev = math.sqrt(
            (
                (first_sn - sn_mean) ** 2
                + (second_sn - sn_mean) ** 2
                + (third_sn - sn_mean) ** 2
                + (fourth_sn - sn_mean) ** 2
            )
            / 4.0
        )

        first_tf = first_personality.tf
        second_tf = second_personality.tf
        third_tf = third_personality.tf
        fourth_tf = fourth_personality.tf
        tf_mean = (
            first_tf + second_tf + third_tf + fourth_tf
        ) / 4.0
        tf_stddev = math.sqrt(
            (
                (first_tf - tf_mean) ** 2
                + (second_tf - tf_mean) ** 2
                + (third_tf - tf_mean) ** 2
                + (fourth_tf - tf_mean) ** 2
            )
            / 4.0
        )

        diversity = 0.75 * sn_stddev * tf_stddev
        gender_bonus = _compat_gender_bonus(team)
        return (
            diversity
            + (0.2475 * best_compat_etj)
            + (0.2475 * best_compat_introvert)
            + gender_bonus
        )

    sn_values: list[float] = []
    tf_values: list[float] = []
    declared_genders: set[str] = set()
    best_compat_etj = 0.0
    best_paper_etj = 0.0
    best_compat_introvert = 0.0
    best_paper_introvert = 0.0

    for member in team:
        personality = member.personality
        sn_values.append(personality.sn)
        tf_values.append(personality.tf)
        if member.gender is not None:
            declared_genders.add(member.gender)
        if personality.ei > 0 and personality.tf > 0 and personality.pj > 0:
            compat_etj = (personality.ei + personality.tf + personality.pj) / 3.0
            if compat_etj > best_compat_etj:
                best_compat_etj = compat_etj
            paper_etj = 0.19 * (
                personality.tf + personality.ei + personality.pj
            )
            if paper_etj > best_paper_etj:
                best_paper_etj = paper_etj
        compat_introvert = max(-personality.ei, 0.0)
        if compat_introvert > best_compat_introvert:
            best_compat_introvert = compat_introvert
        paper_introvert = max(0.0, 0.19 * (-personality.ei))
        if paper_introvert > best_paper_introvert:
            best_paper_introvert = paper_introvert

    sn_stddev = _population_stddev(sn_values)
    tf_stddev = _population_stddev(tf_values)

    if mode == Mode.COMPAT:
        diversity = 0.75 * sn_stddev * tf_stddev
        gender_bonus = _compat_gender_bonus(team)
        return (
            diversity
            + (0.2475 * best_compat_etj)
            + (0.2475 * best_compat_introvert)
            + gender_bonus
        )

    diversity = sn_stddev * tf_stddev
    gender_bonus = 0.1 if len(declared_genders) > 1 else 0.0
    return diversity + best_paper_etj + best_paper_introvert + gender_bonus


def _compat_gender_bonus(team: Sequence[Person]) -> float:
    if len(team) == 2:
        first_gender = team[0].gender
        second_gender = team[1].gender
        if first_gender == second_gender:
            if first_gender is None:
                return _COMPAT_GENDER_BONUS_BALANCED
            return 0.0
        if first_gender is None or second_gender is None:
            return _COMPAT_GENDER_BONUS_ONE_UNKNOWN
        return _COMPAT_GENDER_BONUS_BALANCED

    female_count = sum(member.gender == 'FEMALE' for member in team)
    male_count = sum(member.gender == 'MALE' for member in team)
    missing_count = len(team) - female_count - male_count

    effective_female_count = female_count + (0.5 * missing_count)
    effective_male_count = male_count + (0.5 * missing_count)
    minority_fraction = min(effective_female_count, effective_male_count) / len(team)
    return 0.075 * math.sin(math.pi * minority_fraction)


def skill_similarity(
    task_skill_id: str,
    person_skill_id: str,
    *,
    mode: Mode,
    lookup: dict[tuple[str, str], float],
) -> float:
    if task_skill_id == person_skill_id:
        return 1.0
    if mode == Mode.COMPAT:
        return 0.0
    return lookup.get((person_skill_id, task_skill_id), 0.0)


def coverage_for_person_and_task_skill(
    person: Person,
    task_skill: TaskSkill,
    *,
    mode: Mode,
    similarity_index: dict[tuple[str, str], float],
) -> float:
    best = 0.0
    for skill in person.skills:
        similarity = skill_similarity(
            task_skill.id,
            skill.id,
            mode=mode,
            lookup=similarity_index,
        )
        if similarity <= 0:
            continue
        if mode == Mode.COMPAT:
            candidate = min(skill.level * similarity, 1.0)
        else:
            required_level = max(task_skill.level, EPSILON)
            candidate = min((skill.level * similarity) / required_level, 1.0)
        if candidate > best:
            best = candidate
    return best


def compat_person_skill_value(
    person_skill: PersonSkill,
    task_skill: TaskSkill,
) -> float:
    if task_skill.id != person_skill.id:
        return 0.0
    return person_skill.level


def _compat_member_task_values(
    member: Person,
    task_skills: Sequence[TaskSkill],
    *,
    task_skill_ids: tuple[str, ...] | None = None,
) -> tuple[float, ...]:
    if task_skill_ids is None:
        task_skill_ids = tuple(task_skill.id for task_skill in task_skills)
    cache_key = (id(member), task_skill_ids)
    cached = _COMPAT_MEMBER_TASK_VALUES_CACHE.get(cache_key)
    if cached is not None and cached[0] is member:
        return cached[1]

    first_levels: dict[str, float] = {}
    for skill in member.skills:
        first_levels.setdefault(skill.id, skill.level)
    values = tuple(
        first_levels.get(task_skill_id, 0.0)
        for task_skill_id in task_skill_ids
    )
    _COMPAT_MEMBER_TASK_VALUES_CACHE[cache_key] = (member, values)
    return values


def _compat_member_task_analysis(
    member_task_values: Sequence[Sequence[float]],
) -> tuple[list[int], list[int], list[float], list[float], list[int]]:
    if not member_task_values:
        return [], [], [], [], []

    member_count = len(member_task_values)
    task_count = len(member_task_values[0])
    member_positive_masks = [0] * member_count
    task_capable_counts = [0] * task_count
    best_values = [0.0] * task_count
    second_best_values = [0.0] * task_count
    best_value_counts = [0] * task_count

    for task_index in range(task_count):
        best_value = 0.0
        second_best_value = 0.0
        best_value_count = 0
        capable_count = 0
        for member_index, task_values in enumerate(member_task_values):
            value = task_values[task_index]
            if value > 0:
                capable_count += 1
                member_positive_masks[member_index] |= 1 << task_index
            if value > best_value and not math.isclose(value, best_value):
                second_best_value = best_value
                best_value = value
                best_value_count = 1
            elif math.isclose(value, best_value):
                best_value_count += 1
            elif value > second_best_value and not math.isclose(
                value,
                second_best_value,
            ):
                second_best_value = value
        task_capable_counts[task_index] = capable_count
        best_values[task_index] = best_value
        second_best_values[task_index] = second_best_value
        best_value_counts[task_index] = best_value_count

    return (
        member_positive_masks,
        task_capable_counts,
        best_values,
        second_best_values,
        best_value_counts,
    )


def _compat_member_priority_order(
    task_skill_ids: Sequence[str],
    member_task_values: Sequence[Sequence[float]],
    *,
    task_capable_counts: Sequence[int],
    require_all_members: bool,
) -> list[int]:
    def scarce_first_priority_key(member_index: int) -> tuple[object, ...]:
        positive_tasks = sorted(
            (
                task_capable_counts[task_index],
                -value,
                task_skill_ids[task_index],
                task_index,
            )
            for task_index, value in enumerate(member_task_values[member_index])
            if value > 0
        )
        return (not positive_tasks, positive_tasks, len(positive_tasks))

    if require_all_members:
        return sorted(
            range(len(member_task_values)),
            key=scarce_first_priority_key,
        )

    task_capable_counts_key = tuple(task_capable_counts)
    task_skill_ids_key = tuple(task_skill_ids)

    def rich_first_priority_key(member_index: int) -> tuple[object, ...]:
        task_values = tuple(member_task_values[member_index])
        cache_key = (task_skill_ids_key, task_capable_counts_key, task_values)
        positive_tasks = _COMPAT_RICH_PRIORITY_TASKS_CACHE.get(cache_key)
        if positive_tasks is None:
            positive_tasks = tuple(
                sorted(
                    (
                        (
                            value,
                            task_capable_counts[task_index],
                            task_skill_ids[task_index],
                            task_index,
                        )
                        for task_index, value in enumerate(task_values)
                        if value > 0
                    ),
                    reverse=True,
                )
            )
            _COMPAT_RICH_PRIORITY_TASKS_CACHE[cache_key] = positive_tasks

        return (len(positive_tasks), positive_tasks)

    return sorted(
        range(len(member_task_values)),
        key=rich_first_priority_key,
        reverse=True,
    )


def _compat_sort_member_assignments(
    task_skills: Sequence[TaskSkill],
    assignments: dict[str, list[str]],
) -> dict[str, list[str]]:
    task_skill_order = {
        task_skill.id: index for index, task_skill in enumerate(task_skills)
    }
    for member_id, skill_ids in assignments.items():
        assignments[member_id] = sorted(
            skill_ids,
            key=lambda skill_id: task_skill_order.get(skill_id, len(task_skills)),
        )
    return assignments


def _compat_fill_uncovered_assignments_single_capacity(
    task_skills: Sequence[TaskSkill],
    assignments: dict[str, list[str]],
    *,
    uncovered_mask: int,
) -> dict[str, list[str]]:
    if uncovered_mask == 0:
        return assignments

    uncovered_skill_ids: list[str] = []
    while uncovered_mask:
        task_bit = uncovered_mask & -uncovered_mask
        task_index = task_bit.bit_length() - 1
        uncovered_skill_ids.append(task_skills[task_index].id)
        uncovered_mask ^= task_bit

    next_skill_index = 0
    for member_id, skill_ids in assignments.items():
        if skill_ids or next_skill_index >= len(uncovered_skill_ids):
            continue
        assignments[member_id] = [uncovered_skill_ids[next_skill_index]]
        next_skill_index += 1

    return assignments



def _compat_fill_uncovered_assignments(
    task_skills: Sequence[TaskSkill],
    assignments: dict[str, list[str]],
) -> dict[str, list[str]]:
    if not task_skills or not assignments:
        return assignments
    if all(not skill_ids for skill_ids in assignments.values()):
        return _compat_fallback_assignments(task_skills, tuple(assignments))

    assigned_counts: dict[str, int] = {}
    for member_skill_ids in assignments.values():
        for skill_id in member_skill_ids:
            assigned_counts[skill_id] = assigned_counts.get(skill_id, 0) + 1

    uncovered_skill_ids: list[str] = []
    for task_skill in task_skills:
        assigned_count = assigned_counts.get(task_skill.id, 0)
        if assigned_count > 0:
            assigned_counts[task_skill.id] = assigned_count - 1
            continue
        uncovered_skill_ids.append(task_skill.id)
    if not uncovered_skill_ids:
        return _compat_sort_member_assignments(task_skills, assignments)

    max_skills_per_member = math.ceil(len(task_skills) / len(assignments))
    next_skill_index = 0

    if max_skills_per_member == 1:
        for member_id, skill_ids in assignments.items():
            if skill_ids or next_skill_index >= len(uncovered_skill_ids):
                continue
            assignments[member_id] = [uncovered_skill_ids[next_skill_index]]
            next_skill_index += 1
        return assignments

    for member_id, skill_ids in assignments.items():
        if (
            skill_ids
            or len(skill_ids) >= max_skills_per_member
            or next_skill_index >= len(uncovered_skill_ids)
        ):
            continue
        assignments[member_id] = [uncovered_skill_ids[next_skill_index]]
        next_skill_index += 1

    for _member_id, skill_ids in assignments.items():
        while len(skill_ids) < max_skills_per_member and next_skill_index < len(
            uncovered_skill_ids
        ):
            skill_ids.append(uncovered_skill_ids[next_skill_index])
            next_skill_index += 1

    return _compat_sort_member_assignments(task_skills, assignments)


def _compat_has_perfect_positive_matching(
    member_task_values: Sequence[Sequence[float]],
) -> bool:
    member_count = len(member_task_values)
    if member_count == 0:
        return True

    task_count = len(member_task_values[0])
    if member_count != task_count:
        return False

    matched_members_by_task = [-1] * task_count

    def try_match(member_index: int, seen_tasks: list[bool]) -> bool:
        for task_index, value in enumerate(member_task_values[member_index]):
            if value <= 0 or seen_tasks[task_index]:
                continue
            seen_tasks[task_index] = True
            matched_member = matched_members_by_task[task_index]
            if matched_member == -1 or try_match(matched_member, seen_tasks):
                matched_members_by_task[task_index] = member_index
                return True
        return False

    for member_index in range(member_count):
        if not try_match(member_index, [False] * task_count):
            return False
    return True


def _assign_task_skills_compat(
    task_skills: list[TaskSkill],
    team: Sequence[Person],
    *,
    similarities: list[Similarity] | None,
) -> AssignmentResult:
    _ = similarities
    member_ids = [member.id for member in team]
    task_skill_ids = tuple(task_skill.id for task_skill in task_skills)
    full_mask = (1 << len(task_skills)) - 1
    max_skills_per_member = math.ceil(len(task_skills) / len(team))
    require_all_members = len(task_skills) < len(team)
    assignments = {member_id: [] for member_id in member_ids}
    matched_values: list[float] = []
    covered_mask = 0

    member_task_values = [
        _compat_member_task_values(
            member,
            task_skills,
            task_skill_ids=task_skill_ids,
        )
        for member in team
    ]
    (
        member_positive_masks,
        task_capable_counts,
        best_task_values,
        second_best_task_values,
        best_task_value_counts,
    ) = _compat_member_task_analysis(member_task_values)
    member_priority_order = _compat_member_priority_order(
        task_skill_ids,
        member_task_values,
        task_capable_counts=task_capable_counts,
        require_all_members=require_all_members,
    )

    for member_index in member_priority_order:
        member = team[member_index]
        task_values = member_task_values[member_index]
        positive_mask = member_positive_masks[member_index]
        member_mask = 0
        for _ in range(max_skills_per_member):
            available_mask = full_mask ^ member_mask
            preferred_mask = available_mask & (full_mask ^ covered_mask)
            candidate_mask = (preferred_mask if preferred_mask else available_mask) & (
                positive_mask
            )

            best_task_index: int | None = None
            best_value = 0.0
            best_capable_count = 0
            best_other_member_best = 0.0
            best_skill_id = ''
            while candidate_mask:
                task_bit = candidate_mask & -candidate_mask
                task_index = task_bit.bit_length() - 1
                candidate_mask ^= task_bit
                value = task_values[task_index]
                capable_count = task_capable_counts[task_index]
                other_member_best = best_task_values[task_index]
                if (
                    best_task_value_counts[task_index] == 1
                    and math.isclose(value, best_task_values[task_index])
                ):
                    other_member_best = second_best_task_values[task_index]
                skill_id = task_skill_ids[task_index]

                is_better = best_task_index is None or (
                    value > best_value
                    or (
                        value == best_value
                        and (
                            capable_count > best_capable_count
                            or (
                                capable_count == best_capable_count
                                and (
                                    other_member_best > best_other_member_best
                                    or (
                                        other_member_best
                                        == best_other_member_best
                                        and (
                                            skill_id > best_skill_id
                                            or (
                                                skill_id == best_skill_id
                                                and task_index < best_task_index
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
                if is_better:
                    best_task_index = task_index
                    best_value = value
                    best_capable_count = capable_count
                    best_other_member_best = other_member_best
                    best_skill_id = skill_id

            if best_task_index is None:
                break

            member_mask |= 1 << best_task_index
            covered_mask |= 1 << best_task_index
            assignments[member.id].append(task_skills[best_task_index].id)
            matched_values.append(task_values[best_task_index])

    rescued_values: list[float] = []
    initial_uncovered_mask = full_mask ^ covered_mask
    uncovered_mask = initial_uncovered_mask
    while uncovered_mask:
        task_bit = uncovered_mask & -uncovered_mask
        task_index = task_bit.bit_length() - 1
        rescued_value = best_task_values[task_index]
        if rescued_value <= 0:
            if max_skills_per_member == 1:
                return AssignmentResult(
                    assignments=_compat_fill_uncovered_assignments_single_capacity(
                        task_skills,
                        assignments,
                        uncovered_mask=initial_uncovered_mask,
                    ),
                    skill_score=0.0,
                )
            return AssignmentResult(
                assignments=_compat_fill_uncovered_assignments(
                    task_skills,
                    assignments,
                ),
                skill_score=0.0,
            )
        rescued_values.append(rescued_value)
        uncovered_mask ^= task_bit

    if max_skills_per_member == 1 and not rescued_values:
        if any(member_mask == 0 for member_mask in member_positive_masks):
            return AssignmentResult(assignments=assignments, skill_score=0.0)
        return AssignmentResult(
            assignments=assignments,
            skill_score=geometric_mean(matched_values),
        )

    if max_skills_per_member == 1:
        finalized_assignments = _compat_fill_uncovered_assignments_single_capacity(
            task_skills,
            assignments,
            uncovered_mask=initial_uncovered_mask,
        )
    else:
        finalized_assignments = _compat_fill_uncovered_assignments(
            task_skills,
            assignments,
        )

    if any(member_mask == 0 for member_mask in member_positive_masks):
        return AssignmentResult(
            assignments=finalized_assignments,
            skill_score=0.0,
        )

    if (
        len(task_skills) == len(team)
        and rescued_values
        and not _compat_has_perfect_positive_matching(member_task_values)
    ):
        return AssignmentResult(
            assignments=finalized_assignments,
            skill_score=0.0,
        )

    return AssignmentResult(
        assignments=finalized_assignments,
        skill_score=geometric_mean([*matched_values, *rescued_values]),
    )


def _compat_fallback_assignments(
    task_skills: Sequence[TaskSkill],
    member_ids: Sequence[str],
) -> dict[str, list[str]]:
    assignments = {member_id: [] for member_id in member_ids}
    if not task_skills or not member_ids:
        return assignments

    task_skill_ids = [task_skill.id for task_skill in task_skills]
    max_skills_per_member = math.ceil(len(task_skill_ids) / len(member_ids))
    require_all_members = len(task_skill_ids) >= len(member_ids)
    next_skill_index = 0
    skills_remaining = len(task_skill_ids)

    for member_index, member_id in enumerate(member_ids):
        members_after = len(member_ids) - member_index - 1
        if skills_remaining <= 0:
            break

        min_skills = max(
            1 if require_all_members else 0,
            skills_remaining - (max_skills_per_member * members_after),
        )
        max_skills = min(
            max_skills_per_member,
            skills_remaining - (members_after if require_all_members else 0),
        )
        skills_for_member = min_skills if min_skills <= max_skills else max_skills
        if skills_for_member <= 0:
            continue

        assignments[member_id] = task_skill_ids[
            next_skill_index : next_skill_index + skills_for_member
        ]
        next_skill_index += skills_for_member
        skills_remaining -= skills_for_member

    return assignments


def _member_assignment_score(
    score_matrix: list[list[float]],
    task_skills: Sequence[TaskSkill],
    *,
    member_index: int,
    skill_indices: Sequence[int],
    mode: Mode,
) -> float:
    scored_items = [
        (
            score_matrix[member_index][skill_index],
            task_skills[skill_index].importance,
        )
        for skill_index in skill_indices
    ]
    if mode == Mode.PAPER:
        return weighted_geometric_mean(scored_items)
    return geometric_mean(score for score, _ in scored_items)


def _assign_task_skills_partitioned_greedy(
    task_skills: list[TaskSkill],
    team: Sequence[Person],
    *,
    mode: Mode,
    similarities: list[Similarity] | None,
) -> AssignmentResult:
    similarity_index = similarity_lookup(similarities)
    member_ids = [member.id for member in team]
    score_matrix = [
        [
            coverage_for_person_and_task_skill(
                member,
                task_skill,
                mode=mode,
                similarity_index=similarity_index,
            )
            for task_skill in task_skills
        ]
        for member in team
    ]

    if not task_skills or not team:
        return AssignmentResult(
            assignments={member_id: [] for member_id in member_ids},
            skill_score=0.0,
        )

    max_skills_per_member = math.ceil(len(task_skills) / len(team))
    require_all_members = len(task_skills) >= len(team)
    assignment_indices = [[] for _ in team]
    member_loads = [0] * len(team)
    empty_members = len(team)

    task_order = sorted(
        range(len(task_skills)),
        key=lambda task_index: (
            -task_skills[task_index].importance,
            max(
                score_matrix[member_index][task_index]
                for member_index in range(len(team))
            ),
            task_skills[task_index].id,
            task_index,
        ),
    )

    for task_position, task_index in enumerate(task_order):
        skills_left_after = len(task_skills) - task_position - 1
        best_member_index: int | None = None
        best_priority: tuple[float, int, int, str, int] | None = None

        for member_index, member in enumerate(team):
            if member_loads[member_index] >= max_skills_per_member:
                continue

            was_empty = member_loads[member_index] == 0
            empty_members_after = empty_members - (1 if was_empty else 0)
            if require_all_members and skills_left_after < empty_members_after:
                continue

            candidate_priority = (
                score_matrix[member_index][task_index],
                1 if was_empty else 0,
                -member_loads[member_index],
                member.id,
                -member_index,
            )
            if best_priority is None or candidate_priority > best_priority:
                best_member_index = member_index
                best_priority = candidate_priority

        if best_member_index is None:
            best_member_index = min(
                (
                    member_index
                    for member_index in range(len(team))
                    if member_loads[member_index] < max_skills_per_member
                ),
                key=lambda member_index: (
                    member_loads[member_index],
                    team[member_index].id,
                    member_index,
                ),
            )

        if member_loads[best_member_index] == 0:
            empty_members -= 1
        member_loads[best_member_index] += 1
        assignment_indices[best_member_index].append(task_index)

    assignments = {
        member_id: [task_skills[task_index].id for task_index in sorted(skill_indices)]
        for member_id, skill_indices in zip(member_ids, assignment_indices, strict=True)
    }
    member_scores = [
        _member_assignment_score(
            score_matrix,
            task_skills,
            member_index=member_index,
            skill_indices=skill_indices,
            mode=mode,
        )
        for member_index, skill_indices in enumerate(assignment_indices)
        if skill_indices
    ]
    if len(member_scores) != len(team):
        return AssignmentResult(assignments=assignments, skill_score=0.0)
    return AssignmentResult(
        assignments=assignments,
        skill_score=geometric_mean(member_scores),
    )


def _assign_task_skills_partitioned_exact(
    task_skills: list[TaskSkill],
    team: Sequence[Person],
    *,
    mode: Mode,
    similarities: list[Similarity] | None,
) -> AssignmentResult:
    similarity_index = similarity_lookup(similarities)
    member_ids = [member.id for member in team]
    full_mask = (1 << len(task_skills)) - 1
    max_skills_per_member = math.ceil(len(task_skills) / len(team))
    require_all_members = len(task_skills) >= len(team)

    score_matrix = [
        [
            coverage_for_person_and_task_skill(
                member,
                task_skill,
                mode=mode,
                similarity_index=similarity_index,
            )
            for task_skill in task_skills
        ]
        for member in team
    ]

    subset_signatures: dict[int, tuple[str, ...]] = {}
    subset_scores: list[dict[int, float]] = []
    for mask in range(1, full_mask + 1):
        subset_signatures[mask] = tuple(
            task_skills[skill_index].id
            for skill_index in range(len(task_skills))
            if mask & (1 << skill_index)
        )

    for member_index, _member in enumerate(team):
        scores_for_member: dict[int, float] = {}
        for mask in range(1, full_mask + 1):
            skill_indices = [
                skill_index
                for skill_index in range(len(task_skills))
                if mask & (1 << skill_index)
            ]
            scores_for_member[mask] = _member_assignment_score(
                score_matrix,
                task_skills,
                member_index=member_index,
                skill_indices=skill_indices,
                mode=mode,
            )
        subset_scores.append(scores_for_member)

    def iter_submasks(mask: int) -> Iterable[int]:
        submask = mask
        while submask:
            if submask.bit_count() <= max_skills_per_member:
                yield submask
            submask = (submask - 1) & mask

    dp: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {(0, 0): (0.0, ())}

    for member_index in range(len(team)):
        next_dp: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {}
        for (used_mask, used_members), (log_sum, path) in dp.items():
            remaining_mask = full_mask ^ used_mask
            members_left = len(team) - member_index - 1

            options = [] if require_all_members else [0]
            options.extend(iter_submasks(remaining_mask))

            for chosen_mask in options:
                remaining_after_choice = remaining_mask ^ chosen_mask
                if (
                    require_all_members
                    and members_left > remaining_after_choice.bit_count()
                ):
                    continue
                if (
                    remaining_after_choice.bit_count()
                    > members_left * max_skills_per_member
                ):
                    continue

                next_used_mask = used_mask | chosen_mask
                next_used_members = used_members + (1 if chosen_mask else 0)
                next_path = path + (chosen_mask,)
                member_score = (
                    subset_scores[member_index][chosen_mask] if chosen_mask else 1.0
                )
                next_log_sum = log_sum
                if chosen_mask:
                    next_log_sum += math.log(max(member_score, EPSILON))

                state = (next_used_mask, next_used_members)
                existing = next_dp.get(state)
                if (
                    existing is None
                    or next_log_sum > existing[0]
                    or (
                        math.isclose(next_log_sum, existing[0])
                        and next_path < existing[1]
                    )
                ):
                    next_dp[state] = (next_log_sum, next_path)
        dp = next_dp

    best_path: tuple[int, ...] | None = None
    best_average_log: float | None = None

    for (used_mask, used_members), (log_sum, path) in dp.items():
        if used_mask != full_mask or used_members == 0:
            continue
        average_log = log_sum / used_members
        if (
            best_average_log is None
            or average_log > best_average_log
            or (
                math.isclose(average_log, best_average_log)
                and path < (best_path or path)
            )
        ):
            best_average_log = average_log
            best_path = path

    if best_path is None:
        empty_assignments = {member_id: [] for member_id in member_ids}
        return AssignmentResult(assignments=empty_assignments, skill_score=0.0)

    assignments = {
        member_id: list(subset_signatures[mask]) if mask else []
        for member_id, mask in zip(member_ids, best_path, strict=True)
    }

    member_scores = [
        subset_scores[member_index][mask]
        for member_index, mask in enumerate(best_path)
        if mask
    ]
    if len(member_scores) != len(team):
        return AssignmentResult(assignments=assignments, skill_score=0.0)
    return AssignmentResult(
        assignments=assignments,
        skill_score=geometric_mean(member_scores),
    )


def _assign_task_skills_partitioned(
    task_skills: list[TaskSkill],
    team: Sequence[Person],
    *,
    mode: Mode,
    similarities: list[Similarity] | None,
) -> AssignmentResult:
    if len(task_skills) > MAX_EXACT_PARTITIONED_TASK_SKILLS:
        return _assign_task_skills_partitioned_greedy(
            task_skills,
            team,
            mode=mode,
            similarities=similarities,
        )
    return _assign_task_skills_partitioned_exact(
        task_skills,
        team,
        mode=mode,
        similarities=similarities,
    )


def assign_task_skills(
    task_skills: list[TaskSkill],
    team: Sequence[Person],
    *,
    mode: Mode,
    similarities: list[Similarity] | None,
) -> AssignmentResult:
    if mode == Mode.COMPAT:
        return _assign_task_skills_compat(
            task_skills,
            team,
            similarities=similarities,
        )
    return _assign_task_skills_partitioned(
        task_skills,
        team,
        mode=mode,
        similarities=similarities,
    )


def build_team_quality_request(
    *,
    task: Task,
    team: list[Person],
    all_tasks: list[Task],
    alpha: float | None,
    beta: float | None,
    gamma: float | None,
    delta: float | None,
    similarities: list[Similarity] | None,
    mode: Mode,
    compat_task_preference_default: float | None = None,
) -> TeamQualityRequest:
    task_preferences = preference_lookup(task.preferences)
    teammate_ids = {member.id for member in team}
    members = [
        TeamMember(
            id=member.id,
            gender=member.gender,
            personality=member.personality,
            skills=member.skills,
            preferences=[
                preference
                for preference in member.preferences or []
                if preference.person_id in teammate_ids
            ]
            or None,
            task_preference=task_preferences.get(member.id),
        )
        for member in team
    ]
    return TeamQualityRequest(
        taskSkills=task.skills,
        team=members,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        delta=delta,
        similarities=similarities,
    )


def _calculate_team_quality_components_for_people(
    *,
    task_skills: list[TaskSkill],
    team: Sequence[Person],
    alpha: float | None,
    beta: float | None,
    gamma: float | None,
    delta: float | None,
    similarities: list[Similarity] | None,
    mode: Mode = Mode.COMPAT,
    preset: WeightPreset | None = None,
    normalize_weights: bool = False,
    task_preferences: dict[str, float] | None = None,
    compat_task_preference_default: float | None = None,
    compat_social_preference_default: float | None = None,
    compat_zero_social_without_preferences: bool = False,
    personality_score: float | None = None,
    social_score: float | None = None,
    resolved_weights: Weights | None = None,
) -> _TeamQualityComponents:
    weights = resolved_weights or resolve_weights(
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        delta=delta,
        mode=mode,
        preset=preset,
        normalize=normalize_weights,
    )
    assignment = assign_task_skills(
        task_skills,
        team,
        mode=mode,
        similarities=similarities,
    )
    task_preference_default = (
        0.5
        if compat_task_preference_default is None
        else compat_task_preference_default
    )
    social_preference_default = (
        0.5
        if compat_social_preference_default is None
        else compat_social_preference_default
    )
    task_preference_score = _task_preference_score(
        team,
        task_preferences=task_preferences,
        compat_default=task_preference_default,
    )
    if social_score is None:
        social_score = (
            0.0
            if compat_zero_social_without_preferences
            else team_social_score(
                team,
                compat_default=social_preference_default,
            )
        )
    if personality_score is None:
        personality_score = team_personality_score(team, mode=mode)
    quality = (
        weights.alpha * assignment.skill_score
        + weights.beta * personality_score
        + weights.gamma * task_preference_score
        + weights.delta * social_score
    )
    return _TeamQualityComponents(
        quality=quality,
        skill_score=assignment.skill_score,
        personality_score=personality_score,
        task_preference_score=task_preference_score,
        social_score=social_score,
        assignments=assignment.assignments,
        weights=weights,
    )



def calculate_team_quality_for_people(
    *,
    task_skills: list[TaskSkill],
    team: Sequence[Person],
    alpha: float | None,
    beta: float | None,
    gamma: float | None,
    delta: float | None,
    similarities: list[Similarity] | None,
    mode: Mode = Mode.COMPAT,
    preset: WeightPreset | None = None,
    normalize_weights: bool = False,
    task_preferences: dict[str, float] | None = None,
    compat_task_preference_default: float | None = None,
    compat_social_preference_default: float | None = None,
    compat_zero_social_without_preferences: bool = False,
    personality_score: float | None = None,
    social_score: float | None = None,
    resolved_weights: Weights | None = None,
) -> QualityBreakdown:
    components = _calculate_team_quality_components_for_people(
        task_skills=task_skills,
        team=team,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        delta=delta,
        similarities=similarities,
        mode=mode,
        preset=preset,
        normalize_weights=normalize_weights,
        task_preferences=task_preferences,
        compat_task_preference_default=compat_task_preference_default,
        compat_social_preference_default=compat_social_preference_default,
        compat_zero_social_without_preferences=compat_zero_social_without_preferences,
        personality_score=personality_score,
        social_score=social_score,
        resolved_weights=resolved_weights,
    )
    return QualityBreakdown(
        quality=components.quality,
        skillScore=components.skill_score,
        personalityScore=components.personality_score,
        taskPreferenceScore=components.task_preference_score,
        socialScore=components.social_score,
        weights={
            'alpha': components.weights.alpha,
            'beta': components.weights.beta,
            'gamma': components.weights.gamma,
            'delta': components.weights.delta,
        },
        assignments=components.assignments,
    )



def calculate_team_quality(
    request: TeamQualityRequest,
    *,
    mode: Mode = Mode.COMPAT,
    preset: WeightPreset | None = None,
    normalize_weights: bool = False,
    compat_task_preference_default: float | None = None,
    compat_social_preference_default: float | None = None,
    compat_zero_social_without_preferences: bool = False,
) -> QualityBreakdown:
    task_preferences = {
        member.id: member.task_preference
        for member in request.team
        if member.task_preference is not None
    }
    return calculate_team_quality_for_people(
        task_skills=request.task_skills,
        team=request.team,
        alpha=request.alpha,
        beta=request.beta,
        gamma=request.gamma,
        delta=request.delta,
        similarities=request.similarities,
        mode=mode,
        preset=preset,
        normalize_weights=normalize_weights,
        task_preferences=task_preferences,
        compat_task_preference_default=compat_task_preference_default,
        compat_social_preference_default=compat_social_preference_default,
        compat_zero_social_without_preferences=compat_zero_social_without_preferences,
    )


def assigned_people_from_assignments(
    assignments: dict[str, list[str]],
) -> list[AssignedPerson]:
    return [
        AssignedPerson(id=person_id, skillIds=skill_ids)
        for person_id, skill_ids in assignments.items()
    ]
