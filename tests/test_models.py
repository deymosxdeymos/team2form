from team2form import FormationRequest
from team2form.models import dump_json


def test_dump_json_excludes_computed_fields_from_requests() -> None:
    request = FormationRequest.model_validate(
        {
            'people': [
                {
                    'id': 'a',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's1', 'level': 1.0}],
                },
                {
                    'id': 'b',
                    'personality': {'ei': 0.0, 'sn': 0.0, 'tf': 0.0, 'pj': 0.0},
                    'skills': [{'id': 's2', 'level': 1.0}],
                },
            ],
            'tasks': [
                {
                    'id': 't1',
                    'teamSize': 2,
                    'skills': [
                        {'id': 's1', 'level': 1.0, 'importance': 1},
                        {'id': 's2', 'level': 1.0, 'importance': 1},
                    ],
                }
            ],
        }
    )

    payload = dump_json(request)

    assert 'total_requested_seats' not in payload
    assert FormationRequest.model_validate(payload) == request
