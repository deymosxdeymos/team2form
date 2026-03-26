# team2form

Hybrid local reimplementation of the Edu2Com team formation model.

Current scope:
- local Python library first
- hybrid behavior modes:
  - `compat`: closer to the live Edu2Com endpoint behavior
  - `paper`: closer to the published scoring ideas
- implemented now:
  - team quality scoring
  - deterministic local team formation
  - small JSON CLI

## Stack
- `uv`
- `pydantic`
- `ruff`
- `ty`
- `pytest`

## Install
```bash
cd /home/deymos/Documents/team2form
uv sync
```

## Run tests
```bash
uv run pytest
uv run ruff check .
uv run ty check
```

## CLI
### Score a team
```bash
uv run team2form quality examples/team-quality.json --mode compat --preset live_compat
```

### Form teams locally
```bash
uv run team2form form examples/team-formation.json --mode compat --preset live_compat
```

Add `--max-candidate-teams 10000` to opt into shortlist-based candidate pruning for faster approximate search on large inputs.

## Python usage
```python
from team2form import FormationRequest, Mode, WeightPreset, TeamQualityRequest, calculate_team_quality, form_teams

quality_request = TeamQualityRequest.model_validate({...})
quality = calculate_team_quality(
    quality_request,
    mode=Mode.COMPAT,
    preset=WeightPreset.LIVE_COMPAT,
)

formation_request = FormationRequest.model_validate({...})
teams = form_teams(
    formation_request,
    mode=Mode.COMPAT,
    preset=WeightPreset.LIVE_COMPAT,
)
```

`form_teams()` defaults to exact candidate enumeration. Pass `max_candidate_teams=10000` or another positive integer to enable heuristic pruning explicitly.

The FastAPI wrapper is safer by default: `create_app()` and `team2form-api` start with `max_candidate_teams=10000` so ordinary API requests do not hit uncapped exact enumeration unless you explicitly override it with `max_candidate_teams=None`.

## Weight presets
- `live_compat` -> `0.3, 0.3, 0.2, 0.2`
- `docs_recommended` -> `0.4, 0.3, 0.2, 0.1`
- `paper_balanced` -> `0.25, 0.25, 0.25, 0.25`

## API wrapper
Run the local compatibility API:

```bash
uv run team2form-api
```

By default the API uses a bounded candidate cap (`10000`) for `/v1/teamFormation`. If you embed the app yourself and intentionally want uncapped exact search, call `create_app(max_candidate_teams=None)`.

Endpoints:
- `GET /v1/help`
- `POST /v1/teamQuality`
- `POST /v1/teamFormation`

Example:

```bash
curl http://127.0.0.1:8000/v1/help
```

## Notes
Current limitations:
- no background webhook flow yet
- symmetric live `/v1/teamFormation` cases can still be nondeterministic on the upstream service itself
