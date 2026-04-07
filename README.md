# team2form 🧩

A local reimplementation of the Edu2Com team formation model. Scores teams, forms them, and doesn't phone home.

**Two modes:**
- `compat` — mirrors the live Edu2Com endpoint
- `paper` — closer to the published scoring ideas

**Stack:** `uv` · `pydantic` · `fastapi` · `uvicorn` · `ruff` · `ty` · `pytest`

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
uv run team2form quality examples/team-quality.json --mode compat --preset live_compat

# form teams
uv run team2form form examples/team-formation.json --mode compat --preset live_compat

# go fast (approximate) on large inputs
uv run team2form form examples/team-formation.json --max-candidate-teams 10000
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
uv run team2form-api
# → http://127.0.0.1:8000
```

| method | path |
|---|---|
| `GET` | `/v1/help` |
| `POST` | `/v1/teamQuality` |
| `POST` | `/v1/teamFormation` |

The API caps candidate search at `10000` by default so you don't accidentally melt your laptop. Override with `create_app(max_candidate_teams=None)` if you really mean it.

## Notes
- No background webhook flow yet (the schema is ready, the plumbing isn't).
- Symmetric inputs can still be nondeterministic on the upstream Edu2Com service itself — that's their problem, not ours.
