# team2form 🧩

A local team formation model. Scores teams, forms them, and doesn't phone home.

**Two modes:**
- `compat` — compatibility-oriented scoring
- `paper` — closer to the published scoring ideas

**Stack:** `gleam` on Erlang/BEAM

## Install
```bash
gleam build
```

## Test

The project targets Erlang by default. `gleam_json` requires OTP 27+, so on Fedora systems with OTP 26 use the containerized check:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD":/app:Z -w /app \
  ghcr.io/gleam-lang/gleam:nightly-erlang \
  sh -lc 'gleam check && gleam test'
```

## Weight presets

| preset | α | β | γ | δ |
|---|---|---|---|---|
| `live_compat` | 0.3 | 0.3 | 0.2 | 0.2 |
| `docs_recommended` | 0.4 | 0.3 | 0.2 | 0.1 |
| `paper_balanced` | 0.25 | 0.25 | 0.25 | 0.25 |

## API

Run from the Gleam container without building an image:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e HOST=0.0.0.0 \
  -p 127.0.0.1:8000:8000 \
  -v "$PWD":/app:Z -w /app \
  ghcr.io/gleam-lang/gleam:nightly-erlang \
  sh -lc 'gleam run -m team2form_gleam/api'
```

Or build the deployable API image:

```bash
docker build -t team2form-api .
docker run --rm -e HOST=0.0.0.0 -p 127.0.0.1:8000:8000 team2form-api
```

The server listens on `HOST` and `PORT`. `HOST` defaults to `127.0.0.1` for local runs; set `HOST=0.0.0.0` only when you intentionally need network/container access. Docker examples set `HOST=0.0.0.0` for container reachability but publish only on host localhost. `PORT` defaults to `8000` and invalid values fail startup instead of falling back silently.

| method | path |
|---|---|
| `GET` | `/v1/help` |
| `POST` | `/v1/teamQuality` |
| `POST` | `/v1/teamFormation` |

```bash
curl -sS http://127.0.0.1:8000/v1/help
curl -sS -X POST http://127.0.0.1:8000/v1/teamQuality \
  --data-binary @examples/team-quality.json \
  -H 'content-type: application/json'
curl -sS -X POST http://127.0.0.1:8000/v1/teamFormation \
  --data-binary @examples/team-formation.json \
  -H 'content-type: application/json'
```

## Formation Search

Formation responses include search metadata:

```json
{
  "teams": [],
  "search": {
    "mode": "interactive",
    "exact": false,
    "maxCandidateTeams": 10000
  }
}
```
