from __future__ import annotations

import json
import math
import statistics
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_QUALITY = [
    'uv',
    'run',
    'team2form',
    'quality',
]
PY_FORM = [
    'uv',
    'run',
    'team2form',
    'form',
]
GL_QUALITY = [
    'node',
    str(ROOT / 'gleam' / 'scripts' / 'cli.mjs'),
    'quality',
]
GL_FORM = [
    'node',
    str(ROOT / 'gleam' / 'scripts' / 'cli.mjs'),
    'form',
]


@dataclass
class BenchResult:
    name: str
    mean_ms: float
    median_ms: float
    stdev_ms: float


def run_once(command: list[str], cwd: Path) -> tuple[float, str]:
    start = time.perf_counter_ns()
    output = subprocess.check_output(command, cwd=cwd, text=True)
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    return elapsed_ms, output


def benchmark(name: str, command: list[str], *, warmup: int = 3, runs: int = 20) -> BenchResult:
    for _ in range(warmup):
        subprocess.check_output(command, cwd=ROOT, text=True)

    samples: list[float] = []
    for _ in range(runs):
        elapsed, _ = run_once(command, ROOT)
        samples.append(elapsed)

    return BenchResult(
        name=name,
        mean_ms=statistics.mean(samples),
        median_ms=statistics.median(samples),
        stdev_ms=statistics.stdev(samples) if len(samples) > 1 else 0.0,
    )


def write_temp_payload(payload: dict) -> Path:
    handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    with handle:
        json.dump(payload, handle)
    return Path(handle.name)


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
    assert people_count % tasks_count == 0
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


def compare_output(command_a: list[str], command_b: list[str]) -> bool:
    a = json.loads(subprocess.check_output(command_a, cwd=ROOT, text=True))
    b = json.loads(subprocess.check_output(command_b, cwd=ROOT, text=True))

    if 'quality' in a and 'quality' in b:
        return math.isclose(a['quality'], b['quality'], rel_tol=1e-9, abs_tol=1e-9)

    if 'teams' in a and 'teams' in b:
        by_task_a = {team['taskId']: team for team in a['teams']}
        by_task_b = {team['taskId']: team for team in b['teams']}
        if by_task_a.keys() != by_task_b.keys():
            return False
        return all(
            math.isclose(
                by_task_a[task]['quality'],
                by_task_b[task]['quality'],
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            for task in by_task_a
        )

    return False


def print_result(result: BenchResult) -> None:
    print(
        f"{result.name:28} mean={result.mean_ms:8.2f}ms "
        f"median={result.median_ms:8.2f}ms stdev={result.stdev_ms:7.2f}ms"
    )


def main() -> None:
    quality_payload = make_quality_payload(team_size=8)
    form_payload = make_form_payload(people_count=10, tasks_count=2)

    quality_file = write_temp_payload(quality_payload)
    form_file = write_temp_payload(form_payload)

    try:
        py_quality_cmd = [
            *PY_QUALITY,
            str(quality_file),
            '--mode',
            'compat',
            '--preset',
            'live_compat',
        ]
        gl_quality_cmd = [
            *GL_QUALITY,
            str(quality_file),
            '--mode',
            'compat',
            '--preset',
            'live_compat',
        ]

        py_form_cmd = [
            *PY_FORM,
            str(form_file),
            '--mode',
            'compat',
            '--preset',
            'live_compat',
        ]
        gl_form_cmd = [
            *GL_FORM,
            str(form_file),
            '--mode',
            'compat',
            '--preset',
            'live_compat',
        ]

        print('Output parity checks:')
        print('  quality:', 'OK' if compare_output(py_quality_cmd, gl_quality_cmd) else 'DIFF')
        print('  form:   ', 'OK' if compare_output(py_form_cmd, gl_form_cmd) else 'DIFF')
        print()

        print('Benchmark results (includes process startup + JSON I/O):')
        py_q = benchmark('python quality', py_quality_cmd)
        gl_q = benchmark('gleam-js quality', gl_quality_cmd)
        py_f = benchmark('python form', py_form_cmd)
        gl_f = benchmark('gleam-js form', gl_form_cmd)

        print_result(py_q)
        print_result(gl_q)
        print_result(py_f)
        print_result(gl_f)

        print('\nRelative speed (lower is better):')
        print(f"  quality: gleam/python = {gl_q.mean_ms / py_q.mean_ms:.2f}x")
        print(f"  form:    gleam/python = {gl_f.mean_ms / py_f.mean_ms:.2f}x")
    finally:
        quality_file.unlink(missing_ok=True)
        form_file.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
