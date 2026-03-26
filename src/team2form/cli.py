from __future__ import annotations

import argparse
import json
from pathlib import Path

from .api_compat import calculate_team_quality, form_teams
from .models import FormationRequest, TeamQualityRequest, dump_json
from .modes import Mode, WeightPreset


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='team2form')
    subparsers = parser.add_subparsers(dest='command', required=True)

    for name in ('quality', 'form'):
        subparser = subparsers.add_parser(name)
        subparser.add_argument('input', type=Path)
        subparser.add_argument(
            '--mode',
            choices=[mode.value for mode in Mode],
            default=Mode.COMPAT.value,
        )
        subparser.add_argument(
            '--preset',
            choices=[preset.value for preset in WeightPreset],
            default=None,
        )
        subparser.add_argument('--normalize-weights', action='store_true')
        if name == 'form':
            subparser.add_argument('--max-candidate-teams', type=int, default=None)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    mode = Mode(args.mode)
    preset = WeightPreset(args.preset) if args.preset else None

    if args.command == 'quality':
        request = TeamQualityRequest.model_validate(read_json(args.input))
        result = calculate_team_quality(
            request,
            mode=mode,
            preset=preset,
            normalize_weights=args.normalize_weights,
        )
        print(json.dumps(dump_json(result), indent=2, sort_keys=True))
        return

    request = FormationRequest.model_validate(read_json(args.input))
    result = form_teams(
        request,
        mode=mode,
        preset=preset,
        normalize_weights=args.normalize_weights,
        max_candidate_teams=args.max_candidate_teams,
    )
    print(json.dumps(dump_json(result), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
