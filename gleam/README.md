# team2form

Gleam/JavaScript implementation of the Edu2Com-compatible team formation model.

- Core domain models and validation
- Team quality scoring
- Exact and capped team formation search
- CLI wrapper (Node)
- HTTP API wrapper (Node)

## Build

```bash
cd gleam
gleam check
gleam build
```

## CLI

```bash
# quality
node scripts/cli.mjs quality ../examples/team-quality.json --mode compat --preset live_compat

# form
node scripts/cli.mjs form ../examples/team-formation.json --mode compat --preset live_compat
```

## Test

```bash
gleam test
node ../scripts/http_smoke_gleam.mjs
```

## API

```bash
node scripts/server.mjs
# GET  http://127.0.0.1:8000/v1/help
# POST http://127.0.0.1:8000/v1/teamQuality
# POST http://127.0.0.1:8000/v1/teamFormation
```

The server reads defaults from `TEAM2FORM_HOST`, `TEAM2FORM_PORT`, `TEAM2FORM_MODE`,
`TEAM2FORM_PRESET`, `TEAM2FORM_NORMALIZE_WEIGHTS`, and
`TEAM2FORM_MAX_CANDIDATE_TEAMS`. Formation is capped at `10000` candidate teams
unless `TEAM2FORM_MAX_CANDIDATE_TEAMS=none` is set.

## HTTP smoke check

```bash
node ../scripts/http_smoke_gleam.mjs
```
