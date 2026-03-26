import sys
from pathlib import Path

import pytest

import team2form.cli as cli


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


def test_read_json_uses_utf_8(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {}
    path = Path('input.json')

    def fake_read_text(self: Path, *, encoding: str | None = None) -> str:
        assert self == path
        captured['encoding'] = encoding
        return '{"name": "Jos\u00e9"}'

    monkeypatch.setattr(Path, 'read_text', fake_read_text)

    assert cli.read_json(path) == {'name': 'José'}
    assert captured == {'encoding': 'utf-8'}



def test_cli_form_defaults_to_exact_candidate_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[int | None] = []
    printed: list[str] = []

    monkeypatch.setattr(sys, 'argv', ['team2form', 'form', 'input.json'])
    monkeypatch.setattr(
        cli,
        'read_json',
        lambda path: valid_formation_payload(),
    )
    monkeypatch.setattr(cli, 'dump_json', lambda value: value)

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
        return {'teams': []}

    monkeypatch.setattr(cli, 'form_teams', fake_form_teams)
    monkeypatch.setattr('builtins.print', printed.append)

    cli.main()

    assert captured == [None]
    assert printed == ['{\n  "teams": []\n}']


def test_cli_form_passes_explicit_candidate_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[int | None] = []
    printed: list[str] = []

    monkeypatch.setattr(
        sys,
        'argv',
        [
            'team2form',
            'form',
            'input.json',
            '--max-candidate-teams',
            '7',
        ],
    )
    monkeypatch.setattr(
        cli,
        'read_json',
        lambda path: valid_formation_payload(),
    )
    monkeypatch.setattr(cli, 'dump_json', lambda value: value)

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
        return {'teams': []}

    monkeypatch.setattr(cli, 'form_teams', fake_form_teams)
    monkeypatch.setattr('builtins.print', printed.append)

    cli.main()

    assert captured == [7]
    assert printed == ['{\n  "teams": []\n}']
