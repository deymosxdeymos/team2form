# Make the Gleam Port Faster Than Python

## Summary

- Goal: make the Gleam implementation match Python outputs and beat Python on
  realistic in-process benchmarks, not just CLI startup.
- Keep Python as the reference oracle until Gleam passes parity and performance
  gates.
- Keep algorithms in Gleam; allow only tiny JS FFI primitives if profiling
  proves pure Gleam data structures are the blocker.
- Use official Gleam docs constraints: list.combinations returns a full List,
  dict.get returns Result(v, Nil), dict order is not stable, and Gleam Int
  bitwise ops on JavaScript use BigInt and should not be used in hot mask code.

## Key Changes

- Replace the current simple list.combinations(... ) |> list.take(...) formation
  path with a bounded candidate pipeline:
  - Generate capped combinations without materializing the full combinatorial
    list.
  - Port Python’s shortlist scoring behavior: skill coverage, task preference
    potential, social preference potential, and alternate scorers.
  - Preserve deterministic tie-breaking by original person/task order, never by
    dict iteration order.
- Add a per-call formation context in Gleam:
  - Store task lookup, original task order, resolved weights, similarity lookup,
    task preferences, and team score cache.
  - Add ScoredAllocation and a score cache keyed by #(task_id,
    sorted_team_signature).
  - Cache personality, social, task-skill values, and upper-bound estimates
    inside the context.
- Port Python’s allocation strategy in this order:
  - Use exact allocation only when capped candidate search is truly exact.
  - Add ranked task candidates with upper-bound pruning.
  - Add greedy allocation fallback for large capped searches.
  - Add bounded swap improvement with default swap_rounds = 8.
  - Keep public behavior compatible with the current Gleam wrapper:
    max_candidate_teams remains the only externally exposed tuning option for
    now; shortlist_padding = 6 and swap_rounds = 8 are internal defaults
    matching Python.
- Optimize only after parity:
  - First use idiomatic Gleam use <- result.try, explicit Error(Nil) handling,
    and no discarded errors.
  - Avoid nested error pyramids and side-effectful map/map_error.
  - If exact-allocation masks remain a hotspot, add a tiny JS FFI mask helper
    for people_count <= 30; keep a pure Gleam fallback for larger inputs.

## Test Plan

- Add Gleam tests mirroring the high-value Python formation tests:
  - candidate cap is respected;
  - bounded candidates use the full budget when possible;
  - capped search avoids full combination materialization;
  - score cache reuses team scores;
  - greedy allocation tie-breaking is deterministic;
  - exact allocation and swap improvement match Python quality/teams.
- Extend comparison scripts:
  - Check Python vs Gleam parity for examples, the current losing 10 people / 2
    tasks case, 9 people / 3 tasks, and at least one larger capped workload.
  - Compare qualities with 1e-9 tolerance and compare assignments/team
    membership where deterministic.
  - Run gleam check after each implementation slice.
- Performance gate:
  - In-process Gleam must be no slower than Python on every benchmark scenario.
  - Gleam geometric mean must be at least 25% faster than Python for quality,
    form, and combined suites.
  - CLI benchmarks stay informational only.

## Implementation Status

- Implemented bounded capped candidate generation so capped formation no longer
  blindly takes the first `list.combinations` results.
- Implemented candidate shortlisting/scoring, task upper-bound pruning, team score
  caching, greedy capped fallback, and bounded swap improvement.
- Kept Python as the oracle and extended parity scripts for examples, 10 people /
  2 tasks, 9 people / 3 tasks, and a larger capped workload.
- Added Gleam regression tests for capped formation cases that previously missed
  late specialists or needed improvement from unused people.
- Passed current gates:
  - `cd gleam && gleam check`
  - `cd gleam && gleam test`
  - `uv run python scripts/compare_gleam.py`
  - `uv run python scripts/bench_autoresearch.py`
- Intentional deviations:
  - The per-call formation context was implemented by threading cached lookup
    values through helpers rather than introducing one large context record.
  - Explicit standalone tests for score-cache reuse and exact-vs-swap internals
    were not added; current coverage verifies externally visible capped behavior.
  - No JS mask helper was added because the benchmark gate passes without it.
- Cleanup: removed obsolete autoresearch scratch files (`autoresearch.ideas.md`
  and `autoresearch.jsonl`).

## Assumptions

- Python remains the oracle until the Gleam port passes parity and benchmark
  gates.
- No full Python deletion is part of this plan.
- Core scoring and formation logic stays in Gleam.
- Official docs used for implementation constraints:
  - gleam/list combinations and list costs:
    https://hexdocs.pm/gleam_stdlib/gleam/list.html
  - gleam/dict lookup/order behavior:
    https://hexdocs.pm/gleam_stdlib/gleam/dict.html
  - gleam/result chaining behavior:
    https://hexdocs.pm/gleam_stdlib/gleam/result.html
  - JavaScript-target Int bitwise caveat:
    https://hexdocs.pm/gleam_stdlib/gleam/int.html
