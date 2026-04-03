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
- Kept:
  - Replaced `statistics.pstdev()` in personality scoring with a float-only implementation. This was the first major win.
  - Added a direct formation scoring path that reuses raw `Person` objects instead of rebuilding Pydantic `TeamQualityRequest` / `TeamMember` structures for every candidate.
  - Added a form-wide `ScoredAllocation` cache shared by candidate generation and swap improvement so repeated task/team evaluations are reused.
  - Cached team-only personality and social components across tasks and swap evaluations; the same group composition often reappears under different tasks.
  - Cached compat member task-value vectors by member identity plus ordered task-skill ids to avoid rebuilding the same per-person alignment arrays.
- Discarded:
  - Precomputing shortlist-scorer invariants per task did not improve the end-to-end benchmark.
  - Caching per-request task lookup / filtered task preferences inside `score_team()` also failed to beat the current best.
  - Replacing the square-team compat perfect-matching recursion with a bitmask DP was slower.
  - Precomputing tiny task-skill cleanup structures for `_compat_fill_uncovered_assignments()` was slower.
  - Making `improve_allocations()` compare objectives from quality lists instead of temporary allocation lists was slower.
  - A naive merged-analysis rewrite of compat assignment changed behavior on regression tests and should not be retried casually.
  - Small `math.isclose` micro-optimizations in `_compat_other_member_best_values()` were not worthwhile.
- Current hotspot picture after the big wins:
  - `_assign_task_skills_compat()` and its helper passes still dominate scoring cost.
  - `candidate_combinations()` remains the next major bucket.
  - `team_personality_score()` and `team_social_score()` are now much smaller after cross-task caching.
- Good next directions:
  - Collapse multiple helper passes inside `_assign_task_skills_compat()`.
  - Reduce shortlist / candidate ranking overhead without hurting solution quality.
  - Look for more team-independent values that can be reused across candidate evaluations.
