from __future__ import annotations

import json
import math
import subprocess
import tempfile
from pathlib import Path

from team2form import (
    Mode,
    TeamQualityRequest,
    WeightPreset,
    calculate_team_quality,
    form_teams,
)
from team2form.models import FormationRequest

ROOT = Path(__file__).resolve().parents[1]
GLEAM_CLI = ROOT / 'gleam' / 'scripts' / 'cli.mjs'


def run_gleam(
    command: str,
    payload: dict,
    *,
    mode: str,
    preset: str | None,
    max_candidate_teams: int | None = None,
) -> dict:
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
        json.dump(payload, handle)
        path = Path(handle.name)

    try:
        args = ['node', str(GLEAM_CLI), command, str(path), '--mode', mode]
        if preset is not None:
            args.extend(['--preset', preset])
        if max_candidate_teams is not None:
            args.extend(['--max-candidate-teams', str(max_candidate_teams)])
        output = subprocess.check_output(args, cwd=ROOT, text=True)
        return json.loads(output)
    finally:
        path.unlink(missing_ok=True)


def assert_close(left: float, right: float, *, tolerance: float = 1e-9) -> None:
    if not math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance):
        raise AssertionError(f'Expected {left} ~= {right}')


def compare_quality_examples() -> None:
    payload = json.loads((ROOT / 'examples' / 'team-quality.json').read_text())

    request = TeamQualityRequest.model_validate(payload)
    python_result = calculate_team_quality(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
    )
    gleam_result = run_gleam(
        'quality',
        payload,
        mode='compat',
        preset='live_compat',
    )

    assert_close(python_result.quality, gleam_result['quality'])
    assert_close(python_result.skill_score, gleam_result['skillScore'])
    assert python_result.assignments == gleam_result['assignments']


def compare_formation_example() -> None:
    payload = json.loads((ROOT / 'examples' / 'team-formation.json').read_text())
    compare_formation_payload('example formation', payload)


def make_form_payload(people_count: int, tasks_count: int) -> dict:
    if people_count % tasks_count != 0:
        raise ValueError('people_count must be divisible by tasks_count')

    team_size = people_count // tasks_count
    people = []
    tasks = []

    for i in range(people_count):
        people.append(
            {
                'id': f'p{i}',
                'personality': {
                    'ei': 0.1 if i % 2 == 0 else -0.1,
                    'sn': 0.0,
                    'tf': 0.0,
                    'pj': 0.0,
                },
                'skills': [
                    {'id': f's{i}', 'level': 1.0},
                    {'id': f's{(i + 1) % people_count}', 'level': 0.3},
                ],
                'preferences': [
                    {'personId': f'p{i}', 'preference': 1.0},
                ],
            }
        )

    for task_index in range(tasks_count):
        start = task_index * team_size
        task_people = list(range(start, start + team_size))
        tasks.append(
            {
                'id': f't{task_index}',
                'teamSize': team_size,
                'skills': [
                    {'id': f's{idx}', 'level': 1.0, 'importance': 1}
                    for idx in task_people
                ],
                'preferences': [
                    {'personId': f'p{idx}', 'preference': 1.0}
                    for idx in task_people
                ],
            }
        )

    return {
        'people': people,
        'tasks': tasks,
        'alpha': 0.3,
        'beta': 0.3,
        'gamma': 0.2,
        'delta': 0.2,
        'initRandom': False,
    }


def compare_formation_payload(
    label: str,
    payload: dict,
    *,
    max_candidate_teams: int | None = None,
) -> None:
    request = FormationRequest.model_validate(payload)
    python_result = form_teams(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        max_candidate_teams=max_candidate_teams,
    )
    gleam_result = run_gleam(
        'form',
        payload,
        mode='compat',
        preset='live_compat',
        max_candidate_teams=max_candidate_teams,
    )

    python_by_task = {team.task_id: team for team in python_result.teams}
    gleam_by_task = {team['taskId']: team for team in gleam_result['teams']}

    if python_by_task.keys() != gleam_by_task.keys():
        raise AssertionError(f'{label}: task ids differ between Python and Gleam outputs')

    for task_id, python_team in python_by_task.items():
        gleam_team = gleam_by_task[task_id]
        assert_close(python_team.quality, gleam_team['quality'])
        python_people = {person.id: sorted(person.skill_ids) for person in python_team.people}
        gleam_people = {
            person['id']: sorted(person['skillIds'])
            for person in gleam_team['people']
        }
        if python_people != gleam_people:
            raise AssertionError(
                f'{label}: people assignments differ for task {task_id}: '
                f'{python_people} != {gleam_people}'
            )


def compare_formation_scenarios() -> None:
    scenarios = [
        ('10 people / 2 tasks', make_form_payload(10, 2), None),
        ('9 people / 3 tasks', make_form_payload(9, 3), None),
        ('larger capped workload', make_form_payload(12, 3), 10),
    ]
    for label, payload, max_candidate_teams in scenarios:
        compare_formation_payload(
            label,
            payload,
            max_candidate_teams=max_candidate_teams,
        )


def compare_overfull_compat_case() -> None:
    payload = {
        'taskSkills': [
            {'id': 's0', 'level': 1.0, 'importance': 1},
            {'id': 's2', 'level': 1.0, 'importance': 1},
        ],
        'team': [
            {
                'id': 'a',
                'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                'skills': [{'id': 's0', 'level': 0.3}],
                'preferences': [{'personId': 'a', 'preference': 1.0}],
            },
            {
                'id': 'b',
                'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                'skills': [{'id': 's2', 'level': 0.43}],
                'preferences': [{'personId': 'b', 'preference': 1.0}],
            },
            {
                'id': 'c',
                'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                'skills': [{'id': 's2', 'level': 0.73}],
                'preferences': [{'personId': 'c', 'preference': 1.0}],
            },
        ],
        'alpha': 1.0,
        'beta': 0.0,
        'gamma': 0.0,
        'delta': 0.0,
    }

    request = TeamQualityRequest.model_validate(payload)
    python_result = calculate_team_quality(request, mode=Mode.COMPAT)
    gleam_result = run_gleam('quality', payload, mode='compat', preset=None)

    assert python_result.assignments == gleam_result['assignments']
    assert_close(python_result.skill_score, gleam_result['skillScore'])


def main() -> None:
    compare_quality_examples()
    compare_formation_example()
    compare_formation_scenarios()
    compare_overfull_compat_case()
    print('Gleam parity checks passed')


if __name__ == '__main__':
    main()
