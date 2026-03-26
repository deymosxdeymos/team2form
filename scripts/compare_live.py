from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from team2form import (
    FormationRequest,
    Mode,
    TeamQualityRequest,
    WeightPreset,
    calculate_team_quality,
    form_teams,
)

BASE_URL = 'https://ardid.iiia.csic.es/eduteams/edu2com'


def post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f'{BASE_URL}{path}',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode())


def normalize_teams(payload: dict[str, Any]) -> list[dict[str, Any]]:
    teams = []
    for team in payload['teams']:
        teams.append(
            {
                'taskId': team['taskId'],
                'quality': round(team['quality'], 12),
                'people': sorted(
                    [
                        {
                            'id': person['id'],
                            'skillIds': sorted(person['skillIds']),
                        }
                        for person in team['people']
                    ],
                    key=lambda person: person['id'],
                ),
            }
        )
    return sorted(teams, key=lambda team: team['taskId'])


def example_quality_payload() -> dict[str, Any]:
    return json.loads(Path('examples/team-quality.json').read_text())


def example_formation_payload() -> dict[str, Any]:
    return json.loads(Path('examples/team-formation.json').read_text())


def fixture_formation_payload() -> dict[str, Any]:
    return {
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


def odd_team_formation_payload() -> dict[str, Any]:
    payload = fixture_formation_payload()
    payload['people'].append(
        {
            'id': 'student-5',
            'gender': 'FEMALE',
            'personality': {'ei': 0.2, 'sn': 0.1, 'tf': 0.4, 'pj': -0.5},
            'skills': [
                {'id': 'skill-frontend', 'level': 0.55},
                {'id': 'skill-devops', 'level': 0.6},
            ],
        }
    )
    payload['tasks'] = [
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
    ]
    return payload


def larger_cohort_payload() -> dict[str, Any]:
    payload = fixture_formation_payload()
    payload['people'].extend(
        [
            {
                'id': 'student-5',
                'gender': 'MALE',
                'personality': {'ei': 0.1, 'sn': -0.5, 'tf': 0.2, 'pj': 0.4},
                'skills': [
                    {'id': 'skill-devops', 'level': 0.7},
                    {'id': 'skill-backend', 'level': 0.5},
                ],
            },
            {
                'id': 'student-6',
                'gender': 'FEMALE',
                'personality': {'ei': -0.4, 'sn': 0.3, 'tf': 0.6, 'pj': -0.3},
                'skills': [
                    {'id': 'skill-frontend', 'level': 0.6},
                    {'id': 'skill-devops', 'level': 0.5},
                ],
            },
        ]
    )
    payload['tasks'] = [
        {
            'id': 'task-frontline',
            'teamSize': 3,
            'skills': [
                {'id': 'skill-frontend', 'level': 0.6, 'importance': 1},
                {'id': 'skill-backend', 'level': 0.4, 'importance': 1},
                {'id': 'skill-devops', 'level': 0.3, 'importance': 1},
            ],
        },
        {
            'id': 'task-backoffice',
            'teamSize': 3,
            'skills': [
                {'id': 'skill-backend', 'level': 0.6, 'importance': 1},
                {'id': 'skill-frontend', 'level': 0.4, 'importance': 1},
                {'id': 'skill-devops', 'level': 0.4, 'importance': 1},
            ],
        },
    ]
    return payload


def preferences_extended_payload() -> dict[str, Any]:
    payload = fixture_formation_payload()
    enhanced_people = []
    for index, person in enumerate(payload['people']):
        next_person = payload['people'][(index + 1) % len(payload['people'])]
        enhanced_people.append(
            {
                **person,
                'skills': [
                    *person['skills'],
                    *(
                        [{'id': 'skill-devops', 'level': 0.45}]
                        if index < 2
                        else []
                    ),
                ],
                'preferences': [
                    {
                        'personId': next_person['id'],
                        'preference': 0.8,
                    }
                ],
            }
        )
    payload['people'] = enhanced_people
    payload['tasks'] = [
        {
            **task,
            'preferences': [
                {'personId': payload['people'][0]['id'], 'preference': 0.9},
                {'personId': payload['people'][1]['id'], 'preference': 0.6},
            ],
            'skills': [
                *task['skills'],
                {'id': 'skill-devops', 'level': 0.3, 'importance': 1},
            ],
        }
        for task in payload['tasks']
    ]
    payload['similarities'] = [
        *payload['similarities'],
        {
            'sourceId': 'skill-frontend',
            'targetId': 'skill-devops',
            'similarity': 0.4,
        },
    ]
    return payload


def fixture_quality_payload() -> dict[str, Any]:
    return {
        'alpha': 0.4,
        'beta': 0.3,
        'gamma': 0.2,
        'delta': 0.1,
        'taskSkills': [
            {'id': 'skill-frontend', 'level': 0.7, 'importance': 1},
            {'id': 'skill-backend', 'level': 0.4, 'importance': 1},
        ],
        'team': [
            {
                'id': 'student-1',
                'gender': 'FEMALE',
                'personality': {'ei': 0.3, 'sn': -0.2, 'tf': 0.5, 'pj': 0.7},
                'skills': [
                    {'id': 'skill-frontend', 'level': 0.8},
                    {'id': 'skill-backend', 'level': 0.4},
                ],
                'taskPreference': 0.5,
            },
            {
                'id': 'student-2',
                'gender': 'MALE',
                'personality': {'ei': -0.1, 'sn': 0.6, 'tf': -0.2, 'pj': 0.4},
                'skills': [
                    {'id': 'skill-frontend', 'level': 0.6},
                    {'id': 'skill-backend', 'level': 0.5},
                ],
                'taskPreference': 0.5,
            },
        ],
    }


def compare_team_quality(
    name: str,
    payload: dict[str, Any],
    preset: WeightPreset,
) -> None:
    local = calculate_team_quality(
        TeamQualityRequest.model_validate(payload),
        mode=Mode.COMPAT,
        preset=preset,
    )
    live = post('/v1/teamQuality', payload)
    print(f'## {name}')
    print(f'- local quality: {local.quality}')
    print(f'- live quality:  {live["quality"]}')
    print(f'- absolute delta: {abs(local.quality - live["quality"]):.12f}')
    print()


def compare_team_formation(
    name: str,
    payload: dict[str, Any],
    preset: WeightPreset,
) -> None:
    local = form_teams(
        FormationRequest.model_validate(payload),
        mode=Mode.COMPAT,
        preset=preset,
    ).model_dump(mode='json', by_alias=True)
    live = post('/v1/teamFormation', payload)
    local_normalized = normalize_teams(local)
    live_normalized = normalize_teams(live)
    print(f'## {name}')
    print(f'- normalized local teams: {json.dumps(local_normalized)}')
    print(f'- normalized live teams:  {json.dumps(live_normalized)}')
    print(f'- exact normalized match: {local_normalized == live_normalized}')
    print()


def probe_live_team_formation_variants(
    name: str,
    payload: dict[str, Any],
    *,
    attempts: int = 8,
) -> None:
    variants: dict[str, int] = {}
    for _ in range(attempts):
        normalized = normalize_teams(post('/v1/teamFormation', payload))
        key = json.dumps(normalized, sort_keys=True)
        variants[key] = variants.get(key, 0) + 1
    print(f'## {name} live-variant probe')
    print(f'- attempts: {attempts}')
    print(f'- unique normalized variants: {len(variants)}')
    for variant, count in variants.items():
        print(f'- seen {count}x: {variant}')
    print()


def main() -> None:
    compare_team_quality(
        'Example teamQuality',
        example_quality_payload(),
        WeightPreset.LIVE_COMPAT,
    )
    compare_team_formation(
        'Example teamFormation',
        example_formation_payload(),
        WeightPreset.LIVE_COMPAT,
    )
    compare_team_quality(
        'Fixture-style teamQuality',
        fixture_quality_payload(),
        WeightPreset.LIVE_COMPAT,
    )
    compare_team_formation(
        'Fixture-style teamFormation',
        fixture_formation_payload(),
        WeightPreset.LIVE_COMPAT,
    )
    compare_team_formation(
        'Odd 3+2 teamFormation',
        odd_team_formation_payload(),
        WeightPreset.LIVE_COMPAT,
    )
    compare_team_formation(
        'Larger cohort 6-student teamFormation',
        larger_cohort_payload(),
        WeightPreset.LIVE_COMPAT,
    )
    compare_team_formation(
        'Preferences + extended skills teamFormation',
        preferences_extended_payload(),
        WeightPreset.LIVE_COMPAT,
    )
    probe_live_team_formation_variants(
        'Fixture-style symmetric',
        fixture_formation_payload(),
    )


if __name__ == '__main__':
    main()
