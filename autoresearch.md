# Autoresearch: form_teams capped-search performance

## Objective
Optimize `team2form.form_teams()` wall-clock time for a representative capped compat-mode workload that exercises the current default shortlist-based search path, while preserving behavior and correctness.

The benchmark uses a deterministic synthetic request with:
- 16 people
- 4 tasks of size 4
- 10 skills
- non-trivial task preferences, teammate preferences, and personality data
- `mode=compat`
- `max_candidate_teams=1000`

This workload is intentionally small enough to run repeatedly, but large enough that the hot path includes candidate shortlisting, repeated team scoring, task-skill assignment, personality/social scoring, and post-greedy swap improvement.

## Metrics
- **Primary**: `total_ms` (ms, lower is better) — median runtime across repeated benchmark runs
- **Secondary**: `best_ms`, `quality_sum`, `quality_min`, `team_count` — stability and behavior monitors

## How to Run
`./autoresearch.sh` — outputs structured `METRIC name=value` lines.

## Files in Scope
- `src/team2form/formation.py` — team formation search, candidate generation, greedy/exact flow, swap improvement
- `src/team2form/scoring.py` — scoring, skill assignment, personality/social/task preference calculations
- `tests/test_form_teams.py` — regression coverage for search/scoring behavior
- `tests/test_team_quality.py` — regression coverage if scoring helpers change
- `autoresearch.sh` — benchmark harness and instrumentation
- `autoresearch.checks.sh` — correctness checks for kept results

## Off Limits
- Public API shape in `src/team2form/models.py`
- CLI/server UX unless required by an internal refactor
- `dist/`, `examples/`, and `comparison-live-endpoint.md`
- New runtime dependencies

## Constraints
- Preserve observable behavior and determinism for existing tests
- `uv run pytest`, `uv run ruff check .`, and `uv run ty check` must pass for kept changes
- Keep benchmark deterministic and cheap enough for repeated runs
- Prefer simpler internal changes over hard-to-maintain micro-optimizations

## What's Been Tried
- Initial profiling on the synthetic capped workload showed `score_team()` dominating runtime.
- The hottest transitive costs were:
  - repeated `team_personality_score()` calls via `statistics.pstdev()`
  - repeated Pydantic object construction in `build_team_quality_request()`
  - compat task-skill assignment work in `_assign_task_skills_compat()`
- First experiments should focus on removing avoidable per-candidate recomputation before attempting larger search changes.
