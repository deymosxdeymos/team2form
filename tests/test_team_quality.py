import math

import pytest
from pydantic import ValidationError

import team2form.scoring as scoring_module
from team2form import Mode, TeamQualityRequest, WeightPreset, calculate_team_quality
from team2form.models import Person, Personality, PersonSkill, TaskSkill
from team2form.scoring import assign_task_skills


def make_member(
    member_id: str,
    *,
    skill_id: str,
    level: float,
    gender: str | None = None,
    personality: dict[str, float] | None = None,
    task_preference: float | None = None,
    teammate_preference: float = 0.5,
) -> dict[str, object]:
    payload: dict[str, object] = {
        'id': member_id,
        'gender': gender,
        'personality': personality or {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
        'skills': [{'id': skill_id, 'level': level}],
        'preferences': [
            {'personId': member_id, 'preference': 1.0},
            {
                'personId': 'b' if member_id == 'a' else 'a',
                'preference': teammate_preference,
            },
        ],
    }
    if task_preference is not None:
        payload['taskPreference'] = task_preference
    return payload


def test_compat_default_weights_match_research_probe() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [
                {'id': 's1', 'level': 1.0, 'importance': 1},
                {'id': 's2', 'level': 1.0, 'importance': 1},
            ],
            'team': [
                make_member(
                    'a',
                    skill_id='s1',
                    level=1.0,
                    gender='MALE',
                    task_preference=1.0,
                ),
                make_member(
                    'b',
                    skill_id='s2',
                    level=1.0,
                    gender='FEMALE',
                    task_preference=1.0,
                ),
            ],
        }
    )

    result = calculate_team_quality(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
    )

    assert result.skill_score == 1.0
    assert result.personality_score == 0.075
    assert result.task_preference_score == 1.0
    assert result.social_score == 0.75
    assert result.quality == 0.6725


def test_skill_score_uses_geometric_mean_in_compat_mode() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [
                {'id': 's1', 'level': 1.0, 'importance': 1},
                {'id': 's2', 'level': 1.0, 'importance': 1},
            ],
            'team': [
                make_member('a', skill_id='s1', level=0.5),
                make_member('b', skill_id='s2', level=1.0),
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.skill_score == 0.7071067811865476
    assert result.quality == result.skill_score


def test_compat_skill_score_uses_only_the_assigned_duplicate_skill() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [
                {'id': 's1', 'level': 1.0, 'importance': 1},
                {'id': 's2', 'level': 1.0, 'importance': 1},
            ],
            'team': [
                make_member('a', skill_id='s1', level=1.0),
                {
                    **make_member('b', skill_id='s2', level=0.5),
                    'skills': [
                        {'id': 's2', 'level': 0.5},
                        {'id': 's2', 'level': 0.25},
                    ],
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.assignments == {'a': ['s1'], 'b': ['s2']}
    assert result.skill_score == pytest.approx(0.7071067811865476)
    assert result.quality == result.skill_score


def test_compat_skill_score_keeps_first_duplicate_skill_level() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [
                {'id': 's1', 'level': 1.0, 'importance': 1},
                {'id': 's2', 'level': 1.0, 'importance': 1},
            ],
            'team': [
                make_member('a', skill_id='s1', level=1.0),
                {
                    **make_member('b', skill_id='s2', level=0.25),
                    'skills': [
                        {'id': 's2', 'level': 0.25},
                        {'id': 's2', 'level': 0.89},
                    ],
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.assignments == {'a': ['s1'], 'b': ['s2']}
    assert result.skill_score == pytest.approx(0.5)
    assert result.quality == result.skill_score


def test_compat_skill_score_counts_all_matched_members_when_team_exceeds_task_skills(
) -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [
                {'id': 's0', 'level': 1.0, 'importance': 1},
                {'id': 's2', 'level': 1.0, 'importance': 1},
            ],
            'team': [
                make_member('a', skill_id='s0', level=0.3),
                make_member('b', skill_id='s2', level=0.43),
                make_member('c', skill_id='s2', level=0.73),
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.assignments == {'a': ['s0'], 'b': ['s2'], 'c': ['s2']}
    assert result.skill_score == pytest.approx((0.3 * 0.43 * 0.73) ** (1.0 / 3.0))
    assert result.quality == result.skill_score


def test_compat_skill_score_is_zero_when_any_member_has_no_match() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                make_member('a', skill_id='s1', level=0.8),
                make_member('b', skill_id='s1', level=0.6),
                {
                    'id': 'c',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [],
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.assignments == {'a': ['s1'], 'b': ['s1'], 'c': []}
    assert result.skill_score == 0.0
    assert result.quality == 0.0


def test_compat_skill_score_is_zero_when_unmatched_member_gets_rescued_assignment() -> (
    None
):
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [
                {'id': 's1', 'level': 1.0, 'importance': 1},
                {'id': 's2', 'level': 1.0, 'importance': 1},
            ],
            'team': [
                {
                    'id': 'a',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [
                        {'id': 's1', 'level': 1.0},
                        {'id': 's2', 'level': 1.0},
                    ],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [],
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.assignments == {'a': ['s2'], 'b': ['s1']}
    assert result.skill_score == 0.0
    assert result.quality == 0.0


def test_compat_skill_score_is_zero_when_capped_assignment_strands_a_matchable_member(
) -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [
                {'id': 's2', 'level': 1.0, 'importance': 1},
                {'id': 's1', 'level': 1.0, 'importance': 1},
                {'id': 's3', 'level': 1.0, 'importance': 1},
            ],
            'team': [
                {
                    'id': 'a',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's2', 'level': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's2', 'level': 1.0}],
                },
                {
                    'id': 'c',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [
                        {'id': 's1', 'level': 1.0},
                        {'id': 's3', 'level': 1.0},
                    ],
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.skill_score == 0.0
    assert result.quality == 0.0


def test_paper_skill_score_is_zero_when_any_member_is_unassigned() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                make_member('a', skill_id='s1', level=1.0),
                {
                    'id': 'b',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [],
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.PAPER)

    assert result.assignments == {'a': ['s1'], 'b': []}
    assert result.skill_score == 0.0
    assert result.quality == 0.0


def test_paper_skill_similarity_respects_direction() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [
                {'id': 'devops', 'level': 1.0, 'importance': 1},
                {'id': 'frontend', 'level': 1.0, 'importance': 1},
            ],
            'team': [
                make_member('a', skill_id='backend', level=1.0),
                make_member('b', skill_id='frontend', level=1.0),
            ],
            'similarities': [
                {
                    'sourceId': 'devops',
                    'targetId': 'backend',
                    'similarity': 1.0,
                }
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.PAPER)

    assert result.assignments == {'a': ['devops'], 'b': ['frontend']}
    assert result.skill_score == 0.0
    assert result.quality == 0.0


def test_task_preference_score_is_geometric_mean() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                make_member('a', skill_id='s1', level=1.0, task_preference=1.0),
                make_member('b', skill_id='s1', level=1.0, task_preference=0.25),
            ],
            'alpha': 0.0,
            'beta': 0.0,
            'gamma': 1.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.task_preference_score == 0.5
    assert result.quality == 0.5


def test_social_score_matches_self_plus_teammate_average() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                make_member('a', skill_id='s1', level=1.0, teammate_preference=0.5),
                make_member('b', skill_id='s1', level=1.0, teammate_preference=0.5),
            ],
            'alpha': 0.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 1.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.social_score == 0.75
    assert result.quality == 0.75


def test_team_quality_request_rejects_duplicate_member_ids() -> None:
    with pytest.raises(ValueError, match='team member ids must be unique: a'):
        TeamQualityRequest.model_validate(
            {
                'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                'team': [
                    make_member('a', skill_id='s1', level=1.0),
                    make_member('a', skill_id='s1', level=1.0),
                ],
            }
        )


def test_team_quality_request_rejects_unknown_person_preference_people() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TeamQualityRequest.model_validate(
            {
                'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                'team': [
                    {
                        'id': 'a',
                        'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                        'preferences': [
                            {'personId': 'ghost', 'preference': 1.0},
                        ],
                    },
                    {
                        'id': 'b',
                        'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                    },
                ],
            }
        )

    errors = exc_info.value.errors(include_url=False)
    assert len(errors) == 1
    assert errors[0]['type'] == 'unknown_person_preference_person_ids'
    assert errors[0]['loc'] == ()
    assert errors[0]['ctx'] == {'person_id': 'a', 'person_ids': ['ghost']}


def test_team_quality_request_allows_empty_skill_lists() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                make_member('a', skill_id='s1', level=1.0),
                {
                    'id': 'b',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [],
                },
            ],
        }
    )

    assert request.team[1].skills == []


def test_skill_assignment_optimizes_member_skill_distribution() -> None:
    result = assign_task_skills(
        [
            TaskSkill(id='s1', level=1.0, importance=1),
            TaskSkill(id='s2', level=1.0, importance=1),
            TaskSkill(id='s3', level=1.0, importance=1),
        ],
        [
            Person(
                id='a',
                personality=Personality(ei=0, sn=0, tf=0, pj=0),
                skills=[
                    PersonSkill(id='s2', level=1.0),
                    PersonSkill(id='s3', level=0.5),
                ],
            ),
            Person(
                id='b',
                personality=Personality(ei=0, sn=0, tf=0, pj=0),
                skills=[
                    PersonSkill(id='s1', level=1.0),
                    PersonSkill(id='s2', level=1.0),
                    PersonSkill(id='s3', level=0.25),
                ],
            ),
        ],
        mode=Mode.COMPAT,
        similarities=None,
    )

    assert result.assignments == {'a': ['s2', 's3'], 'b': ['s1', 's2']}
    assert result.skill_score == pytest.approx(0.8408964152537145)


def test_compat_assignment_keeps_task_skill_ids_when_quality_is_zero() -> None:
    result = assign_task_skills(
        [
            TaskSkill(id='s1', level=1.0, importance=1),
            TaskSkill(id='s2', level=1.0, importance=1),
        ],
        [
            Person(
                id='a',
                personality=Personality(ei=0, sn=0, tf=0, pj=0),
                skills=[PersonSkill(id='s1', level=1.0)],
            ),
            Person(
                id='b',
                personality=Personality(ei=0, sn=0, tf=0, pj=0),
                skills=[],
            ),
        ],
        mode=Mode.COMPAT,
        similarities=None,
    )

    assert result.assignments == {'a': ['s1'], 'b': ['s2']}
    assert result.skill_score == 0.0


def test_compat_assignment_does_not_rebalance_overlap_heavy_team() -> None:
    result = assign_task_skills(
        [
            TaskSkill(id='s1', level=1.0, importance=1),
            TaskSkill(id='s2', level=1.0, importance=1),
            TaskSkill(id='s3', level=1.0, importance=1),
        ],
        [
            Person(
                id='a',
                personality=Personality(ei=0, sn=0, tf=0, pj=0),
                skills=[
                    PersonSkill(id='s1', level=0.33),
                    PersonSkill(id='s3', level=0.76),
                ],
            ),
            Person(
                id='b',
                personality=Personality(ei=0, sn=0, tf=0, pj=0),
                skills=[PersonSkill(id='s2', level=0.5)],
            ),
            Person(
                id='c',
                personality=Personality(ei=0, sn=0, tf=0, pj=0),
                skills=[PersonSkill(id='s3', level=0.22)],
            ),
        ],
        mode=Mode.COMPAT,
        similarities=None,
    )

    assert result.assignments == {'a': ['s3'], 'b': ['s2'], 'c': ['s1']}


def test_paper_assignment_uses_bounded_fallback_for_large_skill_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team = [
        Person(
            id='a',
            personality=Personality(ei=0, sn=0, tf=0, pj=0),
            skills=[PersonSkill(id='s0', level=1.0)],
        ),
        Person(
            id='b',
            personality=Personality(ei=0, sn=0, tf=0, pj=0),
            skills=[PersonSkill(id='s1', level=1.0)],
        ),
    ]
    task_skills = [
        TaskSkill(id=f's{index}', level=1.0, importance=1) for index in range(13)
    ]
    fallback_result = scoring_module.AssignmentResult(
        assignments={'a': ['s0'], 'b': ['s1']},
        skill_score=0.5,
    )

    monkeypatch.setattr(
        scoring_module,
        '_assign_task_skills_partitioned_exact',
        lambda *args, **kwargs: pytest.fail('exact paper partition should be skipped'),
    )
    monkeypatch.setattr(
        scoring_module,
        '_assign_task_skills_partitioned_greedy',
        lambda *args, **kwargs: fallback_result,
    )

    result = assign_task_skills(
        task_skills,
        team,
        mode=Mode.PAPER,
        similarities=None,
    )

    assert result is fallback_result


def test_paper_exact_assignment_respects_per_member_skill_cap() -> None:
    result = assign_task_skills(
        [
            TaskSkill(id='s1', level=1.0, importance=1),
            TaskSkill(id='s2', level=1.0, importance=1),
            TaskSkill(id='s3', level=1.0, importance=1),
            TaskSkill(id='s4', level=1.0, importance=1),
        ],
        [
            Person(
                id='a',
                personality=Personality(ei=0, sn=0, tf=0, pj=0),
                skills=[
                    PersonSkill(id='s1', level=1.0),
                    PersonSkill(id='s2', level=1.0),
                    PersonSkill(id='s3', level=1.0),
                ],
            ),
            Person(
                id='b',
                personality=Personality(ei=0, sn=0, tf=0, pj=0),
                skills=[PersonSkill(id='s4', level=1.0)],
            ),
        ],
        mode=Mode.PAPER,
        similarities=None,
    )

    assert sorted(
        skill_id for skills in result.assignments.values() for skill_id in skills
    ) == ['s1', 's2', 's3', 's4']
    assert max(len(skills) for skills in result.assignments.values()) == 2
    assert result.skill_score == 0.0


def test_compat_skill_score_keeps_partial_overlap_coverage() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [
                {'id': 's1', 'level': 1.0, 'importance': 1},
                {'id': 's2', 'level': 1.0, 'importance': 1},
            ],
            'team': [
                {
                    **make_member('a', skill_id='s1', level=1.0),
                    'skills': [
                        {'id': 's1', 'level': 1.0},
                        {'id': 's2', 'level': 0.2},
                    ],
                },
                make_member('b', skill_id='s1', level=1.0),
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.assignments == {'a': ['s1'], 'b': ['s2']}
    assert result.skill_score == pytest.approx((1.0 * 0.2) ** 0.5)
    assert result.quality == result.skill_score


def test_compat_skill_score_is_invariant_to_team_member_order() -> None:
    payload = {
        'taskSkills': [
            {'id': 's1', 'level': 1.0, 'importance': 1},
            {'id': 's2', 'level': 1.0, 'importance': 1},
            {'id': 's0', 'level': 1.0, 'importance': 1},
        ],
        'team': [
            {
                **make_member('a', skill_id='s1', level=1.0),
                'skills': [
                    {'id': 's1', 'level': 1.0},
                    {'id': 's2', 'level': 1.0},
                    {'id': 's0', 'level': 1.0},
                ],
            },
            make_member('b', skill_id='s2', level=0.5),
        ],
        'alpha': 1.0,
        'beta': 0.0,
        'gamma': 0.0,
        'delta': 0.0,
    }
    forward = TeamQualityRequest.model_validate(payload)
    reversed_request = TeamQualityRequest.model_validate(
        {**payload, 'team': list(reversed(payload['team']))}
    )

    forward_result = calculate_team_quality(forward, mode=Mode.COMPAT)
    reversed_result = calculate_team_quality(reversed_request, mode=Mode.COMPAT)

    assert (
        forward_result.assignments
        == reversed_result.assignments
        == {
            'a': ['s1', 's2'],
            'b': ['s0'],
        }
    )
    assert forward_result.skill_score == reversed_result.skill_score == 1.0
    assert forward_result.quality == reversed_result.quality == 1.0


def test_compat_skill_score_is_invariant_to_member_ids() -> None:
    payload = {
        'taskSkills': [
            {'id': 's0', 'level': 1.0, 'importance': 1},
            {'id': 's1', 'level': 1.0, 'importance': 1},
            {'id': 's2', 'level': 1.0, 'importance': 1},
        ],
        'team': [
            {
                **make_member('generalist-a', skill_id='s0', level=1.0),
                'id': 'a',
                'skills': [
                    {'id': 's0', 'level': 1.0},
                    {'id': 's1', 'level': 1.0},
                    {'id': 's2', 'level': 1.0},
                ],
                'preferences': [
                    {'personId': 'a', 'preference': 1.0},
                    {'personId': 'z', 'preference': 0.5},
                ],
            },
            make_member('z', skill_id='s2', level=0.5),
        ],
        'alpha': 1.0,
        'beta': 0.0,
        'gamma': 0.0,
        'delta': 0.0,
    }
    renamed_payload = {
        **payload,
        'team': [
            {
                **payload['team'][0],
                'id': 'z',
                'preferences': [
                    {'personId': 'z', 'preference': 1.0},
                    {'personId': 'a', 'preference': 0.5},
                ],
            },
            {
                **payload['team'][1],
                'id': 'a',
                'preferences': [
                    {'personId': 'a', 'preference': 1.0},
                    {'personId': 'z', 'preference': 0.5},
                ],
            },
        ],
    }

    original = calculate_team_quality(
        TeamQualityRequest.model_validate(payload),
        mode=Mode.COMPAT,
    )
    renamed = calculate_team_quality(
        TeamQualityRequest.model_validate(renamed_payload),
        mode=Mode.COMPAT,
    )

    assert original.skill_score == renamed.skill_score == 1.0
    assert original.quality == renamed.quality == 1.0
    assert sorted(sorted(skill_ids) for skill_ids in original.assignments.values()) == [
        ['s0'],
        ['s1', 's2'],
    ]
    assert sorted(sorted(skill_ids) for skill_ids in renamed.assignments.values()) == [
        ['s0'],
        ['s1', 's2'],
    ]


def test_compat_skill_score_is_invariant_to_task_skill_order() -> None:
    payload = {
        'taskSkills': [
            {'id': 's0', 'level': 1.0, 'importance': 1},
            {'id': 's1', 'level': 1.0, 'importance': 1},
            {'id': 's2', 'level': 1.0, 'importance': 1},
        ],
        'team': [
            {
                **make_member('a', skill_id='s0', level=1.0),
                'skills': [
                    {'id': 's0', 'level': 1.0},
                    {'id': 's1', 'level': 1.0},
                    {'id': 's2', 'level': 1.0},
                ],
            },
            make_member('b', skill_id='s2', level=0.5),
        ],
        'alpha': 1.0,
        'beta': 0.0,
        'gamma': 0.0,
        'delta': 0.0,
    }
    reordered_payload = {
        **payload,
        'taskSkills': [
            payload['taskSkills'][1],
            payload['taskSkills'][2],
            payload['taskSkills'][0],
        ],
    }

    original = calculate_team_quality(
        TeamQualityRequest.model_validate(payload),
        mode=Mode.COMPAT,
    )
    reordered = calculate_team_quality(
        TeamQualityRequest.model_validate(reordered_payload),
        mode=Mode.COMPAT,
    )

    assert original.skill_score == reordered.skill_score == 1.0
    assert original.quality == reordered.quality == 1.0
    assert (
        set(original.assignments['a'])
        == set(reordered.assignments['a'])
        == {
            's1',
            's2',
        }
    )
    assert original.assignments['b'] == reordered.assignments['b'] == ['s0']


def test_empty_preference_lists_are_treated_like_missing_preferences() -> None:
    member_a = {
        'id': 'a',
        'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
        'skills': [{'id': 's1', 'level': 1.0}],
    }
    member_b = {
        'id': 'b',
        'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
        'skills': [{'id': 's1', 'level': 1.0}],
    }
    missing_request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [member_a, member_b],
            'alpha': 0.0,
            'beta': 0.3,
            'gamma': 0.2,
            'delta': 0.1,
        }
    )
    empty_request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                {**member_a, 'preferences': []},
                {**member_b, 'preferences': []},
            ],
            'alpha': 0.0,
            'beta': 0.3,
            'gamma': 0.2,
            'delta': 0.1,
        }
    )

    missing_result = calculate_team_quality(
        missing_request,
        mode=Mode.COMPAT,
        compat_zero_social_without_preferences=True,
        compat_social_preference_default=0.0,
    )
    empty_result = calculate_team_quality(
        empty_request,
        mode=Mode.COMPAT,
        compat_zero_social_without_preferences=True,
        compat_social_preference_default=0.0,
    )

    assert empty_result.social_score == missing_result.social_score
    assert empty_result.quality == missing_result.quality


def test_personality_score_matches_reverse_engineered_cases() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [
                {'id': 's1', 'level': 1.0, 'importance': 1},
                {'id': 's2', 'level': 1.0, 'importance': 1},
            ],
            'team': [
                make_member(
                    'a',
                    skill_id='s1',
                    level=1.0,
                    gender='MALE',
                    personality={'ei': 1.0, 'sn': -1.0, 'tf': 1.0, 'pj': 1.0},
                ),
                make_member(
                    'b',
                    skill_id='s2',
                    level=1.0,
                    gender='FEMALE',
                    personality={'ei': -1.0, 'sn': 1.0, 'tf': -1.0, 'pj': -1.0},
                ),
            ],
            'alpha': 0.0,
            'beta': 1.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.personality_score == 1.32
    assert result.quality == 1.32


def test_three_person_mixed_gender_personality_score_matches_live_probe() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                {
                    'id': 'student-3',
                    'gender': 'FEMALE',
                    'personality': {'ei': 0.5, 'sn': -0.4, 'tf': 0.3, 'pj': -0.2},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'student-4',
                    'gender': 'MALE',
                    'personality': {'ei': -0.3, 'sn': 0.2, 'tf': 0.6, 'pj': 0.1},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'student-5',
                    'gender': 'FEMALE',
                    'personality': {'ei': 0.2, 'sn': 0.1, 'tf': 0.4, 'pj': -0.5},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
            ],
            'alpha': 0.0,
            'beta': 1.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.personality_score == pytest.approx(0.16375343838825998)
    assert result.quality == pytest.approx(0.16375343838825998)


def test_partial_missing_gender_gets_reduced_compat_bonus_for_two_person_team() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                make_member('a', skill_id='s1', level=1.0, gender='MALE'),
                make_member('b', skill_id='s1', level=1.0, gender=None),
            ],
            'alpha': 0.0,
            'beta': 1.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.personality_score == pytest.approx(0.075 * math.sqrt(2.0) / 2.0)
    assert result.quality == result.personality_score


def test_all_missing_gender_gets_reduced_compat_bonus_for_two_person_team() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                make_member('a', skill_id='s1', level=1.0, gender=None),
                make_member('b', skill_id='s1', level=1.0, gender=None),
            ],
            'alpha': 0.0,
            'beta': 1.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.personality_score == pytest.approx(0.075)
    assert result.quality == result.personality_score


def test_partial_missing_gender_with_one_declared_gender_matches_live_probe() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                make_member('a', skill_id='s1', level=1.0, gender='FEMALE'),
                make_member('b', skill_id='s1', level=1.0, gender=None),
                make_member('c', skill_id='s1', level=1.0, gender='FEMALE'),
            ],
            'alpha': 0.0,
            'beta': 1.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.personality_score == pytest.approx(0.0375)
    assert result.quality == result.personality_score


def test_partial_missing_gender_with_two_unknowns_matches_live_probe() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                make_member('a', skill_id='s1', level=1.0, gender='MALE'),
                make_member('b', skill_id='s1', level=1.0, gender=None),
                make_member('c', skill_id='s1', level=1.0, gender=None),
            ],
            'alpha': 0.0,
            'beta': 1.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.personality_score == pytest.approx(0.075 * math.sqrt(3.0) / 2.0)
    assert result.quality == result.personality_score


def test_all_missing_gender_gets_full_compat_bonus_for_three_person_team() -> None:
    request = TeamQualityRequest.model_validate(
        {
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                make_member('a', skill_id='s1', level=1.0, gender=None),
                make_member('b', skill_id='s1', level=1.0, gender=None),
                make_member('c', skill_id='s1', level=1.0, gender=None),
            ],
            'alpha': 0.0,
            'beta': 1.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = calculate_team_quality(request, mode=Mode.COMPAT)

    assert result.personality_score == pytest.approx(0.075)
    assert result.quality == result.personality_score
