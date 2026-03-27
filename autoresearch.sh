#!/bin/bash
set -euo pipefail

uv run python -m py_compile src/team2form/*.py

uv run python - <<'PY'
from __future__ import annotations

import gc
import random
import statistics
import time

from team2form import FormationRequest, Mode, form_teams


def make_request() -> FormationRequest:
    rnd = random.Random(0)
    people = []
    for index in range(16):
        skills = [
            {
                'id': f's{skill_id}',
                'level': round(rnd.uniform(0.3, 1.0), 2),
            }
            for skill_id in rnd.sample(range(10), k=4)
        ]
        preferences = [
            {
                'personId': f'p{person_id}',
                'preference': rnd.choice([0.0, 0.25, 0.5, 0.75, 1.0]),
            }
            for person_id in rnd.sample(
                [candidate for candidate in range(16) if candidate != index],
                k=4,
            )
        ]
        people.append(
            {
                'id': f'p{index}',
                'gender': 'FEMALE' if index % 2 == 0 else 'MALE',
                'personality': {
                    axis: round(rnd.uniform(-1.0, 1.0), 2)
                    for axis in ('ei', 'sn', 'tf', 'pj')
                },
                'skills': skills,
                'preferences': preferences,
            }
        )

    tasks = []
    for index in range(4):
        task_skills = [
            {
                'id': f's{skill_id}',
                'level': round(rnd.uniform(0.4, 1.0), 2),
                'importance': rnd.randint(1, 3),
            }
            for skill_id in rnd.sample(range(10), k=4)
        ]
        task_preferences = [
            {
                'personId': f'p{person_id}',
                'preference': rnd.choice([0.0, 0.25, 0.5, 0.75, 1.0]),
            }
            for person_id in rnd.sample(range(16), k=6)
        ]
        tasks.append(
            {
                'id': f't{index}',
                'teamSize': 4,
                'skills': task_skills,
                'preferences': task_preferences,
            }
        )

    return FormationRequest.model_validate(
        {
            'people': people,
            'tasks': tasks,
            'alpha': 0.3,
            'beta': 0.3,
            'gamma': 0.2,
            'delta': 0.2,
            'initRandom': False,
        }
    )


request = make_request()

warm_response = form_teams(
    request,
    mode=Mode.COMPAT,
    max_candidate_teams=1000,
)

quality_sum = sum(team.quality for team in warm_response.teams)
quality_min = min(team.quality for team in warm_response.teams)
team_count = len(warm_response.teams)

samples_ms = []
for _ in range(5):
    gc.collect()
    start = time.perf_counter()
    response = form_teams(
        request,
        mode=Mode.COMPAT,
        max_candidate_teams=1000,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    samples_ms.append(elapsed_ms)
    assert len(response.teams) == team_count
    assert abs(sum(team.quality for team in response.teams) - quality_sum) < 1e-12

print(f'METRIC total_ms={statistics.median(samples_ms):.6f}')
print(f'METRIC best_ms={min(samples_ms):.6f}')
print(f'METRIC quality_sum={quality_sum:.12f}')
print(f'METRIC quality_min={quality_min:.12f}')
print(f'METRIC team_count={team_count}')
PY
