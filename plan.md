# Gleam Cutover Plan

## Goal

Ditch Python from the hot path immediately and make the Gleam/JavaScript runtime
the production implementation for team quality and team formation.

Python remains only as a short-lived reference/test oracle and rollback artifact
until cutover confidence is high enough to delete it.

## Recommended Answers to the Design Questions

1. **What are we replacing first?**
   - Recommended: replace the HTTP API and CLI execution path with Gleam/JS
     first. Do not wait to redesign packaging.

2. **Do we need byte-identical JSON?**
   - Recommended: no. Require schema-compatible JSON and semantically equal
     values. Field order and `1` vs `1.0` are not API contracts.

3. **Do we keep FastAPI?**
   - Recommended: no for production. A Python wrapper would keep Python
     startup/runtime overhead and defeat the goal. Keep FastAPI only as
     rollback/reference.

4. **What server should production run?**
   - Recommended: `node gleam/scripts/server.mjs`, backed by compiled Gleam
     modules, with endpoint compatibility for `/v1/help`, `/v1/teamQuality`, and
     `/v1/teamFormation`.

5. **How do mode/preset/candidate-cap settings get configured?**
   - Recommended: environment variables for server defaults:
     - `TEAM2FORM_HOST`, default `127.0.0.1`
     - `TEAM2FORM_PORT`, default `8000`
     - `TEAM2FORM_MODE`, default `compat`
     - `TEAM2FORM_PRESET`, default unset/none
     - `TEAM2FORM_NORMALIZE_WEIGHTS`, default `false`
     - `TEAM2FORM_MAX_CANDIDATE_TEAMS`, default `10000`; use `none` for uncapped

6. **Do request query params override server defaults?**
   - Recommended: not in the first cutover unless existing clients already
     depend on it. Preserve current Python API behavior, where `create_app(...)`
     config controls defaults.

7. **How strict should validation/error parity be?**
   - Recommended: preserve status-code shape (`400 {"detail": "..."}`) and valid
     payload behavior. Do not require exact Pydantic error messages.

8. **What about the Python package API?**
   - Recommended: freeze it during cutover. Do not promise Python library API
     performance. If someone imports `team2form`, they are on legacy/reference
     code until deletion.

9. **What is the rollback story?**
   - Recommended: keep the previous Python service command deployable for one
     release. Rollback is switching process command back to
     `uv run team2form-api`.

10. **What proves we can cut over?**
    - Recommended: pass Gleam tests, Python-vs-Gleam parity script, HTTP smoke
      tests against the Node server, and benchmark showing Gleam faster on
      example payloads.

## Implementation Steps

### Phase 1 — Harden the Gleam/Node server

- Update `gleam/scripts/server.mjs` to:
  - read host/port/mode/preset/normalize/max-candidate config from env;
  - use `quality_from_json_with_mode_preset` and
    `form_from_json_with_mode_preset` so mode/preset parsing happens once at
    startup;
  - default team formation cap to `10000`, matching the Python API safety
    default;
  - handle malformed JSON/runtime errors as `400 {"detail": ...}`;
  - return `404 {"detail":"Not found"}` for unknown routes;
  - optionally reject oversized request bodies with `413` if needed.

### Phase 2 — Add HTTP parity smoke tests

- Add a small Node or Python smoke script that starts the Node server and
  checks:
  - `GET /v1/help` returns `{"name":"Edu2com","version":"0.1.0"}`;
  - `POST /v1/teamQuality` with `examples/team-quality.json` matches Python
    semantically;
  - `POST /v1/teamFormation` with `examples/team-formation.json` matches Python
    semantically;
  - insufficient headcount returns HTTP 400 with `detail` containing
    `insufficient
 headcount`.

### Phase 3 — Switch deployment/runtime commands

- Build before deploy:

```bash
cd gleam
gleam build
```

- Production command:

```bash
node gleam/scripts/server.mjs
```

- CLI command for direct use:

```bash
node gleam/scripts/cli.mjs quality examples/team-quality.json --mode compat --preset
live_compat
node gleam/scripts/cli.mjs form examples/team-formation.json --mode compat --preset
live_compat
```

### Phase 4 — Keep Python as oracle briefly

- Keep these gates in CI/local release checks:

```bash
cd gleam && gleam check && gleam test
cd ..
uv run python scripts/compare_gleam.py
uv run python /tmp/bench_examples.py  # or move this into scripts/
```

- Python is not served in production after this phase.

### Phase 5 — Delete Python once stable

After at least one stable production window:

- remove FastAPI server entrypoint;
- remove Python scoring/formation implementation;
- keep only comparison fixtures if useful;
- update README/install/deploy docs to Node/Gleam-first.

## Immediate Cutover Checklist

- [ ] Patch `gleam/scripts/server.mjs` for env config and pre-parsed
      mode/preset.
- [ ] Confirm default formation cap is `10000` in Node server.
- [ ] Run `cd gleam && gleam build && gleam test`.
- [ ] Run `uv run python scripts/compare_gleam.py`.
- [ ] Run example HTTP smoke tests against `node gleam/scripts/server.mjs`.
- [ ] Change deployment command from Python/FastAPI to Node server.
- [ ] Keep Python command documented as rollback only.

## Risks

- **Validation messages differ from Pydantic.** Accept this unless clients rely
  on exact error text.
- **JSON field ordering differs.** Accept this; clients should parse JSON.
- **Node server lacks FastAPI middleware features.** Add only what production
  actually uses: CORS, body limits, health checks, logging.
- **Packaging may still be Python-oriented.** Do not block cutover on perfect
  packaging; run Node directly first.

## Decision

Proceed with a direct Gleam/Node production cutover. The Python implementation
becomes a temporary reference and rollback path, not part of the serving path.
