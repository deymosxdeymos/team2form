# team2form 🧩

A local team formation model. Scores teams, forms them, and doesn't phone home.

**Two modes:**
- `compat` — compatibility-oriented scoring
- `paper` — closer to the published scoring ideas

**Stack:** `gleam` on Erlang/BEAM

## Running

Run the API locally:

```bash
nix develop
gleam run -m team2form_gleam/api
```

Or with Docker:

```bash
docker build -t team2form-api .
docker run --rm -e HOST=0.0.0.0 -p 127.0.0.1:8000:8000 team2form-api
```

The server listens on `HOST` and `PORT`. `HOST` defaults to `127.0.0.1`;
Docker uses `HOST=0.0.0.0` so the container can receive traffic. `PORT`
defaults to `8000`.

Set `API_KEY` to require bearer authentication for `/v1/*`. `/healthz` is
always unauthenticated.

## API

| method | path |
|---|---|
| `GET` | `/healthz` |
| `GET` | `/v1/help` |
| `POST` | `/v1/teamQuality` |
| `POST` | `/v1/teamFormation` |

Example requests:

```bash
curl -sS http://127.0.0.1:8000/v1/help

curl -sS -X POST http://127.0.0.1:8000/v1/teamQuality \
  --data-binary @examples/team-quality.json \
  -H 'content-type: application/json'

curl -sS -X POST http://127.0.0.1:8000/v1/teamFormation \
  --data-binary @examples/team-formation.json \
  -H 'content-type: application/json'
```

With `API_KEY` set:

```bash
curl -sS http://127.0.0.1:8000/v1/help \
  -H 'authorization: Bearer test-secret'
```

## Weight presets

| preset | α | β | γ | δ |
|---|---|---|---|---|
| `live_compat` | 0.3 | 0.3 | 0.2 | 0.2 |
| `docs_recommended` | 0.4 | 0.3 | 0.2 | 0.1 |
| `paper_balanced` | 0.25 | 0.25 | 0.25 | 0.25 |

## Development

```bash
nix develop
gleam check
gleam test
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
