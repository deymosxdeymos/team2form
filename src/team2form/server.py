from __future__ import annotations

import uvicorn
from fastapi import FastAPI, HTTPException

from .api_compat import help_info
from .formation import DEFAULT_MAX_CANDIDATE_TEAMS, TeamFormationError, form_teams
from .models import (
    FormationRequest,
    QualityBreakdown,
    TeamQualityRequest,
    TeamsResponse,
)
from .modes import Mode, WeightPreset
from .scoring import calculate_team_quality


def create_app(
    *,
    mode: Mode = Mode.COMPAT,
    preset: WeightPreset | None = None,
    normalize_weights: bool = False,
    max_candidate_teams: int | None = DEFAULT_MAX_CANDIDATE_TEAMS,
) -> FastAPI:
    app = FastAPI(
        title='Edu2com-compatible Team2Form',
        version='0.1.0',
    )

    @app.get('/v1/help')
    def get_help() -> dict[str, str]:
        return help_info()

    @app.post('/v1/teamQuality', response_model=QualityBreakdown)
    def post_team_quality(request: TeamQualityRequest) -> QualityBreakdown:
        return calculate_team_quality(
            request,
            mode=mode,
            preset=preset,
            normalize_weights=normalize_weights,
        )

    @app.post('/v1/teamFormation', response_model=TeamsResponse)
    def post_team_formation(request: FormationRequest) -> TeamsResponse:
        try:
            return form_teams(
                request,
                mode=mode,
                preset=preset,
                normalize_weights=normalize_weights,
                max_candidate_teams=max_candidate_teams,
            )
        except TeamFormationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()


def main() -> None:
    uvicorn.run('team2form.server:app', host='127.0.0.1', port=8000)
