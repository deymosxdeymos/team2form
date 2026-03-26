# team2form vs live Edu2Com endpoint

Date: 2026-03-12

Compared local library results in `/home/deymos/Documents/team2form` against the live endpoint:
- `https://ardid.iiia.csic.es/eduteams/edu2com/v1/teamQuality`
- `https://ardid.iiia.csic.es/eduteams/edu2com/v1/teamFormation`

Reusable script:
- `scripts/compare_live.py`

Run it with:

```bash
cd /home/deymos/Documents/team2form
uv run python scripts/compare_live.py
```

## Summary

### Stable exact or practical-exact matches
1. `examples/team-quality.json`
   - local `team2form quality`
   - live `/v1/teamQuality`
   - exact match: `0.6725`

2. `examples/team-formation.json`
   - local `team2form form`
   - live `/v1/teamFormation`
   - exact normalized match
   - same members, same task responsibilities, same quality
   - only raw response array order may differ

3. fixture-style direct `teamQuality`
   - local scorer matches the live endpoint exactly for the tested 2-person quality probe
   - exact match: `0.5265322128134704`

4. odd `3+2` formation fixture
   - same team membership
   - same task responsibilities
   - same qualities up to floating-point noise
   - local: `0.28688290962700314`
   - live:  `0.28688290962700325`

5. larger `6-student / 3+3` formation fixture
   - same team membership
   - same task responsibilities
   - same qualities up to floating-point noise
   - local and live differ only in insignificant final decimal rounding

6. preferences + extended-skills fixture
   - exact normalized match
   - same members
   - same duplicated skill-id assignments
   - same qualities

### Remaining caveat
7. fixture-style symmetric `teamFormation`
   - the live endpoint is not fully deterministic in this case
   - repeated calls return **two different normalized variants**
   - both variants have the same two quality values:
     - `0.35153221281347036`
     - `0.29154319132398465`
   - the variants differ only in which task receives the stronger pair
   - local `team2form` deterministically selects one of the two live-observed variants

## What improved during comparison
The comparison work revealed and helped fix several compat quirks:

- compat skill scoring now uses observed live behavior more closely
  - raw matched skill levels matter more than required-level ratios
- compat personality scoring was adjusted to match additional live probes
- the compat ETJ bonus now requires a fully positive ETJ-style profile
- compat mixed-gender 3-person personality scoring now matches the live endpoint
- formation scoring now treats missing task preferences differently depending on whether a task preference list exists at all
- formation scoring now treats teammate preferences differently depending on whether a team has any explicit social preferences
- compat task-skill assignment no longer assumes a strict partition of task skills
  - in live compat behavior, members can carry overlapping `skillIds`
  - per-member skill selections are capped by `ceil(task_skills / team_size)`
  - this change was necessary to match live extended-skill fixtures
- global formation search now uses an exact DP over candidate teams instead of a greedy first-choice pass only
  - this fixed the stable `3+2` and `6-student` allocation cases

## Current parity status

### `teamQuality`
Current parity is strong for the tested scenarios, including:
- the example fixture
- the original 2-person fixture probe
- the richer 3-person mixed-gender probe

### `teamFormation`
Current parity is now strong across multiple richer fixtures:
- exact on the simple example
- practical-exact on the odd `3+2` fixture
- practical-exact on the larger `6-student / 3+3` fixture
- exact on the preferences + extended-skills fixture

The main remaining caveat is not a stable local-vs-live scoring gap, but a **live-endpoint nondeterminism** in the symmetric fixture.

## Practical conclusion
The local library is now good enough to:
- replicate core payload handling
- match tested `teamQuality` cases across small and moderate fixtures
- match several full `teamFormation` scenarios, including richer skill/preference cases
- reproduce live-style overlapping compat `skillIds` assignments in extended-skill scenarios
- provide a strong base for the upcoming FastAPI wrapper

The main thing still preventing a strict "black-box clone" claim is that the live `/v1/teamFormation` service itself appears nondeterministic in a symmetric tie case.
