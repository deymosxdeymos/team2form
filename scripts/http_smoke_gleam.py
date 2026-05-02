from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from team2form import (
    Mode,
    TeamQualityRequest,
    WeightPreset,
    calculate_team_quality,
    form_teams,
)
from team2form.models import FormationRequest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'gleam' / 'scripts' / 'server.mjs'


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def request_json(
    method: str,
    url: str,
    payload: dict | None = None,
) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(
        url,
        data=data,
        method=method,
        headers={'content-type': 'application/json'},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def request_bytes(method: str, url: str, data: bytes) -> tuple[int, dict]:
    request = Request(
        url,
        data=data,
        method=method,
        headers={'content-type': 'application/json'},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def wait_until_ready(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Node server exited before becoming ready')
        try:
            status, _body = request_json('GET', f'{base_url}/v1/help')
            if status == 200:
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError('Node server did not become ready')


def assert_close(left: float, right: float, *, tolerance: float = 1e-9) -> None:
    if not math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance):
        raise AssertionError(f'Expected {left} ~= {right}')


def assert_quality_matches_python(base_url: str) -> None:
    payload = json.loads((ROOT / 'examples' / 'team-quality.json').read_text())
    request = TeamQualityRequest.model_validate(payload)
    expected = calculate_team_quality(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
    )

    status, actual = request_json('POST', f'{base_url}/v1/teamQuality', payload)
    assert status == 200
    assert_close(expected.quality, actual['quality'])
    assert_close(expected.skill_score, actual['skillScore'])
    assert expected.assignments == actual['assignments']


def assert_formation_matches_python(base_url: str) -> None:
    payload = json.loads((ROOT / 'examples' / 'team-formation.json').read_text())
    request = FormationRequest.model_validate(payload)
    expected = form_teams(
        request,
        mode=Mode.COMPAT,
        preset=WeightPreset.LIVE_COMPAT,
        max_candidate_teams=10000,
    )

    status, actual = request_json('POST', f'{base_url}/v1/teamFormation', payload)
    assert status == 200
    expected_by_task = {team.task_id: team for team in expected.teams}
    actual_by_task = {team['taskId']: team for team in actual['teams']}
    assert expected_by_task.keys() == actual_by_task.keys()
    for task_id, expected_team in expected_by_task.items():
        actual_team = actual_by_task[task_id]
        assert_close(expected_team.quality, actual_team['quality'])
        expected_people = {
            person.id: sorted(person.skill_ids)
            for person in expected_team.people
        }
        actual_people = {
            person['id']: sorted(person['skillIds'])
            for person in actual_team['people']
        }
        assert expected_people == actual_people


def assert_insufficient_headcount(base_url: str) -> None:
    payload = {
        'people': [
            {
                'id': 'p0',
                'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                'skills': [{'id': 's1', 'level': 1.0}],
                'preferences': [],
            },
            {
                'id': 'p1',
                'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                'skills': [{'id': 's1', 'level': 1.0}],
                'preferences': [],
            },
        ],
        'tasks': [
            {
                'id': 't0',
                'teamSize': 3,
                'skills': [{'id': 's1', 'level': 1.0, 'importance': 1}],
                'preferences': [],
            }
        ],
        'alpha': 0.3,
        'beta': 0.3,
        'gamma': 0.2,
        'delta': 0.2,
        'initRandom': False,
    }
    status, body = request_json('POST', f'{base_url}/v1/teamFormation', payload)
    assert status == 400
    assert 'insufficient headcount' in body['detail']


def assert_oversized_body_returns_json_413(base_url: str) -> None:
    body = b'{' + (b'"x":' + b'"' + (b'a' * (10 * 1024 * 1024)) + b'"}')
    status, response = request_bytes('POST', f'{base_url}/v1/teamQuality', body)
    assert status == 413
    assert response == {'detail': 'Request body too large'}


def assert_invalid_port_is_rejected() -> None:
    env = {
        **os.environ,
        'TEAM2FORM_PORT': '8000abc',
    }
    process = subprocess.run(
        ['node', str(SERVER)],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    assert process.returncode != 0
    assert 'TEAM2FORM_PORT must be an integer from 1 to 65535' in process.stderr


def main() -> None:
    assert_invalid_port_is_rejected()

    port = free_port()
    base_url = f'http://127.0.0.1:{port}'
    env = {
        **os.environ,
        'TEAM2FORM_HOST': '127.0.0.1',
        'TEAM2FORM_PORT': str(port),
        'TEAM2FORM_MODE': 'compat',
        'TEAM2FORM_PRESET': 'live_compat',
    }
    process = subprocess.Popen(
        ['node', str(SERVER)],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        wait_until_ready(base_url, process)
        status, help_body = request_json('GET', f'{base_url}/v1/help')
        assert status == 200
        assert help_body == {'name': 'Edu2com', 'version': '0.1.0'}
        assert_quality_matches_python(base_url)
        assert_formation_matches_python(base_url)
        assert_insufficient_headcount(base_url)
        assert_oversized_body_returns_json_413(base_url)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    print('Gleam HTTP smoke checks passed')


if __name__ == '__main__':
    main()
