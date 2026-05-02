# team2form 🧩

A local reimplementation of the Edu2Com team formation model. Scores teams, forms them, and doesn't phone home.

**Two modes:**
- `compat` — mirrors the live Edu2Com endpoint
- `paper` — closer to the published scoring ideas

**Stack:** `gleam` · `node` · `uv` · `pydantic` · `ruff` · `ty` · `pytest`

## Install
```bash
uv sync
```

## Test
```bash
uv run pytest
uv run ruff check .
uv run ty check
```

## CLI

```bash
# score a team
cd gleam
gleam build
node scripts/cli.mjs quality ../examples/team-quality.json --mode compat --preset live_compat

# form teams
node scripts/cli.mjs form ../examples/team-formation.json --mode compat --preset live_compat

# go fast (approximate) on large inputs
node scripts/cli.mjs form ../examples/team-formation.json --max-candidate-teams 10000
```

## Python

```python
from team2form import (
    FormationRequest, TeamQualityRequest,
    Mode, WeightPreset,
    calculate_team_quality, form_teams,
)

quality = calculate_team_quality(
    TeamQualityRequest.model_validate({...}),
    mode=Mode.COMPAT,
    preset=WeightPreset.LIVE_COMPAT,
)

teams = form_teams(
    FormationRequest.model_validate({...}),
    mode=Mode.COMPAT,
    preset=WeightPreset.LIVE_COMPAT,
    # max_candidate_teams=10000  ← pass this to cap search on big inputs
)
```

## Weight presets

| preset | α | β | γ | δ |
|---|---|---|---|---|
| `live_compat` | 0.3 | 0.3 | 0.2 | 0.2 |
| `docs_recommended` | 0.4 | 0.3 | 0.2 | 0.1 |
| `paper_balanced` | 0.25 | 0.25 | 0.25 | 0.25 |

## API

```bash
cd gleam
gleam build
node scripts/server.mjs
# → http://127.0.0.1:8000
```

| method | path |
|---|---|
| `GET` | `/v1/help` |
| `POST` | `/v1/teamQuality` |
| `POST` | `/v1/teamFormation` |

The Node API caps candidate search at `10000` by default so you don't accidentally melt your laptop. Set `TEAM2FORM_MAX_CANDIDATE_TEAMS=none` if you really mean it.

Server defaults are configured with environment variables: `TEAM2FORM_HOST`, `TEAM2FORM_PORT`, `TEAM2FORM_MODE`, `TEAM2FORM_PRESET`, `TEAM2FORM_NORMALIZE_WEIGHTS`, and `TEAM2FORM_MAX_CANDIDATE_TEAMS`.

The Python FastAPI command remains available only as a short-term rollback/reference path:

```bash
uv run team2form-api
```

## Notes
- No background webhook flow yet (the schema is ready, the plumbing isn't).
- Symmetric inputs can still be nondeterministic on the upstream Edu2Com service itself — that's their problem, not ours.
