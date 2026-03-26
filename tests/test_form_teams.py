import math
import random
import sys
from importlib import import_module

import pytest
from pydantic import ValidationError

import team2form.formation as formation_module
from team2form import FormationRequest, Mode, WeightPreset, form_teams
from team2form.formation import (
    DEFAULT_MAX_CANDIDATE_TEAMS,
    ScoredAllocation,
    TeamFormationError,
    allocation_objective,
    candidate_combinations,
    candidate_social_potential,
    exact_allocations,
    greedy_allocations,
    score_team,
    task_hardness,
)
from team2form.models import TaskPreference
from team2form.scoring import build_team_quality_request, calculate_team_quality


def test_candidate_combinations_respects_max_candidate_teams() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': f'p{i}',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for i in range(20)
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 10,
                    'skills': [{'id': 's1', 'level': 1, 'importance': 1}],
                }
            ],
        }
    )

    candidates = candidate_combinations(
        people=request.people,
        team_size=10,
        max_candidate_teams=1000,
        shortlist_padding=6,
        scorer=lambda person: 1.0,
    )

    assert len(candidates) <= 1000


def test_candidate_combinations_uses_full_capped_budget() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': f'p{i}',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for i in range(5)
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 3,
                    'skills': [{'id': 's1', 'level': 1, 'importance': 1}],
                }
            ],
        }
    )
    scores = {person.id: 5 - index for index, person in enumerate(request.people)}

    candidates = candidate_combinations(
        people=request.people,
        team_size=3,
        max_candidate_teams=3,
        shortlist_padding=6,
        scorer=lambda person: scores[person.id],
    )

    assert candidates == [
        tuple(request.people[index] for index in (0, 1, 2)),
        tuple(request.people[index] for index in (0, 1, 3)),
        tuple(request.people[index] for index in (0, 2, 3)),
    ]


def test_candidate_combinations_is_lazy_when_uncapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': f'p{i}',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for i in range(6)
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 3,
                    'skills': [{'id': 's1', 'level': 1, 'importance': 1}],
                }
            ],
        }
    )
    yielded = 0
    original_combinations = formation_module.itertools.combinations

    def tracking_combinations(iterable, team_size):
        nonlocal yielded
        for combination in original_combinations(iterable, team_size):
            yielded += 1
            yield combination

    monkeypatch.setattr(
        formation_module.itertools,
        'combinations',
        tracking_combinations,
    )

    candidates = candidate_combinations(
        people=request.people,
        team_size=3,
        max_candidate_teams=None,
        shortlist_padding=6,
        scorer=lambda person: 1.0,
    )

    assert yielded == 0
    assert tuple(member.id for member in next(iter(candidates))) == ('p0', 'p1', 'p2')
    assert yielded == 1


def test_candidate_combinations_expands_shortlist_to_use_large_budget() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': f'decoy-{index}',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 'decoy', 'level': 1.0}],
                }
                for index in range(14)
            ]
            + [
                {
                    'id': f'specialist-{index}',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': f's{index}', 'level': 1.0}],
                }
                for index in range(5)
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 5,
                    'skills': [
                        {'id': f's{index}', 'level': 1.0, 'importance': 1}
                        for index in range(5)
                    ],
                }
            ],
        }
    )
    specialist_ids = {f'specialist-{index}' for index in range(5)}
    scores = {
        person.id: len(request.people) - index
        for index, person in enumerate(request.people)
    }

    candidates = candidate_combinations(
        people=request.people,
        team_size=5,
        max_candidate_teams=DEFAULT_MAX_CANDIDATE_TEAMS,
        shortlist_padding=6,
        scorer=lambda person: scores[person.id],
        combination_scorer=lambda candidate: float(
            {person.id for person in candidate} == specialist_ids
        ),
    )

    assert len(candidates) == DEFAULT_MAX_CANDIDATE_TEAMS
    assert any(
        {person.id for person in candidate} == specialist_ids
        for candidate in candidates
    )


def test_candidate_combinations_limits_scored_enumeration_for_large_teams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': f'p{index}',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for index in range(50)
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 25,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        }
    )
    yielded = 0
    original_combinations = formation_module.itertools.combinations

    def bounded_combinations(iterable, team_size):
        nonlocal yielded
        for combination in original_combinations(iterable, team_size):
            yielded += 1
            if yielded > 30_000:
                raise AssertionError('candidate enumeration exceeded bounded budget')
            yield combination

    monkeypatch.setattr(
        formation_module.itertools,
        'combinations',
        bounded_combinations,
    )

    candidates = candidate_combinations(
        people=request.people,
        team_size=25,
        max_candidate_teams=DEFAULT_MAX_CANDIDATE_TEAMS,
        shortlist_padding=6,
        scorer=lambda person: 1.0,
        combination_scorer=lambda candidate: 0.0,
    )

    assert len(candidates) == DEFAULT_MAX_CANDIDATE_TEAMS
    assert yielded <= 30_000


def test_candidate_combinations_limits_scored_enumeration_on_budget_overshoot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': f'p{index}',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for index in range(150)
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 139,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        }
    )
    yielded = 0
    original_combinations = formation_module.itertools.combinations

    def bounded_combinations(iterable, team_size):
        nonlocal yielded
        for combination in original_combinations(iterable, team_size):
            yielded += 1
            if yielded > 12_000:
                raise AssertionError('candidate enumeration exceeded bounded budget')
            yield combination

    monkeypatch.setattr(
        formation_module.itertools,
        'combinations',
        bounded_combinations,
    )

    candidates = candidate_combinations(
        people=request.people,
        team_size=139,
        max_candidate_teams=DEFAULT_MAX_CANDIDATE_TEAMS,
        shortlist_padding=6,
        scorer=lambda person: 1.0,
        combination_scorer=lambda candidate: 0.0,
    )

    assert len(candidates) <= DEFAULT_MAX_CANDIDATE_TEAMS
    assert yielded <= 12_000


def test_candidate_combinations_preserve_input_order_for_scored_caps() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': person_id,
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for person_id in ('a', 'b', 'c', 'd')
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        }
    )
    rank = {'a': 1, 'b': 2, 'c': 3, 'd': 4}
    quality_by_order = {
        ('a', 'b'): 3.0,
        ('a', 'c'): 2.0,
    }

    candidates = candidate_combinations(
        people=request.people,
        team_size=2,
        max_candidate_teams=2,
        shortlist_padding=0,
        scorer=lambda person: rank[person.id],
        combination_scorer=lambda candidate: quality_by_order.get(
            tuple(member.id for member in candidate),
            0.0,
        ),
    )

    assert [tuple(member.id for member in candidate) for candidate in candidates] == [
        ('a', 'b'),
        ('a', 'c'),
    ]


def test_build_scored_candidates_reuses_cached_team_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': person_id,
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for person_id in ('a', 'b', 'c', 'd')
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        }
    )
    scored_calls = 0

    def fake_score_team(
        request,
        *,
        task_id,
        people,
        mode,
        preset,
        normalize_weights,
    ) -> ScoredAllocation:
        nonlocal scored_calls
        _ = request
        _ = mode
        _ = preset
        _ = normalize_weights
        scored_calls += 1
        return ScoredAllocation(
            task_id=task_id,
            people=people,
            quality=float(sum(ord(member.id) for member in people)),
            assignments={},
        )

    monkeypatch.setattr(formation_module, 'score_team', fake_score_team)

    task_candidates = formation_module.build_scored_candidates(
        request,
        task_order=list(request.tasks),
        mode=Mode.COMPAT,
        preset=None,
        normalize_weights=False,
        max_candidate_teams=2,
        shortlist_padding=0,
        randomizer=random.Random(0),
    )

    assert len(task_candidates) == 1
    assert len(task_candidates[0]) == 2
    assert scored_calls == 6


def test_greedy_allocations_reuses_cached_team_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': person_id,
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for person_id in ('a', 'b', 'c', 'd')
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        }
    )
    scored_calls = 0

    def fake_score_team(
        request,
        *,
        task_id,
        people,
        mode,
        preset,
        normalize_weights,
    ) -> ScoredAllocation:
        nonlocal scored_calls
        _ = request
        _ = mode
        _ = preset
        _ = normalize_weights
        scored_calls += 1
        return ScoredAllocation(
            task_id=task_id,
            people=people,
            quality=float(sum(ord(member.id) for member in people)),
            assignments={},
        )

    monkeypatch.setattr(formation_module, 'score_team', fake_score_team)

    allocations, unused_people = greedy_allocations(
        request,
        task_order=list(request.tasks),
        mode=Mode.COMPAT,
        preset=None,
        normalize_weights=False,
        max_candidate_teams=2,
        shortlist_padding=0,
        randomizer=random.Random(0),
    )

    assert len(allocations) == 1
    assert len(unused_people) == 2
    assert scored_calls == 6


def test_greedy_allocations_preserves_shuffled_tie_breaking_when_init_random(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': person_id,
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for person_id in ('a', 'b', 'c')
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
            'initRandom': True,
        }
    )

    candidates = [
        tuple(request.people[index] for index in indexes)
        for indexes in ((0, 1), (0, 2), (1, 2))
    ]

    def fixed_shuffle(values: list[object]) -> None:
        values[:] = [values[1], values[0], values[2]]

    randomizer = random.Random(0)
    monkeypatch.setattr(randomizer, 'shuffle', fixed_shuffle)

    def fake_candidate_combinations(**kwargs):
        _ = kwargs
        return list(candidates)

    def fake_score_team(
        request,
        *,
        task_id,
        people,
        mode,
        preset,
        normalize_weights,
    ) -> ScoredAllocation:
        _ = request
        _ = mode
        _ = preset
        _ = normalize_weights
        return ScoredAllocation(
            task_id=task_id,
            people=people,
            quality=1.0,
            assignments={},
        )

    monkeypatch.setattr(
        formation_module,
        'candidate_combinations',
        fake_candidate_combinations,
    )
    monkeypatch.setattr(formation_module, 'score_team', fake_score_team)

    allocations, unused_people = greedy_allocations(
        request,
        task_order=list(request.tasks),
        mode=Mode.COMPAT,
        preset=None,
        normalize_weights=False,
        max_candidate_teams=2,
        shortlist_padding=0,
        randomizer=randomizer,
    )

    assert [member.id for member in allocations[0].people] == ['a', 'c']
    assert [person.id for person in unused_people] == ['b']


def test_form_teams_defaults_to_exact_candidate_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        }
    )
    captured: list[int | None] = []

    def record_candidate_limit(
        *,
        people,
        team_size,
        max_candidate_teams,
        shortlist_padding,
        scorer,
        alternate_scorers=None,
        combination_scorer=None,
    ):
        _ = shortlist_padding
        _ = scorer
        _ = alternate_scorers
        _ = combination_scorer
        captured.append(max_candidate_teams)
        return [tuple(people[:team_size])]

    monkeypatch.setattr(
        'team2form.formation.candidate_combinations',
        record_candidate_limit,
    )

    response = form_teams(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        swap_rounds=0,
    )

    assert captured == [None]
    assert response.teams[0].task_id == 't1'


def test_form_teams_skips_exact_search_when_candidate_cap_prunes_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'c',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        }
    )
    greedy_allocation = ScoredAllocation(
        task_id='t1',
        people=tuple(request.people[:2]),
        quality=1.0,
        assignments={person.id: ['s1'] for person in request.people[:2]},
    )

    monkeypatch.setattr(
        'team2form.formation.exact_allocations',
        lambda *args, **kwargs: pytest.fail('exact candidate search should be skipped'),
    )
    monkeypatch.setattr(
        'team2form.formation.greedy_allocations',
        lambda *args, **kwargs: ([greedy_allocation], []),
    )

    response = form_teams(
        request,
        max_candidate_teams=1,
        swap_rounds=0,
    )

    assert response.teams[0].task_id == 't1'
    assert {member.id for member in response.teams[0].people} == {'a', 'b'}
    assert response.teams[0].quality == pytest.approx(1.0)


def test_form_teams_skips_exact_search_when_global_exact_space_exceeds_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': f'p{i}',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for i in range(18)
            ],
            'tasks': [
                {
                    'id': f't{i}',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
                for i in range(9)
            ],
        }
    )
    greedy_allocations_result = [
        ScoredAllocation(
            task_id=task.id,
            people=tuple(request.people[index * 2 : index * 2 + 2]),
            quality=1.0,
            assignments={
                person.id: ['s1']
                for person in request.people[index * 2 : index * 2 + 2]
            },
        )
        for index, task in enumerate(request.tasks)
    ]

    monkeypatch.setattr(
        'team2form.formation.exact_allocations',
        lambda *args, **kwargs: pytest.fail('exact candidate search should be skipped'),
    )
    monkeypatch.setattr(
        'team2form.formation.greedy_allocations',
        lambda *args, **kwargs: (greedy_allocations_result, []),
    )

    response = form_teams(
        request,
        max_candidate_teams=DEFAULT_MAX_CANDIDATE_TEAMS,
        swap_rounds=0,
    )

    assert [team.task_id for team in response.teams] == [
        task.id for task in request.tasks
    ]
    assert all(team.quality == pytest.approx(1.0) for team in response.teams)


def test_form_teams_keeps_exact_search_when_swap_rounds_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        }
    )
    exact_allocation = ScoredAllocation(
        task_id='t1',
        people=tuple(request.people),
        quality=1.0,
        assignments={person.id: ['s1'] for person in request.people},
    )

    monkeypatch.setattr(
        'team2form.formation.exact_allocations',
        lambda *args, **kwargs: ([exact_allocation], []),
    )
    monkeypatch.setattr(
        'team2form.formation.greedy_allocations',
        lambda *args, **kwargs: pytest.fail('greedy fallback should not run'),
    )
    monkeypatch.setattr(
        'team2form.formation.improve_allocations',
        lambda *args, **kwargs: pytest.fail('swap improvement should not run'),
    )

    response = form_teams(request, swap_rounds=0)

    assert response.teams[0].task_id == 't1'
    assert {member.id for member in response.teams[0].people} == {'a', 'b'}
    assert response.teams[0].quality == pytest.approx(1.0)


def test_form_teams_improves_greedy_fallback_for_capped_search() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'c',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 0.9}],
                },
                {
                    'id': 'd',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 0.1}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                },
                {
                    'id': 't2',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    result = form_teams(request, max_candidate_teams=1, swap_rounds=8)

    teams_by_task = {
        team.task_id: frozenset(member.id for member in team.people)
        for team in result.teams
    }

    assert teams_by_task != {'t1': frozenset({'a', 'b'}), 't2': frozenset({'c', 'd'})}
    assert set(teams_by_task.values()) in (
        {frozenset({'a', 'd'}), frozenset({'b', 'c'})},
        {frozenset({'a', 'c'}), frozenset({'b', 'd'})},
    )


def test_importing_main_module_does_not_execute_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import team2form.cli as cli

    def fail() -> None:
        raise AssertionError('cli main should not run during import')

    monkeypatch.setattr(cli, 'main', fail)
    sys.modules.pop('team2form.__main__', None)

    module = import_module('team2form.__main__')

    assert module.main is fail


def test_exact_allocations_keeps_equal_product_suffix_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': f'p{i}',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for i in range(8)
            ],
            'tasks': [
                {
                    'id': f't{i}',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
                for i in range(4)
            ],
        }
    )
    task_order = list(request.tasks)
    people = request.people
    shared_quality = math.sqrt(0.125)
    suffix_quality = math.sqrt(0.5)

    def mask(*indices: int) -> int:
        value = 0
        for index in indices:
            value |= 1 << index
        return value

    def allocation(
        task_index: int,
        person_indices: tuple[int, ...],
        quality: float,
    ) -> ScoredAllocation:
        return ScoredAllocation(
            task_id=task_order[task_index].id,
            people=tuple(people[index] for index in person_indices),
            quality=quality,
            assignments={people[index].id: ['s1'] for index in person_indices},
        )

    monkeypatch.setattr(
        'team2form.formation.build_scored_candidates',
        lambda *args, **kwargs: [
            [(mask(0, 1), allocation(0, (0, 1), shared_quality))],
            [(mask(2, 3), allocation(1, (2, 3), 1.0))],
            [
                (mask(4, 5), allocation(2, (4, 5), 0.5)),
                (mask(4, 6), allocation(2, (4, 6), shared_quality)),
            ],
            [
                (mask(6, 7), allocation(3, (6, 7), suffix_quality)),
                (mask(5, 7), allocation(3, (5, 7), 1.0)),
            ],
        ],
    )

    result = exact_allocations(
        request,
        task_order=task_order,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        normalize_weights=False,
        max_candidate_teams=DEFAULT_MAX_CANDIDATE_TEAMS,
        shortlist_padding=6,
        randomizer=random.Random(0),
    )

    assert result is not None
    allocations, unused_people = result
    assert [allocation.quality for allocation in allocations] == pytest.approx(
        [shared_quality, 1.0, shared_quality, 1.0]
    )
    assert [person.id for person in unused_people] == []


def test_exact_allocations_treats_near_equal_suffix_products_as_ties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': f'p{index}',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for index in range(6)
            ],
            'tasks': [
                {
                    'id': f't{index}',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
                for index in range(3)
            ],
        }
    )
    task_order = list(request.tasks)
    people = request.people
    suffix_quality = math.sqrt(0.6)

    def mask(*indices: int) -> int:
        value = 0
        for index in indices:
            value |= 1 << index
        return value

    def allocation(
        task_index: int,
        person_indices: tuple[int, ...],
        quality: float,
    ) -> ScoredAllocation:
        return ScoredAllocation(
            task_id=task_order[task_index].id,
            people=tuple(people[index] for index in person_indices),
            quality=quality,
            assignments={people[index].id: ['s1'] for index in person_indices},
        )

    monkeypatch.setattr(
        'team2form.formation.build_scored_candidates',
        lambda *args, **kwargs: [
            [(mask(0, 1), allocation(0, (0, 1), 0.6))],
            [
                (mask(2, 3), allocation(1, (2, 3), 1.0)),
                (mask(2, 4), allocation(1, (2, 4), suffix_quality)),
            ],
            [
                (mask(4, 5), allocation(2, (4, 5), 0.6)),
                (mask(3, 5), allocation(2, (3, 5), suffix_quality)),
            ],
        ],
    )

    result = exact_allocations(
        request,
        task_order=task_order,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        normalize_weights=False,
        max_candidate_teams=DEFAULT_MAX_CANDIDATE_TEAMS,
        shortlist_padding=6,
        randomizer=random.Random(0),
    )

    assert result is not None
    allocations, unused_people = result
    assert [allocation.quality for allocation in allocations] == pytest.approx(
        [0.6, 1.0, 0.6]
    )
    assert [person.id for person in unused_people] == []


def test_exact_allocations_indexes_suffix_candidates_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': f'p{index}',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                }
                for index in range(6)
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                },
                {
                    'id': 't2',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                },
            ],
        }
    )
    task_order = list(request.tasks)
    people = request.people

    def mask(*indices: int) -> int:
        value = 0
        for index in indices:
            value |= 1 << index
        return value

    def allocation(task_index: int, person_indices: tuple[int, ...], quality: float):
        return ScoredAllocation(
            task_id=task_order[task_index].id,
            people=tuple(people[index] for index in person_indices),
            quality=quality,
            assignments={people[index].id: ['s1'] for index in person_indices},
        )

    class SinglePassCandidates:
        def __init__(self, items):
            self._items = items
            self.iterations = 0

        def __len__(self) -> int:
            return len(self._items)

        def __getitem__(self, index):
            return self._items[index]

        def __iter__(self):
            self.iterations += 1
            if self.iterations > 1:
                raise AssertionError('suffix candidates were rescanned')
            return iter(self._items)

    suffix_candidates = SinglePassCandidates(
        [
            (mask(2, 3), allocation(1, (2, 3), 1.0)),
            (mask(4, 5), allocation(1, (4, 5), 0.9)),
            (mask(1, 5), allocation(1, (1, 5), 0.2)),
        ]
    )

    monkeypatch.setattr(
        'team2form.formation.build_scored_candidates',
        lambda *args, **kwargs: [
            [
                (mask(0, 1), allocation(0, (0, 1), 0.8)),
                (mask(0, 2), allocation(0, (0, 2), 0.7)),
            ],
            suffix_candidates,
        ],
    )

    result = exact_allocations(
        request,
        task_order=task_order,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        normalize_weights=False,
        max_candidate_teams=DEFAULT_MAX_CANDIDATE_TEAMS,
        shortlist_padding=6,
        randomizer=random.Random(0),
    )

    assert result is not None
    allocations, unused_people = result
    assert [allocation.task_id for allocation in allocations] == ['t1', 't2']
    assert [allocation.quality for allocation in allocations] == pytest.approx(
        [0.8, 1.0]
    )
    assert {person.id for person in unused_people} == {'p4', 'p5'}


def test_form_teams_preserves_partial_compat_overlap_ranking() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [
                        {'id': 's1', 'level': 1.0},
                        {'id': 's2', 'level': 0.2},
                    ],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'c',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's2', 'level': 0.15}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's1', 'level': 1.0, 'importance': 1},
                        {'id': 's2', 'level': 1.0, 'importance': 1},
                    ],
                }
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    response = form_teams(
        request,
        mode=Mode.COMPAT,
        swap_rounds=0,
    )

    assert {member.id for member in response.teams[0].people} == {'a', 'b'}
    assert response.teams[0].quality == pytest.approx((1.0 * 0.2) ** 0.5)


def test_form_teams_accepts_people_with_empty_skill_lists_in_compat_mode() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's1', 'level': 1.0, 'importance': 1},
                        {'id': 's2', 'level': 1.0, 'importance': 1},
                    ],
                }
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    response = form_teams(request, mode=Mode.COMPAT)

    assert request.people[1].skills == []
    assert response.teams[0].quality == 0.0
    assert {person.id: person.skill_ids for person in response.teams[0].people} == {
        'a': ['s1'],
        'b': ['s2'],
    }


def test_form_teams_zeroes_rescued_unmatched_member_even_if_teammate_covers_all_skills(
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'generalist',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [
                        {'id': 's1', 'level': 1.0},
                        {'id': 's2', 'level': 1.0},
                    ],
                },
                {
                    'id': 'unskilled',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's1', 'level': 1.0, 'importance': 1},
                        {'id': 's2', 'level': 1.0, 'importance': 1},
                    ],
                }
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    response = form_teams(request, mode=Mode.COMPAT, swap_rounds=0)

    assert {person.id for person in response.teams[0].people} == {
        'generalist',
        'unskilled',
    }
    assert response.teams[0].quality == 0.0
    assert {person.id: person.skill_ids for person in response.teams[0].people} == {
        'generalist': ['s2'],
        'unskilled': ['s1'],
    }


def test_form_teams_zeroes_infeasible_capped_compat_assignment() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
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
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 3,
                    'skills': [
                        {'id': 's2', 'level': 1.0, 'importance': 1},
                        {'id': 's1', 'level': 1.0, 'importance': 1},
                        {'id': 's3', 'level': 1.0, 'importance': 1},
                    ],
                }
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    response = form_teams(request, mode=Mode.COMPAT, swap_rounds=0)

    assert {person.id for person in response.teams[0].people} == {'a', 'b', 'c'}
    assert response.teams[0].quality == 0.0


def test_paper_mode_formation_uses_same_missing_preference_defaults_as_scoring() -> (
    None
):
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's2', 'level': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's1', 'level': 1, 'importance': 1},
                        {'id': 's2', 'level': 1, 'importance': 1},
                    ],
                }
            ],
            'alpha': 0.3,
            'beta': 0.3,
            'gamma': 0.2,
            'delta': 0.2,
        }
    )

    response = form_teams(
        request,
        mode=Mode.PAPER,
        preset=WeightPreset.PAPER_BALANCED,
    )
    direct = calculate_team_quality(
        build_team_quality_request(
            task=request.tasks[0],
            team=request.people,
            all_tasks=request.tasks,
            alpha=request.alpha,
            beta=request.beta,
            gamma=request.gamma,
            delta=request.delta,
            similarities=request.similarities,
            mode=Mode.PAPER,
        ),
        mode=Mode.PAPER,
        preset=WeightPreset.PAPER_BALANCED,
    )

    assert response.teams[0].quality == direct.quality


def test_build_team_quality_request_keeps_missing_compat_task_preferences_deferred(
) -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
            'alpha': 0.0,
            'beta': 0.0,
            'gamma': 1.0,
            'delta': 0.0,
        }
    )

    built_request = build_team_quality_request(
        task=request.tasks[0],
        team=request.people,
        all_tasks=request.tasks,
        alpha=request.alpha,
        beta=request.beta,
        gamma=request.gamma,
        delta=request.delta,
        similarities=request.similarities,
        mode=Mode.COMPAT,
    )
    direct = calculate_team_quality(
        built_request,
        mode=Mode.COMPAT,
        compat_task_preference_default=0.0,
    )
    scored = score_team(
        request,
        task_id='t1',
        people=tuple(request.people),
        mode=Mode.COMPAT,
        preset=None,
        normalize_weights=False,
    )

    assert [member.task_preference for member in built_request.team] == [None, None]
    assert direct.task_preference_score == 0.0
    assert direct.quality == scored.quality == 0.0


def test_build_team_quality_request_filters_non_teammate_preferences() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'preferences': [
                        {'personId': 'a', 'preference': 1.0},
                        {'personId': 'b', 'preference': 0.5},
                        {'personId': 'c', 'preference': 0.0},
                    ],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'preferences': [
                        {'personId': 'a', 'preference': 0.5},
                        {'personId': 'b', 'preference': 1.0},
                        {'personId': 'c', 'preference': 0.0},
                    ],
                },
                {
                    'id': 'c',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        }
    )

    built_request = build_team_quality_request(
        task=request.tasks[0],
        team=request.people[:2],
        all_tasks=request.tasks,
        alpha=request.alpha,
        beta=request.beta,
        gamma=request.gamma,
        delta=request.delta,
        similarities=request.similarities,
        mode=Mode.COMPAT,
    )

    assert [
        [preference.person_id for preference in member.preferences or []]
        for member in built_request.team
    ] == [['a', 'b'], ['a', 'b']]


def test_score_team_ignores_unknown_task_preferences_for_compat_defaults() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
            'alpha': 0.0,
            'beta': 0.0,
            'gamma': 1.0,
            'delta': 0.0,
        }
    )
    malformed_request = request.model_copy(
        update={
            'tasks': [
                request.tasks[0].model_copy(
                    update={
                        'preferences': [
                            TaskPreference.model_validate(
                                {'personId': 'ghost', 'preference': 1.0}
                            )
                        ]
                    }
                )
            ]
        }
    )

    scored = score_team(
        malformed_request,
        task_id='t1',
        people=tuple(malformed_request.people),
        mode=Mode.COMPAT,
        preset=None,
        normalize_weights=False,
    )

    assert scored.quality == 0.0


def test_score_team_is_invariant_to_compat_member_order() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's1', 'level': 1.0},
                        {'id': 's2', 'level': 1.0},
                        {'id': 's0', 'level': 1.0},
                    ],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's2', 'level': 0.5}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's1', 'level': 1.0, 'importance': 1},
                        {'id': 's2', 'level': 1.0, 'importance': 1},
                        {'id': 's0', 'level': 1.0, 'importance': 1},
                    ],
                }
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    forward = score_team(
        request,
        task_id='t1',
        people=(request.people[0], request.people[1]),
        mode=Mode.COMPAT,
        preset=None,
        normalize_weights=False,
    )
    reversed_score = score_team(
        request,
        task_id='t1',
        people=(request.people[1], request.people[0]),
        mode=Mode.COMPAT,
        preset=None,
        normalize_weights=False,
    )

    assert (
        forward.assignments
        == reversed_score.assignments
        == {
            'a': ['s1', 's2'],
            'b': ['s0'],
        }
    )
    assert forward.quality == reversed_score.quality == 1.0


def test_compat_candidate_social_potential_ignores_non_teammate_preferences() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'preferences': [{'personId': 'a', 'preference': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'preferences': [{'personId': 'c', 'preference': 1.0}],
                },
                {
                    'id': 'c',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'preferences': [{'personId': 'c', 'preference': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        }
    )

    assert (
        candidate_social_potential(
            request.people[0],
            request.people,
            team_size=2,
            mode=Mode.COMPAT,
        )
        == 0.0
    )


def test_score_team_ignores_non_teammate_preferences_for_compat_social_score() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'preferences': [{'personId': 'a', 'preference': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'preferences': [{'personId': 'c', 'preference': 1.0}],
                },
                {
                    'id': 'c',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'preferences': [{'personId': 'c', 'preference': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
            'alpha': 0.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 1.0,
        }
    )

    scored = score_team(
        request,
        task_id='t1',
        people=tuple(request.people[:2]),
        mode=Mode.COMPAT,
        preset=None,
        normalize_weights=False,
    )

    assert scored.quality == 0.0


def test_form_teams_assigns_exact_skill_pairs_deterministically() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1}],
                    'preferences': [
                        {'personId': 'a', 'preference': 1},
                        {'personId': 'b', 'preference': 1},
                        {'personId': 'c', 'preference': 0},
                        {'personId': 'd', 'preference': 0},
                    ],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's2', 'level': 1}],
                    'preferences': [
                        {'personId': 'a', 'preference': 1},
                        {'personId': 'b', 'preference': 1},
                        {'personId': 'c', 'preference': 0},
                        {'personId': 'd', 'preference': 0},
                    ],
                },
                {
                    'id': 'c',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's3', 'level': 1}],
                    'preferences': [
                        {'personId': 'a', 'preference': 0},
                        {'personId': 'b', 'preference': 0},
                        {'personId': 'c', 'preference': 1},
                        {'personId': 'd', 'preference': 1},
                    ],
                },
                {
                    'id': 'd',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's4', 'level': 1}],
                    'preferences': [
                        {'personId': 'a', 'preference': 0},
                        {'personId': 'b', 'preference': 0},
                        {'personId': 'c', 'preference': 1},
                        {'personId': 'd', 'preference': 1},
                    ],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's1', 'level': 1, 'importance': 1},
                        {'id': 's2', 'level': 1, 'importance': 1},
                    ],
                    'preferences': [
                        {'personId': 'a', 'preference': 1},
                        {'personId': 'b', 'preference': 1},
                        {'personId': 'c', 'preference': 0},
                        {'personId': 'd', 'preference': 0},
                    ],
                },
                {
                    'id': 't2',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's3', 'level': 1, 'importance': 1},
                        {'id': 's4', 'level': 1, 'importance': 1},
                    ],
                    'preferences': [
                        {'personId': 'a', 'preference': 0},
                        {'personId': 'b', 'preference': 0},
                        {'personId': 'c', 'preference': 1},
                        {'personId': 'd', 'preference': 1},
                    ],
                },
            ],
            'alpha': 0.3,
            'beta': 0.3,
            'gamma': 0.2,
            'delta': 0.2,
            'initRandom': False,
        }
    )

    response = form_teams(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
    )

    teams = {
        team.task_id: {member.id for member in team.people} for team in response.teams
    }

    assert teams['t1'] == {'a', 'b'}
    assert teams['t2'] == {'c', 'd'}


def test_form_teams_keeps_specialist_teams_available_when_candidates_are_capped() -> (
    None
):
    generalists = [
        {
            'id': f'g{i}',
            'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
            'skills': [
                {'id': f's{skill_index}', 'level': 0.6} for skill_index in range(1, 6)
            ],
        }
        for i in range(10)
    ]
    specialists = [
        {
            'id': f'specialist-{skill_index}-{copy_index}',
            'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
            'skills': [{'id': f's{skill_index}', 'level': 1.0}],
        }
        for skill_index in range(1, 6)
        for copy_index in range(2)
    ]
    request = FormationRequest.model_validate(
        {
            'people': [*generalists, *specialists],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 5,
                    'skills': [
                        {'id': f's{skill_index}', 'level': 1.0, 'importance': 1}
                        for skill_index in range(1, 6)
                    ],
                },
                {
                    'id': 't2',
                    'teamSize': 5,
                    'skills': [
                        {'id': f's{skill_index}', 'level': 1.0, 'importance': 1}
                        for skill_index in range(1, 6)
                    ],
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    response = form_teams(request)

    assert [team.quality for team in response.teams] == pytest.approx([1.0, 1.0])
    assert {member.id for team in response.teams for member in team.people} == {
        specialist['id'] for specialist in specialists
    }


def test_form_teams_shortlist_respects_weighted_objective_when_capped() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'preferred-1',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 'other-1', 'level': 1.0}],
                },
                {
                    'id': 'preferred-2',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 'other-2', 'level': 1.0}],
                },
                {
                    'id': 'specialist-1',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'specialist-2',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's2', 'level': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's1', 'level': 1.0, 'importance': 1},
                        {'id': 's2', 'level': 1.0, 'importance': 1},
                    ],
                    'preferences': [
                        {'personId': 'preferred-1', 'preference': 1.0},
                        {'personId': 'preferred-2', 'preference': 1.0},
                    ],
                }
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    capped = form_teams(
        request,
        max_candidate_teams=3,
        swap_rounds=0,
    )
    uncapped = form_teams(
        request,
        max_candidate_teams=None,
        swap_rounds=0,
    )

    assert capped.teams[0].quality == pytest.approx(1.0)
    assert capped.teams[0].quality == pytest.approx(uncapped.teams[0].quality)
    assert {member.id for member in capped.teams[0].people} == {
        'specialist-1',
        'specialist-2',
    }


def test_form_teams_keeps_high_importance_specialist_when_candidates_are_capped() -> (
    None
):
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'critical-specialist',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 'critical', 'level': 0.9}],
                },
                *[
                    {
                        'id': f'support-{index}',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 'support', 'level': 1.0}],
                    }
                    for index in range(3)
                ],
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 'critical', 'level': 1.0, 'importance': 100},
                        {'id': 'support', 'level': 1.0, 'importance': 1},
                    ],
                }
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    capped = form_teams(
        request,
        max_candidate_teams=3,
        swap_rounds=0,
    )
    uncapped = form_teams(
        request,
        max_candidate_teams=None,
        swap_rounds=0,
    )

    assert capped.teams[0].quality == pytest.approx(uncapped.teams[0].quality)
    team_member_ids = {member.id for member in capped.teams[0].people}
    assert 'critical-specialist' in team_member_ids
    assert len(team_member_ids & {'support-0', 'support-1', 'support-2'}) == 1


def test_form_teams_uses_scored_cap_without_dropping_lower_ranked_specialist() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'dominant-a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 'dominant', 'level': 1.0}],
                },
                {
                    'id': 'dominant-b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 'dominant', 'level': 1.0}],
                },
                {
                    'id': 'secondary-specialist',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 'secondary', 'level': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 'dominant', 'level': 1.0, 'importance': 2},
                        {'id': 'secondary', 'level': 1.0, 'importance': 1},
                    ],
                }
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    capped = form_teams(
        request,
        max_candidate_teams=1,
        swap_rounds=0,
    )
    uncapped = form_teams(
        request,
        max_candidate_teams=None,
        swap_rounds=0,
    )

    assert capped.teams[0].quality == pytest.approx(1.0)
    assert capped.teams[0].quality == pytest.approx(uncapped.teams[0].quality)
    assert {member.id for member in capped.teams[0].people} == {
        'dominant-a',
        'secondary-specialist',
    }


def test_form_teams_keeps_social_clique_when_default_cap_shortlists_people() -> None:
    clique_ids = [f'clique-{index}' for index in range(5)]
    request = FormationRequest.model_validate(
        {
            'people': [
                *[
                    {
                        'id': f'filler-{index}',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                    }
                    for index in range(25)
                ],
                *[
                    {
                        'id': person_id,
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                        'preferences': [
                            {'personId': teammate_id, 'preference': 1.0}
                            for teammate_id in clique_ids
                            if teammate_id != person_id
                        ],
                    }
                    for person_id in clique_ids
                ],
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 5,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
            'alpha': 0.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 1.0,
        }
    )

    capped = form_teams(request, swap_rounds=0)
    uncapped = form_teams(
        request,
        max_candidate_teams=None,
        swap_rounds=0,
    )

    assert capped.teams[0].quality == pytest.approx(1.0)
    assert capped.teams[0].quality == pytest.approx(uncapped.teams[0].quality)
    assert {member.id for member in capped.teams[0].people} == set(clique_ids)


def test_form_teams_ranks_capped_combinations_by_team_quality() -> None:
    clique_ids = ['clique-a', 'clique-b', 'clique-c']
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'filler-a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'filler-b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                *[
                    {
                        'id': person_id,
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                        'preferences': [
                            {'personId': teammate_id, 'preference': 1.0}
                            for teammate_id in clique_ids
                            if teammate_id != person_id
                        ],
                    }
                    for person_id in clique_ids
                ],
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 3,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
            'alpha': 0.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 1.0,
        }
    )

    capped = form_teams(
        request,
        max_candidate_teams=9,
        swap_rounds=0,
    )
    uncapped = form_teams(
        request,
        max_candidate_teams=None,
        swap_rounds=0,
    )

    assert capped.teams[0].quality == pytest.approx(1.0)
    assert capped.teams[0].quality == pytest.approx(uncapped.teams[0].quality)
    assert {member.id for member in capped.teams[0].people} == set(clique_ids)


def test_formation_request_rejects_duplicate_task_ids() -> None:
    with pytest.raises(ValueError, match='task ids must be unique: t1'):
        FormationRequest.model_validate(
            {
                'people': [
                    {
                        'id': 'a',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                    },
                    {
                        'id': 'b',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                    },
                ],
                'tasks': [
                    {
                        'id': 't1',
                        'teamSize': 2,
                        'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                    },
                    {
                        'id': 't1',
                        'teamSize': 2,
                        'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                    },
                ],
            }
        )


def test_form_teams_rejects_non_positive_candidate_caps() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        }
    )

    with pytest.raises(
        TeamFormationError,
        match='max_candidate_teams must be a positive integer',
    ):
        form_teams(request, max_candidate_teams=0)

    with pytest.raises(
        TeamFormationError,
        match='max_candidate_teams must be a positive integer',
    ):
        form_teams(request, max_candidate_teams=-1)


def test_formation_request_rejects_duplicate_person_ids() -> None:
    with pytest.raises(ValueError, match='people ids must be unique: a'):
        FormationRequest.model_validate(
            {
                'people': [
                    {
                        'id': 'a',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                    },
                    {
                        'id': 'a',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's2', 'level': 1.0}],
                    },
                ],
                'tasks': [
                    {
                        'id': 't1',
                        'teamSize': 2,
                        'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                    }
                ],
            }
        )


def test_formation_request_rejects_unknown_task_preference_people() -> None:
    with pytest.raises(ValidationError) as exc_info:
        FormationRequest.model_validate(
            {
                'people': [
                    {
                        'id': 'a',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                    },
                    {
                        'id': 'b',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                    },
                ],
                'tasks': [
                    {
                        'id': 't1',
                        'teamSize': 2,
                        'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                        'preferences': [
                            {'personId': 'ghost', 'preference': 1.0},
                        ],
                    }
                ],
            }
        )

    errors = exc_info.value.errors(include_url=False)
    assert len(errors) == 1
    assert errors[0]['type'] == 'unknown_task_preference_person_ids'
    assert errors[0]['loc'] == ()
    assert errors[0]['ctx'] == {'task_id': 't1', 'person_ids': ['ghost']}


def test_formation_request_rejects_unknown_person_preference_people() -> None:
    with pytest.raises(ValidationError) as exc_info:
        FormationRequest.model_validate(
            {
                'people': [
                    {
                        'id': 'a',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                        'preferences': [
                            {'personId': 'ghost', 'preference': 1.0},
                        ],
                    },
                    {
                        'id': 'b',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                    },
                ],
                'tasks': [
                    {
                        'id': 't1',
                        'teamSize': 2,
                        'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                    }
                ],
            }
        )

    errors = exc_info.value.errors(include_url=False)
    assert len(errors) == 1
    assert errors[0]['type'] == 'unknown_person_preference_person_ids'
    assert errors[0]['loc'] == ()
    assert errors[0]['ctx'] == {'person_id': 'a', 'person_ids': ['ghost']}


def test_formation_request_rejects_duplicate_person_preference_ids() -> None:
    with pytest.raises(ValidationError) as exc_info:
        FormationRequest.model_validate(
            {
                'people': [
                    {
                        'id': 'a',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                        'preferences': [
                            {'personId': 'b', 'preference': 1.0},
                            {'personId': 'b', 'preference': 0.0},
                        ],
                    },
                    {
                        'id': 'b',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                    },
                ],
                'tasks': [
                    {
                        'id': 't1',
                        'teamSize': 2,
                        'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                    }
                ],
            }
        )

    errors = exc_info.value.errors(include_url=False)
    assert len(errors) == 1
    assert errors[0]['type'] == 'duplicate_person_preference_ids'
    assert errors[0]['loc'] == ('people', 0)
    assert errors[0]['ctx'] == {'person_ids': ['b']}


def test_formation_request_rejects_duplicate_task_preference_ids() -> None:
    with pytest.raises(ValidationError) as exc_info:
        FormationRequest.model_validate(
            {
                'people': [
                    {
                        'id': 'a',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                    },
                    {
                        'id': 'b',
                        'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                        'skills': [{'id': 's1', 'level': 1.0}],
                    },
                ],
                'tasks': [
                    {
                        'id': 't1',
                        'teamSize': 2,
                        'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                        'preferences': [
                            {'personId': 'a', 'preference': 1.0},
                            {'personId': 'a', 'preference': 0.0},
                        ],
                    }
                ],
            }
        )

    errors = exc_info.value.errors(include_url=False)
    assert len(errors) == 1
    assert errors[0]['type'] == 'duplicate_task_preference_ids'
    assert errors[0]['loc'] == ('tasks', 0)
    assert errors[0]['ctx'] == {'person_ids': ['a']}


def test_form_teams_reconsiders_unused_people_during_improvement() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's1', 'level': 0.5},
                        {'id': 's4', 'level': 0.5},
                    ],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's1', 'level': 0.75},
                        {'id': 's2', 'level': 0.5},
                        {'id': 's3', 'level': 0.75},
                        {'id': 's4', 'level': 0.75},
                    ],
                },
                {
                    'id': 'c',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's1', 'level': 1.0},
                        {'id': 's2', 'level': 0.25},
                        {'id': 's3', 'level': 1.0},
                        {'id': 's4', 'level': 0.25},
                    ],
                },
                {
                    'id': 'd',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's1', 'level': 0.25},
                        {'id': 's2', 'level': 0.25},
                        {'id': 's4', 'level': 0.25},
                    ],
                },
                {
                    'id': 'e',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's1', 'level': 0.5},
                        {'id': 's2', 'level': 0.25},
                        {'id': 's3', 'level': 0.25},
                        {'id': 's4', 'level': 1.0},
                    ],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's1', 'level': 1, 'importance': 1},
                        {'id': 's2', 'level': 1, 'importance': 1},
                    ],
                },
                {
                    'id': 't2',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's3', 'level': 1, 'importance': 1},
                        {'id': 's4', 'level': 1, 'importance': 1},
                    ],
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    task_order = list(request.tasks)
    task_order.sort(
        key=lambda task: (-task_hardness(task.id, request, mode=Mode.COMPAT), task.id)
    )
    greedy_allocs, _ = greedy_allocations(
        request,
        task_order=task_order,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        normalize_weights=False,
        max_candidate_teams=DEFAULT_MAX_CANDIDATE_TEAMS,
        shortlist_padding=6,
        randomizer=random.Random(0),
    )
    improved = form_teams(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        swap_rounds=8,
    )

    def response_objective(response):
        allocations = []
        for team in response.teams:
            task = next(task for task in request.tasks if task.id == team.task_id)
            members = tuple(
                next(person for person in request.people if person.id == assigned.id)
                for assigned in team.people
            )
            allocations.append(
                score_team(
                    request,
                    task_id=task.id,
                    people=members,
                    mode=Mode.COMPAT,
                    preset=WeightPreset.LIVE_COMPAT,
                    normalize_weights=False,
                )
            )
        return allocation_objective(allocations)

    assert response_objective(improved) > allocation_objective(greedy_allocs)


def test_form_teams_prefers_balanced_global_solution() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's1', 'level': 0.75},
                        {'id': 's2', 'level': 0.25},
                        {'id': 's3', 'level': 0.75},
                        {'id': 's4', 'level': 0.75},
                    ],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's1', 'level': 0.25},
                        {'id': 's2', 'level': 0.25},
                        {'id': 's3', 'level': 0.25},
                    ],
                },
                {
                    'id': 'c',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's2', 'level': 0.25},
                        {'id': 's3', 'level': 1.0},
                        {'id': 's4', 'level': 1.0},
                    ],
                },
                {
                    'id': 'd',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's2', 'level': 0.75},
                        {'id': 's4', 'level': 0.5},
                    ],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's1', 'level': 1, 'importance': 1},
                        {'id': 's2', 'level': 1, 'importance': 1},
                    ],
                },
                {
                    'id': 't2',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's3', 'level': 1, 'importance': 1},
                        {'id': 's4', 'level': 1, 'importance': 1},
                    ],
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    response = form_teams(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
    )

    teams = {
        team.task_id: {member.id for member in team.people} for team in response.teams
    }

    assert teams['t1'] == {'a', 'd'}
    assert teams['t2'] == {'b', 'c'}


def test_form_teams_uses_exact_search_when_cap_does_not_prune() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's1', 'level': 0.75},
                        {'id': 's2', 'level': 0.25},
                        {'id': 's3', 'level': 0.75},
                        {'id': 's4', 'level': 0.75},
                    ],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's1', 'level': 0.25},
                        {'id': 's2', 'level': 0.25},
                        {'id': 's3', 'level': 0.25},
                    ],
                },
                {
                    'id': 'c',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's2', 'level': 0.25},
                        {'id': 's3', 'level': 1.0},
                        {'id': 's4', 'level': 1.0},
                    ],
                },
                {
                    'id': 'd',
                    'personality': {'ei': 0, 'sn': 0, 'tf': 0, 'pj': 0},
                    'skills': [
                        {'id': 's2', 'level': 0.75},
                        {'id': 's4', 'level': 0.5},
                    ],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's1', 'level': 1, 'importance': 1},
                        {'id': 's2', 'level': 1, 'importance': 1},
                    ],
                },
                {
                    'id': 't2',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's3', 'level': 1, 'importance': 1},
                        {'id': 's4', 'level': 1, 'importance': 1},
                    ],
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        }
    )

    capped = form_teams(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        max_candidate_teams=DEFAULT_MAX_CANDIDATE_TEAMS,
        swap_rounds=0,
    )
    uncapped = form_teams(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        max_candidate_teams=None,
        swap_rounds=0,
    )

    capped_teams = {
        team.task_id: {member.id for member in team.people} for team in capped.teams
    }
    uncapped_teams = {
        team.task_id: {member.id for member in team.people} for team in uncapped.teams
    }

    assert capped_teams == uncapped_teams
    assert capped_teams['t1'] == {'a', 'd'}
    assert capped_teams['t2'] == {'b', 'c'}


def test_form_teams_matches_live_symmetric_task_mapping() -> None:
    request = FormationRequest.model_validate(
        {
            'alpha': 0.4,
            'beta': 0.3,
            'gamma': 0.2,
            'delta': 0.1,
            'initRandom': False,
            'people': [
                {
                    'id': 'student-1',
                    'gender': 'FEMALE',
                    'personality': {'ei': 0.3, 'sn': -0.2, 'tf': 0.5, 'pj': 0.7},
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.8},
                        {'id': 'skill-backend', 'level': 0.4},
                    ],
                },
                {
                    'id': 'student-2',
                    'gender': 'MALE',
                    'personality': {'ei': -0.1, 'sn': 0.6, 'tf': -0.2, 'pj': 0.4},
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.6},
                        {'id': 'skill-backend', 'level': 0.5},
                    ],
                },
                {
                    'id': 'student-3',
                    'gender': 'FEMALE',
                    'personality': {'ei': 0.5, 'sn': -0.4, 'tf': 0.3, 'pj': -0.2},
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.4},
                        {'id': 'skill-backend', 'level': 0.7},
                    ],
                },
                {
                    'id': 'student-4',
                    'gender': 'MALE',
                    'personality': {'ei': -0.3, 'sn': 0.2, 'tf': 0.6, 'pj': 0.1},
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.5},
                        {'id': 'skill-backend', 'level': 0.3},
                    ],
                },
            ],
            'tasks': [
                {
                    'id': 'task-frontend',
                    'teamSize': 2,
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.7, 'importance': 1},
                        {'id': 'skill-backend', 'level': 0.4, 'importance': 1},
                    ],
                },
                {
                    'id': 'task-backend',
                    'teamSize': 2,
                    'skills': [
                        {'id': 'skill-backend', 'level': 0.7, 'importance': 1},
                        {'id': 'skill-frontend', 'level': 0.4, 'importance': 1},
                    ],
                },
            ],
            'similarities': [
                {
                    'sourceId': 'skill-frontend',
                    'targetId': 'skill-backend',
                    'similarity': 0.5,
                },
                {
                    'sourceId': 'skill-backend',
                    'targetId': 'skill-frontend',
                    'similarity': 0.5,
                },
                {
                    'sourceId': 'skill-devops',
                    'targetId': 'skill-backend',
                    'similarity': 0.6,
                },
            ],
        }
    )

    response = form_teams(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
    )

    teams = {
        team.task_id: {member.id for member in team.people} for team in response.teams
    }

    assert teams['task-frontend'] == {'student-3', 'student-4'}
    assert teams['task-backend'] == {'student-1', 'student-2'}


def test_form_teams_prefers_global_project_mapping_over_best_first_task() -> None:
    request = FormationRequest.model_validate(
        {
            'alpha': 0.4,
            'beta': 0.3,
            'gamma': 0.2,
            'delta': 0.1,
            'initRandom': False,
            'people': [
                {
                    'id': 'student-1',
                    'gender': 'FEMALE',
                    'personality': {'ei': 0.3, 'sn': -0.2, 'tf': 0.5, 'pj': 0.7},
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.8},
                        {'id': 'skill-backend', 'level': 0.4},
                    ],
                },
                {
                    'id': 'student-2',
                    'gender': 'MALE',
                    'personality': {'ei': -0.1, 'sn': 0.6, 'tf': -0.2, 'pj': 0.4},
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.6},
                        {'id': 'skill-backend', 'level': 0.5},
                    ],
                },
                {
                    'id': 'student-3',
                    'gender': 'FEMALE',
                    'personality': {'ei': 0.5, 'sn': -0.4, 'tf': 0.3, 'pj': -0.2},
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.4},
                        {'id': 'skill-backend', 'level': 0.7},
                    ],
                },
                {
                    'id': 'student-4',
                    'gender': 'MALE',
                    'personality': {'ei': -0.3, 'sn': 0.2, 'tf': 0.6, 'pj': 0.1},
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.5},
                        {'id': 'skill-backend', 'level': 0.3},
                    ],
                },
                {
                    'id': 'student-5',
                    'gender': 'FEMALE',
                    'personality': {'ei': 0.2, 'sn': 0.1, 'tf': 0.4, 'pj': -0.5},
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.55},
                        {'id': 'skill-devops', 'level': 0.6},
                    ],
                },
            ],
            'tasks': [
                {
                    'id': 'task-complex',
                    'teamSize': 3,
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.6, 'importance': 1},
                        {'id': 'skill-backend', 'level': 0.6, 'importance': 1},
                        {'id': 'skill-devops', 'level': 0.4, 'importance': 1},
                    ],
                },
                {
                    'id': 'task-support',
                    'teamSize': 2,
                    'skills': [
                        {'id': 'skill-frontend', 'level': 0.5, 'importance': 1},
                        {'id': 'skill-backend', 'level': 0.3, 'importance': 1},
                    ],
                },
            ],
            'similarities': [
                {
                    'sourceId': 'skill-frontend',
                    'targetId': 'skill-backend',
                    'similarity': 0.5,
                },
                {
                    'sourceId': 'skill-backend',
                    'targetId': 'skill-frontend',
                    'similarity': 0.5,
                },
                {
                    'sourceId': 'skill-devops',
                    'targetId': 'skill-backend',
                    'similarity': 0.6,
                },
            ],
        }
    )

    task_order = list(request.tasks)
    task_order.sort(
        key=lambda task: (-task_hardness(task.id, request, mode=Mode.COMPAT), task.id)
    )
    greedy_allocs, _ = greedy_allocations(
        request,
        task_order=task_order,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        normalize_weights=False,
        max_candidate_teams=DEFAULT_MAX_CANDIDATE_TEAMS,
        shortlist_padding=6,
        randomizer=random.Random(0),
    )
    response = form_teams(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        swap_rounds=0,
    )

    greedy_teams = {
        allocation.task_id: {member.id for member in allocation.people}
        for allocation in greedy_allocs
    }
    teams = {
        team.task_id: {member.id for member in team.people} for team in response.teams
    }

    assert greedy_teams != teams
    assert teams['task-complex'] == {'student-3', 'student-4', 'student-5'}
    assert teams['task-support'] == {'student-1', 'student-2'}
