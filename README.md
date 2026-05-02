# team2form 🧩

A local reimplementation of the Edu2Com team formation model. Scores teams, forms them, and doesn't phone home.

**Two modes:**
- `compat` — mirrors the live Edu2Com endpoint
- `paper` — closer to the published scoring ideas

**Stack:** `gleam` · `node`

## Install
```bash
gleam build
```

## Test
```bash
gleam check
gleam test
node scripts/http_smoke_gleam.mjs
```

## CLI

```bash
# score a team
gleam build
node scripts/cli.mjs quality examples/team-quality.json --mode compat --preset live_compat

# form teams
node scripts/cli.mjs form examples/team-formation.json --mode compat --preset live_compat

# go fast (approximate) on large inputs
node scripts/cli.mjs form examples/team-formation.json --max-candidate-teams 10000
```

## Weight presets

| preset | α | β | γ | δ |
|---|---|---|---|---|
| `live_compat` | 0.3 | 0.3 | 0.2 | 0.2 |
| `docs_recommended` | 0.4 | 0.3 | 0.2 | 0.1 |
| `paper_balanced` | 0.25 | 0.25 | 0.25 | 0.25 |

## API

```bash
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
