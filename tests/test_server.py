import pytest
from fastapi.testclient import TestClient

from team2form import Mode
from team2form.formation import DEFAULT_MAX_CANDIDATE_TEAMS
from team2form.server import create_app

client = TestClient(create_app())


def valid_formation_payload() -> dict:
    return {
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


def test_help_endpoint_matches_edu2com_shape() -> None:
    response = client.get('/v1/help')

    assert response.status_code == 200
    assert response.json() == {'name': 'Edu2com', 'version': '0.1.0'}


def test_team_quality_endpoint_returns_breakdown() -> None:
    response = client.post(
        '/v1/teamQuality',
        json={
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                {
                    'id': 'a',
                    'gender': 'MALE',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'taskPreference': 1.0,
                },
                {
                    'id': 'b',
                    'gender': 'FEMALE',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'taskPreference': 1.0,
                },
            ],
            'alpha': 1.0,
            'beta': 0.0,
            'gamma': 0.0,
            'delta': 0.0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body['quality'] == 1.0
    assert body['skillScore'] == 1.0
    assert sorted(
        tuple(value) for value in body['assignments'].values()
    ) == [('s1',), ('s1',)]


def test_team_formation_endpoint_returns_400_on_insufficient_headcount() -> None:
    response = client.post(
        '/v1/teamFormation',
        json={
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
                    'teamSize': 3,
                    'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                }
            ],
        },
    )

    assert response.status_code == 400
    assert 'insufficient headcount' in response.json()['detail']


def test_paper_mode_server_defaults_to_paper_weights() -> None:
    client = TestClient(create_app(mode=Mode.PAPER))

    response = client.post(
        '/v1/teamQuality',
        json={
            'taskSkills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
            'team': [
                {
                    'id': 'a',
                    'gender': 'MALE',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'taskPreference': 1.0,
                },
                {
                    'id': 'b',
                    'gender': 'FEMALE',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                    'taskPreference': 0.25,
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()['weights'] == {
        'alpha': 0.25,
        'beta': 0.25,
        'gamma': 0.25,
        'delta': 0.25,
    }


def test_create_app_defaults_to_bounded_candidate_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[int | None] = []

    def fake_form_teams(
        request,
        *,
        mode,
        preset,
        normalize_weights,
        max_candidate_teams,
    ):
        _ = request
        _ = mode
        _ = preset
        _ = normalize_weights
        captured.append(max_candidate_teams)
        return {
            'teams': [
                {
                    'taskId': 't1',
                    'people': [
                        {'id': 'a', 'skillIds': ['s1']},
                        {'id': 'b', 'skillIds': ['s1']},
                    ],
                    'quality': 1.0,
                }
            ]
        }

    monkeypatch.setattr('team2form.server.form_teams', fake_form_teams)
    client = TestClient(create_app())

    response = client.post('/v1/teamFormation', json=valid_formation_payload())

    assert response.status_code == 200
    assert captured == [DEFAULT_MAX_CANDIDATE_TEAMS]


def test_create_app_allows_explicit_uncapped_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[int | None] = []

    def fake_form_teams(
        request,
        *,
        mode,
        preset,
        normalize_weights,
        max_candidate_teams,
    ):
        _ = request
        _ = mode
        _ = preset
        _ = normalize_weights
        captured.append(max_candidate_teams)
        return {
            'teams': [
                {
                    'taskId': 't1',
                    'people': [
                        {'id': 'a', 'skillIds': ['s1']},
                        {'id': 'b', 'skillIds': ['s1']},
                    ],
                    'quality': 1.0,
                }
            ]
        }

    monkeypatch.setattr('team2form.server.form_teams', fake_form_teams)
    client = TestClient(create_app(max_candidate_teams=None))

    response = client.post('/v1/teamFormation', json=valid_formation_payload())

    assert response.status_code == 200
    assert captured == [None]


def test_create_app_passes_explicit_candidate_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[int | None] = []

    def fake_form_teams(
        request,
        *,
        mode,
        preset,
        normalize_weights,
        max_candidate_teams,
    ):
        _ = request
        _ = mode
        _ = preset
        _ = normalize_weights
        captured.append(max_candidate_teams)
        return {
            'teams': [
                {
                    'taskId': 't1',
                    'people': [
                        {'id': 'a', 'skillIds': ['s1']},
                        {'id': 'b', 'skillIds': ['s1']},
                    ],
                    'quality': 1.0,
                }
            ]
        }

    monkeypatch.setattr('team2form.server.form_teams', fake_form_teams)
    client = TestClient(create_app(max_candidate_teams=7))

    response = client.post('/v1/teamFormation', json=valid_formation_payload())

    assert response.status_code == 200
    assert captured == [7]
