# team2form_gleam

Minimal Gleam port of the Python `team2form` project.

## Scope (first pass)

- Core domain models and validation
- Team quality scoring
- Exact (simple) team formation search
- CLI wrapper (Node)
- HTTP API wrapper (Node)

This pass intentionally keeps the implementation simple.

## Known gaps vs Python

- No advanced candidate-shortlisting heuristics.
- No greedy+improve hybrid pipeline from Python; this version uses a straightforward exact search.
- No caching/performance micro-optimizations yet.

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

## Parity check against Python

```bash
uv run python ../scripts/compare_gleam.py
```

## API

```bash
node scripts/server.mjs
# GET  http://127.0.0.1:8000/v1/help
# POST http://127.0.0.1:8000/v1/teamQuality
# POST http://127.0.0.1:8000/v1/teamFormation
```
