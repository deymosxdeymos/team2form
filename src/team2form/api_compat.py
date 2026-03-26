from .formation import TeamFormationError, form_teams
from .models import (
    FormationRequest,
    QualityBreakdown,
    TeamQualityRequest,
    TeamsResponse,
)
from .modes import Mode, WeightPreset
from .scoring import calculate_team_quality


def help_info() -> dict[str, str]:
    return {'name': 'Edu2com', 'version': '0.1.0'}


__all__ = [
    'FormationRequest',
    'Mode',
    'QualityBreakdown',
    'TeamFormationError',
    'TeamQualityRequest',
    'TeamsResponse',
    'WeightPreset',
    'calculate_team_quality',
    'form_teams',
    'help_info',
]
