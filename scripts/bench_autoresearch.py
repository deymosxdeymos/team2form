from __future__ import annotations

import json
import math
import statistics
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from team2form import (
    FormationRequest,
    Mode,
    TeamQualityRequest,
    WeightPreset,
    calculate_team_quality,
    form_teams,
)

ROOT = Path(__file__).resolve().parents[1]
GLEAM_CLI = ROOT / 'gleam' / 'scripts' / 'cli.mjs'
GLEAM_BENCH = ROOT / 'gleam' / 'scripts' / 'bench_inproc.mjs'


@dataclass
class Timings:
    python_ms: float
    gleam_ms: float

    @property
    def ratio(self) -> float:
        return self.gleam_ms / self.python_ms


def make_quality_payload(team_size: int) -> dict:
    task_skills = [
        {'id': f's{i}', 'level': 1.0, 'importance': 1}
        for i in range(team_size)
    ]
    team = []
    for i in range(team_size):
        teammate = (i + 1) % team_size
        team.append(
            {
                'id': f'p{i}',
                'gender': 'MALE' if i % 2 == 0 else 'FEMALE',
                'personality': {
                    'ei': 0.2 if i % 2 == 0 else -0.2,
                    'sn': (i / max(team_size - 1, 1)) * 0.6 - 0.3,
                    'tf': ((team_size - i) / team_size) * 0.6 - 0.3,
                    'pj': 0.1,
                },
                'skills': [
                    {'id': f's{i}', 'level': 1.0},
                    {'id': f's{teammate}', 'level': 0.5},
                ],
                'preferences': [
                    {'personId': f'p{i}', 'preference': 1.0},
                    {'personId': f'p{teammate}', 'preference': 0.8},
                ],
                'taskPreference': 0.8,
            }
        )

    return {
        'taskSkills': task_skills,
        'team': team,
        'alpha': 0.3,
        'beta': 0.3,
        'gamma': 0.2,
        'delta': 0.2,
    }


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

    for t in range(tasks_count):
        start = t * team_size
        task_people = list(range(start, start + team_size))
        tasks.append(
            {
                'id': f't{t}',
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


def run_gleam_cli(
    command: str,
    payload_path: Path,
    *,
    mode: str = 'compat',
    preset: str | None = 'live_compat',
    max_candidate_teams: int | None = None,
) -> dict:
    args = ['node', str(GLEAM_CLI), command, str(payload_path), '--mode', mode]
    if preset is not None:
        args.extend(['--preset', preset])
    if max_candidate_teams is not None:
        args.extend(['--max-candidate-teams', str(max_candidate_teams)])
    output = subprocess.check_output(args, cwd=ROOT, text=True)
    return json.loads(output)


def run_python_cli(
    command: str,
    payload_path: Path,
    *,
    mode: str = 'compat',
    preset: str | None = 'live_compat',
) -> dict:
    args = ['uv', 'run', 'team2form', command, str(payload_path), '--mode', mode]
    if preset is not None:
        args.extend(['--preset', preset])
    output = subprocess.check_output(args, cwd=ROOT, text=True)
    return json.loads(output)


def quality_close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def check_quality_parity(payload_path: Path) -> None:
    py = run_python_cli('quality', payload_path)
    gl = run_gleam_cli('quality', payload_path)

    if not quality_close(py['quality'], gl['quality']):
        raise AssertionError(f'quality mismatch: {py["quality"]} != {gl["quality"]}')

    if py['assignments'] != gl['assignments']:
        raise AssertionError(
            f'assignments mismatch: {py["assignments"]} != {gl["assignments"]}'
        )


def check_form_parity(
    payload_path: Path,
    *,
    max_candidate_teams: int | None = None,
) -> None:
    if max_candidate_teams is None:
        py = run_python_cli('form', payload_path)
        gl = run_gleam_cli('form', payload_path)
    else:
        payload = json.loads(payload_path.read_text())
        request = FormationRequest.model_validate(payload)
        py_response = form_teams(
            request,
            mode=Mode.COMPAT,
            preset=WeightPreset.LIVE_COMPAT,
            max_candidate_teams=max_candidate_teams,
        )
        py = {
            'teams': [
                {
                    'taskId': team.task_id,
                    'quality': team.quality,
                    'people': [
                        {'id': person.id, 'skillIds': person.skill_ids}
                        for person in team.people
                    ],
                }
                for team in py_response.teams
            ]
        }
        gl = run_gleam_cli('form', payload_path, max_candidate_teams=max_candidate_teams)

    py_by_task = {team['taskId']: team for team in py['teams']}
    gl_by_task = {team['taskId']: team for team in gl['teams']}

    if py_by_task.keys() != gl_by_task.keys():
        raise AssertionError('form task keys mismatch')

    for task_id, py_team in py_by_task.items():
        gl_team = gl_by_task[task_id]
        if not quality_close(py_team['quality'], gl_team['quality']):
            raise AssertionError(
                f'form quality mismatch on {task_id}: '
                f'{py_team["quality"]} != {gl_team["quality"]}'
            )


def benchmark_python_quality(
    payload_json: str,
    *,
    mode: Mode,
    preset: WeightPreset,
    iterations: int,
) -> float:
    start = time.perf_counter_ns()
    for _ in range(iterations):
        request = TeamQualityRequest.model_validate_json(payload_json)
        calculate_team_quality(request, mode=mode, preset=preset)
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    return elapsed_ms / iterations


def benchmark_python_form(
    payload_json: str,
    *,
    mode: Mode,
    preset: WeightPreset,
    iterations: int,
    max_candidate_teams: int | None = None,
) -> float:
    start = time.perf_counter_ns()
    for _ in range(iterations):
        request = FormationRequest.model_validate_json(payload_json)
        form_teams(
            request,
            mode=mode,
            preset=preset,
            max_candidate_teams=max_candidate_teams,
        )
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    return elapsed_ms / iterations


def benchmark_gleam(
    command: str,
    payload_path: Path,
    *,
    iterations: int,
    mode: str = 'compat',
    preset: str = 'live_compat',
    max_candidate_teams: int | None = None,
) -> float:
    args = [
        'node',
        str(GLEAM_BENCH),
        command,
        str(payload_path),
        str(iterations),
        mode,
        preset,
        str(max_candidate_teams) if max_candidate_teams is not None else 'none',
    ]
    output = subprocess.check_output(args, cwd=ROOT, text=True)
    parsed = json.loads(output)
    return float(parsed['per_call_ms'])


def geometric_mean(values: list[float]) -> float:
    if not values:
        raise ValueError('values must not be empty')
    if any(value <= 0 for value in values):
        return 0.0
    return math.exp(sum(math.log(value) for value in values) / len(values))


def write_payload(payload: dict) -> Path:
    handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    with handle:
        json.dump(payload, handle)
    return Path(handle.name)


def summarize(label: str, timings: list[Timings]) -> tuple[float, float, float]:
    ratios = [timing.ratio for timing in timings]
    ratio_mean = geometric_mean(ratios)
    ratio_stdev = statistics.stdev(ratios) if len(ratios) > 1 else 0.0
    ratio_cv = ratio_stdev / ratio_mean if ratio_mean > 0 else 0.0

    print(
        f'{label}: ratio_gmean={ratio_mean:.6f} '
        f'ratio_stdev={ratio_stdev:.6f} ratio_cv={ratio_cv:.6f}'
    )
    for index, timing in enumerate(timings):
        print(
            f'  run{index + 1}: python={timing.python_ms:.6f}ms '
            f'gleam={timing.gleam_ms:.6f}ms ratio={timing.ratio:.6f}'
        )

    return ratio_mean, ratio_stdev, ratio_cv


def main() -> None:
    quality_payloads = [
        json.loads((ROOT / 'examples' / 'team-quality.json').read_text()),
        make_quality_payload(team_size=8),
    ]
    form_payloads: list[tuple[dict, int | None]] = [
        (json.loads((ROOT / 'examples' / 'team-formation.json').read_text()), None),
        (make_form_payload(people_count=9, tasks_count=3), None),
        (make_form_payload(people_count=12, tasks_count=3), 10),
    ]

    quality_paths = [write_payload(payload) for payload in quality_payloads]
    form_paths = [write_payload(payload) for payload, _ in form_payloads]

    try:
        for path in quality_paths:
            check_quality_parity(path)
        for (_, max_candidate_teams), path in zip(
            form_payloads,
            form_paths,
            strict=True,
        ):
            check_form_parity(path, max_candidate_teams=max_candidate_teams)

        quality_timings: list[Timings] = []
        for payload, payload_path in zip(quality_payloads, quality_paths, strict=True):
            payload_json = json.dumps(payload, separators=(',', ':'))
            python_ms = benchmark_python_quality(
                payload_json,
                mode=Mode.COMPAT,
                preset=WeightPreset.LIVE_COMPAT,
                iterations=1000,
            )
            gleam_ms = benchmark_gleam(
                'quality',
                payload_path,
                iterations=1000,
            )
            quality_timings.append(Timings(python_ms=python_ms, gleam_ms=gleam_ms))

        form_timings: list[Timings] = []
        for (payload, max_candidate_teams), payload_path in zip(
            form_payloads,
            form_paths,
            strict=True,
        ):
            payload_json = json.dumps(payload, separators=(',', ':'))
            python_ms = benchmark_python_form(
                payload_json,
                mode=Mode.COMPAT,
                preset=WeightPreset.LIVE_COMPAT,
                iterations=40,
                max_candidate_teams=max_candidate_teams,
            )
            gleam_ms = benchmark_gleam(
                'form',
                payload_path,
                iterations=40,
                max_candidate_teams=max_candidate_teams,
            )
            form_timings.append(Timings(python_ms=python_ms, gleam_ms=gleam_ms))

        quality_ratio, quality_stdev, quality_cv = summarize('quality', quality_timings)
        form_ratio, form_stdev, form_cv = summarize('form', form_timings)

        combined_ratio = geometric_mean([quality_ratio, form_ratio])
        stability_cv = max(quality_cv, form_cv)

        print(f'METRIC combined_ratio={combined_ratio:.9f}')
        print(f'METRIC quality_ratio={quality_ratio:.9f}')
        print(f'METRIC form_ratio={form_ratio:.9f}')
        print(f'METRIC stability_cv={stability_cv:.9f}')
        print(f'METRIC quality_ratio_stdev={quality_stdev:.9f}')
        print(f'METRIC form_ratio_stdev={form_stdev:.9f}')
    finally:
        for path in [*quality_paths, *form_paths]:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
